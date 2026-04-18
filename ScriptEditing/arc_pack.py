#!/usr/bin/env python3
"""
AZSystem .arc packer (старый формат, SFMT132049-шифрование)
Обратный к распаковщику из AZSystem.cpp (crass/crage).

Использование:
    python arc_pack.py <папка_с_файлами> <выходной.arc> [system.arc] [original.arc]

Если system.arc не указан — будет использован тот же ключ, что использовался
при шифровании заголовка (ini[0]), без дополнительного ключа из sysenv.tbl.
Это работает для старого (old_arc=1) варианта.

Для нового варианта (с sysenv.tbl и SFMT132049) — укажи system.arc третьим аргументом.

Пример:
    python arc_pack.py "E:/テレビの消えた日_extracted" output.arc "E:/テレビの消えた日/system.arc"
"""

import os
import sys
import struct
import zlib
import ctypes
from pathlib import Path


# ---------------------------------------------------------------------------
# Константы из AZSystem.cpp
# ---------------------------------------------------------------------------

# Таблица ini-ключей (MAX_INI=4, каждый — 4 u32)
INI_TABLE = [
    (0x2f4d7dfe, 0x47345292, 0x1ba5fe82, 0x7bc04525),
    (0xff2c9171, 0x4a676214, 0xb8c62e81, 0x504ab64a),
    (0x7f7f85c1, 0x49a60caa, 0x97daf182, 0xb86a1a05),
    (0x76c9a719, 0x46e848d2, 0xb43713bf, 0x33770358),
]

ARC_HEADER_SIZE = 4 + 4 + 4 + 4 + 32   # magic(4)+suffix_number(4)+index_entries(4)+compr_index_length(4)+suffix(32) = 48
ARC_ENTRY_SIZE  = 4 + 4 + 4 + 4 + 32   # offset+length+name_crc+always_zero+name = 48


# ---------------------------------------------------------------------------
# EWF CRC (из ewf_crc.cpp)
# ---------------------------------------------------------------------------

def ewf_crc(data: bytes, previous_key: int = 1) -> int:
    b = previous_key & 0xffff
    d = (previous_key >> 16) & 0xffff
    buf = data
    n = len(buf)
    for i in range(n):
        b = (b + buf[i]) & 0xffffffff
        d = (d + b) & 0xffffffff
        if i != 0 and ((i % 0x15b0 == 0) or (i == n - 1)):
            b = b % 0xfff1
            d = d % 0xfff1
    return ((d << 16) | b) & 0xffffffff


# ---------------------------------------------------------------------------
# gen_key из AZSystem.cpp
# ---------------------------------------------------------------------------

def gen_key(key: tuple) -> int:
    """
    u32 gen_key(u32 *key, unsigned int key_len)
    key — кортеж из 4 u32, key_len = 16 байт
    """
    raw = struct.pack('<4I', *key)
    k0, k1, k2, k3 = key

    def crc32v(seed, data):
        # zlib.crc32 возвращает знаковое в Python 2, беззнаковое в Python 3
        return zlib.crc32(data, seed) & 0xffffffff

    _key  = crc32v(k1 & 0xffff,  raw)
    _key ^= crc32v(k1 >> 16,     raw)
    _key ^= crc32v(k0,           raw)
    _key ^= crc32v(k2,           raw)
    _key ^= crc32v(k3,           raw)
    _key ^= k0
    return _key & 0xffffffff


# ---------------------------------------------------------------------------
# decode / encode (XOR-симметричная, т.е. encode == decode)
# ---------------------------------------------------------------------------

def _make_hi_lo(key: int, shift: int):
    """Вычисляет начальные lo/hi как в decode() из AZSystem.cpp"""
    # hash = (u64)key * 0x9E370001
    h = (key * 0x9E370001) & 0xffffffffffffffff
    hi = (h >> 32) & 0xffffffff
    lo =  h        & 0xffffffff
    if shift & 0x20:
        lo, hi = hi, lo
    shift &= 31
    if shift:
        new_lo = ((lo << shift) | (hi >> (32 - shift))) & 0xffffffff
        new_hi = ((hi << shift) | (lo >> (32 - shift))) & 0xffffffff
        lo, hi = new_lo, new_hi
    return lo, hi


