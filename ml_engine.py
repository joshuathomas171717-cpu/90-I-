import hashlib
import os
import json
import pickle
import sys
import time
import numpy as np
import pandas as pd
from scipy.stats import poisson
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import log_loss, accuracy_score
from sklearn.inspection import permutation_importance
from sklearn.preprocessing import StandardScaler

# Resolved relative to this file so the engine runs from any directory (see tests/test_portability.py).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# ── P3.1 model artifact cache ────────────────────────────────────────────────
# Training plus the 5,000-run baseline Monte Carlo cost ~4s of a ~7.3s cold start. Every input is
# deterministic, so the result is too: caching it turns a cold start into a file read.
ARTIFACTS_DIR = os.path.join(BASE_DIR, "artifacts")
CACHE_FORMAT = "ninety-engine-cache/1"
CACHE_INPUTS = ("teams_2026_27.csv", "matches_2025_26.csv", "matches_2026_27_played.csv",
                "fixtures_2026_27_remaining.csv", "players_2026_27.csv")
CACHED_ATTRS = ("scaler", "glm_home", "glm_away", "gb_home", "gb_away", "clf_gb", "clf_rf", "clf_lr")
FORCE_RETRAIN = os.environ.get("NT90_FORCE_RETRAIN", "").lower() in ("1", "true", "yes", "on")


def library_fingerprint():
    """The versions of the libraries the trained artifacts were produced with.

    This belongs in the cache key and was missing from it. The cache held pickles of scikit-learn
    estimators; unpickling one into a *different* scikit-learn is not a hit but a coin flip — scikit
    logs `InconsistentVersionWarning: Trying to unpickle estimator PoissonRegressor from version 1.9.1
    when using version 1.6.1. This might lead to breaking code or invalid results`, and the numbers
    that come out of it are nobody's intent.

    It surfaced in this project's own CI rig, where a copy trained under scikit-learn 1.9.1 was served
    by an interpreter holding 1.6.1: the model loaded without complaint and answered differently. The
    same trap waits for anyone who upgrades numpy and keeps their artifacts/ directory, so the key now
    moves when they do, and the cost is one retrain.
    """
    parts = []
    for module in ("numpy", "pandas", "scipy", "sklearn"):
        try:
            parts.append("%s=%s" % (module, __import__(module).__version__))
        except Exception:                              # a missing optional library is not a reason to die
            parts.append("%s=absent" % module)
    parts.append("py=%d.%d" % sys.version_info[:2])
    return ";".join(parts)


def engine_fingerprint(paths=None, engine_path=None, salt=""):
    """SHA-256 over every input to the model: the five CSVs, this file's own source, and the versions
    of the libraries that do the arithmetic.

    Hashing the source matters — a change to the maths must miss the cache, or the dashboard would keep
    serving numbers from a model that no longer exists. The library versions matter for the same reason
    in the other direction: the same maths on a different numpy is legitimately a slightly different
    model (see library_fingerprint). Callers may pass explicit paths to prove the key actually moves
    when the inputs do (see tests/test_deploy.py).
    """
    digest = hashlib.sha256()
    digest.update(CACHE_FORMAT.encode())
    digest.update(salt.encode())
    digest.update(library_fingerprint().encode())
    for path in (paths if paths is not None else [os.path.join(DATA_DIR, n) for n in CACHE_INPUTS]):
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
    with open(engine_path or os.path.abspath(__file__), "rb") as fh:
        digest.update(fh.read())
    return digest.hexdigest()


def dixon_coles_tau(x, y, lam_x, lam_y, rho=-0.11):
    """Dixon-Coles (1997) low-scoring correlation adjustment for English football."""
    if x == 0 and y == 0:
        return 1.0 - lam_x * lam_y * rho
    elif x == 0 and y == 1:
        return 1.0 + lam_x * rho
    elif x == 1 and y == 0:
        return 1.0 + lam_y * rho
    elif x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def scoreline_matrix(lam_h, lam_a, max_goals=6, rho=-0.11):
    """Compute exact (max_goals+1)x(max_goals+1) Dixon-Coles bivariate Poisson probability matrix."""
    p_h = poisson.pmf(np.arange(max_goals + 1), lam_h)
    p_a = poisson.pmf(np.arange(max_goals + 1), lam_a)
    mat = np.outer(p_h, p_a)
    for x in (0, 1):
        for y in (0, 1):
            mat[x, y] = max(0.0, mat[x, y] * dixon_coles_tau(x, y, lam_h, lam_a, rho))
    total = mat.sum()
    if total > 0:
        mat /= total
    return mat


def json_safe(obj):
    """Recursively replace non-finite floats with None.

    json.dump() happily writes bare `NaN`, which is not valid JSON — browsers'
    JSON.parse() rejects the whole payload, and the dashboard silently falls back to its
    offline engine. Data read from CSVs (unused columns such as `europe`) is the usual source.
    """
    import math
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj

def as_of_state(df_played):
    """When was the data last promoted, and which gameweek was complete.

    Deliberately a function rather than a cached field: `data/as_of.json` changes on every weekly run,
    while the model artifact only changes when the underlying CSVs do (they are in the cache key).
    Re-stamping on load is what keeps a 0.02 s cache hit from publishing a stale date.
    """
    last_completed_gw = max((int(g) for g in df_played["gw"]), default=0)
    state_path = os.path.join(DATA_DIR, "as_of.json")
    state = None
    if os.path.exists(state_path):
        try:
            with open(state_path, encoding="utf-8") as fh:
                state = json.load(fh)
        except Exception:
            state = None
    if state and state.get("date"):
        return ("%s (Matchweek %d Complete)" % (state["date"], state.get("last_completed_gw", last_completed_gw)),
                int(state.get("last_completed_gw", last_completed_gw)))
    return ("2026-10-02 (Matchweek %d Complete)" % last_completed_gw, last_completed_gw)


