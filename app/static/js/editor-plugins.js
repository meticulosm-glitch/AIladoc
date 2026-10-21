/* Editor: menu «Inserisci» dei plugin, editor visuale delle tabelle, incolla da Excel,
   scelta di file da citare (Excel/CSV, diagrammi, pagine) e diagrammi draw.io. */
(function () {
  "use strict";
  var E = window.AILADOC_EDITOR;
  var dataEl = document.getElementById("plugin-data");
  if (!E || !dataEl) return;
  var DATA = JSON.parse(dataEl.textContent);
  var ta = E.textarea, form = E.form;
  var folder = form.dataset.folder || "";

  // ------------------------------------------------------------ utilità
  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") n.textContent = attrs[k];
      else if (k === "class") n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function relPath(target) {
    var from = folder ? folder.split("/") : [], to = target.split("/");
    var i = 0;
    while (i < from.length && i < to.length - 1 && from[i] === to[i]) i++;
    var up = from.slice(i).map(function () { return ".."; });
    return up.concat(to.slice(i)).join("/");
  }
  function slug(s) {
    return s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  }

  // Dialogo generico: fields = [{name, label, type, value, options, placeholder}]
  function ask(title, fields, okLabel, extra) {
    return new Promise(function (resolve) {
      var dlg = el("dialog", { class: "dialog plug-dialog" });
      var f = el("form", { method: "dialog" });
      f.appendChild(el("h3", { text: title }));
      if (extra) f.appendChild(extra);
      var inputs = {};
      fields.forEach(function (fd) {
        var input;
        if (fd.type === "select") {
          input = el("select", { name: fd.name });
          fd.options.forEach(function (o) { input.appendChild(el("option", { value: o.value, text: o.label })); });
        } else if (fd.type === "checkbox") {
          input = el("input", { type: "checkbox", name: fd.name });
          input.checked = !!fd.value;
          var lab = el("label", { class: "field inline-check" }, [input, " " + fd.label]);
          f.appendChild(lab); inputs[fd.name] = input; return;
        } else {
          input = el("input", { type: fd.type || "text", name: fd.name, placeholder: fd.placeholder || "" });
          if (fd.min) input.min = fd.min; if (fd.max) input.max = fd.max;
          if (fd.value !== undefined) input.value = fd.value;
        }
        if (fd.required) input.required = true;
        inputs[fd.name] = input;
        f.appendChild(el("label", { class: "field" }, [fd.label, input, fd.help ? el("small", { class: "muted", text: fd.help }) : null]));
      });
      var cancel = el("button", { type: "button", class: "btn ghost", text: "Annulla" });
      var ok = el("button", { class: "btn primary", value: "ok", text: okLabel || "Inserisci" });
      f.appendChild(el("div", { class: "dialog-actions" }, [cancel, ok]));
      dlg.appendChild(f);
      document.body.appendChild(dlg);
      cancel.addEventListener("click", function () { dlg.close(); });
      dlg.addEventListener("close", function () {
        var out = null;
        if (dlg.returnValue === "ok") {
          out = {};
          Object.keys(inputs).forEach(function (k) { out[k] = inputs[k].type === "checkbox" ? inputs[k].checked : inputs[k].value; });
        }
        dlg.remove();
        ta.focus();
        resolve(out);
      });
      dlg.showModal();
      var first = f.querySelector("input,select");
      if (first) first.focus();
    });
  }

  function pickFile(title, kinds, extraFields, okLabel) {
    var files = DATA.files.filter(function (x) { return kinds.indexOf(x.kind) >= 0 && x.path !== form.dataset.path; });
    if (!files.length) {
      alert("Nessun file adatto nella documentazione che puoi vedere.");
      return Promise.resolve(null);
    }
    var opts = files.map(function (x) { return { value: x.path, label: x.title + "  —  " + x.path }; });
    return ask(title, [{ name: "path", label: "File", type: "select", options: opts }].concat(extraFields || []), okLabel);
  }

  // ------------------------------------------------------------ tabelle Markdown
  function splitRow(line) {
    var s = line.trim();
    if (s.charAt(0) === "|") s = s.slice(1);
    if (s.slice(-1) === "|" && s.slice(-2) !== "\\|") s = s.slice(0, -1);
    var cells = [], cur = "";
    for (var i = 0; i < s.length; i++) {
      if (s[i] === "\\" && s[i + 1] === "|") { cur += "|"; i++; continue; }
      if (s[i] === "|") { cells.push(cur.trim()); cur = ""; continue; }
      cur += s[i];
    }
    cells.push(cur.trim());
    return cells;
  }
  var SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
  function findTable() {
    var v = ta.value, pos = ta.selectionStart;
    var lines = v.split("\n"), offs = [], o = 0;
    lines.forEach(function (l) { offs.push(o); o += l.length + 1; });
    var li = 0;
    while (li < lines.length - 1 && offs[li + 1] <= pos) li++;
    var isRow = function (l) { return /\|/.test(l) && l.trim() !== ""; };
    if (!isRow(lines[li] || "")) return null;
    var a = li, b = li;
    while (a > 0 && isRow(lines[a - 1])) a--;
    while (b < lines.length - 1 && isRow(lines[b + 1])) b++;
    if (b - a < 1 || !SEP.test(lines[a + 1])) return null;
    var aligns = splitRow(lines[a + 1]).map(function (c) {
      var l = c.charAt(0) === ":", r = c.slice(-1) === ":";
      return l && r ? "center" : r ? "right" : l ? "left" : "";
    });
    var rows = [splitRow(lines[a])];
    for (var k = a + 2; k <= b; k++) rows.push(splitRow(lines[k]));
    var w = Math.max.apply(null, rows.map(function (r) { return r.length; }));
    rows = rows.map(function (r) { while (r.length < w) r.push(""); return r; });
    while (aligns.length < w) aligns.push("");
    return { start: offs[a], end: offs[b] + lines[b].length, rows: rows, aligns: aligns };
  }
  function toMarkdown(rows, aligns) {
    var w = rows[0].length, widths = [];
    var esc = function (c) { return String(c || "").replace(/\r?\n/g, " ").replace(/\|/g, "\\|").trim(); };
    rows = rows.map(function (r) { return r.map(esc); });
    for (var c = 0; c < w; c++) widths[c] = Math.max(3, Math.max.apply(null, rows.map(function (r) { return (r[c] || "").length; })));
    var line = function (r) {
      return "| " + r.map(function (cell, c) {
        var pad = widths[c] - cell.length;
        return aligns[c] === "right" ? " ".repeat(pad) + cell : cell + " ".repeat(pad);
      }).join(" | ") + " |";
    };
    var sep = "|" + widths.map(function (wd, c) {
      var a = aligns[c] || "";
      var d = "-".repeat(wd);
      if (a === "center") d = ":" + "-".repeat(wd) + ":";
      else if (a === "right") d = "-".repeat(wd + 1) + ":";
      else if (a === "left") d = ":" + "-".repeat(wd + 1);
      else d = "-".repeat(wd + 2);
      return d;
    }).join("|") + "|";
    return [line(rows[0]), sep].concat(rows.slice(1).map(line)).join("\n");
  }

  // Editor visuale: griglia di celle modificabili
  function tableEditor(init, onApply) {
    var rows = init.rows.map(function (r) { return r.slice(); });
    var aligns = init.aligns.slice();
    var cur = { r: 1, c: 0 };
    var dlg = el("dialog", { class: "dialog plug-dialog tbl-dialog" });
    var wrap = el("div", { class: "tbl-ed" });
    var title = el("h3", { text: init.isNew ? "Nuova tabella" : "Modifica tabella" });
    var bar = el("div", { class: "tbl-ed-bar" });
    var grid = el("div", { class: "tbl-ed-grid" });
    var hint = el("p", { class: "muted small", text: "Tab / Invio per spostarti · incolla celle da Excel per riempire più celle · la prima riga è l'intestazione." });
    function btn(label, tip, fn) {
      var b = el("button", { type: "button", class: "btn small", title: tip, text: label });
      b.addEventListener("click", function () { fn(); draw(); });
      bar.appendChild(b);
    }
    btn("+ Riga", "Aggiungi una riga sotto", function () { rows.splice(cur.r + 1, 0, rows[0].map(function () { return ""; })); cur.r++; });
    btn("+ Colonna", "Aggiungi una colonna a destra", function () { rows.forEach(function (r) { r.splice(cur.c + 1, 0, ""); }); aligns.splice(cur.c + 1, 0, ""); cur.c++; });
    btn("− Riga", "Elimina la riga", function () { if (rows.length > 2 && cur.r > 0) { rows.splice(cur.r, 1); cur.r = Math.min(cur.r, rows.length - 1); } });
    btn("− Colonna", "Elimina la colonna", function () { if (rows[0].length > 1) { rows.forEach(function (r) { r.splice(cur.c, 1); }); aligns.splice(cur.c, 1); cur.c = Math.min(cur.c, rows[0].length - 1); } });
    btn("↑", "Sposta la riga in su", function () { if (cur.r > 1) { var t = rows[cur.r]; rows[cur.r] = rows[cur.r - 1]; rows[cur.r - 1] = t; cur.r--; } });
    btn("↓", "Sposta la riga in giù", function () { if (cur.r > 0 && cur.r < rows.length - 1) { var t = rows[cur.r]; rows[cur.r] = rows[cur.r + 1]; rows[cur.r + 1] = t; cur.r++; } });
    btn("A→Z", "Ordina per questa colonna", function () { sortBy(1); });
    btn("Z→A", "Ordina al contrario", function () { sortBy(-1); });
    btn("⇤", "Allinea a sinistra", function () { aligns[cur.c] = "left"; });
    btn("↔", "Centra", function () { aligns[cur.c] = "center"; });
    btn("⇥", "Allinea a destra (numeri)", function () { aligns[cur.c] = "right"; });
    function num(s) {
      var t = String(s).replace(/[€$%\s]/g, "");
      if (/^-?\d{1,3}(\.\d{3})+(,\d+)?$|^-?\d+,\d+$/.test(t)) t = t.replace(/\./g, "").replace(",", ".");
      return /^-?\d+(\.\d+)?$/.test(t) ? parseFloat(t) : NaN;
    }
    function sortBy(dir) {
      var body = rows.slice(1), c = cur.c;
      body.sort(function (a, b) {
        var na = num(a[c]), nb = num(b[c]);
        if (!isNaN(na) && !isNaN(nb)) return (na - nb) * dir;
        return String(a[c]).localeCompare(String(b[c]), "it", { numeric: true }) * dir;
      });
      rows = [rows[0]].concat(body);
    }
    function draw() {
      grid.innerHTML = "";
      var t = el("table");
      rows.forEach(function (r, ri) {
        var tr = el("tr", { class: ri === 0 ? "head" : "" });
        r.forEach(function (cell, ci) {
          var td = el("td");
          var inp = el("input", { type: "text", "aria-label": "Riga " + (ri + 1) + ", colonna " + (ci + 1) });
          inp.value = cell;
          inp.style.textAlign = aligns[ci] || "left";
          inp.addEventListener("input", function () { rows[ri][ci] = inp.value; });
          inp.addEventListener("focus", function () { cur = { r: ri, c: ci }; mark(); });
          inp.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
              e.preventDefault();
              if (ri === rows.length - 1) { rows.push(rows[0].map(function () { return ""; })); cur = { r: ri + 1, c: ci }; draw(); }
              else focusCell(ri + 1, ci);
            } else if (e.key === "ArrowDown" && ri < rows.length - 1) { e.preventDefault(); focusCell(ri + 1, ci); }
            else if (e.key === "ArrowUp" && ri > 0) { e.preventDefault(); focusCell(ri - 1, ci); }
          });
          inp.addEventListener("paste", function (e) {
            var txt = e.clipboardData && e.clipboardData.getData("text/plain");
            if (!txt || (txt.indexOf("\t") < 0 && txt.indexOf("\n") < 0)) return;
            e.preventDefault();
            var data = parseTSV(txt);
            data.forEach(function (dr, i) {
              var rr = ri + i;
              while (rows.length <= rr) rows.push(rows[0].map(function () { return ""; }));
              dr.forEach(function (v, j) {
                var cc = ci + j;
                while (rows[0].length <= cc) { rows.forEach(function (x) { x.push(""); }); aligns.push(""); }
                rows[rr][cc] = v;
              });
            });
            draw();
          });
          td.appendChild(inp); tr.appendChild(td);
        });
        t.appendChild(tr);
      });
      grid.appendChild(t);
      mark();
      focusCell(cur.r, cur.c);
    }
    function mark() {
      grid.querySelectorAll("td").forEach(function (td) { td.classList.remove("cur-col", "cur-row"); });
      var trs = grid.querySelectorAll("tr");
      trs.forEach(function (tr, ri) {
        Array.prototype.forEach.call(tr.cells, function (td, ci) {
          if (ci === cur.c) td.classList.add("cur-col");
          if (ri === cur.r) td.classList.add("cur-row");
        });
      });
    }
    function focusCell(r, c) {
      var tr = grid.querySelectorAll("tr")[r];
      var inp = tr && tr.cells[c] && tr.cells[c].querySelector("input");
      if (inp) { inp.focus(); }
    }
    var cancel = el("button", { type: "button", class: "btn ghost", text: "Annulla" });
    var ok = el("button", { type: "button", class: "btn primary", text: init.isNew ? "Inserisci" : "Applica" });
    cancel.addEventListener("click", function () { dlg.close(); });
    ok.addEventListener("click", function () { onApply(toMarkdown(rows, aligns)); dlg.close(); });
    wrap.appendChild(title); wrap.appendChild(bar); wrap.appendChild(grid); wrap.appendChild(hint);
    wrap.appendChild(el("div", { class: "dialog-actions" }, [cancel, ok]));
    dlg.appendChild(wrap);
    document.body.appendChild(dlg);
    dlg.addEventListener("close", function () { dlg.remove(); ta.focus(); });
    dlg.showModal();
    draw();
  }

  function parseTSV(txt) {
    var rows = [], row = [], cell = "", q = false;
    txt = txt.replace(/\r\n?/g, "\n").replace(/\n$/, "");
    for (var i = 0; i < txt.length; i++) {
      var ch = txt[i];
      if (q) {
        if (ch === '"' && txt[i + 1] === '"') { cell += '"'; i++; }
        else if (ch === '"') q = false;
        else cell += ch;
      } else if (ch === '"' && cell === "") q = true;
      else if (ch === "\t") { row.push(cell); cell = ""; }
      else if (ch === "\n") { row.push(cell); rows.push(row); row = []; cell = ""; }
      else cell += ch;
    }
    row.push(cell); rows.push(row);
    var w = Math.max.apply(null, rows.map(function (r) { return r.length; }));
    return rows.map(function (r) { while (r.length < w) r.push(""); return r; });
  }

  function newTable() {
    ask("Nuova tabella", [
      { name: "cols", label: "Colonne", type: "number", value: 3, min: 1, max: 20 },
      { name: "rows", label: "Righe (oltre all'intestazione)", type: "number", value: 3, min: 1, max: 200 }
    ], "Continua").then(function (v) {
      if (!v) return;
      var c = Math.max(1, Math.min(20, parseInt(v.cols, 10) || 3)), r = Math.max(1, Math.min(200, parseInt(v.rows, 10) || 3));
      var rows = [Array.from({ length: c }, function (_, i) { return "Colonna " + (i + 1); })];
      for (var i = 0; i < r; i++) rows.push(Array.from({ length: c }, function () { return ""; }));
      tableEditor({ rows: rows, aligns: rows[0].map(function () { return ""; }), isNew: true }, function (md) { E.insertBlock(md); });
    });
  }
  function editTable() {
    var t = findTable();
    if (!t) {
      if (confirm("Metti il cursore dentro una tabella Markdown per modificarla.\nVuoi crearne una nuova?")) newTable();
      return;
    }
    tableEditor(t, function (md) { E.replaceRange(md, t.start, t.end); });
  }

  // Incolla da Excel / Google Sheets: celle separate da tabulazioni → tabella Markdown
  ta.addEventListener("paste", function (e) {
    if (e.defaultPrevented) return;
    var cd = e.clipboardData;
    if (!cd || (cd.files && cd.files.length)) return;
    var txt = cd.getData("text/plain");
    if (!txt || txt.indexOf("\t") < 0 || txt.replace(/\r?\n$/, "").indexOf("\n") < 0) return;
    var rows = parseTSV(txt);
    if (rows.length < 2 || rows[0].length < 2) return;
    e.preventDefault();
    var aligns = rows[0].map(function (_, c) {
      var nums = rows.slice(1).filter(function (r) { return /^[-+]?[\d.,]+\s*[€%]?$|^€\s*[-\d.,]+$/.test(r[c].trim()); }).length;
      return nums && nums >= (rows.length - 1) / 2 ? "right" : "";
    });
    E.insertBlock(toMarkdown(rows, aligns));
  });

  // ------------------------------------------------------------ azioni
  function tableFromFile() {
    pickFile("Tabella da un file Excel o CSV", ["sheet"], [
      { name: "title", label: "Titolo (facoltativo)", placeholder: "es. Listino 2026" },
      { name: "sheet", label: "Foglio (facoltativo)", placeholder: "nome o numero, vuoto = il primo" },
      { name: "filter", label: "Filtro (facoltativo)", placeholder: "es. Prezzo > 100 and Categoria = \"Rete\"" },
      { name: "chart", label: "Grafico", type: "select", options: [
        { value: "", label: "Nessuno" }, { value: "bar", label: "Barre" }, { value: "hbar", label: "Barre orizzontali" },
        { value: "line", label: "Linee" }, { value: "area", label: "Aree" }, { value: "pie", label: "Torta" }, { value: "donut", label: "Ciambella" }] }
    ]).then(function (v) {
      if (!v) return;
      var lines = ["/// table" + (v.title ? " | " + v.title : ""), "    source: " + relPath(v.path)];
      if (v.sheet) lines.push("    sheet: " + v.sheet);
      if (v.filter) lines.push("    filter: " + v.filter);
      if (v.chart) lines.push("    chart: " + v.chart);
      lines.push("    totals: true", "///");
      E.insertBlock(lines.join("\n"));
    });
  }
  function includePage() {
    pickFile("Includi (cita) un'altra pagina", ["markdown"], [
      { name: "section", label: "Solo una sezione (facoltativo)", placeholder: "titolo della sezione, es. Come richiedere le ferie" }
    ]).then(function (v) {
      if (!v) return;
      var anchor = v.section ? "#" + slug(v.section) : "";
      E.insertBlock("/// include | " + relPath(v.path) + anchor + "\n///");
    });
  }
  function insertDiagram() {
    pickFile("Inserisci un diagramma draw.io", ["diagram"], [
      { name: "caption", label: "Didascalia (facoltativa)" }
    ]).then(function (v) {
      if (!v) return;
      E.insertBlock("/// drawio | " + relPath(v.path) + (v.caption ? "\n    caption: " + v.caption : "") + "\n///");
    });
  }
  function newDiagram() {
    if (!DATA.drawio) { alert("La modifica dei diagrammi non è configurata (DRAWIO_EDITOR_URL)."); return; }
    ask("Nuovo diagramma draw.io", [
      { name: "name", label: "Nome del file", placeholder: "es. schema-rete", required: true,
        help: "Il file .drawio viene creato nella cartella della pagina e si apre l'editor." }
    ], "Crea e apri").then(function (v) {
      if (!v || !v.name) return;
      window.AILADOC_DRAWIO.create(folder, v.name).then(function (d) {
        E.insertBlock("/// drawio | " + relPath(d.path) + "\n///");
        DATA.files.push({ path: d.path, title: d.name, kind: "diagram" });
        window.AILADOC_DRAWIO.edit(d.path, { url: DATA.drawio, mtime: d.mtime, onClose: function () { E.render(); }, onSave: function () { E.render(); } });
      }).catch(function (err) { alert(err.message); });
    });
  }
  var ACTIONS = { "table-new": newTable, "table-edit": editTable, "table-source": tableFromFile,
                  "include": includePage, "drawio-insert": insertDiagram, "drawio-new": newDiagram };

  // Modifica rapida dei diagrammi dall'anteprima (doppio clic)
  var pv = document.getElementById("md-preview");
  if (pv && DATA.drawio) {
    pv.addEventListener("dblclick", function (e) {
      var fig = e.target.closest("figure[data-drawio]");
      if (!fig) return;
      window.AILADOC_DRAWIO.edit(fig.dataset.path, { url: DATA.drawio, onClose: function (saved) { if (saved) E.render(); } });
    });
  }

  // ------------------------------------------------------------ menu «Inserisci»
  var menu = form.querySelector("[data-insert-menu]");
  if (menu) {
    var btnOpen = menu.querySelector(".tb-insert-btn"), list = menu.querySelector(".tb-insert-list");
    var group = null;
    DATA.snippets.forEach(function (s) {
      if (s.group !== group) { group = s.group; list.appendChild(el("div", { class: "tb-insert-group", text: group })); }
      var b = el("button", { type: "button", role: "menuitem", class: "tb-insert-item" },
        [el("span", { class: "tb-insert-ic", text: s.icon || "•", "aria-hidden": "true" }), el("span", { text: s.label })]);
      if ((s.action === "drawio-new") && !DATA.drawio) b.disabled = true;
      b.addEventListener("click", function () {
        toggle(false);
        if (s.action) ACTIONS[s.action]();
        else if (s.inline) E.insertInline(s.text);
        else E.insertBlock(s.text);
      });
      list.appendChild(b);
    });
    var search = el("input", { type: "search", class: "tb-insert-search", placeholder: "Cerca macro…", "aria-label": "Cerca macro" });
    list.insertBefore(search, list.firstChild);
    search.addEventListener("input", function () {
      var q = search.value.trim().toLowerCase();
      list.querySelectorAll(".tb-insert-item").forEach(function (b) { b.hidden = q && b.textContent.toLowerCase().indexOf(q) < 0; });
      list.querySelectorAll(".tb-insert-group").forEach(function (g) {
        var n = g.nextElementSibling, any = false;
        while (n && !n.classList.contains("tb-insert-group")) { if (!n.hidden) any = true; n = n.nextElementSibling; }
        g.hidden = !any;
      });
    });
    function toggle(on) {
      list.hidden = !on; btnOpen.setAttribute("aria-expanded", on ? "true" : "false");
      if (on) { search.value = ""; search.dispatchEvent(new Event("input")); search.focus(); }
    }
    btnOpen.addEventListener("click", function () { toggle(list.hidden); });
    document.addEventListener("click", function (e) { if (!menu.contains(e.target)) toggle(false); });
    list.addEventListener("keydown", function (e) { if (e.key === "Escape") { toggle(false); btnOpen.focus(); } });
  }

  // Il pulsante ▦ della barra apre l'editor visuale (dentro una tabella: la modifica)
  var tb = form.querySelector('[data-md="table"]');
  if (tb) {
    var clone = tb.cloneNode(true);
    clone.title = "Tabella (dentro una tabella: modifica visuale)";
    tb.replaceWith(clone);
    clone.addEventListener("click", function () { if (findTable()) editTable(); else newTable(); });
  }
})();
