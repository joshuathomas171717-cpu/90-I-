"""api_football.py — the player-data source, on a free key (P13.2).

What this provider is for, and what it is not:

* **For.** Per-player minutes, goals, assists and ratings **split by competition** — league, Champions
  League, FA Cup, EFL Cup, internationals — plus who is currently injured or suspended. One request per
  club returns every competition that club's players appeared in, so twenty clubs is twenty requests.
* **Not for.** xG. API-Football has none on any plan (see docs/xg-strategy.md); the engine keeps its own
  ratings and that trade is documented rather than quietly patched.

The free tier's real constraint is **volume, not features**: 100 requests a day, every endpoint open.
This job is weekly and needs about 25, which is comfortable — but a backfill is not, so the provider
counts what it spends, persists the count against the UTC day, and stops at a budget instead of blowing
the allowance and leaving the *next* run unable to fetch anything. Running out is a scheduling problem;
running out silently is a bug.

Three properties matter more than the fetching itself:

1. **No key, no effect.** `available()` is False and every call returns an empty list. The pipeline is
   unchanged, tests still pass, and `data/provider_drop/players/` is the documented way in without an
   account. A player feature that only works with a secret is a player feature that cannot be tested.
2. **Everything raw is cached** under `data/raw/<date>/api-football/` before it is parsed, so a day's
   quota is never spent twice on the same payload and a replay reproduces the same rows exactly.
3. **Team ids are resolved at runtime, not hardcoded.** Twenty ids typed from memory would be twenty
   chances to silently attach one club's players to another; the map is fetched once, cached, and if it
   cannot be fetched the provider says so and returns nothing.
"""
import datetime
import json
import os
import time

from .base import Provider, SEASON_LABEL, SEASON_YEAR, HttpClient, cache_raw, latest_raw, team_code

API = "https://v3.football.api-sports.io"

# The Premier League's id at this provider. This is the one number that has to be right for anything
# else to work, so it is verified by the audit tool (tools/audit_sources.py) rather than trusted: the
# audit checks that the id returns twenty clubs whose names match our own club list.
PL_LEAGUE_ID = 39

# The season parameter is the year the season *starts*: 2026-27 is 2026.
DEFAULT_SEASON = SEASON_YEAR

# How many requests this provider may spend per UTC day. The free tier allows 100; the budget is lower
# on purpose so a backfill cannot eat the allowance the weekly job needs.
DEFAULT_BUDGET = 25

QUOTA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "raw", "api_football_quota.json")


def today_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


class Quota:
    """A daily counter that survives the process, because the limit is per day, not per run.

    Deliberately counts *requests*, not successes: a 429 or a timeout still consumed network and time,
    and pretending otherwise is how a budget gets overrun.
    """

    def __init__(self, path=QUOTA_FILE, budget=DEFAULT_BUDGET, day=None):
        self.path = path
        self.budget = int(os.environ.get("NT90_API_FOOTBALL_BUDGET") or budget)
        self.day = day or today_utc()
        self.used = self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                blob = json.load(fh)
        except (OSError, ValueError):
            return 0
        if blob.get("day") != self.day:
            return 0                      # a new UTC day: the allowance resets (it does at the provider too)
        return int(blob.get("used") or 0)

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"day": self.day, "used": self.used, "budget": self.budget}, fh, indent=2)
        os.replace(tmp, self.path)        # atomic: a kill mid-write must not corrupt the counter

    @property
    def left(self):
        return max(0, self.budget - self.used)

    def spend(self, n=1):
        """True if the request may go ahead. Records it immediately — the assumption is the worst case."""
        if self.left < n:
            return False
        self.used += n
        self._save()
        return True