class PremierLeagueMLEngine:
    """Trained engine: reads the data, then loads the artifact cache if the inputs still hash the same."""

    def __init__(self, use_cache=True, force_retrain=None, n_sims=5000):
        t0 = time.perf_counter()
        self.df_teams = pd.read_csv(os.path.join(DATA_DIR, "teams_2026_27.csv"))
        self.df_25_26 = pd.read_csv(os.path.join(DATA_DIR, "matches_2025_26.csv"))
        self.df_played = pd.read_csv(os.path.join(DATA_DIR, "matches_2026_27_played.csv"))
        self.df_rem = pd.read_csv(os.path.join(DATA_DIR, "fixtures_2026_27_remaining.csv"))
        self.df_players = pd.read_csv(os.path.join(DATA_DIR, "players_2026_27.csv"))
        # P14: descriptive context, not an extra feature smuggled into the trained models.
        from player_data import load_json as _load_player_json
        from player_context import compact as _compact_player_context
        self.player_signal_status = _compact_player_context(_load_player_json(
            os.path.join(DATA_DIR, "player_context_2026_27.json")))
        from player_ui import fingerprint as _ui_fingerprint
        self.player_ui_status = {"version": "player-ui/1", "fingerprint": _ui_fingerprint(
            _load_player_json(os.path.join(DATA_DIR, "player_ui_2026_27.json")))}

        # Historical lookup for relegated 2025-26 teams
        relegated_25_26 = {
            "WHU": {"name": "West Ham United", "elo_base": 1680, "xg_90_base": 1.22, "xga_90_base": 1.62, "squad_value_m": 410, "set_piece_xg": 0.30, "ppda": 12.0, "home_adv": 0.21, "europe": "None", "promoted": 0},
            "BUR": {"name": "Burnley", "elo_base": 1615, "xg_90_base": 1.02, "xga_90_base": 1.82, "squad_value_m": 240, "set_piece_xg": 0.24, "ppda": 12.6, "home_adv": 0.19, "europe": "None", "promoted": 1},
            "WOL": {"name": "Wolverhampton Wanderers", "elo_base": 1605, "xg_90_base": 0.94, "xga_90_base": 1.76, "squad_value_m": 330, "set_piece_xg": 0.23, "ppda": 12.5, "home_adv": 0.20, "europe": "None", "promoted": 0},
        }
        self.teams_dict = {row["code"]: row.to_dict() for _, row in self.df_teams.iterrows()}
        for code, meta in relegated_25_26.items():
            self.teams_dict[code] = {
                **meta,
                "elo_live": meta["elo_base"],
                "xg_90_live": meta["xg_90_base"],
                "xga_90_live": meta["xga_90_base"],
                "ppg_current": 0.9,
            }

        self.feature_names = [
            "elo_diff",
            "home_xg_vs_away_xga",
            "away_xg_vs_home_xga",
            "squad_value_log_ratio",
            "set_piece_xg_diff",
            "pressing_ppda_diff",
            "european_congestion_diff",
            "home_fortress_advantage",
            "recent_form_ppg_diff",
        ]
        self.feature_labels = {
            "elo_diff": "Club Elo & Tactical Strength Diff",
            "home_xg_vs_away_xga": "Home Attacking xG vs Away Defensive xGA",
            "away_xg_vs_home_xga": "Away Attacking xG vs Home Defensive xGA",
            "squad_value_log_ratio": "Squad Depth & Market Value Ratio",
            "set_piece_xg_diff": "Set-Piece Threat Differential (xG/90)",
            "pressing_ppda_diff": "High Pressing Intensity (PPDA Diff)",
            "european_congestion_diff": "UEFA Midweek Fixture Congestion & Fatigue",
            "home_fortress_advantage": "Stadium Home Fortress Advantage",
            "recent_form_ppg_diff": "Current Season 5-Match Form Momentum (PPG)",
        }

        force = FORCE_RETRAIN if force_retrain is None else force_retrain
        self.cache_key = engine_fingerprint()
        self.cache_path = os.path.join(ARTIFACTS_DIR, "engine-%s.pkl" % self.cache_key[:16])
        self.cache_hit = False
        self.cache_error = None

        if use_cache and not force and self._load_from_cache():
            self._restamp_as_of()
            self.baseline_results["meta"]["player_signal"] = self.player_signal_status
            self.baseline_results["meta"]["player_ui"] = self.player_ui_status
            self.boot_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            return

        self._train_models()
        # League scoring-rate calibration: scale the blended lambda so the average match produces
        # the league-observed goals-per-game (blend of PL history ~2.86 and the live 2.82 rate).
        self.lambda_scale = self._calibrate_lambda_scale(target_goals_per_game=2.86)
        self.baseline_results = self.run_simulation(n_sims=n_sims, scenario={})
        self.boot_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        self._save_to_cache()

    def _restamp_as_of(self):
        """A cache hit replays the stored payload. The 'as of' stamp is not a model output — refresh it
        from `data/as_of.json` instead of republishing the date the artifact was written."""
        meta = (self.baseline_results or {}).get("meta")
        if not isinstance(meta, dict):
            return
        label, last = as_of_state(self.df_played)
        meta["as_of_date"] = label
        meta["last_completed_gw"] = last

    # ── cache plumbing ───────────────────────────────────────────────────────
    def _load_from_cache(self):
        """Populate the trained attributes from disk. Returns False on any miss — a stale or corrupt
        artifact must degrade to retraining, never to a crash."""
        if not os.path.exists(self.cache_path):
            return False
        try:
            with open(self.cache_path, "rb") as fh:
                blob = pickle.load(fh)
            if blob.get("format") != CACHE_FORMAT or blob.get("key") != self.cache_key:
                return False
            for attr in CACHED_ATTRS:
                setattr(self, attr, blob["models"][attr])
            self.cv_metrics = blob["cv_metrics"]
            self.feature_importance = blob["feature_importance"]
            self.lambda_scale = blob["lambda_scale"]
            self.baseline_results = blob["baseline_results"]
            self.cache_hit = True
            return True
        except Exception as exc:                      # defensive: corrupt artifact == retrain
            self.cache_error = "%s: %s" % (type(exc).__name__, exc)
            return False

    def _save_to_cache(self):
        """Atomic write, so a half-written artifact can never be loaded by the next process."""
        try:
            os.makedirs(ARTIFACTS_DIR, exist_ok=True)
            blob = {
                "format": CACHE_FORMAT,
                "key": self.cache_key,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "models": {attr: getattr(self, attr) for attr in CACHED_ATTRS},
                "cv_metrics": self.cv_metrics,
                "feature_importance": self.feature_importance,
                "lambda_scale": self.lambda_scale,
                "baseline_results": self.baseline_results,
            }
            tmp = self.cache_path + ".tmp"
            with open(tmp, "wb") as fh:
                pickle.dump(blob, fh, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, self.cache_path)
            self.cache_written = True
            return True
        except Exception as exc:                      # defensive: read-only FS, disk full
            self.cache_error = "%s: %s" % (type(exc).__name__, exc)
            self.cache_written = False
            return False

    def _calibrate_lambda_scale(self, target_goals_per_game=2.86):
        total = 0.0
        for _, fix in self.df_rem.iterrows():
            feats = self._extract_match_features(fix["home"], fix["away"])
            fs = self.scaler.transform(feats.reshape(1, -1))
            ml_h = 0.55 * self.glm_home.predict(fs)[0] + 0.45 * self.gb_home.predict(fs)[0]
            ml_a = 0.55 * self.glm_away.predict(fs)[0] + 0.45 * self.gb_away.predict(fs)[0]
            lh = float(np.clip(0.60 * feats[1] + 0.40 * ml_h, 0.35, 3.80))
            la = float(np.clip(0.60 * feats[2] + 0.40 * ml_a, 0.25, 3.40))
            total += lh + la
        mean_total = total / max(1, len(self.df_rem))
        return float(np.clip(target_goals_per_game / max(0.1, mean_total), 0.6, 1.35))

    def _europe_fatigue(self, eur_str):
        if eur_str == "UCL":
            return 0.065
        elif eur_str in ("UEL", "UECL"):
            return 0.055
        return 0.0

    def _extract_match_features(self, h_code, a_code, team_state=None):
        ts = team_state if team_state is not None else self.teams_dict
        h = ts[h_code]
        a = ts[a_code]

        elo_diff = (h["elo_live"] + 55.0 * h["home_adv"] / 0.25 - a["elo_live"]) / 100.0
        home_xg_vs_away_xga = (h["xg_90_live"] * (a["xga_90_live"] / 1.28)) * (1.0 + 0.5 * h["home_adv"])
        away_xg_vs_home_xga = (a["xg_90_live"] * (h["xga_90_live"] / 1.28)) * (1.0 - 0.35 * h["home_adv"])
        squad_value_log_ratio = np.log(max(h["squad_value_m"], 100) / max(a["squad_value_m"], 100))
        set_piece_xg_diff = h["set_piece_xg"] - a["set_piece_xg"]
        pressing_ppda_diff = a["ppda"] - h["ppda"]  # Positive means home presses harder
        eur_diff = self._europe_fatigue(a["europe"]) - self._europe_fatigue(h["europe"])
        home_fortress = h["home_adv"]
        form_diff = h.get("ppg_current", 1.4) - a.get("ppg_current", 1.4)

        return np.array([
            elo_diff,
            home_xg_vs_away_xga,
            away_xg_vs_home_xga,
            squad_value_log_ratio,
            set_piece_xg_diff,
            pressing_ppda_diff,
            eur_diff,
            home_fortress,
            form_diff
        ], dtype=float)

    def _train_models(self):
        # Combine 380 matches from 2025-26 and 50 matches from 2026-27 (430 real matches)
        df_all = pd.concat([
            self.df_25_26[["season", "home", "away", "home_goals", "away_goals", "outcome"]],
            self.df_played[["season", "home", "away", "home_goals", "away_goals", "outcome"]]
        ], ignore_index=True)

        X_list, yh_list, ya_list, y_cls_list, weights = [], [], [], [], []
        outcome_map = {"H": 0, "D": 1, "A": 2}

        for _, row in df_all.iterrows():
            feats = self._extract_match_features(row["home"], row["away"])
            X_list.append(feats)
            yh_list.append(row["home_goals"])
            ya_list.append(row["away_goals"])
            y_cls_list.append(outcome_map[row["outcome"]])
            # Weight current 2026-27 matches 1.6x higher than 2025-26 matches
            weights.append(1.6 if row["season"] == "2026-27" else 1.0)

        X = np.vstack(X_list)
        yh = np.array(yh_list, dtype=float)
        ya = np.array(ya_list, dtype=float)
        y_cls = np.array(y_cls_list, dtype=int)
        sample_weights = np.array(weights, dtype=float)

        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        # Train Poisson GLM + HistGradientBoosting Poisson ensemble for Home & Away Goals
        self.glm_home = PoissonRegressor(alpha=0.8, max_iter=500)
        self.glm_away = PoissonRegressor(alpha=0.8, max_iter=500)
        self.glm_home.fit(X_scaled, yh, sample_weight=sample_weights)
        self.glm_away.fit(X_scaled, ya, sample_weight=sample_weights)

        self.gb_home = HistGradientBoostingRegressor(
            loss="poisson", max_depth=3, learning_rate=0.04, max_iter=85, l2_regularization=2.5, random_state=42
        )
        self.gb_away = HistGradientBoostingRegressor(
            loss="poisson", max_depth=3, learning_rate=0.04, max_iter=85, l2_regularization=2.5, random_state=42
        )
        self.gb_home.fit(X_scaled, yh, sample_weight=sample_weights)
        self.gb_away.fit(X_scaled, ya, sample_weight=sample_weights)

        # Train 1X2 Match Outcome Classifier Ensemble for feature importance & calibration
        self.clf_gb = GradientBoostingClassifier(n_estimators=90, max_depth=3, learning_rate=0.04, random_state=42)
        self.clf_rf = RandomForestClassifier(n_estimators=150, max_depth=5, min_samples_leaf=8, random_state=42)
        self.clf_lr = LogisticRegression(C=0.6, max_iter=500, random_state=42)

        self.clf_gb.fit(X_scaled, y_cls, sample_weight=sample_weights)
        self.clf_rf.fit(X_scaled, y_cls, sample_weight=sample_weights)
        self.clf_lr.fit(X_scaled, y_cls, sample_weight=sample_weights)

        # Evaluate with 5-Fold Stratified Cross-Validation
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        oof_probs = np.zeros((len(y_cls), 3))
        oof_preds = np.zeros(len(y_cls), dtype=int)

        for train_idx, val_idx in skf.split(X_scaled, y_cls):
            lr_cv = LogisticRegression(C=0.6, max_iter=500, random_state=42)
            rf_cv = RandomForestClassifier(n_estimators=120, max_depth=5, min_samples_leaf=8, random_state=42)
            gb_cv = GradientBoostingClassifier(n_estimators=75, max_depth=3, learning_rate=0.04, random_state=42)
            lr_cv.fit(X_scaled[train_idx], y_cls[train_idx])
            rf_cv.fit(X_scaled[train_idx], y_cls[train_idx])
            gb_cv.fit(X_scaled[train_idx], y_cls[train_idx])

            # Blend classifier probabilities with Dixon-Coles Poisson probabilities
            p_clf = 0.45 * lr_cv.predict_proba(X_scaled[val_idx]) + 0.30 * rf_cv.predict_proba(X_scaled[val_idx]) + 0.25 * gb_cv.predict_proba(X_scaled[val_idx])
            oof_probs[val_idx] = p_clf
            oof_preds[val_idx] = np.argmax(p_clf, axis=1)

        # Compute Ranked Probability Score (RPS), Brier Score, Log Loss, Accuracy
        y_onehot = np.eye(3)[y_cls]
        cum_probs = np.cumsum(oof_probs, axis=1)
        cum_true = np.cumsum(y_onehot, axis=1)
        rps = float(np.mean(0.5 * np.sum((cum_probs[:, :2] - cum_true[:, :2]) ** 2, axis=1)))
        brier = float(np.mean(np.sum((oof_probs - y_onehot) ** 2, axis=1)))
        ll = float(log_loss(y_cls, oof_probs))
        acc = float(accuracy_score(y_cls, oof_preds))

        # Compute Feature Importance (blend of RF impurity, GB impurity, and GLM magnitude)
        imp_rf = self.clf_rf.feature_importances_
        imp_gb = self.clf_gb.feature_importances_
        imp_glm = np.abs(self.glm_home.coef_) + np.abs(self.glm_away.coef_)
        imp_glm = imp_glm / imp_glm.sum()
        blended_imp = 0.40 * imp_glm + 0.35 * imp_gb + 0.25 * imp_rf
        blended_imp = blended_imp / blended_imp.sum()

        self.feature_importance = []
        for fname, val in sorted(zip(self.feature_names, blended_imp), key=lambda x: x[1], reverse=True):
            self.feature_importance.append({
                "feature": fname,
                "label": self.feature_labels[fname],
                "importance": round(float(val) * 100.0, 2)
            })

        # Calibration buckets
        calibration_bins = []
        max_p = np.max(oof_probs, axis=1)
        correct = (oof_preds == y_cls).astype(float)
        for low, high in [(0.33, 0.45), (0.45, 0.55), (0.55, 0.65), (0.65, 0.75), (0.75, 0.95)]:
            mask = (max_p >= low) & (max_p < high)
            if mask.sum() > 0:
                calibration_bins.append({
                    "bin": f"{int(low*100)}-{int(high*100)}%",
                    "predicted": round(float(max_p[mask].mean()) * 100, 1),
                    "observed": round(float(correct[mask].mean()) * 100, 1),
                    "count": int(mask.sum())
                })

        self.cv_metrics = {
            "matches_trained": int(len(df_all)),
            "matches_2025_26": int(len(self.df_25_26)),
            "matches_2026_27_live": int(len(self.df_played)),
            "remaining_fixtures": int(len(self.df_rem)),
            "rps": round(rps, 4),
            "brier_score": round(brier, 4),
            "log_loss": round(ll, 4),
            "accuracy_1x2": round(acc * 100.0, 1),
            "dixon_coles_rho": -0.11,
            "calibration": calibration_bins,
            "feature_importance": self.feature_importance,
        }

    def predict_fixture(self, h_code, a_code, team_state=None):
        """Predict expected goals, 1X2 probabilities, and 7x7 scoreline matrix for a single match."""
        ts = team_state if team_state is not None else self.teams_dict
        feats = self._extract_match_features(h_code, a_code, ts)
        feats_scaled = self.scaler.transform(feats.reshape(1, -1))

        # Structural tactical prior + ML Poisson ensemble
        struct_lam_h = feats[1]
        struct_lam_a = feats[2]
        ml_lam_h = 0.55 * self.glm_home.predict(feats_scaled)[0] + 0.45 * self.gb_home.predict(feats_scaled)[0]
        ml_lam_a = 0.55 * self.glm_away.predict(feats_scaled)[0] + 0.45 * self.gb_away.predict(feats_scaled)[0]

        # Blend 60% structural xG/xGA matchup + 40% ML Poisson regressor for calibrated stability,
        # then apply the league scoring-rate calibration constant.
        scale = getattr(self, "lambda_scale", 1.0)
        lam_h = float(np.clip(0.60 * struct_lam_h + 0.40 * ml_lam_h, 0.35, 3.80) * scale)
        lam_a = float(np.clip(0.60 * struct_lam_a + 0.40 * ml_lam_a, 0.25, 3.40) * scale)

        mat = scoreline_matrix(lam_h, lam_a, max_goals=6, rho=-0.11)
        p_home = float(np.sum(np.tril(mat, -1)))
        p_draw = float(np.sum(np.diag(mat)))
        p_away = float(np.sum(np.triu(mat, 1)))

        # Top 5 most likely exact scorelines
        flat_indices = np.argsort(mat.ravel())[::-1][:6]
        top_scores = []
        for idx in flat_indices:
            hg, ag = divmod(int(idx), mat.shape[1])
            top_scores.append({
                "score": f"{hg}-{ag}",
                "home_goals": hg,
                "away_goals": ag,
                "prob": round(float(mat[hg, ag]) * 100.0, 1)
            })

        return {
            "home": h_code,
            "away": a_code,
            "home_name": ts[h_code]["name"],
            "away_name": ts[a_code]["name"],
            "lambda_home": round(lam_h, 2),
            "lambda_away": round(lam_a, 2),
            "prob_home": round(p_home * 100.0, 1),
            "prob_draw": round(p_draw * 100.0, 1),
            "prob_away": round(p_away * 100.0, 1),
            "clean_sheet_home": round(float(mat[:, 0].sum()) * 100.0, 1),
            "clean_sheet_away": round(float(mat[0, :].sum()) * 100.0, 1),
            "btts_prob": round(float(1.0 - mat[0, :].sum() - mat[:, 0].sum() + mat[0, 0]) * 100.0, 1),
            "over_2_5_prob": round(float(sum(mat[i, j] for i in range(7) for j in range(7) if i + j >= 3)) * 100.0, 1),
            "top_scorelines": top_scores,
            "matrix_5x5": [[round(float(mat[i, j]) * 100.0, 2) for j in range(5)] for i in range(5)],
            "features_breakdown": {
                fname: round(float(val), 3) for fname, val in zip(self.feature_names, feats)
            }
        }

    def run_simulation(self, n_sims=5000, scenario=None):
        """
        Vectorized Monte Carlo simulation of the remaining 330 fixtures + player awards.
        scenario dict supports:
          - player_injuries: {player_id: games_out (0-33)}
          - team_boosts: {team_code: {"attack": pct (-25 to +25), "defense": pct (-25 to +25)}}
          - points_deductions: {team_code: pts_deducted (e.g. 10)}
          - custom_scores: {"ARS-MCI": [2, 1], ...}
        """
        t0 = time.time()
        scenario = scenario or {}
        player_injuries = scenario.get("player_injuries", {})
        player_effects = scenario.get("player_effects") or {}
        team_boosts = scenario.get("team_boosts", {})
        points_deductions = scenario.get("points_deductions", {})
        custom_scores = scenario.get("custom_scores", {})

        # Deep copy team states
        ts = {code: dict(meta) for code, meta in self.teams_dict.items() if code in self.df_teams["code"].values}

        # Apply player injury ripple effects onto team attacking/defensive ratings
        players_list = [dict(row) for _, row in self.df_players.iterrows()]
        for p in players_list:
            pid = p["player_id"]
            games_out = int(player_injuries.get(pid, 0))
            p["games_out"] = max(0, min(33, games_out))
            if p["games_out"] > 0 and pid not in player_effects:
                # v1 links keep this legacy formula. New profiles are explicit user hypotheses below.
                frac_missed = p["games_out"] / 33.0
                club = p["club"]
                if p["pos"] in ("FWD", "MID"):
                    # Star attacker/creator absence reduces team xG/90 and Elo proportionally
                    star_weight = (p["xg_90"] + 0.8 * p["xa_90"]) * 0.16
                    ts[club]["xg_90_live"] *= (1.0 - star_weight * frac_missed)
                    ts[club]["elo_live"] -= 42.0 * star_weight * frac_missed
                elif p["pos"] == "GK":
                    # Starting GK absence increases team xGA/90
                    gk_weight = max(0.05, (p["gk_psxg_diff"] + 2.0) * 0.03)
                    ts[club]["xga_90_live"] *= (1.0 + gk_weight * frac_missed)
                    ts[club]["elo_live"] -= 25.0 * gk_weight * frac_missed

        from player_scenarios import club_effects
        remaining_by_club = {c: int(sum((r["home"] == c or r["away"] == c) for r in self.df_rem.to_dict("records"))) for c in ts}
        frozen_effects = club_effects(player_effects, player_injuries, remaining_by_club)
        for club, effect in frozen_effects.items():
            if club in ts:
                ts[club]["xg_90_live"] *= 1-effect["attack"]/100
                ts[club]["xga_90_live"] *= 1+effect["defence"]/100
        # Automatic predictions never load injury news as an input. This branch is user-selected only.

        # Apply manual team attack/defense form boosts.
        # Note: the dashboard sends `defence` (British) while this engine originally read only
        # `defense` — so every defensive form boost from the UI was silently dropped, and a scenario
        # scored differently depending on which engine ran it. Both spellings are accepted now.
        for code, boost in team_boosts.items():
            if code in ts:
                att_pct = float(boost.get("attack", 0.0)) / 100.0
                def_pct = float(boost.get("defense", boost.get("defence", 0.0))) / 100.0
                ts[code]["xg_90_live"] *= (1.0 + att_pct)
                # Positive defense boost lowers xGA
                ts[code]["xga_90_live"] *= (1.0 - def_pct)
                ts[code]["elo_live"] += (att_pct + def_pct) * 85.0

        team_codes = list(self.df_teams["code"].values)
        code_to_idx = {c: i for i, c in enumerate(team_codes)}
        n_teams = len(team_codes)

        # Compute expected goals (lambda_home, lambda_away) for all 330 remaining fixtures in one vectorized batch
        rem_fixtures = self.df_rem.to_dict("records")
        n_rem = len(rem_fixtures)
        h_idx_arr = np.zeros(n_rem, dtype=int)
        a_idx_arr = np.zeros(n_rem, dtype=int)
        fixed_mask = np.zeros(n_rem, dtype=bool)
        fixed_hg = np.zeros(n_rem, dtype=int)
        fixed_ag = np.zeros(n_rem, dtype=int)

        X_rem = np.zeros((n_rem, len(self.feature_names)), dtype=float)
        for k, fix in enumerate(rem_fixtures):
            hc, ac = fix["home"], fix["away"]
            h_idx_arr[k] = code_to_idx[hc]
            a_idx_arr[k] = code_to_idx[ac]
            X_rem[k] = self._extract_match_features(hc, ac, ts)

        X_rem_scaled = self.scaler.transform(X_rem)
        ml_lam_h_all = 0.55 * self.glm_home.predict(X_rem_scaled) + 0.45 * self.gb_home.predict(X_rem_scaled)
        ml_lam_a_all = 0.55 * self.glm_away.predict(X_rem_scaled) + 0.45 * self.gb_away.predict(X_rem_scaled)

        lam_h_arr = np.clip(0.60 * X_rem[:, 1] + 0.40 * ml_lam_h_all, 0.35, 3.80) * self.lambda_scale
        lam_a_arr = np.clip(0.60 * X_rem[:, 2] + 0.40 * ml_lam_a_all, 0.25, 3.40) * self.lambda_scale

        # Track remaining fixture difficulty rating (FDR) and team total expected goals
        team_rem_xg = np.zeros(n_teams, dtype=float)
        team_rem_xga = np.zeros(n_teams, dtype=float)
        team_rem_cs_prob = np.zeros(n_teams, dtype=float)
        team_opp_elo_sum = np.zeros(n_teams, dtype=float)

        for k, fix in enumerate(rem_fixtures):
            hc, ac = fix["home"], fix["away"]
            hi, ai = h_idx_arr[k], a_idx_arr[k]
            lh, la = float(lam_h_arr[k]), float(lam_a_arr[k])

            key = f"{hc}-{ac}"
            if key in custom_scores and len(custom_scores[key]) == 2:
                fixed_mask[k] = True
                fixed_hg[k] = int(custom_scores[key][0])
                fixed_ag[k] = int(custom_scores[key][1])
                lh_eff, la_eff = float(fixed_hg[k]), float(fixed_ag[k])
            else:
                lh_eff, la_eff = lh, la

            team_rem_xg[hi] += lh_eff
            team_rem_xga[hi] += la_eff
            team_rem_xg[ai] += la_eff
            team_rem_xga[ai] += lh_eff

            # Fast analytical Dixon-Coles clean sheet probabilities
            cs_h = np.exp(-la) * (1.0 - 0.11 * lh * la * np.exp(-lh))
            cs_a = np.exp(-lh) * (1.0 - 0.11 * lh * la * np.exp(-la))
            team_rem_cs_prob[hi] += float(np.clip(cs_h, 0.03, 0.72))
            team_rem_cs_prob[ai] += float(np.clip(cs_a, 0.02, 0.65))
            team_opp_elo_sum[hi] += ts[ac]["elo_live"]
            team_opp_elo_sum[ai] += ts[hc]["elo_live"]

        # Vectorized Monte Carlo sampling (n_sims x 330 fixtures)
        rng = np.random.default_rng(20261002)
        sim_hg = rng.poisson(lam_h_arr, size=(n_sims, n_rem))
        sim_ag = rng.poisson(lam_a_arr, size=(n_sims, n_rem))

        if np.any(fixed_mask):
            sim_hg[:, fixed_mask] = fixed_hg[fixed_mask]
            sim_ag[:, fixed_mask] = fixed_ag[fixed_mask]

        # Initialize team season totals from current GW5 standings
        init_pts = np.array([ts[c]["Pts"] - int(points_deductions.get(c, 0)) for c in team_codes], dtype=int)
        init_gf = np.array([ts[c]["GF"] for c in team_codes], dtype=int)
        init_ga = np.array([ts[c]["GA"] for c in team_codes], dtype=int)
        init_w = np.array([ts[c]["W"] for c in team_codes], dtype=int)
        init_d = np.array([ts[c]["D"] for c in team_codes], dtype=int)
        init_l = np.array([ts[c]["L"] for c in team_codes], dtype=int)

        tot_pts = np.tile(init_pts, (n_sims, 1))
        tot_gf = np.tile(init_gf, (n_sims, 1))
        tot_ga = np.tile(init_ga, (n_sims, 1))
        tot_w = np.tile(init_w, (n_sims, 1))
        tot_d = np.tile(init_d, (n_sims, 1))
        tot_l = np.tile(init_l, (n_sims, 1))

        h_win = (sim_hg > sim_ag).astype(int)
        draw = (sim_hg == sim_ag).astype(int)
        a_win = (sim_hg < sim_ag).astype(int)

        h_pts = 3 * h_win + draw
        a_pts = 3 * a_win + draw

        # Aggregate across all 330 fixtures per simulation
        for k in range(n_rem):
            hi = h_idx_arr[k]
            ai = a_idx_arr[k]
            tot_pts[:, hi] += h_pts[:, k]
            tot_pts[:, ai] += a_pts[:, k]
            tot_gf[:, hi] += sim_hg[:, k]
            tot_ga[:, hi] += sim_ag[:, k]
            tot_gf[:, ai] += sim_ag[:, k]
            tot_ga[:, ai] += sim_hg[:, k]
            tot_w[:, hi] += h_win[:, k]
            tot_d[:, hi] += draw[:, k]
            tot_l[:, hi] += a_win[:, k]
            tot_w[:, ai] += a_win[:, k]
            tot_d[:, ai] += draw[:, k]
            tot_l[:, ai] += h_win[:, k]

        tot_gd = tot_gf - tot_ga
        # Composite sort key: Pts * 1e6 + GD * 1e3 + GF + tiny random tiebreaker
        sort_score = tot_pts * 1e6 + tot_gd * 1e3 + tot_gf + rng.uniform(0, 0.1, size=tot_pts.shape)
        order = np.argsort(-sort_score, axis=1)
        ranks = np.empty_like(order)
        rows_grid = np.arange(n_sims)[:, None]
        ranks[rows_grid, order] = np.arange(1, n_teams + 1)

        # Build projected league table summary
        table_projections = []
        for i, code in enumerate(team_codes):
            r_i = ranks[:, i]
            pts_i = tot_pts[:, i]
            gd_i = tot_gd[:, i]
            gf_i = tot_gf[:, i]
            ga_i = tot_ga[:, i]
            pos_dist = [round(float(np.mean(r_i == pos)) * 100.0, 1) for pos in range(1, n_teams + 1)]
            fdr_score = round(((team_opp_elo_sum[i] / 33.0) - 1650.0) / 2.5, 1)

            table_projections.append({
                "code": code,
                "name": ts[code]["name"],
                "short": ts[code]["short"],
                "manager": ts[code]["manager"],
                "stadium": ts[code]["stadium"],
                "primary_color": ts[code]["primary_color"],
                "europe": ts[code]["europe"],
                "current_pos": int(ts[code]["current_pos"]),
                "curr_p": int(ts[code]["P"]),
                "curr_w": int(ts[code]["W"]),
                "curr_d": int(ts[code]["D"]),
                "curr_l": int(ts[code]["L"]),
                "curr_gf": int(ts[code]["GF"]),
                "curr_ga": int(ts[code]["GA"]),
                "curr_gd": int(ts[code]["GD"]),
                "curr_pts": int(ts[code]["Pts"]),
                "points_deduction": int(points_deductions.get(code, 0)),
                "form": ts[code]["form"],
                "elo_live": round(float(ts[code]["elo_live"]), 1),
                "xg_90_live": round(float(ts[code]["xg_90_live"]), 2),
                "xga_90_live": round(float(ts[code]["xga_90_live"]), 2),
                "proj_w": round(float(tot_w[:, i].mean()), 1),
                "proj_d": round(float(tot_d[:, i].mean()), 1),
                "proj_l": round(float(tot_l[:, i].mean()), 1),
                "proj_gf": round(float(gf_i.mean()), 1),
                "proj_ga": round(float(ga_i.mean()), 1),
                "proj_gd": round(float(gd_i.mean()), 1),
                "proj_pts": round(float(pts_i.mean()), 1),
                "proj_pts_int": int(round(float(pts_i.mean()))),
                "pts_p10": int(np.percentile(pts_i, 10)),
                "pts_p90": int(np.percentile(pts_i, 90)),
                "title_prob": round(float(np.mean(r_i == 1)) * 100.0, 1),
                "top4_prob": round(float(np.mean(r_i <= 4)) * 100.0, 1),
                "top5_ucl_prob": round(float(np.mean(r_i <= 5)) * 100.0, 1),
                "europe_prob": round(float(np.mean(r_i <= 7)) * 100.0, 1),
                "relegation_prob": round(float(np.mean(r_i >= 18)) * 100.0, 1),
                "fdr_remaining": fdr_score,
                "pos_distribution": pos_dist,
            })

        table_projections.sort(key=lambda x: (x["proj_pts"], x["proj_gd"], x["proj_gf"]), reverse=True)
        for rank_idx, row in enumerate(table_projections, 1):
            row["proj_pos"] = rank_idx
            row["pos_delta"] = row["current_pos"] - rank_idx

        # ------------------------------------------------------------------
        # Player Awards Monte Carlo Simulation (Golden Boot, Assists, Clean Sheets)
        # ------------------------------------------------------------------
        outfield_players = [p for p in players_list if p["pos"] != "GK"]
        gk_players = [p for p in players_list if p["pos"] == "GK"]

        # Simulate Outfield Goals & Assists across remaining 33 games
        n_out = len(outfield_players)
        sim_goals = np.zeros((n_sims, n_out), dtype=float)
        sim_assists = np.zeros((n_sims, n_out), dtype=float)
        exp_rem_goals_arr = np.zeros(n_out, dtype=float)
        exp_rem_assists_arr = np.zeros(n_out, dtype=float)

        for j, p in enumerate(outfield_players):
            ci = code_to_idx[p["club"]]
            avail_games = max(0.0, (33.0 - p["games_out"]) * p["mins_prob"])
            # Team offensive multiplier relative to baseline
            team_mult = (team_rem_xg[ci] / 33.0) / max(0.9, self.teams_dict[p["club"]]["xg_90_base"])

            # Expected goals per 90 blended with conversion skill + penalty duty + empirical Bayes shrinkage
            conv_factor = (p["shot_conv"] / 0.19) ** 0.35
            g_rate = (0.82 * p["xg_90"] * conv_factor + 0.06 * p["pen_share"]) * (team_mult ** 0.85)
            exp_rem_g = avail_games * g_rate
            exp_rem_goals_arr[j] = exp_rem_g

            # Expected assists per 90 blended with key passes & team scoring rate
            a_rate = (0.72 * p["xa_90"] + 0.28 * (p["kp_90"] / 8.8)) * (team_mult ** 0.85)
            exp_rem_a = avail_games * a_rate
            exp_rem_assists_arr[j] = exp_rem_a

            # Negative Binomial / Gamma-Poisson overdispersed simulation for realistic player variance
            gamma_g = rng.gamma(shape=14.0, scale=1.0 / 14.0, size=n_sims)
            gamma_a = rng.gamma(shape=14.0, scale=1.0 / 14.0, size=n_sims)
            sim_goals[:, j] = p["goals_curr"] + rng.poisson(exp_rem_g * gamma_g)
            sim_assists[:, j] = p["assists_curr"] + rng.poisson(exp_rem_a * gamma_a)

        # Golden Boot winner per simulation (with slight tie-breaking by assists/mins)
        gb_tiebreak = sim_goals + 0.001 * sim_assists + rng.uniform(0, 0.0001, size=sim_goals.shape)
        gb_winners = np.argmax(gb_tiebreak, axis=1)

        # Playmaker (Top Assists) winner per simulation
        pm_tiebreak = sim_assists + 0.001 * sim_goals + rng.uniform(0, 0.0001, size=sim_assists.shape)
        pm_winners = np.argmax(pm_tiebreak, axis=1)

        golden_boot_race = []
        playmaker_race = []
        poty_candidates = []

        team_proj_lookup = {row["code"]: row for row in table_projections}

        for j, p in enumerate(outfield_players):
            g_tot = sim_goals[:, j]
            a_tot = sim_assists[:, j]
            gb_prob = round(float(np.mean(gb_winners == j)) * 100.0, 1)
            pm_prob = round(float(np.mean(pm_winners == j)) * 100.0, 1)
            club_info = team_proj_lookup[p["club"]]

            proj_g = round(float(g_tot.mean()), 1)
            proj_a = round(float(a_tot.mean()), 1)
            proj_gi = round(proj_g + proj_a, 1)

            # PFA Player of the Year Composite Index (Goals + Assists + Team Title/Top4 success)
            poty_score = (
                proj_g * 2.1
                + proj_a * 1.75
                + club_info["title_prob"] * 0.32
                + club_info["top4_prob"] * 0.12
                + (club_info["proj_pts"] - 50.0) * 0.35
            )

            player_entry = {
                "player_id": p["player_id"],
                "name": p["name"],
                "club": p["club"],
                "club_name": club_info["short"],
                "primary_color": club_info["primary_color"],
                "pos": p["pos"],
                "nation": p["nation"],
                "games_out": p["games_out"],
                "goals_curr": int(p["goals_curr"]),
                "assists_curr": int(p["assists_curr"]),
                "goals_prev": int(p["goals_prev"]),
                "assists_prev": int(p["assists_prev"]),
                "goals_prev_verified": bool(p.get("goals_prev_verified", False)),
                "assists_prev_verified": bool(p.get("assists_prev_verified", False)),
                "xg_90": round(float(p["xg_90"]), 2),
                "xa_90": round(float(p["xa_90"]), 2),
                "kp_90": round(float(p["kp_90"]), 1),
                "shot_conv": round(float(p["shot_conv"]) * 100.0, 1),
                "pen_taker": bool(p["pen_share"] >= 0.5),
                "proj_rem_goals": round(float(exp_rem_goals_arr[j]), 1),
                "proj_goals": proj_g,
                "proj_goals_int": int(round(proj_g)),
                "goals_p10": int(np.percentile(g_tot, 10)),
                "goals_p90": int(np.percentile(g_tot, 90)),
                "golden_boot_prob": gb_prob,
                "proj_rem_assists": round(float(exp_rem_assists_arr[j]), 1),
                "proj_assists": proj_a,
                "proj_assists_int": int(round(proj_a)),
                "assists_p10": int(np.percentile(a_tot, 10)),
                "assists_p90": int(np.percentile(a_tot, 90)),
                "playmaker_prob": pm_prob,
                "proj_gi": proj_gi,
                "poty_index": round(float(poty_score), 1),
            }
            golden_boot_race.append(player_entry)
            playmaker_race.append(player_entry)
            poty_candidates.append(player_entry)

        golden_boot_race.sort(key=lambda x: (x["proj_goals"], x["golden_boot_prob"], x["goals_curr"]), reverse=True)
        playmaker_race.sort(key=lambda x: (x["proj_assists"], x["playmaker_prob"], x["assists_curr"]), reverse=True)
        poty_candidates.sort(key=lambda x: x["poty_index"], reverse=True)

        # Normalize POTY win probability across top candidates
        poty_top = poty_candidates[:10]
        poty_logits = np.array([c["poty_index"] for c in poty_top])
        poty_exp = np.exp((poty_logits - poty_logits.max()) / 6.5)
        poty_probs = poty_exp / poty_exp.sum()
        for c, pr in zip(poty_top, poty_probs):
            c["poty_prob"] = round(float(pr) * 100.0, 1)

        # Simulate Goalkeeper Clean Sheets (Golden Glove)
        n_gk = len(gk_players)
        sim_cs = np.zeros((n_sims, n_gk), dtype=float)
        exp_rem_cs_arr = np.zeros(n_gk, dtype=float)

        for j, gk in enumerate(gk_players):
            ci = code_to_idx[gk["club"]]
            avail_frac = max(0.0, (33.0 - gk["games_out"]) / 33.0) * gk["mins_prob"]
            # GK shot-stopping skill multiplier from PSxG-GA
            gk_skill_mult = 1.0 + (gk["gk_psxg_diff"] * 0.028)
            exp_rem_cs = team_rem_cs_prob[ci] * avail_frac * gk_skill_mult
            exp_rem_cs = float(np.clip(exp_rem_cs, 0.0, 26.0))
            exp_rem_cs_arr[j] = exp_rem_cs

            # Binomial draws across remaining available matches
            n_avail_games = int(round(33 * avail_frac))
            p_cs_per_game = np.clip(exp_rem_cs / max(1, n_avail_games), 0.02, 0.75)
            sim_cs[:, j] = gk["cs_curr"] + rng.binomial(n_avail_games, p_cs_per_game, size=n_sims)

        gg_tiebreak = sim_cs + rng.uniform(0, 0.01, size=sim_cs.shape)
        gg_winners = np.argmax(gg_tiebreak, axis=1)

        golden_glove_race = []
        for j, gk in enumerate(gk_players):
            cs_tot = sim_cs[:, j]
            gg_prob = round(float(np.mean(gg_winners == j)) * 100.0, 1)
            club_info = team_proj_lookup[gk["club"]]
            proj_cs = round(float(cs_tot.mean()), 1)

            golden_glove_race.append({
                "player_id": gk["player_id"],
                "name": gk["name"],
                "club": gk["club"],
                "club_name": club_info["short"],
                "primary_color": club_info["primary_color"],
                "nation": gk["nation"],
                "games_out": gk["games_out"],
                "cs_curr": int(gk["cs_curr"]),
                "cs_prev": int(gk["cs_prev"]),
                "gk_psxg_diff": round(float(gk["gk_psxg_diff"]), 1),
                "save_pct": round(float(gk["save_pct"]), 1),
                "team_xga_90": club_info["xga_90_live"],
                "proj_rem_cs": round(float(exp_rem_cs_arr[j]), 1),
                "proj_cs": proj_cs,
                "proj_cs_int": int(round(proj_cs)),
                "cs_p10": int(np.percentile(cs_tot, 10)),
                "cs_p90": int(np.percentile(cs_tot, 90)),
                "golden_glove_prob": gg_prob,
            })

        golden_glove_race.sort(key=lambda x: (x["proj_cs"], x["golden_glove_prob"], x["cs_curr"]), reverse=True)

        # "As of" state. `data/as_of.json` is written by update_week.py when a gameweek is promoted;
        # without it (a fresh checkout, or a hand-edited dataset) the documented baseline is used.
        as_of_label, last_completed_gw = as_of_state(self.df_played)

        # Upcoming matchweeks — derived from the remaining fixtures, never hardcoded. After MW6 is
        # played the old gw==6 literal would silently return an empty list and the weekly job would
        # publish a snapshot with no predictions in it.
        remaining_gws = sorted({int(f["gw"]) for f in rem_fixtures})
        next_gw = remaining_gws[0] if remaining_gws else None
        after_gw = remaining_gws[1] if len(remaining_gws) > 1 else None

        def predict_gameweek(gw):
            if gw is None:
                return []
            out = []
            for f in [x for x in rem_fixtures if int(x["gw"]) == gw]:
                p = self.predict_fixture(f["home"], f["away"], ts)
                p["gw"] = int(f["gw"])
                p["dates"] = f["dates"]
                out.append(p)
            return out

        next_gw_predictions = predict_gameweek(next_gw)
        after_gw_predictions = predict_gameweek(after_gw)

        # ── every remaining fixture, compact (P5.4) ──────────────────────────────────────────────
        # The dashboard only ever shows the next two gameweeks, so the payload carries two. The
        # crawlable gameweek pages (site_pages.py) need all 330, and so does anyone who wants this as
        # data rather than as a chart. Kept out of the summary JSON deliberately — it is written to
        # data/projected_fixtures_2026_27.csv instead, so the page that every visitor downloads does
        # not grow by 60 KB to serve a crawler.
        projected_fixtures = []
        for f in rem_fixtures:
            p_fx = self.predict_fixture(f["home"], f["away"], ts)
            top = p_fx["top_scorelines"][0] if p_fx.get("top_scorelines") else {"score": "", "prob": ""}
            row = {k: p_fx[k] for k in ("lambda_home", "lambda_away", "prob_home", "prob_draw",
                                        "prob_away", "clean_sheet_home", "clean_sheet_away",
                                        "btts_prob", "over_2_5_prob")}
            row.update({"fixture_id": int(f.get("fixture_id", 0)), "gw": int(f["gw"]),
                        "dates": f["dates"], "home": f["home"], "away": f["away"],
                        "top_score": top["score"], "top_score_prob": top["prob"]})
            projected_fixtures.append(row)
        projected_fixtures.sort(key=lambda r: (r["gw"], -r["prob_home"]))
        gw6_predictions = next_gw_predictions      # legacy key: the dashboard reads this
        gw7_predictions = after_gw_predictions

        # Key Blockbuster Title / Top 4 Clashes Remaining
        marquee_pairs = [
            ("ARS", "MCI"), ("MCI", "ARS"), ("LIV", "MCI"), ("ARS", "LIV"),
            ("CHE", "ARS"), ("MUN", "ARS"), ("LIV", "MUN"), ("BHA", "MCI")
        ]
        marquee_predictions = []
        for hc, ac in marquee_pairs:
            p_fix = self.predict_fixture(hc, ac, ts)
            key = f"{hc}-{ac}"
            if key in custom_scores:
                p_fix["custom_score"] = custom_scores[key]
            marquee_predictions.append(p_fix)

        elapsed_ms = round((time.time() - t0) * 1000.0, 1)

        return {
            "meta": {
                "season": "2026–27 Premier League",
                "as_of_date": as_of_label,
                "last_completed_gw": last_completed_gw,
                "next_gw": next_gw,
                "after_gw": after_gw,
                "next_matchweek": {"gw": next_gw,
                                   "dates": (next_gw_predictions[0]["dates"] if next_gw_predictions else None)},
                "fixture_calendar": "Official Premier League 2026-27 fixture release (19 June 2026)",
                "n_simulations": n_sims,
                "runtime_ms": elapsed_ms,
                "lambda_scale": round(float(self.lambda_scale), 4),
                "scenario_active": bool(player_injuries or team_boosts or points_deductions or custom_scores),
                "player_signal": self.player_signal_status,
                "player_ui": self.player_ui_status,
                "manual_player_effects": frozen_effects,
            },
            "headline_predictions": {
                "champion": table_projections[0],
                "runner_up": table_projections[1],
                "golden_boot": golden_boot_race[0],
                "playmaker": playmaker_race[0],
                "golden_glove": golden_glove_race[0],
                "poty": poty_top[0],
            },
            "table_projections": table_projections,
            "golden_boot_race": golden_boot_race[:18],
            "playmaker_race": playmaker_race[:18],
            "golden_glove_race": golden_glove_race[:16],
            "poty_race": poty_top[:10],
            "gw6_predictions": gw6_predictions,
            "gw7_predictions": gw7_predictions,
            "next_gw_predictions": next_gw_predictions,
            "after_gw_predictions": after_gw_predictions,
            "marquee_predictions": marquee_predictions,
            "ml_metrics": self.cv_metrics,
            # Private: popped and written to CSV by __main__ before the summary is serialised.
            "_projected_fixtures": projected_fixtures,
        }


