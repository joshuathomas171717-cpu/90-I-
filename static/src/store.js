/* ═══════════════════════════════════════════════════════════════════════════
   STORE — namespaced local persistence (P8.1)

   Small on purpose. It holds two kinds of thing: which clubs a reader follows,
   and the What-If scenarios they saved. Neither is precious, and both have to
   survive being absent.

   The three hard requirements, and why each one is here:

   1. SCHEMA VERSION + MIGRATIONS. Everything lives under one namespaced key as a
      single JSON blob with a version. A future release that changes the shape
      reads the old blob, runs the migrations in order, and writes it back —
      instead of finding keys it does not understand and corrupting them, or
      throwing away what the reader saved. A version is cheap now and impossible
      to retrofit onto data already in people's browsers.

   2. IT MUST NEVER THROW. localStorage throws in private-mode Safari, throws
      when the quota is full, and is absent in a sandboxed iframe — which is
      exactly where this dashboard is previewed. Every access is wrapped: if the
      backend is unusable, the store falls back to an in-memory object and the
      UI says the data will not be kept. A dashboard that dies on load because a
      browser refused a cookie jar is worse than one that forgets.

   3. IT MUST NEVER BRICK THE APP. Corrupt JSON, a blob from a newer version, a
      value of the wrong type: all of it degrades to "empty" rather than to an
      exception on the critical path.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  var NAMESPACE = "nt90";         // every key this app writes starts with this
  var KEY = NAMESPACE + ":state"; // one blob: { v: <schema>, data: {…} }
  var VERSION = 4;                // bump when the shape of `data` changes

  /* Migrations run in ascending order from the stored version up to VERSION. Each entry takes the
     whole data object and returns the next one. Never edit one once shipped: the reader's browser
     may still be sitting on the version it migrates away from.

     v1 -> v2: favourites and scenarios were two separate keys, and favourites were an array of club
     codes. They are now one object with a `scenarios` list that carries names and timestamps. */
  var MIGRATIONS = {
    1: function (data) {
      var favs = data && data.favourites;
      return {
        favourites: Array.isArray(favs) ? favs : [],
        scenarios: [],
        lastView: (data && data.lastView) || null,
      };
    },
  };

  // v2 saved scenarios retain their original method. v3 may store frozen named-player profiles.
  MIGRATIONS[2] = function(data){ return data || fresh(); };
  // v3 -> v4: local game worlds and personal prediction challenges; legacy scenario maths stay intact.
  MIGRATIONS[3] = function(data){ data=data||fresh();if(!Array.isArray(data.careers))data.careers=[];if(!Array.isArray(data.predictionChallenges))data.predictionChallenges=[];return data; };

  var memory = null;              // the fallback store, created on first use
  var backendState = null;

  function backend() {
    if (backendState !== null) return backendState;
    try {
      var ls = window.localStorage;
      var probe = NAMESPACE + ":probe";
      ls.setItem(probe, "1");
      ls.removeItem(probe);
      backendState = ls;
    } catch (e) {
      backendState = false;       // no storage: private mode, sandbox, or a full quota
    }
    return backendState;
  }

  function fresh() {
    return { favourites: [], scenarios: [], lastView: null, careers: [], predictionChallenges: [] };
  }

  function readRaw() {
    var store = backend();
    var text = null;
    if (store) {
      try { text = store.getItem(KEY); } catch (e) { text = null; }
    } else {
      text = memory ? memory[KEY] : null;
    }
    if (!text) return { v: VERSION, data: fresh(), created: null };
    var blob;
    try {
      blob = JSON.parse(text);
    } catch (e) {
      // Corrupt: keep the damaged text aside rather than silently overwriting it, then start clean.
      try { if (store) store.setItem(KEY + ":corrupt", text); } catch (e2) {}
      return { v: VERSION, data: fresh(), created: null, recovered: true };
    }
    if (!blob || typeof blob !== "object" || typeof blob.v !== "number") {
      return { v: VERSION, data: fresh(), created: null, recovered: true };
    }
    // A blob from a NEWER release than this build: leave it alone and run read-only. Writing would
    // destroy fields this version has never heard of.
    if (blob.v > VERSION) {
      return { v: blob.v, data: fresh(), created: null, future: true, readOnly: true };
    }
    var data = blob.data;
    if (!data || typeof data !== "object") data = fresh();
    var v = blob.v;
    while (v < VERSION) {
      var step = MIGRATIONS[v];
      data = step ? step(data) : data;
      v += 1;
    }
    // Fill in anything a migration did not provide, so callers never have to check.
    var base = fresh();
    for (var k in base) if (!(k in data)) data[k] = base[k];
    return { v: VERSION, data: data, created: blob.created || null, migrated: blob.v < VERSION };
  }

  function writeRaw(blob) {
    // A blob written by a NEWER release is never touched. This branch is the difference between
    // "your saved scenarios are filed away until you update" and silently destroying fields this
    // build has never heard of. The edit still applies for this page load, in memory.
    if (blob.readOnly) {
      if (!memory) memory = {};
      memory[KEY] = JSON.stringify({ v: blob.v, data: blob.data });
      futureWriteBlocked = true;
      return false;
    }
    blob.v = VERSION;
    blob.data = blob.data || fresh();
    var text = JSON.stringify(blob);
    var store = backend();
    if (!store) {
      if (!memory) memory = {};
      memory[KEY] = text;
      return false;              // persisted only for this page load
    }
    try {
      store.setItem(KEY, text);
      return true;
    } catch (e) {
      // Most likely the quota. Keep the value for this session rather than losing the reader's edit.
      if (!memory) memory = {};
      memory[KEY] = text;
      quotaExceeded = true;
      return false;
    }
  }

  var quotaExceeded = false;
  var futureWriteBlocked = false;
  var cache = null;

  function load() {
    if (!cache) cache = readRaw();
    return cache;
  }

  var STORE = {
    VERSION: VERSION,
    NAMESPACE: NAMESPACE,
    KEY: KEY,

    /** Is this browser keeping the data, or only holding it for the session? */
    persistent: function () { return !!backend(); },

    /** True when the last write could not be persisted (quota, private mode, sandbox, newer data). */
    degraded: function () { return !backend() || quotaExceeded || futureWriteBlocked; },

    /** True when stored data came from a release newer than this build, so it is never overwritten. */
    readOnly: function () { return !!load().readOnly; },

    /** Whole state, migrated to this version. Returns a copy: callers cannot corrupt the cache. */
    all: function () {
      var tot = load();
      return JSON.parse(JSON.stringify(tot.data));
    },

    get: function (field, fallback) {
      var d = load().data;
      return (field in d && d[field] !== undefined && d[field] !== null) ? d[field] : fallback;
    },

    set: function (field, value) {
      var blob = load();
      blob.data[field] = value;
      if (!blob.created) blob.created = new Date().toISOString();
      writeRaw(blob);
      return value;
    },

    /** Structural report, for the tests and for the about panel. */
    describe: function () {
      var blob = load();
      return {
        version: blob.v,
        storedVersion: blob.v,
        migrated: !!blob.migrated,
        recovered: !!blob.recovered,
        future: !!blob.future,
        readOnly: !!blob.readOnly,
        persistent: !!backend(),
        degraded: !backend() || quotaExceeded || futureWriteBlocked,
        fields: Object.keys(blob.data),
      };
    },

    /** Everything, gone. Used by the "forget my data" control and by the tests. */
    clear: function () {
      cache = { v: VERSION, data: fresh(), created: null };
      var store = backend();
      if (store) {
        try { store.removeItem(KEY); } catch (e) {}
        // The quarantine copy holds the reader's old data — the very thing they just asked to
        // forget — so it goes with it. Leaving it meant "Forget everything" left a copy behind.
        try { store.removeItem(KEY + ":corrupt"); } catch (e) {}
      }
      if (memory) { delete memory[KEY]; delete memory[KEY + ":corrupt"]; }
      return true;
    },

    /* ── favourites (P8.2) ───────────────────────────────────────────────────────────────────── */

    favourites: function () {
      var f = load().data.favourites;
      return Array.isArray(f) ? f.slice() : [];
    },

    follows: function (code) {
      return STORE.favourites().indexOf(code) !== -1;
    },

    toggleFavourite: function (code) {
      var list = STORE.favourites();
      var i = list.indexOf(code);
      if (i === -1) list.push(code); else list.splice(i, 1);
      // Keep the set sorted and deduplicated: a stale duplicate from an older release would
      // otherwise make the same club appear twice in the personalised view.
      list = list.filter(function (c, j) { return c && list.indexOf(c) === j; }).sort();
      STORE.set("favourites", list);
      return i === -1;
    },

    /* ── saved scenarios (P8.2) ──────────────────────────────────────────────────────────────── */

    scenarios: function () {
      var s = load().data.scenarios;
      return Array.isArray(s) ? s.slice() : [];
    },

    saveScenario: function (name, scenario) {
      var list = STORE.scenarios();
      var entry = {
        id: "s" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
        name: String(name || "").slice(0, 60) || "Untitled scenario",
        saved: new Date().toISOString(),
        // Stored as the scenario object itself, not as a share payload: a saved scenario has to
        // survive a change to the share format, and the store's own migration path handles the rest.
        scenario: JSON.parse(JSON.stringify(scenario || {})),
      };
      list.unshift(entry);
      if (list.length > 40) list = list.slice(0, 40);   // bounded: this is a browser, not a database
      STORE.set("scenarios", list);
      return entry;
    },

    deleteScenario: function (id) {
      var list = STORE.scenarios().filter(function (e) { return e.id !== id; });
      STORE.set("scenarios", list);
      return list.length;
    },

    renameScenario: function (id, name) {
      var list = STORE.scenarios();
      for (var i = 0; i < list.length; i++) {
        if (list[i].id === id) list[i].name = String(name || "").slice(0, 60) || list[i].name;
      }
      STORE.set("scenarios", list);
      return list;
    },
  };

  window.NT90_STORE = STORE;
  // Node (the test suite drives this file directly) has no `window`; export for that case.
  if (typeof module !== "undefined" && module.exports) module.exports = STORE;
})();
