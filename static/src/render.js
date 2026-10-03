/* ═══════════════════════════════════════════════════════════════════════════
   RENDER — every view, rebuilt as broadcast-grade components
   ═══════════════════════════════════════════════════════════════════════════ */

const M = DATA.ml_metrics;
const FEATS = M.feature_importance || [];
const BT = BACKTEST;

/* ── the payload's own sense of time ─────────────────────────────────────────
   Nothing here may be hardcoded to a matchweek: after the weekly job promotes a gameweek, these
   labels have to move by themselves (P2.5). */
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
                     "August", "September", "October", "November", "December"];
function shortDates(text){
  let out = String(text || "").trim();
  MONTH_NAMES.forEach(m => { out = out.replace(m, m.slice(0, 3)); });
  return out.replace(/\s*\d{4}\s*$/, "").trim();
}
const NEXT_GW = (DATA.meta && DATA.meta.next_gw) || 6;
const NEXT_GW_DATES = ((DATA.meta && DATA.meta.next_matchweek) || {}).dates || "";
const AS_OF = (DATA.meta && DATA.meta.as_of_date) || "";
function nextGwChip(){ return `Matchweek ${NEXT_GW}${NEXT_GW_DATES ? " · " + shortDates(NEXT_GW_DATES) : ""}`; }

/* ── small shared components ─────────────────────────────────────────────── */
function ring(pctVal, { size = 96, stroke = 7, color = "var(--pitch)", label = "", sub = "", id = "" } = {}){
  const r = (size - stroke) / 2, C = 2 * Math.PI * r;
  return `<div class="ring" style="width:${size}px;height:${size}px">
    <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" data-ring="${pctVal}">
      <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="${stroke}"/>
      <circle class="arc" cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="${color}" stroke-width="${stroke}"
        stroke-linecap="round" style="filter:drop-shadow(0 0 6px ${color === "var(--pitch)" ? "rgba(0,224,138,.55)" : "rgba(255,45,120,.5)"})"/>
    </svg>
    <div class="lab" style="width:${size * .8}px">
      <b class="num" data-count="${pctVal}" data-dec="${pctVal < 10 ? 1 : (Number.isInteger(pctVal) ? 0 : 1)}" data-suf="%"
         style="font-size:${size * (pctVal >= 100 ? .2 : .23)}px">0%</b>
      ${sub ? `<span class="small dim" style="font-family:var(--f-disp);font-weight:700;letter-spacing:.1em;text-transform:uppercase;font-size:8.5px">${sub}</span>` : ""}
    </div>
  </div>`;
}
function miniCrestChip(code, name){
  return `<span style="display:inline-flex;align-items:center;gap:7px;min-width:0">
    ${crest(code, 15)}<span style="font-family:var(--f-disp);font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(name)}</span></span>`;
}

/* ═══════════ HEADER ═══════════ */
function renderHeader(){
  const meta = DATA.meta;
  const champ = DATA.headline_predictions.champion;
  $("hstats").innerHTML = `
    <span class="hstat"><span class="dot"></span> ${nextGwChip()}</span>
    <span class="hstat sims">Sims <b>${(meta.n_simulations || 5000).toLocaleString()}</b></span>
    <span class="hstat mode" id="modeChip"><span class="dot"></span> live engine</span>
    <span class="hstat good">Title <b>${esc(champ.short)}</b> ${pct(champ.title_prob)}</span>
    <button class="btn sm resets" id="resetScenTop" style="align-self:center">Reset to baseline</button>
    <button class="btn sm kbdbtn" id="kbdBtn" style="align-self:center" aria-label="Keyboard shortcuts"
      data-tip="Keyboard shortcuts">?</button>`;
  const sub = $("markSub");
  if(sub) sub.textContent = `Premier League 2026–27 · model v2.1${AS_OF ? " · as of " + AS_OF : ""}`;
  const r = $("resetScenTop"); if(r) r.onclick = resetScenario;
  const kb = $("kbdBtn"); if(kb) kb.onclick = () => UX.toggleSheet(true);
  paintMode();
}

/* ═══════════ THE BOARD TICKER ═══════════ */
/* A single marquee of model outputs — the "exchange board" idea, except every number on it is a
   real projection from the payload rather than decoration. Pauses when you point at it. */
function renderTicker(){
  const rail = $("tickerRail"); if(!rail) return;
  const t = DATA.table_projections;
  const acc = BT ? BT.model.accuracy : M.accuracy_1x2;
  const skill = BT ? BT.skill_vs_prior_table.rps : 8.8;
  const bottom = new Set(t.slice(-2).map(r => r.code));
  const items = [];
  const add = (html, cls) => items.push({ html, cls: cls || "" });

  t.slice(0, 4).forEach(r => add(
    `${crest(r.code, 15)}<span class="v">${esc(r.short)}</span><b>${num1(r.title_prob)}%</b><span class="dim">title</span>`));
  (DATA.golden_boot_race || []).slice(0, 3).forEach(p => add(
    `${crest(p.club, 15)}<span class="v">${esc(p.name)}</span><b>${num1(p.proj_goals)}</b><span class="dim">goals</span>`));
  (DATA.playmaker_race || []).slice(0, 2).forEach(p => add(
    `${crest(p.club, 15)}<span class="v">${esc(p.name)}</span><b>${num1(p.proj_assists)}</b><span class="dim">assists</span>`));
  (DATA.golden_glove_race || []).slice(0, 2).forEach(p => add(
    `${crest(p.club, 15)}<span class="v">${esc(p.name)}</span><b>${num1(p.proj_cs)}</b><span class="dim">clean sheets</span>`));
  t.slice(-3).forEach(r => add(
    `${crest(r.code, 15)}<span class="v">${esc(r.short)}</span><b>${num1(r.relegation_prob)}%</b><span class="dim">down</span>`,
    bottom.has(r.code) ? "down" : ""));
  add(`<span class="v">${esc(t[0].short)} v ${esc(t[1].short)}</span><b>${(t[0].proj_pts - t[1].proj_pts).toFixed(1)}</b><span class="dim">projected pts gap</span>`);
  add(`<span class="v">1X2 hit rate</span><b>${num1(acc)}%</b><span class="dim">2025–26 replay</span>`);
  add(`<span class="v">RPS skill</span><b>+${num1(skill)}%</b><span class="dim">vs prior table</span>`);
  add(`<span class="v">Simulations</span><b>${(DATA.meta.n_simulations || 5000).toLocaleString()}</b><span class="dim">seasons</span>`);

  const set = items.map(i => `<span class="it ${i.cls}">${i.html}</span>`).join("");
  rail.innerHTML = `<div class="set">${set}</div><div class="set" aria-hidden="true">${set}</div>`;
}

/* ═══════════ HERO ═══════════ */
function renderHero(){
  const t = DATA.table_projections;
  const [c1, c2] = t;
  const gap = (c1.proj_pts - c2.proj_pts).toFixed(1);
  const close = +gap < 4;
  $("heroKick").textContent = `Matchweek ${NEXT_GW}${NEXT_GW_DATES ? " · " + NEXT_GW_DATES : ""} · ${DATA.meta.n_simulations.toLocaleString()} simulated seasons`;
  $("heroVerdict").innerHTML = close
    ? `Title race down to <em>${num1(gap)} points</em>`
    : `<span class="nm-hot">${esc(c1.short)}</span> pull clear`;
  const gw = DATA.gw6_predictions || [];
  const headline = gw.slice().sort((a, b) =>
    Math.abs(a.prob_home - a.prob_away) - Math.abs(b.prob_home - b.prob_away))[0];
  const headlineText = headline
    ? `<b>${esc(TEAM_LABEL[headline.home])} v ${esc(TEAM_LABEL[headline.away])}</b> at ${esc((TEAM_BY_CODE[headline.home] || {}).stadium || "home")}`
    : "the tightest fixture of the gameweek";
  $("heroLede").innerHTML = `The model has <b>${esc(c1.name)}</b> on <b>${num1(c1.proj_pts)} pts</b>
    with a <b>${pct(c1.title_prob)}</b> title probability, <b>${esc(c2.name)}</b> breathing down their neck on
    ${num1(c2.proj_pts)} (${pct(c2.title_prob)}). Down the bottom, <b>${esc(t[t.length-1].short)}</b>
    are ${pct(t[t.length-1].relegation_prob)} to go down — and this matchweek's headline is
    ${headlineText}.`;

  $("heroRight").innerHTML = `
    <div style="display:flex; align-items:center; justify-content:center; gap:18px; flex-wrap:wrap">
      <div style="text-align:center">
        ${ring(c1.title_prob, { size:132, stroke:10, sub:esc(c1.short) })}
        <div class="kick" style="margin-top:8px">Title favourite</div>
      </div>
      <div style="text-align:center; opacity:.82">
        ${ring(c2.title_prob, { size:96, stroke:7, color:"var(--magi)", sub:esc(c2.short) })}
        <div class="kick" style="margin-top:8px">Challenger</div>
      </div>
    </div>
    <div class="row" style="justify-content:center; gap:8px; margin-top:16px">
      <span class="chip lean">1X2 hit rate ${M.accuracy_1x2}%</span>
      <span class="chip lean">RPS ${M.rps}</span>
    </div>`;

  $("heroCta").onclick = () => $("gwGrid").scrollIntoView({ behavior:"smooth", block:"center" });
  const big = (DATA.gw6_predictions || []).slice().sort((a, b) =>
    Math.min(Math.abs(a.prob_home - a.prob_away), 100) - Math.min(Math.abs(b.prob_home - b.prob_away), 100))[0];
  $("heroDuel").onclick = () => { if(big){ $("fxHome").value = big.home; $("fxAway").value = big.away; switchTab("duel"); } };
}

/* ═══════════ HEADLINE TILES ═══════════ */
function renderHeadTiles(){
  const h = DATA.headline_predictions, t = DATA.table_projections;
  const tiles = [
    { k:"Projected champion", who:`${crest(h.champion.code, 30)}`, nm:h.champion.short,
      big:num1(h.champion.proj_pts), unit:"pts", right:ring(h.champion.title_prob, { size:74, stroke:6 }),
      foot:`${h.champion.curr_pts} now · ${pct(h.champion.title_prob)} title`, cls:"g" },
    { k:"Golden Boot", who:crest(h.golden_boot.club, 30), nm:h.golden_boot.name,
      big:num1(h.golden_boot.proj_goals), unit:"goals", right:ring(h.golden_boot.golden_boot_prob, { size:74, stroke:6, color:"var(--gold)" }),
      foot:`${h.golden_boot.goals_curr} scored so far · ${pct(h.golden_boot.golden_boot_prob)}`, cls:"y" },
    { k:"Most assists", who:crest(h.playmaker.club, 30), nm:h.playmaker.name,
      big:num1(h.playmaker.proj_assists), unit:"assists", right:ring(h.playmaker.playmaker_prob, { size:74, stroke:6, color:"var(--violet)" }),
      foot:`${h.playmaker.assists_curr} so far · ${pct(h.playmaker.playmaker_prob)}`, cls:"v" },
    { k:"Golden Glove", who:crest(h.golden_glove.club, 30), nm:h.golden_glove.name,
      big:num1(h.golden_glove.proj_cs), unit:"clean sheets", right:ring(h.golden_glove.golden_glove_prob, { size:74, stroke:6, color:"var(--draw)" }),
      foot:`${h.golden_glove.cs_curr} so far · save rate ${h.golden_glove.save_pct}%`, cls:"" },
    { k:"Relegation trapdoor", who:crest(t[t.length-1].code, 30), nm:t[t.length-1].short,
      big:num1(t[t.length-1].relegation_prob), unit:"% to go down", right:ring(t[t.length-1].relegation_prob, { size:74, stroke:6, color:"var(--alert)" }),
      foot:`${num1(t[t.length-1].proj_pts)} projected · ${num1(t[t.length-2].proj_pts)} for ${t[t.length-2].short}`, cls:"m" }
  ];
  $("headTiles").innerHTML = tiles.map((x, i) => `
    <div class="tile ${x.cls} rv" style="--d:${i * 70}ms">
      <div class="k">${x.k}</div>
      <div class="row" style="margin-top:12px; align-items:center; gap:12px">
        <div style="flex:1; min-width:0">
          <div style="display:flex;align-items:center;gap:9px">${x.who}
            <span class="disp" style="font-size:17px; letter-spacing:-.03em">${esc(x.nm)}</span></div>
          <div style="margin-top:9px">
            <span class="disp num" data-count="${x.big}" data-dec="1" style="font-size:34px">0</span>
            <span class="small dim" style="margin-left:6px">${x.unit}</span>
          </div>
        </div>
        ${x.right}
      </div>
      <div class="sub">${x.foot}</div>
    </div>`).join("");
}

