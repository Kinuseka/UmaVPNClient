import os
import re
import socket
import signal
import threading
import time
import subprocess
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, List

class VPNStatus(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING   = "connecting"
    CONNECTED    = "connected"
    ERROR        = "error"

class OpenVPNClient:
    """
    Windows-focused OpenVPN client controller using the management interface.

    Features:
      - Start/stop OpenVPN using a .ovpn config
      - Tracks status via management 'STATE' events
      - Streams stdout logs (optional)
      - Wait-until-connected helper
      - Optional on_status_change callback

    Requirements:
      - OpenVPN installed (openvpn.exe path must be valid)
      - Your .ovpn should not already have a 'management' directive.
        This class injects one on the command line.
    """
    def __init__(
        self,
        config_path: str,
        openvpn_path: str = r"C:\Program Files\OpenVPN\bin\openvpn.exe",
        auth_user_pass_path: Optional[str] = None,  # e.g. r"C:\vpn\auth.txt"
        management_host: str = "127.0.0.1",
        management_port: int = 25340,
        extra_args: Optional[List[str]] = None,
        on_status_change: Optional[Callable[[VPNStatus, str], None]] = None,
        log_to_stdout: bool = True,
    ):
        self.openvpn_path = str(Path(openvpn_path))
        self.config_path = str(Path(config_path))
        self.auth_user_pass_path = str(Path(auth_user_pass_path)) if auth_user_pass_path else None
        self.management_host = management_host
        self.management_port = int(management_port)
        self.extra_args = extra_args or []
        self.on_status_change = on_status_change
        self.log_to_stdout = log_to_stdout

        self._proc: Optional[subprocess.Popen] = None
        self._stdout_thread: Optional[threading.Thread] = None
        self._mgmt_thread: Optional[threading.Thread] = None
        self._mgmt_sock: Optional[socket.socket] = None
        self._stop_event = threading.Event()
        self._status = VPNStatus.DISCONNECTED
        self._status_lock = threading.Lock()
        self._last_status_msg = ""
        self._last_error = ""

        # Quick sanity checks (don’t throw yet; we’ll throw on start())
        self._openvpn_exists = Path(self.openvpn_path).is_file()
        self._config_exists = Path(self.config_path).is_file()

    # ---------------------------
    # Public API
    # ---------------------------
    @property
    def status(self) -> VPNStatus:
        with self._status_lock:
            return self._status

    @property
    def last_status_message(self) -> str:
        with self._status_lock:
            return self._last_status_msg

    @property
    def last_error(self) -> str:
        return self._last_error

    def start(self, timeout_connect: float = 30.0) -> None:
        """
        Start OpenVPN and connect.

        timeout_connect: seconds to wait for the management socket to accept connections.
        """
        if self._proc and self._proc.poll() is None:
            return  # already running

        if not self._openvpn_exists:
            raise FileNotFoundError(f"openvpn.exe not found at: {self.openvpn_path}")
        if not self._config_exists:
            raise FileNotFoundError(f".ovpn config not found at: {self.config_path}")
        if self.auth_user_pass_path and not Path(self.auth_user_pass_path).is_file():
            raise FileNotFoundError(f"auth file not found at: {self.auth_user_pass_path}")

        self._stop_event.clear()
        self._set_status(VPNStatus.CONNECTING, "Launching OpenVPN process")

        cmd = [
            self.openvpn_path,
            "--config", self.config_path,
            "--management", f"{self.management_host}", f"{self.management_port}",
            "--management-hold",  # connect but wait until we send 'hold release'
            "--management-query-passwords",
            "--setenv", "IV_GUI_VER", "python-controller",
            # Make stdout line-buffered to read logs smoothly:
            "--suppress-timestamps",
        ]

        # If the config expects username/password and you have them in a file:
        if self.auth_user_pass_path:
            cmd += ["--auth-user-pass", self.auth_user_pass_path]

        # Add user-provided extra args last (e.g. --verb 4)
        cmd += self.extra_args

        # On Windows, allow CTRL_BREAK_EVENT:
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            creationflags=creationflags,
            text=True,  # decode to text lines
            bufsize=1,  # line-buffered
        )

        # Start reader for stdout logs
        self._stdout_thread = threading.Thread(target=self._read_stdout, name="ovpn-stdout", daemon=True)
        self._stdout_thread.start()

        # Connect to management
        self._connect_management_with_retry(timeout_connect)

        # Enable state notifications and bytecount
        # Release hold to actually initiate connection
        self._send_mgmt("hold release\n")
        time.sleep(0.2)

        self._send_mgmt("state on\n")
        self._send_mgmt("bytecount 1\n")

        # Start management reader
        self._mgmt_thread = threading.Thread(target=self._read_management, name="ovpn-mgmt", daemon=True)
        self._mgmt_thread.start()

    def stop(self, graceful_timeout: float = 8.0) -> None:
        """
        Stop OpenVPN. Tries management 'signal SIGTERM' first; falls back to CTRL_BREAK.
        """
        self._stop_event.set()

        # Tell OpenVPN to exit gracefully via management if available
        if self._mgmt_sock:
            try:
                self._send_mgmt("signal SIGTERM\n")
            except Exception:
                pass

        # Fallback: send CTRL_BREAK (Windows-friendly), then terminate
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.send_signal(signal.CTRL_BREAK_EVENT)
            except Exception:
                pass

            # Give it a moment to exit
            end_by = time.time() + graceful_timeout
            while time.time() < end_by and self._proc.poll() is None:
                time.sleep(0.2)

            # Hard kill if still around
            if self._proc.poll() is None:
                try:
                    self._proc.terminate()
                except Exception:
                    pass

        # Cleanup sockets/threads
        self._close_management()
        self._set_status(VPNStatus.DISCONNECTED, "Stopped")

    def is_connected(self) -> bool:
        return self.status == VPNStatus.CONNECTED

    def wait_for_connected(self, timeout: float = 60.0) -> bool:
        """Block until CONNECTED or ERROR/DISCONNECTED or timeout."""
        end_by = time.time() + timeout
        while time.time() < end_by:
            st = self.status
            if st == VPNStatus.CONNECTED:
                return True
            if st in (VPNStatus.ERROR, VPNStatus.DISCONNECTED):
                return False
            time.sleep(0.2)
        return False

    # ---------------------------
    # Internals
    # ---------------------------
    def _set_status(self, new_status: VPNStatus, msg: str = ""):
        with self._status_lock:
            changed = new_status != self._status
            self._status = new_status
            self._last_status_msg = msg
        if changed and self.on_status_change:
            try:
                self.on_status_change(new_status, msg)
            except Exception:
                pass

    def _read_stdout(self):
        # Surface logs and catch obvious errors
        init_completed_re = re.compile(r"Initialization Sequence Completed", re.I)
        auth_fail_re = re.compile(r"AUTH_FAILED", re.I)
        fatal_re = re.compile(r"fatal|exiting due to", re.I)

        if not self._proc or not self._proc.stdout:
            return
        for line in self._proc.stdout:
            line = line.rstrip("\n")
            if self.log_to_stdout:
                print(f"[openvpn] {line}")
            # Heuristic fallbacks if management doesn’t report for some reason:
            if init_completed_re.search(line):
                self._set_status(VPNStatus.CONNECTED, "Initialization Sequence Completed")
            if auth_fail_re.search(line):
                self._last_error = "Authentication failed"
                self._set_status(VPNStatus.ERROR, self._last_error)
            if fatal_re.search(line):
                self._last_error = line
                self._set_status(VPNStatus.ERROR, self._last_error)

        # If process exits, mark disconnected (unless we already marked error)
        rc = self._proc.poll() if self._proc else 0
        if rc is not None and self.status not in (VPNStatus.ERROR,):
            self._set_status(VPNStatus.DISCONNECTED, f"OpenVPN exited (code {rc})")

    def _connect_management_with_retry(self, timeout: float):
        start = time.time()
        while time.time() - start < timeout and not self._stop_event.is_set():
            try:
                self._mgmt_sock = socket.create_connection((self.management_host, self.management_port), timeout=2.0)
                self._mgmt_sock.settimeout(2.0)
                # Drain greeting
                try:
                    self._mgmt_sock.recv(4096)
                except Exception:
                    pass
                return
            except (ConnectionRefusedError, socket.timeout, OSError):
                time.sleep(0.2)
        raise TimeoutError(f"Could not connect to OpenVPN management at {self.management_host}:{self.management_port}")

    def _send_mgmt(self, data: str):
        if not self._mgmt_sock:
            raise RuntimeError("Management socket not connected")
        self._mgmt_sock.sendall(data.encode("utf-8"))

    def _read_management(self):
        """
        Parse management interface messages:
          >STATE:timestamp,STATE_CODE,detail,local,remote
        Typical state codes:
          CONNECTING, WAIT, AUTH, GET_CONFIG, ASSIGN_IP, ADD_ROUTES, CONNECTED, RECONNECTING, EXITING
        """
        buf = b""
        while not self._stop_event.is_set() and self._mgmt_sock:
            try:
                chunk = self._mgmt_sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._handle_mgmt_line(line.decode("utf-8", errors="ignore").strip())
            except socket.timeout:
                continue
            except OSError:
                break

        # Socket died
        self._close_management()

    def _handle_mgmt_line(self, line: str):
        time.sleep(0.001) # 10ms delay to avoid race condition
        # print(line
        if line.startswith(">STATE:"):
            # Example: >STATE:1722338892,CONNECTED,SUCCESS,xxx,yyy,zzz
            parts = line.split(":", 1)[1].split(",")
            if len(parts) >= 2:
                code = parts[1].upper()
                detail = ",".join(parts[2:]) if len(parts) > 2 else ""
                if code in ("RECONNECTING", "CONNECTING", "WAIT", "AUTH", "GET_CONFIG", "ASSIGN_IP", "ADD_ROUTES"):
                    self._set_status(VPNStatus.CONNECTING, code if detail == "" else f"{code} - {detail}")
                elif code == "CONNECTED":
                    self._set_status(VPNStatus.CONNECTED, detail or "Connected")
                elif code in ("EXITING", "FAILED"):
                    self._last_error = detail or "OpenVPN exiting"
                    self._set_status(VPNStatus.ERROR, self._last_error)
                elif code == "DISCONNECTED":
                    self._set_status(VPNStatus.DISCONNECTED, "Disconnected")
        elif line.startswith(">INFO"):
            # Optional: parse or surface
            pass
        elif line.startswith(">BYTECOUNT:"):
            # Could expose throughput here if you want
            pass

    def _close_management(self):
        if self._mgmt_sock:
            try:
                self._mgmt_sock.close()
            except Exception:
                pass
            self._mgmt_sock = None

    # Context manager niceties
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False
