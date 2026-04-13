# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Crimson Desert Interactive Map with Character Tracker — a standalone local web app for live player position tracking. Reads player XYZ from game memory (Windows-only) and displays it on a Leaflet.js map served from a local Python web/WebSocket server. Also shows 5,716 POI markers from MapGenie across 106 categories.

## Running

```
cd python-app
pip install -r requirements.txt
python main.py          # requires admin (memory access)
```

Or: right-click `python-app/run.bat` → Run as administrator (auto-installs deps).

Opens `http://127.0.0.1:17835` in the default browser. The game must be running for position tracking to work.

No build step, no test suite, no linter configured.

## Architecture

```
Game Process (CrimsonDesert.exe)
  ↓ pymem (direct memory read)
memory_reader.py  — AOB hook to find player entity, reads X/Y/Z floats
  ↓
main.py (MapTracker) — orchestrates reading + broadcasting
  ↓
websocket_server.py — async WS + HTTP server on port 17835
  ↓ HTTP (static files) + WebSocket (live position)
index.html — Leaflet.js map, POI markers, sidebar, found tracking
```

### Memory reading (`memory_reader.py`)
- AOB pattern scan on `CrimsonDesert.exe` to locate code that writes entity position
- Code cave injection captures the entity pointer (RAX register)
- Entity offsets in `config.py`: X=+0x90, Y=+0x94, Z=+0x98

### Coordinate transform (`coord_transform.py`)
- 2-point linear calibration: game (x,z) → Leaflet (lng,lat)
- Default calibration points for Pywel realm in `config.py`

### Web server (`websocket_server.py`)
- Single `websockets` server handles both HTTP (static file serving) and WebSocket upgrades
- HTTP responses use `websockets.datastructures.Headers` (list of tuples) — plain dicts don't work
- Integer status codes (200, 404, etc.), not `http.HTTPStatus` enums

### Map UI (`index.html`)
- Leaflet.js with MapGenie tile server
- Canvas renderer (`L.canvas()`) for performance with 5,716 markers
- POI data loaded from `mapgenie_data.json` (slim format: `{groups, locations, sprite}`)
- Markers zoom-gated at `MIN_POI_ZOOM = 11`; radius scales with zoom
- Found locations stored in `localStorage` key `cd_tracker_found`
- Category visibility stored in `localStorage` key `cd_tracker_cat_vis`

### POI data (`mapgenie_data.json`)
- 1MB JSON extracted from MapGenie's `window._cdCache`
- 11 groups, 106 categories, 5,716 locations
- Location fields: `id`, `c` (category_id), `t` (title), `la` (latitude), `lo` (longitude), `d` (description)

## Key Config (`config.py`)
- WS port: `17835`
- Broadcast interval: `0.5s`
- AOB pattern: `\x48\x8B\x06\x0F\x11\x88\xB0\x01\x00\x00`
- Default Pywel calibration points

## Dependencies
- Python 3.10+: `pymem>=1.13`, `websockets>=13.0`
- No frontend build step — pure HTML/JS served as static files
