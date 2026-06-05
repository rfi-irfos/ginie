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

def draw_hat_back(draw, cx, head_top, t):
    """Hat seen from behind — cone shape, gold band visible."""
    tilt   = int(math.sin(t * 2 * math.pi) * 2)
    tip_x  = cx + tilt
    tip_y  = head_top - 34
    base_y = head_top + 4
    bw     = 17
    poly(draw, [(tip_x - 2, tip_y), (cx - bw, base_y), (cx + bw, base_y)], HAT_SHADOW)
    poly(draw, [(tip_x,     tip_y + 2), (cx - 6, base_y), (cx + 6, base_y)], HAT_MID)
    # soft back brim — no hard band
    draw.arc([cx - bw - 1, base_y - 3, cx + bw + 1, base_y + 8],
             start=0, end=180, fill=HAT_SHADOW, width=3)
    ell(draw, tip_x, tip_y, 3, 3, GOLD)

def draw_head_back(draw, cx, cy):
    """Smooth back of head, no face."""
    r = 21
    ell(draw, cx + 2, cy + 2, r, r, BODY_SHADOW)
    ell(draw, cx,     cy,     r, r, BODY_MID)
    # highlight (shifts to top-right from behind)
    ell(draw, cx + 6, cy - 8, 9, 7, BODY_LIGHT)
    ell(draw, cx + 4, cy - 12, 5, 4, BODY_BRIGHT)
    # left ear visible from behind (on right side of back view)
    ell(draw, cx - r + 2, cy + 3, 5, 7, BODY_MID)
    ell(draw, cx - r + 1, cy + 3, 3, 5, BODY_LIGHT)

def draw_torso_back(draw, cx, chest_y):
    """Back of barrel chest — two vertical muscle highlights."""
    ell(draw, cx + 3, chest_y + 2, 26, 18, BODY_SHADOW)
    ell(draw, cx,     chest_y,     24, 17, BODY_MID)
    # back muscle highlights
    ell(draw, cx - 6, chest_y - 4, 7, 10, BODY_LIGHT)
    ell(draw, cx + 7, chest_y - 4, 6,  9, BODY_MID)
    belly_y = chest_y + 20
    ell(draw, cx + 2, belly_y + 1, 18, 14, BODY_SHADOW)
    ell(draw, cx,     belly_y,     17, 13, BODY_MID)
    ell(draw, cx + 5, belly_y - 2,  6,  7, BODY_LIGHT)

def draw_arms_crossed_back(draw, cx, chest_y, t):
    """Crossed arms from behind — shows upper arms and cuffs."""
    bob = int(math.sin(t * 2 * math.pi) * 1)
    ay  = chest_y + 4 + bob
    for sign in [-1, 1]:
        thick_line(draw, cx + sign * 24, ay - 2, cx + sign * 10, ay + 8, BODY_MID, w=9)
        ell(draw, cx + sign * 20, ay - 1, 7, 5, GOLD)
        ell(draw, cx + sign * 20, ay - 1, 5, 3, GOLD_LIGHT)
    # crossed forearms on the back
    thick_line(draw, cx - 10, ay + 6, cx + 12, ay + 10, BODY_SHADOW, w=8)
    thick_line(draw, cx + 10, ay + 6, cx - 12, ay + 10, BODY_MID,    w=8)

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
        seg_y = waist_y + int(frac * 44)
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
    """Zipfelmütze — soft floppy hat, tip droops and sways."""
    phase  = t * 2 * math.pi
    flop_x = int(math.sin(phase) * 6) + 9   # droop right by default, sway ±6
    flop_y = int(abs(math.sin(phase)) * 3)   # tip dips a little at extremes
    tip_x  = cx + flop_x
    tip_y  = head_top - 32 + flop_y
    base_y = head_top + 3
    bw     = 17

    # shadow face (right side)
    poly(draw, [(cx + 1, base_y), (cx + bw, base_y), (tip_x + 2, tip_y + 4)], HAT_SHADOW)
    # main hat body
    poly(draw, [(cx - bw, base_y), (cx + bw, base_y), (tip_x, tip_y)], HAT_MID)
    # highlight stripe — left-lit
    poly(draw, [(cx - bw + 1, base_y), (cx + 2, base_y), (tip_x - 3, tip_y + 12)], HAT_LIGHT)

    # soft rounded brim — no hard band, just fabric draping on head
    draw.arc([cx - bw - 1, base_y - 3, cx + bw + 1, base_y + 8],
             start=0, end=180, fill=HAT_SHADOW, width=3)
    draw.arc([cx - bw + 3, base_y - 1, cx + bw - 3, base_y + 5],
             start=0, end=180, fill=HAT_MID, width=2)

    # pompom at drooping tip
    ell(draw, tip_x, tip_y, 5, 5, GOLD)
    ell(draw, tip_x - 1, tip_y - 1, 3, 3, GOLD_LIGHT)
    ell(draw, tip_x + 1, tip_y + 1, 2, 2, GOLD)

