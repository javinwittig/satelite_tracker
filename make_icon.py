from PIL import Image, ImageDraw

S = 1024


def make_icon():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.ellipse((0, 0, S - 1, S - 1), fill=(30, 39, 46, 255))

    c, r = S // 2, 230
    d.ellipse((c - r, c - r, c + r, c + r), fill=(41, 128, 185, 255))

    ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.ellipse((90, 340, S - 90, S - 340), outline=(236, 240, 241, 255), width=34)
    ring = ring.rotate(25, resample=Image.BICUBIC)
    img.alpha_composite(ring)

    planet = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(planet).ellipse((c - r, c - r, c + r, c + r), fill=(41, 128, 185, 255))
    upper = Image.new("L", (S, S), 0)
    ImageDraw.Draw(upper).rectangle((0, 0, S, c), fill=255)
    upper = upper.rotate(25, resample=Image.BICUBIC)
    planet.putalpha(Image.composite(planet.getchannel("A"), upper, upper))
    img.alpha_composite(planet)

    sx, sy, sr = 790, 330, 62
    d = ImageDraw.Draw(img)
    d.ellipse((sx - sr, sy - sr, sx + sr, sy + sr), fill=(241, 196, 15, 255))

    return img


if __name__ == "__main__":
    icon = make_icon()
    icon.resize((256, 256), Image.LANCZOS).save("icon.png")
    icon.save("icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon.png and icon.ico created")
