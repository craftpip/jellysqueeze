/* JellySqueeze website — Quick Install picker + copy button.
   Static-safe: page works with JS disabled (see <pre> fallback). */
(function () {
  "use strict";

  var installEl = document.getElementById("install-cmd");
  if (!installEl) return;

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

  function currentLines() {
    return SHARED.concat(START[hardware], END);
  }

  function render() {
    installEl.innerHTML = "";
    currentLines().forEach(function (line) {
      var span = document.createElement("span");
      span.textContent = line + "\n";
      if (line.charAt(0) === "#") span.className = "dim2";
      installEl.appendChild(span);
    });
  }

  document.querySelectorAll(".install-pick-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".install-pick-btn").forEach(function (b) {
        b.classList.remove("active");
        b.setAttribute("aria-pressed", "false");
      });
      this.classList.add("active");
      this.setAttribute("aria-pressed", "true");
      hardware = this.dataset.pick;
      render();
    });
  });

  var copyBtn = document.getElementById("copy-install");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      // Copy commands only — skip comment lines for a clean paste.
      var cmds = currentLines()
        .filter(function (l) { return l && l.charAt(0) !== "#"; })
        .join("\n");
      function done() {
        copyBtn.textContent = "Copied!";
        setTimeout(function () { copyBtn.textContent = "Copy"; }, 1500);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(cmds).then(done, done);
      } else {
        var ta = document.createElement("textarea");
        ta.value = cmds;
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); } catch (e) {}
        document.body.removeChild(ta);
        done();
      }
    });
  }

  render();
})();
