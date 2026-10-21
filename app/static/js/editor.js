(function () {
  "use strict";
  var form = document.getElementById("editor-form");
  if (!form) return;
  var ta = document.getElementById("md-input");
  var pv = document.getElementById("md-preview");
  var panes = form.querySelector(".panes");
  var csrf = window.AILADOC.csrf;
  var dirty = false, timer = null;

  function render() {
    fetch("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ content: ta.value, path: form.dataset.path })
    }).then(function (r) { return r.json(); }).then(function (d) {
      pv.innerHTML = d.html;
      pv.classList.toggle("numbered", !!d.numbered);
      if (window.AILADOC_MERMAID) window.AILADOC_MERMAID(pv);
      if (window.AILADOC_PLUGINS) window.AILADOC_PLUGINS.init(pv);
    }).catch(function () {});
  }
  ta.addEventListener("input", function () {
    dirty = true; clearTimeout(timer); timer = setTimeout(render, 250);
  });
  render();

  // Sincronizza lo scroll in modalità divisa
  ta.addEventListener("scroll", function () {
    var r = ta.scrollTop / Math.max(1, ta.scrollHeight - ta.clientHeight);
    pv.scrollTop = r * (pv.scrollHeight - pv.clientHeight);
  });

  form.addEventListener("submit", function () { dirty = false; });
  window.addEventListener("beforeunload", function (e) { if (dirty) { e.preventDefault(); e.returnValue = ""; } });

  // Vista
  form.querySelectorAll("[data-view]").forEach(function (b) {
    b.addEventListener("click", function () {
      panes.dataset.mode = b.dataset.view;
      form.querySelectorAll("[data-view]").forEach(function (x) { x.classList.toggle("active", x === b); });
      if (b.dataset.view !== "preview") ta.focus();
    });
  });

  // Toolbar Markdown
  function wrap(before, after, placeholder) {
    var s = ta.selectionStart, e = ta.selectionEnd, had = e > s;
    var sel = had ? ta.value.slice(s, e) : (placeholder || "");
    ta.setRangeText(before + sel + after, s, e, "end");
    if (!had) { ta.selectionStart = s + before.length; ta.selectionEnd = ta.selectionStart + sel.length; }
    ta.focus(); ta.dispatchEvent(new Event("input"));
  }
  function linePrefix(prefix, numbered) {
    var s = ta.selectionStart, e = ta.selectionEnd, v = ta.value;
    var ls = v.lastIndexOf("\n", s - 1) + 1;
    var le = v.indexOf("\n", e); if (le === -1) le = v.length;
    var lines = v.slice(ls, le).split("\n").map(function (l, i) { return (numbered ? (i + 1) + ". " : prefix) + l; });
    ta.setRangeText(lines.join("\n"), ls, le, "select");
    ta.focus(); ta.dispatchEvent(new Event("input"));
  }
  function insertBlock(text) {
    var s = ta.selectionStart, v = ta.value;
    // mai dentro il front matter (--- ... ---) in cima alla pagina
    var fm = /^---[ \t]*\n[\s\S]*?\n---[ \t]*(\n|$)/.exec(v);
    if (fm && s < fm[0].length) { ta.setSelectionRange(fm[0].length, fm[0].length); s = fm[0].length; }
    var pre = s > 0 && v[s - 1] !== "\n" ? "\n\n" : (s > 1 && v[s - 2] !== "\n" ? "\n" : "");
    replaceRange(pre + text + "\n", s, ta.selectionEnd);
  }
  // Sostituisce un tratto di testo mantenendo l'annulla (Ctrl Z) dove il browser lo consente
  function replaceRange(text, s, e) {
    ta.focus();
    ta.setSelectionRange(s, e);
    var ok = false;
    try { ok = document.execCommand && document.execCommand("insertText", false, text); } catch (err) { ok = false; }
    if (!ok) ta.setRangeText(text, s, e, "end");
    ta.dispatchEvent(new Event("input"));
  }
  window.AILADOC_EDITOR = {
    textarea: ta, form: form, insertBlock: insertBlock, replaceRange: replaceRange, render: render,
    insertInline: function (t) { replaceRange(t, ta.selectionStart, ta.selectionEnd); }
  };
  var actions = {
    heading: function () { linePrefix("## "); },
    bold: function () { wrap("**", "**", "testo"); },
    italic: function () { wrap("_", "_", "testo"); },
    code: function () {
      var sel = ta.value.slice(ta.selectionStart, ta.selectionEnd);
      if (sel.indexOf("\n") >= 0) wrap("```\n", "\n```", ""); else wrap("`", "`", "codice");
    },
    ul: function () { linePrefix("- "); },
    ol: function () { linePrefix("", true); },
    task: function () { linePrefix("- [ ] "); },
    quote: function () { linePrefix("> "); },
    link: function () { wrap("[", "](https://)", "testo del link"); },
    table: function () { insertBlock("| Colonna 1 | Colonna 2 |\n|-----------|-----------|\n| valore    | valore    |"); },
    note: function () { insertBlock('!!! note "Nota"\n    Testo della nota.'); },
    attach: function () { document.getElementById("attach-input").click(); }
  };
  form.querySelectorAll("[data-md]").forEach(function (b) {
    b.addEventListener("click", function () { actions[b.dataset.md](); });
  });
  ta.addEventListener("keydown", function (e) {
    var mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); dirty = false; form.requestSubmit ? form.requestSubmit() : form.submit(); }
    else if (mod && e.key.toLowerCase() === "b") { e.preventDefault(); actions.bold(); }
    else if (mod && e.key.toLowerCase() === "i") { e.preventDefault(); actions.italic(); }
    else if (e.key === "Tab") { e.preventDefault(); ta.setRangeText("    ", ta.selectionStart, ta.selectionEnd, "end"); }
  });

  // Allegati: caricati nella cartella della pagina e linkati
  function uploadFiles(files) {
    if (!files || !files.length) return;
    var fd = new FormData();
    fd.append("csrf", csrf);
    fd.append("folder", form.dataset.folder || "");
    Array.prototype.forEach.call(files, function (f) { fd.append("files", f); });
    fetch("/upload", { method: "POST", body: fd, headers: { "Accept": "application/json", "X-CSRF-Token": csrf } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var folder = form.dataset.folder ? form.dataset.folder + "/" : "";
        var md = d.saved.map(function (p) {
          var name = p.slice(folder.length);
          var url = name.split("/").map(encodeURIComponent).join("/");
          return /\.(png|jpe?g|gif|webp|svg)$/i.test(name) ? "![" + name + "](" + url + ")" : "[" + name + "](" + url + ")";
        }).join("\n");
        if (md) insertBlock(md);
        if (d.errors && d.errors.length) alert(d.errors.join("\n"));
      });
  }
  document.getElementById("attach-input").addEventListener("change", function (e) { uploadFiles(e.target.files); e.target.value = ""; });
  ta.addEventListener("dragover", function (e) { e.preventDefault(); });
  ta.addEventListener("drop", function (e) {
    if (e.dataTransfer && e.dataTransfer.files.length) { e.preventDefault(); uploadFiles(e.dataTransfer.files); }
  });
  ta.addEventListener("paste", function (e) {
    var files = e.clipboardData && e.clipboardData.files;
    if (files && files.length) { e.preventDefault(); uploadFiles(files); }
  });
})();
