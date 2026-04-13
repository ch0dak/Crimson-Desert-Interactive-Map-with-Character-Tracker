# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CD Map Tracker — live player position tracking for Crimson Desert on MapGenie. Reads player XYZ from game memory (Windows-only) and displays a live marker on the MapGenie interactive map via a Chrome extension.

Two components communicate over WebSocket (`ws://127.0.0.1:17835`):
- **Python backend** (`python-app/`) — attaches to `CrimsonDesert.exe`, reads memory, broadcasts position
- **Chrome extension** (`chrome-extension/`) — MV3 content script on mapgenie.io, renders markers via Mapbox GL

## Running

### Python backend
```
cd python-app
pip install -r requirements.txt
python main.py          # requires admin (memory access)
```
Or: right-click `python-app/run.bat` → Run as administrator (auto-installs deps).

### Chrome extension
Load unpacked `chrome-extension/` folder at `chrome://extensions` (Developer mode).

No build step, no test suite, no linter configured.

## Architecture

```
Game Process (CrimsonDesert.exe)
  ↓ pymem (direct memory read)
memory_reader.py  — pointer chain or AOB hook to find player entity
  ↓
main.py (MapTracker) — orchestrates reading + calibration + waypoints
  ↓
websocket_server.py — async WS + HTTP server on port 17835
  ↓ WebSocket
content.js — injects into MapGenie page, accesses window.map (Mapbox GL)
  ↓
popup.js/html — extension popup UI (follow, calibrate, waypoints)
```

### Memory reading (`memory_reader.py`)
- **Primary**: pointer chain from `%LOCALAPPDATA%/CD_MapTracker/pointer_chains.json`
- **Fallback**: minimal code injection hook via AOB pattern scan to capture entity pointer
- Entity offsets in `config.py`: X=+0x90, Y=+0x94, Z=+0x98

### Coordinate transform (`coord_transform.py`)
- 2-point affine calibration per realm (Pywel vs Abyss)
- Realm detected by Y height threshold (1400.0)
- Converts game XZ → MapGenie lng/lat

### Waypoints (`waypoint_store.py`)
- Local: `%LOCALAPPDATA%/CD_MapTracker/cd_waypoints.json`
- Community: fetched from Google Sheets CSV, submitted via Google Form

### Chrome extension (`content.js`)
- Content script uses `postMessage` bridge to inject page-level code accessing `window.map`
- Renders player marker (orange), local waypoints (yellow), community waypoints (cyan)

## Key Config (`config.py`)
- WS port: `17835`
- Broadcast interval: `0.5s`
- Abyss height threshold: `1400.0`
- Default calibration points for Pywel and Abyss realms

## Dependencies
- Python 3.10+: `pymem>=1.13`, `websockets>=13.0`
- Chrome 90+ (Manifest V3)
