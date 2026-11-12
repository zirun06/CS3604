"""Own deployment subprocesses even after the Git Bash launcher exits."""

import ctypes
from ctypes import wintypes
import os
import shutil
import subprocess
from time import monotonic, sleep

from infrastructure.utils.processes import child_environment, start_process, stop_process


class BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
        ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
        ("maximum_working_set", ctypes.c_size_t), ("active_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", BasicLimits), ("io_counters", ctypes.c_uint64 * 6),
        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]


class Accounting(ctypes.Structure):
    _fields_ = [("times", ctypes.c_int64 * 4), ("faults", wintypes.DWORD),
        ("total_processes", wintypes.DWORD), ("active_processes", wintypes.DWORD),
        ("terminated_processes", wintypes.DWORD)]


class WindowsJobAPI:
    """Use kernel-owned membership, without scanning or killing unrelated PIDs."""

    def __init__(self):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        for name, result, arguments in (
            ("CreateJobObjectW", wintypes.HANDLE, [ctypes.c_void_p, wintypes.LPCWSTR]),
            ("SetInformationJobObject", wintypes.BOOL, [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]),
            ("AssignProcessToJobObject", wintypes.BOOL, [wintypes.HANDLE, wintypes.HANDLE]),
            ("QueryInformationJobObject", wintypes.BOOL,
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]),
            ("TerminateJobObject", wintypes.BOOL, [wintypes.HANDLE, wintypes.UINT]),
            ("ResumeThread", wintypes.DWORD, [wintypes.HANDLE]),
        ):
            method = getattr(kernel, name)
            method.restype, method.argtypes = result, arguments
            setattr(self, name, method)

    @staticmethod
    def check(success):
        if not success:
            raise ctypes.WinError(ctypes.get_last_error())

    def create(self):
        import _winapi

        job = self.CreateJobObjectW(None, None)
        self.check(job)
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            self.check(self.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        except BaseException:
            _winapi.CloseHandle(job)
            raise
        return job

    def assign(self, job, process):
        self.check(self.AssignProcessToJobObject(job, process))

    def resume(self, thread):
        self.check(self.ResumeThread(thread) != 0xFFFFFFFF)

    def active(self, job):
        info = Accounting()
        self.check(self.QueryInformationJobObject(job, 1, ctypes.byref(info), ctypes.sizeof(info), None))
        return info.active_processes

    def terminate(self, job):
        self.check(self.TerminateJobObject(job, 1))


def create_suspended(command, application, environment, log):
    import _winapi
    import msvcrt

    executable = shutil.which(command[0])
    if executable is None:
        raise FileNotFoundError(f"Deployment executable not found: {command[0]}")
    owner = _winapi.GetCurrentProcess()
    inherited = []
    with open(os.devnull, "rb") as null:
        try:
            for stream in (null, log):
                inherited.append(_winapi.DuplicateHandle(owner, msvcrt.get_osfhandle(stream.fileno()),
                    owner, 0, True, _winapi.DUPLICATE_SAME_ACCESS))
            startup = subprocess.STARTUPINFO(dwFlags=subprocess.STARTF_USESTDHANDLES,
                hStdInput=inherited[0], hStdOutput=inherited[1], hStdError=inherited[1],
                lpAttributeList={"handle_list": inherited})
            # Suspend the primary thread until the process is assigned to our job.
            return _winapi.CreateProcess(executable, subprocess.list2cmdline(command), None, None, True,
                0x00000004 | subprocess.CREATE_NO_WINDOW, child_environment(environment), str(application), startup)
        finally:
            for handle in inherited:
                _winapi.CloseHandle(handle)


class WindowsDeployment:
    def __init__(self, command, application, environment, log):
        import _winapi

        self.api = WindowsJobAPI()
        self.close = _winapi.CloseHandle
        self.job = self.api.create()
        self.process = None
        try:
            self.process, thread, _, _ = create_suspended(command, application, environment, log)
            try:
                self.api.assign(self.job, self.process)
                self.api.resume(thread)
            finally:
                self.close(thread)
        except BaseException:
            try:
                if self.process is not None:
                    try:
                        _winapi.TerminateProcess(self.process, 1)
                    finally:
                        self.close(self.process)
            finally:
                self.close(self.job)
            raise

    def alive(self):
        return self.api.active(self.job) > 0

    def stop(self):
        try:
            if self.alive():
                self.api.terminate(self.job)
                deadline = monotonic() + 5
                while self.alive():
                    if monotonic() >= deadline:
                        raise TimeoutError("Deployment job still has active processes after termination")
                    sleep(0.05)
        finally:
            try:
                self.close(self.job)
            finally:
                self.close(self.process)


class PosixDeployment:
    def __init__(self, command, application, environment, log):
        self.process = start_process(command, cwd=application, env=environment,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)

    def alive(self):
        return self.process.poll() is None

    def stop(self):
        stop_process(self.process)


def launch(command, application, environment, log):
    process_type = WindowsDeployment if os.name == "nt" else PosixDeployment
    return process_type(command, application, environment, log)
