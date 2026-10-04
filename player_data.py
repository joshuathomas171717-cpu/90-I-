"""Shared, stdlib-only primitives for the optional player layer. No network on import."""
import csv
import datetime as dt
import json
import math
import os
import unicodedata

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
UTC = dt.timezone.utc
POLICY = os.path.join(DATA, "player_signal_policy.json")


def timestamp(value):
    """UTC datetime or None. Dates are accepted for *form*; calendars require an exact timestamp."""
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time(), tzinfo=UTC)
    try:
        parsed = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (ValueError, TypeError):
        return None


def exact_time(value):
    """A calendar date alone is not a kickoff time. Timezone is mandatory too."""
    text = str(value or "")
    if "T" not in text or not (text.endswith("Z") or "+" in text[10:] or "-" in text[10:]):
        return None
    return timestamp(text)


def number(value, default=0.0):
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (ValueError, TypeError):
        return default


def fold(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).lower().split())


def identity(row):
    # Never fuzzy-match abbreviated provider names to a famous player.
    return str(row.get("player_id") or fold(row.get("player") or row.get("name")))


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {} if default is None else default


def load_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def atomic_json(path, payload):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, allow_nan=False)
        fh.write("\n")
    os.replace(tmp, path)


def policy(path=POLICY):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def season_label(value):
    text = str(value or "").replace("–", "-")
    if len(text) == 4 and text.isdigit():
        return "%s-%02d" % (text, (int(text) + 1) % 100)
    return text
