// CD Map Tracker — Popup Script
// Communicates with the content script on the active MapGenie tab.

function queryMapGenieTab(msg, cb) {
  chrome.tabs.query({ url: "https://mapgenie.io/crimson-desert/*" }, function (tabs) {
    if (tabs.length === 0) {
      cb(null);
      return;
    }
    chrome.tabs.sendMessage(tabs[0].id, msg, function (response) {
      cb(chrome.runtime.lastError ? null : response);
    });
  });
}

function updateUI() {
  queryMapGenieTab({ type: "get_status" }, function (res) {
    var dot = document.getElementById("status-dot");
    var text = document.getElementById("status-text");
    var coords = document.getElementById("coords");
    var realm = document.getElementById("realm");
    var btnFollow = document.getElementById("btn-follow");

    if (!res) {
      dot.className = "status-dot";
      text.textContent = "No MapGenie tab open";
      coords.textContent = "—";
      realm.textContent = "—";
      return;
    }

    if (res.connected) {
      dot.className = "status-dot connected";
      text.textContent = "Connected";
    } else if (!res.pageReady) {
      dot.className = "status-dot";
      text.textContent = "Waiting for map...";
    } else {
      dot.className = "status-dot";
      text.textContent = "Disconnected from tracker";
    }

    coords.textContent = res.playerCoords || "—";
    realm.textContent = res.realm || "—";
    btnFollow.classList.toggle("active", res.followMode);
  });
}

document.getElementById("btn-follow").addEventListener("click", function () {
  queryMapGenieTab({ type: "toggle_follow" }, function (res) {
    if (res) {
      document.getElementById("btn-follow").classList.toggle("active", res.followMode);
    }
  });
});

document.getElementById("btn-calibrate").addEventListener("click", function () {
  queryMapGenieTab({ type: "toggle_calibrate" }, function () {});
});

document.getElementById("btn-save-wp").addEventListener("click", function () {
  var name = document.getElementById("wp-name").value.trim() || "Waypoint";
  queryMapGenieTab({ type: "save_waypoint", name: name }, function () {
    document.getElementById("wp-name").value = "";
  });
});

document.getElementById("btn-fetch-community").addEventListener("click", function () {
  queryMapGenieTab({ type: "fetch_community" }, function () {});
});

// Initial update + periodic refresh
updateUI();
setInterval(updateUI, 2000);