# ── head + face ───────────────────────────────────────────────────────────────

def draw_head(draw, cx, cy):
    r = 21
    ell(draw, cx + 2, cy + 2, r, r, BODY_SHADOW)
    ell(draw, cx,     cy,     r, r, BODY_MID)
    ell(draw, cx - 8, cy - 2, 11, 9, BODY_LIGHT)
    ell(draw, cx - 4, cy - 10, 6, 5, BODY_BRIGHT)

    # Right ear (no earring)
    ell(draw, cx + r - 2, cy + 3, 5, 7, BODY_MID)
    ell(draw, cx + r - 1, cy + 3, 3, 5, BODY_LIGHT)

def draw_face(draw, cx, cy, expression="bruh"):
    if expression == "bruh":
        _face_bruh(draw, cx, cy)
    elif expression == "smirk":
        _face_smirk(draw, cx, cy)
    elif expression == "surprised":
        _face_surprised(draw, cx, cy)
    elif expression == "whee":
        _face_whee(draw, cx, cy)
    elif expression == "sleepy":
        _face_sleepy(draw, cx, cy)
    elif expression == "happy":
        _face_happy(draw, cx, cy)
    elif expression == "scared":
        _face_scared(draw, cx, cy)

def _brows_normal(draw, cx, cy):
    for bx0 in [cx - 15, cx + 5]:
        for j in range(8):
            arch = int((j - 3.5) ** 2 * 0.18)
            ell(draw, bx0 + j, cy - 10 - arch, 2, 2, BROW)

