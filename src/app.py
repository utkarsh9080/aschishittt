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

# 9-row-tall x 10-column-wide full-block hero clock glyphs
HERO_DIGITS = {
    "0": (
        "██████████",
        "██████████",
        "███    ███",
        "███    ███",
        "███    ███",
        "███    ███",
        "███    ███",
        "██████████",
        "██████████",
    ),
    "1": (
        "   ████   ",
        " ██████   ",
        "   ████   ",
        "   ████   ",
        "   ████   ",
        "   ████   ",
        "   ████   ",
        " ████████ ",
        " ████████ ",
    ),
    "2": (
        "██████████",
        "██████████",
        "       ███",
        "██████████",
        "██████████",
        "███       ",
        "███       ",
        "██████████",
        "██████████",
    ),
    "3": (
        "██████████",
        "██████████",
        "       ███",
        "  ████████",
        "  ████████",
        "       ███",
        "       ███",
        "██████████",
        "██████████",
    ),
    "4": (
        "███    ███",
        "███    ███",
        "███    ███",
        "██████████",
        "██████████",
        "       ███",
        "       ███",
        "       ███",
        "       ███",
    ),
    "5": (
        "██████████",
        "██████████",
        "███       ",
        "██████████",
        "██████████",
        "       ███",
        "       ███",
        "██████████",
        "██████████",
    ),
    "6": (
        "██████████",
        "██████████",
        "███       ",
        "██████████",
        "██████████",
        "███    ███",
        "███    ███",
        "██████████",
        "██████████",
    ),
    "7": (
        "██████████",
        "██████████",
        "       ███",
        "      ███ ",
        "     ███  ",
        "    ███   ",
        "    ███   ",
        "    ███   ",
        "    ███   ",
    ),
    "8": (
        "██████████",
        "██████████",
        "███    ███",
        "██████████",
        "██████████",
        "███    ███",
        "███    ███",
        "██████████",
        "██████████",
    ),
    "9": (
        "██████████",
        "██████████",
        "███    ███",
        "██████████",
        "██████████",
        "       ███",
        "       ███",
        "██████████",
        "██████████",
    ),
    ":": (
        "    ",
        "    ",
        " ██ ",
        " ██ ",
        "    ",
        " ██ ",
        " ██ ",
        "    ",
        "    ",
    ),
}

# 3-row-tall crisp block glyphs for headers, buttons, and date/host banner
BANNER_FONT = {
    "A": ("█▀█", "█▀█", "▀ ▀"),
    "B": ("█▀▄", "█▀▄", "▀▀ "),
    "C": ("█▀▀", "█  ", "▀▀▀"),
    "D": ("█▀▄", "█ █", "▀▀ "),
    "E": ("█▀▀", "█▀▀", "▀▀▀"),
    "F": ("█▀▀", "█▀ ", "▀  "),
    "G": ("█▀▀", "█ █", "▀▀▀"),
    "H": ("█ █", "█▀█", "▀ ▀"),
    "I": ("▀█▀", " █ ", "▀▀▀"),
    "J": ("  █", "  █", "▀▀ "),
    "K": ("█ █", "█▀▄", "▀ ▀"),
    "L": ("█  ", "█  ", "▀▀▀"),
    "M": ("█▄█", "█ █", "▀ ▀"),
    "N": ("█▀█", "█ █", "▀ ▀"),
    "O": ("█▀█", "█ █", "▀▀▀"),
    "P": ("█▀█", "█▀▀", "▀  "),
    "Q": ("█▀█", "█ █", "▀▀▄"),
    "R": ("█▀█", "█▀▄", "▀ ▀"),
    "S": ("█▀▀", "▀▀█", "▀▀ "),
    "T": ("▀█▀", " █ ", " ▀ "),
    "U": ("█ █", "█ █", "▀▀▀"),
    "V": ("█ █", "█ █", " ▀ "),
    "W": ("█ █", "█ █", "▀▄▀"),
    "X": ("█ █", " ▀ ", "▀ ▀"),
    "Y": ("█ █", " ▀ ", " ▀ "),
    "Z": ("▀▀█", "▄▀ ", "▀▀▀"),
    "0": ("█▀█", "█ █", "▀▀▀"),
    "1": ("▄█ ", " █ ", "▀▀▀"),
    "2": ("▀▀█", "▄▀ ", "▀▀▀"),
    "3": ("▀▀█", " ▀█", "▀▀ "),
    "4": ("█ █", "▀▀█", "  ▀"),
    "5": ("█▀▀", "▀▀█", "▀▀ "),
    "6": ("█▀▀", "█▀█", "▀▀▀"),
    "7": ("▀▀█", "  █", "  ▀"),
    "8": ("█▀█", "█▀█", "▀▀▀"),
    "9": ("█▀█", "▀▀█", "▀▀ "),
    "-": ("   ", "▀▀▀", "   "),
    "•": ("   ", " ▄ ", "   "),
    ":": ("   ", " ▄ ", " ▀ "),
    "/": ("  █", " █ ", "█  "),
    ".": ("   ", "   ", " ▄ "),
    " ": ("  ", "  ", "  "),
}


