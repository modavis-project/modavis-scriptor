#!/usr/bin/env python3
"""Build and test a disposable stack; never mount the research data volume."""
import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def stop_process(process):
    """Stop only this runner's child session, including test/service descendants."""
    def send(sig):
        try:
            if os.name == "posix":
                os.killpg(process.pid, sig)
            elif process.poll() is None:
                process.terminate() if sig == signal.SIGTERM else process.kill()
        except ProcessLookupError:
            pass

    send(signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        send(signal.SIGKILL)
        process.wait(timeout=5)


def interrupted(_signal, _frame):
    raise KeyboardInterrupt


def free_port():
    while True:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            if port > 1024 and port not in {3000, 3080, 8010, 8080}:
                return port


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-build", action="store_true", help="reuse the development-test images")
    parser.add_argument("--skip-browser", action="store_true", help="explicitly omit Playwright coverage")
    parser.add_argument("--native", action="store_true", help="use the optional Python/Tesseract environment and built web server")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupted)
    if not args.native and not shutil.which("docker"):
        parser.error("Docker is required; run npm run doctor.")
    environment = os.environ.copy()
    api_port, web_port = free_port(), free_port()
    while api_port == web_port:
        web_port = free_port()
    environment.update(SCRIPTOR_TEST_API_PORT=str(api_port), SCRIPTOR_TEST_WEB_PORT=str(web_port),
                       SCRIPTOR_TEST_API_URL=f"http://127.0.0.1:{api_port}",
                       SCRIPTOR_TEST_BASE_URL=f"http://127.0.0.1:{web_port}")
    project = "scriptor-check-" + uuid.uuid4().hex[:12]
    compose = ["docker", "compose", "--project-name", project, "--file", "compose.test.yaml"]

    def run(command, timeout=1200):
        print("\n+ " + " ".join(command), flush=True)
        process = subprocess.Popen(command, cwd=ROOT, env=environment, start_new_session=os.name == "posix")
        try:
            status = process.wait(timeout=timeout)
        except BaseException:
            stop_process(process)
            raise
        if status:
            stop_process(process)
            raise subprocess.CalledProcessError(status, command)

    if args.native:
        python = ROOT / "services/graphics/.venv/bin/python"
        if not python.exists() or not shutil.which("tesseract"):
            parser.error("Run scripts/dev/setup-native.py first (requires Python 3.12 and Tesseract 5).")
        environment["PYTHONPATH"] = str(ROOT / "services/graphics")
        models = ROOT / "services/graphics/.venv/tessdata"
        if models.is_dir():
            environment.setdefault("TESSDATA_PREFIX", str(models))
        processes, logs = [], []

        def start(command, directory, log):
            process = subprocess.Popen(command, cwd=directory, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=os.name == "posix")
            processes.append(process)
            return process

        def ready(url, process):
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Test service exited before readiness: {url}")
                try:
                    with opener.open(url, timeout=2) as response:
                        if response.status == 200:
                            return
                except OSError:
                    pass
                time.sleep(.2)
            raise RuntimeError(f"Test service readiness timed out: {url}")

        with tempfile.TemporaryDirectory(prefix="scriptor-native-check-") as directory:
            temporary = Path(directory)
            environment.update(GRAPHICS_DATA=str(temporary / "data"), SCRIPTOR_DISPOSABLE_TEST="1")
            try:
                run([sys.executable, "scripts/graphics/verify-assets.py"], 120)
                run([str(python), "scripts/graphics/test-backend.py"])
                run([str(python), "scripts/graphics/test-pipeline.py"])
                if not args.no_build:
                    run(["npm", "run", "build"])
                for name in ("graphics.log", "web.log"):
                    log = (temporary / name).open("w+")
                    logs.append(log)
                api = start([str(python), "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(api_port)],
                            ROOT / "services/graphics", logs[0])
                ready(environment["SCRIPTOR_TEST_API_URL"] + "/health", api)
                web = start([str(ROOT / "node_modules/.bin/wrangler"), "dev", "--config", "dist/server/wrangler.json",
                             "--ip", "127.0.0.1", "--port", str(web_port), "--persist-to", str(temporary / "web-state"),
                             "--var", "GRAPHICS_API_URL:" + environment["SCRIPTOR_TEST_API_URL"]], ROOT, logs[1])
                ready(environment["SCRIPTOR_TEST_BASE_URL"] + "/api/health", web)
                run([sys.executable, "scripts/graphics/test-api.py", environment["SCRIPTOR_TEST_API_URL"]])
                if not args.skip_browser:
                    run(["npm", "run", "test:browser"])
                print("\nPassed isolated native backend, OCR, API" + (", and browser checks." if not args.skip_browser else " checks; browser checks explicitly skipped."), flush=True)
                return 0
            except (subprocess.SubprocessError, OSError, RuntimeError) as error:
                print(f"\nNative validation failed: {error}", file=sys.stderr, flush=True)
                for log in logs:
                    log.flush()
                    log.seek(0)
                    print("\n".join(log.read().splitlines()[-80:]), file=sys.stderr)
                return 1
            finally:
                for process in reversed(processes):
                    stop_process(process)
                for log in logs:
                    log.close()

    started = False
    try:
        run([sys.executable, "scripts/graphics/verify-assets.py"], 120)
        run(compose + ["config", "--quiet"], 30)
        # Cleanup is scoped by this random project name, including failed starts.
        started = True
        if not args.no_build:
            # Both cold dependency installs write many files. Build separately
            # to avoid competing for the Docker VM's disk on developer laptops.
            run(compose + ["build", "graphics"], 3600)
            run(compose + ["build", "web"], 3600)
        up = compose + ["up", "--detach", "--wait", "--wait-timeout", "180"]
        run(up)
        run(compose + ["exec", "-T", "graphics", "python", "/checks/test-backend.py"])
        run(compose + ["exec", "-T", "graphics", "python", "/checks/test-pipeline.py"])
        run([sys.executable, "scripts/graphics/test-api.py", environment["SCRIPTOR_TEST_API_URL"]])
        if not args.skip_browser:
            run(["npm", "run", "test:browser"])
        print("\nPassed isolated backend, OCR, API" + (", and browser checks." if not args.skip_browser else " checks; browser checks explicitly skipped."), flush=True)
        return 0
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"\nValidation failed: {error}", file=sys.stderr, flush=True)
        if started:
            try:
                run(compose + ["logs", "--no-color", "--tail", "80"], 30)
            except (subprocess.SubprocessError, OSError):
                pass
        return 1
    finally:
        if started:
            run(compose + ["down", "--volumes", "--remove-orphans", "--timeout", "10"], 60)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
