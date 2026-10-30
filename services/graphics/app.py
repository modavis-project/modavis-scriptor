"""Local research image service. SQLite audit log and original evidence survive restarts."""
import csv
import hashlib
import io
import json
import os
import shutil
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, JSONResponse

from corpus import Catalogue
from annotations import number_anchor
from pipeline import normalize, process_image, sha256
from database import SCHEMA_VERSION, connect, migrate
from evidence import IntegrityError, verified_bytes, verified_copy, verify_file
from storage import store_lock, service_owner, artifact_folder, verified_result, admission_folder, clear_abandoned_admissions, sync_directory
from delivery import artifact_response, temporary_path, TemporaryFileResponse
from contracts import Config, Review, HealthResponse, RunListResponse, RunResponse, QueuedRunResponse, GraphicsResult, ErrorResponse
import jobs

ROOT = Path(__file__).parent
DATA = Path(os.environ.get("GRAPHICS_DATA", ROOT / "data"))
DATA.mkdir(parents=True, exist_ok=True)
POOL = ThreadPoolExecutor(max_workers=1)
CATALOGUE = Catalogue()


def now():
    return datetime.now(timezone.utc).isoformat()


def connection():
    return connect(DATA / "graphics.sqlite")


def execute(run_id):
    return jobs.execute(run_id, DATA, connection, process_image, CATALOGUE, now)


def schedule(run_id):
    try:
        POOL.submit(execute, run_id)
    except RuntimeError as error:
        with store_lock(DATA), connection() as db:
            db.execute("UPDATE runs SET status='failed',error=? WHERE id=? AND status='queued'", ("Worker could not start; retry this run: " + str(error)[:500], run_id))
        raise HTTPException(503, "Worker unavailable; the saved source is retained as a failed run for retry") from error


@asynccontextmanager
async def lifespan(_app):
    with service_owner(DATA):
        with store_lock(DATA, exclusive=True):
            with connection() as db:
                migrate(db)
                seed = "example-organ-stops-v1"
                if not db.execute("SELECT 1 FROM runs WHERE id=?", (seed,)).fetchone():
                    folder = DATA / seed
                    folder.mkdir(exist_ok=True)
                    shutil.copyfile(ROOT / "example/Organ-stops.jpg", folder / "original")
                    metadata = json.loads((ROOT / "example/source.json").read_text(encoding="utf-8"))
                    db.execute("INSERT INTO runs(id,title,project,status,created_at,metadata,config,source_sha256) VALUES(?,?,?,?,?,?,?,?)", (seed,metadata["title"],"Organ-stop images","queued",now(),json.dumps(metadata),Config().model_dump_json(),sha256(ROOT / "example/Organ-stops.jpg")))
                    snapshot = ROOT / "example/processed"
                    if (snapshot / "result.json").exists():
                        manifest = json.loads((ROOT / "example/seed-manifest.json").read_text(encoding="utf-8"))
                        assert manifest["run_id"] == seed
                        for name, digest in manifest["files"].items():
                            assert Path(name).name == name and sha256(snapshot/name) == digest, "Frozen example checksum mismatch"
                            shutil.copyfile(snapshot/name,folder/name)
                        frozen = json.loads((folder/"result.json").read_text(encoding="utf-8"))
                        db.execute("UPDATE runs SET status='completed',config=?,result_sha256=?,source_sha256=? WHERE id=?", (json.dumps(frozen["paradata"]["config"]),sha256(folder/"result.json"),frozen["image"]["sha256"],seed))
            pending = jobs.recover(DATA, connection, ROOT)
            with connection() as db:
                known = {r[0] for r in db.execute("SELECT id FROM runs")}
            clear_abandoned_admissions(DATA, known)
        for run_id in pending:
            schedule(run_id)
        try:
            yield
        finally:
            POOL.shutdown(wait=True, cancel_futures=True)


app = FastAPI(title="MODAVIS Scriptor API", version="0.1.0", lifespan=lifespan,
              description="Local-only image OCR, MODAVIS advisory retrieval, append-only human review. No automatic corpus substitutions.",
              responses={code: {"model": ErrorResponse} for code in [400, 404, 409, 413, 422, 429, 500, 503]})


@app.exception_handler(TimeoutError)
async def busy_store(_request, error):
    return JSONResponse({"detail": str(error)}, status_code=503)