/* ═══════════ THE GAMEWEEK GRID ═══════════ */
function fixtureCard(p, i, { compact = false } = {}){
  const tier = tierOf(p);
  const o = outcomeOf(p);
  const hc = p.home, ac = p.away;
  const top = (p.top_scorelines || [])[0] || {};
  const dateLabel = (p.dates || "").replace("-", "–");
  const tossCls = tier.cls === "toss" ? " tossup" : "";
  return `<div class="fx rv${tossCls}" tabindex="0" role="button"
      aria-label="${esc(TEAM_LABEL[hc])} v ${esc(TEAM_LABEL[ac])}: ${pct(p.prob_home)} home, ${pct(p.prob_draw)} draw, ${pct(p.prob_away)} away"
      data-i="${i}" data-home="${hc}" data-away="${ac}"
      data-wh="${p.prob_home}" data-wd="${p.prob_draw}" data-wa="${p.prob_away}"
      style="--hc:${TEAM_COLOR[hc] || "#666"}; --ac:${TEAM_COLOR[ac] || "#666"}; --d:${i * 60}ms">
    <div class="rim"></div>
    <div class="top">
      <span class="when">${esc(dateLabel)}</span>
      <span class="xgtop">xG ${num1(p.lambda_home)}–${num1(p.lambda_away)}</span>
      <span class="chip ${tier.cls}"><b class="mk" aria-hidden="true">${tier.mark}</b>${tier.txt}</span>
    </div>
    <div class="teams">
      <div class="side">${crest(hc, 30)}<div style="min-width:0">
        <span class="nm">${esc(TEAM_LABEL[hc] || hc)}</span>
        <span class="sm">${esc((TEAM_BY_CODE[hc] || {}).manager || "")}</span></div></div>
      <span class="vs">VS</span>
      <div class="side away"><div style="min-width:0">
        <span class="nm">${esc(TEAM_LABEL[ac] || ac)}</span>
        <span class="sm">${esc((TEAM_BY_CODE[ac] || {}).manager || "")}</span></div>${crest(ac, 30)}</div>
    </div>
    <div class="tri" role="img" aria-label="Home win ${pct(p.prob_home)}, draw ${pct(p.prob_draw)}, away win ${pct(p.prob_away)}">
      <i class="h"><b class="sg" aria-hidden="true">H</b><span>${pct(p.prob_home)}</span></i>
      <i class="d"><b class="sg" aria-hidden="true">D</b><span class="lite">${pct(p.prob_draw)}</span></i>
      <i class="a"><b class="sg" aria-hidden="true">A</b><span>${pct(p.prob_away)}</span></i>
    </div>
    <div class="foot">
      <span>model call <b style="color:${o.color}; font-family:var(--f-disp); font-weight:700">${esc(o.label)}</b></span>
      ${top.score ? `<span class="dim">·</span><span class="xl">${top.score} <span class="dim">(${top.prob}%)</span></span>` : ""}
      <span class="go">duel →</span>
    </div>
  </div>`;
}
function renderGW(){
  const fx = DATA.gw6_predictions || [];
  const kick = $("gwKick");
  if(kick) kick.textContent = `Matchweek ${NEXT_GW} — every fixture, model view`;
  $("gwGrid").innerHTML = fx.map((p, i) => fixtureCard(p, i)).join("");
  $("gwGrid").querySelectorAll(".fx").forEach(el => {
    const open = () => {
      $("fxHome").value = el.dataset.home; $("fxAway").value = el.dataset.away;
      switchTab("duel");
    };
    el.onclick = open;
    el.onkeydown = (ev) => { if(ev.key === "Enter" || ev.key === " "){ ev.preventDefault(); open(); } };
  });
  if(fx.length) $("gwLegend").textContent = `${fx.length} fixtures · MW${NEXT_GW}`;
  // The grid was just rewritten, so the marks and the filter have to be reapplied to the new cards.
  renderFollowState();
}

/* ═══════════ RACE + PULSE ═══════════ */
function renderRaceBars(){
  const t = DATA.table_projections.slice(0, 6);
  const max = Math.max(...t.map(x => x.title_prob), 5);
  $("raceBars").innerHTML = t.map((x, i) => `
    <div class="racebar rv" style="--d:${i * 55}ms">
      <div class="who">${crest(x.code, 17)}${esc(x.short)}</div>
      <div class="track"><i data-w="${Math.max(x.title_prob / max * 100, 3.4).toFixed(1)}"
        data-color="${TEAM_COLOR[x.code]}" style="background:linear-gradient(90deg,${TEAM_COLOR[x.code]},color-mix(in srgb,${TEAM_COLOR[x.code]} 40%,#fff))"></i></div>
      <div class="pct" data-count="${x.title_prob}" data-dec="1" data-suf="%">0%</div>
    </div>`).join("");
}
function renderPulse(){
  const acc = BT ? BT.model.accuracy : M.accuracy_1x2;
  const skill = BT ? BT.skill_vs_prior_table.rps : 8.8;
  const rho = BT ? BT.table_level.spearman_rank_correlation : 0.566;
  const hits = (BT && BT.hits) || [];
  const strip = hits.slice(0, 190).map((h, i) =>
    `<i data-hit="${h}" style="--i:${i}; background:${h ? "var(--pitch)" : "rgba(255,255,255,.10)"}; height:${h ? 14 : 6}px"></i>`).join("");
  $("pulse").innerHTML = `
    <div class="grid g2" style="gap:10px">
      <div class="tile g" style="padding:12px 13px">
        <div class="k">Out-of-sample 1X2</div>
        <div class="big" data-count="${acc}" data-dec="1" data-suf="%" style="font-size:26px">0%</div>
      </div>
      <div class="tile g" style="padding:12px 13px">
        <div class="k">Skill vs prior table</div>
        <div class="big" data-count="${skill}" data-dec="1" data-pre="+" data-suf="%" style="font-size:26px">0%</div>
      </div>
    </div>
    <div style="margin-top:14px">
      <div class="kick" style="margin-bottom:8px">Every call in the 2025–26 replay</div>
      <div class="hitstrip">${strip}</div>
      <div class="small dim" style="margin-top:7px">${hits.slice(0,190).filter(Boolean).length} of ${hits.slice(0,190).length} shown correct · tall ticks = the model got it right
        (full replay: ${hits.filter(Boolean).length}/${hits.length}, ${(hits.filter(Boolean).length / (hits.length||1) * 100).toFixed(1)}%)</div>
    </div>
    <div class="small mut" style="margin-top:12px; line-height:1.6">
      Rank correlation <b>${rho}</b> on final positions, calibration checked,
      and every one of those calls made <b>before the season started</b>.
      <a href="#" id="pulseMore" style="color:var(--pitch);text-decoration:none;font-weight:600">See the full replay →</a>
    </div>`;
  const pm = $("pulseMore"); if(pm) pm.onclick = (e) => { e.preventDefault(); switchTab("model"); };
  // the wave: each correct call gets its own beat
  const stripEls = $("pulse").querySelectorAll(".hitstrip i");
  if(!REDUCED) stripEls.forEach((el, i) => {
    el.style.opacity = 0; el.style.transform = "scaleY(.2)";
    el.style.transition = "opacity .3s ease, transform .45s cubic-bezier(.34,1.4,.5,1), box-shadow .5s ease";
    setTimeout(() => {
      el.style.opacity = 1; el.style.transform = "none";
      if(el.dataset.hit === "1") el.style.boxShadow = "0 0 10px rgba(0,224,138,.9)";
      setTimeout(() => { el.style.boxShadow = "none"; }, 320);
    }, 500 + i * 14);
  });
}

/* ═══════════ MARQUEE ═══════════ */
function renderMarquee(){
  const seen = new Set();
  const picks = (DATA.marquee_predictions || []).filter(p => {
    const k = [p.home, p.away].sort().join("-");
    if(seen.has(k)) return false;
    seen.add(k); return true;
  }).slice(0, 3);
  $("marquee").innerHTML = picks.map((p, i) => {
    const o = outcomeOf(p), tier = tierOf(p);
    const scores = (p.top_scorelines || []).slice(0, 3);
    const reasons = [];
    const a = TEAM_BY_CODE[p.home], b = TEAM_BY_CODE[p.away];
    if(a && b){
      const dElo = Math.round(a.elo - b.elo);
      reasons.push(`${Math.abs(dElo) > 25 ? (dElo > 0 ? TEAM_LABEL[p.home] : TEAM_LABEL[p.away]) + " hold a " + Math.abs(dElo) + "-point Elo edge" : "Elo is near level"}`);
      reasons.push(`${(a.xg + b.xg).toFixed(1)} xG/90 between them — ${(a.xg + b.xg) > 3.6 ? "a genuinely open game" : "expect it tight"}`);
      reasons.push(`${p.btts_prob}% both teams score`);
    }
    return `<div class="panel rv" style="--d:${i * 90}ms; cursor:pointer" data-h="${p.home}" data-a="${p.away}">
      <div class="row" style="justify-content:space-between; align-items:center">
        <span class="chip ${tier.cls}">${tier.txt}</span>
        <span class="kick">${esc(TEAM_BY_CODE[p.home] ? TEAM_BY_CODE[p.home].stadium : "")}</span>
      </div>
      <div class="teams" style="display:grid; grid-template-columns:1fr auto 1fr; align-items:center; gap:10px; margin-top:14px">
        <div class="side">${crest(p.home, 34)}<div><span class="nm" style="font-size:18px">${esc(TEAM_LABEL[p.home])}</span>
          <span class="sm">${esc(TEAM_BY_CODE[p.home] ? TEAM_BY_CODE[p.home].form : "")} form</span></div></div>
        <span class="vs">VS</span>
        <div class="side away"><div><span class="nm" style="font-size:18px">${esc(TEAM_LABEL[p.away])}</span>
          <span class="sm">${esc(TEAM_BY_CODE[p.away] ? TEAM_BY_CODE[p.away].form : "")} form</span></div>${crest(p.away, 34)}</div>
      </div>
      <div style="margin-top:16px">
        <div class="row" style="justify-content:space-between; font-size:11px" class="mut">
          <span class="mut">${esc(TEAM_LABEL[p.home])}</span><span class="mut">draw</span><span class="mut">${esc(TEAM_LABEL[p.away])}</span>
        </div>
        <div class="tri" style="height:34px; margin-top:5px" data-wh="${p.prob_home}" data-wd="${p.prob_draw}" data-wa="${p.prob_away}"
             role="img" aria-label="Home win ${pct(p.prob_home)}, draw ${pct(p.prob_draw)}, away win ${pct(p.prob_away)}">
          <i class="h"><b class="sg" aria-hidden="true">H</b><span>${pct(p.prob_home)}</span></i><i class="d"><b class="sg" aria-hidden="true">D</b><span class="lite">${pct(p.prob_draw)}</span></i><i class="a"><b class="sg" aria-hidden="true">A</b><span>${pct(p.prob_away)}</span></i>
        </div>
      </div>
      <div class="row" style="margin-top:13px; gap:7px">${scores.map(s => `<span class="mkt">${s.score} <b>${s.prob}%</b></span>`).join("")}</div>
      <div class="note" style="margin-top:13px; font-size:12px">
        ${reasons.map(r => `<div style="margin:2px 0">· ${r}</div>`).join("")}
      </div>
      <div class="row" style="margin-top:12px; justify-content:space-between">
        <span class="disp" style="font-size:14px">Model call: <b style="color:${o.color}">${esc(o.label)}</b></span>
        <span class="kick">open duel →</span>
      </div>
    </div>`;
  }).join("");
  $("marquee").querySelectorAll("[data-h]").forEach(el => {
    el.onclick = () => { $("fxHome").value = el.dataset.h; $("fxAway").value = el.dataset.a; switchTab("duel"); };
  });
}

