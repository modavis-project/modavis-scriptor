# Installation and operation

## Supported deployment

Docker Compose is the reference deployment. For the historical 0.1.0 release, the web and processing images were built and tested as Linux arm64 and Linux amd64 containers; local amd64 checks used emulation on Apple Silicon. Current development validation is recorded separately in `VALIDATION.md`. The source contains no host-specific absolute runtime paths. Performance and generated timestamps differ by processor.

Windows users should run Docker Desktop with the WSL 2 backend and execute the commands from PowerShell or a WSL shell in a local filesystem checkout. Very slow builds commonly result from keeping the checkout on a network share.

The maintained development workflows, portable Windows commands and isolated macOS runtime are in `DEVELOPMENT.md`. On a Windows/WSL2 host, `powershell -File scripts/dev/check-wsl.ps1` checks the actual default WSL kernel, Linux Docker engine and Compose configuration. Then run the integration suite from a checkout inside the WSL Linux filesystem. Native Windows CI is distinct from a manually executed WSL installation test.

## First start

```bash
git clone https://github.com/modavis-project/modavis-scriptor.git
cd modavis-scriptor
docker compose up --build --detach
```

The first build downloads Node, Python and Debian packages. The application then starts at <http://127.0.0.1:3000>. No API key or GPU is required.

The example is copied into the persistent volume only when its run identifier does not already exist. Restarting does not reset reviews. New source files in a rebuilt image do not overwrite evidence from an existing completed run.

## Backup and restore

For the current development version, use the verified snapshot/rehearsal/non-overwriting tools in `BACKUP.md`. The stopped-service tar procedure below remains a pre-upgrade fallback for historical 0.1.0 installations whose image does not contain the new backup module.

Create a consistent backup while the graphics service is stopped:

```bash
docker compose stop graphics
docker run --rm \
  --mount source=modavis-scriptor-graphics-data,target=/data,readonly \
  --mount "type=bind,source=$PWD,target=/backup" \
  alpine:3.22 tar -C /data -czf /backup/modavis-scriptor-data.tar.gz .
docker compose start graphics
```

Restore into a new empty volume:

```bash
if docker volume inspect modavis-scriptor-graphics-data >/dev/null 2>&1; then
  echo "Restore refused: the target volume already exists. Preserve it before choosing a restore target."
else
  docker volume create modavis-scriptor-graphics-data && \
  docker run --rm \
    --mount source=modavis-scriptor-graphics-data,target=/data \
    --mount "type=bind,source=$PWD,target=/backup,readonly" \
    alpine:3.22 tar -C /data -xzf /backup/modavis-scriptor-data.tar.gz
fi
```

Keep the archive outside the Git repository. It may contain copyrighted source images and reviewer-identifying data.

Rehearse restores in a separate Docker context or explicitly separate volume configuration. Never extract a backup over an existing research volume, and verify evidence/database integrity before resuming reviews.

## Upgrade

1. Export important runs and back up the named volume.
2. Stop the services with `docker compose down`.
3. Check out the intended version or tag.
4. Run `docker compose build --pull`.
5. Start with `docker compose up --detach` and check both health endpoints.

Do not use `--volumes` during a normal upgrade.

## Development environment

Use Node 22.23.4 from `.nvmrc`, Docker with Compose, and Python 3.9 or newer for the dependency-free host check scripts. The graphics container supplies Python 3.12, Tesseract 5 and both OCR language sets. No API key, GPU or full MODAVIS source database is required.

With nvm installed, run `nvm install` and `nvm use` in the checkout. If a different Node version is the system default and no version manager is installed, run commands through the pinned npm package, for example:

```bash
npm exec --yes --package=node@22.23.4 -- npm ci
npm exec --yes --package=node@22.23.4 -- npm run doctor
```

Use the same prefix for subsequent npm/npx commands. This selects the project runtime without changing the system Node installation.

The prerequisite checker is read-only. It verifies Node, installed web dependencies, bundled evidence/corpus/models, Docker's server response and Compose configuration. It reports missing prerequisites with corrective commands; a running Docker client alone is insufficient.

## Frontend reload with separate backend data

This setup avoids sharing an existing research application's ports or volume:

```bash
npm ci
npm run doctor
docker compose -f compose.dev.yaml up --build --detach --wait
GRAPHICS_API_URL=http://127.0.0.1:8410 npm run dev -- --port 3400
```

