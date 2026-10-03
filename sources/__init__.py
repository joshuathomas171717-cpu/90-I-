"""sources — the adapter layer (P2.2).

    from sources import get_provider
    p = get_provider()                  # auto: live provider if a key exists, else local
    p = get_provider("football-data.org")
    p.fetch_results()                   # -> normalised rows, whatever the provider

Selection order for `auto`:

1. `NT90_SOURCE` environment variable (an explicit provider name always wins);
2. `football-data.org`, if `FOOTBALL_DATA_ORG_TOKEN` / `FOOTBALL_DATA_API_KEY` is set;
3. `local` — the pipeline's own CSVs, so the weekly job still runs with no account at all.

Nothing here is imported at module import time by the pipeline: the adapter loads lazily so a missing
key can never break the build.
"""
from .base import Provider, team_code, cache_raw, latest_raw, RAW_DIR, SEASON_LABEL, SEASON_YEAR

PROVIDERS = {
    "football-data.org": "sources.football_data_org:FootballDataOrgProvider",
    "local": "sources.local_snapshot:LocalSnapshotProvider",
}


def _load(spec):
    module_name, cls_name = spec.split(":")
    module = __import__(module_name, fromlist=[cls_name])
    return getattr(module, cls_name)


def available_providers():
    out = {}
    for name, spec in PROVIDERS.items():
        try:
            instance = _load(spec)()
            out[name] = instance.describe()
        except Exception as exc:                                  # a broken provider must not break this
            out[name] = {"name": name, "available": False, "unavailable_reason": str(exc)}
    return out


def get_provider(name=None, offline=False, **kwargs):
    """Return a provider instance. `name=None` means auto-select (see the module docstring)."""
    import os
    name = name or os.environ.get("NT90_SOURCE")
    if name:
        if name not in PROVIDERS:
            raise ValueError("unknown provider %r — known: %s" % (name, ", ".join(sorted(PROVIDERS))))
        try:
            return _load(PROVIDERS[name])(offline=offline, **kwargs)
        except TypeError:
            return _load(PROVIDERS[name])(**kwargs)

    live = _load(PROVIDERS["football-data.org"])(offline=offline)
    if live.available():
        return live
    return _load(PROVIDERS["local"])(offline=offline)


__all__ = ["get_provider", "available_providers", "Provider", "team_code",
           "cache_raw", "latest_raw", "RAW_DIR", "SEASON_LABEL", "SEASON_YEAR"]
