#!/usr/bin/env python3
"""Trust-boundary tests for storage diagnostics and explicit local runtime tools.

Only temporary paths and mocked infrastructure commands are used. No Docker or
Colima VM is started, stopped, selected or inspected by these tests. The Python
launcher tests execute a real, temporary Unicode Python script through Node.
"""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import environment
import runtime
import storage

ROOT = Path(__file__).resolve().parents[2]


class PhysicalStorage(unittest.TestCase):
    def test_nested_images_use_longest_mount_then_real_backing_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            outer, inner = root / "outer", root / "outer/inner"
            work = inner / "work"
            work.mkdir(parents=True)
            inner_backing, physical_backing = outer / "inner.sparseimage", root / "physical.sparsebundle"
            inner_backing.touch()
            physical_backing.touch()
            images = [
                {"image-path": str(physical_backing), "system-entities": [{"mount-point": str(outer)}]},
                {"image-path": str(inner_backing), "system-entities": [{"mount-point": str(inner)}]},
            ]
            self.assertEqual(storage.image_backing_path(work, images), inner_backing)
            usage = SimpleNamespace(total=100 * storage.GIB, used=95 * storage.GIB, free=5 * storage.GIB)
            with patch.object(storage.sys, "platform", "linux"), patch.object(storage.shutil, "disk_usage", return_value=usage) as inspect, patch.object(storage.subprocess, "run", side_effect=AssertionError("Unexpected infrastructure command")):
                result = storage.physical_storage(work / "not-created/cache", images=images)
            inspect.assert_called_once_with(physical_backing)
            self.assertEqual(result["backing_chain"], [str(work), str(inner_backing), str(physical_backing)])
            self.assertEqual(result["free_gib"], 5)
            self.assertEqual(result["used_percent"], 95)
            self.assertFalse((work / "not-created").exists())

    def test_similar_mount_prefix_is_not_a_containing_filesystem(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            images = [{"image-path": str(root / "backing"), "system-entities": [{"mount-point": str(root / "data")}]}]
            self.assertIsNone(storage.image_backing_path(root / "database/large.raw", images))
            self.assertEqual(storage.image_backing_path(root / "data/large.raw", images), root / "backing")


class RuntimeOwnership(unittest.TestCase):
    def test_unknown_marker_and_unmarked_nonempty_directory_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            marker = home / ".owner.json"
            marker.write_text('{"schema":"foreign-owner"}', encoding="utf-8")
            before = marker.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "different runtime"):
                runtime.owner(home)
            self.assertEqual(marker.read_bytes(), before)
            marker.unlink()
            unrelated = home / "do-not-touch.txt"
            unrelated.write_text("preserve me", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "unmarked"):
                runtime.owner(home)
            self.assertEqual(unrelated.read_text(), "preserve me")
            self.assertFalse(marker.exists())

    def test_colliding_context_is_refused_without_replacing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            response = subprocess.CompletedProcess([], 0, json.dumps([{"Name": runtime.CONTEXT, "Endpoints": {"docker": {"Host": "unix:///some-other-runtime/docker.sock"}}}]), "")
            with patch.object(runtime.subprocess, "run", return_value=response) as command:
                with self.assertRaisesRegex(RuntimeError, "another runtime"):
                    runtime.validate_context(home, required=True)
            self.assertEqual(command.call_count, 1)
            self.assertEqual(command.call_args.args[0], ["docker", "context", "inspect", runtime.CONTEXT])
            self.assertEqual(list(home.iterdir()), [])

    def test_explicit_context_selection_is_an_argument_and_does_not_mutate_environment(self):
        selected = {"SCRIPTOR_DOCKER_CONTEXT": "colima-scriptor", "DOCKER_CONTEXT": "desktop-linux"}
        before = selected.copy()
        self.assertEqual(environment.docker_command(selected), ["docker", "--context", "colima-scriptor"])
        self.assertEqual(selected, before)

    @unittest.skipIf(os.name == "nt", "Optional macOS orchestration uses POSIX socket paths")
    def test_status_of_absent_runtime_is_read_only(self):
        with tempfile.TemporaryDirectory(prefix="srt-", dir="/tmp") as directory:
            home = Path(directory) / "fresh"
            with patch.object(runtime.sys, "platform", "darwin"), patch.object(runtime.shutil, "which", return_value="/mock/tool"), patch.object(runtime.sys, "argv", ["runtime.py", "--home", str(home), "status"]), patch.object(runtime.subprocess, "run", side_effect=AssertionError("Absent status must not invoke infrastructure")), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runtime.main(), 0)
            self.assertFalse(home.exists())
            self.assertFalse(json.loads(output.getvalue())["ready"])

    @unittest.skipIf(os.name == "nt", "Optional macOS orchestration uses POSIX socket paths")
    def test_runtime_start_never_activates_or_changes_global_context(self):
        with tempfile.TemporaryDirectory(prefix="srt-", dir="/tmp") as directory:
            home = (Path(directory) / "owned").resolve()
            calls = []
            def fake_run(command, command_home, **_kwargs):
                calls.append(command)
                self.assertEqual(command_home, home)
                return SimpleNamespace(stdout="desktop-linux\n" if command == ["docker", "context", "show"] else "")
            capacity = {"backing_chain": [str(home)], "free_gib": 64, "filesystem": "apfs"}
            with patch.object(runtime.sys, "platform", "darwin"), patch.object(runtime.shutil, "which", return_value="/mock/tool"), patch.object(runtime.sys, "argv", ["runtime.py", "--home", str(home), "start"]), patch.object(runtime, "validate_context", return_value=True), patch.object(runtime, "physical_storage", return_value=capacity), patch.object(runtime, "run", side_effect=fake_run), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runtime.main(), 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["global_context_before"], "desktop-linux")
            self.assertEqual(report["global_context_after"], "desktop-linux")
            start = next(command for command in calls if command[:2] == ["colima", "start"])
            self.assertIn("--activate=false", start)
            self.assertFalse(any(command[:3] == ["docker", "context", "use"] for command in calls))

    @unittest.skipIf(os.name == "nt", "Optional macOS orchestration uses POSIX socket paths")
    def test_exec_selects_child_context_and_removes_child_docker_host_only(self):
        with tempfile.TemporaryDirectory(prefix="srt-", dir="/tmp") as directory:
            home = Path(directory).resolve()
            runtime.owner(home)
            configured = {"DOCKER_CONTEXT": "desktop-linux", "DOCKER_HOST": "tcp://untouched.example:2375", "SCRIPTOR_DOCKER_CONTEXT": "old-context"}
            with patch.dict(os.environ, configured), patch.object(runtime.sys, "platform", "darwin"), patch.object(runtime.shutil, "which", return_value="/mock/tool"), patch.object(runtime.sys, "argv", ["runtime.py", "--home", str(home), "exec", "--", "python", "--version"]), patch.object(runtime, "validate_context", return_value=True), patch.object(runtime.os, "execvpe") as execute:
                before = dict(os.environ)
                self.assertEqual(runtime.main(), 0)
                self.assertEqual(dict(os.environ), before)
            program, arguments, child = execute.call_args.args
            self.assertEqual((program, arguments), ("python", ["python", "--version"]))
            self.assertEqual(child["DOCKER_CONTEXT"], runtime.CONTEXT)
            self.assertEqual(child["SCRIPTOR_DOCKER_CONTEXT"], runtime.CONTEXT)
            self.assertEqual(child["COLIMA_HOME"], str(home))
            self.assertNotIn("DOCKER_HOST", child)


