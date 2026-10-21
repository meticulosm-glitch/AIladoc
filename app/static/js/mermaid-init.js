(function () {
  "use strict";
  // Carica mermaid (incluso nell'immagine Docker in /static/vendor) solo se serve.
  var loading = null;
  function load() {
    if (window.mermaid) return Promise.resolve(window.mermaid);
    if (loading) return loading;
    loading = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = "/static/vendor/mermaid.min.js";
      s.onload = function () { resolve(window.mermaid); };
      s.onerror = reject;
      document.head.appendChild(s);
    });
    return loading;
  }
  function isDark() {
    var t = document.documentElement.dataset.theme;
    return t ? t === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  }
  function run(scope) {
    var nodes = (scope || document).querySelectorAll("pre.mermaid:not([data-processed])");
    if (!nodes.length) return;
    load().then(function (m) {
      m.initialize({ startOnLoad: false, theme: isDark() ? "dark" : "default", securityLevel: "strict" });
      m.run({ nodes: nodes });
    }).catch(function () {});
  }
  window.AILADOC_MERMAID = run;
  run(document);
})();
