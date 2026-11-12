import base64
import fcntl
import io
import math
import os
import struct
import sys
import termios
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw
from rich.style import Style
from rich.text import Text

BRAILLE_WEIGHTS = np.array(
    [
        [0x01, 0x08],
        [0x02, 0x10],
        [0x04, 0x20],
        [0x40, 0x80],
    ],
    dtype=np.uint16,
)


def get_cell_metrics() -> Tuple[float, float, float]:
    """Return (cell_w_px, cell_h_px, aspect_ratio) from the real underlying TTY."""
    for stream in (sys.__stdout__, sys.stdout, sys.stdin):
        try:
            if stream is None:
                continue
            buf = fcntl.ioctl(stream.fileno(), termios.TIOCGWINSZ, b"\x00" * 8)
            t_rows, t_cols, x_px, y_px = struct.unpack("HHHH", buf)
            if t_rows > 0 and t_cols > 0 and x_px > 0 and y_px > 0:
                cw = x_px / t_cols
                ch = y_px / t_rows
                return cw, ch, ch / cw
        except Exception:
            continue
    return 7.0, 15.0, 2.14


def supports_kitty_graphics() -> bool:
    term = os.environ.get("TERM", "")
    return "kitty" in term or bool(os.environ.get("KITTY_WINDOW_ID"))


