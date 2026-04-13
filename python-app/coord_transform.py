"""
CD Map Tracker — Coordinate Transform
Converts between game world coordinates and MapGenie lng/lat.
"""

import json
import os
from config import CALIBRATION_FILES, DEFAULT_CALIBRATIONS, SAVE_DIR, ABYSS_HEIGHT_THRESHOLD


def load_calibration(realm="pywel"):
    """Load coordinate calibration for a realm from file, or return defaults."""
    cal_file = CALIBRATION_FILES[realm]
    try:
        with open(cal_file, "r") as f:
            cal = json.load(f)
            if len(cal) >= 2:
                return cal
    except Exception:
        pass
    return list(DEFAULT_CALIBRATIONS[realm])


def save_calibration(cal, realm="pywel"):
    os.makedirs(SAVE_DIR, exist_ok=True)
    with open(CALIBRATION_FILES[realm], "w") as f:
        json.dump(cal, f, indent=2)


def _build_coord_transform(cal):
    """Build linear transform coefficients from 2 calibration points.

    Returns (scale_x, offset_x, scale_z, offset_z) such that:
        lng = game_x * scale_x + offset_x
        lat = game_z * scale_z + offset_z
    """
    p0, p1 = cal[0], cal[1]
    gx0, gz0 = p0["game"]
    lng0, lat0 = p0["map"]
    gx1, gz1 = p1["game"]
    lng1, lat1 = p1["map"]

    dx = gx1 - gx0
    dz = gz1 - gz0
    if abs(dx) < 1e-6 or abs(dz) < 1e-6:
        return 1.0, 0.0, 1.0, 0.0

    scale_x = (lng1 - lng0) / dx
    offset_x = lng0 - gx0 * scale_x
    scale_z = (lat1 - lat0) / dz
    offset_z = lat0 - gz0 * scale_z
    return scale_x, offset_x, scale_z, offset_z


def game_to_lnglat(gx, gz, cal):
    """Convert game (x, z) to MapGenie (lng, lat)."""
    sx, ox, sz, oz = _build_coord_transform(cal)
    return gx * sx + ox, gz * sz + oz


def lnglat_to_game(lng, lat, cal):
    """Convert MapGenie (lng, lat) to game (x, z)."""
    sx, ox, sz, oz = _build_coord_transform(cal)
    if abs(sx) < 1e-12 or abs(sz) < 1e-12:
        return 0.0, 0.0
    return (lng - ox) / sx, (lat - oz) / sz


def detect_realm(player_y):
    """Return 'abyss' if player Y is above threshold, else 'pywel'."""
    return "abyss" if player_y > ABYSS_HEIGHT_THRESHOLD else "pywel"
