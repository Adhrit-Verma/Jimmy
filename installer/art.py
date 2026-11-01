"""Jimmy's mark, drawn (D62): the app icon and the installer's images.

The mark is Jimmy's own pill (the overlay's top-centre pill) with its listening bars, the
equalizer it shows while it hears you, in the overlay's sky accent on its near-black
surface. The same geometry lives in overlay/src/Logo.jsx (animated); this draws the
static pictures Windows and NSIS need:

  overlay/build/icon.ico                       16-256 px, the app and the installer
  overlay/build/installerSidebar.bmp           164x314, the setup's welcome and finish pages
  overlay/build/uninstallerSidebar.bmp         the same, for the uninstaller
  overlay/build/installerHeader.bmp            150x57, the setup's inner pages
  docs/img/jimmy-mark.png                      512 px, for the README
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "overlay" / "build"
INK = (10, 10, 10)                 # neutral-950, the overlay's surface
RING = (38, 38, 38)                # white/10 on it
SKY_TOP, SKY_BOT = (125, 211, 252), (14, 165, 233)   # sky-300 -> sky-500
BARS = (0.38, 0.72, 1.0, 0.62, 0.42)                 # the listening bars, left to right
TEXT, MUTED = (245, 245, 245), (163, 163, 163)


def _gradient(size: tuple[int, int], top, bottom) -> Image.Image:
    w, h = size
    g = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        g.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return g.resize((w, h))


def mark(size: int, background: bool = True) -> Image.Image:
    """The mark on a transparent (or rounded-square, dark) canvas, drawn 4x then reduced."""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if background:
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=INK + (255,))
        glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((s * .18, s * .30, s * .82, s * .74), fill=SKY_BOT + (70,))
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(s * 0.09)))
        d = ImageDraw.Draw(img)
    # the pill
    pw, ph = s * (0.74 if size > 24 else 0.86), s * (0.38 if size > 24 else 0.5)
    x0, y0 = (s - pw) / 2, (s - ph) / 2
    d.rounded_rectangle((x0, y0, x0 + pw, y0 + ph), radius=ph / 2, fill=(23, 23, 23, 255),
                        outline=RING + (255,), width=max(2, int(s * 0.012)))
    # the listening bars, sky gradient, rounded ends
    n, inner = len(BARS), ph * 0.64
    bw = pw * (0.075 if size > 24 else 0.1)
    gap = (pw * 0.62 - n * bw) / (n - 1)
    left = (s - (n * bw + (n - 1) * gap)) / 2
    sky = _gradient((int(bw) + 1, int(inner) + 1), SKY_TOP, SKY_BOT).convert("RGBA")
    for i, k in enumerate(BARS):
        bh = max(bw, inner * k)
        bx, by = left + i * (bw + gap), s / 2 - bh / 2
        m = Image.new("L", (int(bw) + 1, int(inner) + 1), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, (inner - bh) / 2, bw, (inner + bh) / 2), radius=bw / 2, fill=255)
        img.paste(sky, (int(bx), int(s / 2 - inner / 2)), m)
    return img.resize((size, size), Image.LANCZOS)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    fonts = Path(r"C:\Windows\Fonts")
    for name in (["segoeuib.ttf", "SegUIVar.ttf"] if bold else ["segoeui.ttf", "SegUIVar.ttf"]):
        try:
            f = ImageFont.truetype(str(fonts / name), size)
            if bold and name == "SegUIVar.ttf":
                try:
                    f.set_variation_by_name("Semibold")
                except Exception:
                    pass
            return f
        except OSError:
            continue
    return ImageFont.load_default()


def sidebar() -> Image.Image:
    """NSIS welcome/finish art, 164x314: the mark, the name, one line."""
    w, h = 164, 314
    img = _gradient((w, h), (18, 18, 18), (6, 6, 6)).convert("RGBA")
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-30, 40, w + 30, 190), fill=SKY_BOT + (55,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(28)))
    m = mark(104, background=False)
    img.alpha_composite(m, ((w - 104) // 2, 58))
    d = ImageDraw.Draw(img)
    for text, y, f, c in (("Jimmy", 176, _font(30, True), TEXT), ("the assistant that", 220, _font(13), MUTED),
                          ("knows when to", 237, _font(13), MUTED), ("stay quiet", 254, _font(13), SKY_TOP)):
        tw = d.textlength(text, font=f)
        d.text(((w - tw) / 2, y), text, font=f, fill=c)
    return img.convert("RGB")


def header() -> Image.Image:
    """NSIS inner-page art, 150x57 (sits top right on a white header)."""
    w, h = 150, 57
    img = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    pill = mark(44, background=True)
    img.alpha_composite(pill, (w - 50, 6))
    d = ImageDraw.Draw(img)
    f = _font(20, True)
    d.text((w - 56 - d.textlength("Jimmy", font=f), 15), "Jimmy", font=f, fill=(23, 23, 23))
    return img.convert("RGB")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big = mark(256)
    big.save(OUT / "icon.ico", sizes=[(s, s) for s in sizes],
             append_images=[mark(s) for s in sizes[:-1]])
    big.save(OUT / "icon.png")
    side = sidebar()
    side.save(OUT / "installerSidebar.bmp")
    side.save(OUT / "uninstallerSidebar.bmp")
    header().save(OUT / "installerHeader.bmp")
    (ROOT / "docs" / "img").mkdir(parents=True, exist_ok=True)
    mark(512).save(ROOT / "docs" / "img" / "jimmy-mark.png")
    print("art:", ", ".join(p.name for p in sorted(OUT.iterdir())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