/* ═══════════ TABLE ═══════════ */
let TBL_SORT = "pts";
function renderTable(){
  const t = DATA.table_projections;
  const relTotal = t.reduce((a, b) => a + b.relegation_prob, 0) / 3;
  const tiles = [
    { k:"Projected champion", v:t[0].short, n:`${num1(t[0].proj_pts)} pts · ${pct(t[0].title_prob)} for the title`, cls:"g", code:t[0].code },
    { k:"Top four cut", v:`${num1(t[3].proj_pts)} pts`, n:`${t[3].short} hold the last UCL spot — ${pct(t[4].top4_prob)} for ${t[4].short}`, cls:"v", code:t[3].code },
    { k:"Survival line", v:`${num1(t[16].proj_pts)} pts`, n:`${t[16].short} and up are projected safe`, cls:"y", code:t[16].code },
    { k:"Points spread", v:`${(t[0].proj_pts - t[19].proj_pts).toFixed(0)}`, n:`from top to bottom of the projected table`, cls:"m", code:t[19].code }
  ];
  $("tableTiles").innerHTML = tiles.map((x, i) => `<div class="tile ${x.cls} rv" style="--d:${i*70}ms">
    <div class="row" style="justify-content:space-between; align-items:center">
      <div class="k">${x.k}</div>${crest(x.code, 20)}
    </div>
    <div class="big" style="margin-top:10px">${esc(x.v)}</div>
    <div class="sub">${x.n}</div></div>`).join("");

  const rows = TBL_SORT === "pts"
    ? t
    : [...t].sort((a, b) => (b.pts_p90 - b.pts_p10) - (a.pts_p90 - a.pts_p10));

  $("fullTable").innerHTML = `<thead><tr>
      <th scope="col"style="width:34px">#</th><th scope="col">Club</th><th scope="col" class="num">Now</th><th scope="col" class="num">Projected</th>
      <th scope="col" class="num">80% range</th><th scope="col">Finish spread</th><th scope="col" class="num">Title</th><th scope="col" class="num">Top 4</th><th scope="col" class="num">Down</th>
    </tr></thead><tbody>` + rows.map((r, i) => {
    const pos = t.indexOf(r) + 1;
    const spread = r.pts_p90 - r.pts_p10;
    return `<tr class="rv" data-code="${r.code}" style="--d:${Math.min(i * 26, 400)}ms">
      <td><span class="${posClass(pos)}">${pos}</span></td>
      <td>
        <div class="row" style="gap:9px; flex-wrap:nowrap">
          ${crest(r.code, 20)}
          ${starButton(r.code, r.short)}
          <div style="min-width:0">
            <div class="disp" style="font-size:14px; white-space:nowrap">${esc(r.short)}${deltaTag(r.current_pos, pos)}</div>
            <div class="dim" style="font-size:10.5px; white-space:nowrap">${esc(r.manager)}</div>
          </div>
        </div>
      </td>
      <td class="num mut">${r.curr_pts} <span class="dim" style="font-size:10px">(${r.current_pos})</span></td>
      <td class="num"><b class="num" style="font-size:15px" data-count="${r.proj_pts}" data-dec="1">0</b></td>
      <td class="num dim">${r.pts_p10}–${r.pts_p90}</td>
      <td>${ribbon(r.pos_distribution || [])}</td>
      <td class="num" style="color:${r.title_prob > 5 ? "var(--pitch)" : "var(--ink-2)"}">${r.title_prob > 0 ? num1(r.title_prob) + "%" : "—"}</td>
      <td class="num mut">${r.top4_prob > 0.5 ? num1(r.top4_prob) + "%" : "—"}</td>
      <td class="num" style="color:${r.relegation_prob > 8 ? "var(--alert)" : "var(--ink-3)"}">${r.relegation_prob > 3 ? num1(r.relegation_prob) + "%" : "—"}</td>
    </tr>`;
  }).join("") + `</tbody>`;

  $("tableNote").innerHTML = `Points are mean projections over ${DATA.meta.n_simulations.toLocaleString()} simulated seasons;
    the range is the 10th–90th percentile. Finish spread shows where a club can land — green is a title,
    violet a European place, red relegation. <b>${esc(t[0].short)}</b> and <b>${esc(t[1].short)}</b> are separated by
    ${(t[0].proj_pts - t[1].proj_pts).toFixed(1)} points across 33 remaining matchweeks.`;

  const s1 = $("tblSortPts"), s2 = $("tblSortRib");
  const paint = () => { s1.classList.toggle("pri", TBL_SORT === "pts"); s2.classList.toggle("pri", TBL_SORT === "rib"); };
  s1.onclick = () => { TBL_SORT = "pts"; renderTable(); paint(); animate($("tab-table")); };
  s2.onclick = () => { TBL_SORT = "rib"; renderTable(); paint(); animate($("tab-table")); };
  paint();
  wireStars($("fullTable"));
  renderFollowState();
}
function ribbon(dist){
  const N = dist.length || 20;
  const segs = [];
  const bands = [[0, 1, "var(--pitch)"], [1, 4, "var(--pitch-d)"], [4, 7, "var(--draw)"], [7, 17, "rgba(255,255,255,.16)"], [17, N, "var(--alert)"]];
  bands.forEach(([a, b, c]) => {
    const w = dist.slice(a, b).reduce((x, y) => x + y, 0);
    if(w > .15) segs.push(`<i data-w="${Math.max(w, 1.2).toFixed(1)}" style="background:${c}; width:0"></i>`);
  });
  return `<span class="ribbon">${segs.join("")}</span>`;
}
function renderMarkets(){
  const t = DATA.table_projections;
  const top4 = t.slice(0, 6).filter(x => x.top4_prob > 3);
  const rel = [...t].sort((a, b) => b.relegation_prob - a.relegation_prob).slice(0, 5);
  const cont = (x, color, val) => `
    <div style="padding:9px 0; border-bottom:1px dashed rgba(255,255,255,.055)">
      <div class="row" style="justify-content:space-between; align-items:center">
        <span style="display:flex;align-items:center;gap:8px">${crest(x.code, 17)}<b class="disp" style="font-size:13px">${esc(x.short)}</b></span>
        <span class="num" style="color:${color}" data-count="${val}" data-dec="1" data-suf="%">0%</span>
      </div>
      <div class="track" style="margin-top:7px"><i data-w="${Math.min(val, 100)}" style="background:${color}"></i></div>
    </div>`;
  $("marketPanel").innerHTML = `
    <div class="kick" style="margin-bottom:6px">Top-four probability</div>
    ${top4.map(x => cont(x, "var(--draw)", x.top4_prob)).join("")}
    <div class="kick" style="margin:16px 0 6px">Relegation probability</div>
    ${rel.map(x => cont(x, "var(--magi)", x.relegation_prob)).join("")}`;
}
function renderTop6Rings(){
  const t = DATA.table_projections.slice(0, 6);
  $("top6Rings").innerHTML = `
    <div class="grid g3" style="gap:12px">
      ${t.map((x, i) => `<div style="text-align:center" class="rv" style="--d:${i*60}ms">
        ${crest(x.code, 22)}
        <div style="margin-top:6px">${ring(x.top4_prob, { size:78, stroke:6, color:"var(--pitch)" })}</div>
        <div class="disp" style="font-size:12.5px; margin-top:7px">${esc(x.short)}</div>
        <div class="dim" style="font-size:10.5px">${num1(x.proj_pts)} pts</div>
      </div>`).join("")}
    </div>
    <div class="note" style="margin-top:14px">Top four is the model's view of the UCL places.
      ${esc(t[3].short)} sit on the cut line at ${num1(t[3].proj_pts)} projected points.</div>`;
}

/* ═══════════ AWARDS ═══════════ */
const AWARD_DEF = {
  gb:{ kick:"Golden Boot", title:"Goals, projected", list:() => DATA.golden_boot_race, val:p => p.proj_goals,
       sec:p => p.proj_goals_int, prob:p => p.golden_boot_prob, unit:"goals", color:"var(--gold)",
       note:`Projected full-season totals = goals already scored + Monte Carlo goals over expected remaining minutes.
             Every leader's last-season tally is verified where published (<b style="color:var(--pitch)">✓</b>).` },
  pm:{ kick:"Playmaker award", title:"Assists, projected", list:() => DATA.playmaker_race, val:p => p.proj_assists,
       sec:p => p.proj_assists_int, prob:p => p.playmaker_prob, unit:"assists", color:"var(--violet)",
       note:`Assist rates come from xA/90 and key passes/90, scaled by the attacking output of the player's club over
             its remaining fixtures. Bruno Fernandes' record 21 assists last season is the mark to beat.` },
  gg:{ kick:"Golden Glove", title:"Clean sheets, projected", list:() => DATA.golden_glove_race, val:p => p.proj_cs,
       sec:p => p.proj_cs_int, prob:p => p.golden_glove_prob, unit:"clean sheets", color:"var(--draw)",
       note:`Clean sheets are simulated per fixture from the opponent's expected goals, adjusted for the keeper's
             post-shot xG overperformance (PSxG−GA).` },
  poty:{ kick:"Player of the Season", title:"Composite index", list:() => DATA.poty_race, val:p => p.poty_index,
       sec:p => Math.round(p.poty_index), prob:p => p.poty_prob, unit:"index", color:"var(--magi)",
       note:`A composite of goals (×2.1), assists (×1.75), the club's title and top-four probabilities and projected
             points — the kind of season that wins the writers' vote.` }
};
function renderAwardTiles(){
  const h = DATA.headline_predictions;
  const t = [
    { k:"Golden Boot", p:h.golden_boot, v:h.golden_boot.proj_goals, u:"goals", c:"var(--gold)", cls:"y", prob:h.golden_boot.golden_boot_prob },
    { k:"Most assists", p:h.playmaker, v:h.playmaker.proj_assists, u:"assists", c:"var(--violet)", cls:"v", prob:h.playmaker.playmaker_prob },
    { k:"Golden Glove", p:h.golden_glove, v:h.golden_glove.proj_cs, u:"clean sheets", c:"var(--draw)", cls:"", prob:h.golden_glove.golden_glove_prob },
    { k:"Player of the season", p:h.poty, v:h.poty.poty_index, u:"index", c:"var(--magi)", cls:"m", prob:h.poty.poty_prob }
  ];
  $("awardTiles").innerHTML = t.map((x, i) => `
    <div class="tile ${x.cls} rv" style="--d:${i*70}ms; --hc:${x.p.primary_color}">
      <div class="k">${x.k}</div>
      <div class="row" style="margin-top:11px; gap:11px; align-items:center">
        ${crest(x.p.club, 30)}
        <div style="min-width:0">
          <div class="disp" style="font-size:16px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis">${esc(x.p.name)}</div>
          <div class="dim small">${esc(x.p.club_name || x.p.club)}</div>
        </div>
      </div>
      <div style="margin-top:12px">
        <span class="disp num" data-count="${x.v}" data-dec="1" style="font-size:30px">0</span>
        <span class="small dim" style="margin-left:5px">${x.u}</span>
      </div>
      <div class="track" style="margin-top:11px"><i data-w="${Math.max(x.prob, 2.5)}" style="background:${x.c}"></i></div>
      <div class="sub">${pct(x.prob)} chance of winning it</div>
    </div>`).join("");
}
let AWARD_QUERY = "";
function applyAwardFilter(){
  const rows = [...document.querySelectorAll("#awardTable tbody tr")];
  if(!rows.length) return;
  const q = AWARD_QUERY.trim().toLowerCase();
  let shown = 0;
  rows.forEach(tr => {
    const hit = !q || tr.textContent.toLowerCase().includes(q);
    tr.style.display = hit ? "" : "none";
    if(hit) shown++;
  });
  const info = $("awardSearchInfo");
  if(info) info.textContent = q ? `${shown} of ${rows.length} match "${AWARD_QUERY.trim()}"` : "";
}
function wireAwardSearch(){
  const inp = $("awardSearch");
  if(!inp || inp._wired) return;
  inp._wired = 1;
  inp.addEventListener("input", () => { AWARD_QUERY = inp.value; applyAwardFilter(); });
  inp.addEventListener("keydown", (e) => {
    if(e.key === "Escape"){ inp.value = ""; AWARD_QUERY = ""; applyAwardFilter(); inp.blur(); }
  });
}
function renderAwards(){
  const d = AWARD_DEF[AWARD];
  const list = d.list();
  $("awardKick").textContent = d.kick;
  $("awardTitle").textContent = d.title;
  document.querySelectorAll("[data-award]").forEach(b => b.classList.toggle("pri", b.dataset.award === AWARD));
  $("awardPodium").innerHTML = list.slice(0, 4).map((p, i) => `
    <div class="prow ${i === 0 ? "lead" : ""} rv" style="--d:${i*70}ms">
      <span class="rk">${i + 1}</span>
      <div style="display:flex; align-items:center; gap:11px; min-width:0">
        ${crest(p.club, 26)}
        <div style="min-width:0">
          <div class="nm2">${esc(p.name)}</div>
          <div class="cl">${esc(p.club_name || p.club)} · ${esc(p.pos || "GK")} · ${p.games_out > 0 ? `<span style="color:var(--alert)">${p.games_out} games out</span>` : "available"}</div>
        </div>
      </div>
      <div>
        <div class="tot" style="color:${i === 0 ? d.color : "var(--ink)"}" data-count="${d.val(p)}" data-dec="1">0</div>
        <div class="dim small" style="text-align:right">${pct(d.prob(p))} win prob</div>
      </div>
    </div>`).join("");

  $("awardTable").innerHTML = `<caption class="off">Player boards: projected goals, assists and clean sheets</caption><thead><tr>
      <th scope="col">#</th><th scope="col">Player</th><th scope="col" class="num">Now</th><th scope="col" class="num">Last season</th>
      <th scope="col" class="num">Projected</th><th scope="col" class="num">Range</th><th scope="col" class="num">Win prob</th><th scope="col"style="width:18%">Chance</th>
    </tr></thead><tbody>` + list.map((p, i) => {
    const p10 = p.goals_p10 ?? p.assists_p10 ?? p.cs_p10;
    const p90 = p.goals_p90 ?? p.assists_p90 ?? p.cs_p90;
    const cur = p.goals_curr ?? p.assists_curr ?? p.cs_curr;
    const prev = p.goals_prev ?? p.assists_prev ?? p.cs_prev;
    const ver = p.goals_prev_verified ?? p.assists_prev_verified;
    const prob = d.prob(p);
    return `<tr class="rv" style="--d:${Math.min(i*26,380)}ms">
      <td><span class="pos ${i < 3 ? "ucl" : ""}">${i + 1}</span></td>
      <td><div class="row" style="gap:9px; flex-wrap:nowrap">${crest(p.club, 20)}
        <div><div class="disp" style="font-size:13.5px">${esc(p.name)}</div>
        <div class="dim" style="font-size:10.5px">${esc(p.club_name || p.club)} · ${esc(p.nation || "")}</div></div></div></td>
      <td class="num mut">${cur}</td>
      <td class="num mut">${prev === undefined || prev === null ? "—" : prev}${ver ? ' <span style="color:var(--pitch)" title="verified">✓</span>' : prev ? ' <span class="dim" title="estimate">~</span>' : ""}</td>
      <td class="num"><b class="num" style="font-size:15px">${num1(d.val(p))}</b></td>
      <td class="num dim">${p10 ?? "—"}–${p90 ?? "—"}</td>
      <td class="num" style="color:${prob > 15 ? d.color : "var(--ink-2)"}">${pct(prob)}</td>
      <td><div class="track"><i data-w="${Math.min(prob * 2.2, 100)}" style="background:${d.color}"></i></div></td>
    </tr>`;
  }).join("") + `</tbody>`;
  $("awardNote").innerHTML = d.note;

  $("awardWhy").innerHTML = `
    <div class="note" style="margin-bottom:12px">
      ${AWARD === "gg"
        ? "Goalkeepers are modelled separately: team xGA per fixture, the keeper's own PSxG−GA, save percentage and minutes share."
        : `Outfield players carry xG/90, xA/90, key passes per 90, shot conversion, penalty duty and minutes probability.`}
    </div>
    ${[["Goals", "goals_curr"], ["Assists", "assists_curr"], ["xG/90", "xg_90"], ["xA/90", "xa_90"]].map(([lab]) => "").join("")}
    <div class="grid g2" style="gap:10px">
      ${[["Penalty takers", AWARD === "gg" ? "—" : list.filter(x => x.pen_taker).length],
         ["Injury flags", SCENARIO_ACTIVE() ? "scenario live" : "none"],
         ["Projection basis", "Monte Carlo"],
         ["Simulations", (BASELINE.meta.n_simulations || 0).toLocaleString()]].map(([k, v]) => `
        <div class="tile" style="padding:11px 12px"><div class="k">${k}</div><div class="disp" style="font-size:15px;margin-top:5px">${v}</div></div>`).join("")}
    </div>`;

  const hist = { gb:{ n:"Erling Haaland", c:"MCI", v:"27 goals" }, pm:{ n:"Bruno Fernandes", c:"MUN", v:"21 assists" },
                 gg:{ n:"David Raya", c:"ARS", v:"19 clean sheets" }, poty:{ n:"Bruno Fernandes", c:"MUN", v:"FWA Footballer of the Year" } }[AWARD];
  $("awardHistory").innerHTML = `
    <div class="row" style="gap:12px; align-items:center">
      ${crest(hist.c, 34)}
      <div><div class="disp" style="font-size:15px">${hist.n}</div>
        <div class="mut small">2025–26 winner · ${hist.v}</div></div>
    </div>
    ${AWARD === "pm" ? `<div class="note" style="margin-top:12px">That 21-assist campaign is an all-time single-season
      Premier League record — it is the benchmark every creator in ${"2026–27"} is chasing.</div>` : ""}
    ${AWARD === "gb" ? (DATA.headline_predictions.golden_boot.name === hist.n
      ? `<div class="note" style="margin-top:12px">The model has the reigning Golden Boot winner repeating:
         ${num1(DATA.headline_predictions.golden_boot.proj_goals)} goals projected, ${pct(DATA.headline_predictions.golden_boot.golden_boot_prob)} to win it again.</div>`
      : `<div class="note" style="margin-top:12px">Haaland's 27 is the number the model projects
         ${esc(DATA.headline_predictions.golden_boot.name)} to beat this season.</div>`) : ""}`;
}

