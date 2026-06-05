#!/usr/bin/env python3
"""
Ginie sprite generator — proper Aladdin-style blue genie.
Big round Disney head, expressive face, barrel chest, crossed arms,
wispy animated smoke tail (no legs). Run: python3 gen_sprites.py
"""
import os, math
from PIL import Image, ImageDraw, ImageFilter

HERE   = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "usb_assistant", "frames")
os.makedirs(OUTDIR, exist_ok=True)

W, H = 120, 160

# ── palette ───────────────────────────────────────────────────────────────────
BODY_SHADOW  = ( 22,  65, 145, 255)
BODY_MID     = ( 52, 120, 205, 255)
BODY_LIGHT   = ( 92, 162, 242, 255)
BODY_BRIGHT  = (150, 205, 255, 255)

HAT_SHADOW   = ( 14,  22, 105, 255)
HAT_MID      = ( 32,  50, 150, 255)
HAT_LIGHT    = ( 55,  82, 188, 255)
HAT_BAND     = (255, 210,   0, 255)
HAT_GEM      = (215,  25,  25, 255)

GOLD         = (215, 168,  12, 255)
GOLD_LIGHT   = (255, 225,  85, 255)

EYE_WHITE    = (230, 248, 255, 255)
EYE_IRIS     = ( 32,  70, 182, 255)
EYE_PUPIL    = (  8,  16,  60, 255)
BROW         = ( 16,  38, 122, 255)

TEETH        = (242, 252, 255, 255)
LIP          = ( 16,  44, 128, 255)
BEARD        = ( 28,  60, 150, 190)

SASH         = (200, 110,  10, 255)
SASH_LIGHT   = (235, 150,  38, 255)

GLOW_COL     = ( 68, 138, 222,  18)

# ── helpers ───────────────────────────────────────────────────────────────────

def ell(draw, cx, cy, rx, ry, fill):
    draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=fill)

def poly(draw, pts, fill):
    draw.polygon(pts, fill=fill)

def thick_line(draw, x0, y0, x1, y1, color, w=5):
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)
    hw = w // 2
    for s in range(steps + 1):
        t  = s / steps
        px = int(x0 + t * (x1 - x0))
        py = int(y0 + t * (y1 - y0))
        draw.ellipse([px - hw, py - hw, px + hw, py + hw], fill=color)

def soft_glow(img, cx, cy, r, col):
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d  = ImageDraw.Draw(ov)
    for s in range(r, 0, -4):
        frac = s / r
        a    = int(col[3] * (1 - frac) * (1 - frac))
        d.ellipse([cx - s, cy - s, cx + s, cy + s], fill=(*col[:3], a))
    return Image.alpha_composite(img, ov)

# ── smoke tail ────────────────────────────────────────────────────────────────

def draw_smoke_tail(draw, cx, waist_y, t, amplitude=9):
    """Wispy animated smoke tail — the key Aladdin-genie feature."""
    n = 16
    for i in range(n - 1, -1, -1):          # draw tip first, base overlaps
        frac  = i / (n - 1)                  # 0 = waist, 1 = tip
        seg_y = waist_y + int(frac * 54)
        wave  = math.sin(frac * math.pi * 2.8 + t * 2 * math.pi)
        seg_x = cx + int(wave * amplitude * frac)

        rx = max(2, int(15 * (1 - frac * 0.68)))
        ry = max(2, int(10 * (1 - frac * 0.68)))
        a  = int(215 * (1 - frac * 0.92))

        r = int(BODY_MID[0] * (1 - frac * 0.35) + BODY_SHADOW[0] * frac * 0.35)
        g = int(BODY_MID[1] * (1 - frac * 0.35) + BODY_SHADOW[1] * frac * 0.35)
        b = int(BODY_MID[2] * (1 - frac * 0.35) + BODY_SHADOW[2] * frac * 0.35)
        draw.ellipse([seg_x - rx, seg_y - ry, seg_x + rx, seg_y + ry],
                     fill=(r, g, b, a))

# ── hat ───────────────────────────────────────────────────────────────────────

