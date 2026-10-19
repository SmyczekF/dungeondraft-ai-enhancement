"""Windows process ownership for the local editor; never stop by image name."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import csv
import io
import os
from pathlib import Path
import socket
import subprocess

from .bridge_client import BridgeError


def editor_pids() -> list[int]:
    if os.name != "nt":
        raise BridgeError("Editor lifecycle is currently supported on Windows only")
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Dungeondraft.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return [int(row[1]) for row in csv.reader(io.StringIO(result.stdout))
            if len(row) > 1 and row[0].lower() == "dungeondraft.exe"]


def listener_pid(port: int) -> int:
    """Resolve the IPv4 listener, including bridges predating process metadata."""
    class Row(ctypes.Structure):
        _fields_ = [(name, wintypes.DWORD) for name in
                    ("state", "address", "port", "remote_address", "remote_port", "pid")]

    api = ctypes.WinDLL("iphlpapi", use_last_error=True).GetExtendedTcpTable
    api.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
                    wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
    api.restype = wintypes.DWORD
    size = wintypes.DWORD()
    api(None, ctypes.byref(size), False, socket.AF_INET, 3, 0)  # OWNER_PID_LISTENER
    for _ in range(3):
        buffer = ctypes.create_string_buffer(size.value)
        result = api(buffer, ctypes.byref(size), False, socket.AF_INET, 3, 0)
        if result == 122:  # table grew
            continue
        if result:
            raise BridgeError(f"Cannot inspect bridge listener: Windows error {result}")
        count = wintypes.DWORD.from_buffer(buffer).value
        rows = (Row * count).from_buffer(buffer, ctypes.sizeof(wintypes.DWORD))
        owners = {row.pid for row in rows if socket.ntohs(row.port & 65535) == port
                  and row.address == int.from_bytes(socket.inet_aton("127.0.0.1"), "little")}
        if len(owners) == 1:
            return owners.pop()
        break
    raise BridgeError("Cannot identify exactly one local bridge listener process")


class EditorProcess:
    """Hold a kernel handle so a recycled PID cannot terminate another process."""

    def __init__(self, pid: int):
        self.pid = pid
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.api.OpenProcess.restype = wintypes.HANDLE
        self.api.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                       wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.api.OpenProcess(0x100000 | 0x1000 | 1, False, pid)
        if not self.handle:
            raise BridgeError(f"Cannot acquire editor process {pid}: {ctypes.WinError()}")
        try:
            name = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(name))
            if not self.api.QueryFullProcessImageNameW(self.handle, 0, name, ctypes.byref(size)):
                raise BridgeError(f"Cannot identify editor executable: {ctypes.WinError()}")
            self.executable = Path(name.value)
            if self.executable.name.lower() != "dungeondraft.exe":
                raise BridgeError("Bridge listener does not belong to Dungeondraft.exe")
        except Exception:
            self.close()
            raise

    def stop(self) -> None:
        # Native populated-scene teardown is unsafe on 1.2.0.1. The caller must
        # confirm a complete save (or explicit discard) and an idle editor first.
        if not self.api.TerminateProcess(self.handle, 0):
            raise BridgeError(f"Cannot stop editor {self.pid}: {ctypes.WinError()}")
        if self.api.WaitForSingleObject(self.handle, 10000) != 0:
            raise BridgeError(f"Editor {self.pid} did not exit; no replacement launched")

    def close(self) -> None:
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def launch(executable: Path, path: Path) -> subprocess.Popen:
    # Keep the current startup log beside the native file for actionable errors.
    with path.with_suffix(".editor.log").open("w", encoding="utf-8") as log:
        return subprocess.Popen(
            [str(executable), str(path)], cwd=executable.parent,
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
