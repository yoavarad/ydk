(function () {
  "use strict";

  /* ── State ─────────────────────────────────────────── */
  const MODE = { NONE: "none", SELECT: "select", COMMENT: "comment", DRAW: "draw" };
  let currentMode = MODE.NONE;
  let highlightedEl = null;
  let drawState = null; // { startX, startY, overlay, rect }
  let rafId = null;

  /* ── Toolbar ───────────────────────────────────────── */
  const toolbar = document.createElement("div");
  toolbar.id = "odk-toolbar";
  toolbar.innerHTML = `
    <button data-mode="select" class="odk-tb-btn">Select Mode</button>
    <button data-mode="comment" class="odk-tb-btn">Comment Mode <kbd>C</kbd></button>
    <button data-mode="draw" class="odk-tb-btn">Draw Mode <kbd>R</kbd></button>
    <span class="odk-tb-sep">|</span>
    <button data-mode="none" class="odk-tb-btn odk-tb-cancel">Cancel <kbd>Esc</kbd></button>
  `;
  document.body.prepend(toolbar);

  function setMode(mode) {
    currentMode = mode;
    document.querySelectorAll(".odk-tb-btn").forEach(function (btn) {
      btn.classList.toggle("odk-tb-active", btn.dataset.mode === mode);
    });
    document.body.style.cursor = mode === "comment" ? "pointer" : mode === "draw" ? "crosshair" : "";
    clearHighlight();
    removeDrawOverlay();
  }

  toolbar.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-mode]");
    if (btn) setMode(btn.dataset.mode);
  });

  /* ── Keyboard shortcuts ────────────────────────────── */
  document.addEventListener("keydown", function (e) {
    if (e.target.tagName === "TEXTAREA" || e.target.tagName === "INPUT") return;
    if (e.key === "c" || e.key === "C") setMode(MODE.COMMENT);
    else if (e.key === "r" || e.key === "R") setMode(MODE.DRAW);
    else if (e.key === "Escape") setMode(MODE.NONE);
  });

  /* ── Element highlighting ──────────────────────────── */
  function clearHighlight() {
    if (highlightedEl) {
      highlightedEl.classList.remove("odk-highlight");
      highlightedEl = null;
    }
  }

  document.addEventListener("mousemove", function (e) {
    if (currentMode !== MODE.COMMENT) return;
    var el = e.target;
    if (el === toolbar || toolbar.contains(el)) return;
    if (el.closest("#odk-toolbar") || el.closest(".odk-popover")) return;
    clearHighlight();
    el.classList.add("odk-highlight");
    highlightedEl = el;
  });

  /* ── Comment popover ───────────────────────────────── */
  function showPopover(anchorEl, rect, onSubmit) {
    removePopover();
    var pop = document.createElement("div");
    pop.className = "odk-popover";
    var br = rect || anchorEl.getBoundingClientRect();
    pop.style.top = (br.bottom + window.scrollY + 8) + "px";
    pop.style.left = (br.left + window.scrollX) + "px";
    pop.innerHTML = `
      <textarea class="odk-popover-text" rows="3" placeholder="Add a comment..."></textarea>
      <div class="odk-popover-actions">
        <button class="odk-popover-submit">Submit</button>
        <button class="odk-popover-cancel">Cancel</button>
      </div>
    `;
    document.body.appendChild(pop);
    var ta = pop.querySelector("textarea");
    ta.focus();
    pop.querySelector(".odk-popover-submit").addEventListener("click", function () {
      var text = ta.value.trim();
      if (text) onSubmit(text);
      removePopover();
    });
    pop.querySelector(".odk-popover-cancel").addEventListener("click", removePopover);
  }

  function removePopover() {
    var existing = document.querySelector(".odk-popover");
    if (existing) existing.remove();
  }

  /* ── Anchor generation ─────────────────────────────── */
  function buildAnchor(el) {
    return {
      cssSelector: getCssSelector(el),
      xpath: getXPath(el),
      textSnippet: (el.innerText || "").substring(0, 120) || null,
      elementTag: el.tagName,
      elementId: el.id || null,
      dataTestId: el.getAttribute("data-testid") || el.getAttribute("data-id") || null,
      ariaLabel: el.getAttribute("aria-label") || null,
      fingerprint: buildFingerprint(el),
    };
  }

  function getCssSelector(el) {
    var parts = [];
    var node = el;
    while (node && node !== document.body && node !== document.documentElement) {
      var seg = node.tagName.toLowerCase();
      if (node.id && !/^radix-|^:r/.test(node.id)) return "#" + node.id + (parts.length ? " > " + parts.reverse().join(" > ") : "");
      var dtid = node.getAttribute("data-testid");
      if (dtid) seg = "[data-testid=\"" + dtid + "\"]";
      else {
        var parent = node.parentElement;
        if (parent) {
          var siblings = Array.from(parent.children).filter(function (c) { return c.tagName === node.tagName; });
          if (siblings.length > 1) seg += ":nth-child(" + (Array.from(parent.children).indexOf(node) + 1) + ")";
        }
      }
      parts.push(seg);
      node = node.parentElement;
    }
    return parts.reverse().join(" > ");
  }

  function getXPath(el) {
    var parts = [];
    var node = el;
    while (node && node.nodeType === 1) {
      var idx = 1;
      var sib = node.previousSibling;
      while (sib) {
        if (sib.nodeType === 1 && sib.tagName === node.tagName) idx++;
        sib = sib.previousSibling;
      }
      parts.unshift(node.tagName.toLowerCase() + "[" + idx + "]");
      node = node.parentNode;
    }
    return "/" + parts.join("/");
  }

  function buildFingerprint(el) {
    var childCount = el.children.length;
    var sibIdx = el.parentElement ? Array.from(el.parentElement.children).indexOf(el) : 0;
    var attrHash = 0;
    for (var i = 0; i < el.attributes.length; i++) {
      var name = el.attributes[i].name;
      for (var j = 0; j < name.length; j++) attrHash = ((attrHash << 5) - attrHash + name.charCodeAt(j)) | 0;
    }
    return childCount + ":" + sibIdx + ":" + Math.abs(attrHash).toString(16).substring(0, 5);
  }

  /* ── UUID helper ───────────────────────────────────── */
  function uuid() {
    return "ann-" + Math.random().toString(36).substring(2, 10) + Date.now().toString(36);
  }

  /* ── Post feedback ─────────────────────────────────── */
  function postFeedback(event) {
    fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(event),
    }).catch(function () { /* silent */ });
  }

  /* ── Element click (comment mode) ──────────────────── */
  document.addEventListener("click", function (e) {
    if (currentMode === MODE.COMMENT) {
      var el = e.target;
      if (el.closest("#odk-toolbar") || el.closest(".odk-popover")) return;
      e.preventDefault();
      e.stopPropagation();
      var anchor = buildAnchor(el);
      var br = el.getBoundingClientRect();
      showPopover(el, null, function (comment) {
        postFeedback({
          type: "element_annotation",
          id: uuid(),
          comment: comment,
          anchor: anchor,
          component: null,
          boundingRect: { x: br.x, y: br.y, width: br.width, height: br.height },
          viewport: {
            scrollX: window.scrollX, scrollY: window.scrollY,
            width: window.innerWidth, height: window.innerHeight,
            devicePixelRatio: window.devicePixelRatio,
          },
          screenshotPath: null,
          timestamp: Math.floor(Date.now() / 1000),
          contentFile: document.title || location.pathname,
        });
      });
    } else if (currentMode === MODE.SELECT) {
      var choice = e.target.closest("[data-choice]");
      if (choice) {
        e.preventDefault();
        postFeedback({
          type: "selection",
          choice: choice.dataset.choice,
          choiceText: (choice.innerText || "").substring(0, 200),
          timestamp: Math.floor(Date.now() / 1000),
          contentFile: document.title || location.pathname,
        });
        document.querySelectorAll("[data-choice]").forEach(function (c) { c.classList.remove("odk-selected"); });
        choice.classList.add("odk-selected");
      }
    }
  }, true);

  /* ── Rectangle drawing (draw mode) ─────────────────── */
  function removeDrawOverlay() {
    if (drawState && drawState.overlay) {
      drawState.overlay.remove();
      drawState = null;
    }
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
  }

  document.addEventListener("mousedown", function (e) {
    if (currentMode !== MODE.DRAW) return;
    if (e.target.closest("#odk-toolbar") || e.target.closest(".odk-popover")) return;

    var overlay = document.createElement("div");
    overlay.className = "odk-draw-overlay";
    document.body.appendChild(overlay);

    var rect = document.createElement("div");
    rect.className = "odk-draw-rect";
    overlay.appendChild(rect);

    drawState = {
      startX: e.clientX, startY: e.clientY,
      currentX: e.clientX, currentY: e.clientY,
      overlay: overlay, rect: rect,
    };

    function updateRect() {
      if (!drawState) return;
      var x1 = Math.min(drawState.startX, drawState.currentX);
      var y1 = Math.min(drawState.startY, drawState.currentY);
      var w = Math.abs(drawState.currentX - drawState.startX);
      var h = Math.abs(drawState.currentY - drawState.startY);
      drawState.rect.style.left = x1 + "px";
      drawState.rect.style.top = y1 + "px";
      drawState.rect.style.width = w + "px";
      drawState.rect.style.height = h + "px";
    }

    function onMove(ev) {
      if (!drawState) return;
      drawState.currentX = ev.clientX;
      drawState.currentY = ev.clientY;
      if (!rafId) rafId = requestAnimationFrame(function () { rafId = null; updateRect(); });
    }

    function onUp() {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      if (!drawState) return;

      var w = Math.abs(drawState.currentX - drawState.startX);
      var h = Math.abs(drawState.currentY - drawState.startY);
      if (w < 10 || h < 10) { removeDrawOverlay(); return; }

      var x1 = Math.min(drawState.startX, drawState.currentX);
      var y1 = Math.min(drawState.startY, drawState.currentY);
      var absRect = { x: x1, y: y1, width: w, height: h };

      showPopover(document.body, absRect, function (comment) {
        postFeedback({
          type: "rectangle_annotation",
          id: uuid(),
          comment: comment,
          anchor: null,
          rect: { xPct: x1 / window.innerWidth, yPct: y1 / window.innerHeight, wPct: w / window.innerWidth, hPct: h / window.innerHeight },
          absoluteRect: absRect,
          component: null,
          viewport: {
            scrollX: window.scrollX, scrollY: window.scrollY,
            width: window.innerWidth, height: window.innerHeight,
            devicePixelRatio: window.devicePixelRatio,
          },
          screenshotPath: null,
          timestamp: Math.floor(Date.now() / 1000),
          contentFile: document.title || location.pathname,
        });
        removeDrawOverlay();
      });
    }

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });
})();
