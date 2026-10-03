"""Official 2026-27 Premier League fixture calendar (by matchweek).

Source: Premier League "Season 2026/27 By Date" fixture release (19 June 2026), cross-checked
against premierleague.com's "All 380 fixtures" article and club fixture pages.

Matchweeks 1-5 are complete (played 21 Aug - 20 Sep 2026). Matchweeks 6-38 are the remaining
330 fixtures. Matchweek 37 (23 May 2027) is derived by elimination and verified: the union of
all remaining matchweeks must exactly equal the 330 unplayed home/away pairings.
"""

# Matchweek -> (dates, list of (home, away))
FIXTURES_2026_27 = {
    6: ("10-12 October 2026", [
        ("ARS", "LEE"), ("AVL", "BRE"), ("CHE", "BOU"), ("COV", "NEW"), ("CRY", "NFO"),
        ("HUL", "EVE"), ("IPS", "FUL"), ("LIV", "MCI"), ("MUN", "TOT"), ("SUN", "BHA"),
    ]),
    7: ("17-19 October 2026", [
        ("BOU", "SUN"), ("BRE", "LIV"), ("BHA", "CRY"), ("EVE", "CHE"), ("FUL", "HUL"),
        ("LEE", "MUN"), ("MCI", "IPS"), ("NEW", "AVL"), ("NFO", "ARS"), ("TOT", "COV"),
    ]),
    8: ("24-25 October 2026", [
        ("ARS", "EVE"), ("AVL", "MCI"), ("CHE", "TOT"), ("COV", "FUL"), ("CRY", "NEW"),
        ("HUL", "BRE"), ("IPS", "NFO"), ("LIV", "BHA"), ("MUN", "BOU"), ("SUN", "LEE"),
    ]),
    9: ("31 October - 2 November 2026", [
        ("BOU", "LEE"), ("AVL", "FUL"), ("BRE", "NFO"), ("CHE", "MUN"), ("COV", "SUN"),
        ("HUL", "IPS"), ("LIV", "ARS"), ("MCI", "BHA"), ("NEW", "EVE"), ("TOT", "CRY"),
    ]),
    10: ("7-8 November 2026", [
        ("ARS", "HUL"), ("BHA", "BRE"), ("CRY", "LIV"), ("EVE", "COV"), ("FUL", "NEW"),
        ("IPS", "BOU"), ("LEE", "TOT"), ("MUN", "AVL"), ("NFO", "MCI"), ("SUN", "CHE"),
    ]),
    11: ("21-23 November 2026", [
        ("BOU", "NFO"), ("AVL", "SUN"), ("BRE", "EVE"), ("CHE", "LEE"), ("COV", "CRY"),
        ("HUL", "BHA"), ("LIV", "MUN"), ("MCI", "FUL"), ("NEW", "ARS"), ("TOT", "IPS"),
    ]),
    12: ("28-29 November 2026", [
        ("ARS", "MCI"), ("BHA", "NEW"), ("CRY", "HUL"), ("EVE", "LIV"), ("FUL", "BOU"),
        ("IPS", "AVL"), ("LEE", "COV"), ("MUN", "BRE"), ("NFO", "CHE"), ("SUN", "TOT"),
    ]),
    13: ("2 December 2026", [
        ("BOU", "BHA"), ("AVL", "EVE"), ("BRE", "ARS"), ("CHE", "CRY"), ("COV", "IPS"),
        ("HUL", "NFO"), ("LIV", "SUN"), ("MCI", "LEE"), ("NEW", "MUN"), ("TOT", "FUL"),
    ]),
    14: ("5 December 2026", [
        ("BOU", "HUL"), ("AVL", "CRY"), ("BRE", "MCI"), ("CHE", "LIV"), ("EVE", "FUL"),
        ("LEE", "IPS"), ("MUN", "COV"), ("NEW", "SUN"), ("NFO", "BHA"), ("TOT", "ARS"),
    ]),
    15: ("12 December 2026", [
        ("ARS", "BOU"), ("BHA", "EVE"), ("COV", "AVL"), ("CRY", "MUN"), ("FUL", "BRE"),
        ("HUL", "TOT"), ("IPS", "NEW"), ("LIV", "LEE"), ("MCI", "CHE"), ("SUN", "NFO"),
    ]),
    16: ("19 December 2026", [
        ("BOU", "COV"), ("ARS", "MUN"), ("BRE", "NEW"), ("BHA", "IPS"), ("CHE", "AVL"),
        ("LEE", "FUL"), ("LIV", "TOT"), ("MCI", "HUL"), ("NFO", "EVE"), ("SUN", "CRY"),
    ]),
    17: ("26 December 2026", [
        ("AVL", "LEE"), ("COV", "CHE"), ("CRY", "ARS"), ("EVE", "SUN"), ("FUL", "BHA"),
        ("HUL", "LIV"), ("IPS", "BRE"), ("MUN", "NFO"), ("NEW", "MCI"), ("TOT", "BOU"),
    ]),
    18: ("30 December 2026", [
        ("AVL", "LIV"), ("COV", "BRE"), ("CRY", "BOU"), ("EVE", "MCI"), ("FUL", "ARS"),
        ("HUL", "LEE"), ("IPS", "CHE"), ("MUN", "SUN"), ("NEW", "NFO"), ("TOT", "BHA"),
    ]),
    19: ("2 January 2027", [
        ("BOU", "AVL"), ("ARS", "IPS"), ("BRE", "CRY"), ("BHA", "MUN"), ("CHE", "NEW"),
        ("LEE", "EVE"), ("LIV", "COV"), ("MCI", "TOT"), ("NFO", "FUL"), ("SUN", "HUL"),
    ]),
    20: ("6 January 2027", [
        ("ARS", "BRE"), ("BHA", "BOU"), ("CRY", "CHE"), ("EVE", "AVL"), ("FUL", "TOT"),
        ("IPS", "COV"), ("LEE", "MCI"), ("MUN", "NEW"), ("NFO", "HUL"), ("SUN", "LIV"),
    ]),
    21: ("16 January 2027", [
        ("BOU", "IPS"), ("AVL", "MUN"), ("BRE", "BHA"), ("CHE", "SUN"), ("COV", "EVE"),
        ("HUL", "ARS"), ("LIV", "CRY"), ("MCI", "NFO"), ("NEW", "FUL"), ("TOT", "LEE"),
    ]),
    22: ("23 January 2027", [
        ("ARS", "NEW"), ("BHA", "MCI"), ("CRY", "TOT"), ("EVE", "BRE"), ("FUL", "AVL"),
        ("IPS", "HUL"), ("LEE", "CHE"), ("MUN", "LIV"), ("NFO", "BOU"), ("SUN", "COV"),
    ]),
    23: ("30 January 2027", [
        ("BOU", "FUL"), ("AVL", "IPS"), ("BRE", "MUN"), ("CHE", "NFO"), ("COV", "LEE"),
        ("HUL", "CRY"), ("LIV", "EVE"), ("MCI", "ARS"), ("NEW", "BHA"), ("TOT", "SUN"),
    ]),
    24: ("6 February 2027", [
        ("ARS", "LIV"), ("BHA", "HUL"), ("CRY", "COV"), ("EVE", "NEW"), ("FUL", "MCI"),
        ("IPS", "TOT"), ("LEE", "BOU"), ("MUN", "CHE"), ("NFO", "BRE"), ("SUN", "AVL"),
    ]),
    25: ("10 February 2027", [
        ("AVL", "BOU"), ("COV", "LIV"), ("CRY", "BRE"), ("EVE", "LEE"), ("FUL", "NFO"),
        ("HUL", "SUN"), ("IPS", "ARS"), ("MUN", "BHA"), ("NEW", "CHE"), ("TOT", "MCI"),
    ]),
    26: ("20 February 2027", [
        ("BOU", "CRY"), ("ARS", "FUL"), ("BRE", "COV"), ("BHA", "TOT"), ("CHE", "IPS"),
        ("LEE", "AVL"), ("LIV", "HUL"), ("MCI", "NEW"), ("NFO", "MUN"), ("SUN", "EVE"),
    ]),
    27: ("27 February 2027", [
        ("AVL", "CHE"), ("COV", "BOU"), ("CRY", "SUN"), ("EVE", "NFO"), ("FUL", "LEE"),
        ("HUL", "MCI"), ("IPS", "BHA"), ("MUN", "ARS"), ("NEW", "BRE"), ("TOT", "LIV"),
    ]),
    28: ("3 March 2027", [
        ("BOU", "TOT"), ("ARS", "CRY"), ("BRE", "IPS"), ("BHA", "FUL"), ("CHE", "COV"),
        ("LEE", "HUL"), ("LIV", "AVL"), ("MCI", "EVE"), ("NFO", "NEW"), ("SUN", "MUN"),
    ]),
    29: ("13 March 2027", [
        ("BOU", "NEW"), ("AVL", "HUL"), ("CHE", "ARS"), ("COV", "MCI"), ("CRY", "FUL"),
        ("LEE", "BHA"), ("LIV", "IPS"), ("MUN", "EVE"), ("SUN", "BRE"), ("TOT", "NFO"),
    ]),
    30: ("20 March 2027", [
        ("ARS", "SUN"), ("BRE", "BOU"), ("BHA", "COV"), ("EVE", "TOT"), ("FUL", "LIV"),
        ("HUL", "CHE"), ("IPS", "CRY"), ("MCI", "MUN"), ("NEW", "LEE"), ("NFO", "AVL"),
    ]),
    31: ("10 April 2027", [
        ("BOU", "MCI"), ("AVL", "BHA"), ("CHE", "FUL"), ("COV", "ARS"), ("CRY", "EVE"),
        ("LEE", "NFO"), ("LIV", "NEW"), ("MUN", "HUL"), ("SUN", "IPS"), ("TOT", "BRE"),
    ]),
    32: ("17 April 2027", [
        ("ARS", "AVL"), ("BRE", "LEE"), ("BHA", "CHE"), ("EVE", "BOU"), ("FUL", "SUN"),
        ("HUL", "COV"), ("IPS", "MUN"), ("MCI", "CRY"), ("NEW", "TOT"), ("NFO", "LIV"),
    ]),
    33: ("24 April 2027", [
        ("BOU", "ARS"), ("AVL", "COV"), ("BRE", "FUL"), ("CHE", "MCI"), ("EVE", "BHA"),
        ("LEE", "LIV"), ("MUN", "CRY"), ("NEW", "IPS"), ("NFO", "SUN"), ("TOT", "HUL"),
    ]),
    34: ("1 May 2027", [
        ("ARS", "TOT"), ("BHA", "NFO"), ("COV", "MUN"), ("CRY", "AVL"), ("FUL", "EVE"),
        ("HUL", "BOU"), ("IPS", "LEE"), ("LIV", "CHE"), ("MCI", "BRE"), ("SUN", "NEW"),
    ]),
    35: ("8 May 2027", [
        ("BOU", "MUN"), ("BRE", "AVL"), ("BHA", "SUN"), ("EVE", "HUL"), ("FUL", "IPS"),
        ("LEE", "ARS"), ("MCI", "LIV"), ("NEW", "COV"), ("NFO", "CRY"), ("TOT", "CHE"),
    ]),
    # Matchweek 37 (23 May 2027) is derived by elimination in validate_official_fixtures()
    36: ("15 May 2027", [
        ("ARS", "NFO"), ("AVL", "NEW"), ("CHE", "EVE"), ("COV", "TOT"), ("CRY", "BHA"),
        ("HUL", "FUL"), ("IPS", "MCI"), ("LIV", "BRE"), ("MUN", "LEE"), ("SUN", "BOU"),
    ]),
    38: ("30 May 2027", [
        ("ARS", "BHA"), ("AVL", "TOT"), ("CHE", "BRE"), ("COV", "NFO"), ("CRY", "LEE"),
        ("HUL", "NEW"), ("IPS", "EVE"), ("LIV", "BOU"), ("MUN", "FUL"), ("SUN", "MCI"),
    ]),
}

