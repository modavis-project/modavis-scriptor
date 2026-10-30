"""Own validation children and their descendants without signalling unrelated services."""
import ctypes
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


class WindowsJob:
    """A kill-on-close Windows Job Object; inherited by every launched descendant."""
    def __init__(self):
        from ctypes import wintypes
        size_t = ctypes.c_size_t

        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", wintypes.DWORD), ("minimum", size_t), ("maximum", size_t),
                        ("processes", wintypes.DWORD), ("affinity", size_t),
                        ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

        class Limits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", ctypes.c_ulonglong * 6),
                        ("process_memory", size_t), ("job_memory", size_t),
                        ("peak_process_memory", size_t), ("peak_job_memory", size_t)]

        class Accounting(ctypes.Structure):
            _fields_ = [("times", ctypes.c_longlong * 4), ("faults", wintypes.DWORD),
                        ("total", wintypes.DWORD), ("active", wintypes.DWORD), ("terminated", wintypes.DWORD)]

        self.accounting = Accounting

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.SetInformationJobObject.restype = wintypes.BOOL
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.api.TerminateJobObject.restype = wintypes.BOOL
        self.api.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        self.api.QueryInformationJobObject.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.api.OpenProcess.restype = wintypes.HANDLE
        self.api.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        self.api.IsProcessInJob.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Limits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def attach(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def contains(self, pid):
        if not self.handle:
            return False
        from ctypes import wintypes
        handle = self.api.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            if ctypes.get_last_error() == 87:  # The process has already exited.
                return False
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            member = wintypes.BOOL()
            if not self.api.IsProcessInJob(handle, self.handle, ctypes.byref(member)):
                raise ctypes.WinError(ctypes.get_last_error())
            return bool(member.value)
        finally:
            self.api.CloseHandle(handle)

    def close(self):
        if self.handle:
            try:
                if not self.api.TerminateJobObject(self.handle, 1):
                    raise ctypes.WinError(ctypes.get_last_error())
                deadline = time.monotonic() + 5
                while True:
                    info = self.accounting()
                    if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
                        raise ctypes.WinError(ctypes.get_last_error())
                    if info.active == 0:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Owned Windows process tree did not terminate")
                    time.sleep(.01)
            finally:
                self.api.CloseHandle(self.handle)
                self.handle = None


def executable_command(command):
    """Run npm through Node on Windows, avoiding batch-shell quoting and .cmd execution."""
    command = [str(part) for part in command]
    if os.name == "nt" and command[0] in {"npm", "npx"}:
        executable = shutil.which(command[0])
        if not executable:
            raise FileNotFoundError(f"{command[0]} is not installed")
        cli = Path(executable).parent / "node_modules/npm/bin" / (command[0] + "-cli.js")
        if not cli.is_file():
            raise RuntimeError("Cannot locate npm's JavaScript entry point; install the Node version in .nvmrc")
        return [shutil.which("node") or "node", str(cli), *command[1:]]
    return command


def spawn(command, **kwargs):
    """Start an owned POSIX session or a gated Windows job, then release its command."""
    command = executable_command(command)
    job = None
    if os.name == "nt":
        job = WindowsJob()
        # The wrapper cannot create a child until it has joined the job. This
        # closes the assignment race and works after the wrapper itself exits.
        # A Windows venv python.exe redirects to another interpreter process.
        # Use the real base executable for this stdlib-only gate so no child can
        # appear outside the job before AssignProcessToJobObject finishes.
        gate_python = getattr(sys, "_base_executable", None) or sys.executable
        command = [gate_python, str(Path(__file__).with_name("process-child.py")), *command]
        kwargs.update(stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs.update(start_new_session=True)
    try:
        process = subprocess.Popen(command, **kwargs)
        process._scriptor_owned = True
        process._scriptor_job = job
        process._scriptor_stopped = False
        if job is not None:
            try:
                job.attach(process)
                process.stdin.write(b"G")
                process.stdin.close()
                process.stdin = None
            except BaseException:
                process.kill()
                process.wait(timeout=5)
                raise
        return process
    except BaseException:
        if job is not None:
            job.close()
        raise


def stop_process(process, timeout=10):
    """Terminate only an owned tree, including descendants whose leader already exited."""
    if not getattr(process, "_scriptor_owned", False):
        raise ValueError("Refusing to stop a process not created by this validation runner")
    if process._scriptor_stopped:
        return
    job = process._scriptor_job
    if job is not None:
        job.close()  # Windows atomically terminates every remaining job member.
        process.wait(timeout=5)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass
        # A shell/launcher can exit before its children. Always finish its group.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
    process._scriptor_stopped = True


def owns_process(process, pid):
    """Prove a PID is in this private session/job, including Windows launchers."""
    if not getattr(process, "_scriptor_owned", False):
        raise ValueError("Refusing to inspect a process not created by this validation runner")
    if process._scriptor_stopped:
        return False
    if process._scriptor_job is not None:
        return process._scriptor_job.contains(pid)
    try:
        return os.getpgid(pid) == process.pid
    except ProcessLookupError:
        return False


def kill_process(process):
    """Abruptly kill an owned tree for crash tests, without graceful shutdown."""
    if not getattr(process, "_scriptor_owned", False):
        raise ValueError("Refusing to kill a process not created by this validation runner")
    if process._scriptor_stopped:
        return
    if process._scriptor_job is not None:
        # close() terminates the entire job and waits for its active count to reach zero.
        process._scriptor_job.close()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)
    process._scriptor_stopped = True


def process_running(pid):
    """Check whether a recorded private worker is still executing after a crash."""
    if os.name == "nt":
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        api.GetExitCodeProcess.restype = wintypes.BOOL
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.CloseHandle.restype = wintypes.BOOL
        handle = api.OpenProcess(0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return False
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            code = wintypes.DWORD()
            if not api.GetExitCodeProcess(handle, ctypes.byref(code)):
                raise ctypes.WinError(ctypes.get_last_error())
            return code.value == 259  # STILL_ACTIVE
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        if sys.platform.startswith("linux"):
            # A dead orphan can remain a zombie briefly before init reaps it.
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
            return state != "Z"
        return True
    except (ProcessLookupError, FileNotFoundError):
        return False
