import math

from PIL import Image, ImageDraw, ImageFilter

SIZE = 512
BG_CENTER = (24, 27, 36)
BG_EDGE = (14, 16, 22)
ACCENT = (51, 140, 242)
ACCENT_BRIGHT = (77, 163, 255)
OK = (51, 191, 115)


def radial_bg():
    img = Image.new("RGB", (SIZE, SIZE))
    px = img.load()
    cx, cy = SIZE / 2, SIZE / 2
    maxd = math.hypot(cx, cy)
    for y in range(SIZE):
        for x in range(SIZE):
            d = min(math.hypot(x - cx, y - cy) / maxd, 1)
            r = int(BG_CENTER[0] + (BG_EDGE[0] - BG_CENTER[0]) * d)
            g = int(BG_CENTER[1] + (BG_EDGE[1] - BG_CENTER[1]) * d)
            b = int(BG_CENTER[2] + (BG_EDGE[2] - BG_CENTER[2]) * d)
            px[x, y] = (r, g, b)
    return img


def rounded_mask(radius):
    mask = Image.new("L", (SIZE, SIZE), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=radius, fill=255)
    return mask


def shield_signal(img):
    d = ImageDraw.Draw(img, "RGBA")
    cx, cy = SIZE / 2, SIZE / 2 + 15

    # shield outline (protection / proxy)
    w, h = 170, 210
    shield = [
        (cx, cy - h / 2),
        (cx + w / 2, cy - h / 2 + 40),
        (cx + w / 2, cy + h / 2 - 60),
        (cx, cy + h / 2),
        (cx - w / 2, cy + h / 2 - 60),
        (cx - w / 2, cy - h / 2 + 40),
    ]
    d.polygon(shield, fill=ACCENT + (255,))
    d.line(shield + [shield[0]], fill=ACCENT_BRIGHT + (255,), width=8, joint="curve")

    # signal arcs inside shield
    for radius, width, alpha in [(46, 10, 255), (74, 9, 170)]:
        bbox = [cx - radius, cy + 10 - radius, cx + radius, cy + 10 + radius]
        d.arc(bbox, start=210, end=330, fill=(255, 255, 255, alpha), width=width)

    node_r = 16
    d.ellipse([cx - node_r, cy + 10 - node_r, cx + node_r, cy + 10 + node_r], fill=(255, 255, 255, 255))

    # verified check dot, lower-right
    ax, ay = cx + 95, cy + 90
    ar = 34
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([ax - ar * 1.8, ay - ar * 1.8, ax + ar * 1.8, ay + ar * 1.8], fill=OK + (110,))
    glow = glow.filter(ImageFilter.GaussianBlur(14))
    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    d.ellipse([ax - ar, ay - ar, ax + ar, ay + ar], fill=OK + (255,))
    d.ellipse([ax - ar, ay - ar, ax + ar, ay + ar], outline=BG_EDGE + (255,), width=6)
    check = [(ax - 15, ay + 1), (ax - 4, ay + 13), (ax + 17, ay - 12)]
    d.line(check, fill=(255, 255, 255, 255), width=7, joint="curve")


def build():
    img = radial_bg()
    shield_signal(img)
    img = img.filter(ImageFilter.SMOOTH_MORE)
    img.save("icon.png", "PNG")

    rounded = img.convert("RGBA")
    rounded.putalpha(rounded_mask(110))
    rounded.save("icon_round.png", "PNG")


if __name__ == "__main__":
    build()
    print("done")