Open <http://127.0.0.1:3400>. The development API is at <http://127.0.0.1:8410/docs>. Its Compose project is `modavis-scriptor-development`, with a separate `graphics-dev-data` volume. The native web process reloads frontend source. After changing Python modules or bundled assets, rerun `docker compose -f compose.dev.yaml up --build --detach --wait`; unchanged dependency layers are cached. The backend does not mount the host virtual environment or data directory. `SCRIPTOR_DEV_API_PORT` changes the API's host port; set `GRAPHICS_API_URL` to the matching URL when starting the web process.

Stop the web process with Ctrl-C and the development backend with `docker compose -f compose.dev.yaml down`. Its data persists. Research deployment still uses `compose.yaml`; keep the two projects and data volumes separate.

## Completely native backend (optional)

Install Python 3.12, Tesseract 5 and its German/English fast language models using your operating system's package manager. Then:

```bash
python3 scripts/dev/setup-native.py
npm run doctor -- --native
TESSDATA_PREFIX="$PWD/services/graphics/.venv/tessdata" GRAPHICS_DATA="$PWD/services/graphics/data" services/graphics/.venv/bin/python -m uvicorn app:app --app-dir services/graphics --host 127.0.0.1 --port 8410
```

The setup script creates/validates the Python 3.12 environment, installs the lockfile, and downloads only English/German fast models from upstream commit `87416418657359cb625c412a48b6e1d6d41c29bd`, verifying their pinned SHA-256 values. The environment and downloaded models are ignored by Git. It does not install system packages. On macOS, `brew install tesseract` supplies the executable; the helper supplies the two language files without the large all-language package.

Use the same frontend command as above. The native data directory is ignored by Git and is independent of Docker volumes. Models in `models/best` are bundled; fast models are resolved from the active Tesseract tessdata directory and their checksums are recorded. `doctor --native` and the native validation runner select the managed fast model directory automatically when it exists; manual backend launches must set `TESSDATA_PREFIX` as shown.

Restart this native backend after Python changes.

## Development validation

```bash
npm run check
npx playwright install chromium firefox webkit
npm run test:integration
```

On Linux, Playwright may need `npx playwright install --with-deps chromium firefox webkit`. The integration runner uses a randomly named Compose project, free loopback ports and fresh disposable data. It runs asset, backend/migration/reliability, real OCR, upload/API, proxy and all three browser-engine checks, then removes only its own containers and volumes even on failure. `--no-build` reuses the test images; `--skip-browser` explicitly runs a reduced suite. See `VALIDATION.md` and `DEVELOPMENT.md` for full host prerequisites and contract/workflow checks.

For an entirely native test stack, run `npm run test:integration -- --native`. It uses the prepared Python/Tesseract environment and Wrangler on free ports with temporary state, and stops its own processes afterwards. `--native --no-build` reuses the host web build. CI exercises Linux amd64/arm64 containers and native Windows separately.

## Troubleshooting

### The web interface reports that the graphics service is unavailable

Run `docker compose ps` and `docker compose logs graphics`. Port changes affect the host URL only; the internal web service must continue to use `http://graphics:8010`.

### A build runs out of disk space

Check `docker system df`. Remove only unused build cache or images. Do not remove the `modavis-scriptor-graphics-data` volume unless its contents have been exported or are intentionally disposable.

### An image is accepted but no useful region appears

The organ-stop detector targets light, low-saturation label surfaces. Adjust brightness, saturation and minimum area, or draw normalized regions manually. Use general graphics mode for isolated visible text that is not printed on stop labels.

### OCR uses the wrong language

Choose `deu`, `eng`, `deu+eng` or `eng+deu` before creating the new run. Changing the interface setting does not modify a completed result; use reprocessing to create a child run.

### A decision returns HTTP 409

Another decision exists for that region version. In the interface, compare the newer decision with the retained draft and explicitly rebase before submitting. API clients must inspect the newer event and submit a decision with the current `expected_version`.

HTTP 409 can also indicate missing or changed evidence. Inspect the returned message and restore the exact original artifact from a verified backup. Do not edit result JSON or replace stored digests to bypass the check. Historical non-example runs may have incomplete artifact coverage; their raw results remain unchanged and unverifiable OCR files are excluded from exports.

### Docker reports starting indefinitely

Check `docker desktop status` (Docker Desktop) and `docker version`. Wait for a server version before running builds. If startup is stuck, use Docker Desktop diagnostics/restart after accounting for other running workloads. The project checker times out and reports the failure; it never resets Docker or deletes volumes.
