import os
import json
import numpy as np
import pandas as pd

from dataset_io import write_dataset   # the same CSV dialect the weekly job writes

# Paths resolve relative to this file, never to an absolute location — the pipeline must run
# from any directory, on any machine, under any username. See tests/test_portability.py.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 1. Exact 2026-27 Premier League Clubs (20 teams) + 3 relegated 2025-26 clubs for historical training
TEAMS_META = {
    "MCI": {
        "name": "Manchester City", "short": "Man City", "manager": "Enzo Maresca",
        "stadium": "Etihad Stadium", "capacity": 61038, "europe": "UCL",
        "promoted": 0, "prev_pos": 2, "prev_pts": 78, "prev_gf": 77, "prev_ga": 35,
        "squad_value_m": 1280, "elo_base": 1952, "xg_90_base": 2.25, "xga_90_base": 0.90,
        "set_piece_xg": 0.36, "ppda": 8.6, "home_adv": 0.28, "primary_color": "#6CABDD"
    },
    "ARS": {
        "name": "Arsenal", "short": "Arsenal", "manager": "Mikel Arteta",
        "stadium": "Emirates Stadium", "capacity": 60704, "europe": "UCL",
        "promoted": 0, "prev_pos": 1, "prev_pts": 85, "prev_gf": 71, "prev_ga": 27,
        "squad_value_m": 1250, "elo_base": 1960, "xg_90_base": 2.14, "xga_90_base": 0.76,
        "set_piece_xg": 0.48, "ppda": 8.4, "home_adv": 0.30, "primary_color": "#EF0107"
    },
    "LIV": {
        "name": "Liverpool", "short": "Liverpool", "manager": "Andoni Iraola",
        "stadium": "Anfield", "capacity": 61276, "europe": "UCL",
        "promoted": 0, "prev_pos": 5, "prev_pts": 60, "prev_gf": 63, "prev_ga": 53,
        "squad_value_m": 1060, "elo_base": 1868, "xg_90_base": 1.95, "xga_90_base": 1.10,
        "set_piece_xg": 0.35, "ppda": 8.8, "home_adv": 0.31, "primary_color": "#C8102E"
    },
    "BHA": {
        "name": "Brighton & Hove Albion", "short": "Brighton", "manager": "Fabian Hürzeler",
        "stadium": "Amex Stadium", "capacity": 32176, "europe": "UECL",
        "promoted": 0, "prev_pos": 8, "prev_pts": 53, "prev_gf": 52, "prev_ga": 46,
        "squad_value_m": 640, "elo_base": 1805, "xg_90_base": 1.84, "xga_90_base": 1.16,
        "set_piece_xg": 0.31, "ppda": 9.4, "home_adv": 0.23, "primary_color": "#0057B8"
    },
    "CHE": {
        "name": "Chelsea", "short": "Chelsea", "manager": "Xabi Alonso",
        "stadium": "Stamford Bridge", "capacity": 40044, "europe": "None",
        "promoted": 0, "prev_pos": 10, "prev_pts": 52, "prev_gf": 58, "prev_ga": 52,
        "squad_value_m": 1090, "elo_base": 1815, "xg_90_base": 1.88, "xga_90_base": 1.32,
        "set_piece_xg": 0.29, "ppda": 9.1, "home_adv": 0.25, "primary_color": "#034694"
    },
    "MUN": {
        "name": "Manchester United", "short": "Man Utd", "manager": "Michael Carrick",
        "stadium": "Old Trafford", "capacity": 74158, "europe": "UCL",
        "promoted": 0, "prev_pos": 3, "prev_pts": 71, "prev_gf": 69, "prev_ga": 50,
        "squad_value_m": 920, "elo_base": 1820, "xg_90_base": 1.75, "xga_90_base": 1.26,
        "set_piece_xg": 0.28, "ppda": 10.3, "home_adv": 0.26, "primary_color": "#DA291C"
    },
    "NEW": {
        "name": "Newcastle United", "short": "Newcastle", "manager": "Matthias Jaissle",
        "stadium": "St James' Park", "capacity": 52729, "europe": "None",
        "promoted": 0, "prev_pos": 12, "prev_pts": 49, "prev_gf": 53, "prev_ga": 55,
        "squad_value_m": 710, "elo_base": 1780, "xg_90_base": 1.68, "xga_90_base": 1.30,
        "set_piece_xg": 0.33, "ppda": 9.8, "home_adv": 0.29, "primary_color": "#241F20"
    },
    "BRE": {
        "name": "Brentford", "short": "Brentford", "manager": "Keith Andrews",
        "stadium": "Gtech Community Stadium", "capacity": 17250, "europe": "None",
        "promoted": 0, "prev_pos": 9, "prev_pts": 53, "prev_gf": 55, "prev_ga": 52,
        "squad_value_m": 460, "elo_base": 1770, "xg_90_base": 1.62, "xga_90_base": 1.24,
        "set_piece_xg": 0.42, "ppda": 11.2, "home_adv": 0.23, "primary_color": "#E30613"
    },
    "AVL": {
        "name": "Aston Villa", "short": "Aston Villa", "manager": "Unai Emery",
        "stadium": "Villa Park", "capacity": 36887, "europe": "UCL",
        "promoted": 0, "prev_pos": 4, "prev_pts": 65, "prev_gf": 56, "prev_ga": 49,
        "squad_value_m": 690, "elo_base": 1782, "xg_90_base": 1.58, "xga_90_base": 1.30,
        "set_piece_xg": 0.34, "ppda": 10.6, "home_adv": 0.25, "primary_color": "#670E36"
    },
    "EVE": {
        "name": "Everton", "short": "Everton", "manager": "David Moyes",
        "stadium": "Hill Dickinson Stadium", "capacity": 52769, "europe": "None",
        "promoted": 0, "prev_pos": 13, "prev_pts": 49, "prev_gf": 47, "prev_ga": 50,
        "squad_value_m": 430, "elo_base": 1752, "xg_90_base": 1.40, "xga_90_base": 1.15,
        "set_piece_xg": 0.39, "ppda": 11.8, "home_adv": 0.27, "primary_color": "#003399"
    },
    "LEE": {
        "name": "Leeds United", "short": "Leeds", "manager": "Daniel Farke",
        "stadium": "Elland Road", "capacity": 37633, "europe": "None",
        "promoted": 0, "prev_pos": 14, "prev_pts": 47, "prev_gf": 49, "prev_ga": 56,
        "squad_value_m": 395, "elo_base": 1742, "xg_90_base": 1.48, "xga_90_base": 1.24,
        "set_piece_xg": 0.30, "ppda": 9.9, "home_adv": 0.27, "primary_color": "#FFCD00"
    },
    "BOU": {
        "name": "Bournemouth", "short": "Bournemouth", "manager": "Marco Rose",
        "stadium": "Vitality Stadium", "capacity": 12357, "europe": "UEL",
        "promoted": 0, "prev_pos": 6, "prev_pts": 57, "prev_gf": 58, "prev_ga": 54,
        "squad_value_m": 440, "elo_base": 1738, "xg_90_base": 1.48, "xga_90_base": 1.36,
        "set_piece_xg": 0.29, "ppda": 9.5, "home_adv": 0.19, "primary_color": "#DA291C"
    },
    "TOT": {
        "name": "Tottenham Hotspur", "short": "Tottenham", "manager": "Roberto De Zerbi",
        "stadium": "Tottenham Hotspur Stadium", "capacity": 62850, "europe": "None",
        "promoted": 0, "prev_pos": 17, "prev_pts": 41, "prev_gf": 48, "prev_ga": 57,
        "squad_value_m": 780, "elo_base": 1732, "xg_90_base": 1.50, "xga_90_base": 1.42,
        "set_piece_xg": 0.26, "ppda": 9.2, "home_adv": 0.24, "primary_color": "#132257"
    },
    "NFO": {
        "name": "Nottingham Forest", "short": "Nott'm Forest", "manager": "Oliver Glasner",
        "stadium": "City Ground", "capacity": 31212, "europe": "None",
        "promoted": 0, "prev_pos": 16, "prev_pts": 44, "prev_gf": 48, "prev_ga": 51,
        "squad_value_m": 450, "elo_base": 1722, "xg_90_base": 1.35, "xga_90_base": 1.28,
        "set_piece_xg": 0.32, "ppda": 11.4, "home_adv": 0.24, "primary_color": "#DD0000"
    },
    "FUL": {
        "name": "Fulham", "short": "Fulham", "manager": "Álvaro Arbeloa",
        "stadium": "Craven Cottage", "capacity": 28107, "europe": "None",
        "promoted": 0, "prev_pos": 11, "prev_pts": 52, "prev_gf": 47, "prev_ga": 51,
        "squad_value_m": 390, "elo_base": 1712, "xg_90_base": 1.32, "xga_90_base": 1.38,
        "set_piece_xg": 0.28, "ppda": 10.9, "home_adv": 0.21, "primary_color": "#000000"
    },
    "CRY": {
        "name": "Crystal Palace", "short": "Crystal Palace", "manager": "Pierre Sage",
        "stadium": "Selhurst Park", "capacity": 25194, "europe": "UEL",
        "promoted": 0, "prev_pos": 15, "prev_pts": 45, "prev_gf": 41, "prev_ga": 51,
        "squad_value_m": 420, "elo_base": 1708, "xg_90_base": 1.29, "xga_90_base": 1.42,
        "set_piece_xg": 0.31, "ppda": 11.3, "home_adv": 0.23, "primary_color": "#1B458F"
    },
    "SUN": {
        "name": "Sunderland", "short": "Sunderland", "manager": "Régis Le Bris",
        "stadium": "Stadium of Light", "capacity": 48095, "europe": "UEL",
        "promoted": 0, "prev_pos": 7, "prev_pts": 54, "prev_gf": 42, "prev_ga": 48,
        "squad_value_m": 340, "elo_base": 1702, "xg_90_base": 1.26, "xga_90_base": 1.44,
        "set_piece_xg": 0.27, "ppda": 11.5, "home_adv": 0.25, "primary_color": "#EB172B"
    },
    "HUL": {
        "name": "Hull City", "short": "Hull City", "manager": "Sergej Jakirović",
        "stadium": "MKM Stadium", "capacity": 24983, "europe": "None",
        "promoted": 1, "prev_pos": 20, "prev_pts": 38, "prev_gf": 38, "prev_ga": 60,
        "squad_value_m": 245, "elo_base": 1672, "xg_90_base": 1.18, "xga_90_base": 1.46,
        "set_piece_xg": 0.27, "ppda": 12.1, "home_adv": 0.21, "primary_color": "#F5A12D"
    },
    "IPS": {
        "name": "Ipswich Town", "short": "Ipswich", "manager": "Gary O'Neil",
        "stadium": "Portman Road", "capacity": 30056, "europe": "None",
        "promoted": 1, "prev_pos": 19, "prev_pts": 40, "prev_gf": 40, "prev_ga": 58,
        "squad_value_m": 265, "elo_base": 1662, "xg_90_base": 1.20, "xga_90_base": 1.56,
        "set_piece_xg": 0.28, "ppda": 11.9, "home_adv": 0.22, "primary_color": "#3A64A3"
    },
    "COV": {
        "name": "Coventry City", "short": "Coventry", "manager": "Frank Lampard",
        "stadium": "CBS Arena", "capacity": 32609, "europe": "None",
        "promoted": 1, "prev_pos": 18, "prev_pts": 42, "prev_gf": 41, "prev_ga": 56,
        "squad_value_m": 230, "elo_base": 1638, "xg_90_base": 1.04, "xga_90_base": 1.64,
        "set_piece_xg": 0.25, "ppda": 12.4, "home_adv": 0.20, "primary_color": "#0593D3"
    }
}