def render_hero_clock(time_str: str) -> str:
    rows = [""] * 9
    for idx, ch in enumerate(time_str):
        glyph = HERO_DIGITS.get(ch, ("    ",) * 9)
        sep = "  " if idx > 0 else ""
        for r in range(9):
            rows[r] += sep + glyph[r]
    return "\n".join(rows)


def render_banner_text(text: str) -> str:
    rows = ["", "", ""]
    for idx, ch in enumerate(text.upper()):
        glyph = BANNER_FONT.get(ch, ("   ", "   ", "   "))
        sep = " " if idx > 0 else ""
        for r in range(3):
            rows[r] += sep + glyph[r]
    return "\n".join(rows)


def parse_time_arg(val: str) -> float:
    if ":" in val:
        parts = val.strip().split(":")
        if len(parts) == 2:
            return float(parts[0]) * 60.0 + float(parts[1])
        if len(parts) == 3:
            return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
    return float(val)


def build_progress_bar(pos: float, dur: float, width: int = 34) -> str:
    if dur <= 0:
        return "─" * width
    ratio = max(0.0, min(1.0, pos / dur))
    filled = int(round(ratio * (width - 1)))
    return ("━" * filled) + "●" + ("─" * max(0, width - filled - 1))


def write_tty_atomic(seq: str) -> None:
    """Write raw terminal control bytes in a single unbuffered os.write() call."""
    data = seq.encode("ascii")
    try:
        if sys.__stdout__ is not None:
            os.write(sys.__stdout__.fileno(), data)
            return
    except Exception:
        pass
    sys.stdout.write(seq)
    sys.stdout.flush()


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
        write_tty_atomic(
            f"\x1b[?2026h\x1b7\x1b[{lbl_row};{lbl_col}H{esc}\x1b8\x1b[?2026l"
        )


