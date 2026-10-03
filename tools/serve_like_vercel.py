#!/usr/bin/env python3
"""Serve static/ the way Vercel will, by executing vercel.json's own rewrite rules.

Why this exists: `vercel.json` cannot be tested by deploying it, and a rewrite that is wrong is not
a loud failure — it is a 404 on a URL the site itself generates (the router pushes /table and
/club/arsenal into the address bar). So this reads the real config, applies its rewrites in order,
and serves the files underneath. If the rules and the app disagree, you find out here.

    python3 tools/serve_like_vercel.py            # http://0.0.0.0:8960
    python3 tools/serve_like_vercel.py --port 9000
"""
import argparse
import json
import os
import re
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(BASE, "static")


def load_rewrites():
    with open(os.path.join(BASE, "vercel.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    rules = []
    for rule in cfg.get("rewrites", []):
        source = rule["source"]
        # Vercel paths are path-to-regexp: /club/:slug -> one segment. Compile to the same thing.
        pattern = re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", r"(?P<\1>[^/]+)", source)
        rules.append((re.compile("^%s/?$" % pattern), rule["destination"]))
    return rules, cfg


REWRITES, CONFIG = load_rewrites()


def _match_rules(path):
    """Every vercel.json header rule that applies to a path, with Vercel's (.*) semantics."""
    out = []
    for rule in CONFIG.get("headers", []):
        pattern = rule["source"]
        if pattern == "/(.*)" or re.fullmatch(pattern.replace("(.*)", ".*").replace("/", r"\/"), path):
            out.extend(rule["headers"])
        else:
            probe = re.sub(r"\(\.\*\)", ".*", pattern)
            try:
                if re.fullmatch(probe.lstrip("/"), path.lstrip("/")):
                    out.extend(rule["headers"])
            except re.error:
                continue
    return out


class VercelLikeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    def end_headers(self):
        # The headers from vercel.json, applied here too. A CSP that breaks the page is worse than
        # no CSP, and the only way to find that out before deploying is to serve the real rules.
        seen = set()
        for header in _match_rules(self.path.split("?")[0]):
            if header["key"].lower() in seen:
                continue
            seen.add(header["key"].lower())
            self.send_header(header["key"], header["value"])
        super().end_headers()

    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        # A real file wins — this is what keeps /table.html (the crawlable page) distinct from
        # /table (the app), exactly as it does on Vercel.
        candidate = os.path.join(STATIC, clean.lstrip("/") or "index.html")
        if os.path.isfile(candidate):
            return candidate
        for pattern, destination in REWRITES:
            if pattern.match(clean):
                return os.path.join(STATIC, destination.lstrip("/"))
        return candidate

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8960)
    args = ap.parse_args()
    print("Serving static/ as Vercel would on port %d — %d rewrites from vercel.json:"
          % (args.port, len(REWRITES)))
    for pattern, destination in REWRITES:
        print("   %-24s -> %s" % (pattern.pattern.replace("^", "").replace("/?$", "")
                                  .replace("(?P<", ":").replace(">[^/]+)", ""), destination))
    print("   output directory: %s · build command: %r"
          % (CONFIG.get("outputDirectory"), CONFIG.get("buildCommand")))
    ThreadingHTTPServer(("0.0.0.0", args.port), VercelLikeHandler).serve_forever()


if __name__ == "__main__":
    main()