/* ═══════════ DUEL ═══════════ */
function renderDuel(p){
  const o = outcomeOf(p), tier = tierOf(p);
  const hc = p.home, ac = p.away;
  const hs = (p.top_scorelines || [])[0] || {};
  const rows = reasoning(p);
  const h2h = h2hFor(hc, ac);
  const mk = (label, val) => `<span class="mkt">${label} <b>${pct(val)}</b></span>`;
  const heatMax = Math.max(...(p.matrix_5x5 || [[1]]).flat());

  const battleRows = rows.map((r, i) => {
    const max = Math.max(Math.abs(r.h), Math.abs(r.a), 1e-6);
    const hw = Math.abs(r.h) / max * 50, aw = Math.abs(r.a) / max * 50;
    return `<div class="rv" style="--d:${i*45}ms">
      <div class="lbl">${r.label}</div>
      <div class="brow">
        <div class="v l ${r.edge === "h" ? "win" : "lose"}">${r.fmt(r.h)}</div>
        <div class="tug" style="--hc:${TEAM_COLOR[hc]}; --ac:${TEAM_COLOR[ac]}">
          <div class="l" style="width:${hw}%"></div><div class="r" style="width:${aw}%"></div><div class="mark"></div>
        </div>
        <div class="v r ${r.edge === "a" ? "win" : "lose"}">${r.fmt(r.a)}</div>
      </div>
    </div>`;
  }).join("");

  let heat = `<div class="heat"><div class="hl"></div>` + [0,1,2,3,4].map(j => `<div class="hl">${esc(TEAM_LABEL[ac] || ac)} ${j}</div>`).join("");
  for(let i = 0; i < 5; i++){
    heat += `<div class="hl">${esc(TEAM_LABEL[hc] || hc)} ${i}</div>`;
    for(let j = 0; j < 5; j++){
      const v = p.matrix_5x5[i][j];
      const t = v / heatMax;
      const isMode = hs.score === `${i}-${j}`;
      heat += `<div class="cell${isMode ? " mode" : ""}" title="${i}–${j}: ${v}%"
        style="background:linear-gradient(160deg, rgba(0,224,138,${(0.06 + t * 0.72).toFixed(3)}), rgba(0,180,110,${(0.03 + t * 0.4).toFixed(3)}))"
        >${v > 1.4 ? v.toFixed(1) : ""}</div>`;
    }
  }
  heat += `</div>`;

  $("fxResult").innerHTML = `
    <div class="panel pitch">
      <div class="duel-head">
        <div class="who rv">
          ${crest(hc, 62)}
          <div class="rn">${esc(TEAM_NAME[hc] || hc)}</div>
          <div class="meta">${esc((TEAM_BY_CODE[hc] || {}).manager || "")} · ${esc((TEAM_BY_CODE[hc] || {}).stadium || "")}</div>
          <div>${formStreak((TEAM_BY_CODE[hc] || {}).form)}</div>
        </div>
        <div style="text-align:center">
          <div class="vs2">VS</div>
          <div class="row" style="justify-content:center; gap:6px; margin-top:12px">
            <span class="chip ${tier.cls}">${tier.txt}</span>
            ${p._offline ? `<span class="chip lean">offline engine</span>` : ""}
          </div>
        </div>
        <div class="who rv" style="--d:90ms">
          ${crest(ac, 62)}
          <div class="rn">${esc(TEAM_NAME[ac] || ac)}</div>
          <div class="meta">${esc((TEAM_BY_CODE[ac] || {}).manager || "")} · ${esc((TEAM_BY_CODE[ac] || {}).stadium || "")}</div>
          <div>${formStreak((TEAM_BY_CODE[ac] || {}).form)}</div>
        </div>
      </div>

      <div class="tri" style="height:30px; margin:4px 0 14px" data-wh="${p.prob_home}" data-wd="${p.prob_draw}" data-wa="${p.prob_away}">
        <i class="h"><span>${pct(p.prob_home)}</span></i><i class="d"><span class="lite">${pct(p.prob_draw)}</span></i><i class="a"><span>${pct(p.prob_away)}</span></i>
      </div>
      <div class="grid g3" style="gap:14px; align-items:center; margin-top:6px">
        <div class="tile" style="text-align:center; --hc:${TEAM_COLOR[hc]}">
          <div class="k">${esc(TEAM_LABEL[hc])} win</div>
          <div class="big" style="color:var(--pitch)" data-count="${p.prob_home}" data-dec="1" data-suf="%">0%</div>
          <div class="track" style="margin-top:10px"><i data-w="${p.prob_home}" style="background:var(--pitch)"></i></div>
        </div>
        <div class="tile" style="text-align:center">
          <div class="k">Draw</div>
          <div class="big" style="color:var(--draw)" data-count="${p.prob_draw}" data-dec="1" data-suf="%">0%</div>
          <div class="track" style="margin-top:10px"><i data-w="${p.prob_draw}" style="background:var(--draw)"></i></div>
        </div>
        <div class="tile" style="text-align:center; --ac:${TEAM_COLOR[ac]}">
          <div class="k">${esc(TEAM_LABEL[ac])} win</div>
          <div class="big" style="color:var(--magi)" data-count="${p.prob_away}" data-dec="1" data-suf="%">0%</div>
          <div class="track" style="margin-top:10px"><i data-w="${p.prob_away}" style="background:var(--magi)"></i></div>
        </div>
      </div>

      <div class="note" style="margin-top:14px">
        <b>Model call:</b> <b style="color:${o.color}">${esc(o.label)}</b> — ${pct(o.prob)} probability.
        Most likely scoreline <b>${hs.score || "—"}</b> (${hs.prob ?? "—"} expected goals ${num1(p.lambda_home)}–${num1(p.lambda_away)}).
        ${tier.cls === "toss" ? "This one is about as close to a coin-flip as the model gets." : ""}
      </div>
    </div>

    <div class="grid g2" style="margin-top:16px; gap:16px">
      <div class="panel">
        <div class="phead"><div><span class="kick">Stat battle</span><h3>Who holds the edge, and where</h3></div></div>
        <div class="battle">${battleRows}</div>
        <div class="note" style="margin-top:14px">
          Each bar is a tug-of-war: the further a fill crosses the centre line, the bigger that side's edge.
          These are the same live ratings the match model consumes.
        </div>
      </div>

      <div class="stack">
        <div class="panel hot">
          <div class="phead"><div><span class="kick">Scoreline grid</span><h3>Dixon-Coles probability map</h3></div></div>
          ${heat}
          <div class="row" style="margin-top:12px">
            <span class="kick">most likely</span>
            ${(p.top_scorelines || []).slice(0, 4).map(s => `<span class="mkt">${s.score} <b>${s.prob}%</b></span>`).join("")}
          </div>
        </div>
        <div class="panel">
          <div class="phead"><div><span class="kick">Markets</span><h3>Derived from the grid</h3></div></div>
          <div class="mkts">
            ${mk("Both teams score", p.btts_prob)}
            ${mk("Over 2.5 goals", p.over_2_5_prob)}
            <span class="mkt">Under 2.5 <b>${pct(100 - p.over_2_5_prob)}</b></span>
            <span class="mkt">${esc(TEAM_LABEL[hc])} clean sheet <b>${pct(p.clean_sheet_home)}</b></span>
            <span class="mkt">${esc(TEAM_LABEL[ac])} clean sheet <b>${pct(p.clean_sheet_away)}</b></span>
          </div>
        </div>
      </div>
    </div>

    <div class="grid g2" style="margin-top:16px; gap:16px">
      <div class="panel">
        <div class="phead"><div><span class="kick">Head to head</span><h3>Recent meetings</h3></div></div>
        ${h2h.recs.length ? `
          <div class="row" style="gap:10px; margin-bottom:12px">
            <span class="mkt">${esc(TEAM_LABEL[hc])} wins <b>${h2h.hw}</b></span>
            <span class="mkt">draws <b>${h2h.d}</b></span>
            <span class="mkt">${esc(TEAM_LABEL[ac])} wins <b>${h2h.aw}</b></span>
          </div>
          ${h2h.recs.slice(0, 4).map(r => `
            <div class="row" style="justify-content:space-between; padding:9px 0; border-top:1px dashed rgba(255,255,255,.06)">
              <span class="small mut">${esc(r[4] || "")}</span>
              <span style="display:flex;align-items:center;gap:9px">
                ${crest(r[0], 16)}<span class="disp" style="font-size:13px">${esc(TEAM_LABEL[r[0]])}</span>
                <span class="num" style="font-size:15px">${r[2]}–${r[3]}</span>
                <span class="disp" style="font-size:13px">${esc(TEAM_LABEL[r[1]])}</span>${crest(r[1], 16)}
              </span>
            </div>`).join("")}` :
        `<div class="note">No meeting between these two in the training window — the model leans purely on ratings for this one.</div>`}
      </div>
      <div class="panel">
        <div class="phead"><div><span class="kick">Context</span><h3>Both clubs this season</h3></div></div>
        <div class="grid g2" style="gap:12px">
          ${[hc, ac].map((c, i) => {
            const t = DATA.table_projections.find(x => x.code === c) || {};
            return `<div>
              <div class="row" style="gap:9px; margin-bottom:9px">${crest(c, 24)}
                <div><div class="disp" style="font-size:14px">${esc(TEAM_LABEL[c])}</div>
                <div class="dim small">${t.current_pos ? t.current_pos + "th" : ""} · ${t.curr_pts ?? "—"} pts</div></div></div>
              <div class="small mut" style="line-height:1.9">
                Form <b>${esc((TEAM_BY_CODE[c] || {}).form || "—")}</b><br>
                Projected <b>${num1(t.proj_pts)}</b> pts (${num1(t.proj_gf)}–${num1(t.proj_ga)})<br>
                Title <b>${pct(t.title_prob)}</b> · Top four <b>${pct(t.top4_prob)}</b><br>
                Relegation <b>${pct(t.relegation_prob)}</b>
              </div>
            </div>`;
          }).join("")}
        </div>
      </div>
    </div>`;

  animate($("fxResult"));
}
function renderDuelSelects(){
  const opts = [...TEAMS_IN].sort((a, b) => a.name.localeCompare(b.name))
    .map(t => `<option value="${t.code}">${esc(t.name)}</option>`).join("");
  $("fxHome").innerHTML = opts; $("fxAway").innerHTML = opts;
  $("fxHome").value = "LIV"; $("fxAway").value = "MCI";
  const quick = [["LIV","MCI"],["ARS","MCI"],["LIV","MUN"],["CHE","TOT"],["NEW","SUN"],["MCI","IPS"]];
  $("fxQuick").innerHTML = `<span class="kick" style="align-self:center">quick duels</span>` +
    quick.map(([h, a]) => `<button class="btn sm" data-h="${h}" data-a="${a}">
      ${crest(h, 13)} ${esc(TEAM_LABEL[h])} v ${esc(TEAM_LABEL[a])} ${crest(a, 13)}</button>`).join("");
  $("fxQuick").querySelectorAll("button").forEach(b => b.onclick = () => {
    $("fxHome").value = b.dataset.h; $("fxAway").value = b.dataset.a; predictFixture();
  });
}

