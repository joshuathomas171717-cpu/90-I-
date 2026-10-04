#!/usr/bin/env bash
# Install the accessibility instruments (tests/a11y/*.mjs) and everything they need.
#
# Why this is a script: the tools need node, a headless Chromium and an npm install, none of which
# belong to a stdlib-Python project — and in this sandbox they evaporate between sessions, because
# /tmp is not persisted and ~/.cache (where Playwright keeps its browser) is excluded from snapshots.
# Rebuilding it by hand took two attempts to get right the first time; this is that, written down.
#
#   bash tools/setup_browser_tools.sh          # install and report
#   bash tools/setup_browser_tools.sh --check  # report what is missing, install nothing
#
# Then, with the site running (PORT=8000 python3 server.py):
#   node tests/a11y/sweep.mjs --reduce-motion
#   node tests/a11y/contrast.mjs --sample 30
#
# If Chromium cannot start for want of shared libraries, the script fetches them into
# /tmp/chromelibs and prints the LD_LIBRARY_PATH line to use. That is the sandbox's problem, not a
# normal machine's: on a desktop Linux or macOS, `npx playwright install chromium` is the whole story.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="${NT90_TOOLS_DIR:-/tmp/a11y}"
LIBS="${NT90_CHROMELIBS:-/tmp/chromelibs}"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

say() { printf '  %s\n' "$*"; }

command -v node >/dev/null 2>&1 || { say "node is not installed — the instruments cannot run here."; exit 1; }
say "node $(node --version), npm $(npm --version)"

if [ "$CHECK_ONLY" = "1" ]; then
  [ -d "$TOOLS/node_modules/playwright" ] && say "playwright installed in $TOOLS" || say "playwright MISSING from $TOOLS"
  [ -d "$TOOLS/node_modules/axe-core" ] && say "axe-core installed in $TOOLS" || say "axe-core MISSING from $TOOLS"
  [ -d "$HOME/.cache/ms-playwright" ] && say "chromium present in ~/.cache/ms-playwright" || say "chromium MISSING"
  exit 0
fi

mkdir -p "$TOOLS"
if [ ! -d "$TOOLS/node_modules/playwright" ] || [ ! -d "$TOOLS/node_modules/axe-core" ]; then
  say "installing playwright and axe-core into $TOOLS …"
  ( cd "$TOOLS" && npm install --silent --no-fund --no-audit playwright axe-core >/dev/null 2>&1 )
fi
say "playwright $(node -e "console.log(require('$TOOLS/node_modules/playwright/package.json').version)" 2>/dev/null || echo '?')"
say "axe-core   $(node -e "console.log(require('$TOOLS/node_modules/axe-core/package.json').version)" 2>/dev/null || echo '?')"

BROWSER_DIR="$HOME/.cache/ms-playwright"
BIN="$(find "$BROWSER_DIR" -name 'chrome-headless-shell' -type f 2>/dev/null | head -1)"
if [ -z "$BIN" ]; then
  say "downloading chromium (~115 MB) …"
  ( cd "$TOOLS" && npx --yes playwright install chromium >/dev/null 2>&1 )
  BIN="$(find "$BROWSER_DIR" -name 'chrome-headless-shell' -type f 2>/dev/null | head -1)"
fi
[ -n "$BIN" ] || { say "chromium install failed"; exit 1; }
say "chromium at $BIN"

# ── shared libraries ─────────────────────────────────────────────────────────────────────────────
missing_before="$(ldd "$BIN" 2>/dev/null | grep -c 'not found')"
if [ "$missing_before" != "0" ]; then
  say "$missing_before shared libraries missing — fetching them into $LIBS without root"
  mkdir -p "$LIBS" /tmp/nt90-debs
  # The pool files drift out of the apt index, so the versions that are definitely there are named
  # explicitly as a fallback. This is the part that cost two attempts.
  PKGS="libnspr4 libnss3 libxdamage1 libxkbcommon0 libasound2t64 libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64"
  ok=0
  for pkg in $PKGS; do
    ( cd /tmp/nt90-debs && apt-get download "$pkg" >/dev/null 2>&1 ) && ok=$((ok+1))
  done
  say "fetched $ok of $(echo $PKGS | wc -w) packages from the archive"
  # the two that are commonly 404 in the index: take the current pool file directly
  base="http://deb.debian.org/debian/pool/main"
  for url in \
    "$base/n/nss/libnss3_3.110-1+deb13u4_amd64.deb" \
    "$base/a/at-spi2-core/libatk-bridge2.0-0t64_2.56.2-1+deb13u2_amd64.deb" \
    "$base/a/at-spi2-core/libatspi2.0-0t64_2.56.2-1+deb13u2_amd64.deb"; do
    ( cd /tmp/nt90-debs && curl -s --max-time 60 -O "$url" ) || true
  done
  for d in /tmp/nt90-debs/*.deb; do dpkg-deb -x "$d" "$LIBS" 2>/dev/null || true; done
fi

LIBPATH="$(find "$LIBS" -name '*.so*' -printf '%h\n' 2>/dev/null | sort -u | tr '\n' ':' | sed 's/:$//')"
missing_after="$(LD_LIBRARY_PATH="$LIBPATH" ldd "$BIN" 2>/dev/null | grep -c 'not found')"
echo
if [ "$missing_after" = "0" ]; then
  say "ready."
  if [ -n "$LIBPATH" ]; then
    echo
    echo "  Run the instruments with:"
    echo "    export LD_LIBRARY_PATH=$LIBPATH"
    echo "    export NT90_PLAYWRIGHT_MODULES=$TOOLS/node_modules"
    echo "    node tests/a11y/sweep.mjs --reduce-motion"
  else
    echo
    echo "  Run the instruments with:  NT90_PLAYWRIGHT_MODULES=$TOOLS/node_modules node tests/a11y/sweep.mjs"
  fi
else
  say "still $missing_after libraries short — run: ldd $BIN | grep 'not found'"
  exit 1
fi
