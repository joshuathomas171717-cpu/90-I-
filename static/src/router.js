/* ══════════════════════════════════════════════════════════════════════════════════════════════
   ROUTER — real URLs, working back button, deep links (P5.3)

   The dashboard was one URL: whatever you were looking at, `location.href` said the same thing. You
   could not send someone "the table" or "Arsenal", and the browser's back button walked out of the
   app entirely.

   Every view now has a path — /table, /awards, /duel, /whatif, /model, /gameweek/6, /club/arsenal —
   and the server serves this same file for all of them (it cannot know which view you want; only the
   client can). Three rules keep it honest:

     · A route that only the app understands must never become a dead end. If someone opens
       /gameweek/12 and the app only carries the next two gameweeks, we go to the matchweek view and
       say so rather than pretending — and the crawlable page for that week is linked from the footer.
     · Loading a route must not fight the first paint. The initial render happens with no history
       entry; only a *change* pushes one.
     · Assets are relative, so the same build works from file://, from Pages at /90-I-/, and from a
       local server. A route is only applied when we are actually served over http(s).
   ══════════════════════════════════════════════════════════════════════════════════════════════ */
(function(){
  "use strict";

  const VIEW_PATH = { matchweek:"/", table:"/table", awards:"/awards", duel:"/duel",
                      whatif:"/whatif", model:"/model" };
  const PATH_VIEW = Object.fromEntries(Object.entries(VIEW_PATH).map(([v, p]) => [p, v]));
  const ROUTED = location.protocol === "http:" || location.protocol === "https:";

  function parse(path){
    let p = (path || "/").replace(/\/index\.html$/i, "/").replace(/\/+$/, "");
    if(p === "") p = "/";
    const club = p.match(/^\/club\/([a-z0-9'\-]+)$/i);
    if(club) return { view:"table", club:club[1].toLowerCase() };
    const gw = p.match(/^\/gameweek\/(?:mw)?(\d+)$/i);
    if(gw) return { view:"matchweek", gw:parseInt(gw[1], 10) };
    if(PATH_VIEW[p]) return { view:PATH_VIEW[p] };
    return { view:"matchweek", unknown:true };
  }

  function pathFor(route){
    if(!route) return "/";
    if(route.club) return "/club/" + route.club;
    if(route.gw) return "/gameweek/" + route.gw;
    return VIEW_PATH[route.view] || "/";
  }

  /* Slug matching mirrors site_pages.py's _slug(): "nott'm forest" → "nott-m-forest". */
  function slugify(name){
    return String(name || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  }

  /** Which gameweeks can this page actually show? Only the two the payload carries. */
  function availableGameweeks(){
    const out = [];
    const m = (DATA && DATA.meta) || {};
    if(m.next_gw) out.push(m.next_gw);
    if(m.after_gw) out.push(m.after_gw);
    return out;
  }

  function highlightClub(slug){
    const row = [...document.querySelectorAll("tr[data-code]")].find(tr => {
      const t = (DATA.teams || []).find(x => x.code === tr.dataset.code);
      return t && (slugify(t.name) === slug || t.code.toLowerCase() === slug);
    });
    if(!row){
      toast("No club matches “" + slug + "” — here is the whole table.");
      return false;
    }
    row.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block:"center" });
    row.classList.remove("moment"); void row.offsetWidth; row.classList.add("moment");
    return true;
  }

  /** Apply a route without touching history — used for the first paint and for popstate. */
  function apply(route, opts){
    opts = opts || {};
    if(route.view){
      const section = $("tab-" + route.view);
      const already = section && section.classList.contains("on");
      // switchTab does the slide + reveal choreography; it no-ops on the view already showing, which
      // is what we want on first load (no pointless animation) but not when a deep link needs to
      // re-highlight inside it.
      if(!already || opts.force) switchTab(route.view);
    }
    if(route.club) setTimeout(() => highlightClub(route.club), alreadyDelay());
    if(route.gw){
      const have = availableGameweeks();
      if(have.length && have.indexOf(route.gw) === -1){
        toast("Matchweek " + route.gw + " is beyond the model's next two weeks — showing matchweek "
              + have[0] + ". Its fixture list is on the matchweek page.", 6000);
      }
    }
  }

  function alreadyDelay(){ return REDUCED ? 0 : 420; }

  /** Navigate: push a history entry (unless this is the first paint) and apply. */
  function go(view, opts){
    opts = opts || {};
    if(opts.replace) history.replaceState({ view:view, club:opts.club, gw:opts.gw }, "",
                                          ROUTED ? pathFor(opts) : location.href);
    else if(ROUTED) history.pushState({ view:view, club:opts.club, gw:opts.gw }, "", pathFor(opts));
    apply({ view:view, club:opts.club, gw:opts.gw }, { force:true });
  }

  function init(){
    if(!ROUTED) return;   // file:// or a sandboxed preview: no URL to route

    // Tab clicks become real navigations.
    document.querySelectorAll("nav.tabs button").forEach(b => {
      b.onclick = () => go(b.dataset.tab);
    });
    // Anything that jumps to a view (the hero button, an award card, a fixture row) routes too. These
    // handlers were installed by render.js; wrapping switchTab keeps every one of them consistent
    // without touching each call site.
    const original = window.switchTab;
    if(typeof original === "function"){
      window.switchTab = function(name){
        original.apply(null, arguments);
        if(ROUTED && pathFor({ view:name }) !== location.pathname){
          history.pushState({ view:name }, "", pathFor({ view:name }));
        }
      };
    }
    window.addEventListener("popstate", (e) => {
      apply(e.state && e.state.view ? e.state : parse(location.pathname), { force:true });
    });

    // Deep-link-friendly links are generated by the static pages; remember the arrival for the
    // share affordance so "copy link" reproduces what you are looking at.
    const route = parse(location.pathname);
    if(route.view !== "matchweek" || route.club || route.gw){
      history.replaceState({ view:route.view, club:route.club, gw:route.gw }, "", location.href);
      apply(route, { force:!!route.club });
    } else {
      history.replaceState({ view:"matchweek" }, "", location.href);
    }
  }

  window.NT90_ROUTER = { go:go, parse:parse, pathFor:pathFor, apply:apply, slugify:slugify };
  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
