/* ═══════════════════════════════════════════════════════════════════════════
   UX — the interaction layer.

   Everything here is additive: it enhances the app when a pointer and a GPU are
   available, and stays completely out of the way when they are not. Every effect
   checks `prefers-reduced-motion` and pointer type before doing anything.
   ═══════════════════════════════════════════════════════════════════════════ */

const UX = (() => {
  const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const FINE = window.matchMedia("(pointer: fine)").matches;
  const canAnimate = () => !REDUCED && FINE;

  /* late-rendered content re-registers through these, so the returned object is stable */
  let _refresh = () => {};
  let _refreshTilt = () => {};

  /* ── 1. pointer glow: a soft light that trails the cursor ── */
  function initPointerGlow(){
    if(!canAnimate()) return;
    const el = $("ptr"); if(!el) return;
    let tx = innerWidth / 2, ty = innerHeight / 2, x = tx, y = ty, raf = null, idle = null;

    const tick = () => {
      x += (tx - x) * 0.12; y += (ty - y) * 0.12;
      el.style.transform = `translate3d(${x - 260}px, ${y - 260}px, 0)`;
      raf = (Math.abs(tx - x) > .5 || Math.abs(ty - y) > .5) ? requestAnimationFrame(tick) : null;
    };
    window.addEventListener("pointermove", (e) => {
      tx = e.clientX; ty = e.clientY;
      if(!el.classList.contains("on")) el.classList.add("on");
      clearTimeout(idle);
      idle = setTimeout(() => el.classList.remove("on"), 2600);
      if(!raf) raf = requestAnimationFrame(tick);
    }, { passive:true });
    window.addEventListener("pointerdown", () => el.classList.add("on"));
  }

  /* ── 2. card spotlight: local light under the pointer ── */
  function initSpotlight(){
    if(!canAnimate()) return;
    const TARGETS = ".fx, .tile, .panel, .prow, .racebar";
    document.addEventListener("pointermove", (e) => {
      const host = e.target.closest ? e.target.closest(TARGETS) : null;
      if(!host) return;
      const r = host.getBoundingClientRect();
      host.style.setProperty("--mx", ((e.clientX - r.left) / r.width * 100).toFixed(2) + "%");
      host.style.setProperty("--my", ((e.clientY - r.top) / r.height * 100).toFixed(2) + "%");
    }, { passive:true });
    // every panel gets the spotlight layer
    const add = (root) => (root || document).querySelectorAll(TARGETS).forEach(el => {
      if(el.querySelector(":scope > .spot")) return;
      const s = document.createElement("div"); s.className = "spot"; el.prepend(s);
    });
    add(document);
    _refresh = () => add(document);
  }

  /* ── 3. tilt: cards lean toward the pointer ── */
  function initTilt(){
    if(!canAnimate()) return;
    const MAX = 3.4;
    const bind = () => document.querySelectorAll(".fx, .tile").forEach(el => {
      if(el._tilt) return; el._tilt = 1;
      el.classList.add("tiltable");
      el.addEventListener("pointermove", (ev) => {
        const r = el.getBoundingClientRect();
        const px = (ev.clientX - r.left) / r.width - .5;
        const py = (ev.clientY - r.top) / r.height - .5;
        el.classList.add("tilting");
        el.style.setProperty("--rx", (-py * MAX).toFixed(2) + "deg");
        el.style.setProperty("--ry", (px * MAX).toFixed(2) + "deg");
        el.style.setProperty("--ty", "-3px");
      }, { passive:true });
      const reset = () => {
        el.classList.remove("tilting");
        el.style.setProperty("--rx", "0deg"); el.style.setProperty("--ry", "0deg");
        el.style.setProperty("--ty", "0px");
      };
      el.addEventListener("pointerleave", reset);
      el.addEventListener("blur", reset);
    });
    bind();
    _refreshTilt = bind;
  }

  /* ── 4. magnetic buttons + click ripple ── */
  function initMagnetic(){
    document.querySelectorAll(".btn, .preset, .hstat, .mkt").forEach(el => {
      if(el._mag) return; el._mag = 1;
      if(canAnimate()){
        el.addEventListener("pointermove", (ev) => {
          const r = el.getBoundingClientRect();
          const dx = (ev.clientX - r.left) / r.width - .5;
          const dy = (ev.clientY - r.top) / r.height - .5;
          el.style.transform = `translate(${(dx * 5).toFixed(2)}px, ${(dy * 4).toFixed(2)}px)`;
          el.style.transition = "transform .1s linear";
        }, { passive:true });
        el.addEventListener("pointerleave", () => {
          el.style.transition = "transform .34s cubic-bezier(.34,1.4,.5,1)";
          el.style.transform = "";
        });
      }
      el.addEventListener("pointerdown", (ev) => {
        if(REDUCED) return;
        const r = el.getBoundingClientRect();
        const size = Math.max(r.width, r.height) * 2.2;
        const rip = document.createElement("span");
        rip.className = "ripple";
        rip.style.cssText = `width:${size}px;height:${size}px;left:${ev.clientX - r.left}px;top:${ev.clientY - r.top}px`;
        el.appendChild(rip);
        setTimeout(() => rip.remove(), 620);
      });
    });
  }

  /* ── 5. scroll: progress bar, header compaction, parallax ── */
  function initScrollFx(){
    const bar = $("progress"), header = document.querySelector("header.top");
    const glows = [...document.querySelectorAll(".ambient .glow")];
    let queued = false;
    const apply = () => {
      queued = false;
      const y = window.scrollY || 0;
      const max = Math.max(1, document.body.scrollHeight - innerHeight);
      if(bar) bar.style.width = Math.min(100, y / max * 100) + "%";
      if(header) header.classList.toggle("compact", y > 90);
      if(!REDUCED && FINE){
        glows.forEach((g, i) => {
          const rate = [0.06, -0.045, 0.03][i] || 0.04;
          g.style.transform = `translate3d(0, ${(y * rate).toFixed(1)}px, 0)`;
        });
        const hero = document.querySelector(".hero");
        if(hero && y < 700) hero.style.transform = `translate3d(0, ${(y * 0.055).toFixed(1)}px, 0)`;
      }
    };
    const onScroll = () => { if(!queued){ queued = true; requestAnimationFrame(apply); } };
    window.addEventListener("scroll", onScroll, { passive:true });
    window.addEventListener("resize", onScroll);
    apply();
  }

  /* ── 6. keyboard shortcuts ── */
  const SHORTCUTS = [
    ["1 – 6", "Jump between views (Matchweek → Model)"],
    ["D", "Duel: focus the club pickers"],
    ["W", "What-If: open the scenario desk"],
    ["P", "Cycle the award board (Golden Boot → POTS)"],
    ["S", "Copy a shareable link to the current scenario"],
    ["R", "Reset the scenario to baseline"],
    ["Esc", "Close this panel"],
    ["?", "Show this panel"]
  ];
  function typingInField(el){
    if(!el) return false;
    const t = (el.tagName || "").toLowerCase();
    return t === "input" || t === "select" || t === "textarea" || el.isContentEditable;
  }
  function toggleSheet(force){
    const s = $("sheet"); if(!s) return;
    const on = force === undefined ? !s.classList.contains("on") : force;
    s.classList.toggle("on", on);
    if(on){ const b = s.querySelector("button"); if(b) b.focus(); }
  }
  function initShortcuts(){
    const s = $("sheet");
    if(s){
      s.innerHTML = `<div class="card" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts">
        <span class="kick">Keyboard</span>
        <h3>Shortcuts</h3>
        <div class="small dim" style="margin-bottom:12px">Everything here is also reachable by mouse — these are just faster.</div>
        ${SHORTCUTS.map(([k, d]) => `<div class="rowk"><kbd>${k}</kbd><span>${d}</span></div>`).join("")}
        <div class="row" style="margin-top:16px; justify-content:flex-end">
          <button class="btn pri" id="sheetClose">Got it</button>
        </div>
      </div>`;
      s.addEventListener("click", (e) => { if(e.target === s) toggleSheet(false); });
      const c = $("sheetClose"); if(c) c.onclick = () => toggleSheet(false);
    }
    document.addEventListener("keydown", (e) => {
      if(typingInField(e.target)) return;
      const k = e.key;
      if(k === "Escape"){ toggleSheet(false); return; }
      if(k === "?"){ e.preventDefault(); toggleSheet(); return; }
      const tabs = ["matchweek", "table", "awards", "duel", "whatif", "model"];
      if(/^[1-6]$/.test(k)){ switchTab(tabs[+k - 1]); return; }
      if(k === "d" || k === "D"){ switchTab("duel"); setTimeout(() => { const h = $("fxHome"); if(h) h.focus(); }, 320); return; }
      if(k === "w" || k === "W"){ switchTab("whatif"); return; }
      if(k === "p" || k === "P"){
        const order = ["gb", "pm", "gg", "poty"];
        AWARD = order[(order.indexOf(AWARD) + 1) % order.length];
        switchTab("awards"); renderAwards(); animate($("tab-awards")); toast("Award board: " + AWARD.toUpperCase());
        return;
      }
      if(k === "s" || k === "S"){ shareScenario(); return; }
      if(k === "r" || k === "R"){ resetScenario(); return; }
    });
  }

  /* ── 7. shareable scenario links (#s=<base64>) — an early slice of Phase 6 ── */
  function encodeScenario(){
    const compact = { i:{}, b:{}, d:{}, c:{} };
    Object.entries(SCENARIO.player_injuries).forEach(([k, v]) => { if(v > 0) compact.i[k] = v; });
    Object.entries(SCENARIO.team_boosts).forEach(([k, v]) => {
      if((v.attack || 0) || (v.defence || 0)) compact.b[k] = [v.attack || 0, v.defence || 0];
    });
    Object.entries(SCENARIO.points_deductions).forEach(([k, v]) => { if(v > 0) compact.d[k] = v; });
    Object.entries(SCENARIO.custom_scores).forEach(([k, v]) => { compact.c[k] = v; });
    if(SCENARIO.player_effects && Object.keys(SCENARIO.player_effects).length) compact.e=SCENARIO.player_effects;
    return (compact.e ? "v2-" : "")+btoa(unescape(encodeURIComponent(JSON.stringify(compact)))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  /* A scenario encoded by either writer this page has ever had, or by a link someone else made.
   *
   * There are two writers, which is one too many, and they disagree: ux.js's shareScenario() emitted
   * a bare base64 body, and share.js's SCENARIO_URL emits "v2-<base64>" with a version prefix. Both
   * wire the same button, and share.js — loaded later — wins, so the link a reader actually copies
   * carries the prefix. This reader used to understand only the bare form, which meant **every shared
   * scenario link the button produced failed to open**, with a toast blaming the link.
   *
   * So: accept an optional version prefix, understand both the compact body (i/b/d/c) and the
   * canonical one, and reject a version from the future rather than guessing at it. Everything is
   * sanitised on the way out, whatever the shape.
   */
  function decodeScenario(token){
    let body = String(token || ""), version = 1;
    if(body.length>48000)throw new Error("scenario link is too large");
    const prefixed = body.match(/^v(\d+)-(.*)$/);
    if(prefixed){
      version = parseInt(prefixed[1], 10);
      body = prefixed[2];
      if(version > 2) throw new Error("this link was made by a newer version of NINETY+");
    }
    const b64 = body.replace(/-/g, "+").replace(/_/g, "/");
    const padded = b64 + "=".repeat((4 - b64.length % 4) % 4);
    const c = JSON.parse(decodeURIComponent(escape(atob(padded))));
    // Compact keys from a link, canonical keys from a saved payload — accept either.
    return sanitizeScenario({
      player_injuries: c.player_injuries || c.i,
      team_boosts: c.team_boosts || c.b,
      points_deductions: c.points_deductions || c.d,
      custom_scores: c.custom_scores || c.c,
      player_effects: version >= 2 ? (c.player_effects || c.e) : undefined,
    });
  }
  function applyScenarioFromHash(){
    const m = location.hash.match(/s=([A-Za-z0-9\-_]+)/);
    if(!m) return false;
    try{
      const loaded = decodeScenario(m[1]);
      SCENARIO = { player_injuries:{}, team_boosts:{}, points_deductions:{}, custom_scores:{}, ...loaded };
      renderScenarioForm();
      const n = markScenario();
      switchTab("whatif");
      toast(`Loaded a shared scenario with ${n} change${n === 1 ? "" : "s"} — press Re-simulate to run it.`, 5200);
      return true;
    }catch(e){ toast("That shared link could not be read — showing the baseline instead."); return false; }
  }
  function shareScenario(){
    if(!SCENARIO_ACTIVE()){ toast("Nothing to share yet — set an injury, form swing or deduction first."); return; }
    const url = location.origin === "null"
      ? location.href.split("#")[0] + "#s=" + encodeScenario()
      : location.origin + location.pathname + "#s=" + encodeScenario();
    const done = () => toast("Link copied — it reopens this exact scenario.", 3600);
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(url).then(done).catch(() => toast(url, 8000));
    } else {
      const ta = document.createElement("textarea");
      ta.value = url; document.body.appendChild(ta); ta.select();
      try{ document.execCommand("copy"); done(); }catch(e){ toast(url, 8000); }
      ta.remove();
    }
    // fire the moment animation on the button that asked for it
    moment($("shareScen"));
  }

  /* ── 8. one-click scenario presets ── */
  const PRESETS = [
    { id:"haaland", em:"🚑", label:"Haaland out 8 weeks", apply:() => ({ player_injuries:{ haaland:8 } }) },
    { id:"city",    em:"📉", label:"Man City −10 points",  apply:() => ({ points_deductions:{ MCI:10 } }) },
    { id:"arsenal", em:"🔥", label:"Arsenal +12% form",    apply:() => ({ team_boosts:{ ARS:{ attack:12, defence:6 } } }) },
    { id:"cov",     em:"✨", label:"Coventry escape (+20%)", apply:() => ({ team_boosts:{ COV:{ attack:20, defence:20 } } }) },
    { id:"crisis",  em:"💥", label:"Title-race chaos",     apply:() => ({ player_injuries:{ haaland:10, saka:8, isak:6 }, points_deductions:{ MCI:10 }, team_boosts:{ ARS:{ attack:8, defence:4 } } }) }
  ];
  function applyPreset(id){
    const p = PRESETS.find(x => x.id === id); if(!p) return;
    SCENARIO = { player_injuries:{}, team_boosts:{}, points_deductions:{}, custom_scores:{} };
    const patch = p.apply();
    Object.assign(SCENARIO, patch);
    renderScenarioForm();
    document.querySelectorAll(".preset").forEach(el => el.classList.toggle("on", el.dataset.preset === id));
    const n = markScenario();
    toast(`${p.label} applied — simulating…`, 2600);
    moment(document.querySelector(`.preset[data-preset="${id}"]`));
    // auto-run so the effect lands immediately: the point of a preset is instant feedback
    if($("simCount")) $("simCount").value = "2500";
    setTimeout(() => runSim(), 260);
  }
  function initPresets(){
    const host = $("presets"); if(!host) return;
    host.innerHTML = `<span class="kick" style="align-self:center; margin-right:2px">Try it</span>` +
      PRESETS.map(p => `<button class="preset" data-preset="${p.id}" data-tip="${p.label}">` +
        `<span class="em">${p.em}</span>${p.label}</button>`).join("");
    host.querySelectorAll(".preset").forEach(b => b.onclick = () => applyPreset(b.dataset.preset));
  }

  /* ── 9. compare two clubs straight from the table ── */
  let comparePick = [];
  function initCompare(){
    document.addEventListener("click", (e) => {
      const bar = $("compareBar");
      if(e.target && e.target.id && /^resetScen/.test(e.target.id))
        document.querySelectorAll(".preset.on").forEach(el => el.classList.remove("on"));
      const row = e.target.closest ? e.target.closest("#fullTable tbody tr") : null;
      if(!row || !bar) return;
      const code = row.dataset.code; if(!code) return;
      if(comparePick.includes(code)) comparePick = comparePick.filter(c => c !== code);
      else { comparePick.push(code); if(comparePick.length > 2) comparePick = comparePick.slice(-2); }
      document.querySelectorAll("#fullTable tbody tr").forEach(r =>
        r.classList.toggle("pick", comparePick.includes(r.dataset.code)));
      paintCompare();
    });
  }
  function paintCompare(){
    const bar = $("compareBar"); if(!bar) return;
    if(comparePick.length === 0){ bar.style.display = "none"; return; }
    bar.style.display = "flex";
    const [a, b] = comparePick;
    bar.innerHTML = `
      <span class="kick">Compare mode</span>
      ${a ? `<span class="mkt">${crest(a, 16)} <b>${esc(TEAM_LABEL[a])}</b></span>` : `<span class="mkt dim">pick a home side</span>`}
      <span class="dim">v</span>
      ${b ? `<span class="mkt">${crest(b, 16)} <b>${esc(TEAM_LABEL[b])}</b></span>` : `<span class="mkt dim">pick an away side</span>`}
      <button class="btn pri sm" id="compareGo" ${a && b ? "" : "disabled"}>Open the duel →</button>
      <button class="btn sm" id="compareClear">Clear</button>`;
    const go = $("compareGo"); if(go) go.onclick = () => {
      $("fxHome").value = a; $("fxAway").value = b; switchTab("duel");
    };
    const cl = $("compareClear"); if(cl) cl.onclick = () => {
      comparePick = [];
      document.querySelectorAll("#fullTable tbody tr.pick").forEach(r => r.classList.remove("pick"));
      paintCompare();
    };
  }

  /* ── 10. the verdict moment: pulse when a scenario flips the title ── */
  function celebrateFlip(champion, baselineChampion){
    if(REDUCED) return;
    if(champion && baselineChampion && champion !== baselineChampion){
      const el = $("simSummary");
      if(el){ el.classList.remove("flip"); void el.offsetWidth; el.classList.add("flip"); }
      moment($("scenTable"));
      toast(`${TEAM_LABEL[champion]} take the title in this scenario.`, 4200);
    }
  }

  function init(){
    initPointerGlow(); initSpotlight(); initTilt(); initMagnetic();
    initScrollFx(); initShortcuts(); initPresets(); initCompare();
    const kb = $("kbdBtn"); if(kb) kb.onclick = () => toggleSheet(true);
    const sh = $("shareScen"); if(sh) sh.onclick = () => shareScenario();
    applyScenarioFromHash();
    // late-rendered content (dashboards re-render on tab change) picks up the new interactions
    _refreshTilt();
    _refresh();
  }

  return { init, refresh: () => _refresh(), refreshTilt: () => _refreshTilt(),
           applyPreset, shareScenario, toggleSheet, celebrateFlip };
})();