/* ═══════════ SCENARIO ═══════════ */
/** A scenario value, safe to put in markup. Digits and a minus sign, nothing else.
 *
 * Belt and braces: core.js's sanitizeScenario is what stops a crafted share link from reaching the
 * form at all, and this is what guarantees the form cannot emit anything but a number even if that
 * ever fails. The bug being fixed here was an `<img onerror=...>` landing in a slider's value
 * attribute, so these call sites do not get to trust their input any more.
 */
function scnNum(v){
  const n = Math.round(Number(v));
  if(!isFinite(n)) return 0;
  return Math.max(-99, Math.min(99, n));
}

function renderScenarioForm(){
  const { teamsSorted, players } = scenarioInputTemplates();
  const boosted = SCENARIO.team_boosts, ded = SCENARIO.points_deductions;
  const keyFixtures = [["MCI","LIV"],["ARS","MCI"],["LIV","MCI"],["MCI","ARS"]];
  $("scenarioForm").innerHTML = `
    <details class="acc" open>
      <summary>Injuries &amp; absences <span class="cnt" data-cnt="inj">0 active</span></summary>
      <div class="body">
        <div class="small mut">Games out of the remaining 33 matchweeks. Losing a frontline player
          cuts the club's attacking output and Elo by a magnitude scaled to their goal involvement.</div>
        ${players.map((p, i) => `
          <div class="itemrow wide">
            <div class="row" style="gap:9px">${crest(p.club, 18)}
              <div><div class="disp" style="font-size:13px">${esc(p.name)}</div>
              <div class="dim" style="font-size:10.5px">${esc(TEAM_LABEL[p.club])} · ${esc(p.pos)}</div></div></div>
            <div class="srow">
              <input class="slider inj" type="range" min="0" max="33" value="${scnNum(SCENARIO.player_injuries[p.player_id])}"
                aria-label="Games out: ${esc(p.name)}"
                aria-valuetext="${scnNum(SCENARIO.player_injuries[p.player_id]) === 0 ? "available" : scnNum(SCENARIO.player_injuries[p.player_id]) + " games out"}"
                data-pid="${p.player_id}" data-name="${esc(p.name)}">
              <span class="val" id="inj_${p.player_id}">${scnNum(SCENARIO.player_injuries[p.player_id])}</span>
            </div>
          </div>`).join("")}
      </div>
    </details>

    <details class="acc">
      <summary>Form swings <span class="cnt" data-cnt="form">0 clubs</span></summary>
      <div class="body">
        <div class="small mut">Scale a club's attack and defence by ±25% — a new manager bounce, a January signing, or a collapse.</div>
        ${teamsSorted.map(t => {
          const b = boosted[t.code] || { attack:0, defence:0 };
          return `<div class="itemrow wide">
            <div class="row" style="gap:9px">${crest(t.code, 18)}
              <div class="disp" style="font-size:13px">${esc(t.short)}</div></div>
            <div>
              <div class="srow form"><input class="slider atk" type="range" min="-25" max="25" value="${scnNum(b.attack)}" data-code="${t.code}">
                <span class="val" id="atk_${t.code}">${scnNum(b.attack) > 0 ? "+" : ""}${scnNum(b.attack)}%</span></div>
              <div class="srow form" style="margin-top:7px"><input class="slider def" type="range" min="-25" max="25" value="${scnNum(b.defence)}" data-code="${t.code}">
                <span class="val" id="def_${t.code}">${scnNum(b.defence) > 0 ? "+" : ""}${scnNum(b.defence)}%</span></div>
            </div>
          </div>`;
        }).join("")}
        <div class="small dim">Left slider = attack, right slider = defence.</div>
      </div>
    </details>

    <details class="acc">
      <summary>Points deductions <span class="cnt" data-cnt="ded">0 clubs</span></summary>
      <div class="body">
        ${teamsSorted.map(t => `<div class="itemrow wide">
          <div class="row" style="gap:9px">${crest(t.code, 18)}<div class="disp" style="font-size:13px">${esc(t.short)}</div></div>
          <div class="srow">
            <input class="slider ded" type="range" min="0" max="30" value="${scnNum(ded[t.code])}" data-code="${t.code}">
            <span class="val" id="ded_${t.code}">−${scnNum(ded[t.code])}</span></div>
        </div>`).join("")}
      </div>
    </details>

    <details class="acc">
      <summary>Force a scoreline <span class="cnt" data-cnt="forced">0 forced</span></summary>
      <div class="body">
        <div class="small mut">Lock in a result you think the model has wrong — a derby upset, a smash-and-grab.</div>
        ${keyFixtures.map(([h, a]) => `<div class="itemrow" style="grid-template-columns:1fr auto; align-items:center">
          <div class="row" style="gap:8px">${crest(h, 18)}<b class="disp" style="font-size:13px">${esc(TEAM_LABEL[h])}</b>
            <input type="number" min="0" max="9" value="0" id="cs_h_${h}${a}" style="width:58px; text-align:center">
            <span class="dim">–</span>
            <input type="number" min="0" max="9" value="0" id="cs_a_${h}${a}" style="width:58px; text-align:center">
            <b class="disp" style="font-size:13px">${esc(TEAM_LABEL[a])}</b>${crest(a, 18)}</div>
          <button class="btn sm" onclick="setCustomScore('${h}','${a}')">Lock in</button>
        </div>`).join("")}
      </div>
    </details>`;

  $("scenarioForm").querySelectorAll(".inj").forEach(el => {
    el.oninput = () => {
      const v = +el.value; SCENARIO.player_injuries[el.dataset.pid] = v;
      $("inj_" + el.dataset.pid).textContent = v;
      if(v === 0) delete SCENARIO.player_injuries[el.dataset.pid];
      markScenario();
    };
  });
  $("scenarioForm").querySelectorAll(".atk").forEach(el => {
    el.oninput = () => {
      const c = el.dataset.code, v = +el.value;
      SCENARIO.team_boosts[c] = SCENARIO.team_boosts[c] || { attack:0, defence:0 };
      SCENARIO.team_boosts[c].attack = v;
      $("atk_" + c).textContent = (v > 0 ? "+" : "") + v + "%";
      markScenario();
    };
  });
  $("scenarioForm").querySelectorAll(".def").forEach(el => {
    el.oninput = () => {
      const c = el.dataset.code, v = +el.value;
      SCENARIO.team_boosts[c] = SCENARIO.team_boosts[c] || { attack:0, defence:0 };
      SCENARIO.team_boosts[c].defence = v;
      $("def_" + c).textContent = (v > 0 ? "+" : "") + v + "%";
      markScenario();
    };
  });
  $("scenarioForm").querySelectorAll(".ded").forEach(el => {
    el.oninput = () => {
      const c = el.dataset.code, v = +el.value;
      SCENARIO.points_deductions[c] = v;
      $("ded_" + c).textContent = "−" + v;
      markScenario();
    };
  });
  $("scenAwardBtns").innerHTML = [["gb","Golden Boot"],["pm","Assists"],["gg","Glove"]].map(([k, l]) =>
    `<button class="btn sm ${SCEN_AWARD === k ? "pri" : ""}" data-sa="${k}">${l}</button>`).join("");
  $("scenAwardBtns").querySelectorAll("button").forEach(b => b.onclick = () => { SCEN_AWARD = b.dataset.sa; renderScenarioAwards(); });
  markScenario();
}
function resetScenario(){
  SCENARIO = { player_injuries:{}, team_boosts:{}, points_deductions:{}, custom_scores:{} };
  SIM_RESULT = null;
  renderScenarioForm();
  $("simSummary").innerHTML = `<div class="note">Cleared — showing baseline projections again. Adjust something and re-simulate.</div>`;
  $("simMovers").innerHTML = "";
  $("scenTable").innerHTML = "";
  renderScenarioAwards();
  toast("Scenario cleared — back to the baseline model.");
}
function renderScenario(){
  const s = SIM_RESULT, b = BASELINE;
  if(!s) return;
  const champ = s.table_projections[0];
  const bMap = {}; b.table_projections.forEach(r => bMap[r.code] = r);
  const deltas = s.table_projections.map(r => ({ r, d:r.proj_pts - bMap[r.code].proj_pts, bpts:bMap[r.code].proj_pts, bpos:bMap[r.code].proj_pos }))
    .sort((x, y) => y.d - x.d);
  const injCount = Object.values(SCENARIO.player_injuries).filter(v => v > 0).length;
  const boostCount = Object.values(SCENARIO.team_boosts).filter(x => (x.attack || 0) !== 0 || (x.defence || 0) !== 0).length;
  const dedCount = Object.values(SCENARIO.points_deductions).filter(v => v > 0).length;

  $("simSummary").innerHTML = `
    <div class="grid g2" style="gap:12px">
      <div class="tile g"><div class="k">Scenario champion</div>
        <div class="row" style="gap:10px; align-items:center; margin-top:8px">${crest(champ.code, 28)}
          <div><div class="disp" style="font-size:19px">${esc(champ.short)}</div>
          <div class="small mut">${num1(champ.proj_pts)} pts · ${pct(champ.title_prob)} title
          (baseline ${pct(bMap[champ.code].title_prob)})</div></div></div></div>
      <div class="tile y"><div class="k">Golden Boot</div>
        <div class="row" style="gap:10px; align-items:center; margin-top:8px">${crest(s.headline_predictions.golden_boot.club, 28)}
          <div><div class="disp" style="font-size:19px">${esc(s.headline_predictions.golden_boot.name)}</div>
          <div class="small mut">${s.headline_predictions.golden_boot.proj_goals} goals
          (baseline ${b.headline_predictions.golden_boot.proj_goals})</div></div></div></div>
    </div>
    <div class="note" style="margin-top:12px">
      ${s.meta.n_simulations.toLocaleString()} seasons re-simulated${s.meta.client_fallback ? " with the client-side structural engine" : " by the Python ML engine"} ·
      ${injCount} injuries · ${boostCount} form swings · ${dedCount} deductions · ${Object.keys(SCENARIO.custom_scores).length} forced results.
      Deltas below compare against the baseline run.
    </div>`;

  $("scenTable").innerHTML = `<caption class="off">Scenario table: what the What-If settings do to each club</caption><thead><tr><th scope="col">#</th><th scope="col">Club</th><th scope="col" class="num">Scenario pts</th>
      <th scope="col" class="num">Δ pts</th><th scope="col" class="num">Pos</th><th scope="col" class="num">Δ</th><th scope="col" class="num">Title</th><th scope="col" class="num">Releg.</th></tr></thead><tbody>` +
    [...s.table_projections].sort((x, y) => y.proj_pts - x.proj_pts).map((r, i) => {
      const d = r.proj_pts - bMap[r.code].proj_pts;
      return `<tr class="rv" style="--d:${Math.min(i*24,360)}ms">
        <td><span class="${posClass(i + 1)}">${i + 1}</span></td>
        <td><div class="row" style="gap:8px; flex-wrap:nowrap">${crest(r.code, 18)}
          <b class="disp" style="font-size:13px">${esc(r.short)}</b></div></td>
        <td class="num"><b class="num">${num1(r.proj_pts)}</b></td>
        <td class="num" style="color:${d > .05 ? "var(--pitch)" : d < -.05 ? "var(--alert)" : "var(--ink-3)"}"><b>${d > 0 ? "+" : ""}${num1(d)}</b></td>
        <td class="num mut">${bMap[r.code].proj_pos} → <b style="color:var(--ink)">${i + 1}</b></td>
        <td class="num mut">${(i + 1) - bMap[r.code].proj_pos > 0 ? "+" : ""}${(i + 1) - bMap[r.code].proj_pos}</td>
        <td class="num">${r.title_prob > 0.1 ? num1(r.title_prob) + "%" : "—"}</td>
        <td class="num" style="color:${r.relegation_prob > 5 ? "var(--alert)" : "var(--ink-3)"}">${r.relegation_prob > 1 ? num1(r.relegation_prob) + "%" : "—"}</td>
      </tr>`;
    }).join("") + `</tbody>`;

  const movers = deltas.slice(0, 3).concat(deltas.slice(-3)).filter((x, i, arr) => arr.indexOf(x) === i);
  $("simMovers").innerHTML = movers.sort((x, y) => y.d - x.d).map(m => `
    <div class="racebar">
      <div class="who">${crest(m.r.code, 17)}${esc(m.r.short)}</div>
      <div class="track"><i data-w="${Math.min(Math.abs(m.d) * 8, 100)}"
        style="background:${m.d >= 0 ? "var(--pitch)" : "var(--alert)"}"></i></div>
      <div class="pct" style="color:${m.d >= 0 ? "var(--pitch)" : "var(--alert)"}">${m.d > 0 ? "+" : ""}${num1(m.d)}</div>
    </div>`).join("");
  animate($("tab-whatif"));
  /* if this scenario has changed who wins the league, say so — loudly */
  if(typeof UX !== "undefined") UX.celebrateFlip(champ.code, b.table_projections[0].code);
}
function renderScenarioAwards(){
  const box = $("scenAwards");
  if(!SIM_RESULT){
    box.innerHTML = `<div class="note">Run a scenario to see how the award races move — injuries to a
      Golden Boot contender ripple straight through these numbers.</div>`;
    if($("simMovers")) $("simMovers").innerHTML = `<div class="empty">No scenario yet — the top gainers and
      losers will appear here once you re-simulate.</div>`;
    if($("scenTable")) $("scenTable").innerHTML = `<caption class="off">Scenario table: what the What-If settings do to each club</caption><tbody><tr><td><div class="empty">
      Baseline projections are on the Table tab. Run a scenario to compare against them here.</div></td></tr></tbody>`;
    return;
  }
  const s = SIM_RESULT, b = BASELINE;
  const src = SCEN_AWARD === "gb" ? [s.golden_boot_race, b.golden_boot_race, "proj_goals", "golden_boot_prob", "goals"]
            : SCEN_AWARD === "pm" ? [s.playmaker_race, b.playmaker_race, "proj_assists", "playmaker_prob", "assists"]
            : [s.golden_glove_race, b.golden_glove_race, "proj_cs", "golden_glove_prob", "clean sheets"];
  const [list, base, key, pkey] = src;
  const bMap = {}; base.forEach(r => bMap[r.player_id] = r);
  box.innerHTML = list.slice(0, 6).map((p, i) => {
    const bv = bMap[p.player_id] ? bMap[p.player_id][key] : p[key];
    const d = p[key] - bv;
    return `<div class="prow ${i === 0 ? "lead" : ""}" style="--hc:${p.primary_color}">
      <span class="rk">${i + 1}</span>
      <div style="display:flex; align-items:center; gap:10px; min-width:0">${crest(p.club, 22)}
        <div style="min-width:0"><div class="nm2" style="font-size:13.5px">${esc(p.name)}</div>
        <div class="cl">${esc(p.club_name || p.club)}</div></div></div>
      <div><div class="tot" style="font-size:17px">${num1(p[key])}</div>
        <div class="dim small" style="text-align:right; color:${d > .05 ? "var(--pitch)" : d < -.05 ? "var(--alert)" : "var(--ink-3)"}">
          ${d > 0 ? "+" : ""}${num1(d)} vs base</div></div>
    </div>`;
  }).join("") + `<div class="note" style="margin-top:12px">Showing ${src[4]} · win probability ${pct(list[0][pkey])} for ${esc(list[0].name)} under this scenario.</div>`;
}