def draw_hat(draw, cx, head_top, t):
    tilt   = int(math.sin(t * 2 * math.pi) * 2)
    tip_x  = cx + tilt
    tip_y  = head_top - 34
    base_y = head_top + 4
    bw     = 17

    poly(draw, [(tip_x - 2, tip_y), (cx - bw, base_y), (cx,      base_y)], HAT_SHADOW)
    poly(draw, [(tip_x + 1, tip_y), (cx,      base_y), (cx + bw, base_y)], HAT_MID)
    poly(draw, [(tip_x,     tip_y + 3), (cx - 4, base_y), (cx + 4, base_y)], HAT_LIGHT)

    draw.rectangle([cx - bw - 1, base_y - 5, cx + bw + 1, base_y + 5], fill=HAT_BAND)
    ell(draw, cx, base_y, 6, 6, HAT_GEM)
    ell(draw, cx - 1, base_y - 1, 2, 2, (255, 115, 115, 255))

    ell(draw, tip_x, tip_y, 3, 3, GOLD)
    for ang in [0, 90, 180, 270]:
        rad = math.radians(ang)
        draw.point((tip_x + int(math.cos(rad) * 4),
                    tip_y + int(math.sin(rad) * 4)), fill=GOLD_LIGHT)

# ── head + face ───────────────────────────────────────────────────────────────

def draw_head(draw, cx, cy):
    r = 21
    ell(draw, cx + 2, cy + 2, r, r, BODY_SHADOW)
    ell(draw, cx,     cy,     r, r, BODY_MID)
    ell(draw, cx - 8, cy - 2, 11, 9, BODY_LIGHT)
    ell(draw, cx - 4, cy - 10, 6, 5, BODY_BRIGHT)

    # Right ear + earring
    ell(draw, cx + r - 2, cy + 3, 5, 7, BODY_MID)
    ell(draw, cx + r - 1, cy + 3, 3, 5, BODY_LIGHT)
    draw.line([(cx + r + 2, cy + 6), (cx + r + 3, cy + 13)], fill=GOLD, width=2)
    ell(draw, cx + r + 3, cy + 15, 4, 4, GOLD)
    ell(draw, cx + r + 3, cy + 15, 2, 2, GOLD_LIGHT)

def draw_face(draw, cx, cy):
    # Eyebrows — gently arched, relaxed (not raised in shock)
    for bx0, flip in [(cx - 15, 1), (cx + 5, -1)]:
        for j in range(8):
            arch = int((j - 3.5) ** 2 * 0.18)
            ell(draw, bx0 + j, cy - 10 - arch, 2, 2, BROW)

    # Eyes — half-lidded, cool/relaxed (not wide-open shocked)
    for ex in [cx - 9, cx + 9]:
        # eye white — slightly smaller, oval not circle
        ell(draw, ex, cy - 2, 6, 5, EYE_WHITE)
        # iris
        ell(draw, ex, cy - 2, 4, 4, EYE_IRIS)
        # pupil
        ell(draw, ex + 1, cy - 2, 2, 2, EYE_PUPIL)
        # shine
        ell(draw, ex - 1, cy - 4, 1, 1, (255, 255, 255, 220))
        # upper eyelid — covers top third of eye = relaxed/half-lidded look
        draw.line([(ex - 6, cy - 5), (ex + 6, cy - 5)], fill=BROW, width=2)
        draw.line([(ex - 5, cy - 6), (ex + 5, cy - 6)], fill=BROW, width=1)

    # Nose — small rounded bulb
    ell(draw, cx + 3, cy + 5, 5, 4, BODY_LIGHT)
    ell(draw, cx + 3, cy + 5, 3, 3, BODY_MID)

    # Friendly closed smirk — no gaping mouth
    sy = cy + 11
    # lower lip curve
    for dx in range(-8, 9):
        curve = int(dx * dx * 0.055)
        draw.point((cx + dx, sy + 3 + curve), fill=LIP)
    # upper lip line — straight with slight upturn at corners
    for dx in range(-8, 9):
        upturn = int(abs(dx) * 0.3)
        draw.point((cx + dx, sy - upturn), fill=LIP)
    # small visible teeth strip — understated
    ell(draw, cx, sy + 1, 6, 3, TEETH)

    # Goatee
    for dy in range(6):
        bw = max(0, 3 - abs(dy - 2))
        for dx in range(-bw, bw + 1):
            a = max(60, BEARD[3] - dy * 25)
            draw.point((cx + dx, sy + 5 + dy), fill=(*BEARD[:3], a))