if __name__ == "__main__":
    import sys

    force = "--force-retrain" in sys.argv or FORCE_RETRAIN
    engine = PremierLeagueMLEngine(force_retrain=force)
    res = engine.baseline_results
    print("engine boot: %.2fs (%s)" % (
        engine.boot_ms / 1000.0,
        "artifact cache hit" if engine.cache_hit
        else "trained from scratch" + (" + cache written" if getattr(engine, "cache_written", False) else ""),
    ))
    # Export CSV & JSON artifacts
    pd.DataFrame(res["table_projections"]).drop(columns=["pos_distribution"]).to_csv(
        os.path.join(DATA_DIR, "projected_table_2026_27.csv"), index=False
    )
    pd.DataFrame(res["golden_boot_race"]).to_csv(
        os.path.join(DATA_DIR, "projected_golden_boot_2026_27.csv"), index=False
    )
    pd.DataFrame(res["playmaker_race"]).to_csv(
        os.path.join(DATA_DIR, "projected_playmaker_2026_27.csv"), index=False
    )
    pd.DataFrame(res["golden_glove_race"]).to_csv(
        os.path.join(DATA_DIR, "projected_golden_glove_2026_27.csv"), index=False
    )
    # Every remaining fixture with its projection: the crawlable-content export (P5.4). Written with
    # the shared writer so a no-op rebuild keeps the bytes identical, then removed from `res` so the
    # dashboard payload does not carry it.
    from dataset_io import write_dataset
    projected = res.pop("_projected_fixtures", [])
    if projected:
        fields = ["fixture_id", "gw", "dates", "home", "away", "lambda_home", "lambda_away",
                  "prob_home", "prob_draw", "prob_away", "clean_sheet_home", "clean_sheet_away",
                  "btts_prob", "over_2_5_prob", "top_score", "top_score_prob"]
        write_dataset(DATA_DIR, {"projected_fixtures_2026_27.csv":
                                 ([{k: r[k] for k in fields} for r in projected], fields)})
        print(f"Projected all {len(projected)} remaining fixtures -> projected_fixtures_2026_27.csv")
    with open(os.path.join(DATA_DIR, "predictions_2026_27_summary.json"), "w") as f:
        json.dump(json_safe(res), f, indent=2, allow_nan=False)

    print(f"Simulation completed in {res['meta']['runtime_ms']} ms across {res['meta']['n_simulations']} simulations.")
    print("\n--- TOP 6 PROJECTED 2026-27 PREMIER LEAGUE TABLE ---")
    for row in res["table_projections"][:6]:
        print(f"{row['proj_pos']:2d}. {row['name']:24s} Curr:{row['curr_pts']:2d} -> Proj:{row['proj_pts']:5.1f} pts ({row['pts_p10']}-{row['pts_p90']}) | Title:{row['title_prob']:5.1f}% | Top4:{row['top4_prob']:5.1f}%")
    print("\n--- BOTTOM 4 RELEGATION PROJECTION ---")
    for row in res["table_projections"][-4:]:
        print(f"{row['proj_pos']:2d}. {row['name']:24s} Curr:{row['curr_pts']:2d} -> Proj:{row['proj_pts']:5.1f} pts | Relegation:{row['relegation_prob']:5.1f}%")
    print("\n--- GOLDEN BOOT TOP 5 ---")
    for p in res["golden_boot_race"][:5]:
        print(f" - {p['name']:22s} ({p['club']}) Curr:{p['goals_curr']} -> Proj:{p['proj_goals']:4.1f} goals | Win Prob:{p['golden_boot_prob']:5.1f}%")
    print("\n--- PLAYMAKER (TOP ASSISTS) TOP 5 ---")
    for p in res["playmaker_race"][:5]:
        print(f" - {p['name']:22s} ({p['club']}) Curr:{p['assists_curr']} -> Proj:{p['proj_assists']:4.1f} assists | Win Prob:{p['playmaker_prob']:5.1f}%")
    print("\n--- GOLDEN GLOVE (CLEAN SHEETS) TOP 5 ---")
    for g in res["golden_glove_race"][:5]:
        print(f" - {g['name']:22s} ({g['club']}) Curr:{g['cs_curr']} -> Proj:{g['proj_cs']:4.1f} CS | Win Prob:{g['golden_glove_prob']:5.1f}%")
    print("\n--- ML CROSS-VALIDATION METRICS ---")
    print(json.dumps({k: v for k, v in res["ml_metrics"].items() if k not in ("calibration", "feature_importance")}, indent=2))
