"""A tiny PDF writer (text, lines, simple tables) so statements, receipts and the media kit need no extra library.
Helvetica only, A4, automatic page breaks. Text is ASCII-safe (other characters are replaced)."""
from __future__ import annotations

W, H = 595, 842  # A4 in points
M = 48


def _esc(s: str) -> str:
    s = str(s).replace("·", "-").replace("–", "-").replace("—", "-").replace("’", "'").replace("“", '"').replace("”", '"').replace("×", "x")
    s = s.encode("latin-1", "replace").decode("latin-1")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class Doc:
    def __init__(self, title: str):
        self.title = title
        self.pages: list[list[str]] = []
        self.y = 0
        self.new_page()

    def new_page(self):
        self.pages.append([])
        self.y = H - M

    def _need(self, h: float):
        if self.y - h < M + 20:
            self.new_page()

    def text(self, s: str, size: float = 11, bold: bool = False, x: float = M, gap: float = 4, color=(0.08, 0.09, 0.1)):
        self._need(size + gap)
        r, g, b = color
        f = "F2" if bold else "F1"
        self.pages[-1].append(f"{r} {g} {b} rg BT /{f} {size} Tf {x} {self.y - size} Td ({_esc(s)}) Tj ET")
        self.y -= size + gap

    def row(self, cols: list[tuple[str, float]], size: float = 10, bold: bool = False, align_right_from: int = 99):
        """cols: [(text, width)], left to right; columns from index align_right_from are right-aligned (roughly)."""
        self._need(size + 6)
        x = M
        f = "F2" if bold else "F1"
        for i, (t, w) in enumerate(cols):
            t = _esc(t)
            tx = x + w - len(t) * size * 0.5 if i >= align_right_from else x
            self.pages[-1].append(f"0.08 0.09 0.1 rg BT /{f} {size} Tf {tx:.1f} {self.y - size} Td ({t}) Tj ET")
            x += w
        self.y -= size + 6

    def rule(self, gap: float = 8):
        self._need(gap)
        self.pages[-1].append(f"0.85 0.84 0.81 RG 0.8 w {M} {self.y - 2} m {W - M} {self.y - 2} l S")
        self.y -= gap

    def space(self, h: float = 8):
        self.y -= h

    def bytes(self) -> bytes:
        objs: list[bytes] = []
        objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(len(self.pages)))
        objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(self.pages)} >>".encode())
        objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        for i, ops in enumerate(self.pages):
            footer = f"0.4 0.42 0.45 rg BT /F1 8 Tf {M} 28 Td ({_esc(self.title)} - page {i + 1} of {len(self.pages)} - Amend (PayPal sandbox demo)) Tj ET"
            stream = "\n".join(ops + [footer]).encode("latin-1")
            objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                        f"/Contents {6 + 2 * i} 0 R >>".encode())
            objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        out = bytearray(b"%PDF-1.4\n")
        offsets = []
        for n, o in enumerate(objs, 1):
            offsets.append(len(out))
            out += f"{n} 0 obj\n".encode() + o + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
        out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info << /Title ({_esc(self.title)}) /Producer (Amend) >> >>\nstartxref\n{xref}\n%%EOF".encode()
        return bytes(out)
