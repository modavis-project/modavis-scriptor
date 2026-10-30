# Architecture

## Components

MODAVIS Scriptor consists of two containers on a private Compose network.

### Web service

The TypeScript/React service renders the interface and proxies `/api/graphics/*` to the processing service. The proxy allows `GET`, `POST` and `PATCH` only, applies a same-origin check to browser writes, restricts route shapes, forwards request bodies as streams and disables response caching.

The browser does not need direct access to the processing container. Port 8010 remains published on loopback for local API clients and OpenAPI inspection.

### Processing service

The Python/FastAPI service performs image normalization, region detection, Tesseract OCR, field parsing, corpus retrieval, review materialization and export. A single background executor limits concurrent inference. At most ten queued or running jobs are accepted: admission checks and insertion share an immediate SQLite transaction across uploads and reruns. A rejected insertion removes only its newly created folder. A run may contain no more than 120 regions.

The service stores state in `/data`:

```text
/data/
  graphics.sqlite
  <run-id>/
    original
    processed/           published evidence for new runs
      original
      image.png
      result.json
      source-*.py
      rNNN-crop.png
      rNNN-ocr.png[.tsv]
      rNNN-alt.png[.tsv]
```

`original` contains the uploaded bytes. `image.png` is the EXIF-normalized RGB derivative used by the interface and coordinate system. OCR inputs and TSV outputs are retained separately from evidence crops.

New processing writes a private `.attempt-<id>` directory. Generated artifacts are flushed and verified; the result digest is committed before atomic publication to `processed/`. Restart either validates and finishes that prepared publication or discards only the incomplete attempt and requeues the preserved source. Completed historical/frozen runs keep their existing flat layout and bytes. Schema 3 records `artifact_path` and `attempt_id` without changing the raw run JSON schema.

An operating-system ownership lock rejects a second service for the same data directory. Shared operation locks coordinate uploads, processing and review with exclusive backup snapshots; Windows conservatively serializes the operations. Marked admission folders absent from SQLite can be cleaned after interruption; unmarked directories are never treated as disposable reservations.

## Persistence

SQLite stores run records and append-only review events. Database triggers reject updates and deletions of review events. A `UNIQUE(run_id, region_id, version)` constraint and `expected_version` request field prevent a reviewer from silently overwriting a newer decision.

`result.json` is immutable after a run completes. Its SHA-256 is stored in the run table and verified before review or export. New results contain an artifact manifest covering the original, normalized image, crops, OCR inputs/outputs and executing source snapshots. Evidence-consuming operations verify recorded digests and reject missing or changed files with HTTP 409. Bundles include only verified artifacts. Reviewer decisions are materialized at read time and returned separately from the immutable result.

The frozen example uses its trusted file manifest. Older non-example results retain their original bytes and use the hashes they already recorded; OCR artifacts without historical hashes are explicitly listed as unverified and excluded from exports. Their integrity cannot be established retroactively. The response and research bundle expose verification coverage.

SQLite `PRAGMA user_version` selects the ordered schema migration. The initial migration validates/adopts the existing 0.1.0 structure and preserves its rows and append-only triggers. A database with a newer unsupported schema is rejected rather than modified. Back up persistent data before upgrades.

This protects against accidental application-level replacement. It is not a cryptographic audit system against an administrator who can modify both the files and database. Long-term preservation requires externally stored checksums or a signed archival package.

Image and ZIP responses use preverified temporary files with bounded chunked copy/hash operations. Streaming begins only after artifact verification succeeds, and cleanup runs even on disconnect. Transfer memory does not scale with the total archive size; disk space and the image-processing arrays still scale with the workload. Verified live backup/restore is described in `BACKUP.md`.

## Frontend contracts and state

Pydantic models in `services/graphics/contracts.py` are the actual FastAPI request/response contracts. A deterministic OpenAPI generator emits the committed frontend types/schema; runtime guards validate successful responses and the API client handles structured failures. CI rejects drift and unsupported generation features.

The workbench composes focused upload/configuration/evidence/queue/review/output panels. Its controller owns run loading and navigation. Review drafts are retained per region, including after a 409; comparing/rebasing a stale draft is explicit. Markdown is lazy-loaded separately from the initial evidence UI.

## Processing sequence

```text
original bytes
  -> EXIF normalization
  -> region detection or supplied regions
  -> unchanged evidence crops
  -> OCR-specific preprocessing
  -> configured and alternate OCR
  -> rule-based field proposal
  -> advisory corpus retrieval
  -> immutable run result
  -> human review events
  -> materialized Markdown / JSON / CSV / ZIP
```

The corpus is never injected into Tesseract and never changes raw OCR. Retrieval starts only after recognition and parsing.

## Network and trust boundary

Compose publishes both ports on `127.0.0.1`. The services contain no user account system, role model or authenticated reviewer identity. The `reviewer` value is a self-asserted label recorded for provenance.

A multi-user deployment must add an authenticated gateway, authorization rules, TLS, upload malware controls, rate limits, database backup, log retention and a verified identity mapping. The current same-origin check is not a substitute for those controls.

## Reproducibility boundary

The Python base image is pinned by digest. Python packages and recognition model files are versioned and hashed. Every newly processed run records package versions, Python/platform information, model checksums, configuration, corpus projection checksum and checksums of the executing Python source files.

Debian packages installed during the container build are resolved from the Debian archive. Exact reproduction therefore additionally requires preservation of the built image or its exported OCI digest. Runtime duration and timestamps are expected to differ across machines.