def xor_stream(data: bytearray, offset: int, key: int):
    """
    Применяет XOR-поток из decode() к bytearray на месте.
    offset — позиция в файле (используется как shift).
    Функция симметричная: encode == decode.
    """
    lo, hi = _make_hi_lo(key, offset)
    for i in range(len(data)):
        data[i] ^= (lo & 0xff)
        cf = 1 if (lo & 0x80000000) else 0
        lo = ((lo << 1) | (hi >> 31)) & 0xffffffff
        hi = ((hi << 1) | cf)         & 0xffffffff


# ---------------------------------------------------------------------------
# Минимальная реализация SFMT-19937 для gen_code_buffer (new_arc)
# (нам она не нужна для старого формата, но оставлена для полноты)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Чтение ключа из system.arc (функция azsystem_find_key из AZSystem.cpp)
# ---------------------------------------------------------------------------

def find_key_from_system_arc(system_arc_path: str) -> int | None:
    """
    Читает system.arc, находит sysenv.tbl, расшифровывает его,
    берёт первые 16 байт как resource_key, вычисляет финальный ключ
    через SFMT132049 (как в AZSystem_arc_extract_directory).
    Возвращает финальный u32 ключ или None при ошибке.
    """
    try:
        with open(system_arc_path, 'rb') as f:
            raw = f.read()
    except OSError as e:
        print(f"[!] Не могу открыть system.arc: {e}")
        return None

    # Пробуем каждый ini-вектор
    arc_header = None
    found_key = None
    for ini in INI_TABLE:
        key = gen_key(ini)
        hdr_bytes = bytearray(raw[:ARC_HEADER_SIZE])
        xor_stream(hdr_bytes, 0, key)
        magic = bytes(hdr_bytes[:4])
        if magic[:3] == b'ARC':
            arc_header_raw = bytes(hdr_bytes)
            found_key = key
            break

    if found_key is None:
        print("[!] Не удалось расшифровать заголовок system.arc ни одним из ini-ключей")
        return None

    # Разбираем заголовок
    magic, suffix_number, index_entries, compr_index_length = struct.unpack_from('<4sIII', arc_header_raw, 0)

    # Расшифровываем и декомпрессируем индекс
    compr_index_start = ARC_HEADER_SIZE
    compr_index_end   = compr_index_start + compr_index_length
    compr_index = bytearray(raw[compr_index_start:compr_index_end])
    xor_stream(compr_index, ARC_HEADER_SIZE, found_key)

    crc_stored = struct.unpack_from('<I', compr_index, 0)[0]
    # Определяем old_arc по CRC
    payload = bytes(compr_index[4:])
    if ewf_crc(payload) == crc_stored:
        old_arc = 0
    elif (zlib.crc32(payload) & 0xffffffff) == crc_stored:
        old_arc = 1
    else:
        print("[!] CRC индекса system.arc не совпадает")
        return None

    try:
        index_data = zlib.decompress(payload)
    except zlib.error as e:
        print(f"[!] Не удалось разжать индекс system.arc: {e}")
        return None

    # Ищем sysenv.tbl в индексе
    n_entries = index_entries
    sysenv_entry = None
    for i in range(n_entries):
        off = i * ARC_ENTRY_SIZE
        e_offset, e_length, e_name_crc, e_always_zero = struct.unpack_from('<IIII', index_data, off)
        e_name_raw = index_data[off+16 : off+16+32]
        e_name = e_name_raw.split(b'\x00')[0].decode('ascii', errors='replace')
        name_bytes = e_name_raw[:len(e_name)]
        crc_check = zlib.crc32(name_bytes) & 0xffffffff
        if e_name == 'sysenv.tbl':
            # Абсолютный офсет в файле
            abs_offset = e_offset + ARC_HEADER_SIZE + compr_index_length
            sysenv_entry = (abs_offset, e_length)
            break

    if sysenv_entry is None:
        print("[!] sysenv.tbl не найден в system.arc")
        return None

    abs_offset, e_length = sysenv_entry
    sysenv_compr = bytearray(raw[abs_offset : abs_offset + e_length])
    xor_stream(sysenv_compr, abs_offset, found_key)

    # Декомпрессируем sysenv.tbl (azsystem_decompress: ewf_crc + zlib)
    sysenv_crc = struct.unpack_from('<I', sysenv_compr, 0)[0]
    sysenv_payload = bytes(sysenv_compr[4:])
    if ewf_crc(sysenv_payload) != sysenv_crc:
        print("[!] CRC sysenv.tbl не совпадает")
        return None

    try:
        sysenv_data = zlib.decompress(sysenv_payload)
    except zlib.error as e:
        print(f"[!] Не удалось разжать sysenv.tbl: {e}")
        return None

    # Первые 16 байт = resource_key (4 u32)
    resource_key = struct.unpack_from('<4I', sysenv_data, 0)

    # Вычисляем финальный ключ через SFMT132049
    seed = zlib.crc32(struct.pack('<4I', *resource_key)) & 0xffffffff
    _ini = sfmt132049_gen_ini(seed)
    final_key = gen_key(_ini)
    print(f"[*] Финальный ключ из system.arc: 0x{final_key:08x}")
    return final_key