class AsciiGreeterApp(App):
    ansi_color = True

    CSS = """
    App, Screen {
        background: ansi_default;
    }

    Screen {
        layers: base vinyl login;
    }

    #top-bar {
        layer: base;
        dock: top;
        height: auto;
        width: 100%;
        align: center top;
        background: ansi_default;
        padding-top: 1;
    }

    #clock-big {
        width: 100%;
        text-align: center;
        color: #f4f6fb;
        text-style: bold;
        background: ansi_default;
    }

    #clock-sub {
        width: 100%;
        text-align: center;
        color: #eceff4;
        text-style: bold;
        margin-top: 1;
        background: ansi_default;
    }

    #vinyl-dock {
        layer: vinyl;
        dock: right;
        height: auto;
        align: right top;
        padding: 1 2 0 0;
        background: ansi_default;
    }

    #vinyl-card {
        height: auto;
        padding: 1 1;
        background: ansi_default;
        border: none;
        align: center top;
    }

    #vinyl-disc {
        background: ansi_default;
    }

    #track-title {
        width: 100%;
        text-align: center;
        color: #f4f6fb;
        text-style: bold;
        margin-top: 1;
        background: ansi_default;
    }

    #track-time {
        width: 100%;
        text-align: center;
        color: #eceff4;
        text-style: bold;
        background: ansi_default;
    }

    #track-bar {
        width: 100%;
        text-align: center;
        color: #e5b567;
        margin-bottom: 1;
        background: ansi_default;
    }

    #controls-row {
        width: 100%;
        height: 3;
        align: center middle;
        background: ansi_default;
    }

    .media-btn {
        min-width: 7;
        height: 3;
        margin: 0 1;
        background: #121722;
        color: #eceff4;
        border: heavy #8896ab;
    }

    .media-btn:hover {
        border: heavy #e5b567;
        background: #2b2416;
    }

    #btn-play {
        min-width: 13;
        border: heavy #e5b567;
    }

    #login-layer {
        layer: login;
        dock: bottom;
        width: 100%;
        height: auto;
        align: right bottom;
        padding: 0 2 1 0;
        background: ansi_default;
    }

    #login-card {
        width: 58;
        height: auto;
        padding: 0 2;
        background: ansi_default;
        border: heavy #c8d3e6;
    }

    #card-title {
        width: 100%;
        text-align: center;
        color: #f4f6fb;
        text-style: bold;
        padding-bottom: 1;
        margin-bottom: 1;
        border-bottom: heavy #8896ab;
        background: ansi_default;
    }

    .field-label {
        color: #ffffff;
        text-style: bold;
        margin-top: 0;
        margin-bottom: 0;
        background: ansi_default;
    }

    #pass-label {
        margin-top: 1;
    }

    Input {
        width: 100%;
        height: 3;
        padding: 0 2;
        background: #0d111a;
        border: heavy #8896ab;
        color: #ffffff;
        text-style: bold;
        margin-bottom: 0;
    }

    Input:focus {
        border: heavy #e5b567;
    }

    #status-msg {
        width: 100%;
        height: 1;
        text-align: center;
        color: #bf616a;
        text-style: bold;
        background: ansi_default;
    }

    #status-msg.ok {
        color: #a3be8c;
    }

    #login-btn {
        width: 100%;
        height: 5;
        margin-top: 0;
        text-style: bold;
        background: #141926;
        color: #eceff4;
        border: heavy #8896ab;
    }

    #login-btn:hover, #login-btn:focus {
        background: #2b2416;
        border: heavy #e5b567;
        color: #ffffff;
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
        self.ansi_color = True
        self.dry_run = dry_run
        self.auto_exit_sec = auto_exit_sec
        self.session_cmd = session_cmd.split()
        self.greeter = GreetdClient(dry_run=dry_run)
        self.player = MpvPlayer(
            MUSIC_DIR, start_paused=start_paused, start_pos=start_pos
        )
        self.vinyl_renderer = VinylRenderer(radius=21.0)
        self._current_cover: Optional[Path] = None
        self._angle: float = 0.0
        self._authenticating: bool = False

    def compose(self) -> ComposeResult:
        with Vertical(id="top-bar"):
            yield Label("", id="clock-big")
            yield Label("", id="clock-sub")

        with Container(id="vinyl-dock"):
            with Vertical(id="vinyl-card"):
                yield VinylDisplay(self.vinyl_renderer, id="vinyl-disc")
                yield Label("Loading track...", id="track-title")
                yield Label("00:00 / 00:00", id="track-time")
                yield Label("─" * 34, id="track-bar")
                with Horizontal(id="controls-row"):
                    yield Button("⏮", id="btn-prev", classes="media-btn")
                    yield Button("⏸ PAUSE", id="btn-play", classes="media-btn")
                    yield Button("⏭", id="btn-next", classes="media-btn")

        with Container(id="login-layer"):
            with Vertical(id="login-card"):
                yield Label(render_banner_text("SYSTEM ACCESS"), id="card-title")
                yield Label("U S E R N A M E", classes="field-label")
                yield Input(value=DEFAULT_USER, placeholder="username", id="user-input")
                yield Label("P A S S W O R D", id="pass-label", classes="field-label")
                yield Input(
                    placeholder="enter password...",
                    password=True,
                    id="pass-input",
                )
                yield Label("", id="status-msg")
                yield Button(render_banner_text("UNLOCK"), id="login-btn")

    def _apply_vinyl_layout_sizes(self) -> None:
        self.vinyl_renderer.recompute_geometry()
        disc = self.query_one("#vinyl-disc", VinylDisplay)
        disc.sync_dimensions()
        card_w = self.vinyl_renderer.cols + 2
        card_h = self.vinyl_renderer.rows + 11
        self.query_one("#vinyl-card", Vertical).styles.width = card_w
        vinyl_dock = self.query_one("#vinyl-dock", Container)
        vinyl_dock.styles.width = card_w + 2
        vinyl_dock.styles.height = card_h
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
            write_tty_atomic("\x1b_Ga=d,d=I,i=42,q=2;\x1b\\")

    def _sync_cover(self, cover_path: Optional[Path]) -> None:
        if cover_path != self._current_cover:
            self._current_cover = cover_path
            self.vinyl_renderer.set_cover(cover_path)

    def _update_clock(self) -> None:
        now = datetime.datetime.now()
        self.query_one("#clock-big", Label).update(render_hero_clock(now.strftime("%H:%M")))
        sub_text = f"{now.strftime('%a %d %b %Y')} • {os.uname().nodename}"
        self.query_one("#clock-sub", Label).update(render_banner_text(sub_text))

    def _tick_frame(self) -> None:
        st = self.player.get_state()
        self._sync_cover(st["cover_path"])

        if not st["paused"]:
            self._angle = (self._angle + 0.082) % (2.0 * math.pi)
            self.query_one("#vinyl-disc", VinylDisplay).refresh_disc(self._angle)

        title = st["title"]
        if len(title) > 34:
            title = title[:31] + "..."
        self.query_one("#track-title", Label).update(title)
        self.query_one("#track-time", Label).update(
            f"{format_mmss(st['position'])} / {format_mmss(st['duration'])}"
        )
        self.query_one("#track-bar", Label).update(
            build_progress_bar(st["position"], st["duration"], width=34)
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
