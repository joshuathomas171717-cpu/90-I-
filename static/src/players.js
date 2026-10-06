/* Phase 15 — frozen manual profiles and source-labelled player context. No network or accounts. */
var NT90_PLAYERS = (function(){
  const MODEL = "replacement-share/1";
  const finite = (v,lo,hi) => typeof v === "number" && Number.isFinite(v) ? +Math.max(lo,Math.min(hi,v)).toFixed(4) : null;
  const text = (v,n) => String(v == null ? "" : v).slice(0,n);
  function validate(raw, injuries, teams, players){
    const profiles=Object.create(null), codes=new Set(teams.map(t=>t.code)), roster=new Map(players.map(p=>[p.player_id,p]));
    let rejected=0;
    if(!raw || typeof raw!=="object" || Array.isArray(raw) || Object.keys(raw).length>52) return {profiles,rejected:1};
    Object.keys(raw).forEach(id=>{
      const p=raw[id], member=roster.get(id);
      if(!member || !injuries[id] || !p || typeof p!=="object" || p.model!==MODEL || !codes.has(p.club) || member.club!==p.club || ![1,2].includes(p.tier)){rejected++;return;}
      const attack=finite(p.attack,-10,30), defence=finite(p.defence,-10,25);
      if(attack===null || defence===null || !Array.isArray(p.attack_range) || p.attack_range.length!==2 || !Array.isArray(p.defence_range) || p.defence_range.length!==2){rejected++;return;}
      const ar=p.attack_range.map(v=>finite(v,-10,30)), dr=p.defence_range.map(v=>finite(v,-10,25));
      if(ar.includes(null)||dr.includes(null)){rejected++;return;}
      ar.sort((a,b)=>a-b);dr.sort((a,b)=>a-b);
      if(attack<ar[0]||attack>ar[1]||defence<dr[0]||defence>dr[1]){rejected++;return;}
      profiles[id]={model:MODEL,club:p.club,tier:p.tier,attack,defence,attack_range:ar,defence_range:dr,
        name:text(p.name,100),source:text(p.source,160),fetched_at:text(p.fetched_at,40),baseline_as_of:text(p.baseline_as_of,80),context_hash:text(p.context_hash,64)};
    });
    return {profiles,rejected};
  }
  function clubEffects(effects, injuries, remaining){
    const out=Object.create(null);
    Object.entries(effects).forEach(([id,p])=>{
      const n=Math.max(1,Math.trunc(remaining[p.club]||33)), f=Math.min(n,Math.max(0,Math.trunc(injuries[id]||0)))/n;
      if(!f)return;
      const e=out[p.club]||(out[p.club]={attack:0,defence:0,attack_range:[0,0],defence_range:[0,0],players:[]});
      e.attack+=p.attack*f;e.defence+=p.defence*f;
      [0,1].forEach(i=>{e.attack_range[i]+=p.attack_range[i]*f;e.defence_range[i]+=p.defence_range[i]*f});e.players.push(id);
    });
    Object.values(out).forEach(e=>{["attack","defence"].forEach(k=>{const cap=k==="attack"?30:25;e[k]=finite(e[k],-10,cap);e[k+"_range"]=e[k+"_range"].map(v=>finite(v,-10,cap))})});
    return out;
  }
  return {MODEL,validate,clubEffects};
})();

