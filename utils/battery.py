import json
import os
import subprocess

_BATTERY_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "battery.json")

_DEFAULTS = {
    "enabled": False,
    "minPercentage": 15,
    "checkInterval": [240, 360],
    "respectPlugged": True,
}


def load_battery(path=None):
    target = path if path else _BATTERY_PATH
    try:
        with open(target, "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_DEFAULTS)
    if not isinstance(data, dict):
        return dict(_DEFAULTS)

    result = dict(_DEFAULTS)

    enabled = data.get("enabled", _DEFAULTS["enabled"])
    result["enabled"] = enabled if isinstance(enabled, bool) else _DEFAULTS["enabled"]

    minp = data.get("minPercentage", _DEFAULTS["minPercentage"])
    if isinstance(minp, bool) or not isinstance(minp, (int, float)) or minp < 0 or minp > 100:
        result["minPercentage"] = _DEFAULTS["minPercentage"]
    else:
        result["minPercentage"] = minp

    interval = data.get("checkInterval", _DEFAULTS["checkInterval"])
    if (
        isinstance(interval, list)
        and len(interval) == 2
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in interval)
        and interval[0] <= interval[1]
    ):
        result["checkInterval"] = interval
    else:
        result["checkInterval"] = _DEFAULTS["checkInterval"]

    rp = data.get("respectPlugged", _DEFAULTS["respectPlugged"])
    result["respectPlugged"] = rp if isinstance(rp, bool) else _DEFAULTS["respectPlugged"]

    return result


def parse_battery_status(raw):
    if not isinstance(raw, dict):
        return None
    pct = raw.get("percentage", raw.get("level"))
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        return None
    pct = int(pct)
    if pct < 0 or pct > 100:
        return None
    plugged = raw.get("plugged")
    if isinstance(plugged, str):
        plugged_norm = plugged.strip().upper() == "PLUGGED"
    elif isinstance(plugged, bool):
        plugged_norm = plugged
    else:
        return None
    return {"percentage": pct, "plugged": plugged_norm}


def should_pause(status, cfg):
    if not isinstance(status, dict):
        return False
    pct = status.get("percentage")
    plugged = status.get("plugged")
    if pct is None or plugged is None:
        return False
    minp = cfg.get("minPercentage", _DEFAULTS["minPercentage"])
    respect = cfg.get("respectPlugged", _DEFAULTS["respectPlugged"])
    if pct < minp:
        if respect:
            return not plugged
        return True
    return False


def _is_termux():
    return os.path.exists("/data/data/com.termux")


def get_battery_status():
    try:
        if _is_termux():
            proc = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=10)
            if proc.returncode != 0:
                return None
            return parse_battery_status(json.loads(proc.stdout))
        try:
            import psutil
        except Exception:
            return None
        battery = psutil.sensors_battery()
        if battery is None:
            return None
        return parse_battery_status({"percentage": int(battery.percent), "plugged": bool(battery.power_plugged)})
    except Exception:
        return None