/* ═══════════ MODEL ═══════════ */
function renderMetrics(){
  const tiles = [
    { k:"1X2 accuracy", v:M.accuracy_1x2, s:"5-fold stratified cross-validation, out-of-fold", cls:"g" },
    { k:"Ranked probability score", v:M.rps, s:"lower is better — scores the full distribution", cls:"", dec:4 },
    { k:"Brier score", v:M.brier_score, s:"multi-class, calibrated probabilities", cls:"v", dec:4 },
    { k:"Log-loss", v:M.log_loss, s:"penalises confident mistakes", cls:"m", dec:4 }
  ];
  $("metricTiles").innerHTML = tiles.map((x, i) => `
    <div class="tile ${x.cls} rv" style="--d:${i*70}ms">
      <div class="k">${x.k}</div>
      <div class="big" data-count="${x.v}" data-dec="${x.dec ?? 1}" data-suf="${x.dec === 0 || !x.dec ? "%" : ""}">0</div>
      <div class="sub">${x.s}</div>
    </div>`).join("");
}
function renderCharts(){
  /* RPS comparison */
  const items = [
    { n:"This model", v:M.rps, me:true },
    { n:"Home base rate", v:0.2276 },
    { n:"Prior-table favourite", v:0.2396 },
    { n:"Uniform 1/3", v:0.2322 }
  ];
  const max = Math.max(...items.map(x => x.v)) * 1.12;
  $("chartRps").innerHTML = items.map((x, i) => `
    <div style="margin-bottom:11px" class="rv">
      <div class="row" style="justify-content:space-between">
        <span class="small" style="font-family:var(--f-disp);font-weight:700;color:${x.me ? "var(--pitch)" : "var(--ink-2)"}">${x.n}</span>
        <span class="num small">${x.v}</span>
      </div>
      <div class="track" style="margin-top:6px; height:${x.me ? 12 : 8}px">
        <i data-w="${(x.v / max * 100).toFixed(1)}" style="background:${x.me ? "linear-gradient(90deg,#00e08a,#22d3ee)" : "rgba(255,255,255,.22)"}"></i>
      </div>
    </div>`).join("") + `<div class="small dim">${((1 - M.rps / 0.2396) * 100).toFixed(1)}% better than the prior-season-table benchmark.</div>`;

  /* calibration */
  const cal = M.calibration || [];
  const W = 340, H = 190, pad = 36;
  const sx = v => pad + (v - 30) / 60 * (W - pad * 1.3), sy = v => H - pad - (v - 30) / 60 * (H - pad * 1.5);
  $("chartCalib").innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" class="chart">
      <line x1="${sx(30)}" y1="${sy(30)}" x2="${sx(90)}" y2="${sy(90)}" stroke="rgba(255,255,255,.16)" stroke-dasharray="4 4"/>
      ${[30,45,60,75,90].map(v => `<line class="gline" x1="${sx(v)}" y1="${sy(30)}" x2="${sx(v)}" y2="${sy(90)}"/>
        <text class="glabel" x="${sx(v)}" y="${H - 14}" text-anchor="middle">${v}%</text>`).join("")}
      ${[30,45,60,75,90].map(v => `<line class="gline" x1="${sx(30)}" y1="${sy(v)}" x2="${sx(90)}" y2="${sy(v)}"/>
        <text class="glabel" x="${pad - 8}" y="${sy(v) + 3}" text-anchor="end">${v}%</text>`).join("")}
      <polyline data-draw points="${cal.map(c => `${sx(c.predicted)},${sy(c.observed)}`).join(" ")}"
        fill="none" stroke="url(#calgrad)" stroke-width="2.6" stroke-linejoin="round"/>
      <defs><linearGradient id="calgrad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#00e08a"/><stop offset="1" stop-color="#ff2d78"/></linearGradient></defs>
      ${cal.map(c => `<circle cx="${sx(c.predicted)}" cy="${sy(c.observed)}" r="${Math.max(3, Math.min(6, c.count / 24))}"
        fill="${c.count < 6 ? "var(--gold)" : "#0ef0a0"}" opacity=".95"><title>predicted ${c.predicted}% → observed ${c.observed}% (n=${c.count})</title></circle>`).join("")}
    </svg>
    <div class="small dim">On the dashed line = perfectly calibrated. Amber points have n&lt;6 — don't read them as signal.</div>`;

  /* feature importance */
  const maxF = Math.max(...FEATS.map(f => f.importance));
  $("featImp").innerHTML = FEATS.map((f, i) => `
    <div style="margin-bottom:12px" class="rv">
      <div class="row" style="justify-content:space-between; align-items:baseline">
        <span class="small" style="font-family:var(--f-disp);font-weight:700">${esc(f.label)}</span>
        <span class="num small dim">${f.importance}%</span>
      </div>
      <div class="track" style="margin-top:6px; height:9px">
        <i data-w="${(f.importance / maxF * 100).toFixed(1)}"
           style="background:linear-gradient(90deg,rgba(0,224,138,${(1 - i * 0.08).toFixed(2)}),rgba(34,211,238,${(0.85 - i * 0.07).toFixed(2)}))"></i>
      </div>
    </div>`).join("");
}

