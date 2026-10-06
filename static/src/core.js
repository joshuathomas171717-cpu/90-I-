/* ═══════════════════════════════════════════════════════════════════════════
   CORE — data access, model math, scenario state, engine bridge
   The maths here is the same validated engine as the Python side: structural
   attack×defence λ, Dixon-Coles low-score correction, calendar-calibrated scale.
   ═══════════════════════════════════════════════════════════════════════════ */

let DATA = EMBEDDED.baseline;
const BASELINE = EMBEDDED.baseline;
const TEAMS_IN = EMBEDDED.inputs.teams;
const FIXTURES_IN = EMBEDDED.inputs.fixtures;
const LAMBDA_SCALE = (BASELINE.meta && BASELINE.meta.lambda_scale) || 0.95;
const BACKTEST = EMBEDDED.backtest || null;
const EXTRAS = EMBEDDED.club_extras || {};
const H2H = EMBEDDED.h2h || {};
const PLAYER_LAYER = EMBEDDED.player_layer || { players:[], by_gameweek:{}, coverage:{} };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pct = (v) => (v === undefined || v === null ? "—" : Number(v).toFixed(1) + "%");
const num1 = (v) => (v === undefined || v === null ? "—" : Number(v).toFixed(1));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

const TEAM_LABEL = {}, TEAM_COLOR = {}, TEAM_NAME = {}, TEAM_BY_CODE = {};
TEAMS_IN.forEach(t => { TEAM_LABEL[t.code] = t.short; TEAM_COLOR[t.code] = t.color; TEAM_NAME[t.code] = t.name; TEAM_BY_CODE[t.code] = t; });

function toast(msg, ms = 3400){
  const t = $("toast"); t.textContent = msg; t.classList.add("on");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), ms);
}
function posClass(p){ return p <= 5 ? "pos ucl" : p <= 7 ? "pos uel" : p >= 18 ? "pos rel" : "pos"; }
function formStreak(form){
  if(!form) return "";
  return `<span class="form">${[...form].slice(-5).map(c =>
    `<i class="${c === "W" ? "W" : c === "D" ? "D" : "L"}">${c}</i>`).join("")}</span>`;
}
function deltaTag(cur, proj){
  const d = cur - proj;
  if(d > 0) return `<span class="delta up">▲${d}</span>`;
  if(d < 0) return `<span class="delta down">▼${Math.abs(d)}</span>`;
  return `<span class="delta flat">—</span>`;
}
/* outcome → accent + label */
function outcomeOf(p){
  const m = Math.max(p.prob_home, p.prob_draw, p.prob_away);
  if(m === p.prob_home) return { key:"h", label:`${TEAM_LABEL[p.home] || p.home} win`, color:"var(--pitch)", prob:p.prob_home };
  if(m === p.prob_away) return { key:"a", label:`${TEAM_LABEL[p.away] || p.away} win`, color:"var(--magi)", prob:p.prob_away };
  return { key:"d", label:"Draw", color:"var(--draw)", prob:p.prob_draw };
}
/* certainty tier — powers the "sense it without reading" chips.
   P9.1: the words are the model's confidence, not a betting slip. "Banker" is bookmaker language for a
   sure thing, which is a claim this model cannot make — it gets about half of individual matches right.
   "Clear favourite" says the same thing about the probabilities without borrowing the bookie's voice.
   P7.4: each tier also carries a one-letter mark, because a chip that only means "green" or "orange"
   says nothing to a reader who cannot separate those two colours. */
function tierOf(p){
  const m = Math.max(p.prob_home, p.prob_draw, p.prob_away);
  if(m >= 65) return { cls:"banker", txt:"clear favourite", mark:"F" };
  if(m < 40) return { cls:"toss", txt:"toss-up", mark:"T" };
  if(m >= 52) return { cls:"upset", txt:"edge", mark:"E" };
  return { cls:"lean", txt:"lean", mark:"L" };
}

