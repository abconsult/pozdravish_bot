#!/usr/bin/env python3
"""
scripts/generate_templates.py

Standalone local-dev script. Run it to generate preview JPEG images
for the 3 template postcards and save them to assets/templates/.

After reviewing the images:
  1. Send each JPEG to any Telegram bot (e.g. @RawDataBot) or
     forward to your main bot via BotFather test chat.
  2. Copy the file_id from the Telegram API response.
  3. Paste each file_id into TEMPLATE_POSTCARDS in bot/config.py.
  4. Commit and deploy.

Usage:
    pip install Pillow
    python scripts/generate_templates.py

Output: assets/templates/birthday.jpg, march8.jpg, universal.jpg
"""
import io
import math
import os
import random
from PIL import Image, ImageDraw, ImageFont

W, H = 800, 500
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "templates")
os.makedirs(OUT_DIR, exist_ok=True)


def gradient(draw, w, h, top, bottom):
    for y in range(h):
        t = y / h
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))


def font(size):
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def shadow_text(draw, xy, text, fnt, shadow=(0, 0, 0, 140), fill=(255, 255, 255, 255)):
    x, y = xy
    for dx, dy in [(-2, 2), (2, 2), (0, 3)]:
        draw.text((x + dx, y + dy), text, font=fnt, fill=shadow)
    draw.text((x, y), text, font=fnt, fill=fill)


def centered(draw, img_w, y, text, fnt, **kw):
    bb = draw.textbbox((0, 0), text, font=fnt)
    tw = bb[2] - bb[0]
    shadow_text(draw, ((img_w - tw) // 2, y), text, fnt, **kw)


def overlay(img, color=(0, 0, 0, 85)):
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.rounded_rectangle([W // 2 - 300, H // 2 - 90, W // 2 + 300, H // 2 + 95],
                        radius=32, fill=color)
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


# ── birthday ─────────────────────────────────────────────────────────────────
img = Image.new("RGB", (W, H))
d = ImageDraw.Draw(img)
gradient(d, W, H, (255, 182, 155), (255, 223, 100))
rng = random.Random(42)
for _ in range(65):
    cx, cy = rng.randint(0, W), rng.randint(0, H)
    r = rng.randint(4, 18)
    col = rng.choice([(255,80,80),(255,200,0),(200,80,255),(80,200,255),(80,255,150)])
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=col)
img = overlay(img, (0, 0, 0, 90))
d = ImageDraw.Draw(img)
centered(d, W, H//2-58, "С Днём Рождения!", font(62),
         shadow=(120,40,0,180), fill=(255,255,255,255))
centered(d, W, H//2+22, "✨  🎂  ✨", font(28), fill=(255,240,160,255))
path = os.path.join(OUT_DIR, "birthday.jpg")
img.save(path, "JPEG", quality=92)
print(f"✅  birthday.jpg  →  {path}")

# ── march8 ───────────────────────────────────────────────────────────────────
def petals(draw, cx, cy, r):
    for i in range(6):
        a = 2 * math.pi * i / 6
        px, py = cx + r * math.cos(a), cy + r * math.sin(a)
        hr = r // 2
        draw.ellipse([px-hr, py-hr, px+hr, py+hr], fill=(255,100,150))
    draw.ellipse([cx-r//3, cy-r//3, cx+r//3, cy+r//3], fill=(255,220,230))

img = Image.new("RGB", (W, H))
d = ImageDraw.Draw(img)
gradient(d, W, H, (255, 200, 220), (220, 180, 255))
for cx, cy, sz in [(75,75,52),(W-75,75,52),(75,H-75,52),(W-75,H-75,52),(W//2,38,32),(W//2,H-38,32)]:
    petals(d, cx, cy, sz)
img = overlay(img, (255, 255, 255, 110))
d = ImageDraw.Draw(img)
centered(d, W, H//2-60, "С 8 Марта!", font(72),
         shadow=(150,30,100,160), fill=(200,0,100,255))
centered(d, W, H//2+22, "🌸  🌷  🌸", font(28), fill=(180,0,80,255))
path = os.path.join(OUT_DIR, "march8.jpg")
img.save(path, "JPEG", quality=92)
print(f"✅  march8.jpg    →  {path}")

# ── universal ────────────────────────────────────────────────────────────────
img = Image.new("RGB", (W, H))
d = ImageDraw.Draw(img)
gradient(d, W, H, (180, 225, 255), (140, 255, 200))
rng = random.Random(99)
for i in range(55):
    cx, cy = rng.randint(0, W), rng.randint(0, H)
    r = rng.randint(3, 14)
    col = rng.choice([(255,220,0),(255,180,50),(200,255,100),(100,200,255)])
    for a in range(0, 360, 45):
        rad = math.radians(a)
        er = r if a % 90 == 0 else max(r//3, 2)
        px, py = cx + er*math.cos(rad), cy + er*math.sin(rad)
        d.ellipse([px-2, py-2, px+2, py+2], fill=col)
img = overlay(img, (0, 30, 80, 95))
d = ImageDraw.Draw(img)
centered(d, W, H//2-58, "Поздравляю!", font(74),
         shadow=(0,50,120,180), fill=(255,255,255,255))
centered(d, W, H//2+22, "🎉  🎊  🎉", font(28), fill=(255,240,100,255))
path = os.path.join(OUT_DIR, "universal.jpg")
img.save(path, "JPEG", quality=92)
print(f"✅  universal.jpg  →  {path}")

print("\nGot the images? Now:")
print("  1. Send each JPG to @RawDataBot (or forward to your bot)")
print("  2. Copy file_id from the Telegram response")
print("  3. Paste into TEMPLATE_POSTCARDS in bot/config.py")
