"""BiWQA icon artwork — pure Pillow, drawn at 2048 px and downsampled.

Variant D (transparent split teardrop) is shipped as icon.png;
variant A (navy tile) is assets/biwqa_logo.png.
"""
import math, os
from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.dirname(os.path.abspath(__file__))
S = 2048          # supersample canvas
FINAL = [512, 128, 64, 48, 24]

NAVY   = (11, 37, 69, 255)
BLUE_D = (0, 40, 128, 255)
BLUE   = (23, 118, 210, 255)
CYAN   = (0, 200, 220, 255)
GREEN  = (60, 190, 80, 255)
YELLOW = (250, 210, 40, 255)
ORANGE = (255, 140, 30, 255)
WHITE  = (255, 255, 255, 255)


def lerp(c1, c2, t):
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))


def ramp(stops, t):
    """stops: list of (pos, color)."""
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        if p0 <= t <= p1:
            return lerp(c0, c1, (t - p0) / (p1 - p0))
    return stops[-1][1]


def vgrad(size, stops, horizontal=False):
    img = Image.new("RGBA", (size, size))
    d = ImageDraw.Draw(img)
    for i in range(size):
        c = ramp(stops, i / (size - 1))
        if horizontal:
            d.line([(i, 0), (i, size)], fill=c)
        else:
            d.line([(0, i), (size, i)], fill=c)
    return img


def drop_polygon(cx, cy, r, apex_y):
    """Teardrop outline: circle (cx,cy,r) + apex at (cx, apex_y)."""
    d = cy - apex_y
    a = math.acos(min(0.999, r / d))
    pts = [(cx, apex_y)]
    # right tangent point -> around the circle -> left tangent point
    n = 240
    start = -math.pi / 2 + a          # angle measured from +x axis
    end = -math.pi / 2 - a + 2 * math.pi
    for i in range(n + 1):
        th = start + (end - start) * i / n
        pts.append((cx + r * math.cos(th), cy + r * math.sin(th)))
    return pts


def tile(size, color=NAVY, radius_frac=0.22):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * radius_frac), fill=color)
    return img


def save(img, name):
    for px in FINAL:
        out = img.resize((px, px), Image.LANCZOS)
        out.save(os.path.join(OUT, f"{name}_{px}.png"))
    return os.path.join(OUT, f"{name}_512.png")


# ---------------------------------------------------------------- variant A
# Navy tile, teardrop split down the middle: clear blue (T1) | eutrophic (T2)
def variant_a():
    img = tile(S)
    d = ImageDraw.Draw(img)

    cx, cy, r = S * 0.5, S * 0.60, S * 0.275
    apex = S * 0.155
    poly = drop_polygon(cx, cy, r, apex)

    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).polygon(poly, fill=255)

    left = vgrad(S, [(0.0, CYAN), (0.55, BLUE), (1.0, BLUE_D)])
    right = vgrad(S, [(0.0, YELLOW), (0.5, GREEN), (1.0, (20, 120, 60, 255))])
    split = Image.new("RGBA", (S, S))
    split.paste(left, (0, 0))
    split.paste(right.crop((int(cx), 0, S, S)), (int(cx), 0))

    img.paste(split, (0, 0), mask)

    # divider + highlight
    d.line([(cx, apex + S * 0.02), (cx, cy + r * 0.98)], fill=(255, 255, 255, 235), width=int(S * 0.016))
    return img


# ---------------------------------------------------------------- variant B
# Transparent glyph: teardrop with Chl-a ramp, white change arrow across it
def variant_b():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cx, cy, r = S * 0.5, S * 0.605, S * 0.30
    apex = S * 0.115
    poly = drop_polygon(cx, cy, r, apex)

    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).polygon(poly, fill=255)

    fill = vgrad(S, [(0.10, BLUE_D), (0.35, BLUE), (0.55, CYAN),
                     (0.72, GREEN), (0.88, YELLOW), (1.0, ORANGE)])
    img.paste(fill, (0, 0), mask)

    # dark outline
    ImageDraw.Draw(img).line(poly + [poly[0]], fill=(8, 30, 55, 255),
                             width=int(S * 0.030), joint="curve")

    # change arrow (T1 -> T2) across the belly
    d = ImageDraw.Draw(img)
    y = cy + r * 0.10
    x0, x1 = cx - r * 0.66, cx + r * 0.52
    w = int(S * 0.045)
    d.line([(x0, y), (x1, y)], fill=WHITE, width=w)
    head = r * 0.30
    d.polygon([(x1 + head * 0.55, y), (x1 - head * 0.15, y - head * 0.52),
               (x1 - head * 0.15, y + head * 0.52)], fill=WHITE)
    return img


