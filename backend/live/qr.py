"""Pure-Python ISO/IEC 18004 QR Code SVG generator (`backend/live/qr.py`).

Generates scannable QR codes (Versions 1–6, ECC Level L, Byte Mode, Mask 0)
with zero third-party dependencies so `/api/live/sessions/{id}/qr.svg` works
in any environment and scans cleanly from a real smartphone camera.
"""

from __future__ import annotations

import html

# (version, total_data_codewords_L, ec_codewords_per_block_L, alignment_centers)
_VERSION_SPECS: list[tuple[int, int, int, list[int]]] = [
    (1, 19, 7, []),
    (2, 34, 10, [6, 18]),
    (3, 55, 15, [6, 22]),
    (4, 80, 20, [6, 26]),
    (5, 108, 26, [6, 30]),
    (6, 136, 18, [6, 34]),  # 2 blocks of (68 data, 18 ec)
]

# Precomputed format info bits for ECC Level L (01), Mask 0 (000) -> 0x77C4
_FORMAT_BITS_L_MASK0 = 0x77C4


def _gf_mul(a: int, b: int) -> int:
    res = 0
    for _ in range(8):
        if b & 1:
            res ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x11D
        b >>= 1
    return res


def _rs_generator_poly(degree: int) -> list[int]:
    poly = [1]
    root = 1
    for _ in range(degree):
        new_poly = [0] * (len(poly) + 1)
        for i, c in enumerate(poly):
            new_poly[i] ^= c
            new_poly[i + 1] ^= _gf_mul(c, root)
        poly = new_poly
        root = _gf_mul(root, 2)
    return poly


def _rs_encode(data: list[int], ec_len: int) -> list[int]:
    gen = _rs_generator_poly(ec_len)
    reg = [0] * ec_len
    for b in data:
        factor = b ^ reg[0]
        reg = reg[1:] + [0]
        for i in range(ec_len):
            reg[i] ^= _gf_mul(gen[i + 1], factor)
    return reg


