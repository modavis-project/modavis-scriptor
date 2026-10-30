#!/usr/bin/env python3
"""Collect pinned candidates, annotate blindly, adjudicate, and freeze reviewed gold."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import unicodedata
import urllib.parse
import urllib.request
import uuid

import score

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "evaluation/candidates.json"
WORKSPACE = ROOT / "evaluation-data"
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,100}")
SCHEMA = "modavis-scriptor.annotation-workspace/v1"
MAX_SOURCE = 20 * 1024 * 1024
USER_AGENT = "MODAVIS-Scriptor/0.1 evaluation preparation (https://github.com/modavis-project/modavis-scriptor)"


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def load(path):
    return json.loads(Path(path).read_bytes(), object_pairs_hook=score.unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON value")))


def file_digest(path, algorithm="sha256"):
    digest = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def publish_new(path, content):
    """Publish complete bytes atomically without replacing a previous submission."""
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary = path.parent / (".pending-" + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def nonempty(value, label, minimum=1, maximum=4000):
    score.require(isinstance(value, str) and minimum <= len(value.strip()) <= maximum, f"Invalid {label}")
    return value.strip()


def reviewer_key(value):
    return " ".join(unicodedata.normalize("NFC", nonempty(value, "reviewer", 2, 120)).casefold().split())


def catalog_at(path):
    catalog = load(path)
    score.require(catalog.get("schema") == "modavis-scriptor.candidate-set/v1", "Unknown candidate schema")
    score.require(catalog.get("status") == "unreviewed", "Candidates must remain explicitly unreviewed")
    score.require(isinstance(catalog.get("items"), list) and bool(catalog["items"]), "Candidate set is empty")
    ids, sources, filenames, groups = set(), set(), set(), {}
    for item in catalog["items"]:
        score.require(bool(SLUG.fullmatch(item.get("id", ""))), "Unsafe candidate identifier")
        score.require(item["id"] not in ids, "Duplicate candidate identifier")
        ids.add(item["id"])
        source = score.digest(item.get("source_sha256"), "source_sha256")
        score.require(source not in sources, "Duplicate source image")
        sources.add(source)
        score.require(bool(re.fullmatch(r"[a-f0-9]{40}", item.get("source_sha1", ""))), "Missing source SHA-1")
        score.require(type(item.get("source_bytes")) is int and 0 < item["source_bytes"] <= MAX_SOURCE, "Invalid source size")
        name = item.get("source_filename", "")
        score.require(bool(re.fullmatch(r"[a-z0-9-]+\.(?:jpg|jpeg|png|webp|tif|tiff)", name)), "Unsafe source filename")
        score.require(name not in filenames, "Duplicate source filename")
        filenames.add(name)
        url = urllib.parse.urlsplit(item.get("source_url", ""))
        score.require(url.scheme == "https" and url.hostname == "upload.wikimedia.org" and not url.username and not url.password,
                      "Candidate downloads must use Wikimedia HTTPS originals")
        rights = item.get("rights", {})
        for key in ("license", "attribution", "source_url", "license_url"):
            nonempty(rights.get(key), "rights." + key)
        score.require(rights["license"].startswith(("CC BY", "CC0", "Public domain")), "Unsupported candidate license")
        score.require(item.get("split") in {"development", "held_out"}, "Invalid candidate split")
        example = ROOT / "services/graphics/example/seed-manifest.json"
        if item["split"] == "held_out" and example.exists():
            score.require(source != load(example)["files"]["original"], "The tuned example cannot be held out")
        group = nonempty(item.get("group_id"), "source group")
        score.require(group not in groups or groups[group] == item["split"], "Source group leaks between splits")
        groups[group] = item["split"]
    return catalog


def catalog_digest(catalog):
    return hashlib.sha256(canonical(catalog)).hexdigest()


def ensure_workspace(workspace, catalog):
    workspace = Path(workspace).resolve()
    score.require(not (workspace / "graphics.sqlite").exists(), "An annotation workspace cannot be a research service data directory")
    marker = workspace / "workspace.json"
    expected = {"schema": SCHEMA, "catalog_sha256": catalog_digest(catalog)}
    if marker.exists():
        score.require(load(marker) == expected, "Workspace uses a different candidate catalog; use a separate workspace")
    else:
        if workspace.exists():
            score.require(set(p.name for p in workspace.iterdir()) <= {"sources"}, "Refusing to adopt an unrelated directory")
        workspace.mkdir(parents=True, mode=0o700, exist_ok=True)
        marker.write_bytes(canonical(expected))
    return workspace


@contextmanager
def workspace_lock(workspace):
    with (workspace / ".lock").open("a+b") as lock:
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                # Windows byte locks also prohibit reads by another process.
                # Inspect metadata so contention reaches our conflict handler.
                if os.fstat(lock.fileno()).st_size == 0:
                    lock.write(b"0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ValueError("Another annotation/collection/freeze process owns this workspace") from error
        else:
            import fcntl
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ValueError("Another annotation/collection/freeze process owns this workspace") from error
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def verified_source(workspace, item):
    path = workspace / "sources" / item["source_filename"]
    score.require(path.is_file() and not path.is_symlink(), f"Missing regular source: {item['id']}; run collect")
    score.require(path.stat().st_size == item["source_bytes"] and file_digest(path) == item["source_sha256"]
                  and file_digest(path, "sha1") == item["source_sha1"], f"Source checksum mismatch: {item['id']}")
    return path


def collect(workspace, catalog):
    directory = workspace / "sources"
    directory.mkdir(exist_ok=True)
    for item in catalog["items"]:
        destination = directory / item["source_filename"]
        if destination.exists():
            verified_source(workspace, item)
            continue
        temporary = directory / (".download-" + uuid.uuid4().hex)
        try:
            request = urllib.request.Request(item["source_url"], headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open("xb") as output:
                score.require(urllib.parse.urlsplit(response.url).hostname == "upload.wikimedia.org", "Download redirected outside Wikimedia")
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    score.require(total <= item["source_bytes"], "Source exceeds pinned size")
                    output.write(block)
            score.require(temporary.stat().st_size == item["source_bytes"] and file_digest(temporary) == item["source_sha256"]
                          and file_digest(temporary, "sha1") == item["source_sha1"], "Downloaded source fixity failed")
            # Workspace lock excludes competing writers; never replace a cached source.
            score.require(not destination.exists(), "Source appeared while downloading")
            temporary.rename(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return {"status": "unreviewed", "images": len(catalog["items"]), "catalog_sha256": catalog_digest(catalog)}


class AnnotationStore:
    def __init__(self, workspace, catalog):
        self.workspace, self.catalog = workspace, catalog
        self.items = {item["id"]: item for item in catalog["items"]}
        self.digest = catalog_digest(catalog)
        self.mutex = threading.RLock()

    def directory(self, reviewer, item_id):
        score.require(item_id in self.items, "Unknown item")
        key = hashlib.sha256(reviewer_key(reviewer).encode("utf-8")).hexdigest()
        return self.workspace / "annotations" / key / item_id

    def latest(self, reviewer, item_id):
        directory = self.directory(reviewer, item_id)
        files = sorted(directory.glob("[0-9]*.json")) if directory.exists() else []
        if not files:
            return {"revision": 0, "regions": [], "complete": False}
        annotation = load(files[-1])
        score.require(annotation["catalog_sha256"] == self.digest and annotation["source_sha256"] == self.items[item_id]["source_sha256"],
                      "Annotation source/catalog changed")
        return annotation

    def comparison(self, item_id, left, right):
        score.require(reviewer_key(left) != reviewer_key(right), "Two independent reviewer identifiers are required")
        a, b = self.latest(left, item_id), self.latest(right, item_id)
        score.require(a.get("complete") and b.get("complete") and a.get("human_reviewed") and b.get("human_reviewed"),
                      "Both independent readings must be completed and explicitly attested")
        pairs = score.match_regions(a["regions"], b["regions"])
        ai, bi = {i for i, _ in pairs}, {i for _, i in pairs}
        return {"left": a, "right": b,
                "pairs": [{"left_id": a["regions"][i]["id"], "right_id": b["regions"][j]["id"],
                           "iou": score.iou(a["regions"][i]["bbox_normalized"], b["regions"][j]["bbox_normalized"])} for i, j in pairs],
                "unmatched_left": [region["id"] for i, region in enumerate(a["regions"]) if i not in ai],
                "unmatched_right": [region["id"] for i, region in enumerate(b["regions"]) if i not in bi]}

    def save(self, payload):
        reviewer = nonempty(payload.get("reviewer"), "reviewer", 2, 120)
        item_id = payload.get("item_id")
        directory = self.directory(reviewer, item_id)
        complete, human = payload.get("complete"), payload.get("human_reviewed")
        score.require(type(complete) is bool and type(human) is bool, "Explicit completion/reviewer attestation flags are required")
        score.require(not complete or human, "Completing an annotation requires explicit independent visual-reading attestation")
        protocol = nonempty(payload.get("protocol"), "annotation protocol", 12)
        regions = payload.get("regions")
        score.regions_at(regions, "annotation.regions", gold=True)
        score.require(len(regions) <= 120, "At most 120 target regions are supported")
        for region in regions:
            score.require(type(region.get("recognition_evaluable", True)) is bool, "recognition_evaluable must be boolean")
            if complete and region.get("recognition_evaluable", True):
                nonempty(region["text"], "readable literal transcription")
            if "rationale" in region:
                score.require(isinstance(region["rationale"], str) and len(region["rationale"]) <= 4000, "Invalid region rationale")
        with self.mutex:
            previous = self.latest(reviewer, item_id)
            expected = payload.get("expected_revision")
            if type(expected) is not int or expected != previous["revision"]:
                raise RevisionConflict("Annotation changed; reload explicitly before saving. Your browser draft is retained.")
            adjudication = payload.get("adjudication")
            if adjudication is not None:
                readers = adjudication.get("reviewers", [])
                score.require(isinstance(readers, list) and len(readers) == 2, "Two adjudicated reviewers are required")
                score.require(reviewer_key(reviewer) not in {reviewer_key(reader) for reader in readers}, "Adjudicator must be a third reviewer")
                comparison = self.comparison(item_id, *readers)
                reason = nonempty(adjudication.get("rationale"), "adjudication rationale", 32 if complete else 0)
                if complete:
                    for region in regions:
                        nonempty(region.get("rationale"), "adjudicated region rationale", 12)
                adjudication = {"reviewers": readers, "rationale": reason,
                                "reviewed_revisions": [comparison["left"]["revision"], comparison["right"]["revision"]]}
            annotation = {"schema": "modavis-scriptor.annotation/v1", "item_id": item_id, "reviewer": reviewer,
                          "revision": expected + 1, "created_at": now(), "source_sha256": self.items[item_id]["source_sha256"],
                          "catalog_sha256": self.digest, "complete": complete, "human_reviewed": human,
                          "protocol": protocol, "regions": regions, "adjudication": adjudication}
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            path = directory / f"{annotation['revision']:08d}.json"
            # Every submitted revision remains immutable. No mutable latest pointer.
            publish_new(path, canonical(annotation))
            return annotation


class RevisionConflict(ValueError):
    pass


def freeze(workspace, catalog, readers, adjudicator, split, output):
    score.require(len(readers) == 2 and len({reviewer_key(r) for r in [*readers, adjudicator]}) == 3,
                  "Freezing requires two independent reviewer IDs and a distinct adjudicator")
    score.require(not output.exists(), "Refusing to overwrite an existing frozen manifest")
    for protected in (workspace / "annotations", workspace / "sources"):
        score.require(not output.resolve().is_relative_to(protected.resolve()), "Gold output cannot replace annotation/source records")
    store = AnnotationStore(workspace, catalog)
    items, provenance = [], []
    for item in catalog["items"]:
        if item["split"] != split:
            continue
        verified_source(workspace, item)
        comparison = store.comparison(item["id"], *readers)
        final = store.latest(adjudicator, item["id"])
        score.require(final.get("complete") and final.get("human_reviewed"), "Adjudication is incomplete")
        decision = final.get("adjudication") or {}
        score.require([reviewer_key(r) for r in decision.get("reviewers", [])] == [reviewer_key(r) for r in readers], "Adjudication uses different reviewers")
        score.require(decision.get("reviewed_revisions") == [comparison["left"]["revision"], comparison["right"]["revision"]],
                      "A reading changed after adjudication; review it again before freezing")
        nonempty(decision.get("rationale"), "adjudication rationale", 32)
        for region in final["regions"]:
            nonempty(region.get("rationale"), "adjudicated region rationale", 12)
        items.append({"id": item["id"], "group_id": item["group_id"], "source_sha256": item["source_sha256"],
                      "rights": item["rights"], "strata": item.get("strata", []), "regions": final["regions"]})
        records = []
        for annotation in (comparison["left"], comparison["right"], final):
            path = store.directory(annotation["reviewer"], item["id"]) / f"{annotation['revision']:08d}.json"
            records.append({"reviewer": annotation["reviewer"], "revision": annotation["revision"], "sha256": file_digest(path),
                            "human_reviewed": annotation["human_reviewed"], "protocol": annotation["protocol"]})
        provenance.append({"item_id": item["id"], "annotations": records, "decision": decision})
    score.require(bool(items), "No candidates belong to the requested split")
    gold = {"schema": score.GOLD_SCHEMA, "split": split,
            "annotation": {"reviewer": adjudicator, "method": "Two blind declared human reviewers and a distinct adjudicator; literal-visible-text protocol v1"},
            "workflow": {"catalog_sha256": store.digest, "frozen_at": now(), "reviewers": readers,
                         "identity_limit": "Reviewer identities and independence are self-attested; no authentication or external certification.",
                         "provenance": provenance}, "items": items}
    score.validate_gold(gold)
    output.parent.mkdir(parents=True, exist_ok=True)
    publish_new(output, canonical(gold))
    return {"status": "frozen", "split": split, "images": len(items), "sha256": file_digest(output), "output": str(output)}


def make_server(workspace, catalog, port):
    store = AnnotationStore(workspace, catalog)
    for item in catalog["items"]:
        verified_source(workspace, item)
    preview_lock = threading.Lock()
    static = ROOT / "tools/annotation"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, code, data, content_type="application/json"):
            body = canonical(data) if content_type == "application/json" else data
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; img-src 'self'; script-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def parameters(self):
            return urllib.parse.urlsplit(self.path), urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)

        def do_GET(self):
            try:
                parsed, query = self.parameters()
                if parsed.path == "/api/catalog":
                    return self.respond(200, {"catalog_sha256": store.digest,
                        "items": [{**{key: item[key] for key in ("id", "group_id", "split", "rights", "source_sha256", "strata")},
                                   "image_url": "/image/" + item["id"]} for item in catalog["items"]]})
                if parsed.path == "/api/annotation":
                    return self.respond(200, store.latest(query["reviewer"][0], query["item"][0]))
                if parsed.path == "/api/compare":
                    return self.respond(200, store.comparison(query["item"][0], query["reviewer_a"][0], query["reviewer_b"][0]))
                if parsed.path.startswith("/image/"):
                    item = store.items[parsed.path.removeprefix("/image/")]
                    source = verified_source(workspace, item)
                    from PIL import Image, ImageOps
                    with preview_lock, Image.open(source) as image, io.BytesIO() as data:
                        score.require(image.width * image.height <= 40_000_000, "Image exceeds 40 megapixels")
                        score.require(getattr(image, "n_frames", 1) == 1, "Multiple image frames are not supported")
                        oriented = ImageOps.exif_transpose(image)
                        if oriented.mode in {"RGBA", "LA", "P"}:
                            background = Image.new("RGBA", oriented.size, "white")
                            background.alpha_composite(oriented.convert("RGBA"))
                            oriented = background
                        oriented.convert("RGB").save(data, "PNG")
                        return self.respond(200, data.getvalue(), "image/png")
                files = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                         "/style.css": ("style.css", "text/css; charset=utf-8")}
                if parsed.path in files:
                    name, kind = files[parsed.path]
                    return self.respond(200, (static / name).read_bytes(), kind)
                return self.respond(404, {"detail": "Not found"})
            except (ValueError, KeyError, TypeError, OSError) as error:
                self.respond(422, {"detail": str(error)})

        def do_POST(self):
            try:
                parsed, _query = self.parameters()
                port = self.server.server_address[1]
                allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
                if self.headers.get("Origin") and self.headers["Origin"] not in allowed:
                    return self.respond(403, {"detail": "Cross-origin writes are forbidden"})
                if self.headers.get("X-Scriptor-Annotation") != "1" or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    return self.respond(403, {"detail": "Use the local annotation interface"})
                if parsed.path != "/api/annotation":
                    return self.respond(404, {"detail": "Not found"})
                size = int(self.headers.get("Content-Length", "0"))
                score.require(0 < size <= 1024 * 1024, "Invalid annotation request size")
                payload = json.loads(self.rfile.read(size), object_pairs_hook=score.unique_object)
                return self.respond(200, store.save(payload))
            except RevisionConflict as error:
                self.respond(409, {"detail": str(error)})
            except (ValueError, KeyError, TypeError, OSError) as error:
                self.respond(422, {"detail": str(error)})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect", help="download and verify pinned rights-documented candidates")
    commands.add_parser("status", help="show collection and annotation readiness without inventing gold")
    serve = commands.add_parser("serve", help="serve blind annotation/adjudication locally")
    serve.add_argument("--port", type=int, default=0)
    freeze_parser = commands.add_parser("freeze", help="freeze a split only after two readings and independent adjudication")
    freeze_parser.add_argument("--reviewers", nargs=2, required=True)
    freeze_parser.add_argument("--adjudicator", required=True)
    freeze_parser.add_argument("--split", choices=["development", "held_out"], default="held_out")
    freeze_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = catalog_at(args.catalog)
    workspace = ensure_workspace(args.workspace, catalog)
    with workspace_lock(workspace):
        if args.command == "collect":
            result = collect(workspace, catalog)
        elif args.command == "freeze":
            result = freeze(workspace, catalog, args.reviewers, args.adjudicator, args.split, args.output)
        elif args.command == "status":
            result = {"status": "unreviewed", "candidates": len(catalog["items"]),
                      "collected": sum((workspace / "sources" / item["source_filename"]).is_file() for item in catalog["items"]),
                      "annotation_revisions": len(list((workspace / "annotations").glob("*/*/[0-9]*.json"))),
                      "note": "No independent human ground truth is supplied by collecting candidates or running software tests."}
        else:
            server = make_server(workspace, catalog, args.port)
            print(json.dumps({"url": f"http://127.0.0.1:{server.server_address[1]}", "status": "unreviewed", "workspace": str(workspace)}), flush=True)
            try:
                server.serve_forever()
            finally:
                server.server_close()
            return 0
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise SystemExit(str(error))
    except KeyboardInterrupt:
        raise SystemExit(130)