/* ─── club identity: inline SVG crests (no external assets) ─── */
function crest(code, size = 26){
  const t = TEAM_BY_CODE[code] || {};
  const ex = EXTRAS[code] || {};
  const c1 = t.color || "#334", c2 = ex.secondary || "#ffffff";
  const pat = ex.pattern || "plain";
  const id = "cf" + code + size;
  const initials = (code || "").replace(/[^A-Za-z]/g, "").slice(0, 3).toUpperCase();
  let inner = `<rect x="0" y="0" width="24" height="30" fill="${c1}"/>`;
  if(pat === "stripes") inner = `<rect width="24" height="30" fill="${c1}"/>` +
    [3,9,15,21].map(x => `<rect x="${x}" y="0" width="3" height="30" fill="${c2}"/>`).join("");
  else if(pat === "halves") inner = `<rect width="12" height="30" fill="${c1}"/><rect x="12" width="12" height="30" fill="${c2}"/>`;
  else if(pat === "hoops") inner = `<rect width="24" height="30" fill="${c1}"/>` +
    [4,12,20].map(y => `<rect y="${y}" width="24" height="3.4" fill="${c2}"/>`).join("");
  else if(pat === "sash") inner = `<rect width="24" height="30" fill="${c1}"/><path d="M-2 24 L14 4 L24 4 L0 30 Z" fill="${c2}" opacity=".85"/>`;
  else if(pat === "chest") inner = `<rect width="24" height="30" fill="${c1}"/><rect y="12" width="24" height="7" fill="${c2}" opacity=".9"/>`;
  else if(pat === "shoulders") inner = `<rect width="24" height="30" fill="${c1}"/><path d="M0 0 H24 V8 C18 13 6 13 0 8 Z" fill="${c2}" opacity=".9"/>`;
  return `<svg class="crest" width="${size}" height="${size * 1.24}" viewBox="0 0 24 30" aria-hidden="true">
    <defs>
      <clipPath id="${id}"><path d="M0 2.5 A2.5 2.5 0 0 1 2.5 0 H21.5 A2.5 2.5 0 0 1 24 2.5 V15 C24 23 16 27.5 12 30 C8 27.5 0 23 0 15 Z"/></clipPath>
      <linearGradient id="g${id}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#fff" stop-opacity=".22"/><stop offset=".55" stop-color="#fff" stop-opacity="0"/>
        <stop offset="1" stop-color="#000" stop-opacity=".3"/>
      </linearGradient>
    </defs>
    <g class="sh">
      <g clip-path="url(#${id})">${inner}<rect width="24" height="30" fill="url(#g${id})"/></g>
      <path d="M0 2.5 A2.5 2.5 0 0 1 2.5 0 H21.5 A2.5 2.5 0 0 1 24 2.5 V15 C24 23 16 27.5 12 30 C8 27.5 0 23 0 15 Z"
        fill="none" stroke="rgba(255,255,255,.38)" stroke-width="1"/>
      <text x="12" y="14.8" text-anchor="middle" font-family="Archivo,system-ui" font-weight="900" font-size="7.2"
        fill="#fff" style="paint-order:stroke" stroke="rgba(0,0,0,.4)" stroke-width="1.6">${esc(initials)}</text>
    </g>
  </svg>`;
}

/* ─── head-to-head from real played matches (2025-26 + 2026-27) ─── */
function h2hFor(h, a){
  const key = h + "-" + a;
  const recs = H2H[key] || [];
  let hw = 0, d = 0, aw = 0;
  recs.forEach(r => { if(r[2] > r[3]) hw++; else if(r[2] < r[3]) aw++; else d++; });
  return { recs, hw, d, aw };
}

/* ═══════════ model maths ═══════════ */
function structuralLambda(hc, ac){
  const h = TEAM_BY_CODE[hc], a = TEAM_BY_CODE[ac];
  const lh = h.xg * (a.xga / 1.28) * (1 + 0.5 * h.home_adv) * LAMBDA_SCALE;
  const la = a.xg * (h.xga / 1.28) * (1 - 0.35 * h.home_adv) * LAMBDA_SCALE;
  return [clamp(lh, 0.35, 3.8), clamp(la, 0.25, 3.4)];
}
function poissonPmf(k, l){ let s = 0; for(let i = 0; i < k; i++) s -= Math.log(i + 1); return Math.exp(-l + k * Math.log(l) + s); }
function dcMatrix(lh, la, n = 6, rho = -0.11){
  const mat = [];
  for(let i = 0; i <= n; i++){ mat.push([]);
    for(let j = 0; j <= n; j++){
      let v = poissonPmf(i, lh) * poissonPmf(j, la);
      if(i === 0 && j === 0) v *= (1 - lh * la * rho);
      else if(i === 0 && j === 1) v *= (1 + lh * rho);
      else if(i === 1 && j === 0) v *= (1 + la * rho);
      else if(i === 1 && j === 1) v *= (1 - rho);
      mat[i].push(Math.max(0, v));
    }}
  const tot = mat.reduce((a, r) => a + r.reduce((x, y) => x + y, 0), 0);
  return mat.map(r => r.map(v => v / tot));
}
const sumLower = m => m.reduce((a, r, i) => a + r.reduce((s, v, j) => s + (i > j ? v : 0), 0), 0);
const sumUpper = m => m.reduce((a, r, i) => a + r.reduce((s, v, j) => s + (i < j ? v : 0), 0), 0);
const sumDiag = m => m.reduce((a, r, i) => a + r[i], 0);

function localFixturePredict(hc, ac){
  const [lh, la] = structuralLambda(hc, ac);
  const mat = dcMatrix(lh, la);
  const ph = sumLower(mat), pd = sumDiag(mat), pa = sumUpper(mat);
  const scores = [];
  for(let i = 0; i < mat.length; i++) for(let j = 0; j < mat[i].length; j++) scores.push({ h:i, a:j, p:mat[i][j] });
  scores.sort((x, y) => y.p - x.p);
  return {
    home: hc, away: ac, home_name: TEAM_NAME[hc] || hc, away_name: TEAM_NAME[ac] || ac,
    lambda_home: +lh.toFixed(2), lambda_away: +la.toFixed(2),
    prob_home: +(ph * 100).toFixed(1), prob_draw: +(pd * 100).toFixed(1), prob_away: +(pa * 100).toFixed(1),
    clean_sheet_home: +(mat.map(r => r[0]).reduce((a, b) => a + b, 0) * 100).toFixed(1),
    clean_sheet_away: +(mat[0].reduce((a, b) => a + b, 0) * 100).toFixed(1),
    btts_prob: +((1 - mat[0].reduce((a, b) => a + b, 0) - mat.map(r => r[0]).reduce((a, b) => a + b, 0) + mat[0][0]) * 100).toFixed(1),
    over_2_5_prob: +(mat.reduce((acc, row, i) => acc + row.reduce((s, v, j) => s + (i + j >= 3 ? v : 0), 0), 0) * 100).toFixed(1),
    top_scorelines: scores.slice(0, 6).map(s => ({ score:`${s.h}-${s.a}`, home_goals:s.h, away_goals:s.a, prob:+(s.p * 100).toFixed(1) })),
    matrix_5x5: mat.slice(0, 5).map(r => r.slice(0, 5).map(v => +(v * 100).toFixed(2))),
    features_breakdown: null
  };
}
/* the model's reasoning, decomposed — shown in the duel, not hidden in a tooltip */
function reasoning(p){
  const h = TEAM_BY_CODE[p.home], a = TEAM_BY_CODE[p.away];
  const rows = [];
  const push = (label, hV, aV, fmt, note) => {
    const hv = hV, av = aV;
    rows.push({ label, h:hv, a:av, fmt, note, edge: hv > av ? "h" : av > hv ? "a" : "even" });
  };
  push("Attack (xG/90, live)", h.xg, a.xg, v => v.toFixed(2));
  push("Defence (xGA/90 — lower is better)", -h.xga, -a.xga, v => Math.abs(v).toFixed(2));
  push("Elo rating", h.elo, a.elo, v => Math.round(v));
  push("Form (points per game)", h.ppg, a.ppg, v => v.toFixed(2));
  push("Squad value (£m)", TEAM_BY_CODE[p.home].value_m || 0, TEAM_BY_CODE[p.away].value_m || 0, v => Math.round(v));
  push("Home-ground factor", (h.home_adv || 0) * 100, 0, v => (v > 0 ? "+" + v.toFixed(0) + "%" : "—"));
  return rows;
}
function blankLambda(P){ return [P[0], P[1]]; }

