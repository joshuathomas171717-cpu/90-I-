/* ═══════════════════════════════════════════════════════════════════════════
   MOTION — nothing just appears.
   Counters tick, bars fill, rings sweep, cards arrive in choreographed order.
   All declarative: renders emit data-attributes, animate() plays them once.
   ═══════════════════════════════════════════════════════════════════════════ */

const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const EASE_OUT = t => 1 - Math.pow(1 - t, 3);

function countUp(el, to, { dec = 0, dur = 900, prefix = "", suffix = "" } = {}){
  if(REDUCED){ el.textContent = prefix + to.toFixed(dec) + suffix; return; }
  const from = dec === 0 ? Math.max(0, Math.round(to * 0.55)) : 0;
  const t0 = performance.now();
  const step = (now) => {
    const k = Math.min(1, (now - t0) / dur);
    const v = from + (to - from) * EASE_OUT(k);
    el.textContent = prefix + v.toFixed(dec) + suffix;
    // digits stay visually alive while they move
    el.style.textShadow = k < 1 ? "0 0 14px rgba(61,220,151,.35)" : "none";
    if(k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* Scroll-driven reveal. Deterministic (no IO dependency), throttled to one rAF per scroll burst,
   and guaranteed: anything within ~1.2 viewports reveals on load, on scroll, and on tab change. */
let _revQueued = false;
function fillTri(root){
  (root || document).querySelectorAll(".tri").forEach(tri => {
    if(tri.dataset.filled) return;
    tri.dataset.filled = "1";
    /* probabilities live on the .tri itself (marquee, duel) or on the enclosing .fx card */
    const src = (tri.dataset.wh !== undefined) ? tri : (tri.closest(".fx") || tri);
    const w = [src.dataset.wh, src.dataset.wd, src.dataset.wa].map(Number);
    [...tri.querySelectorAll("i")].forEach((i, k) => {
      const v = w[k];
      if(!isNaN(v) && v > 0) i.style.width = v + "%";
    });
    /* keep the CSS-variable path working too (no-JS / reduced-motion safety) */
    const fx = tri.closest(".fx");
    if(fx){
      fx.style.setProperty("--wh", (w[0] || 0) + "%");
      fx.style.setProperty("--wd", (w[1] || 0) + "%");
      fx.style.setProperty("--wa", (w[2] || 0) + "%");
      fx.classList.add("done");
    }
    tri.classList.add("done");
  });
}
function checkReveals(){
  _revQueued = false;
  const vh = window.innerHeight || 900;
  document.querySelectorAll(".rv:not(.in)").forEach(el => {
    const r = el.getBoundingClientRect();
    if(r.top < vh * 1.12 && r.bottom > -vh * 0.4) el.classList.add("in");
  });
  document.querySelectorAll("[data-count]:not([data-done])").forEach(el => {
    const r = el.getBoundingClientRect();
    if(r.top < vh * 1.06 && r.bottom > -160){
      el.dataset.done = "1";
      countUp(el, parseFloat(el.dataset.count), {
        dec:+(el.dataset.dec || 0), prefix:el.dataset.pre || "",
        suffix:el.dataset.suf || "", dur:+(el.dataset.dur || 900) });
    }
  });
  fillTri();
}
function queueReveals(){
  if(_revQueued) return;
  _revQueued = true;
  requestAnimationFrame(checkReveals);
}
window.addEventListener("scroll", queueReveals, { passive:true });
window.addEventListener("resize", queueReveals);

function animate(root){
  root = root || document;
  /* staggered entrances */
  const rvs = [...root.querySelectorAll(".rv:not(.in)")];
  rvs.forEach((el, i) => {
    if(el.dataset.d === undefined) el.style.setProperty("--d", Math.min(i * 42, 460) + "ms");
    if(REDUCED) el.classList.add("in");
  });
  checkReveals();
  setTimeout(checkReveals, 260);   // catch late layout shifts
  setTimeout(checkReveals, 900);
  /* probability tracks + ribbons */
  root.querySelectorAll(".track > i[data-w]").forEach(i => {
    const w = clamp(parseFloat(i.dataset.w), 0, 100);
    i.style.color = i.dataset.color || "";
    requestAnimationFrame(() => { i.style.width = w + "%"; });
  });
  root.querySelectorAll(".ribbon > i[data-w]").forEach(i => {
    const w = clamp(parseFloat(i.dataset.w), 0, 100);
    requestAnimationFrame(() => { i.style.width = w + "%"; });
  });
  /* three-way outcome bars — staggered so a gameweek fills in like a broadcast wipe */
  root.querySelectorAll(".fx").forEach(fx => {
    setTimeout(() => fillTri(fx), REDUCED ? 0 : 130 + (+fx.dataset.i || 0) * 60);
  });
  root.querySelectorAll(".tri").forEach(tri => { if(!tri.closest(".fx")) setTimeout(() => fillTri(tri.parentNode), 260); });
  /* rings */
  root.querySelectorAll("[data-ring]").forEach(svg => {
    const p = clamp(parseFloat(svg.dataset.ring), 0, 100);
    const arc = svg.querySelector(".arc");
    if(!arc) return;
    const r = +arc.getAttribute("r"), C = 2 * Math.PI * r;
    arc.setAttribute("stroke-dasharray", C);
    arc.setAttribute("stroke-dashoffset", C);
    setTimeout(() => { arc.setAttribute("stroke-dashoffset", C * (1 - p / 100)); }, 120);
  });
  /* sparkline / line draw-in */
  root.querySelectorAll("[data-draw]").forEach(path => {
    try{
      const L = path.getTotalLength();
      path.style.strokeDasharray = L; path.style.strokeDashoffset = L;
      path.style.transition = "stroke-dashoffset 1.5s cubic-bezier(.22,.68,.32,1)";
      setTimeout(() => { path.style.strokeDashoffset = 0; }, 180);
    }catch(e){}
  });
  /* bar charts growing from the bottom (feature importance etc.) */
  root.querySelectorAll("[data-grow]").forEach(el => {
    const w = parseFloat(el.dataset.grow);
    requestAnimationFrame(() => { el.style.width = w + "%"; });
  });
}

function moment(el){
  if(!el || REDUCED) return;
  el.classList.remove("moment"); void el.offsetWidth; el.classList.add("moment");
}

/* ── tab choreography: current view slides out, next flows in ── */
function switchTab(name){
  const cur = document.querySelector("section.page.on");
  const next = $("tab-" + name);
  if(!next || next === cur) return;
  document.querySelectorAll("nav.tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === name));
  const dirIdx = { matchweek:0, table:1, awards:2, duel:3, whatif:4, model:5 };
  const curIdx = dirIdx[cur?.id?.replace("tab-", "")] ?? 0, nextIdx = dirIdx[name] ?? 0;
  const dir = nextIdx >= curIdx ? 1 : -1;

  const show = () => {
    next.classList.add("on");
    next.style.setProperty("--dir", dir);
    const kids = [...next.querySelectorAll(":scope > .grid, :scope > .panel, :scope > .hero, :scope > .row, :scope > .stack")];
    kids.forEach((k, i) => {
      k.classList.add("rv"); k.style.setProperty("--d", (i * 70) + "ms");
      k.classList.remove("in");
    });
    requestAnimationFrame(() => { kids.forEach(k => k.classList.add("in")); animate(next); });
    window.scrollTo({ top:0, behavior: REDUCED ? "auto" : "smooth" });
    if(name === "duel" && !LAST_FIXTURE) predictFixture();
  };

  if(cur && !REDUCED){
    cur.classList.add("leaving");
    setTimeout(() => { cur.classList.remove("on", "leaving"); show(); }, 150);
  } else show();
}

/* ── pointer spotlight is owned by the UX layer (static/src/ux.js). This keeps the
   original call-site in render.js working without two systems fighting over --mx/--my. ── */
function armGlow(root){
  if(typeof UX !== "undefined" && UX.refresh) UX.refresh();
}

/* ── small screen: the ticker is decorative, so slow it down rather than let it distract ── */
if(window.matchMedia("(max-width: 720px)").matches){
  const rail = document.querySelector("#ticker .rail");
  if(rail) rail.style.animationDuration = "88s";
}