# Relegated 2025-26 teams (used for 2025-26 historical training set)
RELEGATED_2025_26 = {
    "WHU": {"name": "West Ham United", "elo_base": 1680, "xg_90_base": 1.22, "xga_90_base": 1.62, "squad_value_m": 410, "set_piece_xg": 0.30, "ppda": 12.0, "home_adv": 0.21, "europe": "None", "promoted": 0},
    "BUR": {"name": "Burnley", "elo_base": 1615, "xg_90_base": 1.02, "xga_90_base": 1.82, "squad_value_m": 240, "set_piece_xg": 0.24, "ppda": 12.6, "home_adv": 0.19, "europe": "None", "promoted": 1},
    "WOL": {"name": "Wolverhampton Wanderers", "elo_base": 1605, "xg_90_base": 0.94, "xga_90_base": 1.76, "squad_value_m": 330, "set_piece_xg": 0.23, "ppda": 12.5, "home_adv": 0.20, "europe": "None", "promoted": 0},
}

ALL_TEAMS_HIST = {**TEAMS_META, **RELEGATED_2025_26}

# 2. Exact 2025-26 Premier League Results Matrix (All 380 matches!)
TEAMS_25_26_ORDER = [
    "ARS", "AVL", "BOU", "BRE", "BHA", "BUR", "CHE", "CRY", "EVE", "FUL",
    "LEE", "LIV", "MCI", "MUN", "NEW", "NFO", "SUN", "TOT", "WHU", "WOL"
]