# ---------------------------------------------------------------------------
# Минимальная портативная реализация SFMT-132049
# (только init_gen_rand + 5 вызовов gen_rand32, как в AZSystem.cpp)
# ---------------------------------------------------------------------------

_MEXP    = 132049
_N       = _MEXP // 128 + 1   # 1032
_N32     = _N * 4              # 4128
_POS1    = 110
_SL1     = 19
_SL2     = 1
_SR1     = 21
_SR2     = 1
_MSK1    = 0xffffbb5f
_MSK2    = 0xfb6ebf95
_MSK3    = 0xfffefffa
_MSK4    = 0xcff77fff
_PARITY1 = 0x00000001
_PARITY2 = 0x00000000
_PARITY3 = 0xcb520000
_PARITY4 = 0xc7e91c7d

_MSK3    = 0xfffefffa  # исправленное значение


def _u32(x):
    return x & 0xffffffff


def _lshift128(a, b, c, d, shift):
    """Сдвиг 128-битного числа влево на shift байт"""
    th = (_u32(c) << 32 | _u32(d))
    tl = (_u32(a) << 32 | _u32(b))
    oh = th << (shift * 8)
    ol = tl << (shift * 8)
    oh |= tl >> (64 - shift * 8)
    oh = oh & 0xffffffffffffffff
    ol = ol & 0xffffffffffffffff
    r0 = _u32(ol >> 32)
    r1 = _u32(ol)
    r2 = _u32(oh >> 32)
    r3 = _u32(oh)
    return r0, r1, r2, r3


def _rshift128(a, b, c, d, shift):
    """Сдвиг 128-битного числа вправо на shift байт"""
    th = (_u32(a) << 32 | _u32(b))
    tl = (_u32(c) << 32 | _u32(d))
    oh = th >> (shift * 8)
    ol = tl >> (shift * 8)
    ol |= th << (64 - shift * 8)
    oh = oh & 0xffffffffffffffff
    ol = ol & 0xffffffffffffffff
    r0 = _u32(oh >> 32)
    r1 = _u32(oh)
    r2 = _u32(ol >> 32)
    r3 = _u32(ol)
    return r0, r1, r2, r3


