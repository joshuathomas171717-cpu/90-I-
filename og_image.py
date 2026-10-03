"""og_image.py — 1200×630 social cards, drawn without a browser and without a dependency.

Every share of this site (a club's projection, a gameweek's fixtures, the projected table) wants an
image, and social platforms only accept raster formats — no SVG. The usual answer is a headless
browser or Pillow; both are a large new dependency for a project whose whole point is that you can
run it from a clean extraction with four libraries, two of which are numpy and pandas.

So this module encodes PNG itself — `zlib` and `struct` from the standard library — and draws text
with a hand-made 5×7 bitmap font scaled up. The result is deliberately scoreboard-like: chunky,
high-contrast, readable at the size a link preview is actually shown. It is also completely
deterministic, which matters here: the same inputs produce the same bytes on every machine, so a
rebuild never churns these files.

    from og_image import club_card, gameweek_card, table_card, site_card, icon_png

Rendered at build time by site_pages.py into static/og/, and served straight off disk by server.py.
"""
import os
import struct
import zlib

# ── the palette, matching static/src/theme.css ───────────────────────────────────────────────────
INK = (0x0B, 0x0F, 0x1A)          # page background
PANEL = (0x12, 0x18, 0x2A)
TEXT = (0xEC, 0xF1, 0xFB)
DIM = (0x8E, 0x9B, 0xB8)
FAINT = (0x2A, 0x33, 0x4D)
CYAN = (0x22, 0xD3, 0xEE)
MAGENTA = (0xE5, 0x4B, 0x9A)

# ── a 5×7 font. Each glyph is seven rows of five columns; "#" is ink, "." is empty ──────────────
_GLYPHS = {
    "A": "01110 10001 10001 11111 10001 10001 10001",
    "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110",
    "D": "11110 10001 10001 10001 10001 10001 11110",
    "E": "11111 10000 10000 11110 10000 10000 11111",
    "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111",
    "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "11111 00100 00100 00100 00100 00100 11111",
    "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001",
    "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001",
    "N": "10001 11001 10101 10011 10001 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110",
    "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101",
    "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110",
    "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110",
    "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 11011 10001",
    "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 01010 00100 00100 00100 00100",
    "Z": "11111 00001 00010 00100 01000 10000 11111",
    "0": "01110 10001 10011 10101 11001 10001 01110",
    "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111",
    "3": "11111 00010 00100 00010 00001 10001 01110",
    "4": "00010 00110 01010 10010 11111 00010 00010",
    "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110",
    "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110",
    "9": "01110 10001 10001 01111 00001 00010 01100",
    " ": "00000 00000 00000 00000 00000 00000 00000",
    ".": "00000 00000 00000 00000 00000 01100 01100",
    ",": "00000 00000 00000 00000 01100 00100 01000",
    ":": "00000 01100 01100 00000 01100 01100 00000",
    "-": "00000 00000 00000 11111 00000 00000 00000",
    "+": "00000 00100 00100 11111 00100 00100 00000",
    "%": "11001 11010 00010 00100 01000 01011 10011",
    "/": "00001 00010 00010 00100 01000 01000 10000",
    "(": "00010 00100 01000 01000 01000 00100 00010",
    ")": "01000 00100 00010 00010 00010 00100 01000",
    "'": "00100 00100 00000 00000 00000 00000 00000",
    "!": "00100 00100 00100 00100 00100 00000 00100",
    "?": "01110 10001 00001 00110 00100 00000 00100",
    "=": "00000 00000 11111 00000 11111 00000 00000",
    "·": "00000 00000 00000 01100 01100 00000 00000",
    "’": "00100 00100 00000 00000 00000 00000 00000",
    "–": "00000 00000 00000 11111 00000 00000 00000",
    "—": "00000 00000 00000 11111 00000 00000 00000",
    "…": "00000 00000 00000 00000 00000 00000 10101",
}
_FONT = {ch: [int(row.replace(" ", ""), 2) for row in rows.split()] for ch, rows in _GLYPHS.items()}
GLYPH_W, GLYPH_H = 5, 7


def _fold(text):
    """Cards are set in an uppercase bitmap font. Map the characters it cannot draw."""
    out = []
    for ch in text:
        up = ch.upper()
        if up in _FONT:
            out.append(up)
        elif ch in _FONT:
            out.append(ch)
        else:
            out.append({"ø": "O", "ß": "SS", "é": "E", "á": "A", "í": "I", "ó": "O", "ú": "U",
                        "ü": "U", "ö": "O", "ä": "A", "ñ": "N", "ç": "C", "å": "A", "æ": "AE"}.get(ch, "?"))
    return "".join(out)