def _encode_matrix(payload: bytes) -> list[list[int]]:
    # Pick smallest version (1..6) that fits payload in byte mode (4-bit mode + 8-bit len + data + 4-bit term)
    chosen = _VERSION_SPECS[-1]
    for spec in _VERSION_SPECS:
        ver, data_cw, _, _ = spec
        if len(payload) + 2 <= data_cw:
            chosen = spec
            break
    ver, data_cw, ec_cw, align = chosen
    if len(payload) + 2 > data_cw:
        payload = payload[: data_cw - 2]

    # Build bit stream: 0100 (byte mode) + 8-bit length + bytes + terminator + pad
    bits: list[int] = [0, 1, 0, 0]
    n_len = len(payload)
    for i in range(7, -1, -1):
        bits.append((n_len >> i) & 1)
    for b in payload:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    for _ in range(min(4, data_cw * 8 - len(bits))):
        bits.append(0)
    while len(bits) % 8 != 0:
        bits.append(0)
    pad_bytes = (0xEC, 0x11)
    p_idx = 0
    while len(bits) < data_cw * 8:
        pb = pad_bytes[p_idx % 2]
        p_idx += 1
        for i in range(7, -1, -1):
            bits.append((pb >> i) & 1)

    codewords = [
        sum(bits[i * 8 + j] << (7 - j) for j in range(8))
        for i in range(data_cw)
    ]

    if ver == 6:
        b1, b2 = codewords[:68], codewords[68:]
        ec1, ec2 = _rs_encode(b1, ec_cw), _rs_encode(b2, ec_cw)
        final_cw = [x for pair in zip(b1, b2) for x in pair] + [x for pair in zip(ec1, ec2) for x in pair]
    else:
        ec = _rs_encode(codewords, ec_cw)
        final_cw = codewords + ec

    all_bits: list[int] = []
    for cw in final_cw:
        for i in range(7, -1, -1):
            all_bits.append((cw >> i) & 1)
    all_bits.extend([0] * 7)

    size = 17 + 4 * ver
    grid: list[list[int | None]] = [[None] * size for _ in range(size)]

    def set_finder(r0: int, c0: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = r0 + dr, c0 + dc
                if 0 <= r < size and 0 <= c < size:
                    if 0 <= dr <= 6 and 0 <= dc <= 6:
                        on = (
                            dr in (0, 6)
                            or dc in (0, 6)
                            or (2 <= dr <= 4 and 2 <= dc <= 4)
                        )
                        grid[r][c] = 1 if on else 0
                    else:
                        grid[r][c] = 0

    set_finder(0, 0)
    set_finder(0, size - 7)
    set_finder(size - 7, 0)

    # Timing patterns
    for i in range(8, size - 8):
        bit = 1 if i % 2 == 0 else 0
        if grid[6][i] is None:
            grid[6][i] = bit
        if grid[i][6] is None:
            grid[i][6] = bit

    # Alignment patterns
    for ar in align:
        for ac in align:
            if (ar < 8 and ac < 8) or (ar < 8 and ac > size - 9) or (ar > size - 9 and ac < 8):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    on = abs(dr) == 2 or abs(dc) == 2 or (dr == 0 and dc == 0)
                    grid[ar + dr][ac + dc] = 1 if on else 0

    # Dark module & reserve format info areas
    grid[size - 8][8] = 1
    for i in range(9):
        if i != 6:
            if grid[8][i] is None:
                grid[8][i] = 0
            if grid[i][8] is None:
                grid[i][8] = 0
    for i in range(8):
        if grid[8][size - 1 - i] is None:
            grid[8][size - 1 - i] = 0
        if grid[size - 1 - i][8] is None:
            grid[size - 1 - i][8] = 0

    # Place data bits upward/downward in 2-column strips, applying Mask 0: (r + c) % 2 == 0
    bit_pos = 0
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for dc in (0, -1):
                c = col + dc
                if grid[r][c] is None:
                    b = all_bits[bit_pos] if bit_pos < len(all_bits) else 0
                    bit_pos += 1
                    if (r + c) % 2 == 0:
                        b ^= 1
                    grid[r][c] = b
        upward = not upward
        col -= 2

    # Write format information bits (L, Mask 0)
    fmt = _FORMAT_BITS_L_MASK0
    fmt_bits = [(fmt >> i) & 1 for i in range(15)]
    # Around top-left
    r_coords = [8, 8, 8, 8, 8, 8, 8, 8, 7, 5, 4, 3, 2, 1, 0]
    c_coords = [0, 1, 2, 3, 4, 5, 7, 8, 8, 8, 8, 8, 8, 8, 8]
    for i in range(15):
        grid[r_coords[i]][c_coords[i]] = fmt_bits[14 - i]
    # Split across bottom-left and top-right
    for i in range(7):
        grid[size - 1 - i][8] = fmt_bits[14 - i]
    for i in range(7, 15):
        grid[8][size - 15 + i] = fmt_bits[14 - i]

    return [[int(cell or 0) for cell in row] for row in grid]


def render_qr_svg(url: str) -> str:
    """Render a scannable ISO/IEC 18004 QR code SVG for the given URL."""
    matrix = _encode_matrix(url.encode("utf-8"))
    n = len(matrix)
    quiet = 4
    total = n + quiet * 2
    cell = 8
    dim = total * cell
    esc_url = html.escape(url, quote=True)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {dim} {dim}" width="{dim}" height="{dim}" data-url="{esc_url}" shape-rendering="crispEdges">',
        "<title>Andes · Operación de la red eléctrica con IA</title>",
        f"<desc>{esc_url}</desc>",
        f'<rect width="{dim}" height="{dim}" fill="#ffffff"/>',
    ]
    for r, row in enumerate(matrix):
        for c, val in enumerate(row):
            if val:
                x = (c + quiet) * cell
                y = (r + quiet) * cell
                parts.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="#000000"/>')
    parts.append("</svg>")
    return "".join(parts)