/* ═══════════ engine bridge ═══════════ */
let ENGINE_MODE = "offline";
let SCENARIO = { player_injuries:{}, team_boosts:{}, points_deductions:{}, custom_scores:{} };
let SIM_RESULT = null;
let AWARD = "gb";
let SCEN_AWARD = "gb";
let LAST_FIXTURE = null;
let RENDER_STATE = { awardsPodium:false };

async function detectEngine(){
  try{
    const r = await fetch("api/baseline", { cache:"no-store" });
    if(r.ok){
      const j = await r.json();
      if(j && j.table_projections){ ENGINE_MODE = "server"; }
    }
  }catch(e){ /* opened as a file:// — offline engine takes over */ }
  paintMode();
}
function paintMode(){
  const el = $("modeChip"); if(!el) return;
  const offline = ENGINE_MODE !== "server";
  el.innerHTML = offline
    ? `<span class="dot" style="background:var(--gold)"></span> offline preview`
    : `<span class="dot"></span> live engine`;
  el.title = offline
    ? "No API behind this deployment — the model runs in your browser"
    : "Served by the Python API on this host";
  // The What-If tab says the same thing in its own words, where a reader who is about to press
  // "Re-simulate season" will actually see it. A header chip alone is easy to miss, and "why is
  // this page not talking to a server?" deserves an answer next to the button that would use one.
  const note = $("engineNote");
  if(note) note.hidden = !offline;
}

async function predictFixture(){
  const hc = $("fxHome").value, ac = $("fxAway").value;
  if(hc === ac){ toast("Pick two different clubs."); return; }
  $("fxResult").innerHTML = `<div class="panel"><div class="skel" style="width:60%"></div>
    <div class="skel" style="margin-top:12px; width:35%"></div>
    <div class="note" style="margin-top:14px">reading the Dixon-Coles grid…</div></div>`;
  let p = null;
  if(ENGINE_MODE === "server"){
    try{
      const r = await fetch(`api/fixture?home=${hc}&away=${ac}`, { cache:"no-store" });
      if(r.ok) p = await r.json();
    }catch(e){}
  }
  if(!p){ p = localFixturePredict(hc, ac); p._offline = true; }
  LAST_FIXTURE = p;
  renderDuel(p);
}

/* ═══════════ scenario desk ═══════════ */
const SCEN_PLAYERS = () => EMBEDDED.inputs.players.concat(EMBEDDED.inputs.gks);
function scenarioInputTemplates(){
  const teamsSorted = [...TEAMS_IN].sort((a, b) => a.short.localeCompare(b.short));
  const keyPlayers = ["haaland","saka","isak","bruno","palmer","raya","donnarumma","wirtz"];
  const pl = SCEN_PLAYERS();
  const flagged = keyPlayers.map(id => pl.find(p => p.player_id === id)).filter(Boolean);
  return { teamsSorted, players:pl.sort((a,b) => a.club.localeCompare(b.club) || a.name.localeCompare(b.name)) };
}
function SCENARIO_ACTIVE(){
  return Object.values(SCENARIO.player_injuries).some(v => v > 0) ||
         Object.values(SCENARIO.team_boosts).some(b => (b.attack || 0) !== 0 || (b.defence || 0) !== 0) ||
         Object.values(SCENARIO.points_deductions).some(v => v > 0) ||
         Object.keys(SCENARIO.custom_scores).length > 0;
}
/* ═══════════ scenario validation ═══════════ */
/*
 * There are three ways a scenario can arrive from outside this page: a `#s=` share link, an entry
 * in local storage, and — in future — a sync. All three are attacker-controlled in the sense that
 * matters: anyone can put anything in a URL, and the page hands it straight to a form that renders
 * it.
 *
 * It used to hand it over untouched, and that was a cross-site scripting bug. A link of the form
 *
 *     /whatif#s=<base64 of {"b":{"ARS":["<img src=x onerror=...>",0]}}>
 *
 * put that string into the Form-swings slider's `value="…"` attribute, broke out of the quotes and
 * ran script on this origin. Injuries, deductions and boost values were all reachable the same way.
 *
 * So a scenario is now normalised at the boundary: four maps of numbers, keyed only by ids the page
 * already knows. Anything else is dropped, not escaped — a scenario has no reason to contain a
 * string, so the correct response to one is to discard it rather than to render it carefully.
 *
 * The form additionally coerces every value it prints (see `scnNum` in render.js). That second layer
 * is deliberate redundancy: this function is the fix, and the coercion is what keeps a future bug
 * here from becoming a future XSS.
 */
