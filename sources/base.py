"""Provider interface, team-name resolution, raw-payload caching and a rate-limited HTTP client.

Every provider returns the *internal* shapes, never its own. That is the whole point of the layer: the
pipeline downstream never knows whether a result came from an API, a CSV someone pasted, or the
2025-26 backtest. Normalised shapes:

    result        {"date": "2026-08-21", "home": "ARS", "away": "COV", "home_goals": 2, "away_goals": 0,
                   "matchweek": 1, "source_id": "537327", "source": "football-data.org"}
    table_row     {"code": "ARS", "position": 1, "played": 5, "won": 4, "drawn": 1, "lost": 0,
                   "gf": 12, "ga": 4, "gd": 8, "points": 13, "form": "WWWDW"}
    player_stat   {"name": "Erling Haaland", "code": "MCI", "stat": "goals", "value": 4, "source_id": "44"}

Raw payloads are cached under `data/raw/<YYYY-MM-DD>/` before parsing, so every automated run is
reproducible and auditable: if a number looks wrong a week later, the exact bytes that produced it are
still on disk.
"""
import csv
import json
import os
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(HERE)
DATA_DIR = os.path.join(BASE_DIR, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")

# football-data.org uses the season's *start* year; our internal naming uses "2026-27".
SEASON_LABEL = "2026-27"
SEASON_YEAR = "2026"


# ── team identity ────────────────────────────────────────────────────────────
def _load_teams():
    path = os.path.join(DATA_DIR, "teams_2026_27.csv")
    with open(path, encoding="utf-8") as fh:
        return {row["code"]: row for row in csv.DictReader(fh)}


TEAMS = _load_teams()

# Provider spellings that do not resolve to our code on their own. Kept explicit rather than fuzzy:
# a wrong club is worse than a failed lookup, and a failure is loud.
ALIASES = {
    "man city": "MCI", "manchester city": "MCI", "man utd": "MUN", "manchester united": "MUN",
    "nott'm forest": "NFO", "nottm forest": "NFO", "nottingham forest": "NFO", "forest": "NFO",
    "spurs": "TOT", "tottenham": "TOT", "tottenham hotspur": "TOT",
    "brighton": "BHA", "brighton & hove albion": "BHA", "brighton and hove albion": "BHA",
    "bournemouth": "BOU", "afc bournemouth": "BOU", "leeds": "LEE", "leeds united": "LEE",
    "coventry": "COV", "coventry city": "COV", "hull": "HUL", "hull city": "HUL",
    "ipswich": "IPS", "ipswich town": "IPS", "newcastle": "NEW", "newcastle united": "NEW",
    "palace": "CRY", "crystal palace": "CRY", "sunderland": "SUN", "everton": "EVE", "fulham": "FUL",
    "chelsea": "CHE", "arsenal": "ARS", "liverpool": "LIV", "wolves": "WOL",
    "wolverhampton wanderers": "WOL", "west ham": "WHU", "west ham united": "WHU", "burnley": "BUR",
    "villa": "AVL", "aston villa": "AVL", "brentford": "BRE", "west brom": "WBA",
}

SUFFIXES = ("fc", "afc", "cf", "sc", "city fc", "united fc")


def normalize_name(value):
    """Lower-case, drop punctuation, and strip the club-suffix noise providers add inconsistently
    ("Arsenal FC" and "Arsenal" are the same club; "Manchester City FC" is not a different one)."""
    text = str(value or "").lower().replace(".", "").replace("'", "").replace("&", "and")
    text = " ".join(text.split())
    parts = text.split(" ")
    while parts and parts[-1] in SUFFIXES:
        parts.pop()
    return " ".join(parts)


_LOOKUP = {}
for _code, _row in TEAMS.items():
    for _name in (_code, _row.get("name", ""), _row.get("short", "")):
        if _name:
            _LOOKUP[normalize_name(_name)] = _code
for _alias, _code in ALIASES.items():
    _LOOKUP[normalize_name(_alias)] = _code
    # Historical clubs resolve both by name and by code, so a normalised 2025–26 row round-trips.
    _LOOKUP[normalize_name(_code)] = _code


def team_code(value):
    """Resolve a provider's club name (or 3-letter code) to ours. Returns None if unknown — callers
    must treat that as a hard error rather than drop the fixture."""
    if not value:
        return None
    return _LOOKUP.get(normalize_name(value))


# ── raw payload cache ────────────────────────────────────────────────────────
def raw_dir(date=None):
    path = os.path.join(RAW_DIR, date or time.strftime("%Y-%m-%d"))
    os.makedirs(path, exist_ok=True)
    return path


def cache_raw(provider, name, payload, date=None):
    """Write the untouched provider response to disk and return its path."""
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)
    path = os.path.join(raw_dir(date), "%s-%s.json" % (provider, safe))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return path