@app.middleware("http")
async def local_safety(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return Response("Cross-origin writes are not allowed", status_code=403)
        if int(request.headers.get("content-length", "0")) > 22 * 1024 * 1024:
            return Response("Upload exceeds 20 MiB plus form metadata", status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


def run_record(run_id):
    with connection() as db:
        row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Run not found")
    return dict(row)


def result_for(run_id):
    row = run_record(run_id)
    if row["status"] != "completed":
        raise HTTPException(409, "Run is not completed")
    try:
        result = verified_result(DATA, row, ROOT)
        if row["source_sha256"] is None:
            with store_lock(DATA), connection() as db:
                db.execute("UPDATE runs SET source_sha256=? WHERE id=? AND source_sha256 IS NULL", (result["image"]["sha256"], run_id))
        return result
    except (IntegrityError, OSError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(409, f"Evidence integrity check failed: {error}. Restore evidence before continuing.") from error


def materialize(run_id):
    result = result_for(run_id)
    with connection() as db:
        events = [dict(r) for r in db.execute("SELECT * FROM review_events WHERE run_id=? ORDER BY id", (run_id,))]
    latest = {}
    for event in events:
        event["payload"] = json.loads(event["payload"])
        latest[event["region_id"]] = event
    for region in result["regions"]:
        event = latest.get(region["id"])
        review = event["payload"] if event else None
        region["review"] = event
        region["version"] = event["version"] if event else 0
        region["effective"] = {k: review[k] for k in ["name", "specification", "kind", "division"]} if review and review["action"] == "accept" else region["parsed"]
        region["status"] = review["action"] if review else "unreviewed"
    result["review_events"] = events
    result["immutable_result_sha256"] = run_record(run_id)["result_sha256"]
    result["markdown"] = markdown(result)
    result["raw_markdown"] = markdown(result, raw=True)
    return result


def cell(value):
    value = str(value or "").replace("\\", "\\\\").replace("\n", " / ").replace("<", "&lt;").replace(">", "&gt;")
    for character in "|[]!*_`":
        value = value.replace(character,"\\"+character)
    return value


def markdown(result, raw=False):
    text = f"# {cell(result['metadata'].get('title', 'Graphics OCR'))}\n\n"
    text += "## " + ("Unveränderte OCR und regelbasierte Feldtrennung" if raw else "Aktueller Arbeitsstand (ungeprüfte OCR bleibt erhalten)") + "\n\n"
    text += "| Nr. | Bildlesung / Name | Angabe (uninterpretiert) | Typ | Werk (nur manuell) | Prüfstatus |\n| --- | --- | --- | --- | --- | --- |\n"
    for r in result["regions"]:
        p = r["parsed"] if raw else r["effective"]
        text += "| " + " | ".join(cell(v) for v in [r["number"],p["name"],p["specification"],p["kind"],p["division"],"raw" if raw else r["status"]]) + " |\n"
    if raw:
        text += "\n## Vollständige OCR-Zeichenfolgen\n\n"
        for r in result["regions"]:
            text += f"### Region {r['number']}\n\n" + cell(r["raw_text"]) + "\n\n"
    text += "\n## Quellen und Verarbeitung\n\n" + cell(result["metadata"].get("attribution", "Attribution not supplied")) + "\n\n"
    for k in ["source_url", "license_url", "changes"]:
        if result["metadata"].get(k):
            text += cell(result["metadata"][k]) + "\n\n"
    text += f"Run: {result['run_id']} · Original-SHA-256: {result['image']['sha256']}\n\n"
    if result["paradata"]["corpus"]:
        text += "Korpus: Dominik Ukolov, MODAVIS POD 1.5.0, DOI: 10.5281/zenodo.22234059, CC BY 4.0. Nur beratend; kein Identitätsnachweis.\n"
    return text


@app.get("/health", response_model=HealthResponse)
def health():
    return {"ok": True, "corpus": CATALOGUE.report, "local_only": True, "database_schema": SCHEMA_VERSION,
            "disposable_test_instance": os.environ.get("SCRIPTOR_DISPOSABLE_TEST") == "1"}


@app.get("/runs", response_model=RunListResponse)
def runs():
    with connection() as db:
        return {"runs": [dict(r) for r in db.execute("SELECT id,title,project,status,created_at,parent_id,error FROM runs ORDER BY created_at DESC")], "corpus": CATALOGUE.report}


@app.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str):
    row = run_record(run_id)
    return {"run": {**row, "config": json.loads(row["config"]), "metadata": json.loads(row["metadata"])}, "result": materialize(run_id) if row["status"] == "completed" else None}


def admit_run(run_id, folder, title, project, metadata, config, source_digest, parent_id=None):
    """Reserve capacity and insert together; callers own this newly created UUID folder."""
    try:
        with store_lock(DATA), connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0] >= 10:
                raise HTTPException(429, "Processing queue is full; wait for a run to finish")
            db.execute("INSERT INTO runs(id,title,project,status,created_at,metadata,config,parent_id,source_sha256) VALUES(?,?,?,?,?,?,?,?,?)", (run_id, title, project, "queued", now(), metadata, config, parent_id, source_digest))
    except Exception:
        # Never touch a parent folder or any previously admitted run on rejection.
        shutil.rmtree(folder)
        raise
    try:
        (folder / ".admission.json").unlink(missing_ok=True)
    except OSError:
        pass  # A committed reservation is valid; startup clears a leftover marker.


@app.post("/runs", status_code=202, response_model=QueuedRunResponse)
async def create_run(file: UploadFile = File(...), title: str = Form(..., max_length=200), project: str = Form("Organ-stop images", max_length=200), config: str = Form("{}", max_length=20000), metadata: str = Form("{}", max_length=20000)):
    with connection() as db:
        if db.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0] >= 10:
            raise HTTPException(429,"Processing queue is full; wait for a run to finish")
    try:
        settings = Config.model_validate_json(config)
        meta = json.loads(metadata)
        if not isinstance(meta, dict) or any(not isinstance(v, str) or len(v)>4000 for v in meta.values()):
            raise ValueError("Metadata must contain string fields up to 4000 characters.")
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if not title.strip() or not project.strip():
        raise HTTPException(422, "Title and project must not be empty")
    body = await file.read(20 * 1024 * 1024 + 1)
    await file.close()
    if len(body) > 20 * 1024 * 1024:
        raise HTTPException(413, "Image limit is 20 MiB")
    run_id = uuid.uuid4().hex
    with store_lock(DATA):
        folder = admission_folder(DATA, run_id)
        with (folder / "original").open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        sync_directory(folder)
    try:
        normalize(folder / "original", folder / ".validation.png")
        (folder / ".validation.png").unlink()
    except Exception as error:
        # Only this newly created, validated UUID directory belongs to this failed upload.
        shutil.rmtree(folder)
        raise HTTPException(422, f"Invalid image: {error}") from error
    meta.update(title=title.strip(), original_filename=Path(file.filename or "image").name)
    admit_run(run_id, folder, title.strip(), project.strip(), json.dumps(meta), settings.model_dump_json(), hashlib.sha256(body).hexdigest())
    schedule(run_id)
    return {"id": run_id, "status": "queued"}


