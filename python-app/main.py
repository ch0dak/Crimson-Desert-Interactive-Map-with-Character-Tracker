"""
CD Map Tracker — Main Entry Point
Reads Crimson Desert player position and broadcasts via WebSocket.
"""

import asyncio
import ctypes
import json
import logging
import sys
import time
import os
import webbrowser

from config import VERSION, BROADCAST_INTERVAL, PROCESS_NAME, WS_PORT
from memory_reader import MemoryReader
from coord_transform import load_calibration, save_calibration, game_to_lnglat, detect_realm
from websocket_server import TrackerWebSocketServer
from waypoint_store import WaypointStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


class MapTracker:
    def __init__(self):
        self.reader = MemoryReader()
        self.ws_server = TrackerWebSocketServer()
        self.waypoints = WaypointStore()

        self.calibrations = {}  # realm -> cal
        self.current_realm = "pywel"
        self.follow_mode = False

        # Calibration state
        self.calibrating = False
        self.cal_point_index = 0  # 0 = waiting for point 1, 1 = waiting for point 2
        self.cal_game_pos = None  # captured game pos for current calibration point

    def _load_calibrations(self):
        self.calibrations["pywel"] = load_calibration("pywel")
        self.calibrations["abyss"] = load_calibration("abyss")

    def _handle_ws_message(self, msg):
        """Handle messages from the Chrome extension."""
        msg_type = msg.get("type")

        if msg_type == "calibrate_start":
            self.calibrating = True
            self.cal_point_index = 0
            self.cal_game_pos = None
            log.info("Calibration started")

        elif msg_type == "calibrate_cancel":
            self.calibrating = False
            self.cal_point_index = 0
            self.cal_game_pos = None
            log.info("Calibration cancelled")

        elif msg_type == "calibrate_click":
            self._handle_calibrate_click(msg.get("lng"), msg.get("lat"))

        elif msg_type == "toggle_follow":
            self.follow_mode = not self.follow_mode
            log.info(f"Follow mode: {self.follow_mode}")

        elif msg_type == "save_waypoint":
            name = msg.get("name", "Waypoint")
            pos = self.reader.get_player_abs()
            if pos:
                self.waypoints.add(name, pos[0], pos[1], pos[2])
                log.info(f"Saved waypoint: {name}")

        elif msg_type == "delete_waypoint":
            idx = msg.get("idx")
            if idx is not None:
                self.waypoints.delete(idx)

        elif msg_type == "fetch_community":
            self.waypoints.fetch_shared()

    def _handle_calibrate_click(self, lng, lat):
        if not self.calibrating or lng is None or lat is None:
            return

        pos = self.reader.get_player_abs()
        if not pos:
            log.warning("Cannot calibrate: no player position")
            return

        cal = self.calibrations[self.current_realm]

        if self.cal_point_index == 0:
            cal[0] = {"game": [pos[0], pos[2]], "map": [lng, lat]}
            self.cal_point_index = 1
            log.info(f"Calibration point 1: game=({pos[0]:.1f}, {pos[2]:.1f}), map=({lng:.4f}, {lat:.4f})")
            # Notify extension
            self._cal_status_msg = {
                "type": "calibration_status",
                "text": "Point 1 captured. Move to a different location and click point 2.",
                "done": False,
            }
        else:
            cal[1] = {"game": [pos[0], pos[2]], "map": [lng, lat]}
            save_calibration(cal, self.current_realm)
            self.calibrations[self.current_realm] = cal
            self.calibrating = False
            self.cal_point_index = 0
            log.info(f"Calibration point 2 captured. Calibration saved for {self.current_realm}.")
            self._cal_status_msg = {
                "type": "calibration_status",
                "text": f"Calibration saved for {self.current_realm}!",
                "done": True,
            }

    def _build_waypoint_data(self):
        """Convert waypoints to lng/lat for the map."""
        cal = self.calibrations[self.current_realm]
        local = []
        for i, wp in enumerate(self.waypoints.local):
            lng, lat = game_to_lnglat(wp["absX"], wp["absZ"], cal)
            local.append({"lng": lng, "lat": lat, "name": wp["name"], "idx": i})

        community = []
        for i, wp in enumerate(self.waypoints.shared):
            lng, lat = game_to_lnglat(wp["absX"], wp["absZ"], cal)
            community.append({"lng": lng, "lat": lat, "name": wp["name"], "idx": i})

        return local, community

    async def run(self):
        log.info(f"CD Map Tracker v{VERSION}")
        log.info("Starting WebSocket server...")

        self.ws_server.set_message_handler(self._handle_ws_message)
        await self.ws_server.start()

        # Auto-open the map UI in browser
        webbrowser.open(f"http://127.0.0.1:{WS_PORT}")
        log.info(f"Map UI opened at http://127.0.0.1:{WS_PORT}")

        self._load_calibrations()
        self.waypoints.load()

        # Try to fetch community waypoints in background
        try:
            self.waypoints.fetch_shared()
        except Exception:
            pass

        self._cal_status_msg = None

        log.info(f"Waiting for {PROCESS_NAME}...")

        last_broadcast = 0
        last_waypoint_broadcast = 0
        attached = False
        aobs_scanned = False
        last_realm = None

        while True:
            now = time.time()

            # Attachment loop
            if not attached:
                if now - last_broadcast >= 10:
                    log.info(f"Searching for {PROCESS_NAME}...")
                    last_broadcast = now
                if self.reader.attach():
                    attached = True
                    aobs_scanned = False
                    log.info("Attached to game")
                else:
                    await asyncio.sleep(2)
                    continue

            # Check if still attached
            if not self.reader.is_attached():
                attached = False
                aobs_scanned = False
                log.warning("Game disconnected, waiting for reconnection...")
                self.reader.detach()
                await asyncio.sleep(2)
                continue

            # Scan AOBs and install hook once after attach
            if not aobs_scanned:
                self.reader.scan_aobs()

                if self.reader.pointer_chain:
                    aobs_scanned = True
                    log.info("Using pointer chain mode")
                elif self.reader.hook_addr:
                    if self.reader.install_hook():
                        aobs_scanned = True
                        log.info("Entity capture hook installed — move in-game to capture entity")
                    else:
                        log.warning("Hook install failed, will retry in 5s...")
                        await asyncio.sleep(5)
                        continue
                else:
                    log.warning("No entity hook found, retrying in 5s (close other mods and restart game)...")
                    await asyncio.sleep(5)
                    continue

            # Read position
            pos = self.reader.get_player_abs()

            # Broadcast position at configured interval
            if now - last_broadcast >= BROADCAST_INTERVAL and self.ws_server.has_clients:
                if pos:
                    realm = detect_realm(pos[1])
                    if realm != self.current_realm:
                        self.current_realm = realm
                        log.info(f"Realm changed to: {realm}")

                    cal = self.calibrations[realm]
                    lng, lat = game_to_lnglat(pos[0], pos[2], cal)
                    label = f"({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})"

                    await self.ws_server.broadcast({
                        "type": "position",
                        "lng": lng,
                        "lat": lat,
                        "label": label,
                        "realm": realm,
                        "follow": self.follow_mode,
                    })

                    # Realm change notification
                    if realm != last_realm and last_realm is not None:
                        await self.ws_server.broadcast({
                            "type": "realm_changed",
                            "realm": realm,
                        })
                    last_realm = realm
                else:
                    await self.ws_server.broadcast({
                        "type": "status",
                        "text": "Waiting for player position...",
                        "game_attached": True,
                    })

                last_broadcast = now

            # Broadcast waypoints less frequently
            if now - last_waypoint_broadcast >= 5.0 and self.ws_server.has_clients:
                local_wps, comm_wps = self._build_waypoint_data()
                await self.ws_server.broadcast({
                    "type": "waypoints",
                    "local": local_wps,
                    "community": comm_wps,
                })
                last_waypoint_broadcast = now

            # Send calibration status if pending
            if self._cal_status_msg and self.ws_server.has_clients:
                await self.ws_server.broadcast(self._cal_status_msg)
                self._cal_status_msg = None

            await asyncio.sleep(0.05)  # 50ms tick


async def main():
    if not is_admin():
        print("ERROR: This program must be run as Administrator.")
        print("Right-click your terminal -> 'Run as administrator', then try again.")
        sys.exit(1)

    tracker = MapTracker()
    try:
        await tracker.run()
    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        tracker.reader.detach()
        await tracker.ws_server.stop()


if __name__ == "__main__":
    asyncio.run(main())
