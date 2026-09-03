# Installation and operation

## Supported deployment

Docker Compose is the reference deployment for version 0.1.0. The web and processing images have been built and tested as Linux arm64 and Linux amd64 containers. The amd64 checks ran under emulation on Apple Silicon. The source contains no host-specific absolute runtime paths. Performance and generated timestamps differ by processor.

Windows users should run Docker Desktop with the WSL 2 backend and execute the commands from PowerShell or a WSL shell in a local filesystem checkout. Very slow builds commonly result from keeping the checkout on a network share.

## First start

```bash
git clone https://github.com/modavis-project/modavis-scriptor.git
cd modavis-scriptor
docker compose up --build --detach
```

The first build downloads Node, Python and Debian packages. The application then starts at <http://127.0.0.1:3000>. No API key or GPU is required.

The example is copied into the persistent volume only when its run identifier does not already exist. Restarting does not reset reviews. New source files in a rebuilt image do not overwrite evidence from an existing completed run.

## Backup and restore

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
docker volume create modavis-scriptor-graphics-data
docker run --rm \
  --mount source=modavis-scriptor-graphics-data,target=/data \
  --mount "type=bind,source=$PWD,target=/backup,readonly" \
  alpine:3.22 tar -C /data -xzf /backup/modavis-scriptor-data.tar.gz
```

Keep the archive outside the Git repository. It may contain copyrighted source images and reviewer-identifying data.

## Upgrade

1. Export important runs and back up the named volume.
2. Stop the services with `docker compose down`.
3. Check out the intended version or tag.
4. Run `docker compose build --pull`.
5. Start with `docker compose up --detach` and check both health endpoints.

Do not use `--volumes` during a normal upgrade.

## Native web development

```bash
npm ci
npm run dev
```

The web process expects the graphics API at `http://127.0.0.1:8010`. Start that service with Compose, or run the Python service from `services/graphics` with Python 3.12, Tesseract 5 and the locked Python dependencies. Set `GRAPHICS_API_URL` only when the processing service uses another address.

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

Another decision exists for that region version. Reload the run, inspect the newer event and submit a decision with the current `expected_version`.