@app.post("/runs/{run_id}/rerun", status_code=202, response_model=QueuedRunResponse)
def rerun(run_id: str, config: Config):
    parent = run_record(run_id)
    if parent["status"] in {"queued", "running"}:
        raise HTTPException(409, "Processing is still queued or running; wait for it to finish before reprocessing")
    if parent["status"] == "completed":
        source_digest = result_for(run_id)["image"]["sha256"]
    else:
        source_digest = parent["source_sha256"]
        if not source_digest:
            raise HTTPException(409, "This legacy failed run has no preserved source checksum; re-upload the original image to retry safely")
    try:
        original = verified_bytes(DATA / run_id, "original", source_digest)
    except IntegrityError as error:
        raise HTTPException(409, str(error)) from error
    child = uuid.uuid4().hex
    with store_lock(DATA):
        folder = admission_folder(DATA, child)
        with (folder / "original").open("xb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        sync_directory(folder)
    admit_run(child, folder, parent["title"], parent["project"], parent["metadata"], config.model_dump_json(), source_digest, run_id)
    schedule(child)
    return {"id": child, "status": "queued"}


@app.get("/runs/{run_id}/image")
def image(run_id: str):
    result = result_for(run_id)
    try:
        return artifact_response(artifact_folder(DATA, run_record(run_id)), "image.png", result["image"]["normalized_sha256"], "image/png")
    except IntegrityError as error:
        raise HTTPException(409, str(error)) from error


@app.get("/runs/{run_id}/regions/{region_id}/crop")
def crop(run_id: str, region_id: str):
    result = result_for(run_id)
    region = next((r for r in result["regions"] if r["id"] == region_id), None)
    if region is None:
        raise HTTPException(404,"Region not found")
    try:
        return artifact_response(artifact_folder(DATA, run_record(run_id)), f"{region_id}-crop.png", region["crop_sha256"], "image/png")
    except IntegrityError as error:
        raise HTTPException(409, str(error)) from error


@app.patch("/runs/{run_id}/regions/{region_id}/review", response_model=GraphicsResult)
def review(run_id: str, region_id: str, decision: Review):
    result = result_for(run_id)
    region = next((r for r in result["regions"] if r["id"] == region_id),None)
    if not region:
        raise HTTPException(404,"Region not found")
    if decision.candidate_id is not None and not any(c["id"] == decision.candidate_id for c in region["candidates"]):
        raise HTTPException(422,"Candidate does not belong to this region")
    with store_lock(DATA), connection() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT coalesce(max(version),0) FROM review_events WHERE run_id=? AND region_id=?",(run_id,region_id)).fetchone()[0]
        if decision.expected_version != current:
            raise HTTPException(409,"Review changed. Reload before saving; no decision was overwritten.")
        db.execute("INSERT INTO review_events(run_id,region_id,version,payload,created_at) VALUES(?,?,?,?,?)",(run_id,region_id,current+1,decision.model_dump_json(),now()))
    return materialize(run_id)


def annotated_svg(result):
    w,h = result["image"]["width"],result["image"]["height"]
    # The SVG references a sibling image supplied in the bundle; no remote request.
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w+100}" height="{h+100}" viewBox="-70 -50 {w+100} {h+100}">', '<title>Lokalisierte Bildregionen; ungeprüfte Detektionen</title>',f'<image href="image.png" width="{w}" height="{h}"/>']
    for r in result["regions"]:
        x,y,x2,y2=r["bbox"]
        label_x,label_y=number_anchor(r,result["regions"],h)
        svg += [f'<rect x="{x}" y="{y}" width="{x2-x}" height="{y2-y}" fill="none" stroke="#00695c" stroke-width="4"/>',f'<text x="{label_x-9}" y="{label_y+3}" text-anchor="end" fill="#00695c" font-size="30" font-family="sans-serif">{r["number"]}</text>']
    svg.append(f'<metadata>{escape(json.dumps(result["metadata"],ensure_ascii=False))}</metadata></svg>')
    return "".join(svg)


