#!/usr/bin/env python3
"""Real process-tree cleanup regressions, using private children and temporary files."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from processes import spawn, stop_process


CHILD = """
import os,signal,sys,time
from pathlib import Path
if os.name == 'posix': signal.signal(signal.SIGTERM,signal.SIG_IGN)
path=Path(sys.argv[1])
while True:
    with path.open('ab') as log: log.write(b'.')
    time.sleep(.03)
"""
PARENT = """
import subprocess,sys,time
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[1]])
Path(sys.argv[1]+'.pid').write_text(str(child.pid))
if sys.argv[3] == 'wait': time.sleep(120)
"""


class ProcessCleanup(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="scriptor-process-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # This deliberately unrelated test-owned process must survive tree cleanup.
        self.sentinel = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(120)"])
        self.addCleanup(self.stop_sentinel)

    def stop_sentinel(self):
        self.sentinel.terminate()
        self.sentinel.wait(timeout=5)

    def tree(self, mode="wait"):
        heartbeat = self.root / "heartbeat"
        process = spawn([sys.executable, "-c", PARENT, str(heartbeat), CHILD, mode])
        self.addCleanup(stop_process, process, .1)
        deadline = time.monotonic() + 10
        while not heartbeat.exists() or heartbeat.stat().st_size < 2:
            if time.monotonic() > deadline:
                self.fail("Private grandchild did not become ready")
            time.sleep(.03)
        return process, heartbeat

    def assert_stopped(self, process, heartbeat):
        stop_process(process, .1)
        size = heartbeat.stat().st_size
        time.sleep(.15)
        self.assertEqual(heartbeat.stat().st_size, size, "Grandchild kept running after cleanup")
        self.assertIsNone(self.sentinel.poll(), "Cleanup reached an unrelated process")
        stop_process(process, .1)  # Idempotent cleanup must never signal a reused PID.

    def test_stops_child_and_term_ignoring_grandchild(self):
        process, heartbeat = self.tree()
        self.assert_stopped(process, heartbeat)

    def test_stops_descendants_after_their_parent_exits(self):
        process, heartbeat = self.tree("exit")
        self.assertEqual(process.wait(timeout=5), 0)
        self.assert_stopped(process, heartbeat)

    def test_timeout_cleanup_still_stops_complete_tree(self):
        process, heartbeat = self.tree()
        with self.assertRaises(subprocess.TimeoutExpired):
            process.wait(timeout=.05)
        self.assert_stopped(process, heartbeat)

    def test_refuses_unowned_process(self):
        with self.assertRaisesRegex(ValueError, "not created"):
            stop_process(self.sentinel)
        self.assertIsNone(self.sentinel.poll())

    def test_windows_launch_gate_cannot_start_before_job_assignment(self):
        marker = self.root / "must-not-exist"
        child = Path(__file__).with_name("process-child.py")
        command = [sys.executable, str(child), sys.executable, "-c", "from pathlib import Path;import sys;Path(sys.argv[1]).touch()", str(marker)]
        result = subprocess.run(command, stdin=subprocess.DEVNULL, timeout=5)
        self.assertEqual(result.returncode, 125)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