class Canvas:
    """A tiny RGB raster with the handful of primitives these cards need."""

    def __init__(self, width, height, background=INK):
        self.w, self.h = width, height
        self.buf = bytearray(background * (width * height))

    def _blit(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.buf[i:i + 3] = bytes(color)

    def rect(self, x, y, w, h, color):
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(self.w, int(x + w)), min(self.h, int(y + h))
        row = bytes(color) * max(0, x1 - x0)
        for yy in range(y0, y1):
            i = (yy * self.w + x0) * 3
            self.buf[i:i + len(row)] = row

    def fade(self, x, y, w, h, color, steps=90):
        """A vertical gradient into the background — cheap depth for a flat card."""
        x0, x1 = max(0, int(x)), min(self.w, int(x + w))
        y0, y1 = max(0, int(y)), min(self.h, int(y + h))
        span = max(1, y1 - y0)
        for yy in range(y0, y1):
            f = (yy - y0) / span
            shade = tuple(int(background + (c - background) * f) for c, background in zip(color, INK))
            self.rect(x0, yy, x1 - x0, 1, shade)

    def text_width(self, s, scale, tracking=1):
        return (len(s) * (GLYPH_W + tracking) - tracking) * scale if s else 0

    def text(self, x, y, s, scale=3, color=TEXT, tracking=1):
        s = _fold(s)
        cx = x
        for ch in s:
            rows = _FONT.get(ch, _FONT["?"])
            for ry, bits in enumerate(rows):
                for rx in range(GLYPH_W):
                    if bits & (1 << (GLYPH_W - 1 - rx)):
                        self.rect(cx + rx * scale, y + ry * scale, scale, scale, color)
            cx += (GLYPH_W + tracking) * scale
        return cx

    def text_fit(self, x, y, s, scale=3, color=TEXT, tracking=1, max_w=None):
        """Draw text that must fit a width: shrink to a floor, then truncate with an ellipsis.

        Cards are fixed at 1200×630 and a footer can easily be longer than the card — the first
        render of the club card ran its attribution off the right-hand edge. Silently clipping is
        worse than shrinking: an attribution nobody can read is not an attribution.
        """
        if max_w:
            floor = 2
            while scale > floor and self.text_width(s, scale, tracking) > max_w:
                scale -= 1
            if self.text_width(s, scale, tracking) > max_w:
                while len(s) > 1 and self.text_width(s + "…", scale, tracking) > max_w:
                    s = s[:-1]
                s = s.rstrip(" ·,") + "…"
        return self.text(x, y, s, scale=scale, color=color, tracking=tracking)

    def bar(self, x, y, w, h, fraction, color, track=FAINT):
        self.rect(x, y, w, h, track)
        fill = max(0, min(1.0, float(fraction))) * w
        if fill >= 1:
            self.rect(x, y, fill, h, color)

    def save(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(to_png(self.w, self.h, self.buf))
        return path


def to_png(width, height, rgb):
    """Encode raw RGB rows as a PNG. Filter type 0 (none) on every row — these are small images."""
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)   # 8-bit, truecolour
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def png_size(path):
    """(width, height) of a PNG on disk, read from the header. Used by the tests."""
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ValueError("%s is not a PNG" % path)
    return struct.unpack(">II", head[16:24])


# ── card furniture ───────────────────────────────────────────────────────────────────────────────
W, H = 1200, 630


def _hex(color, fallback=(0x6C, 0xAB, 0xDD)):
    color = (color or "").lstrip("#")
    if len(color) != 6:
        return fallback
    try:
        return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def _frame(accent, kicker, footer):
    """The shared furniture: background, accent edge, wordmark, kicker, footer."""
    c = Canvas(W, H)
    c.fade(0, 0, W, H, PANEL, steps=120)
    c.rect(0, 0, 14, H, accent)                 # the club's colour down the left edge
    c.rect(14, 0, 4, H, CYAN)
    # wordmark
    c.text(64, 52, "NINETY+", scale=4, color=TEXT, tracking=2)
    c.text_fit(64 + c.text_width("NINETY+", 4, 2) + 26, 56, kicker.upper(), scale=3, color=CYAN,
               tracking=2, max_w=W - 128 - c.text_width("NINETY+", 4, 2) - 26)
    # a hairline and the footer line
    c.rect(64, 128, W - 128, 2, FAINT)
    c.rect(64, H - 96, W - 128, 2, FAINT)
    c.text_fit(64, H - 68, footer, scale=2, color=DIM, tracking=2, max_w=W - 128)
    return c


def _strip(c, x, y, w, rows, label_scale=3, value_scale=3):
    """Rows of `label, value, fraction, colour` — the stat block at the foot of a card."""
    for i, (label, value, frac, color) in enumerate(rows):
        yy = y + i * 46
        c.text(x, yy, label, scale=label_scale, color=DIM, tracking=2)
        c.text(x + w - c.text_width(value, value_scale, 2), yy - 2, value, scale=value_scale, color=TEXT, tracking=2)
        c.bar(x, yy + 26, w, 8, frac, color)


def club_card(team, out_path):
    """One club: projected points, and the three probabilities that decide its season."""
    accent = _hex(team.get("color"))
    c = _frame(accent, "premier league 2026-27",
               "%s · %s · 5,000 simulated seasons · not affiliated with the premier league" %
               (team.get("name", "").upper(), team.get("stadium", "").upper()))
    c.text(64, 176, team.get("name", ""), scale=7, color=TEXT, tracking=2)
    c.text(64, 262, "%d PTS PROJECTED · %s" % (round(team.get("proj_pts", 0)),
                                              team.get("manager", "").upper()), scale=3, color=DIM, tracking=2)

    def p(v):
        v = float(v or 0)
        return ("%.0f%%" % v), v / 100.0

    tv, tf = p(team.get("title_prob"))
    fv, ff = p(team.get("top4_prob"))
    rv, rf = p(team.get("relegation_prob"))
    _strip(c, 64, 350, W - 128, [
        ("TITLE", tv, tf, CYAN),
        ("TOP FOUR", fv, ff, _hex("#7C6CF0")),
        ("RELEGATION", rv, rf, MAGENTA),
    ])
    return c.save(out_path)


def gameweek_card(gw, dates, fixtures, out_path, mode="prediction"):
    """One gameweek: the fixtures, with the model's pick — or, once played, the result."""
    if mode == "result":
        footer = "MATCHWEEK %d · %s · RESULT" % (gw, dates.upper())
    else:
        footer = "MATCHWEEK %d · %s · PROBABILITIES FROM 5,000 SIMULATED SEASONS" % (gw, dates.upper())
    c = _frame(CYAN, "premier league 2026-27", footer)
    c.text(64, 164, "MATCHWEEK %d" % gw, scale=7, color=TEXT, tracking=2)
    c.text(64, 250, dates.upper(), scale=3, color=DIM, tracking=2)
    # The rows have to fit between the header and the footer hairline (y=534). Laying them out at a
    # fixed pitch put the sixth fixture straight through the attribution — so the pitch is derived
    # from how many rows there are and how much room is left.
    rows = fixtures[:7]
    top, bottom = 320, 528
    pitch = max(28, (bottom - top) // max(1, len(rows)))
    box = pitch - 6
    y = top
    for fx in rows:
        home, away = fx["home"], fx["away"]
        c.rect(64, y - 6, W - 128, box, PANEL)
        c.text(80, y, home, scale=3, color=TEXT, tracking=2)
        c.text(80 + c.text_width(home, 3, 2) + 16, y, str(fx.get("lambda_home", "")), scale=2, color=DIM, tracking=1)
        c.text(520, y, "v", scale=3, color=FAINT, tracking=2)
        c.text(560, y, away, scale=3, color=TEXT, tracking=2)
        c.text(560 + c.text_width(away, 3, 2) + 16, y, str(fx.get("lambda_away", "")), scale=2, color=DIM, tracking=1)
        pick = fx.get("result") if mode == "result" else fx.get("pick")
        if pick:
            c.text(W - 200, y, pick, scale=3, color=(TEXT if mode == "result" else CYAN), tracking=2)
        y += pitch
    return c.save(out_path)


def table_card(rows, out_path):
    """The projected table: the top of it, plus who goes down."""
    c = _frame(CYAN, "2026-27 projection", "PROJECTED FINAL TABLE · 5,000 SIMULATED SEASONS · NOT AFFILIATED")
    c.text(64, 164, "PROJECTED TABLE", scale=7, color=TEXT, tracking=2)
    y = 274
    for i, r in enumerate(rows[:10]):
        colour = CYAN if i < 4 else (MAGENTA if r.get("relegation_prob", 0) > 50 else TEXT)
        c.text(64, y, "%2d" % (i + 1), scale=3, color=DIM, tracking=2)
        c.text(140, y, r["code"], scale=3, color=colour, tracking=2)
        c.text(240, y, r["name"][:22], scale=3, color=TEXT, tracking=2)
        c.text(W - 260, y, "%.0f PTS" % r["proj_pts"], scale=3, color=TEXT, tracking=2)
        c.text(W - 130, y, "%.0f%%" % r["title_prob"], scale=3, color=CYAN, tracking=2)
        y += 32
    return c.save(out_path)


def duel_card(a, b, out_path):
    """A head-to-head: two clubs, one line each, decided by the numbers."""
    ca, cb = _hex(a.get("color")), _hex(b.get("color"))
    c = _frame(ca, "head to head", "WHO WINS THE LEAGUE? · 5,000 SIMULATED SEASONS · NOT AFFILIATED")
    c.rect(W // 2 - 1, 150, 2, H - 246, FAINT)
    for side, team, colour in ((0, a, ca), (1, b, cb)):
        x = 64 + side * (W // 2)
        avail = W // 2 - 96
        name = team.get("name", "").upper()
        while c.text_width(name, 5, 2) > avail and len(name) > 3:
            name = name[:-1]
        c.text(x, 220, name, scale=5, color=TEXT, tracking=2)
        c.text(x, 296, "%.1f PTS" % team.get("proj_pts", 0), scale=4, color=colour, tracking=2)
        c.text(x, 372, "TITLE %.1f%%" % team.get("title_prob", 0), scale=3, color=DIM, tracking=2)
        c.text(x, 414, "TOP FOUR %.1f%%" % team.get("top4_prob", 0), scale=3, color=DIM, tracking=2)
        c.text(x, 456, "RELEGATION %.1f%%" % team.get("relegation_prob", 0), scale=3, color=DIM, tracking=2)
    return c.save(out_path)


def site_card(champion, note, out_path):
    """The default card: who the model says wins the league."""
    accent = _hex(champion.get("color"))
    c = _frame(accent, "premier league 2026-27", "NINETY+ · NOT AFFILIATED WITH THE PREMIER LEAGUE")
    c.text(64, 170, "MODEL SAYS", scale=3, color=DIM, tracking=4)
    name = champion.get("name", "").upper()
    scale = 8
    while c.text_width(name, scale, 2) > W - 128 and scale > 3:
        scale -= 1
    c.text(64, 216, name, scale=scale, color=TEXT, tracking=2)
    c.text(64, 216 + GLYPH_H * scale + 28,
           "%.0f POINTS PROJECTED · %.0f%% TITLE PROBABILITY" %
           (champion.get("proj_pts", 0), champion.get("title_prob", 0)), scale=3, color=CYAN, tracking=2)
    c.text(64, 470, note.upper(), scale=3, color=DIM, tracking=2)
    c.bar(64, 520, W - 128, 10, champion.get("title_prob", 0) / 100.0, accent)
    return c.save(out_path)


def ico_bytes(png_path, size):
    """Wrap an existing square PNG in an ICO container.

    ICO is the format a browser asks for when it gives up on the page's own declared icons: Safari and
    a long tail of crawlers, feed readers and link-preview bots request `/favicon.ico` on sight, and a
    404 there shows up as a console error on a page that is otherwise perfect. This project shipped
    that 404 until a clean-room route sweep found it.

    Modern ICO allows a PNG payload verbatim, so there is nothing to re-encode: a 6-byte header, one
    16-byte directory entry, then the PNG. A 16-bit field would be 22.5 KB, so the size is stored as a
    single byte — 0 means 256, the format's one piece of legacy weirdness.
    """
    with open(png_path, "rb") as fh:
        png = fh.read()
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("%s is not a PNG, so it cannot be wrapped as an ICO" % png_path)
    dim = 0 if size >= 256 else size                    # 0 means 256 in this field
    # width, height, palette colours, reserved, planes, bits-per-pixel, payload size, payload offset
    entry = struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), 22)
    return struct.pack("<HHH", 0, 1, 1) + entry + png


def icon_png(size, out_path, background=INK, accent=CYAN, text="90+"):
    """Square app icon / apple-touch / favicon PNG."""
    c = Canvas(size, size, background)
    c.rect(0, 0, size, max(2, size // 24), accent)
    scale = max(1, size // 12)
    tw = c.text_width(text, scale, 1)
    c.text((size - tw) // 2, (size - GLYPH_H * scale) // 2, text, scale=scale, color=TEXT, tracking=1)
    return c.save(out_path)


FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="NINETY+">'
    '<rect width="64" height="64" rx="12" fill="#0B0F1A"/>'
    '<rect x="0" y="0" width="64" height="5" rx="2" fill="#22D3EE"/>'
    '<text x="32" y="44" font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif" '
    'font-size="30" font-weight="700" fill="#ECF1FB" text-anchor="middle">90+</text>'
    '</svg>'
)