function scnInt(v, lo, hi){
  const n = Math.round(Number(v));
  if(!isFinite(n)) return 0;              // Number("") is 0, Number({}) is NaN, Number("12x") is NaN
  return Math.max(lo, Math.min(hi, n));
}

/** How old is this page — and, more to the point, is it *behind*?
 *
 * P11.1. The old rule was a fixed threshold: flag the page when its data was more than eight days
 * old. That is true but it under-states the problem, because eight days is not the unit that matters.
 * The unit that matters is the gameweek. If the numbers do not include matchweek 6 and matchweek 6
 * finished three days ago, the site is out of date however recent the stamp looks — and a reader has
 * no way to know that from a date, because they do not carry the fixture calendar in their head.
 *
 * So the calendar ships with the page (`EMBEDDED.schedule`, from the same parser the iCal feed uses)
 * and this decides, per load, which of three honest states the page is in:
 *
 *   ok      — the next gameweek has not started; these numbers are current.
 *   due     — a gameweek is being played right now. Numbers cannot include results that do not exist
 *             yet, so this is not a failure, and it says what will happen and when.
 *   behind  — a gameweek has finished and the data still starts from before it. The weekly refresh
 *             has not run. Say so plainly, name the gameweek, and stop presenting the numbers as the
 *             current state of the league.
 *
 * Pure on purpose: `now` is a parameter, so the behaviour at any date can be tested without waiting
 * for that date, and `schedule` is a plain {gameweek: [start, dayAfterEnd]} object.
 */
function freshness(asOfISO, schedule, nextGw, now){
  const stamp = String(asOfISO || "").match(/(\d{4})-(\d{2})-(\d{2})/);
  const today = now instanceof Date ? now : new Date();
  const midnight = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const days = stamp
    ? Math.floor((midnight - new Date(+stamp[1], +stamp[2] - 1, +stamp[3])) / 86400000)
    : null;
  const label = days === null ? "" : days <= 0 ? "updated today"
    : days === 1 ? "updated yesterday" : `data ${days} days old`;

  const table = schedule && typeof schedule === "object" ? schedule : null;
  if(!table || !stamp){
    // No calendar (an older build, or a hand-opened file): fall back to the rule this replaced. Blunt
    // is better than silent — the page still refuses to present month-old numbers as this week's.
    const stale = days !== null && days > 8;
    return { level: stale ? "behind" : "ok", days, label,
             detail: stale ? "The weekly update should have refreshed this by now — treat the numbers "
                           + "as a snapshot, not the current state of the league." : "" };
  }

  const weeks = Object.keys(table).map(Number).sort((a, b) => a - b);
  const start = weeks.find(gw => nextGw === undefined || gw >= nextGw) ?? weeks[0];
  // Finished gameweeks: the day after their last fixture has arrived.
  const finished = weeks.filter(gw => {
    const end = table[String(gw)][1];
    return end && new Date(end + "T00:00:00") <= midnight;
  });
  const playing = weeks.find(gw => {
    const [a, b] = table[String(gw)] || [];
    return a && b && new Date(a + "T00:00:00") <= midnight && midnight < new Date(b + "T00:00:00");
  });
  const next = start !== undefined ? table[String(start)] : null;
  const first = next ? new Date(next[0] + "T00:00:00") : null;
  const daysToStart = first ? Math.round((first - midnight) / 86400000) : null;

  if(finished.length){
    // The earliest finished gameweek is the one the data should already contain: `nextGw` is the
    // gameweek these numbers are *for*, so any finished gameweek at or after it has been missed.
    const missed = finished.filter(gw => nextGw === undefined || gw >= nextGw);
    if(missed.length){
      const gw = missed[0];
      const [a, b] = table[String(gw)];
      return { level: "behind", days, label, gameweek: gw, start: a, ended: b,
               detail: `Matchweek ${gw} ran ${a} to ${dayBefore(b)} and these numbers do not include `
                     + `its results — the weekly refresh has not run since ${String(asOfISO).slice(0, 10)}. `
                     + `Everything on this page starts from before that gameweek was played.` };
    }
  }

  if(playing){
    const [a, b] = table[String(playing)];
    return { level: "due", days, label, gameweek: playing, start: a, ended: b,
             detail: `Matchweek ${playing} is being played now (${a} to ${dayBefore(b)}). These numbers `
                   + `cover everything up to the last completed gameweek, and refresh once the weekend `
                   + `is over — this is what the model knew before kickoff, which is the point of it.` };
  }

  if(daysToStart !== null && daysToStart <= 2 && daysToStart >= 0){
    return { level: "ok", days, label, gameweek: start, start: next[0],
             detail: `Matchweek ${start} starts on ${next[0]} — the model's numbers for it are already `
                   + `published, and they are the ones locked in the ledger before kickoff.` };
  }
  return { level: "ok", days, label, gameweek: start, start: next ? next[0] : null, detail: "" };
}

