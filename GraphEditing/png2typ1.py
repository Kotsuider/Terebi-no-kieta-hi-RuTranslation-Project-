#!/usr/bin/env python3
"""
PNG/BMP → TYP1 (.cpb) конвертер для AZSystem движка (старый arc формат).

Формат TYP1 (24-bit, из AZSystem.cpp):
  struct cpb_header_t {
      char  magic[4];       // "TYP1"
      u8    color_depth;    // 24 или 32
      u8    flag;           // 0 = без палитры
      u16   width;
      u16   height;
      i32   max_comprlen;
      u32   comprlen[4];    // B,R,G,A (порядок хранения)
  };  // 30 байт
  Данные: каналы в порядке A,B,G,R (для 24bit: B,G,R) = i=pixel_bytes-1..0
  Каждый канал: [ewf_crc(4 байта LE)][zlib compressed plane]
  Пиксели top-to-bottom, DIB сборка bottom-up (Y-flip при чтении).

Канальный маппинг для 24-bit (нет альфа):
  comprlen[2] -> i=2 -> канал B (синий)
  comprlen[1] -> i=1 -> канал G (зелёный)
  comprlen[0] -> i=0 -> канал R (красный)

Использование:
  python png2typ1.py input.png output.cpb
  python png2typ1.py input.png output.cpb --depth 32   # с альфа-каналом
  python png2typ1.py input.bmp output.cpb
"""

import sys
import struct
import zlib
import argparse
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("ERROR: pip install Pillow")
    sys.exit(1)


def ewf_crc(data: bytes, init: int = 1) -> int:
    """Правильная реализация ewf_crc из AZSystem."""
    b = init & 0xffff
    d = (init >> 16) & 0xffff
    n = len(data)
    for i in range(n):
        b = (b + data[i]) & 0xffffffff
        d = (d + b) & 0xffffffff
        if i != 0 and ((i % 0x15b0 == 0) or (i == n - 1)):
            b = b % 0xfff1
            d = d % 0xfff1
    return ((d << 16) | b) & 0xffffffff


def compress_plane(plane: bytes) -> bytes:
    """Сжимает один канал: [ewf_crc(4)][zlib data]."""
    zdata = zlib.compress(plane, level=9)
    crc = ewf_crc(zdata)
    return struct.pack("<I", crc) + zdata


def png_to_typ1(input_path: str, output_path: str, force_depth: int = None):
    img = Image.open(input_path)

    has_alpha = img.mode in ("RGBA", "LA", "PA") or \
                (img.mode == "P" and "transparency" in img.info)

    if force_depth == 24:
        has_alpha = False
    elif force_depth == 32:
        has_alpha = True

    if has_alpha:
        img = img.convert("RGBA")
        color_depth = 32
    else:
        img = img.convert("RGB")
        color_depth = 24

    width, height = img.size
    pixel_bytes = color_depth // 8
    plane_size = width * height

    print(f"Изображение: {width}x{height}, {color_depth}-bit")

    # Разделяем на каналы (PIL даёт top-to-bottom, TYP1 тоже хранит top-to-bottom)
    pixels = img.tobytes()  # interleaved RGB(A)

    # Собираем planes top-to-bottom (движок при чтении делает Y-flip сам)
    # channels: для RGB -> R=0, G=1, B=2
    # planes_by_channel[ch] = bytes размером width*height
    planes_by_channel = [bytearray(plane_size) for _ in range(pixel_bytes)]
    for i, byte in enumerate(pixels):
        ch = i % pixel_bytes
        px = i // pixel_bytes
        planes_by_channel[ch][px] = byte

    # R=ch0, G=ch1, B=ch2, A=ch3(если есть)
    R = bytes(planes_by_channel[0])
    G = bytes(planes_by_channel[1])
    B = bytes(planes_by_channel[2])
    A = bytes(planes_by_channel[3]) if pixel_bytes == 4 else None

    # Порядок сжатия в TYP1: i = pixel_bytes-1 .. 0
    # i=2 -> B, i=1 -> G, i=0 -> R  (для 24bit)
    # i=3 -> A, i=2 -> B, i=1 -> G, i=0 -> R  (для 32bit)
    # comprlen[i] хранит длину для канала i
    comprlen = [0, 0, 0, 0]
    compressed_channels = {}  # i -> bytes

    if color_depth == 24:
        channel_map = {2: B, 1: G, 0: R}
    else:  # 32
        channel_map = {3: A, 2: B, 1: G, 0: R}

    for i, plane in channel_map.items():
        c = compress_plane(plane)
        compressed_channels[i] = c
        comprlen[i] = len(c)

    max_comprlen = max(comprlen)

    # Собираем заголовок TYP1 (30 байт)
    header = struct.pack("<4sBBHHiIIII",
        b"TYP1",
        color_depth,
        0,           # flag = 0 (без палитры)
        width,
        height,
        max_comprlen,
        comprlen[0], comprlen[1], comprlen[2], comprlen[3]
    )
    assert len(header) == 30, f"Header size = {len(header)}"

    # Данные: каналы в порядке i = pixel_bytes-1 .. 0
    with open(output_path, "wb") as f:
        f.write(header)
        for i in range(pixel_bytes - 1, -1, -1):
            if i in compressed_channels:
                f.write(compressed_channels[i])

    total = Path(output_path).stat().st_size
    print(f"Записано: {output_path}  ({total:,} байт)")
    print(f"  comprlen: B={comprlen[2]}, G={comprlen[1]}, R={comprlen[0]}"
          + (f", A={comprlen[3]}" if color_depth == 32 else ""))


def main():
    ap = argparse.ArgumentParser(description="PNG/BMP → TYP1 CPB конвертер (AZSystem)")
    ap.add_argument("input", help="Входной PNG или BMP файл")
    ap.add_argument("output", help="Выходной CPB файл")
    ap.add_argument("--depth", type=int, choices=[24, 32],
                    help="Глубина цвета (по умолчанию: авто из PNG)")
    args = ap.parse_args()

    if not Path(args.input).exists():
        print(f"ERROR: {args.input} не найден")
        sys.exit(1)

    png_to_typ1(args.input, args.output, force_depth=args.depth)


if __name__ == "__main__":
    main()