// The GDS Lens host for optodraw's layout view (the one-file page and the editor). GDS Lens asks its host for
// the Display toggles it starts with; its default host starts with outlines only, while KLayout draws filled
// layers, so this host starts with Infill, Ports and Grid on and Text off, and remembers the user's toggles.
// It must run before gds-lens.js. The viewer surface is published as window.gdsLens.
(function () {
  var KEY = "optodraw-gds-lens-display";
  var DEFAULTS = { showInfill: true, showText: false, showPorts: true, mergeOverlaps: false, showGrid: true };
  window.gdsLensHost = {
    loadDisplay: async function () {
      try {
        return Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem(KEY) || "{}"));
      } catch (err) {
        return Object.assign({}, DEFAULTS);
      }
    },
    saveDisplay: function (prefs) {
      try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch (err) { /* storage blocked: not kept */ }
    },
    connect: function (viewer) { window.gdsLens = viewer; },
  };
})();

// A page opened from disk (file://): Chrome starts no worker from a blob URL there, which is how GDS Lens starts
// its parse worker, but it does start one from a data: URL. So on such a page a Worker made from a blob URL reads
// the blob and starts the real worker from a data: URL, holding the messages posted until it runs.
(function () {
  if (location.protocol !== "file:" || !window.Worker) return;
  var NativeWorker = window.Worker;
  function asDataUrl(blob) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(reader.result); };
      reader.onerror = function () { reject(reader.error); };
      reader.readAsDataURL(blob);
    });
  }
  function FileWorker(url, options) {
    var target = new EventTarget();
    var self = this, real = null, ended = false, queue = [];
    function fire(type, init, Kind) {
      var event = new Kind(type, init);
      var handler = self["on" + type];
      if (typeof handler === "function") handler.call(self, event);
      target.dispatchEvent(event);
    }
    this.onmessage = this.onerror = this.onmessageerror = null;
    this.addEventListener = target.addEventListener.bind(target);
    this.removeEventListener = target.removeEventListener.bind(target);
    this.postMessage = function (message, transfer) {
      if (real) real.postMessage(message, transfer);
      else queue.push([message, transfer]);
    };
    this.terminate = function () { ended = true; if (real) real.terminate(); };
    fetch(url).then(function (reply) { return reply.blob(); }).then(asDataUrl).then(function (dataUrl) {
      if (ended) return;
      real = new NativeWorker(dataUrl, options);
      real.onmessage = function (e) { fire("message", { data: e.data, ports: e.ports }, MessageEvent); };
      real.onmessageerror = function (e) { fire("messageerror", { data: e.data }, MessageEvent); };
      real.onerror = function (e) {
        fire("error", { message: e.message, filename: e.filename, lineno: e.lineno }, ErrorEvent);
      };
      queue.forEach(function (item) { real.postMessage(item[0], item[1]); });
      queue = [];
    }).catch(function (error) {
      fire("error", { message: "could not start the viewer's worker: " + error }, ErrorEvent);
    });
  }
  window.Worker = function (url, options) {
    return String(url).indexOf("blob:") === 0 ? new FileWorker(url, options) : new NativeWorker(url, options);
  };
})();
