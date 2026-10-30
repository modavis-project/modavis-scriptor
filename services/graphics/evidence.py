"""Verify recorded evidence without inventing checksums for unverifiable history."""
import hashlib
import re
from pathlib import Path

MANIFEST_SCHEMA = "modavis-scriptor.artifact-manifest/v1"
DIGEST = re.compile(r"[a-f0-9]{64}")
ARTIFACT = re.compile(r"(?:original|image\.png|sparse\.png(?:\.tsv)?|r\d+-(?:crop\.png|(?:ocr|alt)\.png(?:\.tsv)?)|source-[a-zA-Z0-9_-]+\.py)")


class IntegrityError(ValueError):
    pass


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def recorded_files(result):
    """Names required by the v1 pipeline, with original digests where v1 recorded them."""
    files = {"original": result["image"]["sha256"], "image.png": result["image"]["normalized_sha256"]}
    for name, digest in result["paradata"]["source_code_sha256"].items():
        if Path(name).name != name or not name.endswith(".py"):
            raise IntegrityError("Invalid recorded source artifact name")
        files["source-" + name] = digest
    for region in result["regions"]:
        region_id = region["id"]
        if not re.fullmatch(r"r\d+", region_id):
            raise IntegrityError("Invalid recorded region identifier")
        files[f"{region_id}-crop.png"] = region["crop_sha256"]
        for key, suffix in (("ocr", "ocr"), ("alternative_ocr", "alt")):
            expected = f"{region_id}-{suffix}.png.tsv"
            if region[key]["tsv_file"] != expected:
                raise IntegrityError("Invalid recorded OCR artifact name")
            files[expected] = None
            files[expected.removesuffix(".tsv")] = None
    config = result["paradata"]["config"]
    if not config.get("regions") and (config["mode"] == "graphics" or not any(r["detector"] == "light-surface-contour" for r in result["regions"])):
        files.update({"sparse.png": None, "sparse.png.tsv": None})
    for name, digest in files.items():
        if not ARTIFACT.fullmatch(name) or (digest is not None and not DIGEST.fullmatch(digest)):
            raise IntegrityError("Invalid artifact manifest entry")
    return files


def verified_bytes(folder, name, digest):
    """Read once, reject links, and verify the exact bytes that will be served/exported."""
    if not (name == "result.json" or ARTIFACT.fullmatch(name)) or not DIGEST.fullmatch(digest or ""):
        raise IntegrityError("Invalid artifact manifest entry")
    path = folder / name
    try:
        if path.is_symlink() or not path.is_file():
            raise IntegrityError(f"Evidence is missing or not a regular file: {name}")
        content = path.read_bytes()
    except OSError as error:
        raise IntegrityError(f"Evidence is unavailable: {name}") from error
    if hashlib.sha256(content).hexdigest() != digest:
        raise IntegrityError(f"Evidence checksum mismatch: {name}")
    return content


def build_manifest(folder, result):
    files = recorded_files(result)
    for name, digest in files.items():
        if digest is not None:
            verified_bytes(folder, name, digest)
        files[name] = sha256(folder / name)
        verified_bytes(folder, name, files[name])
    return {"schema": MANIFEST_SCHEMA, "files": files}


def verify(folder, result, trusted_files=None):
    """Return an allowlist plus explicit limits for legacy v1 runs lacking OCR hashes."""
    try:
        recorded = recorded_files(result)
        manifest = result.get("artifact_manifest")
        if manifest is not None:
            if manifest.get("schema") != MANIFEST_SCHEMA or set(manifest["files"]) != set(recorded):
                raise IntegrityError("Artifact manifest is incomplete or has unexpected files")
            files = manifest["files"]
            coverage = "complete"
        elif trusted_files is not None:
            files = {k: v for k, v in trusted_files.items() if k != "result.json"}
            if set(files) != set(recorded):
                raise IntegrityError("Frozen example manifest does not match recorded artifacts")
            coverage = "frozen-example"
        else:
            files = {k: v for k, v in recorded.items() if v is not None}
            coverage = "legacy-recorded-hashes"
        for name, digest in files.items():
            if recorded[name] is not None and recorded[name] != digest:
                raise IntegrityError(f"Conflicting evidence digest: {name}")
            verified_bytes(folder, name, digest)
        unverified = sorted(set(recorded) - set(files))
        return {"coverage": coverage, "verified_files": dict(files), "unverified_files": unverified,
                "note": "Legacy OCR inputs/TSVs without recorded hashes are excluded from exports; historical integrity cannot be established." if unverified else "All recorded artifacts verified against preserved checksums."}
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        if isinstance(error, IntegrityError):
            raise
        raise IntegrityError("Invalid recorded evidence metadata") from error
