/* ══════════════════════════════════════════════════════════════════════════════════════════════
   SHARE — versioned links, share affordances, and downloadable cards (P6.1, P6.2, P6.4)

   Three things, one idea: the state you are looking at should be something you can hand to someone
   else, and the thing they receive should look as good as the app.

   ── P6.1 versioned state ───────────────────────────────────────────────────────────────────────
   The scenario payload has a **version** in front of it (`v1-…`). That sounds like ceremony until
   you need it: a link is a promise with an indefinite lifetime, and the day the payload gains a field
   or renames one, every link already sent has to keep working. With a version, the reader can tell an
   old link from a corrupt one and migrate it; without one, it can only guess. Unversioned tokens
   (everything shared before this existed) are still read as version 1.

   ── P6.2 affordances ───────────────────────────────────────────────────────────────────────────
   Copy a link to the exact scenario or duel. On a phone, the native share sheet. And on a fixture
   card, an "open in Duel" link that carries the two clubs through, so a shared fixture lands on the
   duel rather than on the dashboard's front page.

   ── P6.4 the card ──────────────────────────────────────────────────────────────────────────────
   A 1200×630 PNG drawn on a canvas and downloaded — the thing that lands in a group chat. The palette
   and layout deliberately mirror og_image.py, so a link preview and a downloaded card look like the
   same product.
   ══════════════════════════════════════════════════════════════════════════════════════════════ */
