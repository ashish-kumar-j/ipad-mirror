import re
import subprocess
import threading


class TunnelManager:
    """Starts `sudo pymobiledevice3 remote start-tunnel` and exposes host/port."""

    def __init__(self, password: str):
        self._password = password
        self._proc = None
        self._host = None
        self._port = None
        self._error = None
        self._raw_error = None   # full stderr for diagnostics
        self._ready = threading.Event()

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def wait_ready(self, timeout=20) -> bool:
        return self._ready.wait(timeout=timeout)

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    @property
    def host(self):
        return self._host

    @property
    def port(self):
        return self._port

    @property
    def error(self):
        return self._error

    @property
    def raw_error(self):
        return self._raw_error

    # ------------------------------------------------------------------

    @staticmethod
    def _extract_error(text: str) -> str:
        """Pull the actual Python exception out of a rich-formatted traceback."""
        # Strip ANSI escape codes and box-drawing characters
        clean = re.sub(r'\x1b\[[0-9;]*m', '', text)

        # Collect non-empty lines that don't look like box-drawing borders
        lines = []
        for raw in clean.splitlines():
            stripped = raw.strip().lstrip('│╰╭─ ').strip()
            if stripped:
                lines.append(stripped)

        if not lines:
            return text.strip()[:800]

        # The actual exception is always the LAST non-empty meaningful line
        # (e.g. "ConnectionRefusedError: [Errno 61] Connection refused")
        # Skip lines that look like file paths or line-number references
        for line in reversed(lines):
            if re.match(r'^[A-Z][A-Za-z]*Error', line) or \
               re.match(r'^[A-Z][A-Za-z]*Exception', line) or \
               re.match(r'^[A-Z][A-Za-z]*Warning', line) or \
               ('Error' in line and ':' in line):
                return line

        # Fall back to last non-path line
        return lines[-1]

    @staticmethod
    def _is_windows() -> bool:
        import sys
        return sys.platform == "win32"

    @staticmethod
    def _tunnel_cmd() -> list:
        """Return the tunnel command, using the bundled helper when packaged."""
        import os, sys
        if sys.platform == "win32":
            # Windows: no sudo; app must be run as Administrator
            py = "python"
            return [py, "-m", "pymobiledevice3", "remote", "start-tunnel", "--script-mode"]
        # macOS/Linux: use sudo -S with password via stdin
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(sys.executable)
            helper = os.path.join(exe_dir, "tunnel_helper")
            if os.path.exists(helper):
                return ["sudo", "-S", helper]
        return ["sudo", "-S", "python3", "-m", "pymobiledevice3",
                "remote", "start-tunnel", "--script-mode"]

    def _run(self):
        try:
            cmd = self._tunnel_cmd()
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            # Feed password to sudo -S (macOS only; Windows skips this)
            if not self._is_windows() and self._password:
                self._proc.stdin.write((self._password + "\n").encode())
                self._proc.stdin.flush()

            # Read lines until we get HOST PORT
            for raw in self._proc.stdout:
                line = raw.decode().strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) == 2:
                    try:
                        self._host = parts[0]
                        self._port = int(parts[1])
                        self._ready.set()
                        break
                    except ValueError:
                        pass

            # If we exit the loop without finding host/port, read stderr for the error
            if not self._ready.is_set():
                err_out = self._proc.stderr.read().decode()
                self._raw_error = err_out.strip()
                self._error = self._extract_error(err_out) if err_out.strip() \
                    else "Tunnel exited without providing host/port."
                self._ready.set()

        except Exception as e:
            self._error = str(e)
            self._ready.set()
