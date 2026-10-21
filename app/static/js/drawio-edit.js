/* Modifica dei diagrammi con l'editor draw.io incorporato (protocollo "embed" JSON).
   Il diagramma passa tra questa pagina e l'iframe con postMessage e viene salvato da AIladoc
   (/api/drawio/save): non viene caricato sui server di draw.io. */
(function () {
  "use strict";
  var csrf = (window.AILADOC || {}).csrf;

  function edit(path, opts) {
    opts = opts || {};
    var url = opts.url;
    if (!url) { alert("Editor draw.io non configurato (DRAWIO_EDITOR_URL)."); return; }
    var origin = new URL(url, location.href).origin;
    var mtime = opts.mtime || "";
    var saved = false;

    var overlay = document.createElement("div");
    overlay.className = "drawio-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-label", "Modifica diagramma");
    var bar = document.createElement("div");
    bar.className = "drawio-overlay-bar";
    var title = document.createElement("strong");
    title.textContent = path.split("/").pop();
    var status = document.createElement("span");
    status.className = "drawio-overlay-status";
    status.textContent = "Caricamento dell'editor…";
    var close = document.createElement("button");
    close.type = "button"; close.className = "btn small"; close.textContent = "Chiudi";
    bar.appendChild(title); bar.appendChild(status); bar.appendChild(close);
    var frame = document.createElement("iframe");
    frame.title = "Editor draw.io";
    frame.setAttribute("allow", "clipboard-read; clipboard-write");
    frame.src = url;
    overlay.appendChild(bar); overlay.appendChild(frame);
    document.body.appendChild(overlay);
    document.body.classList.add("drawio-open");

    var xmlPromise = fetch("/raw/" + path.split("/").map(encodeURIComponent).join("/"), { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); });

    function post(msg) { frame.contentWindow.postMessage(JSON.stringify(msg), origin); }
    function finish() {
      window.removeEventListener("message", onMsg);
      overlay.remove();
      document.body.classList.remove("drawio-open");
      if (opts.onClose) opts.onClose(saved);
    }
    close.addEventListener("click", function () {
      if (!saved && !confirm("Chiudere l'editor? Le modifiche non salvate andranno perse.")) return;
      finish();
    });

    function onMsg(e) {
      if (e.origin !== origin || e.source !== frame.contentWindow || typeof e.data !== "string") return;
      var msg;
      try { msg = JSON.parse(e.data); } catch (err) { return; }
      if (msg.event === "init") {
        xmlPromise.then(function (xml) {
          post({ action: "load", xml: xml, title: path.split("/").pop(), autosave: 0, saveAndExit: 1 });
          status.textContent = "";
        }).catch(function () {
          status.textContent = "Impossibile leggere il diagramma.";
        });
      } else if (msg.event === "save") {
        status.textContent = "Salvataggio…";
        fetch("/api/drawio/save", {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
          body: JSON.stringify({ path: path, xml: msg.xml, mtime: mtime })
        }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
          .then(function (res) {
            if (!res.ok) throw new Error(res.d.error || "Salvataggio non riuscito");
            saved = true; mtime = res.d.mtime;
            var note = res.d.conflict ? " (attenzione: qualcun altro l'aveva modificato nel frattempo)" : "";
            if (res.d.secrets) note += " · contiene " + res.d.secrets + " possibili password";
            status.textContent = "Salvato" + note;
            post({ action: "status", message: "Salvato", modified: false });
            if (opts.onSave) opts.onSave();
            if (msg.exit) finish();
          }).catch(function (err) {
            status.textContent = String(err.message || err);
            post({ action: "dialog", title: "Salvataggio non riuscito", message: String(err.message || err), button: "OK" });
          });
      } else if (msg.event === "exit") {
        finish();
      }
    }
    window.addEventListener("message", onMsg);
  }

  function create(folder, name) {
    return fetch("/api/drawio/new", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ folder: folder || "", name: name })
    }).then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || "Errore"); return d; }); });
  }

  window.AILADOC_DRAWIO = { edit: edit, create: create };

  document.querySelectorAll("[data-drawio-edit]").forEach(function (b) {
    b.addEventListener("click", function () {
      edit(b.dataset.drawioEdit, {
        url: b.dataset.drawioUrl, mtime: (window.AILADOC || {}).diagramMtime,
        onClose: function (saved) { if (saved) location.reload(); }
      });
    });
  });
})();
