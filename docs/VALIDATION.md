# Validation

The release is validated as a local, single-user image-processing application. The bundled example is not a benchmark dataset and contains no pre-approved human decisions.

## Historical release checks

Date: 3 September 2026.

| Check | Environment | Result |
| --- | --- | --- |
| TypeScript, lint and production build | macOS / Apple Silicon | Passed |
| Web and graphics container builds | Linux arm64 | Passed |
| Web and graphics container builds | Linux amd64, under local emulation | Passed |
| Sixteen API integration checks | Separate arm64 and amd64 containers | Passed |
| Full-image boxes and single-label OCR regression | arm64 and amd64 containers | Passed |
| Web health, proxy health and rendered application response | arm64 and amd64 containers | Passed |
| Web build and graphics API integration tests | GitHub-hosted Ubuntu amd64 runner | Passed |
| Frozen example manifest | 112 files | Passed |
| Corpus integrity and expected counts | SQLite quick check and importer assertions | Passed |

Local amd64 checks use emulation on Apple Silicon; the GitHub-hosted Ubuntu runner additionally builds the web application and graphics image and executes the API tests independently. These checks are not performance benchmarks. Windows/WSL installation has not been independently exercised.

## Development validation: 30 October 2026

Executed locally on macOS / Apple Silicon with Node 22.23.4, Python 3.12.12, Tesseract 5.5.4, Pillow 13.0.0 and python-multipart 0.0.32:

| Check | Result |
| --- | --- |
| Clean npm installation, lint, TypeScript and production build | Passed |
| npm audit | Zero findings |
| Python dependency compatibility and pip-audit 2.10.1 | All 18 locked packages audited, zero findings, none skipped |
| Bundled fixture/model/corpus verification | Passed: 112 files, 38,103 groups, 503,980 components |
| Backend integrity, migration, recovery and atomic queue regressions | 27 tests passed |
| Real detector and close-up dual-model OCR | Passed |
| Fresh full-panel multipart upload, review/child-run/export API checks | Passed |
| Chromium review, persistence, raw OCR, download and narrow viewport | Passed |
| Evaluation scorer algorithms and input validation | 17 tests passed |
| Docker and native prerequisite checks | Passed with the pinned Node runtime |
| Fresh web/graphics images and complete isolated Docker suite | Passed on GitHub-hosted Ubuntu amd64 |
| IPv4 frontend development routes, API proxy and seeded example | Passed |

