/* AIladoc — assistente per trovare i documenti */
(function () {
  "use strict";
  var panel = document.getElementById("assistant");
  if (!panel) return;

  var KEY = "ailadoc-assistant";
  var log = panel.querySelector("[data-assistant-log]");
  var welcome = panel.querySelector("[data-assistant-welcome]");
  var form = panel.querySelector("[data-assistant-form]");
  var input = form.querySelector("textarea");
  var sendBtn = form.querySelector("button");
  var state = load();
  var busy = false;
  var mobile = window.matchMedia("(max-width: 860px)");

  function load() {
    try {
      var s = JSON.parse(sessionStorage.getItem(KEY) || "null");
      if (s && Array.isArray(s.messages)) return s;
    } catch (e) {}
    return { open: false, messages: [] };
  }
  function save() {
    try { sessionStorage.setItem(KEY, JSON.stringify({ open: state.open, messages: state.messages.slice(-30) })); } catch (e) {}
  }

  // ---------------------------------------------------------------- apertura
  function open(focus) {
    panel.hidden = false;
    document.body.classList.add("assistant-open");
    state.open = true; save();
    if (focus !== false) setTimeout(function () { input.focus(); }, 30);
    scrollEnd();
  }
  function close() {
    panel.hidden = true;
    document.body.classList.remove("assistant-open");
    state.open = false; save();
  }
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-assistant-open]")) { panel.hidden ? open() : close(); return; }
    if (e.target.closest("[data-assistant-close]")) { close(); return; }
    if (e.target.closest("[data-assistant-reset]")) { reset(); return; }
    var ask = e.target.closest("[data-ask]");
    if (ask) { e.preventDefault(); open(false); send(ask.dataset.ask); return; }
    if (e.target.closest("[data-ask-search]")) {  // dalla pagina dei risultati: usa la ricerca fatta
      var box = document.querySelector(".search input[name=q]");
      e.preventDefault(); open(false); send(box ? box.value : ""); return;
    }
    var pre = e.target.closest("[data-prefill]");
    if (pre) { input.value = pre.dataset.prefill; autosize(); input.focus(); input.setSelectionRange(input.value.length, input.value.length); return; }
    // su mobile il pannello copre la pagina: chiudilo quando si apre una fonte
    if (e.target.closest(".assistant a[href]") && mobile.matches) { state.open = false; save(); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !panel.hidden && !document.querySelector("dialog[open]")) close();
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") { e.preventDefault(); panel.hidden ? open() : close(); }
  });

  // ----------------------------------------------------------------- input
  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 140) + "px";
  }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit ? form.requestSubmit() : submit(); }
  });
  form.addEventListener("submit", function (e) { e.preventDefault(); submit(); });
  function submit() {
    var q = input.value.trim();
    if (!q) return;
    input.value = ""; autosize();
    send(q);
  }

  // ------------------------------------------------------------- rendering
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function scrollEnd() { log.scrollTop = log.scrollHeight; }

  function renderMessage(m) {
    if (m.role === "user") {
      var u = el("div", "as-msg as-user");
      u.appendChild(el("div", "as-bubble", m.content));
      return u;
    }
    var a = el("div", "as-msg as-bot" + (m.error ? " as-error" : ""));
    var b = el("div", "as-bubble");
    if (m.html) b.innerHTML = m.html;          // HTML già sanificato dal server
    else b.textContent = m.content;
    a.appendChild(b);
    if (m.notice) a.appendChild(el("p", "as-notice", m.notice));
    if (m.sources && m.sources.length) {
      var list = el("ol", "as-sources");
      m.sources.forEach(function (s) {
        var li = el("li");
        var link = el("a", "as-src");
        link.href = s.url;
        var ic = el("span", "as-src-icon ic-bg-" + s.kind);
        ic.innerHTML = s.icon_html;              // SVG generato dal server
        var body = el("span", "as-src-body");
        var top = el("span", "as-src-title");
        top.appendChild(el("span", "as-src-n", String(s.n)));
        top.appendChild(document.createTextNode(s.title));
        body.appendChild(top);
        var meta = [s.kind_label, s.folder].concat(s.location ? [s.location] : []).join(" · ");
        body.appendChild(el("span", "as-src-meta", meta));
        if (s.snippet_html) {
          var sn = el("span", "as-src-snippet");
          sn.innerHTML = s.snippet_html;          // testo già escapato dal server, con <mark>
          body.appendChild(sn);
        }
        link.appendChild(ic); link.appendChild(body);
        li.appendChild(link);
        list.appendChild(li);
      });
      a.appendChild(list);
    }
    return a;
  }

  function renderAll() {
    Array.prototype.slice.call(log.querySelectorAll(".as-msg")).forEach(function (n) { n.remove(); });
    welcome.hidden = state.messages.length > 0;
    state.messages.forEach(function (m) { log.appendChild(renderMessage(m)); });
    scrollEnd();
  }

  function reset() {
    state.messages = []; save(); renderAll(); input.focus();
  }

  // ----------------------------------------------------------------- invio
  function send(q) {
    q = (q || "").trim();
    if (!q || busy) return;
    var history = state.messages.filter(function (m) { return !m.error; })
      .map(function (m) { return { role: m.role, content: m.content }; }).slice(-8);
    state.messages.push({ role: "user", content: q });
    save(); renderAll();
    busy = true; sendBtn.disabled = true;
    var typing = el("div", "as-msg as-bot as-typing");
    var tb = el("div", "as-bubble");
    tb.innerHTML = "<span></span><span></span><span></span>";
    tb.setAttribute("aria-label", "Sto cercando…");
    typing.appendChild(tb);
    log.appendChild(typing); scrollEnd();

    fetch("/api/assistant", {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json", "x-csrf-token": (window.AILADOC || {}).csrf || "" },
      body: JSON.stringify({ question: q, history: history })
    }).then(function (r) {
      var ct = r.headers.get("content-type") || "";
      if (ct.indexOf("application/json") === -1) {
        throw new Error(r.status === 403 || r.redirected ? "La sessione è scaduta: ricarica la pagina e accedi di nuovo."
          : "Errore del server (" + r.status + ").");
      }
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d.error || ("Errore " + r.status));
        return d;
      });
    }).then(function (d) {
      state.messages.push({ role: "assistant", content: d.answer, html: d.answer_html, sources: d.sources, notice: d.notice, mode: d.mode });
    }).catch(function (err) {
      state.messages.push({ role: "assistant", content: err && err.message ? err.message : "Qualcosa è andato storto. Riprova.", error: true });
    }).then(function () {
      busy = false; sendBtn.disabled = false;
      typing.remove(); save(); renderAll();
      if (!mobile.matches) input.focus();
    });
  }

  // ------------------------------------------------------------------ avvio
  renderAll();
  if (state.open && !mobile.matches) open(false);
})();