@unittest.skipUnless(shutil.which("node"), "Node is required for the portable Python launcher")
class PythonLauncher(unittest.TestCase):
    def launch(self, interpreter, *arguments):
        return subprocess.run([shutil.which("node"), str(ROOT / "scripts/dev/python.mjs"), *arguments],
                              env={**os.environ, "SCRIPTOR_PYTHON": str(interpreter)},
                              capture_output=True, text=True, encoding="utf-8", timeout=15)

    def test_explicit_interpreter_unicode_argument_path_and_child_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "read literal QA.py"
            script.write_text("import sys\nprint('Lesung: Ö – ⅓')\nprint(sys.executable)\nprint(sys.argv[1])\nsys.exit(7)\n", encoding="utf-8")
            result = self.launch(sys.executable, str(script), "literal value with spaces and Ö")
            self.assertEqual(result.returncode, 7, result.stderr)
            lines = result.stdout.splitlines()
            self.assertEqual(lines[0], "Lesung: Ö – ⅓")
            self.assertTrue(os.path.samefile(lines[1], sys.executable))
            self.assertEqual(lines[2], "literal value with spaces and Ö")

    def test_invalid_explicit_interpreter_fails_without_falling_back_to_managed_python(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.launch(Path(directory) / "not an executable", "-c", "print('MUST NOT RUN')")
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("MUST NOT RUN", result.stdout)
            self.assertIn("SCRIPTOR_PYTHON", result.stderr)


if __name__ == "__main__":
    unittest.main()
