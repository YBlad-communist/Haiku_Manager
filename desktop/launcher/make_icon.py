"""Рисует иконку приложения в стиле claymorphism."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)

SIZE = 1024
canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
shadow_draw = ImageDraw.Draw(shadow)
shadow_draw.rounded_rectangle(
    (64, 88, 960, 984), radius=230, fill=(91, 75, 214, 80)
)
shadow = shadow.filter(ImageFilter.GaussianBlur(26))
canvas.alpha_composite(shadow)

mask = Image.new("L", (SIZE, SIZE), 0)
ImageDraw.Draw(mask).rounded_rectangle((52, 52, 972, 972), radius=224, fill=255)

gradient = Image.new("RGBA", (SIZE, SIZE))
draw = ImageDraw.Draw(gradient)
for y in range(SIZE):
    t = y / (SIZE - 1)
    top = (247, 244, 255)
    bottom = (214, 206, 242)
    color = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    draw.line((0, y, SIZE, y), fill=color + (255,))

base = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
base.paste(gradient, (0, 0), mask)

highlight = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
highlight_draw = ImageDraw.Draw(highlight)
highlight_draw.rounded_rectangle(
    (92, 84, 932, 900), radius=190, fill=(255, 255, 255, 90)
)
highlight = highlight.filter(ImageFilter.GaussianBlur(26))
base.alpha_composite(highlight)
canvas.alpha_composite(base)

font_path = Path("C:/Windows/Fonts/segoeuib.ttf")
font = ImageFont.truetype(str(font_path), 620)
letter = "Ω"
left, top, right, bottom = font.getbbox(letter)
letter_width = right - left
letter_height = bottom - top
position = (
    (SIZE - letter_width) // 2 - left,
    (SIZE - letter_height) // 2 - top - 12,
)

letter_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
letter_draw = ImageDraw.Draw(letter_layer)
letter_draw.text(position, letter, font=font, fill=(91, 75, 214, 255))
letter_shadow = letter_layer.filter(ImageFilter.GaussianBlur(14))
letter_shadow.putalpha(letter_shadow.getchannel("A").point(lambda a: a * 0.28))
canvas.alpha_composite(letter_shadow, (0, 10))
canvas.alpha_composite(letter_layer)

dot = ImageDraw.Draw(canvas)
dot.ellipse((730, 708, 872, 850), fill=(255, 217, 194, 255))
dot.ellipse((756, 732, 846, 822), fill=(194, 86, 31, 255))

icon = canvas.resize((256, 256), Image.LANCZOS)
icon.save(ASSETS / "icon.png")
icon.save(
    ASSETS / "icon.ico",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
for size in (16, 32):
    icon.resize((size, size), Image.LANCZOS).save(ASSETS / f"tray-{size}.png")
print(ASSETS / "icon.ico")