MATRIX_2025_26 = {
    "ARS": [None,"4-1","1-2","2-0","2-1","1-0","2-1","1-0","2-0","3-0","5-0","0-0","1-1","2-3","1-0","3-0","3-0","4-1","2-0","2-1"],
    "AVL": ["2-1",None,"4-0","0-1","1-0","2-1","1-4","0-3","0-1","3-1","1-1","4-2","1-0","2-1","0-0","3-1","4-3","1-2","2-0","1-0"],
    "BOU": ["2-3","1-1",None,"0-0","2-1","1-1","0-0","3-0","0-1","3-1","2-2","3-2","1-1","2-2","0-0","2-0","1-1","3-2","2-2","1-0"],
    "BRE": ["1-1","1-0","4-1",None,"0-2","3-1","2-2","2-2","2-2","0-0","1-1","3-2","0-1","3-1","3-1","0-2","3-0","0-0","3-0","2-2"],
    "BHA": ["0-1","3-4","1-1","2-1",None,"2-0","3-0","0-1","1-1","1-1","3-0","2-1","2-1","0-3","2-1","2-1","0-0","2-2","1-1","3-0"],
    "BUR": ["0-2","2-2","0-0","3-4","0-2",None,"0-2","0-1","0-0","2-3","2-0","0-1","0-1","2-2","1-3","1-1","2-0","2-2","0-2","1-1"],
    "CHE": ["1-1","1-2","2-2","2-0","1-3","1-1",None,"0-0","2-0","2-0","2-2","2-1","0-3","0-1","0-1","1-3","1-2","2-1","3-2","3-0"],
    "CRY": ["1-2","0-0","3-3","2-0","0-0","2-3","1-3",None,"2-2","1-1","0-0","2-1","0-3","1-2","2-1","1-1","0-0","0-1","0-0","1-0"],
    "EVE": ["0-1","0-0","1-2","2-4","2-0","2-0","3-0","2-1",None,"2-0","1-1","1-2","3-3","0-1","1-4","3-0","1-3","0-3","1-1","1-1"],
    "FUL": ["0-1","1-0","0-1","3-1","2-1","3-1","2-1","1-2","1-2",None,"1-0","2-2","4-5","1-1","2-0","1-0","1-0","2-1","0-1","3-0"],
    "LEE": ["0-4","1-2","2-2","0-0","1-0","3-1","3-1","4-1","1-0","1-0",None,"3-3","0-1","1-1","0-0","3-1","0-1","1-2","2-1","3-0"],
    "LIV": ["1-0","2-0","4-2","1-1","2-0","1-1","1-1","3-1","2-1","2-0","0-0",None,"1-2","1-2","4-1","0-3","1-1","1-1","5-2","2-1"],
    "MCI": ["2-1","1-2","3-1","3-0","1-1","5-1","1-1","3-0","2-0","3-0","3-2","3-0",None,"3-0","2-1","2-2","3-0","0-2","3-0","2-0"],
    "MUN": ["0-1","3-1","4-4","2-1","4-2","3-2","2-1","2-1","0-1","3-2","1-2","3-2","2-0",None,"1-0","3-2","2-0","2-0","1-1","1-1"],
    "NEW": ["1-2","0-2","1-2","2-3","3-1","2-1","2-2","2-0","2-3","2-1","4-3","2-3","2-1","2-1",None,"2-0","1-2","2-2","3-1","1-0"],
    "NFO": ["0-0","1-1","1-1","3-1","0-2","4-1","0-3","1-1","0-2","0-0","3-1","0-1","1-2","2-2","1-1",None,"0-1","3-0","0-3","0-0"],
    "SUN": ["2-2","1-1","3-2","2-1","0-1","3-0","2-1","2-1","1-1","1-3","1-1","0-1","0-0","0-0","1-0","0-5",None,"1-0","3-0","2-0"],
    "TOT": ["1-4","1-2","0-1","2-0","2-2","3-0","0-1","1-3","1-0","1-2","1-1","1-2","2-2","2-2","1-2","0-3","1-1",None,"1-2","1-1"],
    "WHU": ["0-1","2-3","0-0","0-2","2-2","3-2","1-5","1-2","2-1","0-1","3-0","0-2","1-1","1-1","3-1","1-2","3-1","0-3",None,"4-0"],
    "WOL": ["2-2","2-0","0-2","0-2","1-1","2-3","1-3","0-2","2-3","1-1","1-3","2-1","0-4","1-4","0-0","0-1","1-1","0-1","3-0",None],
}

matches_25_26 = []
for h_code, row in MATRIX_2025_26.items():
    for idx, score in enumerate(row):
        if score is None:
            continue
        a_code = TEAMS_25_26_ORDER[idx]
        hg, ag = map(int, score.split("-"))
        matches_25_26.append({
            "season": "2025-26",
            "home": h_code,
            "away": a_code,
            "home_goals": hg,
            "away_goals": ag,
            "outcome": "H" if hg > ag else ("A" if hg < ag else "D")
        })

df_25_26 = pd.DataFrame(matches_25_26)
write_dataset(DATA_DIR, {"matches_2025_26.csv": (df_25_26.to_dict("records"), list(df_25_26.columns))})
print(f"Saved {len(df_25_26)} matches from 2025-26 PL.")

