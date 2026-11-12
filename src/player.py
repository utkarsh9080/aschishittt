import json
import os
import re
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

import mutagen

AUDIO_EXTS = {".mp3", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wav"}
COVER_NAMES = ("cover.png", "cover.jpg", "cover.jpeg", "cover.webp")


@dataclass
class TrackInfo:
    path: Path
    display_name: str
    duration: float
    cover_path: Optional[Path]


def format_track_name(path: Path) -> str:
    """Extract clean 'Title - Artist' from tags or sanitized filename."""
    try:
        audio = mutagen.File(path, easy=True)
        if audio and audio.tags:
            title = audio.tags.get("title", [None])[0]
            artist = audio.tags.get("artist", [None])[0]
            if title and artist:
                return f"{title.strip()} - {artist.strip()}"
            if title:
                return title.strip()
    except Exception:
        pass

    stem = re.sub(r"[\(\[].*?[\)\]]", "", path.stem)
    stem = re.sub(r"\s+", " ", stem.replace("_", " ")).strip(" -")
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return f"{title.strip()} - {artist.strip()}"
    return stem or path.stem


def probe_duration(path: Path) -> float:
    try:
        audio = mutagen.File(path)
        if audio and audio.info and getattr(audio.info, "length", 0):
            return float(audio.info.length)
    except Exception:
        pass
    return 0.0


def find_cover_for_track(track_path: Path, music_dir: Path) -> Optional[Path]:
    per_track_matches = [
        track_path.with_suffix(ext)
        for ext in (".png", ".jpg", ".jpeg", ".webp")
        if track_path.with_suffix(ext).exists()
    ]
    if per_track_matches:
        return max(per_track_matches, key=lambda p: p.stat().st_mtime)

    shared_matches = [
        music_dir / name for name in COVER_NAMES if (music_dir / name).exists()
    ]
    if shared_matches:
        return max(shared_matches, key=lambda p: p.stat().st_mtime)
    return None


def format_mmss(seconds: float) -> str:
    sec = max(0, int(seconds))
    mins, rem = divmod(sec, 60)
    return f"{mins:02d}:{rem:02d}"


class MpvPlayer:
    def __init__(
        self,
        music_dir: Path,
        start_paused: bool = True,
        start_pos: float = 0.0,
    ) -> None:
        self.music_dir = music_dir
        self.start_paused = start_paused
        self.start_pos = max(0.0, float(start_pos))
        self.tracks: List[TrackInfo] = self._scan_tracks()
        self.sock_path = Path(tempfile.gettempdir()) / f"asciishit-mpv-{os.getpid()}.sock"
        self.proc: Optional[subprocess.Popen] = None

    def _scan_tracks(self) -> List[TrackInfo]:
        if not self.music_dir.exists():
            return []
        files = sorted(
            p for p in self.music_dir.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS
        )
        return [
            TrackInfo(
                path=p,
                display_name=format_track_name(p),
                duration=probe_duration(p),
                cover_path=find_cover_for_track(p, self.music_dir),
            )
            for p in files
        ]

    def start(self) -> None:
        if not self.tracks:
            return
        if self.sock_path.exists():
            self.sock_path.unlink(missing_ok=True)

        cmd = [
            "mpv",
            "--no-video",
            "--no-terminal",
            "--idle=yes",
            "--loop-playlist=inf",
            f"--input-ipc-server={self.sock_path}",
        ]
        if self.start_pos > 0:
            cmd.append(f"--start={self.start_pos}")
        if self.start_paused:
            cmd.append("--pause")
        cmd.extend(str(t.path) for t in self.tracks)

        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.time() + 2.5
        while time.time() < deadline:
            if self.sock_path.exists():
                break
            time.sleep(0.05)

    def _ipc(self, command: List[Any]) -> Any:
        if not self.sock_path.exists():
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(0.15)
                client.connect(str(self.sock_path))
                payload = (json.dumps({"command": command}) + "\n").encode("utf-8")
                client.sendall(payload)
                buf = b""
                while b"\n" not in buf:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                for line in buf.splitlines():
                    msg = json.loads(line.decode("utf-8", errors="ignore"))
                    if "error" in msg:
                        return msg.get("data") if msg["error"] == "success" else None
        except Exception:
            return None
        return None

    def toggle_pause(self) -> None:
        self._ipc(["cycle", "pause"])

    def seek(self, seconds: float) -> None:
        self._ipc(["seek", max(0.0, float(seconds)), "absolute"])

    def next_track(self) -> None:
        self._ipc(["playlist-next", "force"])

    def prev_track(self) -> None:
        self._ipc(["playlist-prev", "force"])

    def get_state(self) -> dict:
        if not self.tracks:
            return {
                "has_tracks": False,
                "paused": True,
                "position": 0.0,
                "duration": 0.0,
                "title": "No tracks found",
                "cover_path": None,
            }

        paused = self._ipc(["get_property", "pause"])
        pos = self._ipc(["get_property", "time-pos"])
        dur = self._ipc(["get_property", "duration"])
        cur_path = self._ipc(["get_property", "path"])

        active_track = self.tracks[0]
        if cur_path:
            for t in self.tracks:
                if str(t.path) == str(cur_path):
                    active_track = t
                    break

        final_dur = float(dur) if isinstance(dur, (int, float)) and dur > 0 else active_track.duration
        final_pos = float(pos) if isinstance(pos, (int, float)) and pos >= 0 else self.start_pos

        return {
            "has_tracks": True,
            "paused": bool(paused) if paused is not None else self.start_paused,
            "position": final_pos,
            "duration": final_dur,
            "title": active_track.display_name,
            "cover_path": active_track.cover_path,
        }

    def shutdown(self) -> None:
        if self.proc and self.proc.poll() is None:
            self._ipc(["quit"])
            try:
                self.proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.sock_path.unlink(missing_ok=True)
