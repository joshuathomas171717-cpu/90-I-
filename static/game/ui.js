/* Browser-only game UI (v2). Imported/saved text is always escaped; no eval, API or third-party calls.
 *
 * The matchday is played, not skipped: kickoff → first-half commentary → half-time decision (instruction
 * + substitutions) → second half → full time, then the manager's inbox. "Skip match" remains available
 * for people who want the old fast path, and reduced-motion users get the same decision points as
 * segmented summaries instead of a ticking clock.
 */
(function(){
 'use strict';
 const G=NT90_GAME,STORE=window.NT90_STORE,BASE=G.cleanBase(PLAY_DATA.world),$=id=>document.getElementById(id);
 const esc=x=>String(x==null?'':x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const teams=Object.fromEntries(BASE.teams.map(t=>[t.code,t])),query=new URLSearchParams(location.search),reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
 const team=c=>teams[c]||{code:c,short:c,name:c,color:'#2dd4bf'};
 const badge=c=>{const color=/^#[a-f0-9]{6}$/i.test(team(c).color)?team(c).color:'#2dd4bf',rgb=[1,3,5].map(i=>parseInt(color.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4)),light=.2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];return `<span class="crest" style="background:${color};color:${light>.179?'#000':'#fff'}" aria-hidden="true">${esc(c)}</span>`;};
 const signed=n=>(n>0?'+':'')+Number(n).toFixed(n%1?1:0);
 let chosen=teams[query.get('club')]?query.get('club'):'ARS',active=null,activeId=null,busy=false,session=null,timer=null;
 let draft=Object.assign({},PLAY_DATA.challenge,{picks:{}}),practiceSeed=42;
 const niceDate=x=>{const d=new Date(x||'');return Number.isNaN(d.getTime())?'date unavailable':new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}).format(d)};
 function notify(text){$('gameToast').textContent=text;$('gameToast').classList.add('on');clearTimeout(notify.timer);notify.timer=setTimeout(()=>$('gameToast').classList.remove('on'),4500);}
 function error(text){$('gameError').textContent=text;$('gameError').hidden=false;}
 function guarded(fn){return function(e){$('gameError').hidden=true;try{return fn(e)}catch(err){error(err.message&&err.message.length<150?err.message:'This game data could not be read safely.');}};}
 function saved(){const raw=STORE?STORE.get('careers',[]):[];return Array.isArray(raw)?raw.slice(0,3).filter(e=>e&&typeof e.id==='string'&&/^[a-z0-9_-]{1,64}$/.test(e.id)&&e.state):[];}
 function updateStorage(){const blocked=!STORE||STORE.degraded();$('storageNotice').hidden=!blocked;$('storageNotice').textContent=blocked?'This browser is not keeping saves permanently. Your session still works—export a backup before closing the tab.':'';}
 function save(){if(!active||!STORE)return;const list=saved(),entry={id:activeId,state:active,saved:Date.now()},found=list.findIndex(e=>e.id===activeId);if(found>=0)list[found]=entry;else{if(list.length>=3)throw new Error('Three save slots are full. Export/delete an older career first.');list.unshift(entry);}STORE.set('careers',list);updateStorage();}
 function careerId(){return 'c'+Date.now().toString(36)+Math.random().toString(36).slice(2,7);}
 function mode(name){const challenge=name==='challenge';if(challenge&&session)return notify('Finish the match in front of you first.');$('careerView').hidden=challenge;$('challengeView').hidden=!challenge;$('careerTab').setAttribute('aria-selected',String(!challenge));$('challengeTab').setAttribute('aria-selected',String(challenge));$('careerTab').tabIndex=challenge?-1:0;$('challengeTab').tabIndex=challenge?0:-1;if(challenge)renderChallenge();}
 function chooseClub(c){if(!teams[c])return;chosen=c;document.querySelectorAll('[data-club]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.club===c)));$('selectedClub').textContent=team(c).name+' · target: top '+team(c).target;}
 function renderClubs(){const q=$('clubSearch').value.toLowerCase();$('clubGrid').innerHTML=[...BASE.teams].sort((a,b)=>a.name.localeCompare(b.name)).filter(t=>(t.name+' '+t.code).toLowerCase().includes(q)).map(t=>`<button class="club-tile" data-club="${esc(t.code)}" aria-pressed="${t.code===chosen}">${badge(t.code)}<b>${esc(t.name)}</b><small>${t.pts} points now · game target top ${t.target}</small></button>`).join('');$('clubGrid').querySelectorAll('[data-club]').forEach(b=>b.onclick=()=>chooseClub(b.dataset.club));chooseClub(chosen);}
 function renderSaves(){const list=saved();$('careerSaves').innerHTML=list.length?list.map(e=>{try{const s=G.restore(e.state),r=G.summary(s);return `<div class="saved-card"><div><strong>${esc(s.base.teams.find(t=>t.code===s.club).name)}</strong><p>${r.played}/${r.total} matchdays · ${r.pts} points · ${r.position}${r.position===1?'st':r.position===2?'nd':r.position===3?'rd':'th'}${r.momentum&&r.momentum.length?' · form '+r.momentum.join(''):''} · frozen ${esc(niceDate(s.base.asOf))}</p></div><div class="actions"><button data-resume="${esc(e.id)}" class="primary">Resume →</button><button data-delete="${esc(e.id)}" class="danger">Delete</button></div></div>`}catch(err){return `<div class="saved-card"><span>Unrecognised/damaged save—never executed or silently overwritten.</span><button data-delete="${esc(e.id)}" class="danger">Delete</button></div>`}}).join(''):'<p class="empty">Your first career starts above. Up to three saved worlds, all on this device.</p>';
  $('careerSaves').querySelectorAll('[data-resume]').forEach(b=>b.onclick=guarded(()=>{const e=saved().find(x=>x.id===b.dataset.resume);active=G.restore(e.state);activeId=e.id;session=null;openCareer();if(active.migrated)notify('This save was made with the earlier rules. Its results are unchanged; new matches use half-time decisions.',6000);}));
  $('careerSaves').querySelectorAll('[data-delete]').forEach(b=>b.onclick=()=>{if(!b.dataset.confirm){b.dataset.confirm='yes';b.textContent='Delete this save?';return;}STORE.set('careers',saved().filter(x=>x.id!==b.dataset.delete));renderSaves();notify('Career deleted from this device.');});
 }
 function openCareer(){$('careerSetup').hidden=true;$('careerActive').hidden=false;renderCareer();$('careerTitle').scrollIntoView({behavior:reduced?'auto':'smooth',block:'start'});}
 function resultLabel(r,club){if(!r)return 'no fixture';const gf=r.h===club?r.hg:r.ag,ga=r.h===club?r.ag:r.hg;return gf>ga?'WIN':gf===ga?'DRAW':'LOSS';}
 function effectText(effect){
  const bits=[];
  if(effect.credits)bits.push(signed(effect.credits)+' fictional credits');
  if(effect.fitness)bits.push(signed(effect.fitness)+' fitness');
  if(effect.boost)bits.push('next match: attack '+signed(effect.boost.attack||0)+'%, conceded-goal rate '+signed(effect.boost.defence||0)+'%');
  if(effect.rest_next)bits.push('that player is rested next matchday');
  if(effect.club)bits.push('you are now the manager of '+team(effect.club).name);
  if(effect.pressure)bits.push('board pressure '+(effect.pressure>0?'rises':'eases'));
  return bits.length?bits.join(' · '):'Nothing changed — the reply was only words.';
 }
 function momentumStrip(s){return s.momentum&&s.momentum.length?`<span class="momentum" aria-label="Last results">${s.momentum.map(m=>`<i class="${m}">${m}</i>`).join('')}</span>`:'';}
 function renderCareer(){
  if(!active)return;const s=active,r=G.summary(s),own=s.base.teams.find(t=>t.code===s.club);
  $('careerTitle').textContent=own.name+' · Club Manager';
  $('careerSubtitle').textContent=`Frozen world: ${niceDate(s.base.asOf)} · world code ${s.seed} · your progress never changes the real season`;
  $('managerStats').innerHTML=[['League position',r.position+' / 20','Game objective: top '+r.target],
   ['Points',r.pts,(r.delta>=0?'+':'')+r.delta+' vs unchanged control path'],
   ['Fitness',Math.round(s.fitness)+' / 100','Pressing and chasing games cost legs'],
   ['Transfer budget',s.credits+' cr','Fictional credits · no real money']]
   .map(([a,b,c])=>`<div class="stat"><small>${esc(a)}</small><b>${esc(b)}</b><span>${esc(c)}</span></div>`).join('');
  const p=G.preview(s),briefing=G.beginMatch(s);
  $('roundBadge').textContent=r.done?'Season complete':`MW${briefing?briefing.gw:G.rounds(s)[s.step]} · ${r.played}/${r.total} played`;
  $('nextMatchTitle').textContent=r.done?'Your season is complete':(session?briefing&&`${team(briefing.fixture.h).short} v ${team(briefing.fixture.a).short}`:'Ready for kickoff?');
  if(!session){
   $('nextMatch').innerHTML=p?`<div class="match-versus"><div>${badge(p.h)}<strong>${esc(team(p.h).short)}</strong></div><span class="versus">VS</span><div>${badge(p.a)}<strong>${esc(team(p.a).short)}</strong></div></div>
    <div class="prob-row"><span>Home win<b>${p.prob.h}%</b></span><span>Draw<b>${p.prob.d}%</b></span><span>Away win<b>${p.prob.a}%</b></span></div>
    <div class="brief-grid">${briefing?[['Kickoff window',esc(briefing.fixture.dates)],['Weather',esc(briefing.weather)],['Crowd',esc(briefing.attendance.toLocaleString()+' inside')],['Your form',momentumStrip(s)||'first match of the career'],['Plan',esc(s.tactic+' · '+s.training)],['Available',esc(briefing.subsPool.length+' tracked players, '+briefing.restedCount+' rested')]].map(([k,v])=>`<div><small>${k}</small><b>${v}</b></div>`).join(''):''}</div>
    <div class="match-note">Your game choices: ${p.prob.h===p.original.h&&p.prob.a===p.original.a?'no probability change yet':'changed this fixture’s game chances'} · unchanged path ${p.original.h}% / ${p.original.d}% / ${p.original.a}%${s.boosts&&s.boosts.attack||s.boosts&&s.boosts.defence?` · active decision boost: attack ${signed(s.boosts.attack||0)}%, conceded-goal rate ${signed(s.boosts.defence||0)}%`:''}</div>`:'<p class="lead">The final whistle has gone. See your season report below.</p>';
  }
  $('kickOff').disabled=r.done||!!session;$('playRound').disabled=r.done||!!session;$('fastForward').disabled=r.done||!!session;
  $('managementDesk').hidden=r.done;
  $('tactics').innerHTML=Object.keys(G.TACTICS).map(k=>`<button data-tactic="${k}" aria-pressed="${s.tactic===k}">${{balanced:'Balanced',attacking:'Attack',defensive:'Defend',pressing:'High press'}[k]}<span>${{balanced:'Keep your shape',attacking:'More goals, more risk',defensive:'Protect the lead',pressing:'Pressure costs fitness'}[k]}</span></button>`).join('');
  $('training').innerHTML=Object.keys(G.TRAINING).map(k=>`<button data-training="${k}" aria-pressed="${s.training===k}">${{recovery:'Recovery',attack:'Finishing',defence:'Defensive work'}[k]}<span>${{recovery:'Restore 12 fitness',attack:'+4% game attack, −4 fitness',defence:'−4% conceded-goal rate, −3 fitness'}[k]}</span></button>`).join('');
  $('tactics').querySelectorAll('[data-tactic]').forEach(b=>b.onclick=guarded(()=>{if(busy||session)return;active=G.configure(active,{tactic:b.dataset.tactic});save();renderCareer();}));
  $('training').querySelectorAll('[data-training]').forEach(b=>b.onclick=guarded(()=>{if(busy||session)return;active=G.configure(active,{training:b.dataset.training});save();renderCareer();}));
  $('careerSquad').innerHTML=G.roster(s,s.club).map(p=>`<div class="star-row"><div><strong>${esc(p.name)}</strong><small>${esc(p.pos)} · ${s.bought[p.id]?'Fantasy signing':'Tracked club player'}</small></div><label><input type="checkbox" data-rest="${esc(p.id)}" ${s.rested.includes(p.id)?'checked':''} ${session?'disabled':''}>Rest next game</label></div>`).join('');
  $('careerSquad').querySelectorAll('[data-rest]').forEach(input=>input.onchange=guarded(()=>{if(session)return;const set=new Set(active.rested);if(input.checked)set.add(input.dataset.rest);else set.delete(input.dataset.rest);active=G.configure(active,{rested:[...set]});save();renderCareer();}));
  const ordered=G.rank(s.table);
  $('careerTable').innerHTML='<caption class="small muted" style="text-align:left;padding-bottom:10px">Alternate table · simulated future only</caption><thead><tr><th scope="col">#</th><th scope="col">Club</th><th scope="col" class="num">P</th><th scope="col" class="num">GD</th><th scope="col" class="num">Pts</th></tr></thead><tbody>'+ordered.map((t,i)=>`<tr class="${t.code===s.club?'yours ':''}${i<4?'top-four':i>=17?'relegation':''}"><td>${i+1}</td><th scope="row"><span class="table-club">${badge(t.code)}${esc(t.short)}</span></th><td class="num">${t.p}</td><td class="num">${t.gf-t.ga}</td><td class="num"><b>${t.pts}</b></td></tr>`).join('')+'</tbody>';
  $('careerNotebook').innerHTML=s.journal.length?s.journal.slice(-6).reverse().map(entry=>{
   const last=entry.own,plan=entry.plan||{},decision=(G.INSTRUCTIONS[plan.interaction]||{}).label||'Stayed calm';
   const inbox=(entry.inbox||[]).map(c=>`${c.type}: ${c.choice}`).join(', ');
   return `<div class="notebook-item"><strong>MW${entry.gw} · ${last?resultLabel(last,s.club)+' '+last.hg+'–'+last.ag:'no club fixture'}</strong><small>${esc(decision)}${plan.subs&&plan.subs.length?' · '+plan.subs.length+' sub(s)':''} · ${esc(entry.tactic)} · ${esc(entry.training)} · ${entry.rested.length} rested${inbox?' · replied '+esc(inbox):''}</small></div>`;}).join(''):'<p class="empty">Your story starts at the next matchday. Every choice, half-time call and inbox reply is kept here.</p>';
  $('seasonReport').hidden=!r.done;
  if(r.done)$('seasonReport').innerHTML=`<p class="eyebrow">FINAL WHISTLE · YOUR GAME REPORT</p><h2>${r.position===1?'Champions. You wrote the ending.':r.objective?'Mission accomplished.':r.position>=18?'A tough ending. Try a different route.':'A season to learn from.'}</h2><p class="lead">${esc(own.name)} finish ${r.position} with ${r.pts} points. ${(r.delta>=0?'+':'')+r.delta} points versus the untouched control path. Your game target was top ${r.target}; ${r.objective?'achieved':'not achieved'}. Form: ${r.momentum.join(' ')||'—'}. This is a simulated alternative, not the real final table.</p><div class="row-buttons" style="margin-top:18px"><button id="reportNew" class="primary">Start another story</button><button id="reportExport">Export this career</button></div>`;
  if($('reportNew'))$('reportNew').onclick=goHome;if($('reportExport'))$('reportExport').onclick=exportSave;
  renderInbox();renderMarket();
  // The desk is rebuilt above, so the live-match lock has to be applied last, or fresh buttons arrive enabled.
  if(session)$('managementDesk').querySelectorAll('button,input').forEach(el=>el.disabled=true);
  updateStorage();
 }
 /* ══════════════ the matchday session ══════════════ */
 const LINES=['Both sides are feeling each other out.','The crowd lifts as the ball goes forward.','A crunching challenge in midfield — no card.','The manager is on the touchline, pointing.','Patient build-up, but the final ball is missing.','A half-chance flashes wide.','The tempo drops; someone needs to take control.','The fourth official signals a minimum of added time.'];
 function lineFor(id,minute){return LINES[Math.floor(G.rand(G.salt(0,id+'-'+minute))*LINES.length)];}
 function paintStage(){const s=session;if(!s)return;$('matchStage').hidden=false;$('stageTag').textContent=s.stage==='pre'?'Pre-match':s.stage==='first'?'First half':s.stage==='half'?'Half time':s.stage==='second'?'Second half':'Full time';
  $('stageTitle').textContent=[s.brief.fixture.h,s.brief.fixture.a].map(c=>team(c).short).join(' v ');
  const shown=s.shown||{home:0,away:0};$('liveScore').textContent=shown.home+' – '+shown.away;
  $('liveClock').textContent=(s.minute||0)+'′';
  $('liveFeed').innerHTML=s.feed.length?s.feed.map(f=>`<p class="${f.kind||''}">${f.minute}′ · ${f.text}</p>`).join(''):'<p class="muted">The teams are in the tunnel.</p>';
 }
 function firstHalfScript(first){const script=[];for(let minute=1;minute<=45;minute+=1){
   const goal=first.goals.find(g=>g.minute===minute);
   if(goal)script.push({minute,kind:'goal',side:goal.side,text:`GOAL — ${esc(goal.scorer)} for ${team(goal.side==='h'?first.fixture.h:first.fixture.a).short}.`});
   else if(minute%7===0)script.push({minute,text:lineFor(first.fixture.id,minute)});
  }return script;}
 function runFirstHalf(){
  const s=session,first=s.first,script=firstHalfScript(first);let index=0;
  const finish=()=>{s.minute=45;s.stage='half';showHalfTime();paintStage();};
  const step=()=>{if(!session)return;const item=script[index];
   if(item){index++;s.minute=item.minute;s.feed.push(item);
    if(item.kind==='goal'){if(item.side==='h')s.shown.home++;else s.shown.away++;}}
   if(!item||s.minute>=45){clearTimeout(timer);finish();return;}
   paintStage();timer=setTimeout(step,420);};
  s.stage='first';s.feed=[];s.shown={home:0,away:0};busy=true;paintStage();
  if(reduced){
   script.forEach(item=>{s.feed.push(item);if(item.kind==='goal'){if(item.side==='h')s.shown.home++;else s.shown.away++;}});
   s.minute=45;finish();return;
  }
  timer=setTimeout(step,420);
 }
function showHalfTime(){
  const s=session,first=s.first;
  $('halfTimePanel').hidden=false;$('fullTimePanel').hidden=true;$('skipReveal').hidden=false;$('skipReveal').textContent='Skip the second half';
  const lead=first.lead;
  $('halfTimeHint').textContent=lead>1?`You are ${lead} goals up. Change anything, or protect it.`
   :lead===1?'One goal ahead. Push, hold, or stay as you are?'
   :lead===0?'Level at the break. What do you change?'
   :`You are ${Math.abs(lead)} goal(s) down. Time for a decision.`;
  $('instructionChoices').innerHTML=Object.entries(G.INSTRUCTIONS).map(([key,item])=>
   `<button data-instruction="${key}" aria-pressed="${s.plan.interaction===key}">${esc(item.label)}<span>${esc(item.detail)}</span></button>`).join('');
  $('instructionChoices').querySelectorAll('[data-instruction]').forEach(b=>b.onclick=()=>{s.plan.interaction=b.dataset.instruction;$('instructionChoices').querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.instruction===b.dataset.instruction)));});
  const rested=new Set(active.rested);
  $('subChoices').innerHTML=s.brief.subsPool.map(p=>`<label class="sub-row"><span><b>${esc(p.name)}</b><small>${esc(p.pos)}</small></span><input type="checkbox" data-sub="${esc(p.id)}" ${s.plan.subs.includes(p.id)?'checked':''} ${rested.has(p.id)?'disabled':''}></label>`).join('')||'<p class="empty">No tracked players are available to bring on.</p>';
  $('subChoices').querySelectorAll('[data-sub]').forEach(input=>input.onchange=()=>{
   const set=new Set(session.plan.subs);
   if(input.checked){if(set.size>=G.MAX_SUBS){input.checked=false;return notify('At most '+G.MAX_SUBS+' substitutions per match.');}set.add(input.dataset.sub);}else set.delete(input.dataset.sub);
   session.plan.subs=[...set];$('subsCount').textContent=set.size+' / '+G.MAX_SUBS+' used';
  });
  $('subsCount').textContent=s.plan.subs.length+' / '+G.MAX_SUBS+' used';
  $('secondHalf').focus();
 }
 function playSecondHalf(){
  if(!session)return;
  const s=session,pre=s.pre;
  const committed=G.complete(active,{interaction:s.plan.interaction,subs:s.plan.subs});
  active=committed.state;save();
  const neutral=G.complete(G.clone(pre),{interaction:'calm',subs:[]}).result;
  s.result=committed.result;s.neutral=neutral;s.stage='second';busy=true;
  const second=s.result.goals.filter(g=>g.phase==='second');
  $('halfTimePanel').hidden=true;$('skipReveal').hidden=false;$('skipReveal').textContent='Skip to full time';
  const rest=[...second].sort((a,b)=>a.minute-b.minute);
  $('stageTag').textContent='Second half';
  const step=()=>{if(!session)return;const item=rest.shift();
   if(item){s.shown[item.side==='h'?'home':'away']++;s.feed.push({minute:item.minute,kind:'goal',side:item.side,text:`GOAL — ${esc(item.scorer)} for ${team(item.side==='h'?s.result.own.h:s.result.own.a).short}.`});}
   if(!item||!rest.length){clearTimeout(timer);session.stage='full';showFullTime();paintStage();return;}
   paintStage();timer=setTimeout(step,520);};
  if(reduced){second.forEach(item=>s.feed.push({minute:item.minute,kind:'goal',side:item.side,text:`GOAL — ${esc(item.scorer)} for ${team(item.side==='h'?s.result.own.h:s.result.own.a).short}.`}));s.shown={home:s.result.own.hg,away:s.result.own.ag};s.stage='full';showFullTime();paintStage();return;}
  paintStage();timer=setTimeout(step,520);
 }
 function showFullTime(){
  const s=session,result=s.result,own=result.own,neutral=s.neutral;
  $('fullTimePanel').hidden=false;$('skipReveal').hidden=true;
  const youHome=own.h===active.club,gf=youHome?own.hg:own.ag,ga=youHome?own.ag:own.hg;
  const instruction=G.INSTRUCTIONS[result.plan.interaction];
  const effect=result.effect,mean=effect.means;
  const mine=mean.mine,theirs=mean.theirs;
  const addedMine=youHome?effect.added.home:effect.added.away,addedTheirs=youHome?effect.added.away:effect.added.home;
  const removedMine=youHome?effect.removed.home:effect.removed.away,removedTheirs=youHome?effect.removed.away:effect.removed.home;
  const neutralOwn=neutral.own,neutralYou=neutralYouScore(neutralOwn,active.club);
  const swing=neutralYou&&(neutralYou[0]!==gf||neutralYou[1]!==ga)?'That call changed the score.' : 'That call did not change the score this time.';
  $('fullTimeSummary').innerHTML=`<p class="eyebrow">FULL TIME · SIMULATED</p>
   <div class="match-versus"><div>${badge(own.h)}<strong>${esc(team(own.h).short)}</strong></div><b class="score-big">${own.hg} – ${own.ag}</b><div>${badge(own.a)}<strong>${esc(team(own.a).short)}</strong></div></div>
   <ul class="scorers">${result.goals.length?result.goals.map(g=>`<li>${g.minute}′ · ${esc(team(g.side==='h'?own.h:own.a).short)} · ${esc(g.scorer)}${g.phase==='second'?' <span class="chip">2nd half</span>':''}</li>`).join(''):'<li>No goals.</li>'}</ul>
   <div class="decision-report"><h3>${esc(instruction.label)} — what it did</h3>
    <p>Your instruction ${addedMine?`added ${addedMine} goal(s) for you`:removedMine?`took ${removedMine} goal(s) off you`:'raised your expected goals by '+signed(mean.mine)+'%'}${addedTheirs?`, and the risk told: the opponent added ${addedTheirs}`:removedTheirs?`, and it also removed ${removedTheirs} of theirs`:' and did not change theirs'}.</p>
    ${result.plan.subs.length?`<p>Substitutions: ${result.plan.subs.map(id=>esc(((active.base.players.find(p=>p.id===id))||{}).name||id)).join(', ')}.</p>`:''}
    <p class="muted">Without any half-time change the same world would have finished ${neutralYou?neutralYou[0]+'–'+neutralYou[1]:'the same'}. ${swing}</p></div>
   <div class="stat-row">${[['Form',result.result.toUpperCase()],['Momentum',(active.momentum||[]).join(' ')||'—'],['Fitness',Math.round(active.fitness)+' / 100'],['Credits',active.credits+' cr']].map(([k,v])=>`<div><small>${k}</small><b>${esc(v)}</b></div>`).join('')}</div>`;
  $('continueAfterMatch').focus();
 }
 function neutralYouScore(neutralOwn,club){if(!neutralOwn)return null;return neutralOwn.h===club?[neutralOwn.hg,neutralOwn.ag]:[neutralOwn.ag,neutralOwn.hg];}
 function kickOff(){
  if(!active||session||busy)return;
  const brief=G.beginMatch(active);if(!brief)return;
  try{
   session={stage:'pre',brief,plan:{interaction:'calm',subs:[]},first:G.firstHalf(active),pre:G.clone(active),feed:[],shown:{home:0,away:0},minute:0};
  }catch(err){return error('This fixture could not be prepared.');}
  $('matchReplay').hidden=true;$('nextMatch').hidden=true;$('fullTimePanel').hidden=true;$('halfTimePanel').hidden=true;
  renderCareer();runFirstHalf();
 }
 function skipMatch(){
  if(!active||session||busy)return;
  const committed=G.complete(active,{interaction:'calm',subs:[]});active=committed.state;save();
  const r=committed.result,youHome=r.own&&r.own.h===active.club;
  $('matchStage').hidden=true;$('nextMatch').hidden=false;
  $('matchReplay').hidden=false;
  $('matchReplay').innerHTML=`<p class="eyebrow">SKIPPED · SIMULATED FULL TIME</p><div class="match-versus"><div>${badge(r.own.h)}<strong>${esc(team(r.own.h).short)}</strong></div><b class="score-big">${r.own.hg} – ${r.own.ag}</b><div>${badge(r.own.a)}<strong>${esc(team(r.own.a).short)}</strong></div></div>
   <p class="small muted">You played this one without a half-time call: ${r.result.toUpperCase()}${youHome?'':' away'}. The inbox below has the fallout.</p>`;
  busy=false;renderCareer();notify('Matchday played with no instruction — the inbox is ready.');
 }
 function fast(){
  if(!active||session||busy)return;let count=0;
  while(count<3&&!G.summary(active).done){active=G.complete(active,{interaction:'calm',subs:[]}).state;count++;}
  save();busy=false;$('matchReplay').hidden=true;$('matchStage').hidden=true;$('nextMatch').hidden=false;renderCareer();
  notify(count+' matchdays played with no half-time calls. The inbox holds the last week’s decisions.');
 }
 /* ══════════════ the manager's inbox ══════════════ */
 function renderInbox(){
  const list=$('inboxList');if(!list||!active)return;
  const items=active.inbox||[];
  $('inboxBadge').textContent=items.length?items.length+' waiting':'empty';
  $('inboxTitle').textContent=items.length?'Decisions waiting for you':'Nothing waiting';
  list.innerHTML=items.length?items.map(item=>`<article class="inbox-item" data-item="${esc(item.id)}"><span class="chip">${esc(item.tag||item.type)}</span><h3>${esc(item.title)}</h3><p>${esc(item.body)}</p><div class="row-buttons">${item.choices.map(c=>`<button data-inbox="${esc(item.id)}" data-choice="${esc(c.id)}">${esc(c.label)}<span>${esc(c.detail)}</span></button>`).join('')}</div></article>`).join(''):
   `<p class="empty">${active.step===0?'Play a matchday and the fallout lands here.':'Nothing needs you right now. Play the next matchday.'}</p>`;
  list.querySelectorAll('[data-inbox]').forEach(b=>b.onclick=guarded(()=>{
   const chosenItem=(active.inbox||[]).find(i=>i.id===b.dataset.inbox);
   const label=chosenItem?(chosenItem.choices.find(c=>c.id===b.dataset.choice)||{}).label:'decision';
   const out=G.chooseInbox(active,b.dataset.inbox,b.dataset.choice);
   active=out.state;save();renderCareer();
   notify(label+': '+effectText(out.effect),6500);
  }));
 }
 function exportSave(){if(!active)return;const blob=new Blob([JSON.stringify({kind:'ninety-plus-career',version:1,state:active},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='ninety-plus-career-'+active.club.toLowerCase()+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 function renderMarket(){if(!active)return;const q=$('marketSearch').value.toLowerCase(),done=G.summary(active).done,live=!!session;$('transferStatus').textContent=done?'Season complete':live?'Match in progress':active.transferUsed?'Transaction used this week':'1 transaction / week';const own=new Set(G.roster(active,active.club).map(p=>p.id));const market=active.base.players.filter(p=>!own.has(p.id)||active.bought[p.id]).filter(p=>(p.name+' '+team(G.clubOf(active,p)).name).toLowerCase().includes(q));$('transferMarket').innerHTML=market.map(p=>{const release=own.has(p.id),cost=release?Math.floor(active.bought[p.id]/2):p.price;return `<div class="market-row"><div><strong>${esc(p.name)}</strong><small>${esc(team(G.clubOf(active,p)).short)} · ${esc(p.pos)} · game estimate</small></div><div><div class="cost">${release?'+':''}${cost} cr</div><button data-transfer="${esc(p.id)}" data-release="${release}" ${busy||live||done||active.transferUsed||!release&&active.credits<cost?'disabled':''}>${release?'Release':'Sign'}</button></div></div>`}).join('')||'<p class="empty">No tracked players match that search.</p>';$('transferMarket').querySelectorAll('[data-transfer]').forEach(b=>b.onclick=guarded(()=>{if(session)return;active=G.transfer(active,b.dataset.transfer,b.dataset.release==='true');save();renderCareer();notify('Fantasy transaction saved. Both game clubs change—not the official squads.');}));}
 function goHome(){if(busy||session)return;$('careerActive').hidden=true;$('careerSetup').hidden=false;renderSaves();}
 /* ══════════════ Beat the Model (unchanged rules, phase 16) ══════════════ */
 function records(){const r=STORE?STORE.get('predictionChallenges',[]):[];return Array.isArray(r)?r.slice(0,40):[];}
 function lockedCurrent(){return records().find(r=>r&&r.version===1&&r.season===draft.season&&r.gw===draft.gw&&r.locked);}
 function deadlinePassed(){return !draft.deadline||Date.now()>=Date.parse(draft.deadline);}
 function pickName(p,f){return !p?'No pick yet':p.outcome==='H'?team(f.h).short+' win':p.outcome==='A'?team(f.a).short+' win':'Draw';}
 function renderChallenge(){const locked=lockedCurrent();$('challengeTop').innerHTML=`<b>Matchweek ${draft.gw} · ${draft.fixtures.length} fixtures</b><br>Source snapshot ${esc(niceDate(draft.asOf))} · personal pick deadline ${esc(niceDate(draft.deadline))}, 00:00 UTC (window start).<br>${locked?'Your real picks are locked. Changes below are practice only.':deadlinePassed()?'Real-pick deadline passed. You can still practise without adding retrospective real picks.':'Try a practice round, then lock your real predictions before the window starts.'}`;
  $('challengeFixtures').innerHTML=draft.fixtures.map(f=>{const p=draft.picks[f.id],score=p&&p.score||[1,1],m=draft.model[f.id];return `<article class="prediction-card"><h3>${esc(team(f.h).short)} <span class="muted">v</span> ${esc(team(f.a).short)}</h3><div class="pick-buttons">${[['H','Home win'],['D','Draw'],['A','Away win']].map(([key,name])=>`<button data-pick="${esc(f.id)}" data-outcome="${key}" aria-pressed="${!!p&&p.outcome===key}">${name}</button>`).join('')}</div><div class="exact-row"><label><input type="checkbox" data-exact="${esc(f.id)}" ${p&&p.score?'checked':''}> Exact score</label><input type="number" min="0" max="9" data-score="${esc(f.id)}" data-side="0" value="${score[0]}" aria-label="Predicted ${esc(team(f.h).short)} goals"><span>–</span><input type="number" min="0" max="9" data-score="${esc(f.id)}" data-side="1" value="${score[1]}" aria-label="Predicted ${esc(team(f.a).short)} goals"></div><p class="model-pick">Model pick: ${esc(pickName(m,f))} · consistent score pick ${m.score[0]}–${m.score[1]}</p></article>`}).join('');
  $('challengeFixtures').querySelectorAll('[data-pick]').forEach(b=>b.onclick=()=>{draft.picks[b.dataset.pick]={outcome:b.dataset.outcome,score:null};renderChallenge();});
  $('challengeFixtures').querySelectorAll('[data-exact]').forEach(el=>el.onchange=()=>{const key=el.dataset.exact,p=draft.picks[key]||{outcome:'D',score:null};if(el.checked){p.score=p.outcome==='H'?[2,1]:p.outcome==='A'?[1,2]:[1,1];}else p.score=null;draft.picks[key]=p;renderChallenge();});
  $('challengeFixtures').querySelectorAll('[data-score]').forEach(el=>el.onchange=()=>{const key=el.dataset.score,p=draft.picks[key]||{outcome:'D',score:[1,1]};p.score=p.score||[1,1];const v=Number(el.value);if(!Number.isInteger(v)||v<0||v>9){notify('Use a whole score from 0 to 9.');renderChallenge();return;}p.score[Number(el.dataset.side)]=v;p.outcome=G.outcome(...p.score);draft.picks[key]=p;renderChallenge();});
  $('lockPicks').disabled=!!locked||deadlinePassed();$('lockPicks').textContent=locked?'Real picks locked ✓':'Lock my real picks 🔒';renderChallengeHistory();
 }
 function validateRecord(r){if(!r||r.version!==1||r.season!=='2026-27'||!Number.isInteger(r.gw)||r.gw<1||r.gw>38||!Array.isArray(r.fixtures)||r.fixtures.length>20||!r.locked)throw new Error('Damaged prediction record');if(!Number.isFinite(r.locked)||r.locked<0||typeof r.deadline!=='string'||!Number.isFinite(Date.parse(r.deadline))||r.locked>=Date.parse(r.deadline))throw new Error('Invalid local pick deadline');const seen=new Set();const fixtures=r.fixtures.map(f=>{if(!teams[f.h]||!teams[f.a]||f.id!==f.h+'-'+f.a||f.gw!==r.gw||seen.has(f.id))throw new Error('Invalid saved fixture');seen.add(f.id);return f;});const picks=G.cleanPicks(r.picks,fixtures);G.cleanPicks(r.model,fixtures);if(Object.keys(picks).length!==fixtures.length||Object.keys(r.model||{}).length!==fixtures.length)throw new Error('Incomplete saved picks');return {...r,fixtures,picks};}
 function renderChallengeHistory(){const list=records();$('challengeHistory').innerHTML='<p class="eyebrow">REAL-RESULTS SCORECARD</p><h2>Your locked matchdays</h2>'+(list.length?list.map(raw=>{try{const r=validateRecord(raw),actual=PLAY_DATA.challenge.actual.filter(a=>a.gw===r.gw),score=G.scoreChallenge(r.picks,r.model,actual,r.fixtures);return `<div class="notebook-item"><strong>MW${r.gw} · You ${score.you} / Model ${score.model}</strong><small>${score.scored} actually played, ${score.pending} pending. Frozen picks; client-local timestamp, not independently verified.</small><details style="margin-top:10px"><summary>View my locked predictions</summary><ul>${r.fixtures.map(f=>`<li>${esc(team(f.h).short)} v ${esc(team(f.a).short)}: ${esc(pickName(r.picks[f.id],f))}${r.picks[f.id].score?' · '+r.picks[f.id].score.join('–'):''}</li>`).join('')}</ul></details></div>`}catch(err){return '<p class="empty">A saved challenge could not be validated. No real points awarded.</p>'}}).join(''):'<p class="empty">No locked matchdays yet. Practice results never appear here as real points.</p>');}
 function practise(){const picks=G.cleanPicks(draft.picks,draft.fixtures);if(Object.keys(picks).length!==draft.fixtures.length){notify('Make a pick for every match first.');return;}const results=draft.fixtures.map(f=>{const [hg,ag]=G.sample(f.lh,f.la,G.rand(G.salt(practiceSeed,f.id)));return {id:f.id,hg,ag};}),score=G.scoreChallenge(picks,draft.model,results,draft.fixtures);$('challengeFeedback').innerHTML=`<section class="box reveal"><p class="eyebrow">PRACTICE ONLY · SIMULATED ROUND ${practiceSeed}</p><h2>${score.you>score.model?'You beat the model in this practice world.':score.you===score.model?'Honours even.':'The model takes this practice round.'}</h2><div class="score-board"><div><b>${score.you}</b><span>Your practice points</span></div><span>VS</span><div><b>${score.model}</b><span>Model practice points</span></div></div><div class="table-scroll" tabindex="0" role="region" aria-label="Practice results"><table><caption class="small muted" style="text-align:left">Fictional scores—not scored as real results</caption><thead><tr><th scope="col">Fixture</th><th scope="col">Sim score</th><th scope="col">You</th><th scope="col">Model</th></tr></thead><tbody>${score.rows.map(r=>`<tr><th scope="row">${esc(r.id)}</th><td>${r.hg}–${r.ag}</td><td>${r.you}</td><td>${r.model}</td></tr>`).join('')}</tbody></table></div></section>`;$('challengeFeedback').scrollIntoView({behavior:reduced?'auto':'smooth',block:'start'});}
 function lock(){if(lockedCurrent()||deadlinePassed())throw new Error('Real picks cannot be changed after the deadline/lock. Practice is still available.');const picks=G.cleanPicks(draft.picks,draft.fixtures);if(Object.keys(picks).length!==draft.fixtures.length)throw new Error('Make a pick for every match before locking.');const record={version:1,season:draft.season,gw:draft.gw,deadline:draft.deadline,asOf:draft.asOf,fixtures:G.clone(draft.fixtures),model:G.clone(draft.model),picks,locked:Date.now()};const list=records();list.unshift(record);STORE.set('predictionChallenges',list.slice(0,40));updateStorage();renderChallenge();notify('Real picks locked on this device. Practice stays separate.');}
 $('careerTab').onclick=()=>mode('career');$('challengeTab').onclick=()=>mode('challenge');$('clubSearch').oninput=renderClubs;$('marketSearch').oninput=renderMarket;
 document.querySelector('.mode-tabs').addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const challenge=e.key==='End'||e.key==='ArrowRight'&&$('careerTab').getAttribute('aria-selected')==='true'||e.key==='ArrowLeft'&&$('challengeTab').getAttribute('aria-selected')!=='true';mode(challenge?'challenge':'career');$(challenge?'challengeTab':'careerTab').focus();});
 $('startCareer').onclick=guarded(()=>{if(saved().length>=3)throw new Error('Three slots are full. Export/delete an older career first.');active=G.create(BASE,chosen,Number($('worldSeed').value));activeId=careerId();session=null;save();openCareer();});
 $('kickOff').onclick=guarded(kickOff);$('secondHalf').onclick=guarded(playSecondHalf);
 $('continueAfterMatch').onclick=guarded(()=>{session=null;busy=false;$('matchStage').hidden=true;$('halfTimePanel').hidden=true;$('fullTimePanel').hidden=true;$('nextMatch').hidden=false;renderCareer();notify('The manager’s inbox has something for you.');});
 $('skipReveal').onclick=guarded(()=>{if(!session)return;if(session.stage==='first'){clearTimeout(timer);session.first.goals.forEach(g=>session.feed.push({minute:g.minute,kind:'goal',text:`GOAL — ${g.scorer} for ${team(g.side==='h'?session.first.fixture.h:session.first.fixture.a).short}.`}));const hg=session.first.goals.filter(g=>g.side==='h').length,ag=session.first.goals.filter(g=>g.side==='a').length;session.shown={home:hg,away:ag};session.minute=45;session.stage='half';showHalfTime();paintStage();}
  else if(session.stage==='second'){clearTimeout(timer);session.shown={home:session.result.own.hg,away:session.result.own.ag};session.stage='full';showFullTime();paintStage();}});
 $('playRound').onclick=guarded(skipMatch);$('fastForward').onclick=guarded(fast);$('careerHome').onclick=goHome;$('exportCareer').onclick=exportSave;
 $('importCareer').onchange=guarded(async()=>{const f=$('importCareer').files[0];if(!f)return;if(f.size>350000){error('Career backup exceeds 350 KB.');return;}try{const data=JSON.parse(await f.text());if(data.kind!=='ninety-plus-career'||data.version!==1)throw new Error('Unsupported backup format');const restored=G.restore(data.state);if(saved().length>=3)throw new Error('Export/delete a save slot first.');active=restored;activeId=careerId();session=null;save();openCareer();notify('Frozen career restored. Current official data has not been changed.');}catch(err){error('Backup could not be validated: use a supported career JSON and an available save slot.');}$('importCareer').value='';});
 $('practiceRound').onclick=guarded(practise);$('lockPicks').onclick=guarded(lock);$('challengeNew').onclick=()=>{draft.picks={};$('challengeFeedback').innerHTML='';renderChallenge();notify(lockedCurrent()||deadlinePassed()?'Practice picks cleared; real locked picks are unchanged.':'Draft picks cleared.');};$('challengeReplay').onclick=()=>{practiceSeed=(practiceSeed+1)>>>0;notify('New practice seed '+practiceSeed+'. Real picks remain unchanged.');};
 const seedText=query.get('seed'),seed=seedText!==null&&/^\d+$/.test(seedText)&&Number(seedText)<=4294967295?Number(seedText):Math.floor(Math.random()*1000000);$('worldSeed').value=seed;
 $('worldSource').textContent=`Start from results through ${niceDate(BASE.asOf)}. All remaining matchdays are simulated.`;
 if(query.get('world')&&query.get('world')!==BASE.hash)error('This link refers to older starting data. Import its exported save to continue that exact frozen world.');
 renderClubs();renderSaves();renderChallenge();updateStorage();mode(query.get('mode')==='challenge'?'challenge':'career');
 window.NT90_PLAY={getCareer:()=>active,summary:()=>active&&G.summary(active),getDraft:()=>G.clone(draft),getSaves:saved,isBusy:()=>busy||!!session,
  getSession:()=>session&&{stage:session.stage,plan:G.clone(session.plan),minute:session.minute,shown:G.clone(session.shown),feed:session.feed.slice()},
  getInbox:()=>(active&&active.inbox||[]).map(i=>i.id),chooseInbox:(item,choice)=>{const out=G.chooseInbox(active,item,choice);active=out.state;save();renderCareer();return out.effect;}};
})();
