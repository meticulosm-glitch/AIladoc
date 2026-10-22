(function () {
  "use strict";
  var root = document.documentElement;

  // Tema chiaro/scuro
  document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
    b.addEventListener("click", function () {
      var dark = root.dataset.theme ? root.dataset.theme === "dark"
        : window.matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("ailadoc-theme", root.dataset.theme); } catch (e) {}
    });
  });

  // Login: mostra/nascondi password e niente doppio invio
  document.querySelectorAll("[data-pw-toggle]").forEach(function (b) {
    b.addEventListener("click", function () {
      var input = b.parentNode.querySelector("input");
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      b.setAttribute("aria-pressed", show ? "true" : "false");
      b.setAttribute("aria-label", show ? "Nascondi password" : "Mostra password");
      b.title = b.getAttribute("aria-label");
      input.focus();
    });
  });
  document.querySelectorAll("[data-login-form]").forEach(function (f) {
    f.addEventListener("submit", function () {
      var b = f.querySelector("[data-login-submit]");
      if (!b) return;
      setTimeout(function () { b.disabled = true; b.querySelector("[data-label]").textContent = "Accesso in corso…"; }, 0);
    });
  });
  window.addEventListener("pageshow", function (e) {  // tornando indietro il pulsante torna attivo
    if (!e.persisted) return;
    document.querySelectorAll("[data-login-submit]").forEach(function (b) {
      b.disabled = false; b.querySelector("[data-label]").textContent = "Accedi";
    });
  });

  // Menu laterale su mobile
  document.querySelectorAll("[data-toggle-nav]").forEach(function (b) {
    b.addEventListener("click", function () { document.body.classList.toggle("nav-open"); });
  });

  // Mantieni visibile la voce attiva nel menu
  var active = document.querySelector(".sidebar .nav-item.active");
  if (active && active.scrollIntoView) active.scrollIntoView({ block: "center" });

  // Dialoghi
  document.addEventListener("click", function (e) {
    var opener = e.target.closest("[data-open]");
    if (opener) {
      var d = document.getElementById(opener.dataset.open);
      if (d && d.showModal) { closeMenus(); d.showModal(); }
    }
    var closer = e.target.closest("[data-close]");
    if (closer) { var dl = closer.closest("dialog"); if (dl) dl.close(); }
    if (!e.target.closest("details.usermenu, details.more")) closeMenus();
  });
  document.querySelectorAll("dialog").forEach(function (d) {
    d.addEventListener("click", function (e) { if (e.target === d) d.close(); });
  });
  function closeMenus() {
    document.querySelectorAll("details.usermenu[open], details.more[open]").forEach(function (d) { d.open = false; });
  }
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeMenus(); });

  // Conferme
  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) { if (!window.confirm(f.dataset.confirm)) e.preventDefault(); });
  });
  document.querySelectorAll("select[data-autosubmit]").forEach(function (s) {
    s.addEventListener("change", function () { s.form.submit(); });
  });

  // Tipo di destinatario nei permessi
  var ptype = document.querySelector("[data-ptype]");
  if (ptype) {
    var sync = function () {
      document.querySelectorAll("[data-pvalue]").forEach(function (el) {
        var on = el.dataset.pvalue === ptype.value;
        el.hidden = !on;
        el.querySelectorAll("input,select").forEach(function (i) { i.disabled = !on; i.required = on; });
      });
    };
    ptype.addEventListener("change", sync); sync();
  }

  // Tab dei fogli di calcolo
  document.querySelectorAll(".tabs .tab").forEach(function (t) {
    t.addEventListener("click", function () {
      t.parentNode.querySelectorAll(".tab").forEach(function (x) { x.classList.toggle("active", x === t); });
      document.querySelectorAll(".tabpanel").forEach(function (p) { p.classList.toggle("active", p.id === t.dataset.tab); });
    });
  });

  // Upload: elenco file scelti + drag&drop
  document.querySelectorAll("[data-drop]").forEach(function (zone) {
    var input = zone.querySelector("input[type=file]");
    var list = zone.querySelector("[data-drop-list]");
    var show = function () {
      var names = Array.prototype.map.call(input.files, function (f) { return f.name; });
      list.textContent = names.length ? names.length + " file: " + names.slice(0, 4).join(", ") + (names.length > 4 ? "…" : "") : "";
    };
    input.addEventListener("change", show);
    ["dragenter", "dragover"].forEach(function (ev) { zone.addEventListener(ev, function () { zone.classList.add("over"); }); });
    ["dragleave", "drop"].forEach(function (ev) { zone.addEventListener(ev, function () { zone.classList.remove("over"); setTimeout(show, 0); }); });
  });

  // Anteprima Office: nascondi "caricamento" quando l'iframe è pronto
  document.querySelectorAll("iframe[data-onload-hide]").forEach(function (f) {
    f.addEventListener("load", function () {
      var l = document.querySelector("[data-loading]"); if (l) l.remove();
    });
  });

  // Indice: evidenzia la sezione corrente
  var tocLinks = document.querySelectorAll(".toc a");
  if (tocLinks.length && "IntersectionObserver" in window) {
    var map = {};
    tocLinks.forEach(function (a) { map[decodeURIComponent(a.hash.slice(1))] = a; });
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting && map[en.target.id]) {
          tocLinks.forEach(function (a) { a.classList.remove("current"); });
          map[en.target.id].classList.add("current");
        }
      });
    }, { rootMargin: "-70px 0px -70% 0px" });
    document.querySelectorAll(".md-content :is(h2,h3,h4)[id]").forEach(function (h) { obs.observe(h); });
  }
})();
