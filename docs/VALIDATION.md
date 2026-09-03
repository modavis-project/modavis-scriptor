# Validation

The release is validated as a local, single-user image-processing application. The bundled example is not a benchmark dataset and contains no pre-approved human decisions.

## Executed release checks

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

## Automated checks

`scripts/graphics/test-pipeline.py` checks that the full example has 21 unchanged detection boxes and that a close-up of region 3 is recognized as one surface with `Scharff / IV-VI`.

`scripts/graphics/test-api.py` checks:

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

## Isolated API test

Build the graphics image first. The test writes decisions and must use a fresh, disposable container without the research volume:

```bash
docker run --name modavis-scriptor-test --detach \
  --publish 127.0.0.1:8310:8010 modavis-scriptor-graphics:0.1.0
python3 scripts/graphics/test-api.py http://127.0.0.1:8310
docker stop modavis-scriptor-test
```

The test refuses ports 3000 and 8010. A second invocation against the same instance encounters existing test events and is not a fresh test. Removing that test container is optional; never mount or delete the research volume as part of the test.

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
