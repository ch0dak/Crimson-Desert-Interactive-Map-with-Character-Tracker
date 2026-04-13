/**
 * CD Map Tracker — Content Script
 * Injected on mapgenie.io/crimson-desert pages.
 *
 * Content scripts run in an isolated world and cannot access page JS globals
 * like window.map. So we inject a <script> tag into the page that runs in the
 * page's own context, accesses window.map, and communicates back via
 * window.postMessage.
 */

(function () {
  if (window.__cdTrackerContentReady) return;
  window.__cdTrackerContentReady = true;

  const WS_URL = "ws://127.0.0.1:17835";
  const RECONNECT_INTERVAL = 3000;

  let ws = null;
  let connected = false;
  let followMode = false;
  let calibrating = false;
  let currentRealm = "";
  let lastLabel = "";

  // --- Inject page-level script that has access to window.map ---

  function injectPageScript() {
    var script = document.createElement("script");
    script.textContent = "(" + pageScript.toString() + ")();";
    document.documentElement.appendChild(script);
    script.remove();
  }

  /**
   * This function runs in the PAGE context (not content script isolation).
   * It can access window.map (MapGenie's Mapbox GL instance).
   * It communicates with the content script via window.postMessage.
   */
  function pageScript() {
    if (window.__cdTrackerPageReady) return;
    window.__cdTrackerPageReady = true;

    var map = null;
    var overlay = null;
    var playerEl = null;
    var playerLabel = null;
    var playerLngLat = null;
    var playerVisible = false;
    var wpEntries = [];
    var commEntries = [];
    var baseZoom = 3;

    function waitForMap(cb, retries) {
      retries = retries || 0;
      if (
        window.map &&
        typeof window.map.getContainer === "function" &&
        typeof window.map.project === "function" &&
        window.map.getContainer()
      ) {
        cb(window.map);
      } else if (retries < 200) {
        setTimeout(function () {
          waitForMap(cb, retries + 1);
        }, 500);
      } else {
        console.error("[CD Map Tracker] Timed out waiting for MapGenie map");
      }
    }

    waitForMap(function (m) {
      map = m;
      baseZoom = map.getZoom();
      initOverlay();
      // Tell content script we're ready
      window.postMessage({ source: "cd-tracker-page", type: "ready" }, "*");
      console.log("[CD Map Tracker] Page script initialized, map found");
    });

    function getScale() {
      var z = map.getZoom();
      var s = Math.pow(1.4, z - baseZoom) * 0.4;
      return Math.max(0.1, Math.min(s, 1.2));
    }

    function reprojectAll() {
      var s = getScale();
      if (playerVisible && playerLngLat) {
        var p = map.project(playerLngLat);
        playerEl.style.transform =
          "translate(" + p.x + "px," + p.y + "px) scale(" + s + ")";
      }
      for (var i = 0; i < wpEntries.length; i++) {
        var w = wpEntries[i];
        var wp = map.project(w.lnglat);
        w.el.style.transform =
          "translate(" + wp.x + "px," + wp.y + "px) scale(" + s + ")";
      }
      for (var i = 0; i < commEntries.length; i++) {
        var c = commEntries[i];
        var cp = map.project(c.lnglat);
        c.el.style.transform =
          "translate(" + cp.x + "px," + cp.y + "px) scale(" + s + ")";
      }
    }

    function initOverlay() {
      var mapContainer = map.getContainer();

      overlay = document.createElement("div");
      overlay.id = "cd-tracker-overlay";
      overlay.style.cssText =
        "position:absolute;top:0;left:0;width:100%;height:100%;" +
        "pointer-events:none;z-index:9999;overflow:hidden;";
      mapContainer.appendChild(overlay);

      // Player marker
      playerEl = document.createElement("div");
      playerEl.id = "cd-player-marker";
      playerEl.style.cssText =
        "position:absolute;left:0;top:0;pointer-events:none;display:none;transform-origin:0 0;";
      playerEl.innerHTML =
        '<div style="position:absolute;left:-12px;top:-12px;width:24px;height:24px;' +
        "background:#d4920a;border:2px solid #fff;border-radius:50%;" +
        'box-shadow:0 0 8px rgba(212,146,10,0.6);"></div>' +
        '<div style="position:absolute;left:18px;top:-8px;color:#fff;font:bold 11px Segoe UI,sans-serif;' +
        'text-shadow:0 0 3px #000,0 0 6px #000;white-space:nowrap;"></div>';
      overlay.appendChild(playerEl);
      playerLabel = playerEl.children[1];

      // Styles for control bar
      var style = document.createElement("style");
      style.textContent = [
        "#cd-overlay-bar { position: fixed; top: 0; left: 0; right: 0; z-index: 10000;",
        '  background: rgba(30,30,46,0.95); padding: 6px 16px; display: flex;',
        '  align-items: center; gap: 12px; font-family: "Segoe UI", sans-serif;',
        "  color: #cdd6f4; font-size: 13px; border-bottom: 1px solid #45475a;",
        "  flex-wrap: wrap; box-sizing: border-box; height: 38px; }",
        "#cd-overlay-bar button { background: #313244; color: #cdd6f4; border: 1px solid #45475a;",
        "  padding: 4px 14px; border-radius: 4px; cursor: pointer; font-size: 12px; }",
        "#cd-overlay-bar button:hover { background: #89b4fa; color: #1e1e2e; }",
        "#cd-overlay-bar .cd-active { background: #89b4fa !important; color: #1e1e2e !important; }",
        "#cd-overlay-bar .cd-status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }",
        "#cd-overlay-bar .cd-connected { background: #a6e3a1; }",
        "#cd-overlay-bar .cd-disconnected { background: #f38ba8; }",
        "body { margin-top: 38px !important; }",
        "#cd-cal-status { color: #f9e2af; font-size: 11px; }",
      ].join("\n");
      document.head.appendChild(style);

      // Control bar
      var bar = document.createElement("div");
      bar.id = "cd-overlay-bar";
      bar.innerHTML = [
        '<span style="font-weight:bold; color:#89b4fa;">CD Map Tracker</span>',
        '<span class="cd-status-dot cd-disconnected" id="cd-status-dot"></span>',
        '<span id="cd-status-text" style="font-size:11px;color:#6c7086;">Disconnected</span>',
        '<button id="cd-btn-follow">Follow Player</button>',
        '<button id="cd-btn-calibrate">Calibrate</button>',
        '<span id="cd-cal-status" style="display:none;"></span>',
        '<span style="margin-left:auto; font-size:11px; color:#6c7086;" id="cd-player-coords"></span>',
      ].join("");
      document.body.insertBefore(bar, document.body.firstChild);

      // Follow button
      document
        .getElementById("cd-btn-follow")
        .addEventListener("click", function () {
          window.postMessage(
            { source: "cd-tracker-page", type: "toggle_follow" },
            "*"
          );
        });

      // Calibrate button
      document
        .getElementById("cd-btn-calibrate")
        .addEventListener("click", function () {
          window.postMessage(
            { source: "cd-tracker-page", type: "toggle_calibrate" },
            "*"
          );
        });

      // Map click for calibration
      map.on("click", function (e) {
        window.postMessage(
          {
            source: "cd-tracker-page",
            type: "map_click",
            lng: e.lngLat.lng,
            lat: e.lngLat.lat,
          },
          "*"
        );
      });

      map.on("render", reprojectAll);
    }

    function escapeHtml(str) {
      var div = document.createElement("div");
      div.textContent = str;
      return div.innerHTML;
    }

    // Listen for commands from content script
    window.addEventListener("message", function (event) {
      if (event.data && event.data.source === "cd-tracker-content") {
        var msg = event.data;

        switch (msg.type) {
          case "update_position":
            playerLngLat = [msg.lng, msg.lat];
            playerVisible = true;
            playerEl.style.display = "";
            if (playerLabel)
              playerLabel.textContent = msg.label || "";
            var coords = document.getElementById("cd-player-coords");
            if (coords) coords.textContent = msg.label || "";
            reprojectAll();
            if (msg.follow) {
              map.flyTo({ center: [msg.lng, msg.lat], duration: 400 });
            }
            break;

          case "update_status":
            var dot = document.getElementById("cd-status-dot");
            var text = document.getElementById("cd-status-text");
            if (dot) {
              dot.className =
                "cd-status-dot " +
                (msg.connected ? "cd-connected" : "cd-disconnected");
            }
            if (text) {
              text.textContent = msg.connected ? "Connected" : "Disconnected";
              text.style.color = msg.connected ? "#a6e3a1" : "#6c7086";
            }
            break;

          case "update_follow":
            var btn = document.getElementById("cd-btn-follow");
            if (btn)
              btn.classList.toggle("cd-active", msg.followMode);
            break;

          case "update_calibrate":
            var btn2 = document.getElementById("cd-btn-calibrate");
            var status = document.getElementById("cd-cal-status");
            if (btn2)
              btn2.classList.toggle("cd-active", msg.calibrating);
            if (status) {
              if (msg.calibrating) {
                status.style.display = "";
                status.textContent =
                  "Stand at a known spot in-game, then click that spot on the map";
              } else {
                status.style.display = "none";
              }
            }
            break;

          case "calibration_status":
            var calStatus = document.getElementById("cd-cal-status");
            var calBtn = document.getElementById("cd-btn-calibrate");
            if (calStatus) calStatus.textContent = msg.text;
            if (msg.done) {
              if (calBtn) calBtn.classList.remove("cd-active");
              setTimeout(function () {
                if (calStatus) calStatus.style.display = "none";
              }, 5000);
            }
            break;

          case "update_waypoints":
            // Clear old
            for (var i = 0; i < wpEntries.length; i++) {
              overlay.removeChild(wpEntries[i].el);
            }
            wpEntries = [];
            for (var i = 0; i < commEntries.length; i++) {
              overlay.removeChild(commEntries[i].el);
            }
            commEntries = [];

            // Local waypoints (yellow)
            (msg.local || []).forEach(function (wp) {
              var el = document.createElement("div");
              el.style.cssText =
                "position:absolute;left:0;top:0;cursor:pointer;pointer-events:auto;transform-origin:0 0;";
              el.innerHTML =
                '<div style="position:absolute;left:-6px;top:-6px;width:12px;height:12px;' +
                "background:#f9e2af;border:1px solid #b0a088;border-radius:50%;" +
                'pointer-events:auto;"></div>' +
                '<div style="position:absolute;left:0;top:-20px;color:#f9e2af;font:12px Segoe UI,sans-serif;' +
                'text-shadow:0 0 3px #000,0 0 3px #000;white-space:nowrap;pointer-events:none;">' +
                escapeHtml(wp.name || "") +
                "</div>";
              el.addEventListener("click", function (e) {
                e.stopPropagation();
                map.flyTo({ center: [wp.lng, wp.lat], duration: 600 });
              });
              overlay.appendChild(el);
              wpEntries.push({ el: el, lnglat: [wp.lng, wp.lat] });
            });

            // Community waypoints (cyan)
            (msg.community || []).forEach(function (wp) {
              var el = document.createElement("div");
              el.style.cssText =
                "position:absolute;left:0;top:0;cursor:pointer;pointer-events:auto;transform-origin:0 0;";
              el.innerHTML =
                '<div style="position:absolute;left:-5px;top:-5px;width:10px;height:10px;' +
                "background:#a8d4f0;border:1px solid #7ab8d9;border-radius:50%;" +
                'pointer-events:auto;"></div>' +
                '<div style="position:absolute;left:0;top:-18px;color:#a8d4f0;font:12px Segoe UI,sans-serif;' +
                'text-shadow:0 0 3px #000,0 0 3px #000;white-space:nowrap;pointer-events:none;">' +
                escapeHtml(wp.name || "") +
                "</div>";
              el.addEventListener("click", function (e) {
                e.stopPropagation();
                map.flyTo({ center: [wp.lng, wp.lat], duration: 600 });
              });
              overlay.appendChild(el);
              commEntries.push({ el: el, lnglat: [wp.lng, wp.lat] });
            });

            reprojectAll();
            break;
        }
      }
    });
  }

  // --- Content script logic (runs in isolated world) ---

  // Inject the page script
  injectPageScript();

  let pageReady = false;

  // Connect WebSocket immediately — it's independent of the page map
  connectWebSocket();

  // Listen for messages from page script
  window.addEventListener("message", function (event) {
    if (!event.data || event.data.source !== "cd-tracker-page") return;

    var msg = event.data;

    switch (msg.type) {
      case "ready":
        pageReady = true;
        console.log("[CD Map Tracker] Page script ready, map overlay initialized");
        break;

      case "toggle_follow":
        followMode = !followMode;
        sendToPage({ type: "update_follow", followMode: followMode });
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "toggle_follow" }));
        }
        break;

      case "toggle_calibrate":
        calibrating = !calibrating;
        sendToPage({ type: "update_calibrate", calibrating: calibrating });
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({
              type: calibrating ? "calibrate_start" : "calibrate_cancel",
            })
          );
        }
        break;

      case "map_click":
        if (calibrating && ws && ws.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({
              type: "calibrate_click",
              lng: msg.lng,
              lat: msg.lat,
            })
          );
        }
        break;
    }
  });

  function sendToPage(data) {
    data.source = "cd-tracker-content";
    window.postMessage(data, "*");
  }

  // --- WebSocket ---

  function connectWebSocket() {
    if (ws) {
      try {
        ws.close();
      } catch (e) {}
    }

    ws = new WebSocket(WS_URL);

    ws.onopen = function () {
      connected = true;
      sendToPage({ type: "update_status", connected: true });
      console.log("[CD Map Tracker] WebSocket connected");
    };

    ws.onclose = function () {
      connected = false;
      sendToPage({ type: "update_status", connected: false });
      console.log("[CD Map Tracker] WebSocket disconnected, reconnecting...");
      setTimeout(connectWebSocket, RECONNECT_INTERVAL);
    };

    ws.onerror = function (err) {
      console.warn("[CD Map Tracker] WebSocket error:", err);
    };

    ws.onmessage = function (event) {
      try {
        var msg = JSON.parse(event.data);
        handleServerMessage(msg);
      } catch (e) {}
    };
  }

  function handleServerMessage(msg) {
    switch (msg.type) {
      case "position":
        if (msg.realm) currentRealm = msg.realm;
        if (msg.label) lastLabel = msg.label;
        if (!pageReady) return;
        sendToPage({
          type: "update_position",
          lng: msg.lng,
          lat: msg.lat,
          label: msg.label,
          follow: followMode,
        });
        break;

      case "waypoints":
        if (!pageReady) return;
        sendToPage({
          type: "update_waypoints",
          local: msg.local,
          community: msg.community,
        });
        break;

      case "calibration_status":
        if (!pageReady) return;
        sendToPage({
          type: "calibration_status",
          text: msg.text,
          done: msg.done,
        });
        if (msg.done) calibrating = false;
        break;

      case "hello":
        console.log("[CD Map Tracker] Server version:", msg.version);
        break;
    }
  }

  // --- Chrome extension messaging (for popup) ---

  chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
    if (msg.type === "get_status") {
      sendResponse({
        connected: connected,
        pageReady: pageReady,
        followMode: followMode,
        calibrating: calibrating,
        realm: currentRealm,
        playerCoords:
          document.getElementById("cd-player-coords")?.textContent || lastLabel || "",
      });
    } else if (msg.type === "toggle_follow") {
      followMode = !followMode;
      sendToPage({ type: "update_follow", followMode: followMode });
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "toggle_follow" }));
      }
      sendResponse({ followMode: followMode });
    } else if (msg.type === "toggle_calibrate") {
      calibrating = !calibrating;
      sendToPage({ type: "update_calibrate", calibrating: calibrating });
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({
            type: calibrating ? "calibrate_start" : "calibrate_cancel",
          })
        );
      }
      sendResponse({ calibrating: calibrating });
    } else if (msg.type === "save_waypoint") {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({ type: "save_waypoint", name: msg.name || "Waypoint" })
        );
      }
      sendResponse({ ok: true });
    } else if (msg.type === "fetch_community") {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "fetch_community" }));
      }
      sendResponse({ ok: true });
    }
    return true;
  });
})();
