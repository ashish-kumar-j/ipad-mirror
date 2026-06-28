#!/usr/bin/env python3
"""
Generate icon.icns (macOS) and icon.ico (Windows) using Pillow only.
No Homebrew / cairo / SVG renderer required.

Run from the project root:
    python3 assets/make_icons.py
"""

import math
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).parent


def ensure_pillow():
    try:
        from PIL import Image  # noqa
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow", "-q"])


# ──────────────────────────────────────────────────────────────────────────────
# Drawing helpers
# ──────────────────────────────────────────────────────────────────────────────

def _lerp_color(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _rounded_rect_mask(draw, xy, r, fill):
    """Draw a rounded rectangle using Pillow 10+ rounded_rectangle."""
    draw.rounded_rectangle(xy, radius=r, fill=fill)


def _arc_thick(draw, cx, cy, r1, r2, angle_start, angle_end, color, steps=120):
    """Draw a thick arc as a filled polygon (annular sector)."""
    from PIL import ImageDraw
    pts = []
    for i in range(steps + 1):
        a = math.radians(angle_start + (angle_end - angle_start) * i / steps)
        pts.append((cx + r1 * math.cos(a), cy + r1 * math.sin(a)))
    for i in range(steps, -1, -1):
        a = math.radians(angle_start + (angle_end - angle_start) * i / steps)
        pts.append((cx + r2 * math.cos(a), cy + r2 * math.sin(a)))
    draw.polygon(pts, fill=color)


# ──────────────────────────────────────────────────────────────────────────────
# Icon drawing
# ──────────────────────────────────────────────────────────────────────────────

def draw_icon(size: int):
    from PIL import Image, ImageDraw, ImageFilter

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    S = size  # shorthand

    # ── Background gradient (dark navy) ──────────────────────────────────────
    # Simulate gradient by drawing rows
    bg_top    = (22, 26, 54)
    bg_bottom = (10, 13, 28)
    for y in range(S):
        t = y / S
        c = _lerp_color(bg_top, bg_bottom, t) + (255,)
        draw.line([(0, y), (S, y)], fill=c)

    # Apply rounded-rect clip for app-icon shape
    mask = Image.new("L", (S, S), 0)
    mask_draw = ImageDraw.Draw(mask)
    corner = int(S * 0.2)
    mask_draw.rounded_rectangle([0, 0, S - 1, S - 1], radius=corner, fill=255)
    img.putalpha(mask)

    draw = ImageDraw.Draw(img)  # re-create draw after putalpha

    # ── iPad body ─────────────────────────────────────────────────────────────
    ipad_x1 = int(S * 0.285)
    ipad_y1 = int(S * 0.105)
    ipad_x2 = int(S * 0.715)
    ipad_y2 = int(S * 0.895)
    ipad_r  = int(S * 0.052)

    draw.rounded_rectangle(
        [ipad_x1, ipad_y1, ipad_x2, ipad_y2],
        radius=ipad_r,
        fill=(48, 54, 80),
        outline=(72, 82, 118),
        width=max(1, S // 180),
    )

    # ── Screen bezel ──────────────────────────────────────────────────────────
    bz = int(S * 0.03)
    bz_top  = int(S * 0.075)
    bz_bot  = int(S * 0.058)
    scr_x1 = ipad_x1 + bz
    scr_y1 = ipad_y1 + bz_top
    scr_x2 = ipad_x2 - bz
    scr_y2 = ipad_y2 - bz_bot
    scr_r  = max(2, S // 100)

    draw.rounded_rectangle([scr_x1, scr_y1, scr_x2, scr_y2], radius=scr_r,
                            fill=(9, 13, 28))

    # ── Screen content gradient ───────────────────────────────────────────────
    scr_top_c = (85, 170, 255)
    scr_bot_c = (10, 100, 220)
    scr_h = scr_y2 - scr_y1
    scr_w = scr_x2 - scr_x1
    screen_img = Image.new("RGBA", (scr_w, scr_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(screen_img)
    for y in range(scr_h):
        t = y / scr_h
        c = _lerp_color(scr_top_c, scr_bot_c, t) + (255,)
        sd.line([(0, y), (scr_w, y)], fill=c)
    # round corners
    scr_mask = Image.new("L", (scr_w, scr_h), 0)
    ImageDraw.Draw(scr_mask).rounded_rectangle(
        [0, 0, scr_w - 1, scr_h - 1], radius=scr_r, fill=255)
    screen_img.putalpha(scr_mask)
    img.alpha_composite(screen_img, (scr_x1, scr_y1))
    draw = ImageDraw.Draw(img)

    # Screen top reflection
    if scr_h > 10:
        ref_h = max(4, scr_h // 5)
        ref_img = Image.new("RGBA", (scr_w, ref_h), (0, 0, 0, 0))
        rd = ImageDraw.Draw(ref_img)
        for y in range(ref_h):
            a = int(22 * (1 - y / ref_h))
            rd.line([(0, y), (scr_w, y)], fill=(255, 255, 255, a))
        img.alpha_composite(ref_img, (scr_x1, scr_y1))
        draw = ImageDraw.Draw(img)

    # Simulated UI lines on screen
    line_x = scr_x1 + int(scr_w * 0.1)
    line_w = int(scr_w * 0.8)
    y_off  = scr_y1 + int(scr_h * 0.18)
    for (lw, opa, dy) in [
        (line_w,       68, 0),
        (int(line_w * 0.7), 42, int(scr_h * 0.10)),
        (line_w,       18, int(scr_h * 0.22)),
        (int(line_w * 0.5), 40, int(scr_h * 0.60)),
        (int(line_w * 0.65), 30, int(scr_h * 0.69)),
    ]:
        lh = max(2, S // 90)
        r_lh = max(1, lh // 2)
        draw.rounded_rectangle(
            [line_x, y_off + dy, line_x + lw, y_off + dy + lh],
            radius=r_lh,
            fill=(255, 255, 255, opa),
        )

    # Front camera dot
    cam_cx = (ipad_x1 + ipad_x2) // 2
    cam_cy = ipad_y1 + int(S * 0.037)
    cam_r  = max(2, S // 90)
    draw.ellipse([cam_cx - cam_r, cam_cy - cam_r,
                  cam_cx + cam_r, cam_cy + cam_r],
                 fill=(14, 18, 38))

    # Home indicator bar
    hi_w  = int(S * 0.10)
    hi_h  = max(2, S // 100)
    hi_x  = (S - hi_w) // 2
    hi_y  = ipad_y2 - int(S * 0.045)
    draw.rounded_rectangle(
        [hi_x, hi_y, hi_x + hi_w, hi_y + hi_h],
        radius=hi_h // 2,
        fill=(72, 82, 118),
    )

    # ── Broadcasting arcs (left & right) ─────────────────────────────────────
    arc_cx_l = ipad_x1
    arc_cx_r = ipad_x2
    arc_cy   = S // 2
    arc_span = 42   # degrees each side of horizontal

    for cx, a_start, a_end in [
        (arc_cx_l, 180 - arc_span, 180 + arc_span),   # left (faces left)
        (arc_cx_r, -arc_span,       arc_span),          # right (faces right)
    ]:
        for (r_in, r_out, alpha) in [
            (int(S * 0.08), int(S * 0.11), 235),
            (int(S * 0.14), int(S * 0.17), 135),
            (int(S * 0.20), int(S * 0.23),  60),
        ]:
            # Draw as overlay image so we can use alpha
            arc_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            ald = ImageDraw.Draw(arc_layer)
            _arc_thick(ald, cx, arc_cy, r_in, r_out,
                       a_start, a_end,
                       (96, 184, 255, alpha))
            img.alpha_composite(arc_layer)
            draw = ImageDraw.Draw(img)

    # ── Subtle glow beneath iPad ──────────────────────────────────────────────
    glow_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    glow_cx = S // 2
    glow_cy = int(S * 0.93)
    glow_rx = int(S * 0.19)
    glow_ry = int(S * 0.025)
    gd.ellipse(
        [glow_cx - glow_rx, glow_cy - glow_ry,
         glow_cx + glow_rx, glow_cy + glow_ry],
        fill=(10, 132, 255, 28),
    )
    img.alpha_composite(glow_layer)

    return img


# ──────────────────────────────────────────────────────────────────────────────
# Output formats
# ──────────────────────────────────────────────────────────────────────────────

def build_png(size: int, out: Path):
    img = draw_icon(size)
    img.save(str(out), "PNG")
    print(f"  {size:>4}px → {out.name}")
    return img


def build_icns(out: Path):
    print("\nBuilding icon.icns …")
    iconset = HERE / "icon.iconset"
    iconset.mkdir(exist_ok=True)

    for size in [16, 32, 64, 128, 256, 512, 1024]:
        build_png(size, iconset / f"icon_{size}x{size}.png")
        if size <= 512:
            build_png(size * 2, iconset / f"icon_{size}x{size}@2x.png")

    subprocess.check_call(["iconutil", "-c", "icns", str(iconset), "-o", str(out)])
    shutil.rmtree(iconset)
    print(f"  ✓  {out}")


def build_ico(out: Path):
    from PIL import Image
    print("\nBuilding icon.ico …")
    sizes   = [16, 24, 32, 48, 64, 128, 256]
    frames  = [draw_icon(s) for s in sizes]
    frames[0].save(
        str(out),
        format="ICO",
        sizes=[(f.width, f.height) for f in frames],
        append_images=frames[1:],
    )
    print(f"  ✓  {out}")


def main():
    ensure_pillow()
    print("Generating iPad Mirror icons …\n")

    # Always produce a 1024-px PNG (fallback used by main.py + the .app on Windows)
    build_png(1024, HERE / "icon_1024.png")

    if sys.platform == "darwin":
        build_icns(HERE / "icon.icns")
    else:
        print("\n(Skipping icon.icns — macOS only)")

    build_ico(HERE / "icon.ico")
    print("\nDone.")


if __name__ == "__main__":
    main()