(function(){
  "use strict";

  const VERSION = 1;
  const PREFIX = "v" + VERSION + "-";
  const CARD_W = 1200, CARD_H = 630;

  /* ── base64url that survives a URL, a chat client and a copy-paste ── */
  function b64url(s){
    return btoa(unescape(encodeURIComponent(s))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function unb64url(t){
    const b = t.replace(/-/g, "+").replace(/_/g, "/");
    return decodeURIComponent(escape(atob(b + "=".repeat((4 - b.length % 4) % 4))));
  }

  const NT90_SHARE = {
    VERSION: VERSION,

    /** Scenario → token. Short keys keep the URL short; only non-default values are carried. */
    encode: function(scenario){
      const s = scenario || {};
      const compact = { i:{}, b:{}, d:{}, c:{} };
      Object.entries(s.player_injuries || {}).forEach(([k, v]) => { if(v > 0) compact.i[k] = v; });
      Object.entries(s.team_boosts || {}).forEach(([k, v]) => {
        if((v && (v.attack || 0)) || (v && (v.defence || 0))) compact.b[k] = [v.attack || 0, v.defence || 0];
      });
      Object.entries(s.points_deductions || {}).forEach(([k, v]) => { if(v > 0) compact.d[k] = v; });
      Object.entries(s.custom_scores || {}).forEach(([k, v]) => { compact.c[k] = v; });
      return PREFIX + b64url(JSON.stringify(compact));
    },

    /** Token → scenario. Accepts v1 and the unversioned tokens shared before versions existed. */
    decode: function(token){
      if(typeof token !== "string" || !token) throw new Error("empty token");
      let body = token, version = 1, migrated = false;
      const m = token.match(/^v(\d+)-(.*)$/);
      if(m){
        version = parseInt(m[1], 10);
        body = m[2];
        if(version > VERSION) throw new Error("this link was made by a newer version of NINETY+");
      } else {
        migrated = true;                       // a pre-version link: readable, and worth a note
      }
      const c = JSON.parse(unb64url(body));
      return {
        version: version,
        migrated: migrated,
        scenario: {
          player_injuries: c.i || {},
          team_boosts: Object.fromEntries(Object.entries(c.b || {}).map(([k, v]) => [k, { attack:v[0], defence:v[1] }])),
          points_deductions: c.d || {},
          custom_scores: c.c || {},
        },
      };
    },

    /** A link to the What-If view carrying this scenario. */
    scenarioUrl: function(scenario){
      const base = location.origin + location.pathname.replace(/\/[^/]*$/, "/");
      const path = location.protocol === "file:" ? location.href.split("#")[0] : base.replace(/\/$/, "") + "/whatif";
      return path + "#s=" + NT90_SHARE.encode(scenario);
    },

    /** A link to the Duel view for these two clubs — a real URL, not a fragment. */
    duelUrl: function(home, away){
      const base = location.origin + location.pathname.replace(/\/[^/]*$/, "/");
      const path = location.protocol === "file:" ? location.href.split("?")[0] : base.replace(/\/$/, "") + "/duel";
      return path + "?h=" + encodeURIComponent(home) + "&a=" + encodeURIComponent(away);
    },

    /** Clubs named in a duel link, if this page has one. */
    duelFromLocation: function(){
      const m = location.search.match(/[?&]h=([A-Za-z]{2,4})&a=([A-Za-z]{2,4})/);
      return m ? { home: m[1].toUpperCase(), away: m[2].toUpperCase() } : null;
    },

    /** Copy, the native way where there is one. Resolves to a status string for the toast. */
    copy: function(text){
      return new Promise((resolve) => {
        const fallback = () => {
          try{
            const ta = document.createElement("textarea");
            ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.top = "-1000px";
            document.body.appendChild(ta); ta.select();
            const ok = document.execCommand("copy");
            ta.remove();
            resolve(ok ? "copied" : "manual");
          }catch(e){ resolve("manual"); }
        };
        if(navigator.clipboard && navigator.clipboard.writeText){
          navigator.clipboard.writeText(text).then(() => resolve("copied")).catch(fallback);
        } else fallback();
      });
    },

    /* ── P6.4 the downloadable card ─────────────────────────────────────────────────────────── */
    card: {
      W: CARD_W, H: CARD_H,

      /** Draw a card: {kicker, title, subtitle, rows:[{label,value,frac,color}], accent, footer}. */
      draw: function(canvas, spec){
        const dpr = 1;                                   // the canvas is already 1200×630
        canvas.width = CARD_W * dpr; canvas.height = CARD_H * dpr;
        const c = canvas.getContext("2d");
        const INK = "#0B0F1A", PANEL = "#12182A", TEXT = "#ECF1FB", DIM = "#8E9BB8", FAINT = "#2A334D";
        const accent = spec.accent || "#6CABDD";

        c.fillStyle = INK; c.fillRect(0, 0, CARD_W, CARD_H);
        const grad = c.createLinearGradient(0, 0, 0, CARD_H);
        grad.addColorStop(0, PANEL); grad.addColorStop(1, INK);
        c.fillStyle = grad; c.fillRect(0, 0, CARD_W, CARD_H);
        c.fillStyle = accent; c.fillRect(0, 0, 14, CARD_H);
        c.fillStyle = "#22D3EE"; c.fillRect(14, 0, 4, CARD_H);

        const mono = (size, weight) => (weight || 800) + " " + size + "px ui-monospace,SFMono-Regular,Menlo,monospace";
        c.textBaseline = "top";
        c.font = mono(34); c.fillStyle = TEXT; c.fillText("NINETY+", 64, 48);
        c.font = mono(24);
        c.fillStyle = "#22D3EE";
        c.fillText((spec.kicker || "PREMIER LEAGUE 2026-27").toUpperCase(), 64 + c.measureText("NINETY+ ").width + 20, 56);

        c.fillStyle = FAINT; c.fillRect(64, 128, CARD_W - 128, 2);
        c.fillStyle = FAINT; c.fillRect(64, CARD_H - 96, CARD_W - 128, 2);

        c.fillStyle = TEXT; c.font = mono(72);
        let title = (spec.title || "").toUpperCase();
        while(c.measureText(title).width > CARD_W - 128 && title.length > 4){
          title = title.slice(0, -1);
        }
        c.fillText(title, 64, 172);

        c.font = mono(26); c.fillStyle = DIM;
        c.fillText((spec.subtitle || "").toUpperCase(), 64, 262);

        let y = 340;
        (spec.rows || []).forEach(row => {
          c.font = mono(24); c.fillStyle = DIM;
          c.fillText((row.label || "").toUpperCase(), 64, y);
          c.font = mono(30); c.fillStyle = TEXT;
          const vw = c.measureText(String(row.value)).width;
          c.fillText(String(row.value), CARD_W - 64 - vw, y - 4);
          c.fillStyle = FAINT; c.fillRect(64, y + 34, CARD_W - 128, 8);
          c.fillStyle = row.color || accent;
          c.fillRect(64, y + 34, Math.max(0, Math.min(1, row.frac || 0)) * (CARD_W - 128), 8);
          y += 74;
        });

        c.font = mono(20); c.fillStyle = DIM;
        let footer = (spec.footer || "NINETY+ · NOT AFFILIATED WITH THE PREMIER LEAGUE").toUpperCase();
        while(c.measureText(footer).width > CARD_W - 128 && footer.length > 8){
          footer = footer.slice(0, -4);
        }
        c.fillText(footer, 64, CARD_H - 68);
        return canvas;
      },

      /** Offer the canvas as a file: download on desktop, share sheet on mobile. */
      save: function(canvas, filename){
        return new Promise((resolve) => {
          if(!canvas.toBlob) return resolve("unsupported");
          canvas.toBlob((blob) => {
            if(!blob) return resolve("unsupported");
            const file = new File([blob], filename, { type:"image/png" });
            if(navigator.canShare && navigator.canShare({ files:[file] })){
              navigator.share({ files:[file], title:"NINETY+", text:"Premier League 2026-27 projection" })
                .then(() => resolve("shared")).catch(() => download(blob, filename) && resolve("downloaded"));
              return;
            }
            download(blob, filename);
            resolve("downloaded");
          }, "image/png");
        });
      }
    }
  };

  function download(blob, filename){
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  /* ── wiring: buttons, duel links, and the cards they produce ─────────────────────────────────── */

  function teamOf(code){
    return ((typeof DATA !== "undefined" && DATA.teams) || []).find(t => t.code === code) || {};
  }

  function duelCard(){
    const home = ($("fxHome") || {}).value, away = ($("fxAway") || {}).value;
    const h = teamOf(home), a = teamOf(away);
    if(!home || !away){
      toast("Pick two clubs first.");
      return null;
    }
    const result = (typeof LAST_FIXTURE !== "undefined") ? LAST_FIXTURE : null;
    const rows = [];
    if(result && result.prob_home !== undefined){
      rows.push({ label:h.short + " win", value:Math.round(result.prob_home) + "%",
                  frac:result.prob_home / 100, color:h.color });
      rows.push({ label:"Draw", value:Math.round(result.prob_draw) + "%",
                  frac:result.prob_draw / 100, color:"#8E9BB8" });
      rows.push({ label:(a.short || away) + " win", value:Math.round(result.prob_away) + "%",
                  frac:result.prob_away / 100, color:a.color });
    } else {
      rows.push({ label:"Title probability", value:Math.round(h.title_prob || 0) + "%",
                  frac:(h.title_prob || 0) / 100, color:h.color });
      rows.push({ label:"Top four", value:Math.round(h.top4_prob || 0) + "%",
                  frac:(h.top4_prob || 0) / 100, color:"#7C6CF0" });
      rows.push({ label:"Relegation", value:Math.round(h.relegation_prob || 0) + "%",
                  frac:(h.relegation_prob || 0) / 100, color:"#E54B9A" });
    }
    return NT90_SHARE.card.draw($("cardCanvas"), {
      kicker:"head to head",
      title:(h.short || home) + " v " + (a.short || away),
      subtitle:result && result.lambda_home !== undefined
        ? "expected goals " + result.lambda_home + " - " + result.lambda_away
        : "2026-27 projection",
      rows:rows,
      accent:h.color || "#6CABDD",
      footer:"NINETY+ · 5,000 SIMULATED SEASONS · NOT AFFILIATED WITH THE PREMIER LEAGUE",
    });
  }

  function scenCard(){
    const active = (typeof SCENARIO_ACTIVE === "function") && SCENARIO_ACTIVE();
    const s = (typeof SCENARIO !== "undefined") ? SCENARIO : {};
    const rows = [];
    Object.entries(s.player_injuries || {}).forEach(([k, v]) => { if(v > 0) rows.push({ label:k + " out", value:v + " games", frac:Math.min(1, v / 12), color:"#E54B9A" }); });
    Object.entries(s.team_boosts || {}).forEach(([k, v]) => {
      const any = (v.attack || 0) || (v.defence || 0);
      if(any) rows.push({ label:k + " form", value:((v.attack || 0) >= 0 ? "+" : "") + (v.attack || 0) + "% att",
                         frac:Math.abs(v.attack || 0) / 25, color:"#22D3EE" });
    });
    Object.entries(s.points_deductions || {}).forEach(([k, v]) => { if(v > 0) rows.push({ label:k + " deduction", value:"-" + v + " pts", frac:v / 30, color:"#F0B429" }); });
    if(!rows.length) rows.push({ label:"baseline", value:"no changes", frac:1, color:"#22D3EE" });
    const ranked = (typeof LAST_SIM !== "undefined" && LAST_SIM && LAST_SIM.table_projections) || [];
    const top = ranked[0] || {};
    return NT90_SHARE.card.draw($("cardCanvas"), {
      kicker:"what-if scenario",
      title:top.code ? (top.short || top.code) + " win it" : "What-If",
      subtitle:active ? "scenario applied · 5,000 simulated seasons" : "baseline · 5,000 simulated seasons",
      rows:rows.slice(0, 4),
      accent:(teamOf(top.code || "").color) || "#22D3EE",
      footer:"NINETY+ · WHAT-IF · NOT AFFILIATED WITH THE PREMIER LEAGUE",
    });
  }

  function wire(){
    // `$`, `toast` and the scenario state all come from the modules compiled ahead of this one. If
    // they are not here — this file loaded on its own, as the tests do — there is nothing to wire,
    // and throwing would take the whole page down with it. The payload API above still works.
    if(typeof $ !== "function" || typeof toast !== "function"){
      return;
    }
    const sd = $("shareDuel"), ss = $("shareScen"), cd = $("cardDuel"), cs = $("cardScen");
    if(sd) sd.onclick = () => {
      const home = ($("fxHome") || {}).value, away = ($("fxAway") || {}).value;
      if(!home || !away) return toast("Pick two clubs first.");
      NT90_SHARE.copy(NT90_SHARE.duelUrl(home, away)).then(how => {
        toast(how === "copied" ? "Link copied — it opens this exact duel." : "Copy this link: " + NT90_SHARE.duelUrl(home, away), how === "copied" ? 3600 : 9000);
      });
      if(typeof moment === "function") moment(sd);
    };
    if(ss) ss.onclick = () => {
      if(typeof SCENARIO_ACTIVE === "function" && !SCENARIO_ACTIVE()) return toast("Nothing to share yet — set an injury, form swing or deduction first.");
      const url = NT90_SHARE.scenarioUrl((typeof SCENARIO !== "undefined") ? SCENARIO : {});
      NT90_SHARE.copy(url).then(how => toast(how === "copied" ? "Link copied — it reopens this exact scenario." : "Copy this link: " + url, how === "copied" ? 3600 : 9000));
      if(typeof moment === "function") moment(ss);
    };
    if(cd) cd.onclick = () => {
      const canvas = duelCard();
      if(canvas) NT90_SHARE.card.save(canvas, "ninety-plus-duel.png").then(how =>
        toast(how === "shared" ? "Card shared." : how === "downloaded" ? "Card downloaded — 1200×630 PNG." : "This browser cannot export images."));
    };
    if(cs) cs.onclick = () => {
      const canvas = scenCard();
      if(canvas) NT90_SHARE.card.save(canvas, "ninety-plus-scenario.png").then(how =>
        toast(how === "shared" ? "Card shared." : how === "downloaded" ? "Card downloaded — 1200×630 PNG." : "This browser cannot export images."));
    };

    /* A duel link opens the duel it names (P6.2) */
    const duel = NT90_SHARE.duelFromLocation();
    if(duel && $("fxHome") && $("fxAway")){
      $("fxHome").value = duel.home;
      $("fxAway").value = duel.away;
      if(typeof switchTab === "function") switchTab("duel");
      if(typeof predictFixture === "function") predictFixture();
      toast("Opened the " + duel.home + " v " + duel.away + " duel.", 4200);
    }

    /* Fixture cards already open the duel when clicked (render.js), and the router turns that into a
       /duel URL — so a fixture you are looking at is a link you can carry away without a second
       code path here. What this adds is the address bar catching up: pressing "Share duel" then
       copies a URL that names both clubs. */
  }

  window.NT90_SHARE = NT90_SHARE;
  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
  else wire();
})();
