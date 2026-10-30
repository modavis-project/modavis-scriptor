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

## Engineering priorities after the foundation

| Priority | Improvement | Trigger and acceptance |
| --- | --- | --- |
| High | Shared API contracts and smaller workbench components | Before substantial UI expansion: generate or validate response types from OpenAPI, separate upload/review/evidence views, preserve browser behavior. |
| High | Extended crash/recovery and load coverage | Build on the admission/migration race tests with interruption during real OCR, sustained queue saturation and simultaneous reviewers; no lost evidence or silent decisions. |
| Medium | Export/processing memory and performance | Measure representative large inputs, archive memory and review latency before changing limits; retain deterministic artifact coverage. |
| Medium | Backup/restore and migration rehearsal | Verify a real restored copy with file/database checks before future persistent-schema changes; never use the research volume for tests. |
| Medium | Broader browser/platform coverage | Add Firefox/WebKit and independently exercise Windows/WSL; current automated browser coverage is Chromium. |

## Separate scope decisions

PDF/multipage ingestion, handwriting-specific recognition and authenticated multi-user hosting are separate milestones. Each requires its own source/rights model, evaluation data and acceptance criteria. The present deployment remains local and single-user; reviewer identity is self-asserted. Do not interpret completion of development checks as readiness for public hosting or a measured OCR accuracy claim.
