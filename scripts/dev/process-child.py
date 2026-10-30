#!/usr/bin/env python3
"""Internal Windows launch gate: never spawn before the owner attaches its job."""
import subprocess
import sys

if sys.stdin.buffer.read(1) != b"G":
    raise SystemExit(125)
raise SystemExit(subprocess.call(sys.argv[1:], stdin=subprocess.DEVNULL))