/* ═══════════ BACKTEST ═══════════ */
function renderBacktest(){
  if(!BT){ $("btTiles").innerHTML = `<div class="tile">Backtest unavailable</div>`; return; }
  const m = BT.model, b = BT.baselines, t = BT.table_level;
  $("btStamp").textContent = `pre-season replay · ${BT.meta.season_replayed}`;
  $("btTiles").innerHTML = [
    { k:"1X2 accuracy", v:m.accuracy, s:`vs ${b["prior_season_table_favourite"].accuracy}% for prior-table baseline`, cls:"g", dec:1, suf:"%" },
    { k:"RPS skill", v:BT.skill_vs_prior_table.rps, s:"improvement over the strongest baseline", cls:"g", dec:1, pre:"+", suf:"%" },
    { k:"Position error", v:t.position_mae, s:`mean places off · Spearman ρ ${t.spearman_rank_correlation}`, cls:"v", dec:1 },
    { k:"Champion", v:t.champion_correct ? "✓" : "✗", s:`projected ${t.projected_champion}, actual ${t.actual_champion}`, cls:"y", raw:true }
  ].map((x, i) => `<div class="tile ${x.cls} rv" style="--d:${i*70}ms">
      <div class="k">${x.k}</div>
      ${x.raw ? `<div class="big" style="font-size:34px">${x.v}</div>`
              : `<div class="big" data-count="${x.v}" data-dec="${x.dec}" data-pre="${x.pre || ""}" data-suf="${x.suf || ""}">0</div>`}
      <div class="sub">${x.s}</div>
    </div>`).join("");

  /* rolling accuracy */
  const roll = BT.rolling_accuracy || [];
  if(roll.length){
    const W = 520, H = 170, pad = 30;
    const xs = i => pad + i / (roll.length - 1) * (W - pad - 12);
    const ys = v => H - pad - (v - 30) / 30 * (H - pad - 24);
    let d = `M ${xs(0)} ${ys(roll[0])}`;
    roll.forEach((v, i) => { if(i) d += ` L ${xs(i)} ${ys(v)}`; });
    $("btRolling").innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" class="chart">
        <line class="gline" x1="${pad}" y1="${ys(50)}" x2="${W - 12}" y2="${ys(50)}" stroke-dasharray="4 4"/>
        <text class="glabel" x="${W - 12}" y="${ys(50) - 5}" text-anchor="end">50% = coin flip</text>
        <path d="${d} L ${xs(roll.length - 1)} ${H - pad} L ${pad} ${H - pad} Z" fill="url(#rg)" opacity=".5"/>
        <defs><linearGradient id="rg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="rgba(0,224,138,.5)"/><stop offset="1" stop-color="rgba(0,224,138,0)"/></linearGradient></defs>
        <path data-draw d="${d}" fill="none" stroke="#0ef0a0" stroke-width="2.4" stroke-linejoin="round"/>
        <text class="glabel" x="${pad}" y="${H - 10}">match 1</text>
        <text class="glabel" x="${W - 12}" y="${H - 10}" text-anchor="end">match 380</text>
      </svg>
      <div class="small dim">Rolling 40-match accuracy across the replay — it settles around the mid-40s and
        never drifts, which is what you want from a stable model.</div>`;
    animate($("btRolling"));
  }

  /* dumbbell: projected vs actual finish */
  const rows = t.table.slice().sort((a, b) => a.actual_pos - b.actual_pos);
  $("btDumbbell").innerHTML = `
    <div style="display:grid; gap:5px">
      ${rows.map((r, i) => {
        const lo = Math.min(r.proj_pos, r.actual_pos), hi = Math.max(r.proj_pos, r.actual_pos);
        const good = Math.abs(r.pos_error) <= 2;
        return `<div class="rv" style="--d:${i*18}ms; display:grid; grid-template-columns:20px 1fr; gap:9px; align-items:center">
          ${crest(r.code, 16)}
          <div style="position:relative; height:16px">
            <div style="position:absolute; left:${(lo - 1) / 19 * 100}%; width:${(hi - lo) / 19 * 100}%;
              top:6px; height:3px; border-radius:2px; background:${good ? "rgba(0,224,138,.55)" : "rgba(255,255,255,.18)"}"></div>
            <div title="projected ${r.proj_pos}" style="position:absolute; left:${(r.proj_pos - 1) / 19 * 100}%; top:2px;
              width:11px; height:11px; margin-left:-5.5px; border-radius:50%; background:var(--magi); box-shadow:0 0 10px -2px var(--magi)"></div>
            <div title="actual ${r.actual_pos}" style="position:absolute; left:${(r.actual_pos - 1) / 19 * 100}%; top:2px;
              width:11px; height:11px; margin-left:-5.5px; border-radius:50%; background:var(--pitch); box-shadow:0 0 10px -2px var(--pitch)"></div>
          </div>
        </div>`;
      }).join("")}
    </div>
    <div class="row" style="gap:14px; margin-top:11px">
      <span class="mkt" style="background:transparent">projected <b style="color:var(--magi)">●</b></span>
      <span class="mkt" style="background:transparent">actual <b style="color:var(--pitch)">●</b></span>
      <span class="small dim">narrow gap = the model saw it coming</span>
    </div>`;

  /* metrics table */
  const rowsM = [["This model", m, true]];
  Object.entries(b).forEach(([k, v]) => rowsM.push([k.replace(/_/g, " "), v, false]));
  $("btMetrics").innerHTML = `<caption class="off">Backtest: the model against three baselines over the 2025-26 replay</caption><thead><tr><th scope="col">Forecaster</th><th scope="col" class="num">Acc</th><th scope="col" class="num">RPS ↓</th>
      <th scope="col" class="num">Brier ↓</th><th scope="col" class="num">Log-loss ↓</th></tr></thead><tbody>` +
    rowsM.map(([n, mm, isM]) => `<tr style="${isM ? "background:rgba(0,224,138,.07)" : ""}">
      <td style="font-family:var(--f-disp);font-weight:${isM ? 800 : 500};color:${isM ? "var(--pitch)" : "var(--ink-2)"}">${n}</td>
      <td class="num"><b>${mm.accuracy}%</b></td><td class="num">${mm.rps}</td>
      <td class="num">${mm.brier}</td><td class="num">${mm.log_loss}</td></tr>`).join("") + `</tbody>`;

  const pr = t.promoted_clubs_actual_rank, pp = t.promoted_clubs_proj_rank;
  $("btFindings").innerHTML = `
    <div class="kick" style="margin-bottom:10px">What the replay got right — and wrong</div>
    <div class="note" style="margin-bottom:10px"><b>Champion:</b> projected ${esc(t.projected_champion)}, actual
      <b>${esc(t.actual_champion)}</b> — the model had the right clubs at the top, it just couldn't know the title would flip.</div>
    <div class="note" style="margin-bottom:10px"><b>Top four:</b> ${t.top4_overlap} of 4 correct —
      ${esc(t.projected_top4.join(", "))} vs ${esc(t.actual_top4.join(", "))}.</div>
    <div class="note warn" style="margin-bottom:10px"><b>Biggest miss:</b> Sunderland — projected ${pp["Sunderland"]},
      actual ${pr["Sunderland"]}. A promoted-club prior can't see a £150m rebuild.</div>
    <div class="note hot"><b>Why show this?</b> It's a cold-start, pre-season test with no current-season
      information — deliberately harder than the live 2026–27 forecasts. Read ${m.accuracy}% as a floor, not the ceiling.</div>`;
}
function renderArch(){
  const rows = [
    ["Goal model", "Poisson GLM (L2, α=0.8) blended 55/45 with HistGradientBoosting (Poisson loss, depth 3)"],
    ["Structural prior", "Attack × defence matchup rates blended 60/40 with the ML layer"],
    ["Scoreline grid", "Dixon-Coles low-score correction (ρ = −0.11) on a bivariate Poisson grid"],
    ["Outcome layer", "Soft-voting ensemble: logistic 45% + random forest 30% + gradient boosting 25%"],
    ["Calibration", `λ rescaled to the live league rate (${LAMBDA_SCALE}×, ≈2.86 goals per game)`],
    ["Season engine", `Vectorised Monte Carlo over ${FIXTURES_IN.length} remaining fixtures × ${(DATA.meta.n_simulations || 0).toLocaleString()} seasons`],
    ["Player engine", "Gamma-Poisson goal/assist sampling with penalties, conversion skill and minutes probability"],
    ["Training data", `${M.matches_trained} matches — all ${M.matches_2025_26} of 2025–26 plus ${M.matches_2026_27_live} live 2026–27 (weighted 1.6×)`]
  ];
  $("archList").innerHTML = `<div style="display:grid; gap:10px">${rows.map(([k, v], i) => `
    <div class="rv" style="--d:${i*45}ms; display:grid; grid-template-columns:130px 1fr; gap:12px; padding-bottom:10px; border-bottom:1px dashed rgba(255,255,255,.06)">
      <span class="kick" style="padding-top:2px">${k}</span><span class="small mut">${v}</span>
    </div>`).join("")}</div>`;
}
function renderLimits(){
  const items = [
    ["Five games is a tiny sample", "Form is shrunk 85/15 toward last season's baseline and long-run tactical ratings, so a hot start never hijacks the projection."],
    ["It can't know the future", "January signings, sackings, dressing-room crises and fixture rearrangements are exactly what the What-If tab exists for."],
    ["Promoted clubs are the weak spot", "The blind 2025–26 replay shows promoted sides are systematically underpriced — a big summer spend isn't visible to a prior."],
    ["Fixtures are official, kick-offs standard", "Matchweeks and dates come from the published 2026–27 calendar; individual TV rearrangements will move a handful of times."],
    ["This is analysis, not betting advice", "A 52% title probability means 'more likely than not', not certain. About a quarter of matches are genuine coin-flips."]
  ];
  $("limits").innerHTML = `<div style="display:grid; gap:10px">${items.map(([k, v], i) => `
    <div class="rv" style="--d:${i*50}ms">
      <div class="disp" style="font-size:13.5px; margin-bottom:3px">${k}</div>
      <div class="small mut">${v}</div>
    </div>`).join("")}</div>`;
}
function renderDataTab(){
  const files = [
    ["predictions_2026_27_summary.json", "Full payload", "every projection, race and metric"],
    ["projected_table_2026_27.csv", "Projected table", "20 clubs with ranges and probabilities"],
    ["projected_golden_boot_2026_27.csv", "Golden Boot", "player goal projections"],
    ["projected_playmaker_2026_27.csv", "Assists", "creator projections"],
    ["projected_golden_glove_2026_27.csv", "Clean sheets", "keeper projections"],
    ["teams_2026_27.csv", "Club ratings", "attack, defence, Elo, form, live table"],
    ["players_2026_27.csv", "Player ratings", "xG/90, xA/90, minutes, penalties"],
    ["fixtures_2026_27_remaining.csv", "Remaining fixtures", "330 fixtures, real matchweek numbers"],
    ["matches_2025_26.csv", "Training data", "380 matches of 2025–26"],
    ["backtest_2025_26.json", "Backtest report", "the full out-of-sample replay"]
  ];
  $("dataTab").innerHTML = `<div class="grid g3" style="gap:12px">${files.map(([f, t, s], i) => `
    <a class="tile rv" style="--d:${i*40}ms; text-decoration:none; color:inherit" href="api/download/${f}" download>
      <div class="k">${t}</div>
      <div class="disp" style="font-size:13px; margin-top:7px; color:var(--pitch)">${f}</div>
      <div class="sub">${s}</div>
    </a>`).join("")}</div>
    <div class="note" style="margin-top:14px">
      Downloads need the Python server running (<code>PORT=8000 python3 server.py</code>); everything on
      screen works without it, using the embedded payload and a client-side structural Monte Carlo.
    </div>`;
}

/* ═══════════ BOOT ═══════════ */
function renderAll(){
  renderHeader(); renderTicker(); renderHero(); renderHeadTiles(); renderGW(); renderRaceBars(); renderPulse();
  renderMarquee(); renderTable(); renderMarkets(); renderTop6Rings();
  renderAwardTiles(); renderAwards(); wireAwardSearch(); renderDuelSelects(); renderScenarioForm();
  renderMetrics(); renderCharts(); renderBacktest(); renderArch(); renderLimits(); renderModelCard(); renderFreshness(); renderDataTab();
  renderScenarioAwards();
  animate(document);
  armGlow(document);
  applyAwardFilter();
  if(typeof UX !== "undefined"){ UX.refresh(); UX.refreshTilt(); }
}
async function useServerPayload(){
  try{
    const r = await fetch("api/baseline", { cache:"no-store" });
    if(!r.ok) return;
    const j = await r.json();
    if(!j || !j.table_projections) return;
    const diff = Math.abs(j.table_projections[0].proj_pts - DATA.table_projections[0].proj_pts);
    if(diff > 0.05 || (j.meta.n_simulations || 0) !== (DATA.meta.n_simulations || 0)){
      DATA = j; renderAll(); animate(document);
      toast("Loaded a fresher projection from the running model server.");
    }
  }catch(e){}
}
/* ═══════════ DATA FRESHNESS (P9.4) ═══════════ */
function renderFreshness(){
  const host = $("freshness");
  if(!host) return;
  const asOf = (DATA.meta && DATA.meta.as_of_date) || "";
  const m = String(asOf).match(/(\d{4})-(\d{2})-(\d{2})/);
  if(!m){ host.innerHTML = ""; return; }
  const stamped = new Date(+m[1], +m[2] - 1, +m[3]);
  const today = new Date();
  const days = Math.floor((new Date(today.getFullYear(), today.getMonth(), today.getDate()) - stamped) / 86400000);
  // The pipeline runs weekly, so a gap of up to a week is normal and a fortnight is not. The point is
  // not to alarm on schedule — it is to never quietly present month-old numbers as this week's.
  const weekly = 8;
  const stale = days > weekly;
  const label = days <= 0 ? "updated today"
    : days === 1 ? "updated yesterday"
    : `data ${days} days old`;
  host.className = "fresh" + (stale ? " stale" : "");
  host.innerHTML = `<span class="dot" aria-hidden="true"></span>${esc(label)}`
    + (stale ? ` <b>· the weekly update may have failed</b>` : "");
  host.title = `Predictions built from results up to ${esc(String(asOf))}${stale
    ? ". The weekly job should have refreshed this by now — treat the numbers as a snapshot, not the current state of the league."
    : ". The pipeline refreshes after the last match of each gameweek."}`;
}

/* ═══════════ FOLLOW YOUR CLUBS, AND WHAT YOU SAVED (P8.1, P8.2) ═══════════
   All of this is local: the store keeps a small blob in this browser and sends nothing anywhere.
   The rule the whole feature follows is that a reader who has never starred anything must not notice
   it exists — no empty panels, no "0 clubs followed" chrome, no filter that hides the fixtures they
   came to see. */

const STORE = (typeof window !== "undefined" && window.NT90_STORE) || null;
let MINE_ONLY = false;

function followedClubs(){
  return STORE ? STORE.favourites() : [];
}

function starButton(code, label){
  const on = followedClubs().indexOf(code) !== -1;
  return `<button class="star${on ? " on" : ""}" data-follow="${code}"
      aria-pressed="${on ? "true" : "false"}"
      aria-label="${on ? "Stop following" : "Follow"} ${esc(label)}"
      title="${on ? "Stop following" : "Follow"} ${esc(label)}"><span aria-hidden="true">${on ? "★" : "☆"}</span></button>`;
}

function wireStars(root){
  (root || document).querySelectorAll("[data-follow]").forEach(btn => {
    btn.onclick = (e) => {
      e.stopPropagation();               // the star sits inside a row that is itself clickable
      e.preventDefault();
      if(!STORE) return;
      STORE.toggleFavourite(btn.dataset.follow);
      const now = STORE.follows(btn.dataset.follow);
      renderFollowState();
      toast(`${TEAM_LABEL[btn.dataset.follow] || btn.dataset.follow} ${now ? "followed" : "unfollowed"}` +
            (now ? " — their fixtures are marked on the Matchweek view." : "."));
    };
  });
}

/* Everything that depends on who the reader follows, in one place: the stars, the gameweek marks,
   the filter button and the personalised note. Called on every change rather than patched piecemeal,
   so the four can never disagree about what is followed. */
function renderFollowState(){
  const mine = followedClubs();
  document.querySelectorAll("[data-follow]").forEach(btn => {
    const on = mine.indexOf(btn.dataset.follow) !== -1;
    const label = TEAM_LABEL[btn.dataset.follow] || btn.dataset.follow;
    btn.classList.toggle("on", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.setAttribute("aria-label", (on ? "Stop following " : "Follow ") + label);
    btn.title = (on ? "Stop following " : "Follow ") + label;
    const glyph = btn.querySelector("span");
    if(glyph) glyph.textContent = on ? "★" : "☆";
  });

  const toggle = $("myClubsToggle");
  if(toggle){
    toggle.hidden = mine.length === 0 && !MINE_ONLY;
    toggle.classList.toggle("on", MINE_ONLY);
    toggle.setAttribute("aria-pressed", MINE_ONLY ? "true" : "false");
    toggle.innerHTML = (MINE_ONLY ? "★ My clubs only" : "☆ My clubs") +
      ` <span class="k" aria-hidden="true">${mine.length}</span>`;
    toggle.title = mine.length
      ? (MINE_ONLY ? "Show every fixture again" : `Show only the ${mine.length} club${mine.length === 1 ? "" : "s"} you follow`)
      : "Star clubs on the Table view to filter this gameweek";
  }

  // The fixture cards: mark the ones involving a followed club, and hide the rest when filtering.
  const grid = $("gwGrid");
  if(grid){
    let shown = 0;
    grid.querySelectorAll(".fx").forEach(card => {
      const involves = mine.indexOf(card.dataset.home) !== -1 || mine.indexOf(card.dataset.away) !== -1;
      card.classList.toggle("mine", involves);
      const hide = MINE_ONLY && !involves;
      card.hidden = hide;
      if(!hide) shown++;
    });
    const note = $("gwMineNote");
    if(note){
      if(mine.length === 0){
        note.hidden = true;
      } else {
        note.hidden = false;
        const total = (DATA.gw6_predictions || []).length;
        note.innerHTML = MINE_ONLY
          ? `Showing <b>${shown}</b> of ${total} fixtures — the ${mine.length} club${mine.length === 1 ? "" : "s"} you follow.
             <button class="linkbtn" id="mineShowAll">Show all</button>`
          : `${mine.map(c => esc(TEAM_LABEL[c] || c)).join(", ")} — followed, so their fixtures are marked.
             <button class="linkbtn" id="mineOnlyBtn">Show only mine</button>`;
        const off = $("mineShowAll"), on = $("mineOnlyBtn");
        if(off) off.onclick = () => { MINE_ONLY = false; renderFollowState(); };
        if(on) on.onclick = () => { MINE_ONLY = true; renderFollowState(); };
      }
    }
  }

  // The standings carry a "followed" tint, so the table answers "where are my clubs" at a glance.
  document.querySelectorAll("#fullTable tr[data-code]").forEach(tr => {
    tr.classList.toggle("mine", mine.indexOf(tr.dataset.code) !== -1);
  });
}

/* ── saved scenarios (P8.2) ──────────────────────────────────────────────────────────────────── */
function scenarioSummary(sc){
  const s = sc || {};
  const parts = [];
  const inj = Object.values(s.player_injuries || {}).filter(v => v > 0).length;
  const form = Object.values(s.team_boosts || {}).filter(b => b && (b.attack || b.defence)).length;
  const ded = Object.values(s.points_deductions || {}).filter(v => v > 0).length;
  const forced = Object.keys(s.custom_scores || {}).length;
  if(inj) parts.push(`${inj} injured`);
  if(form) parts.push(`${form} form change${form === 1 ? "" : "s"}`);
  if(ded) parts.push(`${ded} deduction${ded === 1 ? "" : "s"}`);
  if(forced) parts.push(`${forced} forced result${forced === 1 ? "" : "s"}`);
  return parts.length ? parts.join(" · ") : "empty scenario";
}

function shortWhen(iso){
  const d = new Date(iso);
  if(isNaN(d.getTime())) return "earlier";
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  if(days <= 0) return "today";
  if(days === 1) return "yesterday";
  if(days < 30) return `${days} days ago`;
  return d.toISOString().slice(0, 10);
}

function renderSavedScenarios(){
  const host = $("savedList");
  if(!host || !STORE) return;
  const list = STORE.scenarios();
  const state = $("storeState");
  if(state){
    // Say plainly when nothing is being kept: a reader who saves something and finds it gone later
    // deserves to have been told at the time.
    state.textContent = STORE.degraded() ? "not saved on this device" : "saved in this browser";
    state.className = "chip lean" + (STORE.degraded() ? " warn" : "");
    state.title = STORE.degraded()
      ? "This browser is not letting the page store data (private mode, a full quota, or a sandboxed preview), so saves last until you close the tab."
      : "Stored in this browser's local storage. Nothing is sent to a server.";
  }
  if(!list.length){
    host.innerHTML = `<div class="note">Nothing saved yet. Build a scenario above, name it, and hit
      <b>Save current</b> — it will be waiting here next time you open this page.</div>`;
    return;
  }
  host.innerHTML = list.map((e, i) => `
    <div class="saverow rv" style="--d:${Math.min(i * 40, 240)}ms">
      <div class="grow">
        <div class="disp" style="font-size:13.5px">${esc(e.name)}</div>
        <div class="dim" style="font-size:10.5px">${esc(scenarioSummary(e.scenario))} · saved ${esc(shortWhen(e.saved))}</div>
      </div>
      <button class="btn sm" data-load="${e.id}">Load</button>
      <button class="btn sm" data-del="${e.id}" aria-label="Delete ${esc(e.name)}">Delete</button>
    </div>`).join("");
  host.querySelectorAll("[data-load]").forEach(btn => {
    btn.onclick = () => {
      const entry = STORE.scenarios().filter(x => x.id === btn.dataset.load)[0];
      if(!entry) return;
      // A saved scenario is one a link or a form put there earlier, so it is validated on the way
      // back out of storage as well — a save made from a hostile link must not become a payload that
      // fires on every subsequent visit.
      SCENARIO = sanitizeScenario(entry.scenario);
      renderScenarioForm();
      toast(`Loaded "${entry.name}" — running it now.`);
      runSim();
    };
  });
  host.querySelectorAll("[data-del]").forEach(btn => {
    btn.onclick = () => {
      STORE.deleteScenario(btn.dataset.del);
      renderSavedScenarios();
      toast("Scenario deleted.");
    };
  });
}

function wireSavedScenarios(){
  const save = $("saveScen");
  if(save && STORE){
    save.onclick = () => {
      if(!SCENARIO_ACTIVE()){ toast("Nothing to save yet — change an injury, a form slider or a result first."); return; }
      const nameField = $("scenName");
      const entry = STORE.saveScenario(nameField.value, SCENARIO);
      nameField.value = "";
      renderSavedScenarios();
      toast(STORE.degraded()
        ? `"${entry.name}" saved for this session — this browser is not storing data.`
        : `Saved "${entry.name}".`);
    };
  }
  const forget = $("forgetAll");
  if(forget) forget.onclick = () => {
    if(STORE) STORE.clear();
    MINE_ONLY = false;
    renderSavedScenarios();
    renderFollowState();
    toast("Cleared everything saved on this device — followed clubs and scenarios.");
  };
  const toggle = $("myClubsToggle");
  if(toggle) toggle.onclick = () => { MINE_ONLY = !MINE_ONLY; renderFollowState(); };
}

/* ═══════════ THE MODEL CARD (P9.1) ═══════════ */
function renderModelCard(){
  const host = $("modelCard");
  if(!host) return;
  // `BT` is the backtest payload, defined at the top of this file as `const BT = BACKTEST`. The first
  // version of this function read `DATA.backtest`, which does not exist — the payload carries the
  // backtest as its own top-level object, not inside DATA — and the card rendered a set of em dashes
  // where the accuracy should be. A test that asserted `"DATA.backtest" in source` passed anyway,
  // because it was checking that the wrong code was present rather than that the right numbers were.
  const m = (BT && BT.model) || null;
  const tl = (BT && BT.table_level) || null;
  const b = (BT && BT.baselines) || {};
  const homeBase = b["home_win_always (PL base rates)"] || null;
  const asOf = (DATA.meta && DATA.meta.as_of_date) || "unknown";
  const sims = (DATA.meta && DATA.meta.n_simulations) || 0;
  const skill = (BT && BT.skill_vs_prior_table) || null;

  host.innerHTML = `
    <p class="body">NINETY+ <b>is a statistical model, not a tipster</b>. It knows the results so far,
    the strength of every squad, home advantage and the fixture list — nothing else. It has no access to
    team news, injuries, transfer gossip or a manager's mood, and it cannot predict a bad afternoon.</p>

    <div class="mcfacts">
      <div><span class="k">What it is</span><b>Dixon-Coles scoreline model + gradient boosting</b>
        <span class="sm">Goal expectations per fixture, then ${sims.toLocaleString()} simulated seasons.</span></div>
      <div><span class="k">Measured on 2025-26</span>
        <b>${m ? m.accuracy.toFixed(1) + "% of matches called" : "—"}</b>
        <span class="sm">${m ? "Log-loss " + m.log_loss.toFixed(3) + " · Brier " + m.brier.toFixed(3) : ""}
          ${skill ? " · RPS skill +" + skill.rps.toFixed(1) + "% vs the prior table" : ""}</span></div>
      <div><span class="k">Where it does not help</span>
        <b>Table position, not match results</b>
        <span class="sm">${tl ? "Rank correlation " + tl.spearman_rank_correlation.toFixed(2) + " · points error ±" + tl.points_mae.toFixed(1) : ""}</span></div>
      <div><span class="k">Updated</span><b>Weekly, after the last match of each gameweek</b>
        <span class="sm">This build: ${esc(String(asOf))}</span></div>
    </div>

    <p class="disclaim"><b>Analysis, not betting advice.</b> Every number here is the output of a model
    that gets roughly half of individual matches right — about ${homeBase ? (homeBase.accuracy || 0).toFixed(1) : "—"}% of
    fixtures are won by the home side before anyone looks at the teams. Treat a 70% favourite as one
    match in three going the other way, because that is what it means.</p>
    <p class="sm dim">Wrong result? <a href="method.html" style="color:var(--accent);text-decoration:underline;text-underline-offset:2px">How the model is built</a>
    explains the method and how to report a miss.</p>`;
}

function wireControlNames(){
  /* P7.3: controls that are obvious on screen and anonymous to a screen reader. The simulation-size
     select is the clearest case — it reads as "combo box" and nothing else, and it changes how long a
     run takes, so its name has to say what it sets. */
  const sim = $("simCount");
  if(sim){
    sim.setAttribute("aria-label", "Simulations per run");
    const help = document.createElement("span");
    help.id = "simCountHelp";
    help.className = "off";
    help.textContent = "More simulations make the probabilities steadier and the run slower.";
    sim.setAttribute("aria-describedby", help.id);
    sim.insertAdjacentElement("afterend", help);
  }
}

function init(){
  document.querySelectorAll("nav.tabs button").forEach(b => b.onclick = () => switchTab(b.dataset.tab));
  document.querySelectorAll("[data-award]").forEach(b => b.onclick = () => { AWARD = b.dataset.award; renderAwards(); animate($("tab-awards")); });
  $("fxGo").onclick = predictFixture;
  $("fxHome").onchange = predictFixture; $("fxAway").onchange = predictFixture;
  $("runSim").onclick = runSim;
  $("resetScen").onclick = resetScenario;
  wireControlNames();
  wireSavedScenarios();
  renderAll();
  renderSavedScenarios();
  if(typeof UX !== "undefined") UX.init();
  detectEngine().then(() => { if(ENGINE_MODE === "server"){ predictFixture(); useServerPayload(); } });
}
init();
