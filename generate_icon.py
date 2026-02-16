#!/usr/bin/env python3
"""market_dashboard.svg から market_dashboard.ico を生成するスクリプト"""
import struct
import os

def create_simple_ico(path, size=32):
    """シンプルなチャートアイコンをICO形式で生成する"""
    pixels = []
    for y in range(size):
        row = []
        for x in range(size):
            # 背景: #1a1a2e
            r, g, b, a = 0x1a, 0x1a, 0x2e, 255

            # 枠線 (外周2px): #00d4aa
            if x < 2 or x >= size - 2 or y < 2 or y >= size - 2:
                r, g, b = 0x00, 0xd4, 0xaa

            # バー (内側エリア)
            elif 4 <= x <= 28 and y >= 8:
                bar_x = x - 4
                # 4本のバー
                bars = [
                    (1, 3, 20, 0x00, 0xe6, 0x76),   # bar1: green
                    (7, 9, 14, 0x00, 0xd4, 0xaa),    # bar2: teal
                    (13, 15, 8, 0xff, 0x9f, 0x1c),   # bar3: orange
                    (19, 21, 12, 0x00, 0xe6, 0x76),  # bar4: green
                ]
                for bx1, bx2, top, br, bg, bb in bars:
                    if bx1 <= bar_x <= bx2 and y >= top + 8:
                        r, g, b = br, bg, bb

            row.append((b, g, r, a))  # ICO uses BGRA
        pixels.append(row)

    # BMP data (BGRA, bottom-up)
    bmp_data = b""
    for row in reversed(pixels):
        for b, g, r, a in row:
            bmp_data += struct.pack("BBBB", b, g, r, a)

    # AND mask (1bpp, all opaque)
    and_mask = b"\x00" * (((size + 31) // 32) * 4 * size)

    # BITMAPINFOHEADER
    bih = struct.pack("<IiiHHIIiiII",
        40,          # biSize
        size,        # biWidth
        size * 2,    # biHeight (double for ICO)
        1,           # biPlanes
        32,          # biBitCount
        0,           # biCompression
        len(bmp_data) + len(and_mask),
        0, 0, 0, 0
    )

    image_data = bih + bmp_data + and_mask

    # ICO header
    ico_header = struct.pack("<HHH", 0, 1, 1)  # reserved, type=ICO, count=1

    # ICO directory entry
    ico_entry = struct.pack("<BBBBHHII",
        size if size < 256 else 0,
        size if size < 256 else 0,
        0,    # color palette
        0,    # reserved
        1,    # color planes
        32,   # bits per pixel
        len(image_data),
        6 + 16  # offset (header=6 + entry=16)
    )

    with open(path, "wb") as f:
        f.write(ico_header + ico_entry + image_data)

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_dashboard.ico")
    create_simple_ico(out, 32)
    print(f"アイコンを生成しました: {out}")
