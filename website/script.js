/* JellySqueeze website — progressive enhancement only.
   The page is fully usable with JS disabled or on static hosts
   (e.g. GitHub Pages). This script adds a fake visitor counter
   persisted in localStorage, plus the Quick Install pickers
   (Docker image + output codec) that rewrite the install command. */
(function () {
  "use strict";

  /* ── Visitor counter ── */
  try {
    var el = document.getElementById("hit-counter");
    if (el) {
      var n = parseInt(localStorage.getItem("js_hits") || "1336", 10) || 1336;
      n += 1;
      localStorage.setItem("js_hits", String(n));
      el.textContent = String(n).padStart(6, "0");
    }
  } catch (e) { /* private mode — leave the static number */ }

  /* ── Quick Install picker ── */
  var installEl = document.getElementById("install-cmd");
  if (installEl) {
    var hardware = "nvidia";   // nvidia | intel | amd | cpu

    var INSTALL = {
      nvidia: [
        "# 1. Clone the repo",
        "git clone https://github.com/craftpip/media-convert-for-jellyfin.git",
        "cd media-convert-for-jellyfin",
        "",
        "# 2. Configure your libraries — paths, bitrate, encoder",
        "cp config.yml.example config.yml",
        "nano config.yml",
        "",
        "# 3. Build & start — NVIDIA (NVENC)",
        "docker compose up -d --build",
        "",
        "# 4. Open the control panel",
        "http://localhost:9238/"
      ],
      intel: [
        "# 1. Clone the repo",
        "git clone https://github.com/craftpip/media-convert-for-jellyfin.git",
        "cd media-convert-for-jellyfin",
        "",
        "# 2. Configure your libraries — paths, bitrate, encoder",
        "cp config.yml.example config.yml",
        "nano config.yml",
        "",
        "# 3. Build & start — Intel (QSV)",
        "docker compose -f docker-compose.intel.yml up -d --build",
        "",
        "# 4. Open the control panel",
        "http://localhost:9238/"
      ],
      amd: [
        "# 1. Clone the repo",
        "git clone https://github.com/craftpip/media-convert-for-jellyfin.git",
        "cd media-convert-for-jellyfin",
        "",
        "# 2. Configure your libraries — paths, bitrate, encoder",
        "cp config.yml.example config.yml",
        "nano config.yml",
        "",
        "# 3. Build & start — AMD (VA-API)",
        "docker compose -f docker-compose.amd.yml up -d --build",
        "",
        "# 4. Open the control panel",
        "http://localhost:9238/"
      ],
      cpu: [
        "# 1. Clone the repo",
        "git clone https://github.com/craftpip/media-convert-for-jellyfin.git",
        "cd media-convert-for-jellyfin",
        "",
        "# 2. Configure your libraries — paths, bitrate, encoder",
        "cp config.yml.example config.yml",
        "nano config.yml",
        "",
        "# 3. Build the CPU image & start (libx264 / libx265)",
        "docker build -f Dockerfile.cpu -t jellysqueeze:cpu .",
        "docker run -d --name jellysqueeze \\",
        "  -p 9238:8080 \\",
        "  -v ${PWD}:/app \\",
        "  -v ${PWD}/config.yml:/app/config.yml:ro \\",
        "  -v ${PWD}/var:/app/var \\",
        "    jellysqueeze:cpu",
        "",
        "# 4. Open the control panel",
        "http://localhost:9238/"
      ]
    };

    document.querySelectorAll(".install-pick button.pick").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll(".pick").forEach(function (b) {
          b.classList.remove("active");
          b.setAttribute("aria-pressed", "false");
        });
        this.classList.add("active");
        this.setAttribute("aria-pressed", "true");
        hardware = this.dataset.pick;
        render();
      });
    });

    function render() {
      installEl.innerHTML = "";
      INSTALL[hardware].forEach(function (line) {
        var span = document.createElement("span");
        span.textContent = line + "\n";
        if (line.charAt(0) === "#") span.className = "dim2";
        installEl.appendChild(span);
      });
    }

    render();
  }
})();