def _brows_raised(draw, cx, cy, extra=6):
    for bx0 in [cx - 15, cx + 5]:
        for j in range(8):
            arch = int((j - 3.5) ** 2 * 0.22)
            ell(draw, bx0 + j, cy - 14 - arch - extra + j // 3, 2, 2, BROW)

def _nose(draw, cx, cy):
    # Voldemort slits — centered, very subtle
    ell(draw, cx - 3, cy + 6, 2, 3, (*BODY_SHADOW[:3], 150))
    ell(draw, cx + 3, cy + 6, 2, 3, (*BODY_SHADOW[:3], 150))

def _goatee(draw, cx, sy):
    """Pointed goatee — narrows to a tip."""
    for dy in range(9):
        bw = max(0, 4 - int(dy * 0.6))
        a  = max(30, BEARD[3] - dy * 18)
        for dx in range(-bw, bw + 1):
            draw.point((cx + dx, sy + dy), fill=(*BEARD[:3], a))

def _face_bruh(draw, cx, cy):
    """Bruh — unimpressed, heavy lids, flat mouth."""
    # inner corners of brows slightly raised = annoyed arch
    for sign in [-1, 1]:
        bx = cx + sign * 9
        draw.line([(bx - 5, cy - 13 + sign * 2), (bx + 5, cy - 14 - sign * 1)],
                  fill=BROW, width=2)
    # half-lidded eyes — whites, iris, pupil, then heavy lid over top half
    for ex in [cx - 9, cx + 9]:
        ell(draw, ex, cy,     6, 6, EYE_WHITE)
        ell(draw, ex, cy + 1, 4, 4, EYE_IRIS)
        ell(draw, ex + 1, cy, 2, 2, EYE_PUPIL)
        # solid eyelid bar covering the top ~45% of the eye
        draw.rectangle([ex - 7, cy - 8, ex + 7, cy - 1], fill=BODY_MID)
    _nose(draw, cx, cy)
    # dead-flat mouth, tiny downturn at corners
    sy = cy + 12
    draw.line([(cx - 8, sy), (cx + 8, sy)], fill=LIP, width=2)
    draw.line([(cx - 8, sy), (cx - 10, sy + 2)], fill=LIP, width=1)
    draw.line([(cx + 8, sy), (cx + 10, sy + 2)], fill=LIP, width=1)
    _goatee(draw, cx, sy + 4)

def _face_smirk(draw, cx, cy):
    """Cool relaxed smirk — default float expression."""
    _brows_normal(draw, cx, cy)
    for ex in [cx - 9, cx + 9]:
        ell(draw, ex, cy - 2, 6, 5, EYE_WHITE)
        ell(draw, ex, cy - 2, 4, 4, EYE_IRIS)
        ell(draw, ex + 1, cy - 2, 2, 2, EYE_PUPIL)
        ell(draw, ex - 1, cy - 4, 1, 1, (255, 255, 255, 220))
        draw.line([(ex - 6, cy - 5), (ex + 6, cy - 5)], fill=BROW, width=2)
        draw.line([(ex - 5, cy - 6), (ex + 5, cy - 6)], fill=BROW, width=1)
    _nose(draw, cx, cy)
    sy = cy + 11
    for dx in range(-8, 9):
        draw.point((cx + dx, sy + 3 + int(dx * dx * 0.055)), fill=LIP)
    for dx in range(-8, 9):
        draw.point((cx + dx, sy - int(abs(dx) * 0.3)), fill=LIP)
    ell(draw, cx, sy + 1, 6, 3, TEETH)
    _goatee(draw, cx, sy + 5)

def _face_surprised(draw, cx, cy):
    """YOOOO face — used when dragged. Wide eyes, raised brows, open mouth."""
    _brows_raised(draw, cx, cy, extra=4)
    for ex in [cx - 9, cx + 9]:
        ell(draw, ex, cy - 2, 7, 7, EYE_WHITE)
        ell(draw, ex, cy - 2, 5, 5, EYE_IRIS)
        ell(draw, ex + 1, cy - 2, 3, 3, EYE_PUPIL)
        ell(draw, ex - 2, cy - 5, 2, 2, (255, 255, 255, 220))
    _nose(draw, cx, cy)
    # wide open O-shaped mouth
    sy = cy + 12
    ell(draw, cx, sy + 3, 9, 7, LIP)
    ell(draw, cx, sy + 3, 7, 5, TEETH)
    ell(draw, cx, sy + 5, 5, 4, (220, 100, 120, 255))   # tongue/throat
    _goatee(draw, cx, sy + 11)
    # exclamation marks
    for ox in [-18, 18]:
        draw.line([(cx + ox, cy - 12), (cx + ox, cy - 6)], fill=GOLD, width=2)
        ell(draw, cx + ox, cy - 4, 2, 2, GOLD)

def _face_whee(draw, cx, cy):
    """WHEEE — used when thrown. Squinted XD eyes, huge grin."""
    _brows_normal(draw, cx, cy)
    # squinted happy eyes — just arcs, no whites
    for ex in [cx - 9, cx + 9]:
        draw.arc([ex - 6, cy - 7, ex + 6, cy + 1], start=200, end=340, fill=BROW, width=3)
    _nose(draw, cx, cy)
    # huge open grin
    sy = cy + 10
    for dx in range(-11, 12):
        curve = int(dx * dx * 0.04)
        draw.point((cx + dx, sy + 6 + curve), fill=LIP)
    draw.line([(cx - 11, sy), (cx + 11, sy)], fill=LIP, width=2)
    ell(draw, cx, sy + 3, 10, 4, TEETH)
    for tx in [-5, 0, 5]:
        draw.line([(cx + tx, sy), (cx + tx, sy + 6)], fill=(*LIP[:3], 60), width=1)
    _goatee(draw, cx, sy + 8)

def _face_sleepy(draw, cx, cy):
    """Sleeping — closed eyes, tiny smile, ZZZs."""
    _brows_normal(draw, cx, cy)
    # closed eyes — just a gentle curve
    for ex in [cx - 9, cx + 9]:
        draw.arc([ex - 6, cy - 6, ex + 6, cy + 2], start=190, end=350, fill=BROW, width=3)
    _nose(draw, cx, cy)
    # small peaceful smile
    sy = cy + 12
    for dx in range(-6, 7):
        draw.point((cx + dx, sy + int(dx * dx * 0.07)), fill=LIP)
    # ZZZs floating near hat (drawn as pixel staircase z-shapes)
    for i, (ox, oy) in enumerate([(14, -18), (20, -26), (26, -36)]):
        size = 3 + i
        zx, zy = cx + ox, cy + oy
        draw.line([(zx, zy), (zx + size, zy)], fill=(*GOLD[:3], 200), width=1)
        draw.line([(zx + size, zy), (zx, zy + size)], fill=(*GOLD[:3], 200), width=1)
        draw.line([(zx, zy + size), (zx + size, zy + size)], fill=(*GOLD[:3], 200), width=1)
    _goatee(draw, cx, sy + 4)

def _face_happy(draw, cx, cy):
    """Happy open — used while drifting/walking."""
    _brows_normal(draw, cx, cy)
    for ex in [cx - 9, cx + 9]:
        ell(draw, ex, cy - 2, 6, 6, EYE_WHITE)
        ell(draw, ex, cy - 2, 4, 4, EYE_IRIS)
        ell(draw, ex + 1, cy - 2, 2, 2, EYE_PUPIL)
        ell(draw, ex - 1, cy - 5, 2, 2, (255, 255, 255, 210))
    _nose(draw, cx, cy)
    sy = cy + 11
    for dx in range(-9, 10):
        draw.point((cx + dx, sy + 4 + int(dx * dx * 0.048)), fill=LIP)
    draw.line([(cx - 9, sy - 1), (cx + 9, sy - 1)], fill=LIP, width=2)
    ell(draw, cx, sy + 2, 8, 4, TEETH)
    _goatee(draw, cx, sy + 6)

def _face_scared(draw, cx, cy):
    """Surprised — slightly wide eyes, small open mouth, raised brows."""
    _brows_raised(draw, cx, cy, extra=2)
    for ex in [cx - 9, cx + 9]:
        ell(draw, ex, cy - 1,  7, 7, EYE_WHITE)
        ell(draw, ex, cy,      4, 4, EYE_IRIS)
        ell(draw, ex + 1, cy - 1, 2, 2, EYE_PUPIL)
        ell(draw, ex - 1, cy - 4, 2, 2, (255, 255, 255, 200))
    _nose(draw, cx, cy)
    sy = cy + 11
    # small surprised "oh" — not a screaming O
    ell(draw, cx + 1, sy + 2, 6, 5, LIP)
    ell(draw, cx + 1, sy + 2, 4, 3, (20, 12, 40, 255))
    _goatee(draw, cx, sy + 8)

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
    # pecs — shadow + base + highlight + specular
    ell(draw, cx + 3, chest_y + 2, 26, 18, BODY_SHADOW)
    ell(draw, cx,     chest_y,     24, 17, BODY_MID)
    # left pec
    ell(draw, cx - 9, chest_y - 2, 11, 9,  BODY_LIGHT)
    ell(draw, cx - 6, chest_y - 7,  6, 5,  BODY_BRIGHT)
    # right pec shadow (depth)
    ell(draw, cx + 9, chest_y - 1, 10, 8,  (*BODY_SHADOW[:3], 140))
    # pec split line
    draw.line([(cx, chest_y - 14), (cx, chest_y + 6)],
              fill=(*BODY_SHADOW[:3], 100), width=1)
    # rim light — bright edge on right side
    for oy in range(-12, 14, 3):
        ell(draw, cx + 24, chest_y + oy, 3, 3, (*BODY_LIGHT[:3], 90))
    belly_y = chest_y + 18
    ell(draw, cx + 2, belly_y + 1, 17, 13, BODY_SHADOW)
    ell(draw, cx,     belly_y,     16, 12, BODY_MID)
    ell(draw, cx - 5, belly_y - 3,  8,  7, BODY_LIGHT)

# ── arms ──────────────────────────────────────────────────────────────────────

def draw_arms_crossed(draw, cx, chest_y, t):
    """Iconic crossed-arms genie pose."""
    bob = int(math.sin(t * 2 * math.pi) * 1)
    ay  = chest_y + 4 + bob

    # Right arm (underneath) — darker, shoulder left toward body
    ell(draw, cx + 22, ay - 2, 9, 7, BODY_SHADOW)       # shoulder
    thick_line(draw, cx + 22, ay - 1, cx + 8,  ay + 6,  BODY_SHADOW, w=10)
    thick_line(draw, cx + 8,  ay + 6, cx - 13, ay + 9,  BODY_MID,    w=9)
    ell(draw, cx - 15, ay + 10, 7, 6, BODY_LIGHT)        # fist
    ell(draw, cx - 13, ay + 8,  9, 6, GOLD)              # cuff at wrist
    ell(draw, cx - 12, ay + 7,  6, 4, GOLD_LIGHT)

    # Left arm (on top) — lighter, goes right
    ell(draw, cx - 22, ay + 2, 9, 7, BODY_MID)           # shoulder
    thick_line(draw, cx - 22, ay + 2, cx - 8,  ay + 8,  BODY_LIGHT, w=10)
    thick_line(draw, cx - 8,  ay + 8, cx + 13, ay + 9,  BODY_MID,   w=9)
    ell(draw, cx + 15, ay + 10, 7, 6, BODY_BRIGHT)       # fist
    ell(draw, cx + 13, ay + 8,  9, 6, GOLD)              # cuff at wrist
    ell(draw, cx + 12, ay + 7,  6, 4, GOLD_LIGHT)

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

def draw_arms_scared(draw, cx, chest_y, t):
    """Both arms flung UP in panic — thrown above head level."""
    shake = int(math.sin(t * 2 * math.pi) * 2)
    ay    = chest_y + 2 + shake
    for sign in [-1, 1]:
        sx = cx + sign * 18       # shoulder — close to body
        # upper arm: sharp diagonal outward + up
        ex = cx + sign * 36
        ey = ay - 26
        thick_line(draw, sx, ay, ex, ey, BODY_MID,   w=10)
        # forearm: continues steeply upward
        fx = cx + sign * 30
        fy = ey - 24               # fists end up well above head
        thick_line(draw, ex, ey, fx, fy, BODY_LIGHT, w=9)
        ell(draw, fx, fy - 4, 7, 6, BODY_BRIGHT)     # fist
        ell(draw, sx, ay - 2,  9, 7, GOLD)            # shoulder cuff
        ell(draw, sx, ay - 2,  6, 4, GOLD_LIGHT)
        ell(draw, fx, fy + 1,  8, 6, GOLD)            # wrist cuff
        ell(draw, fx, fy + 1,  5, 3, GOLD_LIGHT)

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
        head_cy    = int(62 + bob)
        arm_fn     = lambda d, c, cy: draw_arms_crossed(d, c, cy, t)
        tail_a     = 9
        expression = "bruh"
    elif mode == "walk":
        head_cy    = int(60 + bob * 0.5)
        arm_fn     = lambda d, c, cy: draw_arms_drifting(d, c, cy, t)
        tail_a     = 14
        expression = "happy"
    elif mode == "whee":
        head_cy    = int(60 + bob * 0.4)
        arm_fn     = lambda d, c, cy: draw_arms_drifting(d, c, cy, t)
        tail_a     = 18
        expression = "whee"
    elif mode == "sleep":
        head_cy    = int(64 + bob * 0.3)
        arm_fn     = lambda d, c, cy: draw_arms_crossed(d, c, cy, t)
        tail_a     = 5
        expression = "sleepy"
    elif mode == "back_float":
        head_cy    = int(62 + bob)
        tail_a     = 9
        expression = None   # back-view, no face
    elif mode == "back_walk":
        head_cy    = int(60 + bob * 0.5)
        tail_a     = 14
        expression = None
    else:  # grab / drag
        head_cy    = int(62 + bob * 0.3)
        arm_fn     = lambda d, c, cy: draw_arms_scared(d, c, cy, t)
        tail_a     = 7
        expression = "scared"

    chest_y  = head_cy + 22   # was 26 — tighten neck
    waist_y  = chest_y + 18   # was 28 — keeps tail inside canvas
    head_top = head_cy - 21

    img  = soft_glow(img, cx, chest_y, 52, GLOW_COL)
    draw = ImageDraw.Draw(img)

    # back-view branch — no face
    if mode in ("back_float", "back_walk"):
        draw_smoke_tail(draw, cx, waist_y, t, amplitude=tail_a)
        draw_sash(draw, cx, waist_y)
        draw_torso_back(draw, cx, chest_y)
        # no arms — just the cold back
        draw_head_back(draw, cx, head_cy)
        draw_hat_back(draw, cx, head_top, t)
        soft = img.filter(ImageFilter.GaussianBlur(radius=0.7))
        img  = Image.blend(soft, img, 0.82)
        return img

    draw_smoke_tail(draw, cx, waist_y, t, amplitude=tail_a)
    draw_sash(draw, cx, waist_y)
    draw_torso(draw, cx, chest_y)
    arm_fn(draw, cx, chest_y)
    draw_head(draw, cx, head_cy)
    draw_face(draw, cx, head_cy, expression)
    draw_hat(draw, cx, head_top, t)

    soft = img.filter(ImageFilter.GaussianBlur(radius=0.7))
    img  = Image.blend(soft, img, 0.82)
    return img

# ── generate ──────────────────────────────────────────────────────────────────

SETS = {"float": 6, "walk": 6, "whee": 6, "sleep": 4,
        "back_float": 6, "back_walk": 6,
        "poof_expand": 4, "poof_shrink": 4}

def _upscale(img):
    """2x LANCZOS — gives cairo more pixels to work with at high z."""
    return img.resize((W * 2, H * 2), Image.Resampling.LANCZOS)

# grab — single tilted frame
grab = make_frame("grab", 0, 1)
grab = grab.rotate(-20, expand=False, fillcolor=(0, 0, 0, 0))
grab = _upscale(grab)
grab.save(os.path.join(OUTDIR, "grab_00.png"))
print("  grab_00.png")

for mode, n in SETS.items():
    for i in range(n):
        frame = _upscale(make_frame(mode, i, n))
        path  = os.path.join(OUTDIR, f"{mode}_{i:02d}.png")
        frame.save(path)
        print(f"  {path}")

print(f"\ndone. {sum(SETS.values()) + 1} frames in {OUTDIR}")