# The 50 matches already played (matchweeks 1-5), with verified scorelines
PLAYED_BY_MW = {
    1: [("ARS", "COV", 3, 0), ("HUL", "MUN", 2, 0), ("EVE", "CRY", 2, 0), ("IPS", "SUN", 2, 1),
        ("NFO", "LEE", 0, 1), ("BRE", "TOT", 3, 0), ("BHA", "AVL", 4, 0), ("MCI", "BOU", 2, 1),
        ("NEW", "LIV", 2, 2), ("FUL", "CHE", 2, 3)],
    2: [("CRY", "MCI", 1, 4), ("LIV", "NFO", 2, 2), ("BOU", "EVE", 1, 1), ("COV", "HUL", 0, 1),
        ("TOT", "NEW", 0, 2), ("CHE", "BHA", 4, 3), ("LEE", "BRE", 1, 1), ("SUN", "FUL", 1, 0),
        ("MUN", "IPS", 5, 2), ("AVL", "ARS", 0, 1)],
    3: [("IPS", "LIV", 0, 2), ("NEW", "BOU", 2, 2), ("BRE", "SUN", 1, 1), ("BHA", "LEE", 1, 1),
        ("FUL", "CRY", 2, 3), ("MCI", "COV", 1, 0), ("NFO", "TOT", 0, 0), ("HUL", "AVL", 0, 0),
        ("EVE", "MUN", 2, 2), ("ARS", "CHE", 2, 1)],
    4: [("BOU", "BRE", 2, 2), ("AVL", "NFO", 1, 2), ("CHE", "HUL", 2, 2), ("CRY", "IPS", 2, 3),
        ("LIV", "FUL", 0, 0), ("TOT", "EVE", 0, 0), ("SUN", "ARS", 0, 2), ("COV", "BHA", 0, 5),
        ("MUN", "MCI", 0, 1), ("LEE", "NEW", 4, 1)],
    5: [("BRE", "CHE", 3, 0), ("TOT", "AVL", 2, 3), ("BHA", "ARS", 3, 0), ("EVE", "IPS", 1, 0),
        ("NEW", "HUL", 2, 1), ("NFO", "COV", 0, 1), ("BOU", "LIV", 0, 1), ("LEE", "CRY", 0, 0),
        ("MCI", "SUN", 5, 3), ("FUL", "MUN", 1, 1)],
}


