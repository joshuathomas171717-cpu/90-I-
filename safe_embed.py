"""HTML-script-safe JSON. DOM escaping is too late if a string closes the script element."""
import json


def script_json(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False).replace(
        "<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
