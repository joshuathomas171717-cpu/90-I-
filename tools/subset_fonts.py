#!/usr/bin/env python3
"""Rebuild static/src/fonts.css with subsetted copies of the three typefaces.

Why (P7.5): the dashboard inlines its fonts as base64 so it works offline, from a file:// URL and
inside a sandboxed preview with no network. That is the right call for this project — but it means the
fonts are part of the first load, and the three faces shipped as full Latin subsets: 111 KB of font,
149 KB of base64, on every single page view.

Subsetting to the characters the page can actually render is the cheapest weight this project can
shed. The character set is derived from the sources that produce visible text (the markup, the scripts
that write it, the data that feeds them) plus printable ASCII, so the result cannot be a font that
renders "Ars" correctly and a fallback face for "Arsenal".

Run it after adding a character this design uses that is not on the page yet:

    python3 tools/subset_fonts.py            # rewrite static/src/fonts.css
    python3 tools/subset_fonts.py --check    # report what it would save, change nothing

Requires fontTools and brotli (both dev-time only: the shipped project is stdlib Python and needs
neither — it ships the already-subsetted CSS).
"""
import base64
import io
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_CSS = os.path.join(BASE, "static", "src", "fonts.css")

SOURCES = [
    "static/src/app.html", "static/src/core.js", "static/src/render.js",
    "static/src/ux.js", "static/src/motion.js", "static/src/router.js", "static/src/share.js",
    "site_pages.py", "og_image.py", "build_dashboard.py",
]
DATA_DIRS = ["data"]

# Punctuation the design uses in copy that may not appear in a source string yet.
EXTRA = "—–·×÷≤≥→←↑↓£€°±≈%‰†‡“”‘’…✓✗"


def charset():
    chars = set(EXTRA)
    chars |= {chr(c) for c in range(0x20, 0x7F)}          # printable ASCII
    for rel in SOURCES:
        path = os.path.join(BASE, rel)
        if os.path.exists(path):
            chars |= set(open(path, encoding="utf-8", errors="ignore").read())
    for rel in DATA_DIRS:
        root = os.path.join(BASE, rel)
        for base, _dirs, files in os.walk(root):
            for name in files:
                if name.endswith((".csv", ".json")):
                    chars |= set(open(os.path.join(base, name), encoding="utf-8", errors="ignore").read())
    # Emoji are not in these faces and are served by the system emoji font; keeping them in the
    # subset request does nothing but make the subsetter's job ambiguous.
    chars = {c for c in chars if c.isprintable() and not (0x1F000 <= ord(c) <= 0x1FAFF)}
    return "".join(sorted(chars))


def subset_woff2(blob, text):
    from fontTools import subset
    from fontTools.ttLib import TTFont
    font = TTFont(io.BytesIO(blob))
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["*"]      # keep kerning, ligatures, the small-caps-ish alternates
    options.name_IDs = ["*"]
    options.notdef_outline = True
    options.recalc_bounds = True
    options.drop_tables += ["DSIG"]
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=text)
    subsetter.subset(font)
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def main():
    check = "--check" in sys.argv
    css = open(FONTS_CSS, encoding="utf-8").read()
    text = charset()
    faces = list(re.finditer(r"@font-face\s*\{.*?\}", css, re.S))
    if not faces:
        raise SystemExit("no @font-face rules found in %s" % FONTS_CSS)

    before = after = 0
    pieces, cursor = [], 0
    for face in faces:
        body = face.group(0)
        m = re.search(r"base64,([A-Za-z0-9+/=]+)\)", body)
        if not m:
            continue
        original = base64.b64decode(m.group(1))
        name = (re.search(r"font-family:\s*['\"]?([^'\";]+)", body) or [None, "?"])[1].strip()
        smaller = subset_woff2(original, text)
        before += len(original)
        after += len(smaller)
        if not check:
            new_body = body.replace(m.group(1), base64.b64encode(smaller).decode("ascii"))
            pieces.append((face.start(), face.end(), new_body))
        print("  %-16s %6.1f KB -> %5.1f KB  (%d glyphs kept)"
              % (name, len(original) / 1024, len(smaller) / 1024,
                 count_glyphs(smaller)))

    if not check:
        out = []
        last = 0
        for start, end, replacement in pieces:
            out.append(css[last:start]); out.append(replacement); last = end
        out.append(css[last:])
        open(FONTS_CSS, "w", encoding="utf-8").write("".join(out))
        print("  wrote %s (%.1f KB -> %.1f KB)" % (
            os.path.relpath(FONTS_CSS, BASE),
            os.path.getsize(FONTS_CSS) / 1024 + (before - after) / 1024,
            os.path.getsize(FONTS_CSS) / 1024))
    print("  fonts: %.1f KB -> %.1f KB  (%.0f%% smaller, %.1f KB of base64 saved in the page)"
          % (before / 1024, after / 1024, 100 * (1 - after / max(before, 1)),
             (before - after) * 4 / 3 / 1024))
    print("  characters requested: %d" % len(text))


def count_glyphs(blob):
    from fontTools.ttLib import TTFont
    try:
        return len(TTFont(io.BytesIO(blob)).getGlyphOrder())
    except Exception:
        return -1


if __name__ == "__main__":
    main()
