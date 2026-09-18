/* JellySqueeze website — progressive enhancement only.
   The page is fully usable with JS disabled or on static hosts
   (e.g. GitHub Pages). This script adds a fake visitor counter
   persisted in localStorage. */
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
})();