# ---------------------------------------------------------------- variant C
# Tile with two stacked lake bands (Time 1 / Time 2) + change arrow
def variant_c():
    img = tile(S, color=(9, 32, 60, 255))
    d = ImageDraw.Draw(img)

    m = S * 0.135
    gap = S * 0.045
    band_h = (S - 2 * m - gap) / 2
    rad = int(S * 0.055)

    def band(y0, stops):
        strip = vgrad(S, stops, horizontal=True)
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle([m, y0, S - m, y0 + band_h], radius=rad, fill=255)
        img.paste(strip, (0, 0), mask)

    # Time 1 — oligotrophic / clear
    band(m, [(0.0, (10, 60, 150, 255)), (0.45, BLUE), (1.0, CYAN)])
    # Time 2 — eutrophic
    band(m + band_h + gap, [(0.0, CYAN), (0.35, GREEN), (0.75, YELLOW), (1.0, ORANGE)])

    # wave line inside each band
    for k, y0 in enumerate([m, m + band_h + gap]):
        yc = y0 + band_h * 0.62
        amp = band_h * (0.13 + 0.06 * k)
        pts = []
        for i in range(200):
            x = m + (S - 2 * m) * i / 199
            pts.append((x, yc + amp * math.sin(i / 199 * math.pi * 3 + k * 1.2)))
        d.line(pts, fill=(255, 255, 255, 120), width=int(S * 0.014), joint="curve")

    # downward change arrow between the bands
    ax = S * 0.5
    y_top = m + band_h + gap * 0.10
    y_bot = m + band_h + gap * 0.90
    d.polygon([(ax - gap * 0.62, y_top), (ax + gap * 0.62, y_top), (ax, y_bot + gap * 0.15)],
              fill=(255, 255, 255, 240))
    return img


def variant_d():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cx, cy, r = S * 0.5, S * 0.605, S * 0.30
    apex = S * 0.115
    poly = drop_polygon(cx, cy, r, apex)

    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).polygon(poly, fill=255)

    left = vgrad(S, [(0.0, CYAN), (0.55, BLUE), (1.0, BLUE_D)])
    right = vgrad(S, [(0.0, YELLOW), (0.5, GREEN), (1.0, (20, 120, 60, 255))])
    split = Image.new("RGBA", (S, S))
    split.paste(left, (0, 0))
    split.paste(right.crop((int(cx), 0, S, S)), (int(cx), 0))
    img.paste(split, (0, 0), mask)

    d = ImageDraw.Draw(img)
    d.line(poly + [poly[0]], fill=(8, 30, 55, 255), width=int(S * 0.030), joint="curve")
    d.line([(cx, apex + S * 0.03), (cx, cy + r * 0.97)], fill=(255, 255, 255, 240),
           width=int(S * 0.022))
    return img


for name, fn in [("icon_a", variant_a), ("icon_b", variant_b), ("icon_c", variant_c), ("icon_d", variant_d)]:
    print(save(fn(), name))

# contact sheet: each variant at 512 / 64 / 24 on light and dark backgrounds
sheet = Image.new("RGBA", (2270, 1300), (255, 255, 255, 255))
sd = ImageDraw.Draw(sheet)
sd.rectangle([0, 650, 2270, 1300], fill=(40, 44, 52, 255))
for col, name in enumerate(["icon_a", "icon_b", "icon_c", "icon_d"]):
    x = 60 + col * 550
    big = Image.open(os.path.join(OUT, f"{name}_512.png"))
    for row, bg_y in enumerate([40, 690]):
        sheet.paste(big.resize((380, 380), Image.LANCZOS), (x, bg_y), big.resize((380, 380), Image.LANCZOS))
        for i, px in enumerate([128, 64, 48, 24]):
            small = Image.open(os.path.join(OUT, f"{name}_{px}.png"))
            sheet.paste(small, (x + i * 140, bg_y + 430), small)
sheet.convert("RGB").save(os.path.join(OUT, "icon_sheet.png"))
print(os.path.join(OUT, "icon_sheet.png"))
