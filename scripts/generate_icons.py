"""Generate PWA and app icons for all platforms."""
import os
from PIL import Image, ImageDraw, ImageFont

SIZES = {
    "icon-72.png": 72,
    "icon-96.png": 96,
    "icon-128.png": 128,
    "icon-144.png": 144,
    "icon-152.png": 152,
    "icon-192.png": 192,
    "icon-384.png": 384,
    "icon-512.png": 512,
    "apple-touch-icon.png": 180,
    "favicon-32.png": 32,
    "favicon-16.png": 16,
}

FONT_PATHS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
]


def get_font(size):
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def generate_icon(size, output_path):
    img = Image.new("RGBA", (size, size), (10, 10, 10, 255))
    draw = ImageDraw.Draw(img)

    pad = max(4, size // 8)
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=size // 5,
        fill=(212, 160, 23, 255),
    )

    text = "S"
    font_size = int(size * 0.48)
    font = get_font(font_size)

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) // 2 - bbox[0]
    y = (size - text_h) // 2 - bbox[1]
    draw.text((x, y), text, fill=(10, 10, 10, 255), font=font)

    img.save(output_path, "PNG")


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "..", "static", "icons")
    os.makedirs(out_dir, exist_ok=True)

    for filename, size in SIZES.items():
        path = os.path.join(out_dir, filename)
        generate_icon(size, path)
        print(f"  Generated {filename} ({size}x{size})")

    print(f"Icons written to {out_dir}")


if __name__ == "__main__":
    main()