/** '2026-10-13' -> '12 October' — for prose that names when a gameweek ended. */
function dayBefore(iso){
  const m = String(iso || "").match(/(\d{4})-(\d{2})-(\d{2})/);
  if(!m) return "?";
  const dt = new Date(+m[1], +m[2] - 1, +m[3] - 1);
  const months = ["January", "February", "March", "April", "May", "June", "July", "August",
                  "September", "October", "November", "December"];
  return dt.getDate() + " " + months[dt.getMonth()];
}

function sanitizeScenario(raw){
  const src = (raw && typeof raw === "object") ? raw : {};
  const out = { player_injuries:{}, team_boosts:{}, points_deductions:{}, custom_scores:{} };

  const known = Object.create(null);
  TEAMS_IN.forEach(t => { known[t.code] = true; });
  const players = Object.create(null);
  SCEN_PLAYERS().forEach(p => { players[p.player_id] = true; });

  const inj = (src.player_injuries && typeof src.player_injuries === "object") ? src.player_injuries : {};
  Object.keys(inj).forEach(k => {
    if(!players[k]) return;                                   // not a player of this league
    const games = scnInt(inj[k], 0, 33);                      // 33 matches remain in the season
    if(games > 0) out.player_injuries[k] = games;
  });

  const boosts = (src.team_boosts && typeof src.team_boosts === "object") ? src.team_boosts : {};
  Object.keys(boosts).forEach(k => {
    if(!known[k]) return;
    const raw = boosts[k];
    // Two shapes are legitimate here, and getting this wrong is how the first version of this
    // function silently threw away every valid share link: the compact wire format in a link is
    // [attack, defence], while SCENARIO holds {attack, defence} once it is in the page.
    let attack = 0, defence = 0;
    if(Array.isArray(raw)){
      attack = scnInt(raw[0], -25, 25); defence = scnInt(raw[1], -25, 25);
    } else if(raw && typeof raw === "object"){
      attack = scnInt(raw.attack, -25, 25); defence = scnInt(raw.defence, -25, 25);
    } else if(typeof raw === "number" || typeof raw === "string"){
      attack = scnInt(raw, -25, 25);            // a bare number means "attack only"
    }
    if(attack || defence) out.team_boosts[k] = { attack:attack, defence:defence };
  });

  const ded = (src.points_deductions && typeof src.points_deductions === "object") ? src.points_deductions : {};
  Object.keys(ded).forEach(k => {
    if(!known[k]) return;
    const pts = scnInt(ded[k], 0, 30);
    if(pts > 0) out.points_deductions[k] = pts;
  });

  const forced = (src.custom_scores && typeof src.custom_scores === "object") ? src.custom_scores : {};
  Object.keys(forced).forEach(k => {
    const m = /^([A-Z]{2,4})-([A-Z]{2,4})$/.exec(k);          // the key is a fixture, not free text
    if(!m || !known[m[1]] || !known[m[2]]) return;
    const pair = forced[k];
    if(!Array.isArray(pair) || pair.length < 2) return;
    out.custom_scores[k] = [scnInt(pair[0], 0, 9), scnInt(pair[1], 0, 9)];
  });

  if(src.player_effects && typeof NT90_PLAYERS !== "undefined"){
    const frozen = NT90_PLAYERS.validate(src.player_effects, out.player_injuries, TEAMS_IN, SCEN_PLAYERS());
    Object.keys(src.player_effects).forEach(pid => { if(!frozen.profiles[pid]) delete out.player_injuries[pid]; });
    if(Object.keys(frozen.profiles).length) out.player_effects = frozen.profiles;
  }
  return out;
}

function setCustomScore(h, a){
  const key = h + "-" + a;
  const hg = +$("cs_h_" + h + a)?.value, ag = +$("cs_a_" + h + a)?.value;
  if(isNaN(hg) || isNaN(ag)) return;
  SCENARIO.custom_scores[key] = [hg, ag];
  toast(`Forced ${TEAM_LABEL[h]} ${hg}–${ag} ${TEAM_LABEL[a]}`);
  markScenario();
}
function markScenario(){
  const inj = Object.values(SCENARIO.player_injuries).filter(v => v > 0).length;
  const form = Object.values(SCENARIO.team_boosts).filter(b => (b.attack || 0) || (b.defence || 0)).length;
  const ded = Object.values(SCENARIO.points_deductions).filter(v => v > 0).length;
  const forced = Object.keys(SCENARIO.custom_scores).length;
  const badge = (k, v, word) => { const el = document.querySelector(`[data-cnt="${k}"]`); if(el) el.textContent = `${v} ${v === 1 ? word.replace(/s$/, "") : word}`; };
  badge("inj", inj, "active"); badge("form", form, "clubs"); badge("ded", ded, "clubs"); badge("forced", forced, "forced");
  if(typeof renderPlayerEffects === "function") renderPlayerEffects();
  const b = $("runSim"); if(b) b.classList.toggle("has-changes", (inj + form + ded + forced) > 0);
  return inj + form + ded + forced;
}

function poissonDraw(lam, rnd){
  if(lam < 25){
    const L = Math.exp(-lam); let k = 0, p = 1;
    do{ k++; p *= rnd(); } while(p > L);
    return k - 1;
  }
  return Math.max(0, Math.round(lam + Math.sqrt(lam) * (Math.sqrt(-2 * Math.log(rnd())) * Math.cos(2 * Math.PI * rnd()))));
}