function playerDate(value){
  const d=new Date(value||"");
  return Number.isNaN(d.getTime()) ? "date unavailable" : new Intl.DateTimeFormat("en-GB",{day:"numeric",month:"short",year:"numeric",timeZone:"UTC"}).format(d);
}
function layerPlayer(id){return (PLAYER_LAYER.players||[]).find(p=>p.player_id===id)||null;}
function playerProvenance(p){return `Source: ${(p.sources||[]).join(", ")||"unavailable"} · fetched/exported ${playerDate(p.fetched_at)}`;}
function signedPercent(v){return (v>0?"+":"")+Number(v).toFixed(1)+"%";}
function remainingByClub(){const out=Object.create(null);FIXTURES_IN.forEach(([h,a])=>{out[h]=(out[h]||0)+1;out[a]=(out[a]||0)+1});return out;}
function freezePlayerEffect(id){
  const p=layerPlayer(id);if(!p||!p.effect_profile)return null;
  return {...JSON.parse(JSON.stringify(p.effect_profile)),name:p.name,source:(p.sources||[]).join(", "),
    fetched_at:p.fetched_at||"",baseline_as_of:PLAYER_LAYER.as_of||"",context_hash:PLAYER_LAYER.context_hash||""};
}
function profileDescription(id, games){
  const profile=(SCENARIO.player_effects||{})[id];
  if(!games)return "No absence assumed. This control is not actual team news.";
  if(!profile)return "Legacy impact formula — unchanged for older links/saves. Adjust this slider to adopt the new explicit range.";
  const remaining=remainingByClub(), f=Math.min(games,remaining[profile.club]||33)/(remaining[profile.club]||33);
  return `Tier ${profile.tier} ${profile.tier===1?"replacement-share prior":"with/without association"} · season-average attack ${signedPercent(-profile.attack*f)} `
    +`(${signedPercent(-profile.attack_range[1]*f)} to ${signedPercent(-profile.attack_range[0]*f)}); conceded-goal rate ${signedPercent(profile.defence*f)}. `
    +`Frozen source: ${profile.source||"unavailable"}, ${playerDate(profile.fetched_at)}. Ranges are input assumptions, not win/points intervals.`;
}
function renderPlayerEffects(){
  const host=$("playerEffectSummary");if(!host)return;
  const profiles=SCENARIO.player_effects||{}, effects=NT90_PLAYERS.clubEffects(profiles,SCENARIO.player_injuries,remainingByClub());
  const rows=Object.entries(effects);
  host.innerHTML = rows.length ? `<div class="effect-grid">${rows.map(([club,e])=>`<div class="effect-tile">
    <b>${esc(TEAM_LABEL[club]||club)} · ${e.players.length} named assumption${e.players.length===1?"":"s"}</b>
    <div>Attack ${signedPercent(-e.attack)} <span class="dim">${signedPercent(-e.attack_range[1])} to ${signedPercent(-e.attack_range[0])}</span></div>
    <div>Conceded-goal rate ${signedPercent(e.defence)} <span class="dim">${signedPercent(e.defence_range[0])} to ${signedPercent(e.defence_range[1])}</span></div>
  </div>`).join("")}</div><p class="small mut">Season-average assumptions, capped across multiple absences. A replacement is counted; these are not confidence intervals on the table.</p>`
    : `<p class="small mut">Select a named player above. Actual availability never auto-fills your scenario; older saved links keep their legacy method.</p>`;
  const mismatched=Object.values(profiles).some(p=>p.baseline_as_of && String((DATA.meta||{}).as_of_date||"").slice(0,10)!==p.baseline_as_of.slice(0,10));
  if(mismatched)host.innerHTML+=`<p class="note">This tab uses a different baseline date from the saved assumptions. Names and coefficients are preserved; projected outcomes can change with the baseline.</p>`;
}
function filterScenarioPlayers(){
  const q=String($("scenPlayerSearch")?.value||"").toLowerCase(), club=$("scenClubFilter")?.value||"ALL";
  document.querySelectorAll("#scenarioForm [data-scenario-player]").forEach(el=>{
    el.hidden=(club!=="ALL"&&el.dataset.club!==club)||!el.dataset.search.includes(q);
  });
}
function renderPlayerSquad(){
  const host=$("squadPlayers"), picker=$("squadClub");if(!host||!picker)return;
  if(!picker.options.length){picker.innerHTML=[...TEAMS_IN].sort((a,b)=>a.short.localeCompare(b.short)).map(t=>`<option value="${esc(t.code)}">${esc(t.name)}</option>`).join("");picker.value="ARS";}
  const club=picker.value, members=(PLAYER_LAYER.players||[]).filter(p=>p.club===club);
  const note=$("squadCoverage");if(note)note.textContent=`${members.length} tracked players — a partial sample, not a complete squad. Context only; unverified player signals do not change the match probabilities.`;
  if(note && PLAYER_LAYER.omitted_players) note.textContent+=" Additional source records are shown on the full club pages and in players.json; this lightweight preview is bounded.";
  host.innerHTML=members.length ? members.map(p=>{
    const status=p.availability||{}, trend=p.trend||{}, score=p.score===null||p.score===undefined?"Not available":Number(p.score).toFixed(1)+" / 100";
    const trendLabel=trend.delta===null||trend.delta===undefined?"Trend unavailable — no comparable dated matches":signedPercent(trend.delta).replace("%"," index points")+" vs 7 days earlier";
    const mins=Object.entries(p.minutes_by_competition||{});
    return `<article class="squad-card rv"><div class="row" style="justify-content:space-between;gap:10px"><div><h3>${esc(p.name)}</h3><span class="dim small">${esc(p.position)} · ${esc(p.recency)}</span></div><span class="squad-index">${esc(score)}</span></div>
      <p class="small mut">${esc(trendLabel)}</p>
      <ul class="competition-minutes">${mins.map(([c,m])=>`<li><span>${esc(c)}</span><b>${Math.round(m)} min</b></li>`).join("")}</ul>
      <p class="player-availability ${status.status==="out"?"out":""}"><b>${esc(status.label||"Availability unknown")}</b><br><span class="small">${esc(status.reason||"No source")}</span></p>
      <p class="small mut">Absence estimate: Tier ${Number((p.absence||{}).tier)||1} · ${esc((p.absence||{}).label||"unavailable")}. This is not a current injury claim.</p>
      <p class="player-source">${esc(playerProvenance(p))}</p>
    </article>`;
  }).join("") : `<p class="note">No player source for this club. The forecast retains the existing team model.</p>`;
  picker.onchange=()=>{renderPlayerSquad();if(typeof animate==="function")animate(host)};
}
function renderMissingDigest(){
  const host=$("missingDigest");if(!host)return;
  const gw=(DATA.meta||{}).next_gw, evidence=(PLAYER_LAYER.by_gameweek||{})[String(gw)]||{status:"not-recorded",capture:null,note:"No availability record for this week."};
  const capture=evidence.capture, clubs=[...new Set((DATA.next_gw_predictions||DATA.gw6_predictions||[]).flatMap(p=>[p.home,p.away]))];
  host.innerHTML=`<p class="note">${esc(evidence.note||"")} Injury news is not automatically priced into these probabilities.</p>
    <details class="missing-clubs"><summary>Who is missing? · ${clubs.length} clubs · ${esc(evidence.status)}</summary>
    <ul>${clubs.map(club=>{
      const coverage=((capture||{}).coverage||{})[club], missing=(((capture||{}).clubs||{})[club]||[]);
      let label="Availability unknown — not a healthy-team claim";
      if(capture&&capture.tracked&&!['unknown','failed',undefined].includes(coverage)) label=missing.length?missing.map(p=>`${p.player} (${p.type||"listed out"}${p.reason?": "+p.reason:""})`).join("; "):coverage==="checked"?"Source checked; no absence listed":"Partial list; coverage incomplete";
      return `<li><b>${esc(TEAM_LABEL[club]||club)}</b> — ${esc(label)}</li>`;
    }).join("")}</ul></details>
    <p class="player-source">${capture?`Source: ${esc(capture.source||"unavailable")} · captured ${esc(playerDate(capture.captured_at))}`:"No source or pre-lock capture recorded. Later news is never backfilled."}</p>`;
}
