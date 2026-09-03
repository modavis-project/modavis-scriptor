# MODAVIS Scriptor

MODAVIS Scriptor is a local research application for extracting visible text from images, reviewing each reading against the source, and exporting the result with processing provenance. Version 0.1.0 includes a specialized workflow for photographed pipe-organ stops and a general visible-text mode.

The application keeps three kinds of information separate:

1. the original image and immutable OCR output;
2. corpus matches used as advisory evidence; and
3. explicit human decisions with reviewer, rationale and timestamp.

The bundled example is a photograph of the stop controls of the Brombaugh Opus 35 organ. It is included with attribution and license information. No private manuscript or same-author reference corpus is included.

## Start with Docker Compose

Requirements:

- Docker Engine 24 or newer with Docker Compose v2; or Docker Desktop;
- approximately 4 GB free disk space during the first build;
- an internet connection for the first image build.

From the repository root:

```bash
docker compose up --build --detach
```

Open <http://127.0.0.1:3000>. The example is available immediately. The processing API and its OpenAPI interface are available at <http://127.0.0.1:8010/docs>.

Check service state:

```bash
docker compose ps
curl --fail http://127.0.0.1:3000/api/health
curl --fail http://127.0.0.1:8010/health
```

Stop the application without deleting uploads or review decisions:

```bash
docker compose down
```

The named volume `modavis-scriptor-graphics-data` stores uploaded images, OCR artifacts, run metadata and review events. `docker compose down --volumes` deletes that data. Export research bundles before removing the volume.

To use different local ports:

```bash
MODAVIS_SCRIPTOR_PORT=3080 GRAPHICS_PORT=8080 docker compose up --build --detach
```

Both ports bind to `127.0.0.1`. Version 0.1.0 is not designed for direct exposure to an untrusted network.

## Workflow

1. Select the included example or upload JPEG, PNG, WebP or a single-page TIFF.
2. Choose `Registerzüge + MODAVIS` for light stop-label surfaces, or the general graphics mode for sparse visible text.
3. Inspect a numbered region, its unchanged crop, the configured OCR result and the alternate OCR result.
4. Expand corpus matches to inspect original labels and their component, source-record and organ identifiers.
5. Treat a corpus match as a proposal. Edit the structured fields only after inspecting the image.
6. Enter reviewer identity and an image-based rationale. Accept the edited reading, retain the OCR reading, or defer the decision.
7. Inspect complete rendered Markdown or download Markdown, CSV, JSON or a research ZIP.

Manual normalized regions use `[x, y, width, height]`, with every value between `0` and `1`. Reprocessing always creates a child run; it does not overwrite the earlier result.

## Interpretation rules

- The image is the primary documentary evidence.
- OCR remains unchanged in the raw result.
- Corpus similarity is neither identification nor a calibrated probability of correctness.
- Spelling variants, accents, vowels, stop names, numerals, fractions, pitch indications and rank counts are not silently normalized.
- A corpus candidate changes the reviewed output only after an explicit human decision.
- Partially visible controls remain marked as clipped; missing text is not completed from the corpus.

## MODAVIS corpus

The stop workflow uses a read-only retrieval projection made from the OrgRec SQLite profile of **MODAVIS Pipe Organ Dataset 1.5.0**: <https://doi.org/10.5281/zenodo.22234059>.

The public SQLite database is sufficient for name retrieval. The projection contains 38,103 exact name/type groups derived from 503,980 provenance-linked components. Search normalization is limited to Unicode NFC, case folding and whitespace. A trailing numeric or Roman pitch/rank expression may be separated for retrieval; the original label remains in the evidence record.

The complete source SQLite is not committed. `scripts/graphics/import-modavis.py` rebuilds the projection after the source database and the accompanying Zenodo metadata files have been placed in `services/graphics/corpus/`. The script checks the expected source digest and refuses to replace an existing projection implicitly.

## Development checks

Node.js 22.13 or newer is required for the web application. Tesseract is provided by the graphics container.

```bash
npm ci
npm run lint
npx tsc --noEmit
npm run build
docker compose build
docker compose config --quiet
```

Run the read-only detector regression inside the built graphics image:

```bash
docker run --rm -e PYTHONPATH=/app \
  --mount "type=bind,source=$PWD/scripts/graphics/test-pipeline.py,target=/checks.py,readonly" \
  --entrypoint python modavis-scriptor-graphics:0.1.0 /checks.py
```

The API integration test writes review events and therefore refuses the normal ports. Instructions for an isolated test instance are in [`docs/VALIDATION.md`](docs/VALIDATION.md).

## Repository documentation

- [`docs/INSTALLATION.md`](docs/INSTALLATION.md): operating systems, native development, backups, upgrades and troubleshooting
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): service boundaries, persistence and security assumptions
- [`docs/METHOD.md`](docs/METHOD.md): detection, OCR, corpus retrieval and human review method
- [`docs/CORPUS_REBUILD.md`](docs/CORPUS_REBUILD.md): source checksums and retrieval-projection reconstruction
- [`docs/DATA_AND_PROVENANCE.md`](docs/DATA_AND_PROVENANCE.md): schemas, fixity, event history and export contents
- [`docs/API.md`](docs/API.md): endpoints and request examples
- [`docs/VALIDATION.md`](docs/VALIDATION.md): executed checks and limits of the example
- [`docs/CITATION_AND_RIGHTS.md`](docs/CITATION_AND_RIGHTS.md): software, dataset and photograph citations
- [`SECURITY.md`](SECURITY.md): deployment boundary and vulnerability reporting

## Citation and rights

Release citation metadata is provided in [`CITATION.cff`](CITATION.cff). The reserved release DOI is <https://doi.org/10.5281/zenodo.22284008>.

The software and original documentation are licensed under CC BY 4.0. Bundled and referenced material retains its own license:

- photograph: Tucker501, *Organ-stops.jpg*, Wikimedia Commons, CC BY-SA 4.0;
- MODAVIS POD database arrangement and documentation: CC BY 4.0, where rights apply;
- Tesseract `tessdata_best` model files: Apache License 2.0;
- software dependencies: their respective upstream licenses.

See [`LICENSE`](LICENSE) and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). A license attached to this repository does not replace the attribution or share-alike terms of the photograph.
