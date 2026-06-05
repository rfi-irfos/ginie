#!/usr/bin/env python3
"""
Flaschengeist sprite generator for Ginie.
Design reference: Aladdin-style blue genie — tall pointed hat, gold headband+gem,
gold earring, muscular blue torso, gold necklace+gem, orange sash, baggy blue pants,
bare blue feet.
Run: python3 gen_sprites.py
Outputs to usb_assistant/frames/
"""
import os, math
from PIL import Image, ImageDraw, ImageFilter

HERE   = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "usb_assistant", "frames")
os.makedirs(OUTDIR, exist_ok=True)

W, H = 120, 160   # canvas — taller to fit hat + pants

# ── palette (matches reference image) ────────────────────────────────────────
SKIN_DARK   = ( 10,  60, 160, 255)   # deep blue shadow
SKIN_MID    = ( 20, 100, 200, 255)   # main body blue
SKIN_LIGHT  = ( 55, 145, 230, 255)   # highlight
SKIN_BRIGHT = ( 90, 170, 245, 255)   # specular

HAT_DARK    = ( 10,  20, 100, 255)   # dark navy hat shadow
HAT_MID     = ( 25,  45, 155, 255)   # main hat blue
HAT_BAND    = (200, 155,  10, 255)   # gold headband
HAT_GEM     = (200,  30,  30, 255)   # red gem in band
EARRING     = (220, 175,  20, 255)   # gold earring

NECKLACE    = (200, 155,  10, 255)   # gold necklace
NECK_GEM    = (180,  20,  20, 255)   # red pendant gem

SASH        = (210, 120,  15, 255)   # orange sash
SASH_DARK   = (160,  80,   5, 255)   # sash shadow
SASH_LAYER  = (220,  80,  10, 200)   # layered sash drape

PANTS       = ( 15,  40, 130, 255)   # dark blue baggy pants
PANTS_LIGHT = ( 30,  70, 180, 255)   # pants highlight crease

EYE_WHITE   = (220, 235, 255, 255)
EYE_IRIS    = ( 20,  80, 180, 255)
EYE_PUPIL   = (  5,  20,  60, 255)
BROW_COL    = ( 10,  30, 100, 255)
BEARD_COL   = ( 10,  40, 130, 220)

GLOW_COL    = ( 60, 120, 220,  25)

# ── primitives ────────────────────────────────────────────────────────────────

def ell(draw, cx, cy, rx, ry, fill, outline=None):
    draw.ellipse([cx-rx, cy-ry, cx+rx, cy+ry], fill=fill, outline=outline)

def poly(draw, pts, fill):
    draw.polygon(pts, fill=fill)

def soft_glow(img, cx, cy, r, color):
    ov = Image.new("RGBA", img.size, (0,0,0,0))
    d  = ImageDraw.Draw(ov)
    for s in range(r, 0, -3):
        t = s / r
        a = int(color[3] * (1 - t) * (1 - t))
        d.ellipse([cx-s, cy-s, cx+s, cy+s], fill=(*color[:3], a))
    return Image.alpha_composite(img, ov)

def thick_line(draw, x0, y0, x1, y1, color, w=4):
    steps = max(abs(x1-x0), abs(y1-y0), 1)
    hw = w // 2
    for s in range(steps + 1):
        t  = s / steps
        px = int(x0 + t * (x1 - x0))
        py = int(y0 + t * (y1 - y0))
        draw.ellipse([px-hw, py-hw, px+hw, py+hw], fill=color)

# ── hat ───────────────────────────────────────────────────────────────────────

def draw_hat(draw, cx, head_top, t):
    # tall pointed hat tilts slightly with animation
    tilt = int(math.sin(t * 2 * math.pi) * 3)
    tip_x = cx + tilt + 4
    tip_y = head_top - 42

    # hat body: filled polygon (dark back, mid front)
    base_left  = cx - 14
    base_right = cx + 16
    base_y     = head_top + 2

    # shadow side
    poly(draw, [(tip_x-3, tip_y), (base_left, base_y), (cx+2, base_y)], HAT_DARK)
    # highlight side
    poly(draw, [(tip_x+2, tip_y), (cx+2, base_y), (base_right, base_y)], HAT_MID)

    # gold band across base
    draw.rectangle([base_left-1, base_y-4, base_right+1, base_y+4], fill=HAT_BAND)

    # red gem in band centre
    ell(draw, cx+1, base_y, 5, 5, HAT_GEM)
    ell(draw, cx,   base_y-1, 2, 2, (240, 120, 120, 255))   # gem highlight

    # gold trim at very tip
    ell(draw, tip_x, tip_y, 3, 3, HAT_BAND)

    # hanging gold earring (right side of head)
    ear_x = cx + 14
    ear_y = head_top + 12
    draw.line([(ear_x, ear_y), (ear_x+1, ear_y+9)], fill=EARRING, width=2)
    ell(draw, ear_x+1, ear_y+12, 4, 4, EARRING)
    ell(draw, ear_x+1, ear_y+12, 2, 2, (255, 230, 100, 255))