# ── sash ──────────────────────────────────────────────────────────────────────

def draw_sash(draw, cx, waist_y):
    poly(draw,
         [(cx - 18, waist_y - 3), (cx + 18, waist_y - 3),
          (cx + 20, waist_y + 9), (cx,      waist_y + 13),
          (cx - 20, waist_y + 9)], SASH)
    draw.line([(cx - 14, waist_y + 1), (cx + 14, waist_y + 1)],
              fill=SASH_LIGHT, width=2)
    poly(draw,
         [(cx - 3, waist_y + 8), (cx + 7, waist_y + 8),
          (cx + 4, waist_y + 22), (cx - 7, waist_y + 21)],
         (*SASH[:3], 175))

# ── torso ─────────────────────────────────────────────────────────────────────

def draw_torso(draw, cx, chest_y):
    ell(draw, cx + 3, chest_y + 2, 26, 18, BODY_SHADOW)
    ell(draw, cx,     chest_y,     24, 17, BODY_MID)
    ell(draw, cx - 8, chest_y - 5, 12,  9, BODY_LIGHT)
    ell(draw, cx - 5, chest_y - 9,  6,  5, BODY_BRIGHT)
    belly_y = chest_y + 20
    ell(draw, cx + 2, belly_y + 1, 18, 14, BODY_SHADOW)
    ell(draw, cx,     belly_y,     17, 13, BODY_MID)
    ell(draw, cx - 5, belly_y - 3,  8,  7, BODY_LIGHT)

# ── arms ──────────────────────────────────────────────────────────────────────

def draw_arms_crossed(draw, cx, chest_y, t):
    """Iconic crossed-arms genie pose."""
    bob = int(math.sin(t * 2 * math.pi) * 1)
    ay  = chest_y + 4 + bob

    # Right arm (underneath) — goes left across chest
    thick_line(draw, cx + 24, ay - 2, cx + 10, ay + 6,  BODY_MID,   w=9)
    thick_line(draw, cx + 10, ay + 6, cx - 12, ay + 9,  BODY_MID,   w=8)
    ell(draw, cx - 14, ay + 10, 8, 7, BODY_LIGHT)
    ell(draw, cx + 20, ay - 1,  7, 5, GOLD)
    ell(draw, cx + 20, ay - 1,  5, 3, GOLD_LIGHT)

    # Left arm (on top) — goes right across chest
    thick_line(draw, cx - 24, ay + 2, cx - 10, ay + 8,  BODY_LIGHT, w=9)
    thick_line(draw, cx - 10, ay + 8, cx + 12, ay + 9,  BODY_MID,   w=8)
    ell(draw, cx + 14, ay + 10, 8, 7, BODY_LIGHT)
    ell(draw, cx - 20, ay + 2,  7, 5, GOLD)
    ell(draw, cx - 20, ay + 2,  5, 3, GOLD_LIGHT)

def draw_arms_drifting(draw, cx, chest_y, t):
    """Arms swaying — for drift/walk frames."""
    swing = math.sin(t * 2 * math.pi) * 8
    ay    = chest_y + 2
    for sign in [-1, 1]:
        sx = cx + sign * 24
        ex = cx + sign * 18 + int(swing * sign * 0.4)
        ey = ay + 16
        thick_line(draw, sx, ay, ex, ey, BODY_MID, w=9)
        fx = ex + int(swing * sign * 0.3)
        fy = ey + 14
        thick_line(draw, ex, ey, fx, fy, BODY_MID, w=8)
        ell(draw, fx, fy + 2, 7, 6, BODY_LIGHT)
        ell(draw, sx, ay, 7, 5, GOLD)
        ell(draw, sx, ay, 5, 3, GOLD_LIGHT)

def draw_arms_grab(draw, cx, chest_y):
    """Arms up — surprised/grabbed pose."""
    ay = chest_y - 2
    for sign in [-1, 1]:
        sx = cx + sign * 22
        ex = cx + sign * 30
        ey = ay - 16
        thick_line(draw, sx, ay, ex, ey, BODY_MID, w=9)
        ell(draw, ex, ey - 2, 7, 6, BODY_LIGHT)
        ell(draw, sx, ay,     7, 5, GOLD)
        ell(draw, sx, ay,     5, 3, GOLD_LIGHT)