def latest_raw(provider=None, name=None):
    """Most recent cached payload, for replaying a run without touching the network."""
    if not os.path.isdir(RAW_DIR):
        return None
    for day in sorted(os.listdir(RAW_DIR), reverse=True):
        day_path = os.path.join(RAW_DIR, day)
        if not os.path.isdir(day_path):
            continue
        for fname in sorted(os.listdir(day_path)):
            if not fname.endswith(".json"):
                continue
            if provider and not fname.startswith(provider):
                continue
            if name and name not in fname:
                continue
            return os.path.join(day_path, fname)
    return None


# ── HTTP, with the rate limit respected ─────────────────────────────────────
class RateLimitedError(RuntimeError):
    pass


class HttpClient:
    """Minimal urllib client: bearer-style headers, a request budget per minute, bounded retries.

    Free tiers are small (football-data.org: 10 requests/minute) and a weekly job is a handful of
    calls, so a naive sleep-between-calls is the honest implementation — no dependency required.
    """

    def __init__(self, per_minute=10, timeout=20, retries=2, backoff=2.0):
        self.min_interval = 60.0 / max(1, per_minute)
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self._last = 0.0
        self.calls = 0

    def get_json(self, url, headers=None):
        last_error = None
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            req = urllib.request.Request(url, headers=headers or {})
            try:
                self._last = time.time()
                self.calls += 1
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 429 and attempt < self.retries:      # rate limited: wait it out
                    retry_after = float(exc.headers.get("Retry-After", self.backoff * (attempt + 1)) or 60)
                    time.sleep(min(retry_after, 65))
                    continue
                if 500 <= exc.code < 600 and attempt < self.retries:
                    time.sleep(self.backoff * (attempt + 1))
                    continue
                raise
            except Exception as exc:                                # network hiccup: retry, then raise
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.backoff * (attempt + 1))
                    continue
                raise
        raise RateLimitedError(str(last_error))


# ── the interface ───────────────────────────────────────────────────────────
class Provider:
    """Every provider implements these three calls and declares what it can honestly supply."""

    name = "base"
    needs_key = False
    capabilities = {"results": False, "table": False, "player_stats": False, "xg": False, "live": False}
    notes = ""

    def __init__(self, offline=False):
        self.offline = offline
        self.warnings = []

    def available(self):
        """Can this provider actually run right now?"""
        return True

    def unavailable_reason(self):
        return None

    # ── the three calls ──
    def fetch_results(self, season=SEASON_LABEL):
        raise NotImplementedError

    def fetch_table(self, season=SEASON_LABEL):
        raise NotImplementedError

    def fetch_player_stats(self, season=SEASON_LABEL):
        """Return {"goals": [...], "assists": [...], "clean_sheets": [...]} — missing keys are honest."""
        raise NotImplementedError

    def describe(self):
        return {
            "name": self.name,
            "needs_key": self.needs_key,
            "available": self.available(),
            "unavailable_reason": self.unavailable_reason(),
            "capabilities": dict(self.capabilities),
            "notes": self.notes,
        }
