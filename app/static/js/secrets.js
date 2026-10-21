(function () {
  "use strict";
  var csrf = window.AILADOC.csrf;
  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(body)
    }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  var form = document.getElementById("editor-form");
  var panel = form && form.querySelector("[data-secrets]");
  var check = function () { return Promise.resolve([]); };

  // "Non è una password" (pagina di amministrazione ed editor)
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-secret-ignore]");
    if (!b) return;
    b.disabled = true;
    post("/api/secrets/ignore", { path: b.dataset.path, fp: b.dataset.fp, label: b.dataset.label, masked: b.dataset.masked })
      .then(function () { if (panel && panel.contains(b)) check(); else window.location.reload(); })
      .catch(function () { b.disabled = false; alert("Non è stato possibile salvare la segnalazione."); });
  });

  if (!form || !panel || panel.dataset.enabled !== "1") return;
  var ta = document.getElementById("md-input");
  var list = panel.querySelector("[data-secrets-list]");
  var title = panel.querySelector("[data-secrets-title]");
  var confirmInput = form.querySelector("[data-confirm-secrets]");
  var policy = panel.dataset.policy;
  var canIgnore = panel.dataset.canIgnore === "1";
  var path = form.dataset.path;
  var current = [], timer = null, inflight = null, allowSubmit = false;

  function gotoLine(n) {
    n = parseInt(n, 10);
    if (!n) return;
    var lines = ta.value.split("\n"), pos = 0;
    for (var i = 0; i < n - 1 && i < lines.length; i++) pos += lines[i].length + 1;
    var end = pos + (lines[n - 1] || "").length;
    var panes = form.querySelector(".panes");
    if (panes && panes.dataset.mode === "preview") form.querySelector('[data-view="split"]').click();
    ta.focus();
    ta.setSelectionRange(pos, end);
    var lh = parseFloat(getComputedStyle(ta).lineHeight) || 22;
    ta.scrollTop = Math.max(0, (n - 4) * lh);
  }

  function render(items) {
    current = items;
    panel.hidden = !items.length;
    title.textContent = items.length + (items.length === 1 ? " possibile password nel testo" : " possibili password nel testo");
    list.innerHTML = items.map(function (f) {
      return '<li><button type="button" class="link" data-goto-line="' + f.line + '">' + esc(f.location) + "</button> " +
        '<span class="secret-label">' + esc(f.label) + "</span> " +
        '<code class="secret-ctx">' + esc(f.context) + "</code>" +
        (canIgnore ? ' <button type="button" class="btn small ghost" data-secret-ignore data-path="' + esc(path) +
          '" data-fp="' + esc(f.fp) + '" data-label="' + esc(f.label) + '" data-masked="' + esc(f.masked) + '">Non è una password</button>' : "") +
        "</li>";
    }).join("");
  }

  check = function () {
    clearTimeout(timer);
    inflight = post("/api/secrets/check", { content: ta.value, path: path })
      .then(function (d) { render(d.findings || []); return current; })
      .catch(function () { return current; });
    return inflight;
  };

  panel.addEventListener("click", function (e) {
    var g = e.target.closest("[data-goto-line]");
    if (g) gotoLine(g.dataset.gotoLine);
  });
  ta.addEventListener("input", function () {
    confirmInput.value = "";
    clearTimeout(timer);
    timer = setTimeout(check, 700);
  });

  // Prima di salvare: con possibili password chiedi conferma (o blocca, con SECRETS_POLICY=block)
  form.addEventListener("submit", function (e) {
    if (allowSubmit || confirmInput.value === "1") return;
    e.preventDefault();
    e.stopImmediatePropagation();
    check().then(function (items) {
      if (!items.length) { allowSubmit = true; form.requestSubmit(); return; }
      panel.classList.remove("shake"); void panel.offsetWidth; panel.classList.add("shake");
      panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
      if (policy === "block") return;
      var msg = (items.length === 1 ? "Il testo sembra contenere una password o una credenziale."
        : "Il testo sembra contenere " + items.length + " password o credenziali.") +
        "\nChi può leggere la pagina potrà vederle.\n\nSalvare comunque?";
      if (window.confirm(msg)) { confirmInput.value = "1"; allowSubmit = true; form.requestSubmit(); }
    });
  }, true);

  if (/^#L\d+$/.test(window.location.hash)) setTimeout(function () { gotoLine(window.location.hash.slice(2)); }, 50);
})();