# ── poof ─────────────────────────────────────────────────────────────────────

def draw_poof(draw, cx, cy, t, expanding):
    progress = t if expanding else (1 - t)
    r_outer  = int(55 * progress)
    for i in range(10):
        angle  = i * math.pi * 0.2 + progress * math.pi
        dist   = r_outer * (0.7 + 0.3 * math.sin(i * 1.3))
        px     = cx + int(math.cos(angle) * dist)
        py     = cy + int(math.sin(angle) * dist * 0.55)
        blob_r = max(2, int(18 * (1 - progress * 0.6)))
        alpha  = int(240 * progress if not expanding else 240 * (1 - progress * 0.3))
        draw.ellipse([px - blob_r, py - blob_r, px + blob_r, py + blob_r],
                     fill=(40, 100, 210, alpha))
    flash = max(2, int(28 * (1 - progress) if expanding else 28 * progress))
    draw.ellipse([cx - flash, cy - flash, cx + flash, cy + flash],
                 fill=(130, 195, 255, int(200 * (1 - progress))))
    for i in range(6):
        angle = i * math.pi / 3 + progress * math.pi * 2
        dist  = int(r_outer * 0.6)
        sx    = cx + int(math.cos(angle) * dist)
        sy    = cy + int(math.sin(angle) * dist * 0.6)
        draw.point((sx, sy),     fill=GOLD_LIGHT)
        draw.point((sx + 1, sy), fill=GOLD)

# ── assemble ──────────────────────────────────────────────────────────────────

def make_frame(mode, frame_idx, total_frames):
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    t   = frame_idx / max(total_frames - 1, 1)
    cx  = W // 2 + 1
    bob = math.sin(t * 2 * math.pi) * 3.5

    if mode in ("poof_expand", "poof_shrink"):
        draw_poof(draw, cx, H // 2, t, expanding=(mode == "poof_expand"))
        return img

    if mode == "float":
        head_cy = int(62 + bob)
        arm_fn  = lambda d, c, cy: draw_arms_crossed(d, c, cy, t)
        tail_a  = 9
    elif mode == "walk":
        head_cy = int(60 + bob * 0.5)
        arm_fn  = lambda d, c, cy: draw_arms_drifting(d, c, cy, t)
        tail_a  = 14
    else:  # grab
        head_cy = int(62 + bob * 0.3)
        arm_fn  = lambda d, c, cy: draw_arms_grab(d, c, cy)
        tail_a  = 7

    chest_y  = head_cy + 26
    waist_y  = chest_y + 28
    head_top = head_cy - 21

    img  = soft_glow(img, cx, chest_y, 52, GLOW_COL)
    draw = ImageDraw.Draw(img)

    draw_smoke_tail(draw, cx, waist_y, t, amplitude=tail_a)
    draw_sash(draw, cx, waist_y)
    draw_torso(draw, cx, chest_y)
    arm_fn(draw, cx, chest_y)
    draw_head(draw, cx, head_cy)
    draw_face(draw, cx, head_cy)
    draw_hat(draw, cx, head_top, t)

    soft = img.filter(ImageFilter.GaussianBlur(radius=0.7))
    img  = Image.blend(soft, img, 0.82)
    return img

# ── generate ──────────────────────────────────────────────────────────────────

SETS = {"float": 6, "walk": 6, "poof_expand": 4, "poof_shrink": 4}

# grab — single tilted frame
grab = make_frame("grab", 0, 1)
grab = grab.rotate(-20, expand=False, fillcolor=(0, 0, 0, 0))
grab.save(os.path.join(OUTDIR, "grab_00.png"))
print("  grab_00.png")

for mode, n in SETS.items():
    for i in range(n):
        frame = make_frame(mode, i, n)
        path  = os.path.join(OUTDIR, f"{mode}_{i:02d}.png")
        frame.save(path)
        print(f"  {path}")

print(f"\ndone. {sum(SETS.values()) + 1} frames in {OUTDIR}")
