"""Pre-publication credential guard. Stdlib, no key/network, no matched secret printed.

    python3 tools/publication_gate.py            # tracked files + generated public static files
    python3 tools/publication_gate.py --staged   # prospective commit bytes + public static files

This is a targeted guard, not a complete vulnerability/security audit. It fails on credential files,
private keys, common token signatures and literal long API-key assignments. Samples/dynamic env reads
are allowed. Build/XSS/schema tests remain separate gates. Fail closed on an unreadable candidate.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = [
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("Bearer credential", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_.-]{24,}")),
    ("credentialed URL", re.compile(r"https?://[^/\s:'\"]+:[^/@\s'\"]+@")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("literal API key", re.compile(r"(?i)(?:API_FOOTBALL_KEY|FOOTBALL_DATA_KEY|FOOTBALL_DATA_ORG_TOKEN|APISPORTS_KEY|VERCEL_TOKEN|GITHUB_TOKEN|NT90_METRICS_TOKEN|x-apisports-key|X-Auth-Token)\s*['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_-]{24,})")),
]


def forbidden_path(path):
    parts = Path(path).parts
    name = Path(path).name.lower()
    return (('.ssh' in parts or name in ('.env', '.netrc', '.git-credentials', 'id_rsa', 'id_ed25519')
             or name.startswith('.env.') and name != '.env.example'
             or name.endswith(('.pem', '.key'))))


def inspect_bytes(path, data, decode_json=True):
    problems = []
    if forbidden_path(path):
        problems.append({'path': path, 'line': None, 'kind': 'credential file'})
    if b'\0' in data[:4096]:
        return problems
    text = data.decode('utf-8', errors='replace')
    for kind, pattern in PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(1) if match.lastindex else match.group(0)
            if kind == 'literal API key' and (len(set(value.lower())) == 1 or value.lower().startswith(('your_', 'example_', 'placeholder_'))):
                continue
            problems.append({'path': path, 'line': text.count('\n', 0, match.start())+1, 'kind': kind})
    # Embedded/JSON escaped strings can contain credentials too. Decode without printing values.
    if decode_json:
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            parsed = None
        stack = [parsed]
        while stack:
            value = stack.pop()
            if isinstance(value, dict): stack.extend(value.values())
            elif isinstance(value, list): stack.extend(value)
            elif isinstance(value, str):
                for finding in inspect_bytes(path, value.encode("utf-8", errors="replace"), decode_json=False):
                    finding["line"] = None
                    if not any(p["kind"] == finding["kind"] for p in problems): problems.append(finding)
    return problems


def scan(root=ROOT, staged=False, include=None):
    root = Path(root)
    if (root/'.git').exists():
        mode = ['git','diff','--cached','--name-only','--diff-filter=ACMR','-z'] if staged else ['git','ls-files','-z']
        names = subprocess.check_output(mode, cwd=root).decode().split('\0')
    else:
        names = [str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()
                 and not any(x in p.relative_to(root).parts for x in ('node_modules','artifacts','__pycache__','.venv'))]
    names = set(n for n in names if n)
    names.update(str(p.relative_to(root)) for p in (root/'static').rglob('*') if p.is_file())
    for extra in include or []:
        target = root/extra
        if target.is_dir(): names.update(str(p.relative_to(root)) for p in target.rglob('*') if p.is_file())
        elif target.is_file(): names.add(str(target.relative_to(root)))
    problems = []
    for name in sorted(names):
        try:
            if staged and (root/'.git').exists() and not name.startswith('static/'):
                data = subprocess.check_output(['git','show',':'+name], cwd=root, stderr=subprocess.DEVNULL)
            else:
                data = (root/name).read_bytes()
            problems += inspect_bytes(name, data)
        except (OSError, subprocess.CalledProcessError):
            problems.append({'path': name, 'line': None, 'kind': 'unreadable publication candidate'})
    return {'ok': not problems, 'files_checked': len(names), 'problems': problems}


def main(argv=None):
    ap = argparse.ArgumentParser(description='Stop publication of obvious credentials; never echo the matched value.')
    ap.add_argument('--staged', action='store_true')
    ap.add_argument('--root', default=str(ROOT))
    ap.add_argument('--include', action='append', default=[], help='also scan guarded audit artifact directories')
    args = ap.parse_args(argv)
    report = scan(args.root, args.staged, args.include)
    print('Publication guard: %s — %d files checked' % ('PASS' if report['ok'] else 'HOLD', report['files_checked']))
    for p in report['problems']:
        print('  %s%s: %s (value redacted)' % (p['path'], ':'+str(p['line']) if p['line'] else '', p['kind']))
    if not report['ok']:
        print('Do not commit, push or deploy this candidate. Remove/rotate exposed credentials and rerun the gate.')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
