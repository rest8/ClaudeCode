"""アプリのアイコン（assets/icon.png, icon.ico）を作るスクリプト。 pip install pillow で実行."""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 512
OUT = Path(__file__).resolve().parent.parent / "assets"


def draw() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((16, 16, SIZE - 16, SIZE - 16), radius=96, fill=(28, 92, 196, 255))
    # 封筒
    left, top, right, bottom = 96, 150, SIZE - 96, SIZE - 130
    d.rounded_rectangle((left, top, right, bottom), radius=24, fill=(255, 255, 255, 255))
    mid = (left + right) // 2
    d.line([(left + 10, top + 14), (mid, top + 150), (right - 10, top + 14)], fill=(28, 92, 196, 255), width=26,
           joint="curve")
    # 送信を表す緑の矢印バッジ
    cx, cy, r = SIZE - 128, SIZE - 128, 84
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(34, 170, 90, 255), outline=(255, 255, 255, 255), width=14)
    d.polygon([(cx - 34, cy - 40), (cx + 44, cy), (cx - 34, cy + 40), (cx - 16, cy)], fill=(255, 255, 255, 255))
    return img


def main() -> None:
    OUT.mkdir(exist_ok=True)
    img = draw()
    img.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    img.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("saved:", OUT / "icon.png", OUT / "icon.ico")


if __name__ == "__main__":
    main()