class VinylRenderer:
    def __init__(
        self,
        radius: float = 20.0,
        label_ratio: float = 0.38,
        spindle_ratio: float = 0.048,
    ) -> None:
        self.radius = radius
        self.label_ratio = label_ratio
        self.spindle_ratio = spindle_ratio
        self.cover_path: Optional[Path] = None
        self.cover_square: Optional[Image.Image] = None
        self.recompute_geometry()

    def recompute_geometry(self) -> None:
        self.cell_w, self.cell_h, self.aspect_ratio = get_cell_metrics()

        # Keep cols, rows, label_cols, and label_rows strictly even for exact symmetry
        self.cols = int(math.ceil(self.radius * 2.0)) + 2
        if self.cols % 2 != 0:
            self.cols += 1
        self.rows = int(math.ceil((self.radius * 2.0) / self.aspect_ratio)) + 2
        if self.rows % 2 != 0:
            self.rows += 1

        desired_label_cols = max(8, int(round(self.radius * 2.0 * self.label_ratio)))
        if desired_label_cols % 2 != 0:
            desired_label_cols += 1
        self.label_cols = desired_label_cols
        self.label_rows = max(4, int(round(self.label_cols / self.aspect_ratio)))
        if self.label_rows % 2 != 0:
            self.label_rows += 1

        self.label_col_offset = (self.cols - self.label_cols) // 2
        self.label_row_offset = (self.rows - self.label_rows) // 2

        self.box_px_w = max(32, int(round(self.label_cols * self.cell_w)))
        self.box_px_h = max(32, int(round(self.label_rows * self.cell_h)))
        self.label_d_px = min(self.box_px_w, self.box_px_h) - 2

        self.sub_w = self.cols * 2
        self.sub_h = self.rows * 4
        self.r_sub = self.radius * 2.0

        actual_label_r_cols = (self.label_d_px / self.cell_w) * 0.5
        self.r_label = max(2.0, actual_label_r_cols * 2.0 - 0.25)
        self.r_spindle = self.r_sub * self.spindle_ratio

        y_idx, x_idx = np.ogrid[: self.sub_h, : self.sub_w]
        self.dx = x_idx.astype(np.float32) - (self.sub_w - 1) / 2.0
        self.dy = (y_idx.astype(np.float32) - (self.sub_h - 1) / 2.0) * (
            self.aspect_ratio / 2.0
        )
        self.r = np.hypot(self.dx, self.dy)
        self.theta = np.arctan2(self.dy, self.dx)

        self.groove_mask = (self.r > self.r_label) & (self.r <= self.r_sub)
        self.rim_mask = (self.r >= self.r_sub - 1.25) & (self.r <= self.r_sub)

        self._build_label_masks()
        if self.cover_path is not None:
            self.set_cover(self.cover_path)

    def _build_label_masks(self) -> None:
        ss = 4
        w_ss, h_ss = self.box_px_w * ss, self.box_px_h * ss
        cx, cy = (w_ss - 1) / 2.0, (h_ss - 1) / 2.0
        r_outer = (self.label_d_px * ss) / 2.0
        r_inner = r_outer * 0.11

        yy, xx = np.ogrid[:h_ss, :w_ss]
        dist = np.hypot(xx - cx, yy - cy)

        alpha_ss = np.where((dist <= r_outer) & (dist >= r_inner), 255, 0).astype(
            np.uint8
        )
        self.alpha_mask = Image.fromarray(alpha_ss, mode="L").resize(
            (self.box_px_w, self.box_px_h), Image.Resampling.LANCZOS
        )

        overlay = Image.new("RGBA", (w_ss, h_ss), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.ellipse(
            (cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer),
            outline=(210, 165, 82, 255),
            width=max(2, ss * 2),
        )
        draw.ellipse(
            (cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner),
            outline=(225, 195, 155, 255),
            width=max(2, int(ss * 1.5)),
        )
        self.ring_overlay = overlay.resize(
            (self.box_px_w, self.box_px_h), Image.Resampling.LANCZOS
        )

    def set_cover(self, image_path: Optional[Path]) -> None:
        self.cover_path = image_path
        if not image_path or not image_path.exists():
            self.cover_square = Image.new(
                "RGB", (self.label_d_px, self.label_d_px), (138, 12, 16)
            )
            return

        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        cropped = img.crop((left, top, left + side, top + side))

        # Auto-crop black outer framing while keeping the full golden circular rim intact
        gray = np.asarray(cropped.convert("L"), dtype=np.uint8)
        corners = [gray[0, 0], gray[0, -1], gray[-1, 0], gray[-1, -1]]
        if max(int(c) for c in corners) < 18:
            yy, xx = np.ogrid[:side, :side]
            center = (side - 1) / 2.0
            central_zone = np.hypot(xx - center, yy - center) <= (side * 0.505)
            ys, xs = np.where(central_zone & (gray > 14))
            if len(xs) > 0 and len(ys) > 0:
                x0, x1 = int(xs.min()), int(xs.max())
                y0, y1 = int(ys.min()), int(ys.max())
                box_side = max(x1 - x0, y1 - y0)
                cx_box = (x0 + x1) // 2
                cy_box = (y0 + y1) // 2
                half = box_side // 2
                c_left = max(0, cx_box - half)
                c_top = max(0, cy_box - half)
                c_right = min(side, c_left + box_side)
                c_bottom = min(side, c_top + box_side)
                if (c_right - c_left) > side * 0.25:
                    cropped = cropped.crop((c_left, c_top, c_right, c_bottom))

        self.cover_square = cropped.resize(
            (self.label_d_px, self.label_d_px), Image.Resampling.LANCZOS
        )

    def render_grooves(self, angle: float) -> Text:
        theta_rot = self.theta - angle

        gold_lobe = np.abs(np.cos(2.0 * (theta_rot + 0.48))) ** 4.0
        irid_flare = np.abs(np.cos(theta_rot + 0.68)) ** 7.5

        caustic = (
            0.48
            + 0.27 * np.sin(6.5 * theta_rot + 0.30 * self.r)
            + 0.25 * np.cos(12.0 * theta_rot - 0.50 * self.r + np.sin(3.0 * theta_rot))
        )
        caustic = np.clip(caustic * 1.45 - 0.22, 0.0, 1.0)
        grooves = 0.74 + 0.26 * np.sin(self.r * 4.2)

        # Subtle dark-graphite vinyl base so the entire circular silhouette is visible
        gold_energy = np.clip(gold_lobe * (0.28 + 0.90 * caustic) * grooves, 0.0, 1.0)
        gold_r = 18.0 + 237.0 * (gold_energy ** 0.85)
        gold_g = 19.0 + 158.0 * (gold_energy ** 1.15)
        gold_b = 24.0 + 30.0 * (gold_energy ** 1.70)

        diff_phase = (
            (self.r * 0.22)
            + 4.2 * np.sin(2.0 * (theta_rot + 0.68))
            + 1.6 * np.cos(5.0 * theta_rot)
        )
        diff_strength = np.clip(irid_flare * (0.40 + 0.80 * caustic) * grooves, 0.0, 1.0)
        spec_r = 128.0 + 127.0 * np.sin(diff_phase)
        spec_g = 128.0 + 127.0 * np.sin(diff_phase + 2.05)
        spec_b = 135.0 + 120.0 * np.sin(diff_phase + 4.10)
        hot_core = (diff_strength ** 2.5) * 200.0

        rgb = np.zeros((self.sub_h, self.sub_w, 3), dtype=np.float32)
        rgb[..., 0] = np.clip(gold_r + diff_strength * spec_r * 0.85 + hot_core, 0.0, 255.0)
        rgb[..., 1] = np.clip(gold_g + diff_strength * spec_g * 0.90 + hot_core, 0.0, 255.0)
        rgb[..., 2] = np.clip(gold_b + diff_strength * spec_b * 1.15 + hot_core, 0.0, 255.0)

        rim_glow = 0.42 + 0.58 * gold_lobe
        rgb[..., 0] = np.where(self.rim_mask, 42.0 + 213.0 * rim_glow, rgb[..., 0])
        rgb[..., 1] = np.where(self.rim_mask, 32.0 + 162.0 * rim_glow, rgb[..., 1])
        rgb[..., 2] = np.where(self.rim_mask, 22.0 + 80.0 * rim_glow, rgb[..., 2])

        blocks = self.groove_mask.reshape(self.rows, 4, self.cols, 2).transpose(0, 2, 1, 3)
        masks = (blocks * BRAILLE_WEIGHTS).sum(axis=(2, 3), dtype=np.uint16)

        counts = blocks.sum(axis=(2, 3)).astype(np.float32)
        safe_counts = np.maximum(counts, 1.0)

        rgb_blocks = (rgb * self.groove_mask[..., None]).reshape(
            self.rows, 4, self.cols, 2, 3
        ).transpose(0, 2, 1, 3, 4)
        cell_rgb = (rgb_blocks.sum(axis=(2, 3)) / safe_counts[..., None]).astype(np.uint8)

        out = Text()
        for r_i in range(self.rows):
            for c_i in range(self.cols):
                m = int(masks[r_i, c_i])
                if m == 0:
                    out.append(" ")
                else:
                    cr, cg, cb = cell_rgb[r_i, c_i]
                    out.append(
                        chr(0x2800 + m),
                        style=Style(color=f"rgb({cr},{cg},{cb})"),
                    )
            if r_i < self.rows - 1:
                out.append("\n")
        return out

    def build_kitty_label_escape(self, angle: float, image_id: int = 42) -> str:
        if self.cover_square is None:
            self.set_cover(None)

        rotated = self.cover_square.rotate(
            -math.degrees(angle), resample=Image.Resampling.BILINEAR
        )
        canvas = Image.new("RGBA", (self.box_px_w, self.box_px_h), (0, 0, 0, 0))
        paste_x = (self.box_px_w - self.label_d_px) // 2
        paste_y = (self.box_px_h - self.label_d_px) // 2
        canvas.paste(rotated, (paste_x, paste_y))
        canvas.putalpha(self.alpha_mask)
        canvas = Image.alpha_composite(canvas, self.ring_overlay)

        buf = io.BytesIO()
        canvas.save(buf, format="PNG", compress_level=1)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        chunks = []
        chunk_size = 4096
        total = len(b64)
        for idx in range(0, total, chunk_size):
            part = b64[idx : idx + chunk_size]
            more = 1 if (idx + chunk_size) < total else 0
            if idx == 0:
                header = (
                    f"a=T,f=100,i={image_id},p=1,q=2,"
                    f"c={self.label_cols},r={self.label_rows},z=1,C=1,m={more}"
                )
            else:
                header = f"m={more}"
            chunks.append(f"\x1b_G{header};{part}\x1b\\")
        return "".join(chunks)
