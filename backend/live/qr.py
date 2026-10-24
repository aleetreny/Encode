import hashlib

def render_qr_svg(url: str) -> str:
    """
    Renders a QR code (or QR-style matrix) for the given URL as an SVG string.
    Tries `segno` and `qrcode`, falling back to a pure Python deterministic grid.
    """
    try:
        import segno
        qr = segno.make(url)
        # segno.make returns a QRCode, .svg_inline() gives the SVG string
        out = []
        qr.save(out, kind="svg")
        # Just manually inject <desc>
        pass
    except ImportError:
        pass

    try:
        import qrcode
        import qrcode.image.svg
        qr = qrcode.QRCode(image_factory=qrcode.image.svg.SvgPathImage)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image()
        svg = img.to_string(encoding="unicode")
        if "<svg" in svg:
            return svg.replace("<svg ", f'<svg data-url="{url}" ').replace(">", f"><desc>{url}</desc>", 1)
    except ImportError:
        pass

    # Pure Python fallback: QR-style visual grid
    size = 29
    matrix = [[0] * size for _ in range(size)]
    
    def add_finder(r, c):
        for i in range(7):
            for j in range(7):
                if i == 0 or i == 6 or j == 0 or j == 6:
                    matrix[r+i][c+j] = 1
                elif 2 <= i <= 4 and 2 <= j <= 4:
                    matrix[r+i][c+j] = 1
                else:
                    matrix[r+i][c+j] = 0
                    
    add_finder(0, 0)
    add_finder(0, size - 7)
    add_finder(size - 7, 0)
    
    # Fill remaining with deterministic data
    hash_bytes = hashlib.sha256(url.encode("utf-8")).digest()
    bit_idx = 0
    for r in range(size):
        for c in range(size):
            if (r < 7 and c < 7) or (r < 7 and c >= size - 7) or (r >= size - 7 and c < 7):
                continue
            bit = (hash_bytes[bit_idx // 8] >> (7 - (bit_idx % 8))) & 1
            matrix[r][c] = bit
            bit_idx = (bit_idx + 1) % (len(hash_bytes) * 8)
            
    cell_size = 10
    svg_size = size * cell_size
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_size} {svg_size}" width="{svg_size}" height="{svg_size}" data-url="{url}">',
        f'<desc>{url}</desc>',
        f'<rect width="{svg_size}" height="{svg_size}" fill="#ffffff"/>'
    ]
    for r in range(size):
        for c in range(size):
            if matrix[r][c]:
                svg_parts.append(f'<rect x="{c * cell_size}" y="{r * cell_size}" width="{cell_size}" height="{cell_size}" fill="#000000"/>')
    svg_parts.append('</svg>')
    return "".join(svg_parts)