The native integration run used temporary data and free loopback ports, then removed its own processes. Frozen evidence, corpus and bundled models remain unchanged. The [clean Ubuntu CI run](https://github.com/modavis-project/modavis-scriptor/actions/runs/41053258260) additionally passed both fresh Docker builds, 27 backend tests, real OCR, multipart upload/API checks, Chromium acceptance and isolated cleanup. The runtime image includes the system CA store required by Workerd. Current Linux arm64 container validation and Windows/WSL remain separate from these native/amd64 results.

The local Docker Desktop backing storage is an APFS sparse disk image on an external ExFAT volume that was 96% full. Cold builds showed sustained VM I/O stalls despite low CPU/memory pressure and apparently ample virtual free space. This is a storage-maintenance concern rather than an application performance benchmark. The native development/test path is available independently; plan storage cleanup or migration before relying on repeated heavy cold builds.

## Current development suite

Use Node 22.23.4 (`.nvmrc`) and a responding Docker daemon. From the repository root:

```bash
npm ci
npm run doctor
npm run check
npm run test:evaluation
npx playwright install chromium
npm run test:integration
```

`check` includes lint, TypeScript, production build and npm auditing. CI uses the same runtime and integration entry point. On Linux, install Chromium with `npx playwright install --with-deps chromium`.

CI also audits all pinned Python packages with `pip-audit==2.10.1`. If uv is installed, the equivalent isolated local command is:

```bash
uvx --python 3.12 pip-audit==2.10.1 --requirement services/graphics/requirements.lock --disable-pip --no-deps --progress-spinner off
```

Keep auditing tools outside the application's runtime environment. The lockfile lists the complete pinned dependency tree, so the audit can inspect it without dependency resolution.

The integration runner creates a randomly named Compose project, chooses free loopback ports, builds separate `development-test` images, and uses fresh disposable service data. It never mounts a research volume. Cleanup uses that exact project name, including on failure. `--no-build` reuses test images; `--skip-browser` explicitly omits browser coverage and is not the full CI suite.

The optional `--native` path runs the same backend/OCR/API/browser checks using the prepared Python 3.12/Tesseract environment and host Wrangler, with temporary state and free ports. It stops its own process groups afterwards. This validates the native runtime; it does not substitute for the Docker image build and container checks used in CI.

| Check | Purpose |
| --- | --- |
| `verify-assets.py` | Exact 112-file frozen manifest, historical source snapshots, models, corpus digest/SQLite integrity/counts and importer digest. Current source files may differ from historical snapshots. |
| `test-backend.py` | Temporary migration/adoption tests, preservation of review history/triggers, rejection of newer/unknown schemas, corruption/deletion checks across evidence-consuming endpoints, allowlist exports and legacy verification coverage. |
| `test-pipeline.py` | Fresh full-panel detection boxes and real close-up dual-model OCR (`Scharff / IV-VI`). Uses temporary output/data. |
| `test-api.py` | Fresh multipart full-panel upload and automatic OCR, validation, review history, child runs and exports against an explicitly disposable instance. |
| Playwright Chromium | Seed loading, region/crop selection, candidate draft without acceptance, reviewer/rationale gates, acceptance/Markdown update, persistence after reload, raw OCR, JSON download and narrow viewport. |
| `test:evaluation` | Synthetic algorithm/input-validation regressions for detection matching and OCR scoring; does not measure real-world accuracy. |

## API integration checks

`scripts/graphics/test-api.py` checks:

- multipart image upload and fresh automatic full-panel detection/OCR;
- 21 regions and three clipping flags;
- EXIF-normalized dimensions and valid normalized coordinates;
- corpus source identifiers and component counts;
- absence of automatic normalization or acceptance;
- reviewer and rationale validation;
- candidate membership checks;
- same-origin write rejection;
- acceptance reflected in Markdown while raw OCR remains unchanged;
- HTTP 409 for stale review versions;
- `retain` and `defer` materialization;
- preserved event history;
- invalid region bounds;
- child-run provenance;
- absence of corpus candidates in general graphics mode;
- original/result fixity and source attribution in the research bundle.

## Individual isolated checks

Prefer the full runner above. For focused debugging, use the separate test Compose file, never `compose.yaml`:

```bash
docker compose -f compose.test.yaml up --build --detach --wait
docker compose -f compose.test.yaml exec -T graphics python /checks/test-backend.py
docker compose -f compose.test.yaml exec -T graphics python /checks/test-pipeline.py
python3 scripts/graphics/test-api.py http://127.0.0.1:8310
SCRIPTOR_TEST_BASE_URL=http://127.0.0.1:3410 npm run test:browser
docker compose -f compose.test.yaml down --volumes
```

This file names its project `modavis-scriptor-tests` and does not mount the research volume. `SCRIPTOR_TEST_API_PORT` and `SCRIPTOR_TEST_WEB_PORT` override its host ports. API/browser mutation tests require loopback URLs, reject redirects/remote targets and ports 3000/8010/3080/8080, and require `disposable_test_instance: true` from health (`SCRIPTOR_DISPOSABLE_TEST=1` in the test container). They also require pristine test data. Recreate the test containers before another API/browser run; do not reuse existing test reviews.

For completely native backend debugging, activate the locked Python 3.12 environment and run `PYTHONPATH=services/graphics python scripts/graphics/test-backend.py` or `test-pipeline.py`. These scripts create their own temporary state. The pipeline test additionally requires native Tesseract and both language model sets. The asset verifier and evaluation tests use only the standard library.

## Manual interface checks

For each supported browser, inspect:

1. initial example load and every output row;
2. region selection and correspondence with its evidence crop;
3. draft candidate selection without acceptance;
4. reviewer/rationale validation and successful acceptance;
5. immediate rendered Markdown update and persistence after reload;
6. raw Markdown availability through the final region;
7. image upload, custom region processing and parent-run navigation;
8. JSON, CSV, Markdown and ZIP downloads;
9. navigation and keyboard focus at a narrow viewport.

## Release boundary

Functional checks do not establish general OCR accuracy. No CER/WER, recall or correction-precision figure is claimed. Review identities are self-asserted, not authenticated, and append-only SQLite events are not a tamper-proof archive.
