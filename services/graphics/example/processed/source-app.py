"""Local research image service. SQLite audit log and original evidence survive restarts."""
import csv
import io
import json
import os
import shutil
import sqlite3
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, model_validator

from corpus import Catalogue
from annotations import number_anchor
from pipeline import normalize, process_image, sha256

ROOT = Path(__file__).parent
DATA = Path(os.environ.get("GRAPHICS_DATA", ROOT / "data"))
DATA.mkdir(parents=True, exist_ok=True)
POOL = ThreadPoolExecutor(max_workers=1)
LOCK = threading.Lock()
CATALOGUE = Catalogue()


def now():
    return datetime.now(timezone.utc).isoformat()


def connection():
    db = sqlite3.connect(DATA / "graphics.sqlite", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


class Config(BaseModel):
    mode: Literal["graphics", "organ_stops"] = "organ_stops"
    model: Literal["best", "fast"] = "best"
    language: Literal["eng", "deu", "eng+deu", "deu+eng"] = "eng+deu"
    brightness: int = Field(135, ge=60, le=240)
    saturation: int = Field(60, ge=10, le=160)
    binarization: Literal["fixed", "otsu", "none"] = "fixed"
    ink_threshold: int = Field(150, ge=50, le=230)
    min_area: float = Field(.0006, ge=.0001, le=.05)
    match_threshold: int = Field(65, ge=50, le=100)
    regions: list[list[float]] = Field(default_factory=list, max_length=120)

    @model_validator(mode="after")
    def valid_regions(self):
        for box in self.regions:
            if len(box) != 4 or not all(0 <= v <= 1 for v in box) or box[2] < .005 or box[3] < .005 or box[0]+box[2] > 1.000001 or box[1]+box[3] > 1.000001:
                raise ValueError("Each region is normalized [x,y,width,height], inside the image, at least 0.005 wide/high.")
        return self


class Review(BaseModel):
    action: Literal["accept", "retain", "defer"]
    reviewer: str = Field(min_length=2, max_length=120)
    rationale: str = Field(min_length=12, max_length=2000)
    name: str = Field("", max_length=300)
    specification: str = Field("", max_length=100)
    kind: Literal["stop", "coupler", "division", "accessory", "unknown", "not_text"] = "unknown"
    division: str = Field("", max_length=100)
    candidate_id: int | None = None
    expected_version: int = Field(0, ge=0)

    @model_validator(mode="after")
    def meaningful(self):
        if len(self.reviewer.strip()) < 2 or len(self.rationale.strip()) < 12:
            raise ValueError("Provide reviewer identity and an image-based rationale (12 characters minimum).")
        if self.action == "accept" and not self.name.strip() and self.kind != "not_text":
            raise ValueError("A reviewed reading cannot be empty unless the region is marked not_text.")
        return self


def execute(run_id):
    folder = DATA / run_id
    with connection() as db:
        row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        db.execute("UPDATE runs SET status='running',error=NULL WHERE id=?", (run_id,))
    try:
        result = process_image(folder, json.loads(row["config"]), CATALOGUE)
        result["metadata"] = json.loads(row["metadata"])
        result["run_id"] = run_id
        (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        with connection() as db:
            db.execute("UPDATE runs SET status='completed',result_sha256=? WHERE id=?", (sha256(folder / "result.json"),run_id))
    except Exception as error:
        with connection() as db:
            db.execute("UPDATE runs SET status='failed',error=? WHERE id=?", (str(error)[:1000],run_id))


@asynccontextmanager
async def lifespan(_app):
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,title TEXT NOT NULL,project TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,metadata TEXT NOT NULL,config TEXT NOT NULL,parent_id TEXT,error TEXT,result_sha256 TEXT);
        CREATE TABLE IF NOT EXISTS review_events(id INTEGER PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id),region_id TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(run_id,region_id,version));
        CREATE INDEX IF NOT EXISTS review_lookup ON review_events(run_id,region_id,version);
        CREATE TRIGGER IF NOT EXISTS review_no_update BEFORE UPDATE ON review_events BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS review_no_delete BEFORE DELETE ON review_events BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;
        """)
        seed = "example-organ-stops-v1"
        if not db.execute("SELECT 1 FROM runs WHERE id=?", (seed,)).fetchone():
            folder = DATA / seed
            folder.mkdir(exist_ok=True)
            shutil.copyfile(ROOT / "example/Organ-stops.jpg", folder / "original")
            metadata = json.loads((ROOT / "example/source.json").read_text())
            db.execute("INSERT INTO runs(id,title,project,status,created_at,metadata,config) VALUES(?,?,?,?,?,?,?)", (seed,metadata["title"],"Organ-stop images","queued",now(),json.dumps(metadata),Config().model_dump_json()))
            snapshot = ROOT / "example/processed"
            if (snapshot / "result.json").exists():
                manifest = json.loads((ROOT / "example/seed-manifest.json").read_text())
                assert manifest["run_id"] == seed
                for name, digest in manifest["files"].items():
                    assert Path(name).name == name and sha256(snapshot/name) == digest, "Frozen example checksum mismatch"
                    shutil.copyfile(snapshot/name,folder/name)
                frozen = json.loads((folder/"result.json").read_text())
                db.execute("UPDATE runs SET status='completed',config=?,result_sha256=? WHERE id=?", (json.dumps(frozen["paradata"]["config"]),sha256(folder/"result.json"),seed))
        # Supplement an already-seeded example with verified source snapshots, never replace evidence.
        manifest_path = ROOT / "example/seed-manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            folder = DATA / seed
            if (folder/"result.json").exists() and sha256(folder/"result.json") == manifest["files"]["result.json"]:
                for name,digest in manifest["files"].items():
                    if name.startswith("source-") and not (folder/name).exists():
                        assert Path(name).name == name and sha256(ROOT/"example/processed"/name) == digest
                        shutil.copyfile(ROOT/"example/processed"/name,folder/name)
        pending = [r[0] for r in db.execute("SELECT id FROM runs WHERE status IN ('queued','running')")]
        db.execute("UPDATE runs SET status='queued' WHERE status='running'")
    for run_id in pending:
        POOL.submit(execute, run_id)
    yield
    POOL.shutdown(wait=True)


app = FastAPI(title="MODAVIS Scriptor API", version="0.1.0", lifespan=lifespan,
              description="Local-only image OCR, MODAVIS advisory retrieval, append-only human review. No automatic corpus substitutions.")


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
    path = DATA / run_id / "result.json"
    if sha256(path) != row["result_sha256"]:
        raise HTTPException(409, "Immutable result checksum mismatch. Restore evidence before continuing.")
    return json.loads(path.read_text())


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


@app.get("/health")
def health():
    return {"ok": True, "corpus": CATALOGUE.report, "local_only": True}


@app.get("/runs")
def runs():
    with connection() as db:
        return {"runs": [dict(r) for r in db.execute("SELECT id,title,project,status,created_at,parent_id,error FROM runs ORDER BY created_at DESC")], "corpus": CATALOGUE.report}


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    row = run_record(run_id)
    return {"run": {**row, "config": json.loads(row["config"]), "metadata": json.loads(row["metadata"])}, "result": materialize(run_id) if row["status"] == "completed" else None}


@app.post("/runs", status_code=202)
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
    folder = DATA / run_id
    folder.mkdir()
    (folder / "original").write_bytes(body)
    try:
        normalize(folder / "original", folder / "image.png")
    except Exception as error:
        # Only this newly created, validated UUID directory belongs to this failed upload.
        shutil.rmtree(folder)
        raise HTTPException(422, f"Invalid image: {error}") from error
    meta.update(title=title.strip(), original_filename=Path(file.filename or "image").name)
    with connection() as db:
        db.execute("INSERT INTO runs(id,title,project,status,created_at,metadata,config) VALUES(?,?,?,?,?,?,?)", (run_id,title.strip(),project.strip(),"queued",now(),json.dumps(meta),settings.model_dump_json()))
    POOL.submit(execute,run_id)
    return {"id": run_id, "status": "queued"}


@app.post("/runs/{run_id}/rerun", status_code=202)
def rerun(run_id: str, config: Config):
    parent = run_record(run_id)
    with LOCK:
        with connection() as db:
            if db.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0] >= 10:
                raise HTTPException(429,"Processing queue is full")
        child = uuid.uuid4().hex
        folder = DATA / child
        folder.mkdir()
        shutil.copyfile(DATA / run_id / "original", folder / "original")
        with connection() as db:
            db.execute("INSERT INTO runs(id,title,project,status,created_at,metadata,config,parent_id) VALUES(?,?,?,?,?,?,?,?)", (child,parent["title"],parent["project"],"queued",now(),parent["metadata"],config.model_dump_json(),run_id))
        POOL.submit(execute,child)
    return {"id": child, "status": "queued"}


@app.get("/runs/{run_id}/image")
def image(run_id: str):
    run_record(run_id)
    path = DATA / run_id / "image.png"
    if not path.exists():
        raise HTTPException(409,"Image normalization is pending")
    return FileResponse(path,media_type="image/png")


@app.get("/runs/{run_id}/regions/{region_id}/crop")
def crop(run_id: str, region_id: str):
    if not any(r["id"] == region_id for r in result_for(run_id)["regions"]):
        raise HTTPException(404,"Region not found")
    return FileResponse(DATA / run_id / f"{region_id}-crop.png",media_type="image/png")


@app.patch("/runs/{run_id}/regions/{region_id}/review")
def review(run_id: str, region_id: str, decision: Review):
    result = result_for(run_id)
    region = next((r for r in result["regions"] if r["id"] == region_id),None)
    if not region:
        raise HTTPException(404,"Region not found")
    if decision.candidate_id is not None and not any(c["id"] == decision.candidate_id for c in region["candidates"]):
        raise HTTPException(422,"Candidate does not belong to this region")
    with connection() as db:
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
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,"w",zipfile.ZIP_DEFLATED) as archive:
            for name,value in {"reviewed.json":data,"reviewed.md":result["markdown"],"raw.md":result["raw_markdown"],"table.csv":csv_data(result),"regions.svg":annotated_svg(result),"source.json":json.dumps(result["metadata"],ensure_ascii=False,indent=2)}.items():
                archive.writestr(name,value)
            folder=DATA/run_id
            for path in folder.iterdir():
                if path.is_file():
                    archive.write(path,path.name)
            archive.writestr("README.txt","MODAVIS Scriptor research export. Original evidence and immutable result.json are separate from reviewed.json. regions.svg references image.png. Box numbers are left of each upper-left corner. OCR is not ground truth. CSV has spreadsheet formula protection; JSON preserves literals. Credit and licensing are in source.json and reviewed.json. Adapted example photograph: Tucker501, CC BY-SA 4.0; MODAVIS data arrangement: CC BY 4.0.\n")
        return Response(stream.getvalue(),media_type="application/zip",headers={"Content-Disposition":f'attachment; filename="{run_id}-research.zip"'})
    media,ext,value={"json":("application/json","json",data),"markdown":("text/markdown","md",result["markdown"]),"raw-markdown":("text/markdown","raw.md",result["raw_markdown"]),"csv":("text/csv","csv",csv_data(result))}[format]
    return Response(value,media_type=media,headers={"Content-Disposition":f'attachment; filename="{run_id}.{ext}"'})