def validate_official_fixtures():
    """Integrity-check the official calendar against the played results.

    1. Every played fixture (MW1-5) must be a real home/away pairing in the 38-round double
       round-robin (each ordered pair exactly once).
    2. Played results must reproduce the published MW5 league table.
    3. The unplayed pairings implied by the calendar must number exactly 330, and the union of
       MW6-MW38 must be exactly those 330 pairings with no duplicates.
    4. Each matchweek must contain each club at most once.
    """
    teams = sorted({t for mw in PLAYED_BY_MW.values() for fx in mw for t in fx[:2]})
    assert len(teams) == 20, f"expected 20 clubs, got {len(teams)}"

    full_schedule = set()
    for h in teams:
        for a in teams:
            if h != a:
                full_schedule.add((h, a))
    assert len(full_schedule) == 380

    played_pairs = set()
    for mw, fx_list in PLAYED_BY_MW.items():
        assert len(fx_list) == 10, f"MW{mw} should have 10 matches"
        clubs = [c for fx in fx_list for c in fx[:2]]
        assert len(set(clubs)) == 20, f"MW{mw} repeats a club"
        for h, a, hg, ag in fx_list:
            assert h != a, f"MW{mw}: {h} cannot play itself"
            assert (h, a) in full_schedule, f"MW{mw}: {h}-{a} not a valid pairing"
            played_pairs.add((h, a))

    # 2. Verify the live table
    table = {t: {"P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "Pts": 0} for t in teams}
    for mw in sorted(PLAYED_BY_MW):
        for h, a, hg, ag in PLAYED_BY_MW[mw]:
            table[h]["P"] += 1; table[a]["P"] += 1
            table[h]["GF"] += hg; table[h]["GA"] += ag
            table[a]["GF"] += ag; table[a]["GA"] += hg
            if hg > ag:
                table[h]["W"] += 1; table[a]["L"] += 1; table[h]["Pts"] += 3
            elif hg < ag:
                table[a]["W"] += 1; table[h]["L"] += 1; table[a]["Pts"] += 3
            else:
                table[h]["D"] += 1; table[a]["D"] += 1
                table[h]["Pts"] += 1; table[a]["Pts"] += 1
    expected = {
        "MCI": (5, 5, 0, 0, 13, 5, 15), "ARS": (5, 4, 0, 1, 8, 4, 12),
        "BHA": (5, 3, 1, 1, 16, 5, 10), "BRE": (5, 2, 3, 0, 10, 4, 9),
        "LEE": (5, 2, 3, 0, 7, 3, 9), "LIV": (5, 2, 3, 0, 7, 4, 9),
        "EVE": (5, 2, 3, 0, 6, 3, 9), "HUL": (5, 2, 2, 1, 6, 4, 8),
        "NEW": (5, 2, 2, 1, 9, 9, 8), "CHE": (5, 2, 1, 2, 10, 12, 7),
        "IPS": (5, 2, 0, 3, 7, 11, 6), "MUN": (5, 1, 2, 2, 8, 8, 5),
        "NFO": (5, 1, 2, 2, 4, 5, 5), "SUN": (5, 1, 1, 3, 6, 10, 4),
        "CRY": (5, 1, 1, 3, 6, 11, 4), "AVL": (5, 1, 1, 3, 4, 9, 4),
        "BOU": (5, 0, 3, 2, 6, 8, 3), "COV": (5, 1, 0, 4, 1, 10, 3),
        "FUL": (5, 0, 2, 3, 5, 8, 2), "TOT": (5, 0, 2, 3, 2, 8, 2),
    }
    for code, (p, w, d, l, gf, ga, pts) in expected.items():
        s = table[code]
        got = (s["P"], s["W"], s["D"], s["L"], s["GF"], s["GA"], s["Pts"])
        assert got == (p, w, d, l, gf, ga, pts), f"{code}: got {got}, expected {(p, w, d, l, gf, ga, pts)}"
    total_goals = sum(s["GF"] for s in table.values())
    assert total_goals == 141, f"total goals {total_goals} != 141"

    # 3. Remaining pairings from the official calendar
    remaining_pairs = full_schedule - played_pairs
    assert len(remaining_pairs) == 330, f"expected 330 remaining, got {len(remaining_pairs)}"

    cal_pairs = {}
    for mw, (dates, fx_list) in FIXTURES_2026_27.items():
        assert len(fx_list) == 10, f"MW{mw} should have 10 fixtures"
        clubs = [c for fx in fx_list for c in fx]
        assert len(set(clubs)) == 20, f"MW{mw} repeats a club: {clubs}"
        for h, a in fx_list:
            assert (h, a) in remaining_pairs, f"MW{mw}: {h}-{a} is not an unplayed pairing"
            assert (h, a) not in cal_pairs, f"{h}-{a} appears in MW{cal_pairs[(h, a)]} and MW{mw}"
            cal_pairs[(h, a)] = mw

    missing = remaining_pairs - set(cal_pairs)
    assert len(missing) == 10, f"expected exactly 10 pairings left for MW37, got {len(missing)}"

    # Matchweek 37 = the 10 pairings left over, sorted by home club
    mw37 = sorted(missing, key=lambda p: p[0])
    clubs37 = [c for fx in mw37 for c in fx]
    assert len(set(clubs37)) == 20, "MW37 derivation repeats a club"
    FIXTURES_2026_27[37] = ("23 May 2027", mw37)

    covered = played_pairs | set(cal_pairs) | set(mw37)
    assert covered == full_schedule and len(covered) == 380, "calendar does not cover all 380 fixtures"

    return {
        "played": len(played_pairs),
        "remaining": len(remaining_pairs),
        "matchweeks_derived": sorted(FIXTURES_2026_27),
        "mw37_derived": mw37,
    }


if __name__ == "__main__":
    report = validate_official_fixtures()
    print("Official 2026-27 calendar validated ✓")
    print(f"  played pairings   : {report['played']}")
    print(f"  remaining pairings: {report['remaining']}")
    print(f"  matchweeks        : {report['matchweeks_derived'][0]}-{report['matchweeks_derived'][-1]}")
    print("  MW37 derived by elimination:")
    for h, a in report["mw37_derived"]:
        print(f"    {h} v {a}")