# 3. Exact 50 Played Matches of 2026-27 Premier League (GW1 - GW5)
PLAYED_2026_27 = [
    ("ARS", "CHE", 2, 1, 1), ("ARS", "COV", 3, 0, 3),
    ("AVL", "ARS", 0, 1, 2), ("AVL", "NFO", 1, 2, 4),
    ("BOU", "BRE", 2, 2, 1), ("BOU", "EVE", 1, 1, 2), ("BOU", "LIV", 0, 1, 4),
    ("BRE", "CHE", 3, 0, 2), ("BRE", "SUN", 1, 1, 3), ("BRE", "TOT", 3, 0, 5),
    ("BHA", "ARS", 3, 0, 4), ("BHA", "AVL", 4, 0, 1), ("BHA", "LEE", 1, 1, 3),
    ("CHE", "BHA", 4, 3, 5), ("CHE", "HUL", 2, 2, 3),
    ("COV", "BHA", 0, 5, 4), ("COV", "HUL", 0, 1, 2),
    ("CRY", "IPS", 2, 3, 2), ("CRY", "MCI", 1, 4, 3),
    ("EVE", "CRY", 2, 0, 1), ("EVE", "IPS", 1, 0, 4), ("EVE", "MUN", 2, 2, 5),
    ("FUL", "CHE", 2, 3, 4), ("FUL", "CRY", 2, 3, 5), ("FUL", "MUN", 1, 1, 2),
    ("HUL", "AVL", 0, 0, 5), ("HUL", "MUN", 2, 0, 1),
    ("IPS", "LIV", 0, 2, 1), ("IPS", "SUN", 2, 1, 5),
    ("LEE", "BRE", 1, 1, 4), ("LEE", "CRY", 0, 0, 5), ("LEE", "NEW", 4, 1, 1),
    ("LIV", "FUL", 0, 0, 3), ("LIV", "NFO", 2, 2, 2),
    ("MCI", "BOU", 2, 1, 1), ("MCI", "COV", 1, 0, 2), ("MCI", "SUN", 5, 3, 5),
    ("MUN", "IPS", 5, 2, 3), ("MUN", "MCI", 0, 1, 4),
    ("NEW", "BOU", 2, 2, 3), ("NEW", "HUL", 2, 1, 4), ("NEW", "LIV", 2, 2, 5),
    ("NFO", "COV", 0, 1, 1), ("NFO", "LEE", 0, 1, 2), ("NFO", "TOT", 0, 0, 3),
    ("SUN", "ARS", 0, 2, 5), ("SUN", "FUL", 1, 0, 1),
    ("TOT", "AVL", 2, 3, 3), ("TOT", "EVE", 0, 0, 4), ("TOT", "NEW", 0, 2, 2),
]

# ── P2.6 results feedback loop ───────────────────────────────────────────────
# The list above is the verified record for the matches played when this project was built. Anything
# beyond it — results promoted by update_week.py, or added by hand — lives on disk and must survive a
# rebuild. Before this, `data_builder.py` regenerated the file from the literal above and silently
# deleted promoted results on the next `run_all.py`; the weekly loop was therefore a no-op.
promoted_rows = []
_played_path = os.path.join(DATA_DIR, "matches_2026_27_played.csv")
_known_pairs = {(h, a) for h, a, _hg, _ag, _gw in PLAYED_2026_27}
if os.path.exists(_played_path):
    _previous = pd.read_csv(_played_path)
    _conflicts = []
    for _, _row in _previous.iterrows():
        _key = (_row["home"], _row["away"])
        if _key in _known_pairs:
            _internal = next(x for x in PLAYED_2026_27 if (x[0], x[1]) == _key)
            if (int(_row["home_goals"]), int(_row["away_goals"])) != (_internal[2], _internal[3]):
                _conflicts.append(f"{_key[0]} v {_key[1]}: file {int(_row['home_goals'])}-{int(_row['away_goals'])} "
                                  f"vs verified {_internal[2]}-{_internal[3]}")
            continue
        promoted_rows.append((_row["home"], _row["away"], int(_row["home_goals"]), int(_row["away_goals"]),
                              int(_row.get("gw") or 0)))
    if _conflicts:
        # A disagreement about a match we have verified is a data problem, not a merge problem.
        raise SystemExit("Promoted results disagree with the verified 2026-27 record:\n  "
                         + "\n  ".join(_conflicts)
                         + "\nRefusing to build. Check data/matches_2026_27_played.csv.")

_played_all = PLAYED_2026_27 + promoted_rows

played_rows = []
played_pairs = set()
for h, a, hg, ag, gw in _played_all:
    played_pairs.add((h, a))
    played_rows.append({
        "season": "2026-27",
        "gw": gw,
        "home": h,
        "away": a,
        "home_goals": hg,
        "away_goals": ag,
        "outcome": "H" if hg > ag else ("A" if hg < ag else "D")
    })

df_played = pd.DataFrame(played_rows).sort_values(["gw", "home"]).reset_index(drop=True)
write_dataset(DATA_DIR, {"matches_2026_27_played.csv": (df_played.to_dict("records"), list(df_played.columns))})
print(f"Saved {len(df_played)} played matches from 2026-27 PL"
      + (f" ({len(promoted_rows)} promoted by the weekly job)." if promoted_rows else "."))

# 4. Load the official 330 remaining fixtures of 2026-27 PL with real matchweeks and dates
from fixtures_official import FIXTURES_2026_27, validate_official_fixtures

report = validate_official_fixtures()
# The official module knows the five gameweeks that were complete when it was written; `played_pairs`
# also carries anything promoted since. Assert consistency rather than equality: every fixture we hold
# a result for must be part of the official 380, and the ones the module does not know about are new.
assert report["played"] + len(promoted_rows) == len(played_pairs), \
    "played fixtures disagree with the official calendar"

teams_26_27 = list(TEAMS_META.keys())
rem_rows = []
fixture_id = 0
for gw in sorted(FIXTURES_2026_27):
    dates, fx_list = FIXTURES_2026_27[gw]
    for h, a in fx_list:
        if (h, a) in played_pairs:
            continue            # promoted since the calendar was written: it is no longer "remaining"
        fixture_id += 1
        rem_rows.append({
            "fixture_id": fixture_id,
            "season": "2026-27",
            "gw": gw,
            "dates": dates,
            "home": h,
            "away": a
        })

df_rem = pd.DataFrame(rem_rows)
assert len(df_rem) == 330 - len(promoted_rows), \
    f"Expected {330 - len(promoted_rows)} remaining fixtures, got {len(df_rem)}"
assert not df_rem.duplicated(subset=["home", "away"]).any(), "duplicate remaining fixture"
assert set(zip(df_rem["home"], df_rem["away"])) == {
    (h, a) for h in teams_26_27 for a in teams_26_27 if h != a and (h, a) not in played_pairs
}, "remaining fixtures do not match the unplayed pairings"
write_dataset(DATA_DIR, {"fixtures_2026_27_remaining.csv": (df_rem.to_dict("records"), list(df_rem.columns))})
print(f"Saved {len(df_rem)} remaining fixtures (MW6-MW38, real dates) for 2026-27 PL"
      + (f" ({len(promoted_rows)} played since the calendar was released)." if promoted_rows else "."))

