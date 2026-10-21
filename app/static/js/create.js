(function () {
  "use strict";
  var dlg = document.getElementById("dlg-create");
  if (!dlg) return;
  var form = dlg.querySelector("[data-create-form]");
  var parentSel = form.querySelector("[data-cparent]");
  var title = form.querySelector("[data-ctitle]");
  var tree = form.querySelector("[data-ctree]");
  var label = form.querySelector("[data-clabel]");
  var preview = form.querySelector("[data-cpreview]");
  var indexWrap = form.querySelector("[data-cindex]");
  var indexBox = indexWrap.querySelector("input");
  var errorBox = form.querySelector("[data-cerror]");
  var logBox = form.querySelector("[data-clog]");
  var hint = form.querySelector("[data-chint]");
  var btnContinue = form.querySelector("[data-ccontinue]");
  var btnSubmit = form.querySelector("[data-csubmit]");
  var existing = {};
  (window.AILADOC_FOLDERS || []).forEach(function (f) { existing[f] = true; });
  var mode = "page", busy = false, createdSomething = false;

  // --- stessa logica del server (app/creator.py) per l'anteprima ---------------
  function slugify(t) {
    return t.normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^A-Za-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "").toLowerCase().slice(0, 80).replace(/-+$/, "");
  }
  function folderName(t) {
    return t.replace(/[\\/:*?"<>|\x00-\x1f]/g, "").replace(/\s+/g, " ").trim().replace(/^\.+|\.+$/g, "").trim();
  }
  function pageTitle(t) { return t.replace(/\s+/g, " ").trim().replace(/\.(md|markdown)$/i, "").trim(); }
  function esc(s) { return s.replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  function updatePreview() {
    var raw = title.value.trim();
    if (!raw) { preview.hidden = true; return; }
    var kind = /\/$/.test(raw) ? "folder" : mode;
    var segs = raw.replace(/^\/+|\/+$/g, "").split("/").map(function (s) { return s.trim(); }).filter(Boolean);
    if (!segs.length) { preview.hidden = true; return; }
    var cur = parentSel.value, parts = [], newFolders = [];
    var folderSegs = kind === "folder" ? segs : segs.slice(0, -1);
    folderSegs.forEach(function (s) {
      var n = folderName(s) || "?";
      cur = cur ? cur + "/" + n : n;
      parts.push(esc(n) + "/");
      if (!existing[cur]) newFolders.push(n);
    });
    var html = '<span class="muted">/' + (parentSel.value ? esc(parentSel.value) + "/" : "") + "</span>" + parts.join("");
    if (kind === "page") {
      var t = pageTitle(segs[segs.length - 1]);
      html += "<strong>" + esc((slugify(t) || "pagina") + ".md") + "</strong>";
    }
    var extra = newFolders.length ? '<span class="create-new">' + (newFolders.length === 1 ? "nuova cartella: " : "nuove cartelle: ") + esc(newFolders.join(", ")) + "</span>" : "";
    preview.innerHTML = '<code>' + html + "</code>" + extra;
    preview.hidden = false;
    if (kind !== mode) indexWrap.hidden = false;
    else indexWrap.hidden = mode === "page";
  }

  function setMode(m) {
    mode = m;
    form.querySelectorAll("[data-cmode]").forEach(function (b) { b.classList.toggle("active", b.dataset.cmode === m); });
    form.querySelector('[data-cpanel="single"]').hidden = m === "tree";
    form.querySelector('[data-cpanel="tree"]').hidden = m !== "tree";
    indexWrap.hidden = m === "page";
    indexBox.checked = m === "folder";
    label.textContent = m === "folder" ? "Nome della cartella" : "Titolo della pagina";
    title.placeholder = m === "folder" ? "es. Procedure/Qualità" : "es. Procedure/Qualità/Controllo accessi";
    btnContinue.hidden = m === "tree";
    btnSubmit.textContent = m === "tree" ? "Crea struttura" : "Crea e apri";
    hint.hidden = m === "tree";
    errorBox.hidden = true;
    updatePreview();
    (m === "tree" ? tree : title).focus();
  }

  function open(parent, m) {
    if (parent !== undefined && parent !== null) {
      var ok = Array.prototype.some.call(parentSel.options, function (o) { return o.value === parent; });
      if (ok) parentSel.value = parent;
    }
    errorBox.hidden = true;
    logBox.hidden = true; logBox.innerHTML = "";
    title.value = ""; createdSomething = false;
    document.querySelectorAll("details.usermenu[open], details.more[open]").forEach(function (d) { d.open = false; });
    dlg.showModal();
    setMode(m || "page");
  }

  function submit(keepOpen) {
    if (busy) return;
    var body = { parent: parentSel.value, mode: mode, index: !indexWrap.hidden && indexBox.checked, flash: !keepOpen };
    if (mode === "tree") body.text = tree.value; else body.title = title.value;
    if ((mode === "tree" ? tree.value : title.value).trim() === "") {
      showError(mode === "tree" ? "Scrivi almeno una riga." : "Scrivi un titolo."); return;
    }
    busy = true; btnSubmit.disabled = btnContinue.disabled = true; errorBox.hidden = true;
    fetch("/api/create", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json", "X-CSRF-Token": window.AILADOC.csrf },
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return { error: r.status === 403 ? "Non hai i permessi per creare qui." : "Errore imprevisto (" + r.status + ")." }; });
    }).then(function (d) {
      if (d.error) {
        showError(d.error, d.url);
        if (d.items && d.items.some(function (i) { return i.created; })) { createdSomething = true; log(d.items); }
        return;
      }
      if (keepOpen) {
        createdSomething = true;
        log(d.items);
        d.items.forEach(function (i) { if (i.kind === "folder") existing[i.path] = true; });
        title.value = ""; updatePreview(); title.focus();
      } else {
        window.location.href = d.url;
      }
    }).catch(function () { showError("Impossibile contattare il server."); })
      .then(function () { busy = false; btnSubmit.disabled = btnContinue.disabled = false; });
  }

  function showError(msg, url) {
    errorBox.innerHTML = esc(msg) + (url ? ' <a href="' + esc(url) + '">Apri</a>' : "");
    errorBox.hidden = false;
  }
  function log(items) {
    items.filter(function (i) { return i.created; }).forEach(function (i) {
      var li = document.createElement("li");
      var href = i.kind === "page" ? "/edit/" + i.path.split("/").map(encodeURIComponent).join("/") : "/d/" + i.path.split("/").map(encodeURIComponent).join("/");
      li.innerHTML = '<span class="ok">✓</span> ' + (i.kind === "folder" ? "Cartella " : "Pagina ") + '<a href="' + href + '">/' + esc(i.path) + "</a>";
      logBox.appendChild(li);
    });
    logBox.hidden = !logBox.children.length;
    logBox.scrollTop = logBox.scrollHeight;
  }

  // --- eventi ---------------------------------------------------------------
  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-create]");
    if (!t) return;
    e.preventDefault(); e.stopPropagation(); // dentro un <summary> non deve aprire/chiudere la cartella
    document.body.classList.remove("nav-open");
    open(t.dataset.parent, t.dataset.mode);
  }, true);
  form.querySelectorAll("[data-cmode]").forEach(function (b) { b.addEventListener("click", function () { setMode(b.dataset.cmode); }); });
  title.addEventListener("input", updatePreview);
  parentSel.addEventListener("change", function () { updatePreview(); (mode === "tree" ? tree : title).focus(); });
  form.addEventListener("submit", function (e) { e.preventDefault(); submit(false); });
  btnContinue.addEventListener("click", function () { submit(true); });
  title.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); submit(e.shiftKey); }
  });
  tree.addEventListener("keydown", function (e) {
    if (e.key === "Tab") { // rientro con Tab / Shift+Tab sulle righe selezionate
      e.preventDefault();
      var v = tree.value, s = tree.selectionStart, en = tree.selectionEnd;
      var ls = v.lastIndexOf("\n", s - 1) + 1, le = v.indexOf("\n", en); if (le === -1) le = v.length;
      var lines = v.slice(ls, le).split("\n").map(function (l) { return e.shiftKey ? l.replace(/^ {1,2}/, "") : "  " + l; });
      tree.setRangeText(lines.join("\n"), ls, le, "select");
    } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(false); }
    else if (e.key === "Enter") { // mantieni il rientro della riga corrente
      var pos = tree.selectionStart, start = tree.value.lastIndexOf("\n", pos - 1) + 1;
      var indent = (tree.value.slice(start, pos).match(/^\s*/) || [""])[0];
      if (/\/\s*$/.test(tree.value.slice(start, pos))) indent += "  ";
      e.preventDefault(); tree.setRangeText("\n" + indent, pos, tree.selectionEnd, "end");
    }
  });
  dlg.addEventListener("close", function () { if (createdSomething) window.location.reload(); });

  // Scorciatoia: N apre il dialogo (fuori dai campi di testo)
  document.addEventListener("keydown", function (e) {
    if (e.key !== "n" && e.key !== "N") return;
    if (e.ctrlKey || e.metaKey || e.altKey || dlg.open || document.querySelector("dialog[open]")) return;
    var el = document.activeElement;
    if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
    e.preventDefault();
    var btn = document.querySelector(".sidebar-new");
    open(btn ? btn.dataset.parent : "");
  });
})();
