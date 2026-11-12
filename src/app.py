import argparse
import datetime
import math
import os
import sys
from pathlib import Path
from typing import Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Input, Label, Static

from ipc import GreetdClient
from player import MpvPlayer, format_mmss
from vinyl import VinylRenderer, supports_kitty_graphics

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
MUSIC_DIR = ASSETS_DIR / "music"
DEFAULT_USER = "utkarsh-jha"


def parse_time_arg(val: str) -> float:
    if ":" in val:
        parts = val.strip().split(":")
        if len(parts) == 2:
            return float(parts[0]) * 60.0 + float(parts[1])
        if len(parts) == 3:
            return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
    return float(val)


def build_progress_bar(pos: float, dur: float, width: int = 24) -> str:
    if dur <= 0:
        return "─" * width
    ratio = max(0.0, min(1.0, pos / dur))
    filled = int(round(ratio * (width - 1)))
    return ("━" * filled) + "●" + ("─" * max(0, width - filled - 1))


class VinylDisplay(Static):
    """Renders the outer Braille vinyl grooves + native Kitty Graphics center cover."""

    def __init__(self, renderer: VinylRenderer, **kwargs) -> None:
        super().__init__(**kwargs)
        self.renderer = renderer
        self.angle: float = 0.0
        self.use_kitty = supports_kitty_graphics()
        self.sync_dimensions()

    def sync_dimensions(self) -> None:
        self.styles.width = self.renderer.cols
        self.styles.height = self.renderer.rows

    def on_mount(self) -> None:
        self.refresh_disc(0.0)

    def refresh_disc(self, angle: float) -> None:
        self.angle = angle
        self.update(self.renderer.render_grooves(angle))
        if self.use_kitty and self.app:
            self.app.call_after_refresh(self._blit_center_image)

    def _blit_center_image(self) -> None:
        reg = self.region
        if reg.width <= 0 or reg.height <= 0:
            return
        lbl_row = reg.y + self.renderer.label_row_offset + 1
        lbl_col = reg.x + self.renderer.label_col_offset + 1
        esc = self.renderer.build_kitty_label_escape(self.angle, image_id=42)
        sys.__stdout__.write(f"\x1b7\x1b[{lbl_row};{lbl_col}H{esc}\x1b8")
        sys.__stdout__.flush()


