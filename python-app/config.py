"""
CD Map Tracker — Configuration & Constants
"""

import os

VERSION = "1.0.0"
PROCESS_NAME = "CrimsonDesert.exe"
WS_PORT = 17835
WS_HOST = "127.0.0.1"

SAVE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CD_MapTracker")
WAYPOINT_FILE = os.path.join(SAVE_DIR, "cd_waypoints.json")
SETTINGS_FILE = os.path.join(SAVE_DIR, "cd_settings.json")
POINTER_CHAIN_FILE = os.path.join(SAVE_DIR, "pointer_chains.json")

MAPGENIE_URL = "https://mapgenie.io/crimson-desert/maps/pywel"

# Height threshold: player Y > this means Abyss realm
ABYSS_HEIGHT_THRESHOLD = 1400.0

# Per-realm calibration files
CALIBRATION_FILES = {
    "pywel": os.path.join(SAVE_DIR, "cd_calibration_pywel.json"),
    "abyss": os.path.join(SAVE_DIR, "cd_calibration_abyss.json"),
}

# Default calibration points per realm (from reference mod)
DEFAULT_CALIBRATIONS = {
    "pywel": [
        {"game": [-12127.138259887695, 7.692434787750244],
         "map": [-0.9052420615140191, 0.7787327582867241]},
        {"game": [-3690.7935791015625, -6117.512298583984],
         "map": [-0.5555426902317491, 0.5248899410143244]},
    ],
    "abyss": [
        {"game": [-10679.2001953125, -3686.5693359375],
         "map": [-1.3021820027444733, 0.6476022163899415]},
        {"game": [-12273.085479736328, -4988.257263183594],
         "map": [-1.3517201468401367, 0.6072151985198246]},
    ],
}

# Community waypoints Google Sheets integration
SHARED_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRuCTPOpKood_wCToItMFiGYMjL4FxP6CAOWxNzcZKoNI3WUU06OmBqyECASUJ8SUSqh2KvPXaG-s6-"
    "/pub?gid=1303005004&single=true&output=csv"
)
FORM_SUBMIT_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLScdrT1RU4EKKOsbCpt5j2BUTpJEocbc7L4xR53lCDzpjrDfbQ/formResponse"
)
FORM_FIELDS = {
    "name": "entry.2135530741",
    "x": "entry.1438084253",
    "y": "entry.2086854493",
    "z": "entry.1815075034",
}

# AOB signatures (from reference mod's CE table)
AOB_ENTITY = b'\x48\x8B\x06\x0F\x11\x88\xB0\x01\x00\x00'
AOB_POS    = b'\x0F\x11\x99\x90\x00\x00\x00'
AOB_WORLD  = b'\x0F\x5C\x1D'  # prefix for world-offset SUBPS instruction

# Position update broadcast interval (seconds)
BROADCAST_INTERVAL = 0.5