# ── head + face ───────────────────────────────────────────────────────────────

def draw_head(draw, cx, cy, t):
    # head shape: slightly wider at cheeks
    ell(draw, cx, cy,   17, 18, SKIN_DARK)   # shadow ring
    ell(draw, cx, cy-1, 15, 16, SKIN_MID)
    ell(draw, cx-4, cy-4, 7, 7, SKIN_LIGHT)  # highlight

    # eyebrows — thick, slightly arched
    for side, ex in [(-1, cx-6), (1, cx+5)]:
        for dx in range(6):
            by = cy - 9 - int(abs(dx - 2.5) * 0.6)
            draw.point((ex + dx, by), fill=BROW_COL)
        draw.point((ex + 1, cy-10), fill=BROW_COL)

    # eyes
    for ex in [cx-6, cx+6]:
        ell(draw, ex, cy-4, 5, 4, EYE_WHITE)
        ell(draw, ex, cy-4, 3, 3, EYE_IRIS)
        ell(draw, ex+1, cy-4, 2, 2, EYE_PUPIL)
        draw.point((ex-1, cy-6), fill=(255, 255, 255, 200))  # specular

    # smile — wider, slightly visible teeth
    smile_y = cy + 6
    for dx in range(-5, 6):
        sy = smile_y + int(abs(dx) * 0.5)
        draw.point((cx + dx, sy), fill=SKIN_DARK)

    # small goatee beard
    for dy in range(5):
        bw = max(1, 4 - dy)
        for dx in range(-bw, bw+1):
            draw.point((cx + dx, cy + 9 + dy), fill=BEARD_COL)

# ── torso ─────────────────────────────────────────────────────────────────────

def draw_torso(draw, cx, cy, t):
    wave = math.sin(t * 2 * math.pi) * 2

    # chest: wide muscular block
    ell(draw, cx,   cy,    19, 22, SKIN_DARK)
    ell(draw, cx,   cy-2,  17, 19, SKIN_MID)
    # pec highlights
    ell(draw, cx-6, cy-5,   7,  6, SKIN_LIGHT)
    ell(draw, cx+6, cy-5,   6,  5, SKIN_MID)

    # gold necklace across collarbone
    nk_y = cy - 14
    for dx in range(-12, 13):
        dy = int(abs(dx) * 0.35)
        draw.point((cx + dx, nk_y + dy), fill=NECKLACE)
    # pendant gem
    ell(draw, cx, nk_y+8, 5, 5, NECK_GEM)
    ell(draw, cx-1, nk_y+7, 2, 2, (240, 100, 100, 255))

    # arms
    _draw_arms(draw, cx, cy, t)

def _draw_arms(draw, cx, cy, t):
    wave = math.sin(t * 2 * math.pi)
    for side in [-1, 1]:
        bx = cx + side * 19
        by = cy - 4
        # upper arm — forearm bent outward to "hands on hips" pose
        raise_off = int(wave * 3 * side)
        elbow_x = bx + side * 13
        elbow_y = by + 10 + raise_off
        thick_line(draw, bx, by, elbow_x, elbow_y, SKIN_MID, w=7)
        ell(draw, elbow_x, elbow_y, 5, 5, SKIN_MID)
        # forearm going down-inward (hands on hips)
        hand_x = elbow_x - side * 6
        hand_y = elbow_y + 12
        thick_line(draw, elbow_x, elbow_y, hand_x, hand_y, SKIN_MID, w=6)
        ell(draw, hand_x, hand_y, 5, 5, SKIN_LIGHT)
        # gold wristband
        ell(draw, hand_x, hand_y - 3, 6, 4, NECKLACE)

# ── sash + pants ──────────────────────────────────────────────────────────────

def draw_lower(draw, cx, waist_y, t):
    # orange sash wrapping the waist
    sash_pts = [
        (cx-18, waist_y-3),
        (cx+18, waist_y-3),
        (cx+20, waist_y+10),
        (cx,    waist_y+14),
        (cx-20, waist_y+10),
    ]
    poly(draw, sash_pts, SASH)
    # sash overlap flap hanging down-left
    flap = [
        (cx-4, waist_y+8),
        (cx+6, waist_y+8),
        (cx+3, waist_y+24),
        (cx-8, waist_y+22),
    ]
    poly(draw, flap, SASH_LAYER)
    # sash highlight
    draw.line([(cx-14, waist_y+1), (cx+14, waist_y+1)], fill=(240, 160, 50, 180), width=2)

    # baggy pants: two large rounded blobs for thighs + gathered ankles
    for side in [-1, 1]:
        px = cx + side * 9
        # thigh bulge
        ell(draw, px, waist_y+22, 12, 18, PANTS_LIGHT if side < 0 else PANTS)
        ell(draw, px, waist_y+22, 10, 16, PANTS)
        # crease highlights
        ell(draw, px + side*3, waist_y+16, 4, 6, PANTS_LIGHT)
        # gathered ankle band
        ell(draw, px, waist_y+38, 8, 5, PANTS_DARK if side > 0 else PANTS)

    # bare feet
    for side in [-1, 1]:
        fx = cx + side * 9
        fy = waist_y + 46
        ell(draw, fx, fy, 9, 5, SKIN_MID)
        ell(draw, fx + side*6, fy, 4, 3, SKIN_MID)  # toes
        ell(draw, fx - side*2, fy-1, 3, 2, SKIN_LIGHT)  # foot highlight