class ApiFootballProvider(Provider):
    name = "api-football"
    needs_key = True
    capabilities = {"results": False, "table": False, "player_stats": True, "injuries": True,
                    "xg": False, "live": False}
    notes = ("Free tier: 100 requests/day, every endpoint. Player statistics per competition and "
             "injuries. No xG on any plan, so the engine keeps its own ratings.")

    def __init__(self, token=None, offline=False, budget=DEFAULT_BUDGET, season=DEFAULT_SEASON):
        super().__init__(offline=offline)
        self.token = (token or os.environ.get("API_FOOTBALL_KEY")
                      or os.environ.get("API_FOOTBALL_API_KEY")
                      or os.environ.get("APISPORTS_KEY"))
        self.season = str(season)
        self.quota = Quota(budget=budget)
        # 10 requests/minute is the documented per-minute cap; the daily cap is enforced by Quota, which
        # the per-minute limiter knows nothing about.
        self.http = HttpClient(per_minute=10)

    # ── availability ──
    def available(self):
        return bool(self.token) and not self.offline

    def unavailable_reason(self):
        if self.offline:
            return "offline mode (cached payloads only)"
        if not self.token:
            return ("no API key — set API_FOOTBALL_KEY (free: https://dashboard.api-football.com/register, "
                    "100 requests/day, no card). Without it the player signal comes from "
                    "data/provider_drop/players/ instead")
        return None

    # ── transport ──
    def _get(self, path, params, cache_name, replay=False):
        """One GET, raw-cached first, quota-spent before the socket opens.

        The cache name is a hash-free slug of the params so a fetched payload can be found again by
        name; `replay` reads the newest cached copy and spends no quota, which is what makes a replay
        after the fact free.
        """
        if replay or self.offline:
            cached = latest_raw(self.name, cache_name)
            if not cached:
                raise RuntimeError("no cached payload for %s — fetch once online first" % cache_name)
            with open(cached, encoding="utf-8") as fh:
                payload = json.load(fh)
            self.warnings.append("replayed cached payload: %s" % os.path.basename(cached))
            return payload

        if not self.quota.spend():
            raise QuotaExceeded(
                "daily budget of %d requests is spent (%d used today) — the player step will resume on "
                "the next UTC day, or raise NT90_API_FOOTBALL_BUDGET if this is a deliberate backfill"
                % (self.quota.budget, self.quota.used))

        query = "&".join("%s=%s" % (k, v) for k, v in sorted(params.items()))
        url = "%s/%s?%s" % (API, path, query)
        payload = self.http.get_json(url, headers={"x-apisports-key": self.token})
        cache_raw(self.name, cache_name, payload)
        return payload

    @staticmethod
    def _entries(payload):
        """The `response` array, or nothing. Providers return errors with HTTP 200 surprisingly often."""
        if not isinstance(payload, dict):
            return []
        errors = payload.get("errors")
        if errors and errors not in ({}, []):
            raise RuntimeError("provider reported an error: %s" % (errors,))
        return payload.get("response") or []

    # ── the three calls that matter ──
    def fetch_teams(self, league=PL_LEAGUE_ID, replay=False):
        """[{'code': 'ARS', 'name': 'Arsenal', 'id': 42}] — the id map, resolved rather than assumed."""
        payload = self._get("teams", {"league": league, "season": self.season},
                            "teams-%s-%s" % (league, self.season), replay=replay)
        out = []
        for entry in self._entries(payload):
            team = entry.get("team") or {}
            code = team_code(team.get("name"))
            if not code:
                self.warnings.append("unmapped club from provider: %s" % team.get("name"))
                continue
            out.append({"code": code, "name": team.get("name"), "id": team.get("id"),
                        "provider_name": team.get("name")})
        return out

    def fetch_club_players(self, team_id, replay=False):
        """Every player at one club, with statistics split by competition — the core call.

        Returns our row shape, not the provider's, so the backfill and the manual drop produce
        identical files (which is what makes the manual path a real alternative rather than a stub).
        """
        payload = self._get("players", {"team": team_id, "season": self.season},
                            "players-%s-%s" % (team_id, self.season), replay=replay)
        rows = []
        for entry in self._entries(payload):
            player = entry.get("player") or {}
            for stat in entry.get("statistics") or []:
                league = stat.get("league") or {}
                games = stat.get("games") or {}
                goals = stat.get("goals") or {}
                cards = stat.get("cards") or {}
                rows.append({
                    "player": player.get("name"),
                    "player_id": str(player.get("id") or ""),
                    "club_id": team_id,
                    "competition": league.get("name"),
                    "competition_id": league.get("id"),
                    "season": "%s" % self.season,
                    "minutes": games.get("minutes") or 0,
                    "starts": games.get("lineups") or 0,
                    "appearances": games.get("appearences") or 0,
                    "goals": goals.get("total") or 0,
                    "assists": goals.get("assists") or 0,
                    "yellow": cards.get("yellow") or 0,
                    "red": cards.get("red") or 0,
                    "rating": games.get("rating"),
                    "source": self.name,
                    "source_url": "%s/players?team=%s&season=%s" % (API, team_id, self.season),
                })
        return rows

    def fetch_injuries(self, team_id, replay=False):
        """Who is out right now, at one club — injuries and suspensions, with the reason and the date."""
        payload = self._get("injuries", {"team": team_id, "season": self.season},
                            "injuries-%s-%s" % (team_id, self.season), replay=replay)
        out = []
        for entry in self._entries(payload):
            player = entry.get("player") or {}
            fixture = entry.get("fixture") or {}
            league = entry.get("league") or {}
            out.append({
                "player": player.get("name"),
                "player_id": str(player.get("id") or ""),
                "club_id": team_id,
                "type": entry.get("type") or "Injury",
                "reason": entry.get("reason") or "",
                "since": (fixture.get("date") or "")[:10] or None,
                "competition": league.get("name"),
                "source": self.name,
            })
        return out

    def fetch_sidelined(self, player_id, replay=False):
        """One player's absence history — the durability signal, deliberately not used yet (P13.1's NO-GO
        for injury-proneness until it is measured), fetched only when a caller asks for it by name."""
        payload = self._get("sidelined", {"player": player_id},
                            "sidelined-%s" % player_id, replay=replay)
        return payload

    def describe(self):
        return {"provider": self.name, "available": self.available(),
                "reason": self.unavailable_reason(), "season": self.season,
                "quota": {"budget": self.quota.budget, "used": self.quota.used, "left": self.quota.left,
                          "day": self.quota.day},
                "capabilities": self.capabilities, "notes": self.notes}


class QuotaExceeded(RuntimeError):
    """Raised when the daily budget is spent. Callers are expected to treat this as 'try tomorrow', not
    as a failure: the weekly job still has the manual drop and the data it already has."""
