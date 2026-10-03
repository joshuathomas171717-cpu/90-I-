"""Local provider — the no-key path, and the manual update path.

It reads the same CSVs the pipeline already uses, so a weekly run works with zero accounts:

  * to record results by hand, edit `data/matches_2026_27_played.csv` and remove those fixtures from
    `data/fixtures_2026_27_remaining.csv`, then run `python3 update_week.py --source local`;
  * or drop a provider export in `data/provider_drop/` (any JSON with the normalised shape) and it
    will be picked up in preference to the CSVs.

It is also what `update_week.py --dry-run` exercises in tests: the whole chain — fetch, validate,
promote, rebuild, snapshot — runs end to end without a key or a network.
"""
import csv
import json
import os

from .base import BASE_DIR, DATA_DIR, Provider, SEASON_LABEL, team_code

DROP_DIR = os.path.join(DATA_DIR, "provider_drop")


class LocalSnapshotProvider(Provider):
    name = "local"
    needs_key = False
    capabilities = {"results": True, "table": True, "player_stats": True, "xg": False, "live": False}
    notes = ("Reads the pipeline's own CSVs, or a JSON export dropped in data/provider_drop/. "
             "This is the manual weekly path — no account, no rate limit, no network.")

    def available(self):
        return True

    def _drop_file(self):
        if not os.path.isdir(DROP_DIR):
            return None
        files = [f for f in sorted(os.listdir(DROP_DIR)) if f.endswith(".json")]
        return os.path.join(DROP_DIR, files[-1]) if files else None

    def fetch_results(self, season=SEASON_LABEL):
        drop = self._drop_file()
        if drop:
            with open(drop, encoding="utf-8") as fh:
                payload = json.load(fh)
            self.warnings.append("results read from data/provider_drop/%s" % os.path.basename(drop))
            return [self._normalise(r) for r in payload.get("results", payload.get("matches", []))]

        path = os.path.join(DATA_DIR, "matches_2026_27_played.csv")
        out = []
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                out.append({
                    "date": None,                      # the played CSV has gameweeks, not dates
                    "matchweek": int(row["gw"]),
                    "home": row["home"], "away": row["away"],
                    "home_goals": int(row["home_goals"]), "away_goals": int(row["away_goals"]),
                    "source_id": None, "source": "local:matches_2026_27_played.csv",
                })
        self.warnings.append("results read from the local played-match CSV (%d matches)" % len(out))
        return out

    def fetch_table(self, season=SEASON_LABEL):
        drop = self._drop_file()
        if drop:
            with open(drop, encoding="utf-8") as fh:
                payload = json.load(fh)
            if payload.get("table"):
                return [self._normalise_table(r) for r in payload["table"]]
        path = os.path.join(DATA_DIR, "teams_2026_27.csv")
        out = []
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                out.append({
                    "code": row["code"], "position": int(row["current_pos"]), "played": int(row["P"]),
                    "won": int(row["W"]), "drawn": int(row["D"]), "lost": int(row["L"]),
                    "gf": int(row["GF"]), "ga": int(row["GA"]), "gd": int(row["GD"]),
                    "points": int(row["Pts"]), "form": row.get("form", ""),
                })
        return out

    def fetch_player_stats(self, season=SEASON_LABEL):
        path = os.path.join(DATA_DIR, "players_2026_27.csv")
        goals, assists, clean_sheets = [], [], []
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                base = {"name": row["name"], "code": row["club"], "source_id": row["player_id"]}
                goals.append({**base, "stat": "goals", "value": int(float(row["goals_curr"] or 0))})
                assists.append({**base, "stat": "assists", "value": int(float(row["assists_curr"] or 0))})
                if row.get("pos") == "GK" and (row.get("cs_curr") or "").strip() not in ("", "None"):
                    clean_sheets.append({**base, "stat": "clean_sheets", "value": int(float(row["cs_curr"]))})
        return {"goals": goals, "assists": assists, "clean_sheets": clean_sheets}

    # ── normalisation of a dropped export ──
    def _normalise(self, r):
        return {
            "date": r.get("date"),
            "matchweek": r.get("matchweek") or r.get("gw"),
            "home": team_code(r.get("home")) or r.get("home"),
            "away": team_code(r.get("away")) or r.get("away"),
            "home_goals": int(r["home_goals"]), "away_goals": int(r["away_goals"]),
            "source_id": r.get("source_id"), "source": "local:provider_drop",
        }

    def _normalise_table(self, r):
        return {
            "code": team_code(r.get("team") or r.get("code")) or r.get("code"),
            "position": r.get("position"), "played": r.get("played"), "won": r.get("won"),
            "drawn": r.get("drawn", r.get("draw")), "lost": r.get("lost"),
            "gf": r.get("gf", r.get("goalsFor")), "ga": r.get("ga", r.get("goalsAgainst")),
            "gd": r.get("gd"), "points": r.get("points"), "form": r.get("form", ""),
        }