class AsciiGreeterApp(App):
    CSS = """
    Screen {
        background: transparent;
        layers: base overlay;
    }

    #top-bar {
        dock: top;
        height: 2;
        width: 100%;
        content-align: center middle;
        text-align: center;
        color: #d8dee9;
        background: transparent;
        padding-top: 1;
    }

    #login-layer {
        width: 100%;
        height: 100%;
        align: center middle;
        background: transparent;
    }

    #login-card {
        width: 46;
        height: auto;
        padding: 1 3;
        background: rgba(8, 10, 16, 0.76);
        border: round #6e7b91;
    }

    #card-title {
        width: 100%;
        text-align: center;
        color: #eceff4;
        text-style: bold;
        margin-bottom: 1;
    }

    .field-label {
        color: #9aa5b8;
        margin-top: 0;
    }

    Input {
        width: 100%;
        background: rgba(15, 19, 28, 0.90);
        border: tall #4c566a;
        color: #eceff4;
        margin-bottom: 1;
    }

    Input:focus {
        border: tall #e5b567;
    }

    #status-msg {
        width: 100%;
        min-height: 1;
        text-align: center;
        color: #bf616a;
        margin-bottom: 1;
    }

    #status-msg.ok {
        color: #a3be8c;
    }

    #login-btn {
        width: 100%;
        background: rgba(28, 34, 48, 0.92);
        color: #eceff4;
        border: round #5e6c84;
    }

    #login-btn:hover, #login-btn:focus {
        background: rgba(229, 181, 103, 0.22);
        border: round #e5b567;
        color: #ffffff;
    }

    #vinyl-dock {
        layer: overlay;
        dock: right;
        height: 100%;
        align: right bottom;
        padding: 0 2 1 0;
        background: transparent;
    }

    #vinyl-card {
        height: auto;
        padding: 1 2;
        background: rgba(6, 8, 13, 0.68);
        border: round #3b4252;
        align: center bottom;
    }

    #track-title {
        width: 100%;
        text-align: center;
        color: #eceff4;
        text-style: bold;
        margin-top: 1;
    }

    #track-time {
        width: 100%;
        text-align: center;
        color: #d8dee9;
    }

    #track-bar {
        width: 100%;
        text-align: center;
        color: #e5b567;
        margin-bottom: 1;
    }

    #controls-row {
        width: 100%;
        height: 3;
        align: center middle;
    }

    .media-btn {
        min-width: 6;
        height: 3;
        margin: 0 1;
        background: rgba(18, 22, 32, 0.90);
        color: #eceff4;
        border: round #4c566a;
    }

    .media-btn:hover {
        border: round #e5b567;
        background: rgba(229, 181, 103, 0.20);
    }

    #btn-play {
        min-width: 12;
        border: round #e5b567;
    }
    """

    BINDINGS = [
        Binding("ctrl+p", "toggle_music", "Play/Pause", show=False),
        Binding("escape", "quit_preview", "Exit Preview", show=False),
    ]

    def __init__(
        self,
        dry_run: bool = False,
        start_paused: bool = False,
        start_pos: float = 0.0,
        auto_exit_sec: Optional[float] = None,
        session_cmd: str = "gnome-session",
    ) -> None:
        super().__init__()
        self.dry_run = dry_run
        self.auto_exit_sec = auto_exit_sec
        self.session_cmd = session_cmd.split()
        self.greeter = GreetdClient(dry_run=dry_run)
        self.player = MpvPlayer(
            MUSIC_DIR, start_paused=start_paused, start_pos=start_pos
        )
        self.vinyl_renderer = VinylRenderer(radius=20.0)
        self._current_cover: Optional[Path] = None
        self._angle: float = 0.0
        self._authenticating: bool = False

    def compose(self) -> ComposeResult:
        yield Label("", id="top-bar")

        with Container(id="login-layer"):
            with Vertical(id="login-card"):
                mode_tag = " [DRY-RUN]" if self.dry_run else ""
                yield Label(f"◈ SYSTEM ACCESS{mode_tag}", id="card-title")
                yield Label("USER", classes="field-label")
                yield Input(value=DEFAULT_USER, placeholder="username", id="user-input")
                yield Label("PASSWORD", classes="field-label")
                yield Input(
                    placeholder="enter password...",
                    password=True,
                    id="pass-input",
                )
                yield Label("", id="status-msg")
                yield Button("[ ⏎ UNLOCK ]", id="login-btn")

        with Container(id="vinyl-dock"):
            with Vertical(id="vinyl-card"):
                yield VinylDisplay(self.vinyl_renderer, id="vinyl-disc")
                yield Label("Loading track...", id="track-title")
                yield Label("00:00 / 00:00", id="track-time")
                yield Label("─" * 24, id="track-bar")
                with Horizontal(id="controls-row"):
                    yield Button("⏮", id="btn-prev", classes="media-btn")
                    yield Button("⏸ PAUSE", id="btn-play", classes="media-btn")
                    yield Button("⏭", id="btn-next", classes="media-btn")

    def _apply_vinyl_layout_sizes(self) -> None:
        self.vinyl_renderer.recompute_geometry()
        disc = self.query_one("#vinyl-disc", VinylDisplay)
        disc.sync_dimensions()
        card_w = self.vinyl_renderer.cols + 6
        self.query_one("#vinyl-card", Vertical).styles.width = card_w
        self.query_one("#vinyl-dock", Container).styles.width = card_w + 2
        disc.refresh_disc(self._angle)

    def on_mount(self) -> None:
        self.player.start()
        self._sync_cover(self.player.tracks[0].cover_path if self.player.tracks else None)
        self._apply_vinyl_layout_sizes()
        self.query_one("#pass-input", Input).focus()
        self._update_clock()
        self.set_interval(1.0, self._update_clock)
        self.set_interval(1.0 / 24.0, self._tick_frame)
        if self.auto_exit_sec and self.auto_exit_sec > 0:
            self.set_timer(self.auto_exit_sec, self.exit)

    def on_resize(self) -> None:
        if not self.is_mounted:
            return
        self._apply_vinyl_layout_sizes()

    def on_unmount(self) -> None:
        self.player.shutdown()
        if supports_kitty_graphics():
            sys.__stdout__.write("\x1b_Ga=d,d=I,i=42,q=2;\x1b\\")
            sys.__stdout__.flush()

    def _sync_cover(self, cover_path: Optional[Path]) -> None:
        if cover_path != self._current_cover:
            self._current_cover = cover_path
            self.vinyl_renderer.set_cover(cover_path)

    def _update_clock(self) -> None:
        now = datetime.datetime.now().strftime("%a %d %b  %H:%M")
        host = os.uname().nodename
        self.query_one("#top-bar", Label).update(f"{now}   •   {host}")

    def _tick_frame(self) -> None:
        st = self.player.get_state()
        self._sync_cover(st["cover_path"])

        if not st["paused"]:
            self._angle = (self._angle + 0.09) % (2.0 * math.pi)
            self.query_one("#vinyl-disc", VinylDisplay).refresh_disc(self._angle)

        title = st["title"]
        if len(title) > 30:
            title = title[:27] + "..."
        self.query_one("#track-title", Label).update(title)
        self.query_one("#track-time", Label).update(
            f"{format_mmss(st['position'])} / {format_mmss(st['duration'])}"
        )
        self.query_one("#track-bar", Label).update(
            build_progress_bar(st["position"], st["duration"], width=32)
        )

        play_btn = self.query_one("#btn-play", Button)
        want_label = "▶ PLAY" if st["paused"] else "⏸ PAUSE"
        if str(play_btn.label) != want_label:
            play_btn.label = want_label

    def action_toggle_music(self) -> None:
        self.player.toggle_pause()

    def action_quit_preview(self) -> None:
        if self.dry_run:
            self.exit()

    @on(Button.Pressed, "#btn-play")
    def handle_play_pause(self) -> None:
        self.player.toggle_pause()
        self.query_one("#pass-input", Input).focus()

    @on(Button.Pressed, "#btn-prev")
    def handle_prev(self) -> None:
        self.player.prev_track()
        self.query_one("#pass-input", Input).focus()

    @on(Button.Pressed, "#btn-next")
    def handle_next(self) -> None:
        self.player.next_track()
        self.query_one("#pass-input", Input).focus()

    @on(Input.Submitted, "#pass-input")
    @on(Button.Pressed, "#login-btn")
    def trigger_login(self) -> None:
        if self._authenticating:
            return
        username = self.query_one("#user-input", Input).value
        password = self.query_one("#pass-input", Input).value
        status = self.query_one("#status-msg", Label)
        status.remove_class("ok")
        status.update("Authenticating...")
        self._authenticating = True
        self._run_auth(username, password)

    @work(thread=True)
    def _run_auth(self, username: str, password: str) -> None:
        ok, msg = self.greeter.authenticate_and_start(
            username, password, self.session_cmd
        )
        self.call_from_thread(self._on_auth_result, ok, msg)

    def _on_auth_result(self, ok: bool, msg: str) -> None:
        self._authenticating = False
        status = self.query_one("#status-msg", Label)
        if ok:
            status.add_class("ok")
            status.update(msg)
            self.set_timer(0.45, self.exit)
        else:
            status.remove_class("ok")
            status.update(msg)
            pw_input = self.query_one("#pass-input", Input)
            pw_input.value = ""
            pw_input.focus()


def main() -> None:
    parser = argparse.ArgumentParser(description="ASCII Vinyl Login Greeter")
    parser.add_argument("--dry-run", action="store_true", help="Test outside greetd")
    parser.add_argument("--paused", action="store_true", help="Start music paused")
    parser.add_argument(
        "--seek", default="0", help="Start playback at seconds or MM:SS (e.g. 2:45)"
    )
    parser.add_argument(
        "--duration", type=float, default=None, help="Auto-exit preview after N seconds"
    )
    parser.add_argument(
        "--session", default="gnome-session", help="Session command to launch"
    )
    args = parser.parse_args()

    app = AsciiGreeterApp(
        dry_run=args.dry_run,
        start_paused=args.paused,
        start_pos=parse_time_arg(args.seek),
        auto_exit_sec=args.duration,
        session_cmd=args.session,
    )
    app.run()


if __name__ == "__main__":
    main()
