import json
import os
import socket
import struct
import time
from typing import Any, Dict, List, Tuple


class GreetdClient:
    """Length-prefixed JSON IPC client for greetd ($GREETD_SOCK) with dry-run fallback."""

    def __init__(self, dry_run: bool = False) -> None:
        self.sock_path = os.environ.get("GREETD_SOCK", "")
        self.dry_run = dry_run or not bool(self.sock_path)

    def _request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw = json.dumps(payload).encode("utf-8")
        header = struct.pack("=I", len(raw))
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5.0)
            sock.connect(self.sock_path)
            sock.sendall(header + raw)

            resp_hdr = self._recv_exact(sock, 4)
            (resp_len,) = struct.unpack("=I", resp_hdr)
            resp_raw = self._recv_exact(sock, resp_len)
            return json.loads(resp_raw.decode("utf-8"))

    @staticmethod
    def _recv_exact(sock: socket.socket, n: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < n:
            chunk = sock.recv(n - len(chunks))
            if not chunk:
                raise ConnectionError("greetd socket closed unexpectedly")
            chunks.extend(chunk)
        return bytes(chunks)

    def authenticate_and_start(
        self, username: str, password: str, session_cmd: List[str]
    ) -> Tuple[bool, str]:
        username = username.strip()
        if not username:
            return False, "Username cannot be empty."

        if self.dry_run:
            time.sleep(0.25)
            if not password:
                return False, "Password cannot be empty."
            if password == "wrong":
                return False, "Authentication failed (dry-run test)."
            return True, "Dry-run login succeeded! Closing preview..."

        try:
            resp = self._request({"type": "create_session", "username": username})
            while resp.get("type") == "auth_message":
                msg_type = resp.get("auth_message_type", "")
                if msg_type in ("secret", "visible"):
                    resp = self._request(
                        {"type": "post_auth_message_response", "response": password}
                    )
                else:
                    resp = self._request(
                        {"type": "post_auth_message_response", "response": None}
                    )

            if resp.get("type") != "success":
                try:
                    self._request({"type": "cancel_session"})
                except Exception:
                    pass
                desc = resp.get("description") or "Authentication failed."
                return False, desc

            start_resp = self._request(
                {
                    "type": "start_session",
                    "cmd": session_cmd,
                    "env": [
                        "XDG_SESSION_TYPE=wayland",
                        "DESKTOP_SESSION=ubuntu",
                        "XDG_CURRENT_DESKTOP=ubuntu:GNOME",
                    ],
                }
            )
            if start_resp.get("type") == "success":
                return True, "Starting session..."
            return False, start_resp.get("description") or "Failed to start session."
        except Exception as exc:
            return False, f"IPC error: {exc}"