/* Client-side structural Monte Carlo — same shape as the Python payload, so every
   panel renders identically whether or not the server is running. */
function localSimulate(scenario, nSims){
  const teams = TEAMS_IN.map(t => ({ ...t }));
  const byCode = {}; teams.forEach(t => byCode[t.code] = t);
  const players = EMBEDDED.inputs.players.map(p => ({ ...p, games_out:0 }));
  const gks = EMBEDDED.inputs.gks.map(p => ({ ...p, games_out:0 }));

  const inj = scenario.player_injuries || {};
  players.concat(gks).forEach(p => {
    const g = Math.max(0, Math.min(33, +(inj[p.player_id] || 0)));
    p.games_out = g;
    if(g > 0 && !(scenario.player_effects && scenario.player_effects[p.player_id])){
      const frac = g / 33, t = byCode[p.club]; if(!t) return;
      if(p.pos === "GK"){ const w = Math.max(0.05, (p.gk_psxg_diff + 2) * 0.03); t.xga *= (1 + w * frac); t.elo -= 25 * w * frac; }
      else { const w = (p.xg_90 + 0.8 * p.xa_90) * 0.16; t.xg *= (1 - w * frac); t.elo -= 42 * w * frac; }
    }
  });
  const remaining = Object.create(null);
  FIXTURES_IN.forEach(([h,a]) => { remaining[h]=(remaining[h]||0)+1; remaining[a]=(remaining[a]||0)+1; });
  const frozenEffects = typeof NT90_PLAYERS !== "undefined" ? NT90_PLAYERS.clubEffects(scenario.player_effects || {}, inj, remaining) : {};
  Object.entries(frozenEffects).forEach(([club, effect]) => {
    const team = byCode[club]; if(!team) return;
    team.xg *= 1-effect.attack/100; team.xga *= 1+effect.defence/100;
  });
  Object.entries(scenario.team_boosts || {}).forEach(([c, b]) => {
    const t = byCode[c]; if(!t) return;
    t.xg *= (1 + (b.attack || 0) / 100); t.xga *= (1 - (b.defence || 0) / 100);
    t.elo += ((b.attack || 0) + (b.defence || 0)) * 0.85;
  });

  const fixtures = FIXTURES_IN.map(([h, a]) => ({ h, a }));
  const lam = fixtures.map(f => {
    const H = byCode[f.h], A = byCode[f.a];
    return { lh:clamp(H.xg * (A.xga / 1.28) * (1 + 0.5 * H.home_adv), 0.35, 3.8),
             la:clamp(A.xg * (H.xga / 1.28) * (1 - 0.35 * H.home_adv), 0.25, 3.4) };
  });
  lam.forEach(x => { x.lh *= LAMBDA_SCALE; x.la *= LAMBDA_SCALE; });
  const remXg = {}, remXga = {}, remCs = {};
  teams.forEach(t => { remXg[t.code] = 0; remXga[t.code] = 0; remCs[t.code] = 0; });
  fixtures.forEach((f, i) => {
    remXg[f.h] += lam[i].lh; remXga[f.h] += lam[i].la; remXg[f.a] += lam[i].la; remXga[f.a] += lam[i].lh;
    remCs[f.h] += Math.exp(-lam[i].la); remCs[f.a] += Math.exp(-lam[i].lh);
  });

  const codes = teams.map(t => t.code), idx = {}; codes.forEach((c, i) => idx[c] = i);
  const N = teams.length;
  const tot = teams.map(t => ({ pts:t.curr_pts, gf:t.curr_gf, ga:t.curr_ga, w:t.curr_w, d:t.curr_d, l:t.curr_l }));
  Object.entries(scenario.points_deductions || {}).forEach(([c, d]) => { if(idx[c] !== undefined) tot[idx[c]].pts -= (d || 0); });

  const posCount = teams.map(() => new Array(N).fill(0));
  const ptsSamples = teams.map(() => []);
  const goalsSim = Array.from({ length:players.length }, () => []);
  const assistsSim = Array.from({ length:players.length }, () => []);
  const csSim = Array.from({ length:gks.length }, () => []);
  const rnd = Math.random;

  for(let s = 0; s < nSims; s++){
    const simTot = tot.map(t => ({ ...t }));
    fixtures.forEach((f, i) => {
      let hg, ag;
      const forced = scenario.custom_scores && scenario.custom_scores[f.h + "-" + f.a];
      if(forced){ hg = forced[0]; ag = forced[1]; }
      else { hg = poissonDraw(lam[i].lh, rnd); ag = poissonDraw(lam[i].la, rnd); }
      const hi = idx[f.h], ai = idx[f.a];
      simTot[hi].gf += hg; simTot[hi].ga += ag; simTot[ai].gf += ag; simTot[ai].ga += hg;
      if(hg > ag){ simTot[hi].pts += 3; simTot[hi].w++; simTot[ai].l++; }
      else if(hg < ag){ simTot[ai].pts += 3; simTot[ai].w++; simTot[hi].l++; }
      else { simTot[hi].pts++; simTot[ai].pts++; simTot[hi].d++; simTot[ai].d++; }
    });
    const order = teams.map((t, i) => ({ i, key:simTot[i].pts * 1e6 + (simTot[i].gf - simTot[i].ga) * 1e3 + simTot[i].gf }))
      .sort((a, b) => b.key - a.key);
    order.forEach((o, rank) => { posCount[o.i][rank]++; });
    teams.forEach((t, i) => ptsSamples[i].push(simTot[i].pts));

    players.forEach((p, j) => {
      const avail = Math.max(0, 33 - p.games_out) * p.mins_prob;
      const teamMult = (remXg[p.club] / 33) / Math.max(0.9, (TEAMS_IN.find(t => t.code === p.club) || { xg:1.4 }).xg);
      const gRate = (0.82 * p.xg_90 * Math.pow(p.shot_conv / 19, 0.35) + 0.06 * p.pen_share / 100) * Math.pow(teamMult, 0.85);
      const aRate = (0.72 * p.xa_90 + 0.28 * (p.kp_90 / 8.8)) * Math.pow(teamMult, 0.85);
      goalsSim[j].push(p.goals_curr + poissonDraw(Math.max(0.01, avail * gRate), rnd));
      assistsSim[j].push(p.assists_curr + poissonDraw(Math.max(0.01, avail * aRate), rnd));
    });
    gks.forEach((g, j) => {
      const avail = Math.max(0, 33 - g.games_out) * g.mins_prob;
      const skill = 1 + g.gk_psxg_diff * 0.028;
      const nGames = Math.round(33 * (avail / 33));
      const pCs = clamp((remCs[g.club] * (avail / 33) * skill) / Math.max(1, nGames), 0.02, 0.75);
      let cs = 0;
      for(let k = 0; k < nGames; k++) if(rnd() < pCs) cs++;
      csSim[j].push(g.cs_curr + cs);
    });
  }

  const tableRows = teams.map((t, i) => {
    const pts = ptsSamples[i];
    const dist = posCount[i].map(v => +(v / nSims * 100).toFixed(1));
    const title = posCount[i][0] / nSims * 100;
    const top4 = posCount[i].slice(0, 4).reduce((a, b) => a + b, 0) / nSims * 100;
    const top7 = posCount[i].slice(0, 7).reduce((a, b) => a + b, 0) / nSims * 100;
    const rel = posCount[i].slice(17).reduce((a, b) => a + b, 0) / nSims * 100;
    const mean = pts.reduce((a, b) => a + b, 0) / nSims;
    const sorted = [...pts].sort((a, b) => a - b);
    return {
      code:t.code, name:t.name, short:t.short, manager:t.manager, stadium:t.stadium, primary_color:t.color, europe:t.europe,
      current_pos:t.current_pos, curr_p:t.curr_p, curr_w:t.curr_w, curr_d:t.curr_d, curr_l:t.curr_l,
      curr_gf:t.curr_gf, curr_ga:t.curr_ga, curr_gd:t.curr_gf - t.curr_ga, curr_pts:t.curr_pts, form:t.form,
      elo_live:+t.elo.toFixed(1), xg_90_live:+t.xg.toFixed(2), xga_90_live:+t.xga.toFixed(2),
      points_deduction:(scenario.points_deductions && scenario.points_deductions[t.code]) || 0,
      proj_pts:+mean.toFixed(1), proj_pts_int:Math.round(mean),
      pts_p10:sorted[Math.floor(nSims * 0.1)], pts_p90:sorted[Math.floor(nSims * 0.9)],
      proj_gf:0, proj_ga:0, proj_gd:0, proj_w:0, proj_d:0, proj_l:0,
      title_prob:+title.toFixed(1), top4_prob:+top4.toFixed(1), europe_prob:+top7.toFixed(1), relegation_prob:+rel.toFixed(1),
      fdr_remaining:(BASELINE.table_projections.find(r => r.code === t.code) || {}).fdr_remaining || 45,
      pos_distribution:dist
    };
  }).sort((a, b) => b.proj_pts - a.proj_pts);
  tableRows.forEach((r, i) => { r.proj_pos = i + 1; r.pos_delta = r.current_pos - (i + 1); });

  const gbWin = new Array(players.length).fill(0), pmWin = new Array(players.length).fill(0);
  for(let s = 0; s < nSims; s++){
    let bi = 0, bv = -1, ai2 = 0, av = -1;
    for(let j = 0; j < players.length; j++){
      const g = goalsSim[j][s] + 0.001 * assistsSim[j][s];
      if(g > bv){ bv = g; bi = j; }
      const a2 = assistsSim[j][s] + 0.001 * goalsSim[j][s];
      if(a2 > av){ av = a2; ai2 = j; }
    }
    gbWin[bi]++; pmWin[ai2]++;
  }
  const pstat = (arr) => {
    const m = arr.reduce((a, b) => a + b, 0) / arr.length;
    const s = [...arr].sort((a, b) => a - b);
    return { mean:+m.toFixed(1), int:Math.round(m), p10:s[Math.floor(arr.length * 0.1)], p90:s[Math.floor(arr.length * 0.9)] };
  };
  const goldenBoot = players.map((p, j) => {
    const g = pstat(goalsSim[j]), a = pstat(assistsSim[j]);
    const row = tableRows.find(t => t.code === p.club) || {};
    return { player_id:p.player_id, name:p.name, club:p.club, club_name:row.short || p.club, primary_color:row.primary_color || "#333",
      pos:p.pos, nation:p.nation, games_out:p.games_out, goals_curr:p.goals_curr, assists_curr:p.assists_curr,
      goals_prev:p.goals_prev, assists_prev:p.assists_prev, goals_prev_verified:p.goals_prev_verified, assists_prev_verified:p.assists_prev_verified,
      xg_90:p.xg_90, xa_90:p.xa_90, kp_90:p.kp_90, shot_conv:p.shot_conv, pen_taker:p.pen_share >= 50,
      proj_goals:g.mean, proj_goals_int:g.int, goals_p10:g.p10, goals_p90:g.p90,
      golden_boot_prob:+(gbWin[j] / nSims * 100).toFixed(1), proj_assists:a.mean, proj_assists_int:a.int,
      assists_p10:a.p10, assists_p90:a.p90, playmaker_prob:+(pmWin[j] / nSims * 100).toFixed(1), proj_gi:+(g.mean + a.mean).toFixed(1),
      poty_index:+((g.mean * 2.1 + a.mean * 1.75 + (row.title_prob || 0) * 0.32 + (row.top4_prob || 0) * 0.12 + ((row.proj_pts || 50) - 50) * 0.35)).toFixed(1) };
  });
  const playmaker = [...goldenBoot].sort((x, y) => y.proj_assists - x.proj_assists || y.playmaker_prob - x.playmaker_prob);
  const gbSorted = [...goldenBoot].sort((x, y) => y.proj_goals - x.proj_goals || y.golden_boot_prob - x.golden_boot_prob);
  const potySorted = [...goldenBoot].sort((x, y) => y.poty_index - x.poty_index).slice(0, 10);
  const lx = potySorted.map(c => c.poty_index), mx = Math.max(...lx);
  const ex = lx.map(v => Math.exp((v - mx) / 6.5)), sx = ex.reduce((a, b) => a + b, 0);
  potySorted.forEach((c, i) => { c.poty_prob = +(ex[i] / sx * 100).toFixed(1); });

  const ggWin = new Array(gks.length).fill(0);
  for(let s = 0; s < nSims; s++){
    let bi = 0, bv = -1;
    for(let j = 0; j < gks.length; j++) if(csSim[j][s] > bv){ bv = csSim[j][s]; bi = j; }
    ggWin[bi]++;
  }
  const goldenGlove = gks.map((g, j) => {
    const st = pstat(csSim[j]);
    const row = tableRows.find(t => t.code === g.club) || {};
    return { player_id:g.player_id, name:g.name, club:g.club, club_name:row.short || g.club, primary_color:row.primary_color || "#333",
      nation:g.nation, games_out:g.games_out, cs_curr:g.cs_curr, cs_prev:g.cs_prev, gk_psxg_diff:g.gk_psxg_diff,
      save_pct:g.save_pct, team_xga_90:row.xga_90_live, proj_cs:st.mean, proj_cs_int:st.int, cs_p10:st.p10, cs_p90:st.p90,
      golden_glove_prob:+(ggWin[j] / nSims * 100).toFixed(1) };
  }).sort((x, y) => y.proj_cs - x.proj_cs || y.golden_glove_prob - x.golden_glove_prob);

  return {
    // The date comes from the payload, never from a literal. This read "2026-10-02 (Matchweek 5
    // Complete)" — written by hand when the client engine was built, and one day behind the data it
    // was simulating. On a static deployment this is the *only* engine, so every What-If run
    // reported a vintage the rest of the page contradicted.
    meta:{ season:"2026–27 Premier League",
           as_of_date:(DATA.meta && DATA.meta.as_of_date) || "",
           n_simulations:nSims, runtime_ms:0, scenario_active:true, client_fallback:true, manual_player_effects:frozenEffects },
    headline_predictions:{ champion:tableRows[0], runner_up:tableRows[1], golden_boot:gbSorted[0], playmaker:playmaker[0],
                           golden_glove:goldenGlove[0], poty:potySorted[0] },
    table_projections:tableRows, golden_boot_race:gbSorted.slice(0, 18), playmaker_race:playmaker.slice(0, 18),
    golden_glove_race:goldenGlove.slice(0, 16), poty_race:potySorted,
    gw6_predictions:DATA.gw6_predictions, gw7_predictions:DATA.gw7_predictions, marquee_predictions:DATA.marquee_predictions,
    ml_metrics:DATA.ml_metrics
  };
}

