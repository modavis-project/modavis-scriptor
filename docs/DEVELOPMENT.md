# Development workflow

Use Node 22.23.4 from `.nvmrc`. If no version manager is installed, prefix npm commands with `npm exec --yes --package=node@22.23.4 --`. The npm Python launcher selects the managed Python environment when present and works with Windows `python.exe`; `SCRIPTOR_PYTHON` can select an explicit executable.

Full host contract/workflow checks need the locked Python dependencies. A Docker-only developer can create `services/graphics/.venv` with Python 3.12 and install `services/graphics/requirements.lock` there without installing host Tesseract. For entirely native OCR, use `scripts/dev/setup-native.py` after installing Tesseract as described below. CI prepares these dependencies explicitly; the workflow preview tests use Pillow, while scorer-only tests use the standard library.

## Isolated Docker on macOS

The optional Colima runtime keeps Scriptor's containers, images and volumes in `~/.modavis-scriptor-runtime` on direct local APFS storage. It does not move Docker Desktop data, delete other projects, or change the global Docker context. Install Colima and the Docker CLI if needed, then:

```bash
npm ci
npm run runtime -- start
npm run runtime -- exec -- npm run doctor
npm run runtime -- exec -- npm run test:integration
```

The profile uses four CPUs, 4 GiB memory, a 32 GiB data disk and a 12 GiB root disk by default. These are virtual limits, not immediate physical allocation. `runtime status` reports the physical backing filesystem and capacity. Start refuses unrelated runtime directories/context collisions, long socket paths, nested disk images, or unsuitable storage. `runtime stop` stops only this VM and preserves its data.

Start the separate development backend and native frontend:

```bash
npm run runtime -- exec -- docker compose -f compose.dev.yaml up --build --detach --wait
GRAPHICS_API_URL=http://127.0.0.1:8410 npm run dev -- --port 3400
```

Open <http://127.0.0.1:3400>. The API is at <http://127.0.0.1:8410/docs>. Python changes require rebuilding the development backend; the native frontend reloads automatically. Stop the backend with the same runtime prefix and `docker compose -f compose.dev.yaml down`.

The dedicated context is `colima-scriptor`. `runtime exec` sets `SCRIPTOR_DOCKER_CONTEXT`/`DOCKER_CONTEXT` only in the child environment. Existing Linux/Docker Desktop users can instead set `SCRIPTOR_DOCKER_CONTEXT` explicitly or use their current engine without this helper. This macOS helper is not required on Linux or Windows.

## Native backend

Install Python 3.12 and Tesseract 5, then run `python scripts/dev/setup-native.py` with the Python 3.12 interpreter (`python3` on typical macOS/Linux installations). It installs the complete locked environment and verifies English/German fast model downloads. `npm run doctor -- --native` checks the result.

On macOS/Linux:

```bash
TESSDATA_PREFIX="$PWD/services/graphics/.venv/tessdata" GRAPHICS_DATA="$PWD/services/graphics/data" services/graphics/.venv/bin/python -m uvicorn app:app --app-dir services/graphics --host 127.0.0.1 --port 8410
```

On Windows PowerShell after installing Tesseract and Python 3.12:

```powershell
python scripts/dev/setup-native.py
$env:TESSDATA_PREFIX = (Resolve-Path services/graphics/.venv/tessdata).Path
$env:GRAPHICS_DATA = Join-Path (Get-Location) services/graphics/data
services/graphics/.venv/Scripts/python.exe -m uvicorn app:app --app-dir services/graphics --host 127.0.0.1 --port 8410
```

Set `GRAPHICS_API_URL` to `http://127.0.0.1:8410` in the frontend terminal. Native data is ignored by Git. Restart the Python service after source changes. Never share one data directory between two live Scriptor processes; ownership locking rejects this.

## API contracts and UI changes

Response/request models live in `services/graphics/contracts.py`. FastAPI uses these models directly. `scripts/contracts/generate.py` derives the TypeScript schema/types from actual OpenAPI and rejects unsupported schema features. Generated output is committed in `lib/graphics/contracts.generated.ts`; runtime validation and the API client reject malformed or incompatible responses.

```bash
npm run contracts:generate
npm run contracts:check
npm run test:contracts
```

Generation needs the locked Python dependencies; use the managed environment or an equivalent installed environment. Edit the Pydantic model and regenerate rather than editing generated types. CI checks generation drift and both Python/runtime validation.

`components/graphics-workbench.tsx` composes configuration, upload, evidence, queue, review and output panels. `lib/graphics/use-workbench.ts` owns loading/navigation state. Region drafts are held in memory for the current run, and region navigation preserves them. Switching runs or reloading the page starts from saved reviews. A stale review retains the draft until the reviewer explicitly compares and rebases it on the current server version. Markdown loads separately from the initial review UI.

## Validation and diagnostics

```bash
npm run check
npm run contracts:check
npm run test:contracts
npm run test:dev
npm run test:evaluation
npx playwright install chromium firefox webkit
npm run test:integration -- --native
```

Use `npm run runtime -- exec -- npm run test:integration` for the isolated Docker path. The runner exercises process cleanup, assets, backend integrity/migrations, real OCR, crash/restart, concurrency, backups/restores, bounded-memory transfers, upload/API and three browser engines. Each browser uses its own child run; the frozen seed stays unreviewed. Service diagnostics can be retained with `--log-dir`, and failed browser traces/screenshots are ignored by Git.

CI independently runs quality/audits/contracts/evaluation, full Linux amd64 and arm64 container/browser jobs, and a Windows native job. Windows Tesseract is downloaded from the official release asset with a pinned digest. Native Windows testing is distinct from running Docker Desktop's WSL 2 backend; follow `INSTALLATION.md` for WSL deployment and do not treat a native Windows pass as a WSL installation test.

On a real Windows/WSL2 host, `powershell -File scripts/dev/check-wsl.ps1` performs the prerequisite checks before the actual Linux integration run. The script does not install a distribution, reset Docker or change storage/context settings.

Backup operations and recognition research have separate instructions in `BACKUP.md` and `EVALUATION.md`.