PANTS_DARK = (10, 25, 90, 255)

# ── walk legs ─────────────────────────────────────────────────────────────────

def draw_walk_legs(draw, cx, waist_y, t):
    # sash stays
    sash_pts = [
        (cx-18, waist_y-3),
        (cx+18, waist_y-3),
        (cx+20, waist_y+10),
        (cx,    waist_y+14),
        (cx-20, waist_y+10),
    ]
    poly(draw, sash_pts, SASH)
    draw.line([(cx-14, waist_y+1), (cx+14, waist_y+1)], fill=(240, 160, 50, 180), width=2)

    for side, phase in [(-1, 0), (1, math.pi)]:
        swing = math.sin(t * 2 * math.pi + phase) * 0.5
        seg   = 20
        # thigh
        kx = cx + side * 8 + int(math.sin(swing) * seg * 0.7)
        ky = waist_y + int(math.cos(swing) * seg * 0.6) + 16
        thick_line(draw, cx + side*8, waist_y+8, kx, ky, PANTS_LIGHT if side < 0 else PANTS, w=9)
        ell(draw, kx, ky, 6, 6, PANTS)
        # shin
        swing2 = swing * 0.5
        fx = kx + int(math.sin(swing2) * seg * 0.8)
        fy = ky + int(math.cos(swing2) * seg * 0.6) + 4
        thick_line(draw, kx, ky, fx, fy, PANTS, w=7)
        # foot
        ell(draw, fx, fy+2, 9, 5, SKIN_MID)
        ell(draw, fx + side*5, fy+2, 4, 3, SKIN_MID)
        ell(draw, fx - side*2, fy, 3, 2, SKIN_LIGHT)

# ── assemble frame ────────────────────────────────────────────────────────────

def make_frame(mode, frame_idx, total_frames):
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    t   = frame_idx / max(total_frames - 1, 1)
    cx  = W // 2 + 2   # slight right offset (earring hangs right)
    bob = math.sin(t * 2 * math.pi) * 3

    if mode == "poof_expand":
        _poof(img, draw, cx, H//2, t, expanding=True)
        return img
    if mode == "poof_shrink":
        _poof(img, draw, cx, H//2, t, expanding=False)
        return img

    if mode == "float":
        head_cy  = int(H * 0.40 + bob)   # enough clearance for the tall hat above
        torso_cy = head_cy + 28
        waist_y  = torso_cy + 18
        do_walk  = False
    else:
        head_cy  = int(H * 0.38)
        torso_cy = head_cy + 28
        waist_y  = torso_cy + 18
        do_walk  = True

    head_top = head_cy - 17

    # 1. ambient glow
    img = soft_glow(img, cx, torso_cy, 46, GLOW_COL)
    draw = ImageDraw.Draw(img)

    # 2. lower body (behind torso)
    if do_walk:
        draw_walk_legs(draw, cx, waist_y, t)
    else:
        draw_lower(draw, cx, waist_y, t)

    # 3. torso + arms
    draw_torso(draw, cx, torso_cy, t)

    # 4. head
    draw_head(draw, cx, head_cy, t)

    # 5. hat (drawn last so it sits on top of head)
    draw_hat(draw, cx, head_top, t)

    # soft edge blend
    soft = img.filter(ImageFilter.GaussianBlur(radius=0.6))
    img  = Image.blend(soft, img, 0.85)

    return img


def _poof(img, draw, cx, cy, t, expanding):
    r = int((55 * t) if expanding else (55 * (1 - t)))
    for i in range(8):
        angle  = i * math.pi / 4 + t * math.pi
        px     = cx + int(math.cos(angle) * r)
        py     = cy + int(math.sin(angle) * r * 0.55)
        blob_r = max(3, 16 - int(t * 10))
        alpha  = int(230 * (1 - t) if expanding else 230 * t)
        draw.ellipse([px-blob_r, py-blob_r, px+blob_r, py+blob_r],
                     fill=(30, 90, 200, alpha))
    flash_r = max(2, int(22 * (1-t) if expanding else 22*t))
    draw.ellipse([cx-flash_r, cy-flash_r, cx+flash_r, cy+flash_r],
                 fill=(120, 180, 255, int(190 * (1-t if expanding else t))))

# ── generate ──────────────────────────────────────────────────────────────────

SETS = {
    "float":        6,
    "walk":         6,
    "poof_expand":  4,
    "poof_shrink":  4,
}

for mode, n in SETS.items():
    for i in range(n):
        frame = make_frame(mode, i, n)
        path  = os.path.join(OUTDIR, f"{mode}_{i:02d}.png")
        frame.save(path)
        print(f"  {path}")

print(f"\ndone. {sum(SETS.values())} frames in {OUTDIR}")