def sfmt132049_gen_ini(seed: int) -> tuple:
    """
    Инициализирует SFMT-132049 заданным seed,
    генерирует 5 u32 значений (как в AZSystem_arc_extract_directory).
    """
    psfmt32 = [0] * _N32
    psfmt32[0] = seed & 0xffffffff
    for i in range(1, _N32):
        psfmt32[i] = _u32(1812433253 * _u32(psfmt32[i-1] ^ (psfmt32[i-1] >> 30)) + i)

    # period_certification
    parity = [_PARITY1, _PARITY2, _PARITY3, _PARITY4]
    inner = 0
    for i in range(4):
        inner ^= psfmt32[i] & parity[i]
    inner ^= inner >> 16
    inner ^= inner >> 8
    inner ^= inner >> 4
    inner ^= inner >> 2
    inner ^= inner >> 1
    inner &= 1
    if inner == 0:
        work = 1
        done = False
        for pi in range(4):
            for j in range(32):
                if work & parity[pi]:
                    psfmt32[pi] ^= work
                    done = True
                    break
                work = _u32(work << 1)
            if done:
                break

    def lshift128(a0, a1, a2, a3, shift):
        """128-bit left shift by 'shift' bytes (little-endian word order)."""
        s = shift * 8
        if s == 0:
            return a0, a1, a2, a3
        if s < 32:
            return (_u32(a0 << s),
                    _u32((a1 << s) | (a0 >> (32 - s))),
                    _u32((a2 << s) | (a1 >> (32 - s))),
                    _u32((a3 << s) | (a2 >> (32 - s))))
        if s < 64:
            s2 = s - 32
            return (0,
                    _u32(a0 << s2),
                    _u32((a1 << s2) | (a0 >> (32 - s2))) if s2 else a1,
                    _u32((a2 << s2) | (a1 >> (32 - s2))) if s2 else a2)
        if s < 96:
            s2 = s - 64
            return (0, 0,
                    _u32(a0 << s2),
                    _u32((a1 << s2) | (a0 >> (32 - s2))) if s2 else a1)
        s2 = s - 96
        return (0, 0, 0, _u32(a0 << s2))

    def rshift128(a0, a1, a2, a3, shift):
        """128-bit right shift by 'shift' bytes (little-endian word order)."""
        s = shift * 8
        if s == 0:
            return a0, a1, a2, a3
        if s < 32:
            return (_u32((a0 >> s) | (a1 << (32 - s))),
                    _u32((a1 >> s) | (a2 << (32 - s))),
                    _u32((a2 >> s) | (a3 << (32 - s))),
                    a3 >> s)
        if s < 64:
            s2 = s - 32
            return (_u32((a1 >> s2) | (a2 << (32 - s2))) if s2 else a1,
                    _u32((a2 >> s2) | (a3 << (32 - s2))) if s2 else a2,
                    a3 >> s2,
                    0)
        if s < 96:
            s2 = s - 64
            return (_u32((a2 >> s2) | (a3 << (32 - s2))) if s2 else a2,
                    a3 >> s2,
                    0, 0)
        s2 = s - 96
        return (a3 >> s2, 0, 0, 0)

    def do_recursion(a, b, c, d):
        x = lshift128(*a, _SL2)
        y = rshift128(*c, _SR2)
        msks = [_MSK1, _MSK2, _MSK3, _MSK4]
        return tuple(_u32(a[i] ^ x[i] ^ ((b[i] >> _SR1) & msks[i]) ^ y[i] ^ (d[i] << _SL1))
                     for i in range(4))

    def gen_rand_all():
        r1 = tuple(psfmt32[(_N - 2) * 4 + j] for j in range(4))
        r2 = tuple(psfmt32[(_N - 1) * 4 + j] for j in range(4))
        for i in range(_N - _POS1):
            a = tuple(psfmt32[i * 4 + j] for j in range(4))
            b = tuple(psfmt32[(i + _POS1) * 4 + j] for j in range(4))
            r = do_recursion(a, b, r1, r2)
            for j in range(4): psfmt32[i * 4 + j] = r[j]
            r1, r2 = r2, r
        for i in range(_N - _POS1, _N):
            a = tuple(psfmt32[i * 4 + j] for j in range(4))
            b = tuple(psfmt32[(i + _POS1 - _N) * 4 + j] for j in range(4))
            r = do_recursion(a, b, r1, r2)
            for j in range(4): psfmt32[i * 4 + j] = r[j]
            r1, r2 = r2, r

    gen_rand_all()
    v = psfmt32[:5]
    ini0 = v[0]
    ini1 = _u32((v[1] & 0xffff) | (v[2] << 16))
    ini2 = v[3]
    ini3 = v[4]
    return (ini0, ini1, ini2, ini3)



# ---------------------------------------------------------------------------
# Сжатие данных (azsystem_compress — обратное к azsystem_decompress)
# Формат: [ewf_crc(4 байта)] [zlib_compressed_data]
# ---------------------------------------------------------------------------

def azsystem_compress(data: bytes) -> bytes:
    compressed = zlib.compress(data, level=9)
    crc = ewf_crc(compressed)
    return struct.pack('<I', crc) + compressed

# ---------------------------------------------------------------------------
# Обёртка файлов во внутренние контейнеры (ASB и т.д.)
# ---------------------------------------------------------------------------

