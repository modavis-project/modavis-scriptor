#!/usr/bin/env python3
"""Integration checks for a marked, fresh disposable instance; never research data."""
import hashlib
import http.client
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path


SEED = "example-organ-stops-v1"
RESEARCH_PORTS = {3000, 8010, 3080, 8080}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def disposable_url(value):
    """Reject ambiguous, remote and known research targets before I/O."""
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.port is None or parsed.port <= 1024 or parsed.port in RESEARCH_PORTS
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path.rstrip("/") not in {"", "/api/graphics"}):
        raise SystemExit("Refusing QA writes: use an explicit loopback test port, never 3000/8010/3080/8080.")
    return value.rstrip("/")


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Test endpoint redirects are forbidden", headers, fp)


def main():
    base = disposable_url(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SCRIPTOR_TEST_API_URL", "http://127.0.0.1:8310"))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirects)

    def request(path, method="GET", payload=None, expected=200, headers=None, raw_body=None):
        body = raw_body if raw_body is not None else json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json", **(headers or {})}
        try:
            with opener.open(urllib.request.Request(base + path, data=body, method=method, headers=headers), timeout=180) as response:
                code, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            code, raw = error.code, error.read()
        require(code == expected, (path, code, expected, raw[:500]))
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return raw

    for _ in range(120):
        try:
            health = request("/health")
            break
        except (OSError, http.client.HTTPException):
            time.sleep(1)
    else:
        raise SystemExit("Test service did not become ready within 120 seconds")
    require(health.get("disposable_test_instance") is True, "Refusing QA writes: service is not explicitly marked SCRIPTOR_DISPOSABLE_TEST=1")
    listed = request("/runs")["runs"]
    require(len(listed) == 1 and listed[0]["id"] == SEED, "Refusing QA writes: start with a fresh disposable container")

    def completed(run_id):
        for _ in range(180):
            data = request("/runs/" + run_id)
            if data["run"]["status"] == "completed":
                return data
            require(data["run"]["status"] != "failed", data)
            time.sleep(1)
        raise AssertionError(f"Run {run_id} did not finish")

    frozen = completed(SEED)["result"]
    require(not frozen["review_events"], "Refusing QA writes: example already has review events")

    # Exercise multipart upload and full automatic detection/OCR. Leave the seed
    # pristine for the independent browser acceptance check.
    example = Path(__file__).resolve().parents[2] / "services/graphics/example"
    original = (example / "Organ-stops.jpg").read_bytes()
    metadata = json.loads((example / "source.json").read_text())
    boundary = "scriptor-test-" + uuid.uuid4().hex
    fields = {"title": "Disposable full-panel upload", "project": "Automated QA only", "config": "{}", "metadata": json.dumps(metadata)}
    parts = []
    for key, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="Organ-stops.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode() + original + b"\r\n")
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    run = request("/runs", "POST", expected=202, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, raw_body=body)["id"]
    data = completed(run)
    result = data["result"]
    original_hash = result["immutable_result_sha256"]
    require(run != SEED and data["run"]["parent_id"] is None, "Upload did not create an independent run")
    require(result["integrity"]["coverage"] == "complete" and not result["integrity"]["unverified_files"], "Fresh upload lacks complete artifact verification")
    require(len(result["regions"]) == 21, result["regions"])
    require(all(r["detector"] == "light-surface-contour" for r in result["regions"]), "Automatic surface detection was not used")
    require(sum(r["clipped"] for r in result["regions"]) == 3, "Clipping flags changed")
    require(not result["review_events"] and all(r["effective"] == r["parsed"] for r in result["regions"]), "Fresh OCR was automatically accepted or changed")
    require(result["image"]["width"] == 3024 and result["image"]["height"] == 4032, "EXIF orientation changed")
    require(result["image"]["sha256"] == hashlib.sha256(original).hexdigest(), "Uploaded source bytes changed")
    require(result["regions"][2]["parsed"]["name"] == "Scharff", "Protected spelling changed")
    for region in result["regions"]:
        x, y, width, height = region["bbox_normalized"]
        require(0 <= x <= 1 and 0 <= y <= 1 and 0 < width <= 1 and 0 < height <= 1 and x + width <= 1.00001 and y + height <= 1.00001, "Invalid normalized coordinates")
    require(result["paradata"]["corpus"]["input_components"] == 503980, "Missing corpus provenance")

    path = f"/runs/{run}/regions/r003/review"
    payload = {"action": "accept", "reviewer": "QA (automated test)", "rationale": "TEST ONLY: image spelling must remain distinct.", "name": "Scharf", "specification": "IV-VI", "kind": "stop", "division": "", "expected_version": 0}
    request(path, "PATCH", {**payload, "rationale": ""}, 422)
    request(path, "PATCH", {**payload, "reviewer": "  "}, 422)
    request(path, "PATCH", {**payload, "candidate_id": -999}, 422)
    request(path, "PATCH", payload, 403, headers={"Origin": "https://untrusted.example"})
    accepted = request(path, "PATCH", payload)
    require(accepted["regions"][2]["effective"]["name"] == "Scharf", "Acceptance did not materialize")
    require(accepted["regions"][2]["raw_text"] == result["regions"][2]["raw_text"], "Acceptance changed raw OCR")
    require("| 3 | Scharf |" in accepted["markdown"], "Acceptance did not update Markdown")
    request(path, "PATCH", payload, 409)
    retained = request(path, "PATCH", {**payload, "action": "retain", "expected_version": 1})
    require(retained["regions"][2]["effective"]["name"] == "Scharff", "Retain did not restore original fields")
    deferred = request(path, "PATCH", {**payload, "action": "defer", "expected_version": 2})
    require(deferred["regions"][2]["effective"] == result["regions"][2]["parsed"], "Defer changed original fields")
    require(len(deferred["review_events"]) == 3 and deferred["immutable_result_sha256"] == original_hash, "History or immutable result changed")

    request(f"/runs/{run}/rerun", "POST", {"regions": [[.9, .9, .3, .3]]}, 422)
    child = request(f"/runs/{run}/rerun", "POST", {"mode": "graphics", "regions": [[.167, .13, .12, .1]]}, 202)["id"]
    rerun = completed(child)
    require(rerun["run"]["parent_id"] == run, "Child lost parent provenance")
    require(rerun["result"]["paradata"]["corpus"] is None and not any(r["candidates"] for r in rerun["result"]["regions"]), "Corpus leaked into general graphics mode")
    require(rerun["result"]["image"]["sha256"] == result["image"]["sha256"], "Child source bytes changed")

    bundle = request(f"/runs/{run}/export?format=bundle")
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        require({"original", "image.png", "result.json", "reviewed.json", "reviewed.md", "raw.md", "table.csv", "source.json", "regions.svg", "integrity.json"} <= set(archive.namelist()), "Incomplete research export")
        require(json.loads(archive.read("integrity.json"))["coverage"] == "complete", "Export lost artifact verification coverage")
        require(hashlib.sha256(archive.read("original")).hexdigest() == result["image"]["sha256"], "Export source checksum changed")
        require(hashlib.sha256(archive.read("result.json")).hexdigest() == original_hash, "Export result checksum changed")
        require("Tucker501" in archive.read("source.json").decode(), "Missing source attribution")
        require('text-anchor="end"' in archive.read("regions.svg").decode(), "Missing region labels")
    require(not request("/runs/" + SEED)["result"]["review_events"], "API checks modified the browser fixture")
    print(json.dumps({"status": "passed", "api": base, "uploaded_run": run, "qa_child_run": child, "result_sha256": original_hash,
        "runtime": {key: result["paradata"][key] for key in ("engine", "python", "packages")},
        "checks": ["fresh marked disposable target", "multipart full-panel upload", "21 automatic regions / 3 clipped", "EXIF coordinates and source fixity", "complete artifact verification", "corpus provenance", "identity/rationale/candidate/origin validation", "accept/retain/defer and stale-version conflict", "raw OCR and result immutability", "child provenance and graphics corpus isolation", "research ZIP fixity and attribution", "seed preserved for browser QA"]}, indent=2))


if __name__ == "__main__":
    main()
