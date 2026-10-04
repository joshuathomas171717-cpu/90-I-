"""football-data.org v4 provider — the recommended live source (see docs/data-sources.md).

Free tier: 10 requests/minute, competition code `PL`, current-season fixtures, results, standings and
top scorers. No xG — the model keeps its own ratings there, which is exactly the trade documented in
docs/xg-strategy.md.

Set the key and it works:

    export FOOTBALL_DATA_ORG_TOKEN=xxxxxxxx
    python3 update_week.py --source football-data.org

Without a key `available()` is False and `get_provider()` falls back to the local provider, so nothing
in the pipeline breaks.
"""
import os
import time

from .base import (HttpClient, Provider, SEASON_LABEL, SEASON_YEAR, cache_raw, latest_raw, team_code)

API = "https://api.football-data.org/v4"
COMPETITION = "PL"


class FootballDataOrgProvider(Provider):
    name = "football-data.org"
    needs_key = True
    capabilities = {"results": True, "table": True, "player_stats": True, "xg": False, "live": False}
    notes = ("10 req/min free, non-commercial use. Fixtures, results, standings and top scorers. "
             "No xG/xA — the engine keeps its own ratings (docs/xg-strategy.md).")

    def __init__(self, token=None, offline=False):
        super().__init__(offline=offline)
        self.token = token or os.environ.get("FOOTBALL_DATA_ORG_TOKEN") or os.environ.get("FOOTBALL_DATA_API_KEY")
        self.http = HttpClient(per_minute=10)

    # ── availability ──
    def available(self):
        return bool(self.token) and not self.offline

    def unavailable_reason(self):
        if self.offline:
            return "offline mode (replaying cached payloads only)"
        if not self.token:
            return ("no API key — set FOOTBALL_DATA_ORG_TOKEN, or register free at "
                    "https://www.football-data.org/client/register (10 req/min)")
        return None

    # ── transport ──
    def _get(self, path, cache_name, replay=False):
        """GET with the raw payload cached first. `replay` reads the newest cached copy instead."""
        if replay or self.offline:
            cached = latest_raw(self.name, cache_name)
            if not cached:
                raise RuntimeError("no cached payload for %s — run once online first" % cache_name)
            import json
            with open(cached, encoding="utf-8") as fh:
                payload = json.load(fh)
            self.warnings.append("replayed cached payload: %s" % os.path.basename(cached))
            return payload
        payload = self.http.get_json("%s/%s" % (API, path), headers={"X-Auth-Token": self.token})
        cache_raw(self.name, cache_name, payload)
        return payload

    @staticmethod
    def _season(season):
        # "2026-27" -> 2026; an explicit year is passed straight through
        return SEASON_YEAR if str(season).startswith("2026") else str(season)

    # ── the interface ──
    def fetch_calendar(self, competition="PL", season=SEASON_LABEL):
        """Exact PL/UCL schedule for rest calculations. Unknown foreign opponents need no club-code guess."""
        import datetime as dt
        if competition not in ("PL", "CL"):
            raise ValueError("only the free PL and CL competition calendars are supported")
        payload = self._get("competitions/%s/matches?season=%s" % (competition, self._season(season)),
                            "calendar-%s-%s" % (competition, self._season(season)))
        fetched = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        events = []
        for match in payload.get("matches") or []:
            if not match.get("utcDate"):
                continue
            for side, other in (("homeTeam", "awayTeam"), ("awayTeam", "homeTeam")):
                club = team_code((match.get(side) or {}).get("tla")) or team_code((match.get(side) or {}).get("name"))
                if not club:
                    continue
                events.append({"fixture_id": str(match.get("id")), "club": club,
                               "opponent": (match.get(other) or {}).get("name"),
                               "competition": "Premier League" if competition == "PL" else "UEFA Champions League",
                               "kickoff": match["utcDate"], "status": match.get("status"),
                               "venue": "home" if side == "homeTeam" else "away",
                               "travel_km": 0 if side == "homeTeam" else None,
                               "minutes": 90, "known_at": fetched, "source": self.name})
        return events

    def fetch_results(self, season=SEASON_LABEL):
        payload = self._get("competitions/%s/matches?season=%s&status=FINISHED" % (COMPETITION, self._season(season)),
                            "matches-finished")
        out, unknown = [], []
        for m in payload.get("matches", []):
            # a stale TLA must not sink a club whose name we do know
            home = team_code((m.get("homeTeam") or {}).get("tla")) or team_code((m.get("homeTeam") or {}).get("name"))
            away = team_code((m.get("awayTeam") or {}).get("tla")) or team_code((m.get("awayTeam") or {}).get("name"))
            if not home or not away:
                unknown.append("%s v %s" % ((m.get("homeTeam") or {}).get("name"),
                                            (m.get("awayTeam") or {}).get("name")))
                continue
            full = ((m.get("score") or {}).get("fullTime") or {})
            if full.get("home") is None or full.get("away") is None:
                continue                                   # not actually finished (abandoned/postponed)
            out.append({
                "date": (m.get("utcDate") or "")[:10],
                "home": home, "away": away,
                "home_goals": int(full["home"]), "away_goals": int(full["away"]),
                "matchweek": m.get("matchday"),
                "source_id": str(m.get("id")),
                "source": self.name,
            })
        if unknown:
            self.warnings.append("skipped %d unknown club(s): %s" % (len(unknown), "; ".join(unknown[:4])))
        return sorted(out, key=lambda r: (r["date"], r["home"]))

    def fetch_table(self, season=SEASON_LABEL):
        payload = self._get("competitions/%s/standings?season=%s" % (COMPETITION, self._season(season)), "standings")
        blocks = payload.get("standings", [])
        table = next((b.get("table", []) for b in blocks if b.get("type") == "TOTAL"), [])
        out = []
        for row in table:
            code = team_code((row.get("team") or {}).get("tla")) or team_code((row.get("team") or {}).get("name"))
            if not code:
                self.warnings.append("standings: unknown club %r" % (row.get("team") or {}).get("name"))
                continue
            out.append({
                "code": code, "position": row.get("position"), "played": row.get("playedGames"),
                "won": row.get("won"), "drawn": row.get("draw"), "lost": row.get("lost"),
                "gf": row.get("goalsFor"), "ga": row.get("goalsAgainst"), "gd": row.get("goalDifference"),
                "points": row.get("points"), "form": (row.get("form") or "").replace(",", ""),
            })
        return out

    def fetch_player_stats(self, season=SEASON_LABEL):
        """Scorers endpoint carries goals + assists. Clean sheets are NOT here (no xG, no keeper data):
        they are derived from results instead — see derive_clean_sheets() in update_week.py."""
        payload = self._get("competitions/%s/scorers?season=%s&limit=100" % (COMPETITION, self._season(season)), "scorers")
        goals, assists = [], []
        for s in payload.get("scorers", []):
            player = s.get("player") or {}
            code = team_code((s.get("team") or {}).get("tla")) or team_code((s.get("team") or {}).get("name"))
            base = {"name": player.get("name"), "code": code, "source_id": str(player.get("id"))}
            goals.append({**base, "stat": "goals", "value": s.get("goals") or 0})
            assists.append({**base, "stat": "assists", "value": s.get("assists") or 0})
        return {"goals": goals, "assists": assists}


def fetch_with_retry(provider, call, attempts=3):
    """Convenience for the weekly job: a flaky network should not fail a whole weekly run."""
    last = None
    for i in range(attempts):
        try:
            return call()
        except Exception as exc:                                   # noqa: BLE001 - reported, then retried
            last = exc
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("provider %s failed after %d attempts: %s" % (provider.name, attempts, last))