def wrap_asb(data: bytes) -> bytes:
    """Упаковывает голые ASB-данные обратно в ASB-контейнер (старый формат)."""
    uncomprlen = len(data)
    inner = azsystem_compress(data)   # [ewf_crc(4)][zlib]
    comprlen = len(inner)
    # asb_decompress делает *enc_data -= key, значит при упаковке += key
    key = (uncomprlen ^ 0x9E370001) & 0xffffffff
    inner_enc = bytearray(inner)
    for i in range(comprlen // 4):
        off = i * 4
        val = struct.unpack_from('<I', inner_enc, off)[0]
        struct.pack_into('<I', inner_enc, off, (val + key) & 0xffffffff)
    # asb_header_t: magic[4], comprlen, uncomprlen, unknown
    header = struct.pack('<4sIII', b'ASB\x00', comprlen, uncomprlen, 0)
    return header + bytes(inner_enc)


def wrap_file(name: str, data: bytes) -> bytes:
    """Оборачивает файл в контейнер по расширению, если нужно."""
    ext = Path(name).suffix.lower()
    # Если файл уже в контейнере — не трогаем
    if len(data) >= 4 and data[:3] in (b'ASB', b'TBL', b'CPB', b'TYP'):
        return data
    if ext == '.asb':
        return wrap_asb(data)
    return data


# ---------------------------------------------------------------------------
# Получение порядка файлов из оригинального .arc
# ---------------------------------------------------------------------------

def get_original_order(original_arc: str) -> list | None:
    """Возвращает список имён файлов в том порядке, в каком они лежат в оригинале."""
    try:
        raw = open(original_arc, 'rb').read()
    except OSError:
        return None
    for ini in INI_TABLE:
        k = gen_key(ini)
        hdr = bytearray(raw[:ARC_HEADER_SIZE])
        xor_stream(hdr, 0, k)
        if hdr[:3] == b'ARC':
            _, _, index_entries, compr_index_length = struct.unpack_from('<4sIII', hdr, 0)
            ci = bytearray(raw[ARC_HEADER_SIZE : ARC_HEADER_SIZE + compr_index_length])
            xor_stream(ci, ARC_HEADER_SIZE, k)
            payload = bytes(ci[4:])
            try:
                idx_raw = zlib.decompress(payload)
            except Exception:
                return None
            order = []
            for i in range(index_entries):
                off = i * ARC_ENTRY_SIZE
                name = idx_raw[off+16:off+48].split(b'\x00')[0].decode('ascii', 'replace')
                order.append(name)
            return order
    return None


# ---------------------------------------------------------------------------
# Главная функция упаковки
# ---------------------------------------------------------------------------

def pack_arc(input_dir: str, output_arc: str, system_arc: str | None = None, original_arc: str | None = None):
    input_path = Path(input_dir)
    if not input_path.is_dir():
        print(f"[!] {input_dir} — не папка")
        return False

    # Собираем список файлов
    # Сортируем файлы: если задан оригинал — сохраняем его порядок
    all_files = {f.name: f for f in input_path.iterdir() if f.is_file()}
    if original_arc and (orig_order := get_original_order(original_arc)):
        # Файлы из оригинала идут в оригинальном порядке,
        # новые файлы (которых не было) добавляются в конец
        known = [all_files[n] for n in orig_order if n in all_files]
        extra = [f for n, f in sorted(all_files.items()) if n not in set(orig_order)]
        files = known + extra
        print(f"[*] Порядок из оригинала: {len(known)} файлов, новых: {len(extra)}")
    else:
        files = sorted(all_files.values())
    if not files:
        print("[!] Папка пуста")
        return False

    print(f"[*] Файлов для упаковки: {len(files)}")

    # Определяем ключи
    ini = INI_TABLE[0]
    header_key = gen_key(ini)
    print(f"[*] Ключ заголовка (ini[0]): 0x{header_key:08x}")

    if system_arc:
        resource_key = find_key_from_system_arc(system_arc)
        if resource_key is None:
            print("[!] Не удалось получить ключ из system.arc, используем header_key")
            resource_key = header_key
    else:
        print("[*] system.arc не указан — используем header_key для данных")
        resource_key = header_key

    # --- Строим таблицу индекса (arc_entry_t) ---
    # Сначала нужно знать размеры зашифрованных файлов, чтобы посчитать офсеты.
    # Офсеты в arc_entry хранятся относительно конца заголовка+индекса,
    # но мы пока не знаем длину индекса — поэтому строим в два прохода.

    # Проход 1: читаем файлы, оборачиваем в контейнеры (ASB и т.д.)
    encrypted_files = []
    for f in files:
        raw = f.read_bytes()
        wrapped = wrap_file(f.name, raw)
        encrypted_files.append({'name': f.name, 'data': wrapped})

    # Проход 2: вычисляем офсеты
    # Структура файла:
    #   [arc_header_t: 48 байт]
    #   [compr_index: compr_index_length байт]
    #   [данные файлов...]

    # Сначала нужно построить и сжать индекс, чтобы узнать compr_index_length.
    # Офсеты в arc_entry — относительные (без заголовка и индекса), добавляются при чтении.
    # При упаковке записываем как есть (относительные).

    # Шаг A: строим индекс с временными офсетами, начиная с 0
    relative_offset = 0
    index_entries = []
    for ef in encrypted_files:
        name = ef['name']
        data = ef['data']
        length = len(data)  # длина зашифрованных данных = длина исходных (XOR не меняет размер)
        name_b = name.encode('ascii', errors='replace')
        if len(name_b) > 31:
            name_b = name_b[:31]
        name_b_padded = name_b.ljust(32, b'\x00')
        name_len = len(name_b)
        name_crc = zlib.crc32(name_b) & 0xffffffff

        entry = struct.pack('<IIII',
            relative_offset,   # offset (относительный)
            length,            # length
            name_crc,          # name_crc
            0,                 # always_zero
        ) + name_b_padded

        assert len(entry) == ARC_ENTRY_SIZE
        index_entries.append(entry)
        relative_offset += length

    index_raw = b''.join(index_entries)

    # Шаг B: сжимаем индекс
    index_compressed = zlib.compress(index_raw, level=9)
    # Добавляем EWF CRC
    index_crc = ewf_crc(index_compressed)
    compr_index_data = struct.pack('<I', index_crc) + index_compressed
    compr_index_length = len(compr_index_data)

    # Шаг C: шифруем compr_index
    compr_index_enc = bytearray(compr_index_data)
    xor_stream(compr_index_enc, ARC_HEADER_SIZE, header_key)

    # Шаг D: строим заголовок
    # suffix — расширения файлов (например ".tbl"), до 32 байт
    suffixes = set(Path(ef['name']).suffix for ef in encrypted_files)
    suffix_str = ''.join(sorted(suffixes))
    suffix_b = suffix_str.encode('ascii', errors='replace')[:31].ljust(32, b'\x00')

    # magic: "ARC\x00" или "ARC\x1a"? Для старого формата — "ARC\x00"
    # (arc_header_t.magic = "ARC", проверяется как strncmp(magic, "ARC", 4) — т.е. первые 3 байта)
    magic = b'ARC\x00'

    arc_header = struct.pack('<4sIII',
        magic,
        len(suffixes),          # suffix_number
        len(encrypted_files),   # index_entries
        compr_index_length,     # compr_index_length
    ) + suffix_b

    assert len(arc_header) == ARC_HEADER_SIZE

    # Шаг E: шифруем заголовок
    arc_header_enc = bytearray(arc_header)
    xor_stream(arc_header_enc, 0, header_key)

    # Шаг F: вычисляем абсолютные офсеты файлов и шифруем данные
    data_start = ARC_HEADER_SIZE + compr_index_length
    encrypted_data_list = []
    for i, ef in enumerate(encrypted_files):
        # Абсолютный офсет = data_start + relative_offset
        rel_off_in_entry = struct.unpack_from('<I', index_entries[i], 0)[0]
        abs_offset = data_start + rel_off_in_entry

        enc = bytearray(ef['data'])
        xor_stream(enc, abs_offset, resource_key)
        encrypted_data_list.append(bytes(enc))
        print(f"  -> {ef['name']}: {len(ef['data'])} байт, офсет 0x{abs_offset:08x}")

    # Шаг G: записываем файл
    with open(output_arc, 'wb') as out:
        out.write(bytes(arc_header_enc))
        out.write(bytes(compr_index_enc))
        for enc_data in encrypted_data_list:
            out.write(enc_data)

    total = os.path.getsize(output_arc)
    print(f"\n[+] Готово! Записано в: {output_arc} ({total} байт)")
    return True


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    input_dir    = sys.argv[1]
    output_arc   = sys.argv[2]
    system_arc   = sys.argv[3] if len(sys.argv) >= 4 else None
    original_arc = sys.argv[4] if len(sys.argv) >= 5 else None

    ok = pack_arc(input_dir, output_arc, system_arc, original_arc)
    sys.exit(0 if ok else 1)