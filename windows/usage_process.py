"""Own exactly the app-server child tree. Never enumerate or kill user CLIs."""
import os
import subprocess
import time

if os.name == "nt":
    import ctypes as C
    from ctypes import wintypes as W

    class BasicLimits(C.Structure):
        _fields_ = [("PerProcessUserTimeLimit", C.c_longlong), ("PerJobUserTimeLimit", C.c_longlong),
                    ("LimitFlags", W.DWORD), ("MinimumWorkingSetSize", C.c_size_t),
                    ("MaximumWorkingSetSize", C.c_size_t), ("ActiveProcessLimit", W.DWORD),
                    ("Affinity", C.c_size_t), ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD)]

    class IOCounters(C.Structure):
        _fields_ = [(name, C.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ExtendedLimits(C.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IOCounters),
                    ("ProcessMemoryLimit", C.c_size_t), ("JobMemoryLimit", C.c_size_t),
                    ("PeakProcessMemoryUsed", C.c_size_t), ("PeakJobMemoryUsed", C.c_size_t)]

    class Accounting(C.Structure):
        _fields_ = [(name, C.c_longlong) for name in ("TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime")] + [(name, W.DWORD) for name in ("TotalPageFaultCount", "TotalProcesses", "ActiveProcesses", "TotalTerminatedProcesses")]

    class ThreadEntry(C.Structure):
        _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ThreadID", W.DWORD),
                    ("th32OwnerProcessID", W.DWORD), ("tpBasePri", W.LONG), ("tpDeltaPri", W.LONG), ("dwFlags", W.DWORD)]

    K = C.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([C.c_void_p, W.LPCWSTR], W.HANDLE),
        "SetInformationJobObject": ([W.HANDLE, C.c_int, C.c_void_p, W.DWORD], W.BOOL),
        "AssignProcessToJobObject": ([W.HANDLE, W.HANDLE], W.BOOL),
        "TerminateJobObject": ([W.HANDLE, W.UINT], W.BOOL),
        "QueryInformationJobObject": ([W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.c_void_p], W.BOOL),
        "OpenProcess": ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
        "CreateToolhelp32Snapshot": ([W.DWORD, W.DWORD], W.HANDLE),
        "Thread32First": ([W.HANDLE, C.POINTER(ThreadEntry)], W.BOOL),
        "Thread32Next": ([W.HANDLE, C.POINTER(ThreadEntry)], W.BOOL),
        "OpenThread": ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
        "ResumeThread": ([W.HANDLE], W.DWORD),
        "CloseHandle": ([W.HANDLE], W.BOOL),
    }
    for name, (args, result) in signatures.items():
        getattr(K, name).argtypes = args
        getattr(K, name).restype = result

    def checked(handle):
        if not handle or handle == C.c_void_p(-1).value:
            raise C.WinError(C.get_last_error())
        return handle


class ChildTree:
    def __init__(self):
        self.job = None
        self.process = None

    def start(self, command, **kwargs):
        try:
            if os.name == "nt":
                self.job = checked(K.CreateJobObjectW(None, None))
                limits = ExtendedLimits()
                limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                if not K.SetInformationJobObject(self.job, 9, C.byref(limits), C.sizeof(limits)):
                    raise C.WinError(C.get_last_error())
                # Assign before any child code can run, including npm's launcher.
                self.process = subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW | 0x4, **kwargs)
                process_handle = checked(K.OpenProcess(0x100 | 0x1, False, self.process.pid))
                try:
                    if not K.AssignProcessToJobObject(self.job, process_handle):
                        raise C.WinError(C.get_last_error())
                finally:
                    K.CloseHandle(process_handle)
                snapshot = checked(K.CreateToolhelp32Snapshot(4, 0))
                try:
                    entry = ThreadEntry(); entry.dwSize = C.sizeof(entry)
                    found = K.Thread32First(snapshot, C.byref(entry))
                    resumed = False
                    while found:
                        if entry.th32OwnerProcessID == self.process.pid:
                            thread = checked(K.OpenThread(2, False, entry.th32ThreadID))
                            try:
                                if K.ResumeThread(thread) != 1:
                                    raise OSError("Cannot resume owned app-server thread.")
                                resumed = True
                            finally:
                                K.CloseHandle(thread)
                            break
                        entry.dwSize = C.sizeof(entry)
                        found = K.Thread32Next(snapshot, C.byref(entry))
                    if not resumed:
                        raise OSError("Owned app-server thread unavailable.")
                finally:
                    K.CloseHandle(snapshot)
            else:
                self.process = subprocess.Popen(command, start_new_session=True, **kwargs)
            return self.process
        except BaseException:
            self.close()
            if self.process is not None:
                for stream in (self.process.stdin, self.process.stdout):
                    if stream:
                        stream.close()
            raise

    def close(self):
        if self.job is not None:
            job, self.job = self.job, None
            try:
                if not K.TerminateJobObject(job, 1):
                    raise C.WinError(C.get_last_error())
                deadline = time.monotonic() + 3
                while True:
                    counts = Accounting()
                    if not K.QueryInformationJobObject(job, 1, C.byref(counts), C.sizeof(counts), None):
                        raise C.WinError(C.get_last_error())
                    if counts.ActiveProcesses == 0:
                        break
                    if time.monotonic() >= deadline:
                        raise OSError("Owned process tree did not stop in time.")
                    time.sleep(.01)
            finally:
                K.CloseHandle(job)  # Also kills owned descendants on abrupt parent exit.
        elif os.name != "nt" and self.process is not None:
            import signal
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()  # Also handles a failed pre-assignment suspended launch.
            self.process.wait(timeout=3)
