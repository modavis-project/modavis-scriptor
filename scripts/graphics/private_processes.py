"""Use the validation runner's process ownership in native and container tests."""
from pathlib import Path
import importlib.util

helpers = Path(__file__).resolve().parents[1] / "dev"
if not (helpers / "processes.py").is_file():
    helpers = Path("/dev-checks")
if not (helpers / "processes.py").is_file():
    raise RuntimeError("Mount scripts/dev at /dev-checks when running isolated tests in a container")
# Do not add scripts/dev to sys.path: its storage diagnostics module must never
# shadow the backend's evidence/storage module during a later app import.
spec = importlib.util.spec_from_file_location("scriptor_test_processes", helpers / "processes.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
kill_process = module.kill_process
owns_process = module.owns_process
process_running = module.process_running
spawn = module.spawn
stop_process = module.stop_process