# 5. Build Team Current Table & Features Dataset
standings = {code: {"P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "GD": 0, "Pts": 0, "form": []} for code in TEAMS_META}
for h, a, hg, ag, gw in sorted(PLAYED_2026_27, key=lambda x: x[4]):
    standings[h]["P"] += 1
    standings[a]["P"] += 1
    standings[h]["GF"] += hg
    standings[h]["GA"] += ag
    standings[a]["GF"] += ag
    standings[a]["GA"] += hg
    if hg > ag:
        standings[h]["W"] += 1; standings[h]["Pts"] += 3; standings[a]["L"] += 1
        standings[h]["form"].append("W"); standings[a]["form"].append("L")
    elif hg < ag:
        standings[a]["W"] += 1; standings[a]["Pts"] += 3; standings[h]["L"] += 1
        standings[h]["form"].append("L"); standings[a]["form"].append("W")
    else:
        standings[h]["D"] += 1; standings[a]["D"] += 1
        standings[h]["Pts"] += 1; standings[a]["Pts"] += 1
        standings[h]["form"].append("D"); standings[a]["form"].append("D")

# ── the table, and the only two writers of it ────────────────────────────────
# The table and the Elo are recounted from the results by `standings.py` — the *same* function
# `update_week.py` calls. There is deliberately no second implementation here: the legacy heuristic
# that used to live in this file disagreed with the weekly job by up to 25 Elo points, so every
# promotion rewrote this CSV, changed the model's artifact-cache key and forced a full retrain from a
# no-op update.
from standings import recompute_standings

_results_for_table = [{"home": r["home"], "away": r["away"], "home_goals": r["home_goals"],
                       "away_goals": r["away_goals"], "gw": r["gw"]} for r in played_rows]
_seed_rows = [{"code": code, **meta, "elo_live": meta["elo_base"]} for code, meta in TEAMS_META.items()]
_recounted = {row["code"]: row for row in
              recompute_standings(_seed_rows, _results_for_table)}

team_rows = []
for code, meta in TEAMS_META.items():
    r = _recounted[code]
    games = max(1, int(r["P"]))
    # Live form blend: 85% base tactical rating + 15% actual scoring rate, taken from the table we are
    # about to publish (not from a hardcoded gameweek). xG itself is never moved by results — see
    # docs/xg-strategy.md; this is the goals-based form component of the blend and nothing more.
    curr_gf_90 = int(r["GF"]) / games
    curr_ga_90 = int(r["GA"]) / games
    team_rows.append({
        "code": code,
        **meta,
        "P": int(r["P"]), "W": int(r["W"]), "D": int(r["D"]), "L": int(r["L"]),
        "GF": int(r["GF"]), "GA": int(r["GA"]), "GD": int(r["GD"]), "Pts": int(r["Pts"]),
        "form": r["form"],
        # "%.2f", not round(): the weekly job writes this column through standings.py as a string, and
        # 3.0 != "3.00" in a byte comparison — which is the whole point of matching the job exactly.
        "ppg_current": "%.2f" % (int(r["Pts"]) / games),
        "xg_90_live": round(0.85 * meta["xg_90_base"] + 0.15 * curr_gf_90, 3),
        "xga_90_live": round(0.85 * meta["xga_90_base"] + 0.15 * curr_ga_90, 3),
        "elo_live": float(r["elo_live"]),
    })

df_teams = pd.DataFrame(team_rows).sort_values(["Pts", "GD", "GF"], ascending=False).reset_index(drop=True)
df_teams["current_pos"] = df_teams.index + 1
print(f"Table recounted from {len(played_rows)} results by standings.py "
      f"(Elo walked from the base ratings{', including promoted results' if promoted_rows else ''}).")
write_dataset(DATA_DIR, {"teams_2026_27.csv": (df_teams.to_dict("records"), list(df_teams.columns))})
print(f"Saved {len(df_teams)} teams to teams_2026_27.csv.")

# 6. Build Comprehensive Player Dataset (Scorers, Assisters, Goalkeepers)
PLAYERS_DATA = [
    # Forwards & Attacking Midfielders / Wingers (Golden Boot & Playmaker Contenders)
    {"player_id": "haaland", "name": "Erling Haaland", "club": "MCI", "pos": "FWD", "nation": "NOR", "goals_curr": 5, "assists_curr": 1, "cs_curr": 0, "mins_curr": 450, "goals_prev": 27, "assists_prev": 5, "xg_90": 0.88, "xa_90": 0.14, "pen_share": 0.90, "shot_conv": 0.25, "kp_90": 1.1, "mins_prob": 0.92},
    {"player_id": "isak", "name": "Alexander Isak", "club": "LIV", "pos": "FWD", "nation": "SWE", "goals_curr": 4, "assists_curr": 1, "cs_curr": 0, "mins_curr": 415, "goals_prev": 19, "assists_prev": 5, "xg_90": 0.68, "xa_90": 0.16, "pen_share": 0.75, "shot_conv": 0.23, "kp_90": 1.4, "mins_prob": 0.86},
    {"player_id": "saka", "name": "Bukayo Saka", "club": "ARS", "pos": "FWD", "nation": "ENG", "goals_curr": 3, "assists_curr": 2, "cs_curr": 0, "mins_curr": 419, "goals_prev": 16, "assists_prev": 14, "xg_90": 0.52, "xa_90": 0.38, "pen_share": 0.80, "shot_conv": 0.19, "kp_90": 2.7, "mins_prob": 0.91},
    {"player_id": "joao_pedro", "name": "João Pedro", "club": "CHE", "pos": "FWD", "nation": "BRA", "goals_curr": 3, "assists_curr": 3, "cs_curr": 0, "mins_curr": 360, "goals_prev": 15, "assists_prev": 7, "xg_90": 0.54, "xa_90": 0.26, "pen_share": 0.45, "shot_conv": 0.20, "kp_90": 1.9, "mins_prob": 0.85},
    {"player_id": "palmer", "name": "Cole Palmer", "club": "CHE", "pos": "MID", "nation": "ENG", "goals_curr": 2, "assists_curr": 2, "cs_curr": 0, "mins_curr": 443, "goals_prev": 16, "assists_prev": 12, "xg_90": 0.50, "xa_90": 0.36, "pen_share": 0.55, "shot_conv": 0.18, "kp_90": 2.6, "mins_prob": 0.92},
    {"player_id": "gyokeres", "name": "Viktor Gyökeres", "club": "ARS", "pos": "FWD", "nation": "SWE", "goals_curr": 2, "assists_curr": 1, "cs_curr": 0, "mins_curr": 390, "goals_prev": 14, "assists_prev": 6, "xg_90": 0.58, "xa_90": 0.18, "pen_share": 0.20, "shot_conv": 0.21, "kp_90": 1.3, "mins_prob": 0.84},
    {"player_id": "bruno", "name": "Bruno Fernandes", "club": "MUN", "pos": "MID", "nation": "POR", "goals_curr": 3, "assists_curr": 1, "cs_curr": 0, "mins_curr": 450, "goals_prev": 13, "assists_prev": 14, "xg_90": 0.42, "xa_90": 0.39, "pen_share": 0.85, "shot_conv": 0.16, "kp_90": 3.1, "mins_prob": 0.95},
    {"player_id": "cherki", "name": "Rayan Cherki", "club": "MCI", "pos": "MID", "nation": "FRA", "goals_curr": 3, "assists_curr": 2, "cs_curr": 0, "mins_curr": 306, "goals_prev": 10, "assists_prev": 11, "xg_90": 0.38, "xa_90": 0.41, "pen_share": 0.05, "shot_conv": 0.18, "kp_90": 2.9, "mins_prob": 0.80},
    {"player_id": "semenyo", "name": "Antoine Semenyo", "club": "MCI", "pos": "FWD", "nation": "GHA", "goals_curr": 2, "assists_curr": 3, "cs_curr": 0, "mins_curr": 450, "goals_prev": 17, "assists_prev": 8, "xg_90": 0.46, "xa_90": 0.31, "pen_share": 0.05, "shot_conv": 0.19, "kp_90": 2.1, "mins_prob": 0.86},
    {"player_id": "gross", "name": "Pascal Groß", "club": "BHA", "pos": "MID", "nation": "GER", "goals_curr": 3, "assists_curr": 3, "cs_curr": 0, "mins_curr": 450, "goals_prev": 8, "assists_prev": 12, "xg_90": 0.32, "xa_90": 0.38, "pen_share": 0.65, "shot_conv": 0.17, "kp_90": 3.0, "mins_prob": 0.90},
    {"player_id": "dcl", "name": "Dominic Calvert-Lewin", "club": "LEE", "pos": "FWD", "nation": "ENG", "goals_curr": 3, "assists_curr": 1, "cs_curr": 0, "mins_curr": 421, "goals_prev": 14, "assists_prev": 4, "xg_90": 0.51, "xa_90": 0.11, "pen_share": 0.75, "shot_conv": 0.19, "kp_90": 0.9, "mins_prob": 0.84},
    {"player_id": "rogers", "name": "Morgan Rogers", "club": "CHE", "pos": "MID", "nation": "ENG", "goals_curr": 3, "assists_curr": 1, "cs_curr": 0, "mins_curr": 439, "goals_prev": 11, "assists_prev": 9, "xg_90": 0.39, "xa_90": 0.25, "pen_share": 0.0, "shot_conv": 0.18, "kp_90": 1.9, "mins_prob": 0.88},
    {"player_id": "schade", "name": "Kevin Schade", "club": "BRE", "pos": "FWD", "nation": "GER", "goals_curr": 3, "assists_curr": 1, "cs_curr": 0, "mins_curr": 448, "goals_prev": 12, "assists_prev": 6, "xg_90": 0.45, "xa_90": 0.19, "pen_share": 0.20, "shot_conv": 0.20, "kp_90": 1.4, "mins_prob": 0.88},
    {"player_id": "igor_thiago", "name": "Igor Thiago", "club": "BRE", "pos": "FWD", "nation": "BRA", "goals_curr": 2, "assists_curr": 1, "cs_curr": 0, "mins_curr": 410, "goals_prev": 22, "assists_prev": 4, "xg_90": 0.56, "xa_90": 0.13, "pen_share": 0.75, "shot_conv": 0.21, "kp_90": 1.0, "mins_prob": 0.87},
    {"player_id": "watkins", "name": "Ollie Watkins", "club": "AVL", "pos": "FWD", "nation": "ENG", "goals_curr": 2, "assists_curr": 1, "cs_curr": 0, "mins_curr": 435, "goals_prev": 16, "assists_prev": 8, "xg_90": 0.52, "xa_90": 0.20, "pen_share": 0.50, "shot_conv": 0.19, "kp_90": 1.5, "mins_prob": 0.90},
    {"player_id": "brobbey", "name": "Brian Brobbey", "club": "SUN", "pos": "FWD", "nation": "NED", "goals_curr": 3, "assists_curr": 0, "cs_curr": 0, "mins_curr": 401, "goals_prev": 11, "assists_prev": 3, "xg_90": 0.44, "xa_90": 0.10, "pen_share": 0.60, "shot_conv": 0.18, "kp_90": 0.9, "mins_prob": 0.84},
    {"player_id": "tavernier", "name": "Marcus Tavernier", "club": "BOU", "pos": "MID", "nation": "ENG", "goals_curr": 3, "assists_curr": 1, "cs_curr": 0, "mins_curr": 427, "goals_prev": 8, "assists_prev": 7, "xg_90": 0.31, "xa_90": 0.22, "pen_share": 0.15, "shot_conv": 0.16, "kp_90": 1.8, "mins_prob": 0.88},
    {"player_id": "gakpo", "name": "Cody Gakpo", "club": "LIV", "pos": "FWD", "nation": "NED", "goals_curr": 1, "assists_curr": 3, "cs_curr": 0, "mins_curr": 410, "goals_prev": 12, "assists_prev": 9, "xg_90": 0.41, "xa_90": 0.30, "pen_share": 0.10, "shot_conv": 0.17, "kp_90": 2.2, "mins_prob": 0.85},
    {"player_id": "wirtz", "name": "Florian Wirtz", "club": "LIV", "pos": "MID", "nation": "GER", "goals_curr": 1, "assists_curr": 1, "cs_curr": 0, "mins_curr": 420, "goals_prev": 11, "assists_prev": 13, "xg_90": 0.36, "xa_90": 0.37, "pen_share": 0.10, "shot_conv": 0.17, "kp_90": 2.8, "mins_prob": 0.88},
    {"player_id": "odegaard", "name": "Martin Ødegaard", "club": "ARS", "pos": "MID", "nation": "NOR", "goals_curr": 2, "assists_curr": 1, "cs_curr": 0, "mins_curr": 382, "goals_prev": 10, "assists_prev": 12, "xg_90": 0.31, "xa_90": 0.36, "pen_share": 0.15, "shot_conv": 0.16, "kp_90": 2.9, "mins_prob": 0.89},
    {"player_id": "havertz", "name": "Kai Havertz", "club": "ARS", "pos": "FWD", "nation": "GER", "goals_curr": 2, "assists_curr": 1, "cs_curr": 0, "mins_curr": 438, "goals_prev": 13, "assists_prev": 7, "xg_90": 0.44, "xa_90": 0.21, "pen_share": 0.05, "shot_conv": 0.18, "kp_90": 1.5, "mins_prob": 0.87},
    {"player_id": "rice", "name": "Declan Rice", "club": "ARS", "pos": "MID", "nation": "ENG", "goals_curr": 1, "assists_curr": 2, "cs_curr": 0, "mins_curr": 450, "goals_prev": 7, "assists_prev": 10, "xg_90": 0.18, "xa_90": 0.26, "pen_share": 0.0, "shot_conv": 0.14, "kp_90": 2.1, "mins_prob": 0.95},
    {"player_id": "foden", "name": "Phil Foden", "club": "MCI", "pos": "MID", "nation": "ENG", "goals_curr": 1, "assists_curr": 2, "cs_curr": 0, "mins_curr": 340, "goals_prev": 14, "assists_prev": 10, "xg_90": 0.43, "xa_90": 0.32, "pen_share": 0.05, "shot_conv": 0.19, "kp_90": 2.4, "mins_prob": 0.84},
    {"player_id": "mbeumo", "name": "Bryan Mbeumo", "club": "MUN", "pos": "FWD", "nation": "CMR", "goals_curr": 2, "assists_curr": 1, "cs_curr": 0, "mins_curr": 450, "goals_prev": 14, "assists_prev": 8, "xg_90": 0.45, "xa_90": 0.25, "pen_share": 0.15, "shot_conv": 0.18, "kp_90": 1.9, "mins_prob": 0.90},
    {"player_id": "mgw", "name": "Morgan Gibbs-White", "club": "NFO", "pos": "MID", "nation": "ENG", "goals_curr": 1, "assists_curr": 2, "cs_curr": 0, "mins_curr": 450, "goals_prev": 15, "assists_prev": 10, "xg_90": 0.38, "xa_90": 0.29, "pen_share": 0.70, "shot_conv": 0.18, "kp_90": 2.5, "mins_prob": 0.92},
    {"player_id": "evanilson", "name": "Evanilson", "club": "BOU", "pos": "FWD", "nation": "BRA", "goals_curr": 1, "assists_curr": 3, "cs_curr": 0, "mins_curr": 420, "goals_prev": 12, "assists_prev": 6, "xg_90": 0.44, "xa_90": 0.22, "pen_share": 0.40, "shot_conv": 0.18, "kp_90": 1.5, "mins_prob": 0.87},
    {"player_id": "kamada", "name": "Daichi Kamada", "club": "CRY", "pos": "MID", "nation": "JPN", "goals_curr": 1, "assists_curr": 3, "cs_curr": 0, "mins_curr": 415, "goals_prev": 6, "assists_prev": 8, "xg_90": 0.22, "xa_90": 0.27, "pen_share": 0.0, "shot_conv": 0.15, "kp_90": 2.1, "mins_prob": 0.86},
    {"player_id": "barnes", "name": "Harvey Barnes", "club": "NEW", "pos": "FWD", "nation": "ENG", "goals_curr": 2, "assists_curr": 2, "cs_curr": 0, "mins_curr": 410, "goals_prev": 11, "assists_prev": 7, "xg_90": 0.40, "xa_90": 0.23, "pen_share": 0.10, "shot_conv": 0.18, "kp_90": 1.7, "mins_prob": 0.84},
    {"player_id": "elanga", "name": "Anthony Elanga", "club": "NEW", "pos": "FWD", "nation": "SWE", "goals_curr": 2, "assists_curr": 1, "cs_curr": 0, "mins_curr": 360, "goals_prev": 10, "assists_prev": 9, "xg_90": 0.36, "xa_90": 0.28, "pen_share": 0.0, "shot_conv": 0.17, "kp_90": 1.9, "mins_prob": 0.83},
    {"player_id": "belloumi", "name": "Mohamed Belloumi", "club": "HUL", "pos": "FWD", "nation": "ALG", "goals_curr": 2, "assists_curr": 2, "cs_curr": 0, "mins_curr": 398, "goals_prev": 12, "assists_prev": 9, "xg_90": 0.33, "xa_90": 0.24, "pen_share": 0.30, "shot_conv": 0.17, "kp_90": 1.8, "mins_prob": 0.86},
    {"player_id": "enciso", "name": "Julio Enciso", "club": "IPS", "pos": "MID", "nation": "PAR", "goals_curr": 1, "assists_curr": 2, "cs_curr": 0, "mins_curr": 410, "goals_prev": 8, "assists_prev": 7, "xg_90": 0.31, "xa_90": 0.25, "pen_share": 0.40, "shot_conv": 0.15, "kp_90": 2.0, "mins_prob": 0.85},
    {"player_id": "kostoulas", "name": "Charalampos Kostoulas", "club": "BHA", "pos": "FWD", "nation": "GRE", "goals_curr": 2, "assists_curr": 1, "cs_curr": 0, "mins_curr": 356, "goals_prev": 9, "assists_prev": 4, "xg_90": 0.45, "xa_90": 0.18, "pen_share": 0.15, "shot_conv": 0.19, "kp_90": 1.4, "mins_prob": 0.82},

    # Goalkeepers (Golden Glove / Clean Sheets Contenders - All 20 Clubs)
    {"player_id": "raya", "name": "David Raya", "club": "ARS", "pos": "GK", "nation": "ESP", "goals_curr": 0, "assists_curr": 0, "cs_curr": 3, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 19, "gk_psxg_diff": 4.2, "save_pct": 76.8, "mins_prob": 0.98},
    {"player_id": "donnarumma", "name": "Gianluigi Donnarumma", "club": "MCI", "pos": "GK", "nation": "ITA", "goals_curr": 0, "assists_curr": 0, "cs_curr": 2, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 15, "gk_psxg_diff": 3.8, "save_pct": 75.4, "mins_prob": 0.97},
    {"player_id": "alisson", "name": "Alisson Becker", "club": "LIV", "pos": "GK", "nation": "BRA", "goals_curr": 0, "assists_curr": 0, "cs_curr": 3, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 11, "gk_psxg_diff": 3.5, "save_pct": 74.9, "mins_prob": 0.93},
    {"player_id": "pickford", "name": "Jordan Pickford", "club": "EVE", "pos": "GK", "nation": "ENG", "goals_curr": 0, "assists_curr": 0, "cs_curr": 3, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 11, "gk_psxg_diff": 3.1, "save_pct": 73.8, "mins_prob": 0.99},
    {"player_id": "verbruggen", "name": "Bart Verbruggen", "club": "BHA", "pos": "GK", "nation": "NED", "goals_curr": 0, "assists_curr": 0, "cs_curr": 3, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 10, "gk_psxg_diff": 2.4, "save_pct": 72.9, "mins_prob": 0.96},
    {"player_id": "tzolakis", "name": "Konstantinos Tzolakis", "club": "HUL", "pos": "GK", "nation": "GRE", "goals_curr": 0, "assists_curr": 0, "cs_curr": 3, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 12, "gk_psxg_diff": 2.9, "save_pct": 74.1, "mins_prob": 0.96},
    {"player_id": "kelleher", "name": "Caoimhín Kelleher", "club": "BRE", "pos": "GK", "nation": "IRL", "goals_curr": 0, "assists_curr": 0, "cs_curr": 2, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 10, "gk_psxg_diff": 2.1, "save_pct": 72.4, "mins_prob": 0.96},
    {"player_id": "trafford", "name": "James Trafford", "club": "LEE", "pos": "GK", "nation": "ENG", "goals_curr": 0, "assists_curr": 0, "cs_curr": 2, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 9, "gk_psxg_diff": 1.9, "save_pct": 71.8, "mins_prob": 0.96},
    {"player_id": "kinsky", "name": "Antonín Kinský", "club": "TOT", "pos": "GK", "nation": "CZE", "goals_curr": 0, "assists_curr": 0, "cs_curr": 2, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 7, "gk_psxg_diff": 1.1, "save_pct": 70.2, "mins_prob": 0.95},
    {"player_id": "sels", "name": "Matz Sels", "club": "NFO", "pos": "GK", "nation": "BEL", "goals_curr": 0, "assists_curr": 0, "cs_curr": 1, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 9, "gk_psxg_diff": 1.5, "save_pct": 71.2, "mins_prob": 0.96},
    {"player_id": "henderson", "name": "Dean Henderson", "club": "CRY", "pos": "GK", "nation": "ENG", "goals_curr": 0, "assists_curr": 0, "cs_curr": 1, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 11, "gk_psxg_diff": 1.8, "save_pct": 71.5, "mins_prob": 0.95},
    {"player_id": "sanchez", "name": "Robert Sánchez", "club": "CHE", "pos": "GK", "nation": "ESP", "goals_curr": 0, "assists_curr": 0, "cs_curr": 0, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 9, "gk_psxg_diff": 0.4, "save_pct": 69.1, "mins_prob": 0.94},
    {"player_id": "onana", "name": "André Onana", "club": "MUN", "pos": "GK", "nation": "CMR", "goals_curr": 0, "assists_curr": 0, "cs_curr": 0, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 9, "gk_psxg_diff": 1.2, "save_pct": 70.8, "mins_prob": 0.96},
    {"player_id": "hornicek", "name": "Lukáš Horníček", "club": "NEW", "pos": "GK", "nation": "CZE", "goals_curr": 0, "assists_curr": 0, "cs_curr": 1, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 8, "gk_psxg_diff": 0.9, "save_pct": 70.0, "mins_prob": 0.94},
    {"player_id": "suzuki", "name": "Zion Suzuki", "club": "AVL", "pos": "GK", "nation": "JPN", "goals_curr": 0, "assists_curr": 0, "cs_curr": 1, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 8, "gk_psxg_diff": 0.8, "save_pct": 69.8, "mins_prob": 0.95},
    {"player_id": "petrovic", "name": "Đorđe Petrović", "club": "BOU", "pos": "GK", "nation": "SRB", "goals_curr": 0, "assists_curr": 0, "cs_curr": 0, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 11, "gk_psxg_diff": 1.6, "save_pct": 71.4, "mins_prob": 0.95},
    {"player_id": "leno", "name": "Bernd Leno", "club": "FUL", "pos": "GK", "nation": "GER", "goals_curr": 0, "assists_curr": 0, "cs_curr": 1, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 9, "gk_psxg_diff": 1.4, "save_pct": 71.0, "mins_prob": 0.97},
    {"player_id": "roefs", "name": "Robin Roefs", "club": "SUN", "pos": "GK", "nation": "NED", "goals_curr": 0, "assists_curr": 0, "cs_curr": 1, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 10, "gk_psxg_diff": 1.0, "save_pct": 70.1, "mins_prob": 0.95},
    {"player_id": "rushworth", "name": "Carl Rushworth", "club": "COV", "pos": "GK", "nation": "ENG", "goals_curr": 0, "assists_curr": 1, "cs_curr": 1, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 14, "gk_psxg_diff": 0.2, "save_pct": 68.4, "mins_prob": 0.95},
    {"player_id": "muric", "name": "Arijanet Muric", "club": "IPS", "pos": "GK", "nation": "KOS", "goals_curr": 0, "assists_curr": 0, "cs_curr": 0, "mins_curr": 450, "goals_prev": 0, "assists_prev": 0, "cs_prev": 12, "gk_psxg_diff": -0.3, "save_pct": 67.8, "mins_prob": 0.94},
]

df_players = pd.DataFrame(PLAYERS_DATA).fillna(0)

# 6b. Overwrite last-season figures with verified final 2025-26 numbers where published, and flag
#     which fields are sourced vs modelled estimates (surfaced as a badge in the dashboard).
VERIFIED_2025_26_GOALS = {          # published 2025-26 Premier League top-scorer table
    "haaland": 27, "igor_thiago": 22, "semenyo": 17, "watkins": 16, "mgw": 15,
    "joao_pedro": 15, "dcl": 14, "gyokeres": 14,
}
VERIFIED_2025_26_ASSISTS = {        # published 2025-26 Playmaker award table (final)
    "bruno": 21, "cherki": 12, "haaland": 8,
}
df_players["goals_prev_verified"] = df_players["player_id"].isin(VERIFIED_2025_26_GOALS)
df_players["assists_prev_verified"] = df_players["player_id"].isin(VERIFIED_2025_26_ASSISTS)
for pid, g in VERIFIED_2025_26_GOALS.items():
    df_players.loc[df_players["player_id"] == pid, "goals_prev"] = g
for pid, a in VERIFIED_2025_26_ASSISTS.items():
    df_players.loc[df_players["player_id"] == pid, "assists_prev"] = a

write_dataset(DATA_DIR, {"players_2026_27.csv": (df_players.to_dict("records"), list(df_players.columns))})
n_g = int(df_players["goals_prev_verified"].sum())
n_a = int(df_players["assists_prev_verified"].sum())
print(f"Saved {len(df_players)} players to players_2026_27.csv "
      f"({n_g} verified last-season goal tallies, {n_a} verified assist tallies).")