async function runSim(){
  if(!SCENARIO_ACTIVE()){ toast("Adjust an injury, form slider, deduction or scoreline first."); return; }
  const n = +$("simCount").value;
  $("simSummary").innerHTML = `<div class="panel"><div class="skel" style="width:45%"></div>
    <div class="skel" style="margin-top:12px;width:70%"></div>
    <div class="note" style="margin-top:14px">running ${n.toLocaleString()} simulated seasons — ${FIXTURES_IN.length} fixtures each…</div></div>`;
  $("simMovers").innerHTML = `<div class="skel" style="height:60px"></div>`;
  let res = null;
  if(ENGINE_MODE === "server"){
    try{
      const r = await fetch("api/simulate", { method:"POST", headers:{ "Content-Type":"application/json" },
        body:JSON.stringify({ n_sims:n, ...SCENARIO }) });
      if(r.ok) res = await r.json();
    }catch(e){}
  }
  if(!res){
    await new Promise(r => setTimeout(r, 30));
    res = localSimulate(SCENARIO, Math.min(n, 3000));
    // Two different situations, two different sentences. A static deployment has no server to
    // reach, which is not a fault and must not read like one; a server we were talking to a moment
    // ago and cannot reach now is a real failure worth naming.
    toast(ENGINE_MODE === "server"
      ? "The API stopped responding mid-run — ran the in-browser engine instead."
      : "Ran the in-browser engine — this deployment has no server behind it.", 4200);
  }
  SIM_RESULT = res;
  renderScenario(); renderScenarioAwards();
  $("simSummary").scrollIntoView({ behavior:"smooth", block:"center" });
}
