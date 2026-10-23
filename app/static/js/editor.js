(function () {
  "use strict";
  var form = document.getElementById("editor-form");
  if (!form) return;
  var ta = document.getElementById("md-input");
  var pv = document.getElementById("md-preview");
  var panes = form.querySelector(".panes");
  var csrf = window.AILADOC.csrf;
  var dirty = false, timer = null, onRender = null, syncPausedUntil = 0;

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
      if (onRender) onRender();
    }).catch(function () {});
  }
  ta.addEventListener("input", function () {
    dirty = true; clearTimeout(timer); timer = setTimeout(render, 250);
  });
  render();

  // Sincronizza lo scroll in modalità divisa
  ta.addEventListener("scroll", function () {
    if (Date.now() < syncPausedUntil) return;
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

  // ------------------------------------------------------------ immagini e allegati
  // Le immagini hanno tre dimensioni, salvate come classe CSS con la sintassi attr_list
  // (compatibile MkDocs Material): ![foto](foto.png){ .img-media }
  var SIZES = [
    { key: "piccola", label: "Piccola", hint: "circa un terzo della larghezza" },
    { key: "media", label: "Media", hint: "circa due terzi della larghezza" },
    { key: "grande", label: "Grande", hint: "tutta la larghezza della pagina" }
  ];
  var SIZE_CLASS = /(^|\s)\.img-(piccola|media|grande)(?=\s|$)/g;
  var IMG_EXT = /\.(png|jpe?g|gif|webp|svg|bmp)$/i;
  // ![alt](url "titolo"){ attributi } — url anche tra <...> o con parentesi bilanciate: foto (1).png
  var IMG_TOKEN = /!\[((?:\\.|[^\]\\\n])*)\]\(\s*(<[^>\n]*>|(?:[^\s()]|\([^\s()]*\))+)(\s+(?:"[^"\n]*"|'[^'\n]*'))?\s*\)(\{[^}\n]*\})?/g;
  var lastSize = "media";
  try { lastSize = localStorage.getItem("ailadoc.imgSize") || lastSize; } catch (err) {}
  function rememberSize(s) { lastSize = s; try { localStorage.setItem("ailadoc.imgSize", s); } catch (err) {} }

  function sizeOf(attr) { var m = /\.img-(piccola|media|grande)(?=\s|\}|$)/.exec(attr || ""); return m ? m[1] : null; }
  function withSize(attr, size) {
    var inner = attr ? attr.slice(1, -1).replace(/^\s*:/, "") : "";
    inner = inner.replace(SIZE_CLASS, " ").replace(/\s+/g, " ").trim();
    if (size) inner = (".img-" + size + " " + inner).trim();
    return inner ? "{ " + inner + " }" : "";
  }
  function decode(u) { try { return decodeURIComponent(u); } catch (err) { return u; } }
  // Stessa risoluzione del server (render.py): relativo alla cartella della pagina, servito da /raw/
  function imageKey(url) {
    if (url.charAt(0) === "<") url = url.slice(1, -1);
    url = url.split("#")[0].split("?")[0];
    if (/^([a-z][a-z0-9+.-]*:|\/)/i.test(url)) return decode(url);
    var parts = form.dataset.folder ? form.dataset.folder.split("/") : [];
    decode(url).split("/").forEach(function (seg) {
      if (seg === "..") parts.pop(); else if (seg && seg !== ".") parts.push(seg);
    });
    return "/raw/" + parts.join("/");
  }
  // Immagini Markdown nel testo (escluse quelle nei blocchi di codice)
  function imageTokens() {
    var v = ta.value, code = [], m, out = [];
    var fence = /^ {0,3}(`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:\n {0,3}\1[ \t]*(?=\n|$)|$)/gm;
    while ((m = fence.exec(v))) code.push([m.index, m.index + m[0].length]);
    IMG_TOKEN.lastIndex = 0;
    while ((m = IMG_TOKEN.exec(v))) {
      var s = m.index;
      if (code.some(function (r) { return s >= r[0] && s < r[1]; })) continue;
      var attr = m[4] || "";
      out.push({ start: s, end: s + m[0].length, attrStart: s + m[0].length - attr.length, attr: attr, key: imageKey(m[2]) });
    }
    return out;
  }
  function tokenAtCaret() {
    var s = ta.selectionStart, e = ta.selectionEnd;
    return imageTokens().filter(function (t) { return s >= t.start && e <= t.end && s <= t.end; })[0] || null;
  }
  function applySize(t, size) { replaceRange(withSize(t.attr, size), t.attrStart, t.end); }

  // Allegati: caricati nella cartella della pagina e linkati; le immagini con la dimensione scelta
  function uploadFiles(files, size) {
    if (!files || !files.length) return;
    size = size || lastSize;
    var fd = new FormData();
    fd.append("csrf", csrf);
    fd.append("folder", form.dataset.folder || "");
    Array.prototype.forEach.call(files, function (f) { fd.append("files", f); });
    fetch("/upload", { method: "POST", body: fd, headers: { "Accept": "application/json", "X-CSRF-Token": csrf } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var folder = form.dataset.folder ? form.dataset.folder + "/" : "";
        var md = (d.saved || []).map(function (p) {
          var name = p.slice(folder.length);
          var url = name.split("/").map(encodeURIComponent).join("/").replace(/\(/g, "%28").replace(/\)/g, "%29");
          var label = name.replace(/[\[\]\\]/g, "\\$&");
          if (!IMG_EXT.test(name)) return "[" + label + "](" + url + ")";
          return "![" + label.replace(/\.[^.]+$/, "") + "](" + url + ")" + withSize("", size);
        }).join("\n");
        if (md) insertBlock(md);
        if (d.errors && d.errors.length) alert(d.errors.join("\n"));
      })
      .catch(function () { alert("Caricamento non riuscito: controlla la connessione e riprova."); });
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

  // Menu del pulsante immagine: carica con una dimensione, o ridimensiona quella sotto il cursore
  var imgMenu = form.querySelector("[data-img-menu]");
  var imgInput = document.getElementById("image-input");
  if (imgMenu && imgInput) {
    var imgBtn = imgMenu.querySelector(".tb-img-btn"), imgList = imgMenu.querySelector(".tb-img-list");
    var pendingSize = lastSize;
    var mk = function (tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
    var item = function (size, checked, onClick) {
      var b = mk("button", "tb-insert-item tb-img-item");
      b.type = "button"; b.setAttribute("role", "menuitemradio"); b.setAttribute("aria-checked", checked ? "true" : "false");
      var g = mk("span", "size-glyph size-glyph-" + size.key); g.setAttribute("aria-hidden", "true"); g.appendChild(mk("i"));
      var t = mk("span", "", size.label); t.appendChild(mk("small", "", size.hint));
      b.appendChild(g); b.appendChild(t);
      b.addEventListener("click", onClick);
      return b;
    };
    var closeMenu = function () { imgList.hidden = true; imgBtn.setAttribute("aria-expanded", "false"); };
    var openMenu = function () {
      imgList.innerHTML = "";
      var tok = tokenAtCaret();
      if (tok) {
        var cur = sizeOf(tok.attr);
        imgList.appendChild(mk("div", "tb-insert-group", "Immagine selezionata"));
        SIZES.forEach(function (s) {
          imgList.appendChild(item(s, s.key === cur, function () { closeMenu(); applySize(tokenAtCaret() || tok, s.key); }));
        });
        imgList.appendChild(mk("div", "tb-insert-group", "Nuova immagine"));
        var up = mk("button", "tb-insert-item", "Carica un'altra immagine…");
        up.type = "button"; up.setAttribute("role", "menuitem");
        up.addEventListener("click", function () { closeMenu(); pendingSize = lastSize; imgInput.click(); });
        imgList.appendChild(up);
      } else {
        imgList.appendChild(mk("div", "tb-insert-group", "Carica un'immagine"));
        SIZES.forEach(function (s) {
          imgList.appendChild(item(s, s.key === lastSize, function () {
            closeMenu(); rememberSize(s.key); pendingSize = s.key; imgInput.click();
          }));
        });
        imgList.appendChild(mk("p", "tb-img-hint",
          "Trascina o incolla un'immagine nel testo: usa l'ultima dimensione scelta. Per cambiarla dopo, passa il mouse sull'immagine nell'anteprima."));
      }
      imgList.hidden = false; imgBtn.setAttribute("aria-expanded", "true");
      var first = imgList.querySelector("[aria-checked=true]") || imgList.querySelector("button");
      if (first) first.focus();
    };
    imgBtn.addEventListener("click", function () { if (imgList.hidden) openMenu(); else closeMenu(); });
    document.addEventListener("click", function (e) { if (!imgMenu.contains(e.target)) closeMenu(); });
    imgList.addEventListener("keydown", function (e) {
      var items = Array.prototype.slice.call(imgList.querySelectorAll("button")), i = items.indexOf(document.activeElement);
      if (e.key === "Escape") { closeMenu(); imgBtn.focus(); }
      else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
      }
    });
    imgInput.addEventListener("change", function (e) { uploadFiles(e.target.files, pendingSize); e.target.value = ""; });
  }

  // Barra «Piccola · Media · Grande» sulle immagini dell'anteprima
  var bar = document.createElement("div");
  bar.className = "img-size-bar"; bar.hidden = true;
  bar.setAttribute("role", "toolbar"); bar.setAttribute("aria-label", "Dimensione immagine");
  SIZES.forEach(function (s) {
    var b = document.createElement("button");
    b.type = "button"; b.dataset.size = s.key; b.textContent = s.label;
    bar.appendChild(b);
  });
  document.body.appendChild(bar);
  var barImg = null, hideTimer = null, overBar = false;
  function placeBar(img) {
    barImg = img;
    var r = img.getBoundingClientRect(), pr = pv.getBoundingClientRect();
    var cur = img.dataset.imgSize || "";
    bar.querySelectorAll("button").forEach(function (b) {
      var on = b.dataset.size === cur;
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.title = on ? "Torna alla dimensione originale" : "Mostra l'immagine " + b.textContent.toLowerCase();
    });
    // se il mouse è sulla barra non spostarla: l'immagine ridimensionata può cambiare posto
    if (overBar && !bar.hidden) return;
    bar.hidden = false;
    var top = Math.max(r.top, pr.top) + 8, left = Math.max(r.left, pr.left) + 8;
    bar.style.top = Math.min(top, pr.bottom - bar.offsetHeight - 8) + "px";
    bar.style.left = Math.max(pr.left + 4, Math.min(left, pr.right - bar.offsetWidth - 8)) + "px";
  }
  function hideBar() { bar.hidden = true; barImg = null; overBar = false; }
  function hideSoon() { clearTimeout(hideTimer); hideTimer = setTimeout(hideBar, 250); }
  function bindPreviewImages() {
    var groups = {};
    imageTokens().forEach(function (t) { (groups[t.key] = groups[t.key] || []).push(t); });
    var seen = {}, again = null;
    pv.querySelectorAll("img").forEach(function (img) {
      if (/\baura-/.test(img.className) || img.closest("[data-drawio]")) return;
      var key = decode(img.getAttribute("src") || ""), nth = seen[key] || 0;
      var tok = groups[key] && groups[key][nth];
      if (!tok) return;
      seen[key] = nth + 1;
      img.dataset.imgKey = key; img.dataset.imgNth = nth; img.dataset.imgSize = sizeOf(tok.attr) || "";
      img.title = "Cambia dimensione";
      if (barImg && barImg.dataset.imgKey === key && barImg.dataset.imgNth === String(nth)) again = img;
    });
    if (again) placeBar(again); else if (!bar.hidden) hideBar();
  }
  pv.addEventListener("mouseover", function (e) {
    var img = e.target.closest && e.target.closest("img[data-img-key]");
    if (img) { clearTimeout(hideTimer); placeBar(img); }
  });
  pv.addEventListener("mouseout", function (e) { if (e.target.matches && e.target.matches("img[data-img-key]")) hideSoon(); });
  pv.addEventListener("click", function (e) {
    var img = e.target.closest && e.target.closest("img[data-img-key]");
    if (img) { e.preventDefault(); clearTimeout(hideTimer); placeBar(img); }
  });
  bar.addEventListener("mouseenter", function () { overBar = true; clearTimeout(hideTimer); });
  bar.addEventListener("mouseleave", function () { overBar = false; hideSoon(); });
  pv.addEventListener("scroll", function () { if (Date.now() >= syncPausedUntil) hideBar(); });
  window.addEventListener("resize", hideBar);
  bar.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b || !barImg) return;
    var key = barImg.dataset.imgKey, nth = +barImg.dataset.imgNth;
    var tok = imageTokens().filter(function (t) { return t.key === key; })[nth];
    if (!tok) return;
    var size = sizeOf(tok.attr) === b.dataset.size ? null : b.dataset.size;
    // modifica il testo senza far saltare né l'anteprima né l'editor
    var keepPv = pv.scrollTop, keepTa = ta.scrollTop;
    syncPausedUntil = Date.now() + 400;
    applySize(tok, size);
    ta.scrollTop = keepTa;
    // risposta immediata, senza aspettare il nuovo rendering
    SIZES.forEach(function (s) { barImg.classList.remove("img-" + s.key); });
    if (size) barImg.classList.add("img-" + size);
    barImg.dataset.imgSize = size || "";
    pv.scrollTop = keepPv;
    placeBar(barImg);
  });
  onRender = bindPreviewImages;
})();
