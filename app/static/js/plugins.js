/* Plugin AIladoc lato browser: tabelle interattive, countdown, formule LaTeX (KaTeX) e
   visualizzatore draw.io. Le librerie pesanti sono servite in locale da /static/vendor e
   caricate solo se la pagina ne ha bisogno. */
(function () {
  "use strict";

  var loaded = {};
  function loadScript(src) {
    if (!loaded[src]) {
      loaded[src] = new Promise(function (resolve, reject) {
        var s = document.createElement("script");
        s.src = src; s.onload = resolve; s.onerror = reject;
        document.head.appendChild(s);
      });
    }
    return loaded[src];
  }
  function loadCss(href) {
    if (document.querySelector('link[href="' + href + '"]')) return;
    var l = document.createElement("link");
    l.rel = "stylesheet"; l.href = href;
    document.head.appendChild(l);
  }

  // ------------------------------------------------------------ tabelle
  function cellText(td) { return (td.textContent || "").trim(); }
  function initTable(fig) {
    if (fig.dataset.dtReady) return;
    fig.dataset.dtReady = "1";
    var table = fig.querySelector("table.dt-table");
    if (!table) return;
    var tbody = table.tBodies[0];
    var ths = table.tHead ? table.tHead.rows[0].cells : [];
    var count = fig.querySelector(".dt-count");
    Array.prototype.forEach.call(ths, function (th, idx) {
      if (th.classList.contains("dt-rn")) return;
      th.tabIndex = 0;
      th.setAttribute("aria-sort", "none");
      var sort = function () {
        var dir = th.getAttribute("aria-sort") === "ascending" ? -1 : 1;
        Array.prototype.forEach.call(ths, function (x) { x.setAttribute("aria-sort", "none"); });
        th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
        var rows = Array.prototype.slice.call(tbody.rows);
        rows.sort(function (a, b) {
          var ca = a.cells[idx], cb = b.cells[idx];
          if (!ca || !cb) return 0;
          var va = ca.dataset.v, vb = cb.dataset.v;
          if (va !== undefined && vb !== undefined && va !== "" && vb !== "") {
            var na = parseFloat(va), nb = parseFloat(vb);
            if (!isNaN(na) && !isNaN(nb) && /^-?[\d.e+-]+$/i.test(va)) return (na - nb) * dir;
            return (va < vb ? -1 : va > vb ? 1 : 0) * dir;
          }
          var ta = cellText(ca), tb = cellText(cb);
          if (!ta) return 1; if (!tb) return -1;
          return ta.localeCompare(tb, "it", { numeric: true, sensitivity: "base" }) * dir;
        });
        rows.forEach(function (r) { tbody.appendChild(r); });
      };
      th.addEventListener("click", sort);
      th.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sort(); } });
    });
    var search = fig.querySelector(".dt-search");
    if (search) {
      search.addEventListener("input", function () {
        var q = search.value.trim().toLowerCase(), shown = 0;
        Array.prototype.forEach.call(tbody.rows, function (r) {
          var hit = !q || r.textContent.toLowerCase().indexOf(q) >= 0;
          r.hidden = !hit; if (hit) shown++;
        });
        if (count) {
          var tot = count.dataset.total;
          count.textContent = q ? shown + " di " + tot + " righe" : (tot === "1" ? "1 riga" : tot + " righe");
        }
      });
    }
    var exp = fig.querySelector("[data-dt-export]");
    if (exp) {
      exp.addEventListener("click", function () {
        var lines = [];
        var esc = function (s) { s = String(s).replace(/\s+/g, " ").trim(); return /[";\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
        Array.prototype.forEach.call(table.rows, function (r) {
          if (r.hidden) return;
          lines.push(Array.prototype.map.call(r.cells, function (c) { return esc(cellText(c)); }).join(";"));
        });
        var blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
        var a = document.createElement("a");
        var title = fig.querySelector(".dt-title");
        a.href = URL.createObjectURL(blob);
        a.download = ((title && title.textContent) || "tabella").replace(/[\\/:*?"<>|]+/g, "-") + ".csv";
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
      });
    }
  }

  // ------------------------------------------------------------ countdown
  var cdTimer = null;
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function tickCountdowns() {
    var els = document.querySelectorAll("[data-countdown]");
    if (!els.length) { clearInterval(cdTimer); cdTimer = null; return; }
    var now = Date.now();
    els.forEach(function (el) {
      var t = new Date(el.dataset.countdown).getTime();
      if (isNaN(t)) return;
      var d = Math.max(0, Math.floor((t - now) / 1000));
      if (d <= 0) { el.textContent = el.dataset.done || "Scaduto"; el.classList.add("is-done"); return; }
      var days = Math.floor(d / 86400), h = Math.floor(d % 86400 / 3600), m = Math.floor(d % 3600 / 60), s = d % 60;
      var parts = [[days, days === 1 ? "giorno" : "giorni"], [pad(h), "ore"], [pad(m), "min"], [pad(s), "sec"]];
      el.innerHTML = "";
      parts.forEach(function (p) {
        var b = document.createElement("span"); b.className = "cd-part";
        var n = document.createElement("strong"); n.textContent = p[0];
        var l = document.createElement("small"); l.textContent = p[1];
        b.appendChild(n); b.appendChild(l); el.appendChild(b);
      });
    });
  }
  function initCountdowns(scope) {
    if (!scope.querySelector("[data-countdown]")) return;
    tickCountdowns();
    if (!cdTimer) cdTimer = setInterval(tickCountdowns, 1000);
  }

  // ------------------------------------------------------------ LaTeX
  function initMath(scope) {
    var els = scope.querySelectorAll(".arithmatex:not([data-math-done])");
    if (!els.length) return;
    loadCss("/static/vendor/katex/katex.min.css");
    loadScript("/static/vendor/katex/katex.min.js").then(function () {
      els.forEach(function (el) {
        if (el.dataset.mathDone) return;
        var tex = el.textContent.trim(), display = false;
        if (tex.indexOf("\\[") === 0) { tex = tex.slice(2, -2); display = true; }
        else if (tex.indexOf("\\(") === 0) { tex = tex.slice(2, -2); }
        else if (tex.indexOf("$$") === 0) { tex = tex.slice(2, -2); display = true; }
        else if (tex.charAt(0) === "$") { tex = tex.slice(1, -1); }
        try {
          window.katex.render(tex, el, { displayMode: display || el.tagName === "DIV", throwOnError: false, trust: false });
          el.dataset.mathDone = "1";
        } catch (e) { /* lascia il sorgente visibile */ }
      });
    }).catch(function () {});
  }

  // ------------------------------------------------------------ draw.io
  function initDiagrams(scope) {
    var els = scope.querySelectorAll(".mxgraph:not([data-dio-done])");
    if (!els.length) return;
    els.forEach(function (el) { el.dataset.dioDone = "1"; });
    window.onDrawioViewerLoad = function () { /* l'inizializzazione la facciamo noi */ };
    loadScript("/static/vendor/drawio/viewer-static.min.js").then(function () {
      els.forEach(function (el) {
        if (!document.body.contains(el) || el.querySelector("svg")) return;
        try { window.GraphViewer.createViewerForElement(el); } catch (e) { showDiagramError(el); }
      });
    }).catch(function () { els.forEach(showDiagramError); });
  }
  function showDiagramError(el) {
    var p = document.createElement("p");
    p.className = "plug-error";
    p.textContent = "Visualizzatore draw.io non disponibile su questo server (manca /static/vendor/drawio). Scarica il file per aprirlo.";
    el.replaceWith(p);
  }

  function init(scope) {
    scope = scope || document;
    scope.querySelectorAll("figure[data-dt]").forEach(initTable);
    initCountdowns(scope);
    initMath(scope);
    initDiagrams(scope);
  }
  window.AILADOC_PLUGINS = { init: init, loadScript: loadScript };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { init(document); });
  else init(document);
})();