def csv_data(result):
    stream=io.StringIO(); writer=csv.writer(stream)
    writer.writerow(["run_id","region_id","raw_text","name","specification_literal","kind","division","review_status","bbox_xyxy","source_sha256"])
    for r in result["regions"]:
        p=r["effective"]
        # CSV formula-injection protection; JSON retains exact literal values.
        values=[result["run_id"],r["id"],r["raw_text"],p["name"],p["specification"],p["kind"],p["division"],r["status"],json.dumps(r["bbox"]),result["image"]["sha256"]]
        writer.writerow(["'"+v if v.startswith(("=","+","-","@","\t","\r")) else v for v in values])
    return stream.getvalue()


@app.get("/runs/{run_id}/export")
def export(run_id: str, format: Literal["json","markdown","raw-markdown","csv","bundle"]="json"):
    result=materialize(run_id)
    data=json.dumps(result,ensure_ascii=False,indent=2)
    if format == "bundle":
        path = temporary_path(".zip")
        try:
            with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as archive:
                for name,value in {"reviewed.json":data,"reviewed.md":result["markdown"],"raw.md":result["raw_markdown"],"table.csv":csv_data(result),"regions.svg":annotated_svg(result),"source.json":json.dumps(result["metadata"],ensure_ascii=False,indent=2),"integrity.json":json.dumps(result["integrity"],ensure_ascii=False,indent=2)}.items():
                    archive.writestr(name,value)
                folder=artifact_folder(DATA, run_record(run_id))
                files = {**result["integrity"]["verified_files"], "result.json": result["immutable_result_sha256"]}
                try:
                    for name, digest in files.items():
                        with archive.open(name, "w") as destination:
                            verified_copy(folder, name, digest, destination)
                except IntegrityError as error:
                    raise HTTPException(409, str(error)) from error
                archive.writestr("README.txt","MODAVIS Scriptor research export. Original evidence and immutable result.json are separate from reviewed.json. regions.svg references image.png. Box numbers are left of each upper-left corner. OCR is not ground truth. CSV has spreadsheet formula protection; JSON preserves literals. Credit and licensing are in source.json and reviewed.json. integrity.json describes verification coverage; legacy OCR artifacts without recorded checksums are excluded. Adapted example photograph: Tucker501, CC BY-SA 4.0; MODAVIS data arrangement: CC BY 4.0.\n")
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return TemporaryFileResponse(path, media_type="application/zip", filename=f"{run_id}-research.zip")
    media,ext,value={"json":("application/json","json",data),"markdown":("text/markdown","md",result["markdown"]),"raw-markdown":("text/markdown","raw.md",result["raw_markdown"]),"csv":("text/csv","csv",csv_data(result))}[format]
    return Response(value,media_type=media,headers={"Content-Disposition":f'attachment; filename="{run_id}.{ext}"'})
