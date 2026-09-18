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

    var SHARED = [
      "# 1. Get the code",
      "git clone https://github.com/craftpip/media-convert-for-jellyfin.git",
      "cd media-convert-for-jellyfin",
      "",
      "# 2. Add your keys",
      "cp .env.example .env",
      "nano .env",
      "#   JELLYFIN_BASE_URL + JELLYFIN_API_KEY — from Jellyfin → API Keys",
      "#   JELLYSQUEEZE_MCP_API_KEY            — pick your own token for the MCP API",
      "#   WEBUI_PASSWORD                      — password for the control panel",
      ""
    ];

    var START = {
      nvidia: [
        "# 3. Build & start — NVIDIA (NVENC)",
        "docker compose up -d --build"
      ],
      intel: [
        "# 3. Build & start — Intel (QSV)",
        "docker compose -f docker-compose.intel.yml up -d --build"
      ],
      amd: [
        "# 3. Build & start — AMD (VA-API)",
        "docker compose -f docker-compose.amd.yml up -d --build"
      ],
      cpu: [
        "# 3. Build the CPU image & start (libx264 / libx265)",
        "docker build -f Dockerfile.cpu -t jellysqueeze:cpu .",
        "docker run -d --name jellysqueeze \\",
        "  -p 9238:8080 \\",
        "  -v ${PWD}:/app \\",
        "  -v ${PWD}/.env:/app/.env:ro \\",
        "  -v ${PWD}/config.yml:/app/config.yml:ro \\",
        "  -v ${PWD}/var:/app/var \\",
        "    jellysqueeze:cpu"
      ]
    };

    var END = [
      "",
      "# 4. Open the panel and add your libraries",
      "http://localhost:9238/",
      "#   Libraries → Add Library — paths, bitrates, encoder"
    ];

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
      SHARED.concat(START[hardware], END).forEach(function (line) {
        var span = document.createElement("span");
        span.textContent = line + "\n";
        if (line.charAt(0) === "#") span.className = "dim2";
        installEl.appendChild(span);
      });
    }

    render();
  }
})();