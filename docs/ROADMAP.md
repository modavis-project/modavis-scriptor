# Development roadmap

## Development foundation

The current development branch strengthens the existing local image workflow. Acceptance requires a reproducible Node/Python environment, zero reported npm/Python dependency advisories, verified bundled assets, evidence checks across read/review/rerun/export, compatible versioned database initialization, and a passing disposable backend/OCR/API/browser test run. Historical raw results and research volumes must remain unchanged.

Use `npm run doctor` to inspect prerequisites, `npm run check` for web checks and dependency auditing, and `npm run test:integration` for the disposable stack. See `VALIDATION.md` for what each check proves.

## Next milestone: measured recognition improvements

The next feature milestone should improve detection and transcription across varied organ-stop photographs while preserving the image-first review policy.

1. Collect a rights-cleared evaluation corpus covering different organs, typefaces, lighting, reflections, clipped labels, non-stop controls and failed detections. Keep a tuning split separate from a held-out split, grouping photographs of the same organ/source together to reduce leakage.
2. Have independent reviewers annotate every visible target region and literal reading, including spelling variants, fractions and Roman rank expressions. Adjudicate disagreements against the image; corpus matches must not supply missing text. Freeze source digests, annotation version, rights and reviewer provenance before running the held-out evaluation.
3. Record a baseline using `scripts/evaluation/score.py`: detection precision/recall, matched-region raw OCR CER/WER and protected-term losses after review. Report denominators, missed/spurious regions and strata separately. Measure reviewer time and number of corrections in a separate study.
4. Change one recognition/detection factor at a time on the tuning split. Ship only after the fixed regression suite passes and held-out results document both improvements and regressions. Similarity scores must remain advisory; no automatic corpus substitutions.

Completion requires the dataset manifest, annotation protocol/adjudication record, baseline report, reproducible run configuration and a documented decision for every protected-term regression. The current example and synthetic unit tests do not satisfy this research acceptance criterion.

## Delivered engineering priorities

| Area | Implementation | Acceptance evidence |
| --- | --- | --- |
| Shared contracts and focused panels | Actual Pydantic/OpenAPI contracts generate frontend types/schema with runtime validation; configuration/upload/evidence/queue/review/output are separate. | Model/generation and runtime/network tests; drift check; three-browser interaction. |
| Recovery and concurrency | Staged atomic OCR publication, restart recovery, single-service ownership, durable admission, explicit stale-draft compare/rebase. | Real killed Tesseract/API restart, prepared publication recovery, concurrent reviews and sustained queue limits. |
| Transfer memory and initial UI | Chunked verified file copy and disk-spooled response/ZIP delivery with disconnect cleanup; lazy Markdown. | Over-64-MiB transfer/archive tests with bounded Python allocation; client largest chunk reduced from about 516 KB to 332 KB without raising warning limits. Image inference memory still depends on image dimensions. |
| Verified backup/restore | Consistent live SQLite/file snapshot, transport manifest, actual extraction/rehearsal, schema/evidence checks, atomic non-overwriting restore. | Concurrent review during backup, corrupt archives, unsafe paths, legacy preservation, directory durability and restore tests. |
| Browser/platform checks | Chromium, Firefox and WebKit acceptance; Linux amd64/arm64 container jobs; Windows native job with pinned Tesseract; portable command/process cleanup. | Actual local native/arm64 checks and CI results in `VALIDATION.md`. WSL prerequisite tooling is supplied; a real WSL installation remains a distinct manual check. |
| Storage isolation | Separate Colima context on internal APFS; physical backing-capacity diagnostics and child-only context selection. | Actual dedicated VM start/status/exec, preserved global context, fast local arm64 cold build and complete integration. No other project data was moved/deleted. |
| Evaluation workflow | Eight rights-documented unreviewed candidates; blind annotation, independent adjudication, revision safety, verified freeze, scoring that excludes unreadable text from recognition denominators. | Synthetic workflow/API/UI tests and actual pinned-source collection. No real human annotations or accuracy results are fabricated. |

The implemented engineering work is the acceptance baseline for continued development. Recognition experiments should now use the collection/annotation milestone above; quality claims remain dependent on genuine human-reviewed data. Capacity planning and filesystem/hardware maintenance for unrelated Docker Desktop storage are outside this isolated runtime's data boundary.

## Separate scope decisions

PDF/multipage ingestion, handwriting-specific recognition and authenticated multi-user hosting are separate milestones. Each requires its own source/rights model, evaluation data and acceptance criteria. The present deployment remains local and single-user; reviewer identity is self-asserted. Do not interpret completion of development checks as readiness for public hosting or a measured OCR accuracy claim.
