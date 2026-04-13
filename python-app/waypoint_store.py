"""
CD Map Tracker — Waypoint Store
Manages local and community waypoints. Compatible with reference mod format.
"""

import json
import os
import re
import time
import logging
from urllib.request import urlopen, Request
from urllib.parse import quote_plus

from config import (
    SAVE_DIR, WAYPOINT_FILE, SHARED_CSV_URL, FORM_SUBMIT_URL, FORM_FIELDS,
)

log = logging.getLogger("waypoints")


class WaypointStore:
    def __init__(self):
        self.local = []
        self.shared = []
        os.makedirs(SAVE_DIR, exist_ok=True)

    def load(self):
        if not os.path.exists(WAYPOINT_FILE):
            return
        try:
            with open(WAYPOINT_FILE, "r", encoding="utf-8") as f:
                self.local = json.load(f)
        except Exception:
            self.local = []

    def save(self):
        with open(WAYPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(self.local, f, indent=2, ensure_ascii=False)

    def add(self, name, x, y, z):
        self.local.append({"name": name, "absX": x, "absY": y, "absZ": z})
        self.save()

    def delete(self, index):
        if 0 <= index < len(self.local):
            self.local.pop(index)
            self.save()

    def rename(self, index, new_name):
        if 0 <= index < len(self.local):
            self.local[index]["name"] = new_name
            self.save()

    def fetch_shared(self):
        """Fetch community waypoints from Google Sheets."""
        try:
            url = f"{SHARED_CSV_URL}&_t={int(time.time())}"
            req = Request(url, headers={
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            })
            resp = urlopen(req, timeout=10)
            content = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            log.warning(f"Could not fetch shared waypoints: {e}")
            return False

        self.shared = []
        first = True
        for line in content.splitlines():
            if first:
                first = False
                continue
            m = re.match(r'^[^,]*,"([^"]*)",([^,]+),([^,]+),([^,]+)', line)
            if not m:
                m = re.match(r'^[^,]*,([^,]+),([^,]+),([^,]+),([^,]+)', line)
            if m:
                try:
                    self.shared.append({
                        "name": m.group(1),
                        "absX": float(m.group(2)),
                        "absY": float(m.group(3)),
                        "absZ": float(m.group(4)),
                    })
                except ValueError:
                    pass

        log.info(f"Loaded {len(self.shared)} community waypoints")
        return True

    def submit(self, name, x, y, z):
        """Submit a waypoint to the community sheet."""
        try:
            url = (
                f"{FORM_SUBMIT_URL}"
                f"?{FORM_FIELDS['name']}={quote_plus(name)}"
                f"&{FORM_FIELDS['x']}={x:.6f}"
                f"&{FORM_FIELDS['y']}={y:.6f}"
                f"&{FORM_FIELDS['z']}={z:.6f}"
                f"&submit=Submit"
            )
            urlopen(url, timeout=10)
            return True
        except Exception:
            return False
