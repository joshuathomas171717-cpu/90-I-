/* NINETY+ Club Manager — matchday engine (v2). Original management sandbox, not EA assets/code.
 *
 * v2 adds the thing v1 lacked: decisions DURING a match and consequences AFTER it. A round is played
 * as a session — kickoff, first half, half-time instruction + substitutions, second half, full time —
 * followed by a manager's inbox whose items each carry a real, bounded game effect.
 *
 * Rules that keep it honest and deterministic:
 *  · The full-time score is still the same single draw as v1 (same seed, same sampler), so a v1 save
 *    replays to exactly the results the user saw, and 'stay calm' + no subs is byte-identical to v1.
 *  · An instruction can only ADD or REMOVE goals through a second, separate draw, bounded per match.
 *    Nothing is rerolled: the narrative minutes, the half-time score and the extra goals are all
 *    deterministic functions of the world seed and fixture id.
 *  · Simulated scores never enter official prediction, result or ledger data.
 */
(function(root){
 'use strict';
 const VERSION=2, RULES='club-manager/2';
 const TACTICS={balanced:{attack:0,defence:0,cost:5},attacking:{attack:12,defence:8,cost:10},defensive:{attack:-8,defence:-10,cost:4},pressing:{attack:7,defence:3,cost:14}};
 const TRAINING={recovery:{attack:0,defence:0,fitness:12},attack:{attack:4,defence:0,fitness:-4},defence:{attack:0,defence:-4,fitness:-3}};
 /* Half-time instructions. self/theirs are mean goal deltas for YOUR side and the opponent, applied in
    the second half only. Negative means "a chance of that many goals being taken away". */
 const INSTRUCTIONS={
  calm:{label:'Stay calm',detail:'Keep the shape and the plan. Nothing gambled.',self:0,theirs:0,cost:0},
  push:{label:'Push forward',detail:'Chase the game. More chances for us — and for them.',self:.34,theirs:.22,cost:6},
  hold:{label:'Hold the lead',detail:'Slow it down and protect what we have.',self:-.22,theirs:-.14,cost:3},
  press:{label:'Press high',detail:'Win it up the pitch. Costs legs, opens space behind.',self:.24,theirs:.30,cost:10},
 };
 const MAX_SUBS=2, MAX_INBOX=4, POISSON_CAP=6;
 const clone=x=>JSON.parse(JSON.stringify(x));
 const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
 const badIds=new Set(['__proto__','constructor','prototype']);
 function number(x,a,b,integer=false){if(typeof x!=='number'||!Number.isFinite(x)||x<a||x>b||integer&&!Number.isInteger(x))throw new Error('Invalid numeric game field');return x;}
 function label(x,n=100){if(typeof x!=='string'||x.length>n)throw new Error('Invalid text game field');return x;}
 function id(x){if(typeof x!=='string'||!/^[A-Za-z0-9_-]{1,60}$/.test(x)||badIds.has(x))throw new Error('Invalid player identifier');return x;}
 function code(x){if(typeof x!=='string'||!/^[A-Z]{2,4}$/.test(x))throw new Error('Invalid club');return x;}
 function cleanBase(raw){
  if(!raw||raw.version!==VERSION||raw.rules!==RULES||raw.season!=='2026-27')throw new Error('Unsupported career world version/season');
  if(!Array.isArray(raw.teams)||raw.teams.length!==20||!Array.isArray(raw.fixtures)||raw.fixtures.length>380||!Array.isArray(raw.players)||raw.players.length>200)throw new Error('Invalid career world size');
  const clubs=new Set(),ids=new Set(),keys=new Set();
  const teams=raw.teams.map(t=>{code(t.code);if(clubs.has(t.code))throw new Error('Duplicate club');clubs.add(t.code);return {code:t.code,name:label(t.name),short:label(t.short,40),color:/^#[a-f0-9]{6}$/i.test(t.color)?t.color:'#2dd4bf',p:number(t.p,0,38,true),w:number(t.w,0,38,true),d:number(t.d,0,38,true),l:number(t.l,0,38,true),gf:number(t.gf,0,300,true),ga:number(t.ga,0,300,true),pts:number(t.pts,-30,114,true),target:number(t.target,1,20,true)};});
  const fixtures=raw.fixtures.map(f=>{if(!clubs.has(f.h)||!clubs.has(f.a)||f.h===f.a)throw new Error('Invalid fixture clubs');const key=f.h+'-'+f.a;if(keys.has(key))throw new Error('Duplicate fixture');keys.add(key);return {id:key,gw:number(f.gw,1,38,true),h:f.h,a:f.a,lh:number(f.lh,.1,6),la:number(f.la,.1,6),dates:label(f.dates,80)};}).sort((a,b)=>a.gw-b.gw||a.id.localeCompare(b.id));
  const players=raw.players.map(p=>{id(p.id);if(ids.has(p.id)||!clubs.has(p.club)||!['GK','DEF','MID','FWD'].includes(p.pos))throw new Error('Invalid tracked player');ids.add(p.id);return {id:p.id,name:label(p.name),club:p.club,pos:p.pos,attack:number(p.attack,0,30),defence:number(p.defence,0,25),price:number(p.price,20,90,true),source:label(p.source||'source unavailable',160)};});
  if(!/^\d{4}-\d{2}-\d{2}$/.test(raw.asOf)||!/^\w{16,64}$/.test(raw.hash))throw new Error('Invalid world provenance');
  return {version:VERSION,rules:RULES,season:'2026-27',hash:raw.hash,asOf:raw.asOf,teams,players,fixtures};
 }
 function rand(seed){let x=(seed>>>0)||0x6d2b79f5;x^=x<<13;x^=x>>>17;x^=x<<5;return (x>>>0)/4294967296;}
 function salt(seed,key){let h=(seed>>>0)^2166136261;for(let i=0;i<key.length;i++)h=Math.imul(h^key.charCodeAt(i),16777619);return h>>>0;}
 function matrix(lh,la){
  const ph=[Math.exp(-lh)],pa=[Math.exp(-la)];for(let i=1;i<=6;i++){ph.push(ph[i-1]*lh/i);pa.push(pa[i-1]*la/i);}
  const cells=[];let total=0;
  for(let h=0;h<=6;h++)for(let a=0;a<=6;a++){let p=ph[h]*pa[a],rho=-.11;if(h===0&&a===0)p*=1-lh*la*rho;else if(h===0&&a===1)p*=1+lh*rho;else if(h===1&&a===0)p*=1+la*rho;else if(h===1&&a===1)p*=1-rho;p=Math.max(0,p);cells.push({h,a,p});total+=p;}
  return cells.map(c=>({...c,p:c.p/total}));
 }
 function sample(lh,la,u){const cells=matrix(lh,la);let sum=0;for(const c of cells){sum+=c.p;if(u<sum)return [c.h,c.a];}return [6,6];}
 /* Single-side Poisson count by inverse CDF — deterministic, used only for second-half deltas. */
 function poisson(lambda,u){if(lambda<=0)return 0;let p=Math.exp(-lambda),c=p,k=0;while(u>c&&k<POISSON_CAP){k++;p*=lambda/k;c+=p;}return k;}
 function probabilities(lh,la){let h=0,d=0,a=0;matrix(lh,la).forEach(c=>{if(c.h>c.a)h+=c.p;else if(c.h<c.a)a+=c.p;else d+=c.p;});return {h:Math.round(h*1000)/10,d:Math.round(d*1000)/10,a:Math.round(a*1000)/10};}
 function rank(table){return [...table].sort((a,b)=>b.pts-a.pts||(b.gf-b.ga)-(a.gf-a.ga)||b.gf-a.gf||a.code.localeCompare(b.code));}
 function rounds(state){return [...new Set(state.base.fixtures.map(f=>f.gw))];}
 function fixturesNow(state){const gw=rounds(state)[state.step];return state.base.fixtures.filter(f=>f.gw===gw);}
 function clubOf(state,player){return state.moves[player.id]||player.club;}
 function roster(state,club){return state.base.players.filter(p=>clubOf(state,p)===club);}
 function ownFixture(state){return fixturesNow(state).find(f=>f.h===state.club||f.a===state.club)||null;}
 function emptyBoosts(){return {attack:0,defence:0,expires:0,note:''};}
 function create(raw,club,seed){
  const base=cleanBase(raw);if(!base.teams.some(t=>t.code===club))throw new Error('Choose a current club');number(seed,0,4294967295,true);
  return {v:VERSION,base,club,seed:seed>>>0,step:0,table:clone(base.teams),control:clone(base.teams),credits:100,fitness:100,tactic:'balanced',training:'recovery',rested:[],moves:{},bought:{},transferUsed:false,pending:[],pendingInbox:[],inbox:[],pressure:0,momentum:[],boosts:emptyBoosts(),journal:[],last:null};
 }
 function configure(raw,patch){
  const s=clone(raw);if(s.step>=rounds(s).length)throw new Error('Career season is finished');
  if(patch.tactic!==undefined){if(!TACTICS[patch.tactic])throw new Error('Unknown tactic');s.tactic=patch.tactic;}
  if(patch.training!==undefined){if(!TRAINING[patch.training])throw new Error('Unknown training');s.training=patch.training;}
  if(patch.rested!==undefined){if(!Array.isArray(patch.rested)||patch.rested.length>20)throw new Error('Invalid rested stars');const own=new Set(roster(s,s.club).map(p=>p.id));s.rested=[...new Set(patch.rested.map(id))];if(s.rested.some(p=>!own.has(p)))throw new Error('Only rest a player at your club');}
  return s;
 }
 function transfer(raw,pid,release=false){
  const s=clone(raw),p=s.base.players.find(p=>p.id===pid);if(!p||s.transferUsed||s.step>=rounds(s).length)throw new Error('One transfer transaction per matchday');
  if(release){if(!s.bought[pid]||clubOf(s,p)!==s.club)throw new Error('Only release a signed player');s.credits+=Math.floor(s.bought[pid]/2);delete s.moves[pid];delete s.bought[pid];s.rested=s.rested.filter(x=>x!==pid);}
  else {if(clubOf(s,p)===s.club||s.credits<p.price)throw new Error('Not enough credits or already at your club');s.credits-=p.price;s.moves[pid]=s.club;s.bought[pid]=p.price;}
  s.transferUsed=true;s.pending.push({pid,release});return s;
 }
 function modifiers(s){
  const mods=Object.fromEntries(s.base.teams.map(t=>[t.code,{attack:0,defence:0}]));
  s.base.players.forEach(p=>{const to=clubOf(s,p);if(to!==p.club){mods[p.club].attack-=p.attack;mods[p.club].defence+=p.defence;mods[to].attack+=p.attack*.75;mods[to].defence-=p.defence*.75;}});
  const own=mods[s.club],t=TACTICS[s.tactic],train=TRAINING[s.training],effectiveFitness=clamp(s.fitness+train.fitness,25,100);
  own.attack+=t.attack+train.attack-(100-effectiveFitness)*.15;own.defence+=t.defence+train.defence+(100-effectiveFitness)*.10;
  roster(s,s.club).forEach(p=>{if(s.rested.includes(p.id)){own.attack-=p.attack;own.defence+=p.defence;}});
  const boost=s.boosts||emptyBoosts();
  if(boost.expires===s.step&&(boost.attack||boost.defence)){own.attack+=boost.attack;own.defence+=boost.defence;}
  Object.values(mods).forEach(m=>{m.attack=clamp(m.attack,-30,30);m.defence=clamp(m.defence,-25,25);});return mods;
 }
 function lambdas(s,f){const m=modifiers(s),h=m[f.h],a=m[f.a];return [clamp(f.lh*(1+h.attack/100)*(1+a.defence/100),.2,5),clamp(f.la*(1+a.attack/100)*(1+h.defence/100),.2,5)];}
 function preview(s){const f=ownFixture(s);if(!f)return null;const [lh,la]=lambdas(s,f);return {...f,lh,la,prob:probabilities(lh,la),original:probabilities(f.lh,f.la)};}
 function apply(table,f,score){const h=table.find(t=>t.code===f.h),a=table.find(t=>t.code===f.a),[hg,ag]=score;h.p++;a.p++;h.gf+=hg;h.ga+=ag;a.gf+=ag;a.ga+=hg;if(hg>ag){h.w++;h.pts+=3;a.l++;}else if(ag>hg){a.w++;a.pts+=3;h.l++;}else{h.d++;a.d++;h.pts++;a.pts++;}}

 /* ── the narrative: which minute each goal was scored in, from the same world seed ─────────────── */
 function sideGoals(s,f,side,count){
  const out=[];for(let i=0;i<count;i++){const u=rand(salt(s.seed,f.id+'g'+side+i));out.push({side,index:i,minute:1+Math.floor(u*90)});}
  return out;
 }
 function narrative(s,f,score){
  return [...sideGoals(s,f,'h',score[0]),...sideGoals(s,f,'a',score[1])].sort((a,b)=>a.minute-b.minute||a.side.localeCompare(b.side));
 }
 function scorerFor(s,f,side,index,rested){
  const seed=salt(s.seed,f.id+'sc'+side+index);
  if((side==='h'&&f.h===s.club)||(side==='a'&&f.a===s.club)){
   const pool=roster(s,s.club).filter(p=>p.pos!=='GK'&&!(rested||[]).includes(p.id));
   if(pool.length)return pool[Math.floor(rand(seed)*pool.length)].name;
  }
  return 'Team goal';
 }
 /* Full-time base score: the same single draw v1 used, so nothing is rerolled and neutral == v1. */
 function baseScore(s,f){const [lh,la]=lambdas(s,f);return sample(lh,la,rand(salt(s.seed,f.id+'@'+f.gw)));}
 function cleanPlan(raw){
  const plan=raw||{};if(!INSTRUCTIONS[plan.interaction])throw new Error('Unknown half-time instruction');
  if(plan.interaction==='calm'&&plan.subs===undefined)return {interaction:'calm',subs:[]};
  if(plan.subs!==undefined&&(!Array.isArray(plan.subs)||plan.subs.length>MAX_SUBS))throw new Error('At most '+MAX_SUBS+' substitutions');
  return {interaction:plan.interaction,subs:[...new Set((plan.subs||[]).map(id))]};
 }
 /* Instruction + subs → second-half goal deltas, each from its own deterministic draw. */
 function applyPlan(s,f,plan,base){
  const instruction=INSTRUCTIONS[plan.interaction],youHome=f.h===s.club;
  let mine=instruction.self,theirs=instruction.theirs;
  plan.subs.forEach(pid=>{const p=s.base.players.find(x=>x.id===pid);if(!p||clubOf(s,p)!==s.club)throw new Error('Only bring on a player at your club');
   if(p.pos==='FWD'||p.pos==='MID')mine+=.12;else theirs-=.10;});
  const clampMean=v=>clamp(v,-.6,.6);mine=clampMean(mine);theirs=clampMean(theirs);
  const mineMean=youHome?mine:theirs,theirsMean=youHome?theirs:mine;
  let [hg,ag]=base;
  const addMine=poisson(Math.max(0,mineMean),rand(salt(s.seed,f.id+'i0')));
  const addTheirs=poisson(Math.max(0,theirsMean),rand(salt(s.seed,f.id+'i1')));
  const addHome=youHome?addMine:addTheirs,addAway=youHome?addTheirs:addMine;
  const removeHome=youHome?removed(hg,Math.min(0,mineMean)):removed(hg,Math.min(0,theirsMean));
  const removeAway=youHome?removed(ag,Math.min(0,theirsMean)):removed(ag,Math.min(0,mineMean));
  return {score:[Math.max(0,hg+addHome-removeHome),Math.max(0,ag+addAway-removeAway)],
          added:{home:addHome,away:addAway},removed:{home:removeHome,away:removeAway},
          means:{mine:mineMean,theirs:theirsMean}};
 }
 function removed(goals,delta){if(delta>=0||goals<=0)return 0;let n=0;const p=Math.min(.6,-delta);
  for(let i=0;i<goals;i++)if(rand(salt(delta*1000|0,goals+'-'+i))<p)n++;return Math.min(goals,n);}

 /* ── the session API ─────────────────────────────────────────────────────────────────────────── */
 function beginMatch(raw){
  const s=clone(raw),f=ownFixture(s);if(!f)return null;
  const [lh,la]=lambdas(s,f),seed=salt(s.seed,f.id+'atmo');
  const weather=['clear','breezy','wet'][Math.floor(rand(seed)*3)];
  const attendance=18000+Math.floor(rand(seed+7)*42000);
  const firstHalf=Math.round(lh*.46),firstHalfAway=Math.round(la*.46);
  return {gw:f.gw,fixture:clone(f),lh,la,prob:probabilities(lh,la),original:probabilities(f.lh,f.la),
          weather,attendance,instructions:clone(INSTRUCTIONS),
          subsPool:roster(s,s.club).filter(p=>!s.rested.includes(p.id)).map(p=>({id:p.id,name:p.name,pos:p.pos})),
          restedCount:s.rested.length,
          firstHalfHint:{home:Math.max(0,firstHalf),away:Math.max(0,firstHalfAway)}};
 }
 function firstHalf(raw){
  const s=clone(raw),f=ownFixture(s);if(!f)throw new Error('No fixture to play');
  const base=baseScore(s,f),rested=s.rested;
  const minutes=narrative(s,f,base).filter(g=>g.minute<=45)
    .map(g=>({minute:g.minute,side:g.side,scorer:scorerFor(s,f,g.side,g.index,rested)}));
  const hg=minutes.filter(g=>g.side==='h').length,ag=minutes.filter(g=>g.side==='a').length;
  const youHome=f.h===s.club,seed=salt(s.seed,f.id+'h1'),[lh,la]=lambdas(s,f);
  const total=lh+la||1;
  return {fixture:clone(f),base:{home:base[0],away:base[1]},goals:minutes,score:{home:hg,away:ag},
          yours:{goals:youHome?hg:ag,conceded:youHome?ag:hg},
          lead:youHome?hg-ag:ag-hg,
          stats:{possession:clamp(Math.round(38+52*(youHome?lh:la)/total),32,68),
                 shots:{home:Math.max(0,Math.round((youHome?lh:la)*(9+rand(seed)*5)))},
                 onTarget:{home:Math.min(Math.max(0,Math.round((youHome?lh:la)*4+rand(seed+9))),12)},
                 share:clamp(Math.round(30+56*(youHome?la:lh)/total),28,72)}};
 }
/* v1-compatible: no instruction, no subs, no inbox side effects inside this call. */
 function advance(raw){return complete(raw,{interaction:'calm',subs:[]},{skipInbox:false}).state;}
 function complete(raw,rawPlan,options){
  const opts=options||{},s=clone(raw);if(s.step>=rounds(s).length)throw new Error('Career season is finished');
  const plan=cleanPlan(rawPlan),fixtures=fixturesNow(s),settings={tactic:s.tactic,training:s.training,rested:[...s.rested],transfers:clone(s.pending)};
  const scores=[],controlScores=[];
  for(const f of fixtures){
    const base=baseScore(s,f),original=sample(f.lh,f.la,rand(salt(s.seed,f.id+'@'+f.gw)));
    const isOwn=f.h===s.club||f.a===s.club;
    const outcomeScore=isOwn?applyPlan(s,f,plan,base).score:base;
    apply(s.table,f,outcomeScore);apply(s.control,f,original);
    scores.push({id:f.id,gw:f.gw,h:f.h,a:f.a,hg:outcomeScore[0],ag:outcomeScore[1]});
    controlScores.push({id:f.id,gw:f.gw,h:f.h,a:f.a,hg:original[0],ag:original[1]});
  }
  const own=scores.find(r=>r.h===s.club||r.a===s.club);
  const ownFixtureNow=fixtures.find(f=>f.h===s.club||f.a===s.club)||null;
  const detail=own&&ownFixtureNow?(()=>{
    const base=baseScore(s,ownFixtureNow),effect=applyPlan(s,ownFixtureNow,plan,base);
    return {base,effect,goals:narrative(s,ownFixtureNow,effect.score),plan};
  })():null;
  if(own&&detail){
    const goals=detail.goals.map(g=>({...g,scorer:scorerFor(s,ownFixtureNow,g.side,g.index,settings.rested),phase:g.minute<=45?'first':'second'}));
    const gf=own.h===s.club?own.hg:own.ag,ga=own.h===s.club?own.ag:own.hg;
    s.credits+=2+(gf>ga?3:gf===ga?1:0);
    s.fitness=clamp(s.fitness+TRAINING[s.training].fitness-TACTICS[s.tactic].cost-INSTRUCTIONS[plan.interaction].cost+5,25,100);
    s.momentum=[...s.momentum,gf>ga?'W':gf===ga?'D':'L'].slice(-6);
    s.last={gw:fixtures[0].gw,scores,controlScores,own,settings,plan,goals,
            effect:detail.effect,base:detail.base,
            goalsFor:gf,goalsAgainst:ga,result:gf>ga?'win':gf===ga?'draw':'loss',
            lateConceded:goals.filter(g=>g.phase==='second'&&(own.h===s.club?g.side==='a':g.side==='h')).length};
  } else s.last={gw:fixtures[0].gw,scores,controlScores,own:null,settings,plan,goals:[],result:'none'};
  s.journal.push({gw:fixtures[0].gw,...settings,plan,inbox:clone(s.pendingInbox),own:clone(own||null)});
  s.pending=[];s.pendingInbox=[];s.transferUsed=false;s.rested=[];
  if(s.boosts&&s.boosts.expires===s.step)s.boosts=emptyBoosts();
  s.step++;
  if(!opts.skipInbox)s.inbox=buildInbox(s,opts.inboxPlan);
  return {state:s,result:clone(s.last)};
 }

 /* ── the manager's inbox: a few items, each with bounded, replayable effects ──────────────────── */
 function mood(s,last){return s.pressure>=4?'under pressure':last&&last.result==='win'?'confident':'steady';}
 function buildInbox(s,plan){
  const items=[],last=s.last,gw=rounds(s)[s.step-1],failing=failedObjective(s),seed=salt(s.seed,'inbox'+gw);
  if(last&&last.result&&last.result!=='none'){
    const result=last.result;
    items.push({id:'reaction-'+gw,type:'reaction',tag:'The dressing room',
      title:result==='win'?'A win to build on':result==='draw'?'A point, and a question':'A result to answer for',
      body:result==='win'?'The board wants the same intensity next week. So does the crowd.'
          :result==='draw'?'One point. The board would rather see a decision made than another stalemate.'
          :'The board is asking what changes next week.',
      choices:[{id:'quiet',label:'Keep everyone calm',detail:'+4 fitness next matchday'},
               {id:'demand',label:'Demand more in training',detail:'+2 attack, −3 fitness'},
               {id:'promise',label:'Promise the fans a response',detail:'+6 credits in ticket goodwill'}]});
    const firstScorer=(last.goals||[]).find(g=>g.side===(last.own.h===s.club?'h':'a')&&g.phase==='second')||(last.goals||[]).find(g=>g.side===(last.own.h===s.club?'h':'a'));
    if(firstScorer&&firstScorer.scorer!=='Team goal')
      items.push({id:'players-'+gw,type:'player',tag:'Your squad',
        title:firstScorer.scorer+' is the talking point',
        body:'The staff think a decision about them now sets the tone for the month.',
        choices:[{id:'protect',label:'Manage their minutes',detail:'Rest them next matchday'},
                 {id:'trust',label:'Keep them on the pitch',detail:'+2 attack next match'},
                 {id:'talk',label:'Sit down with them',detail:'+1 fitness and +2 credits'}]});
    if((last.lateConceded||0)>0)
      items.push({id:'shape-'+gw,type:'setback',tag:'The analyst',
        title:'We conceded after the break again',
        body:last.lateConceded+' goal(s) came after half-time. The shape is drifting when we are asked a question.',
        choices:[{id:'drill',label:'Defensive drills this week',detail:'−3 conceded-goal rate next match'},
                 {id:'ignore',label:'No change — the result mattered',detail:'Nothing applied'}]});
  }
  if(gw>=8&&failing&&rand(seed)<.75){
    const others=[...s.base.teams].filter(t=>t.code!==s.club).sort((a,b)=>a.code.localeCompare(b.code));
    const target=others[Math.floor(rand(seed+3)*others.length)];
    items.push({id:'job-'+gw,type:'job',tag:'The boardroom',club:target.code,
      title:target.name+' are asking about you',
      body:'Your board is unhappy with the league position. A move would reset the objective — and the world with it.',
      choices:[{id:'stay',label:'Stay and fix it',detail:'+8 fitness, pressure falls'},
               {id:'take',label:'Take the job at '+target.short,detail:'Swap clubs, +10 credits, new target'}]});
  }
  if(s.credits>=28&&rand(salt(s.seed,'budget'+gw))<.4)
    items.push({id:'budget-'+gw,type:'budget',tag:'The boardroom',
      title:'There is money this month',
      body:'The board can release 14–22 extra fictional credits for the transfer market.',
      choices:[{id:'accept',label:'Bank the funds',detail:'+fictional credits for signings'},
               {id:'decline',label:'Put it into the training ground',detail:'+3 attack, +3 defence next match'}]});
  return items.slice(0,MAX_INBOX);
 }
 function failedObjective(s){
  const ordered=rank(s.table),position=ordered.findIndex(t=>t.code===s.club)+1;
  const target=s.base.teams.find(t=>t.code===s.club).target;
  return position>target;
 }
 function choiceEffect(s,item,choiceId){
  switch(item.type){
   case 'reaction': return choiceId==='quiet'?{fitness:4}:choiceId==='demand'?{boost:{attack:2},fitness:-3}:{credits:6};
   case 'player': return choiceId==='protect'?{rest_next:[item.player]}:
    choiceId==='trust'?{boost:{attack:2}}:{fitness:1,credits:2};
   case 'setback': return choiceId==='drill'?{boost:{defence:-3}}:{};
   case 'job': return choiceId==='take'?{club:item.club,credits:10,pressure:-2,objective_reset:true}:{fitness:8,pressure:2};
   case 'budget': return choiceId==='accept'?{credits:14+Math.floor(rand(salt(s.seed,'budget-amount'+item.id))*9)}:{boost:{attack:3,defence:-3}};
   default: throw new Error('Unknown inbox item');
  }
 }
 function chooseInbox(raw,itemId,choiceId){
  const s=clone(raw),index=s.inbox.findIndex(i=>i.id===itemId);
  if(index<0)throw new Error('That inbox item is not open');
  const item=s.inbox[index],choice=item.choices.find(c=>c.id===choiceId);
  if(!choice)throw new Error('Unknown reply to that item');
  const effect=choiceEffect(s,item,choiceId);
  if(effect.credits)s.credits=clamp(s.credits+effect.credits,0,300);
  if(effect.fitness)s.fitness=clamp(s.fitness+effect.fitness,25,100);
  if(effect.boost){
   const cur=s.boosts||emptyBoosts(),attack=Number(cur.attack)||0,defence=Number(cur.defence)||0;
   s.boosts={attack:clamp(attack+(Number(effect.boost.attack)||0),-8,8),
             defence:clamp(defence+(Number(effect.boost.defence)||0),-8,8),expires:s.step,note:label(item.title,80)};
  }
  if(effect.pressure)s.pressure=clamp(s.pressure+effect.pressure,0,12);
  if(effect.rest_next){const own=new Set(roster(s,s.club).map(p=>p.id));const pid=effect.rest_next[0];if(own.has(pid))s.rested=[...new Set([...s.rested,pid])];}
  if(effect.club){if(!s.base.teams.some(t=>t.code===effect.club))throw new Error('Invalid job club');s.club=effect.club;s.pressure=0;}
  s.inbox=s.inbox.filter(i=>i.id!==itemId);
  s.pendingInbox.push({item:itemId,type:item.type,choice:choiceId,effect:clone(effect)});
  return {state:s,effect,resolved:{item:clone(item),choice:clone(choice)}};
 }
 function restore(raw){
  if(!raw||(raw.v!==VERSION&&raw.v!==1)||!Array.isArray(raw.journal)||raw.journal.length>38||!Array.isArray(raw.pending)||raw.pending.length>1)throw new Error('Unsupported or damaged career save');
  const migrated=raw.v===1;
  let s=create(raw.base,code(raw.club),number(raw.seed,0,4294967295,true));
  for(const entry of raw.journal){
    if(entry.gw!==rounds(s)[s.step]||!Array.isArray(entry.transfers)||entry.transfers.length>1)throw new Error('Career journal is out of order');
    for(const tx of entry.transfers){if(typeof tx.release!=='boolean')throw new Error('Invalid transfer');s=transfer(s,id(tx.pid),tx.release);}
    s=configure(s,{tactic:entry.tactic,training:entry.training,rested:entry.rested});
    // Inbox replies between matchdays are replayed against the *rebuilt* inbox for that week. The
    // items are a deterministic function of the state after the previous match, so the same ids exist.
    if(Array.isArray(entry.inbox)&&entry.inbox.length)s.inbox=buildInbox(s);
    for(const choice of entry.inbox||[]){s=chooseInbox(s,id(choice.item),id(choice.choice)).state;}
    s=complete(s,entry.plan||{interaction:'calm',subs:[]},{skipInbox:true}).state;
  }
  if(s.step<rounds(s).length){
    for(const tx of raw.pending){if(typeof tx.release!=='boolean')throw new Error('Invalid transfer');s=transfer(s,id(tx.pid),tx.release);}
    if(Array.isArray(raw.pendingInbox)&&raw.pendingInbox.length)s.inbox=buildInbox(s);
    for(const choice of raw.pendingInbox||[]){s=chooseInbox(s,id(choice.item),id(choice.choice)).state;}
    s=configure(s,{tactic:raw.tactic,training:raw.training,rested:raw.rested});
  }
  if(!migrated&&!s.inbox.length&&s.step>0&&s.step<rounds(s).length)s.inbox=buildInbox(s);
  if(migrated)s.migrated=true;   // a v1 save keeps its results; only the old rules layer is absent
  return s; // Recompute every derived value; never trust editable totals or inbox effects.
 }
 function summary(s){const table=rank(s.table),position=table.findIndex(t=>t.code===s.club)+1,team=table[position-1],control=s.control.find(t=>t.code===s.club),target=s.base.teams.find(t=>t.code===s.club).target;return {position,pts:team.pts,delta:team.pts-control.pts,target,objective:position<=target,done:s.step===rounds(s).length,played:s.step,total:rounds(s).length,momentum:[...s.momentum],pressure:s.pressure,inbox:s.inbox.length};}
 function goalEvents(s,result){
  if(!result)return [];
  const f=s.base.fixtures.find(x=>x.id===result.id);if(!f)return [];
  const goals=narrative(s,f,[result.hg,result.ag]);
  return goals.map(g=>({minute:g.minute,club:g.side==='h'?f.h:f.a,scorer:scorerFor(s,f,g.side,g.index,(s.last&&s.last.settings&&s.last.settings.rested)||[])}))
              .sort((a,b)=>a.minute-b.minute||a.club.localeCompare(b.club));
 }
 function outcome(h,a){return h>a?'H':h<a?'A':'D';}
 function points(pick,h,a){if(!pick)return 0;const match=pick.outcome===outcome(h,a),exact=pick.score&&pick.score[0]===h&&pick.score[1]===a;return (match?3:0)+(exact?2:0);}
 function cleanPicks(raw,fixtures){
  if(!raw||typeof raw!=='object'||Array.isArray(raw)||Object.keys(raw).length>20)throw new Error('Invalid prediction picks');const known=new Set(fixtures.map(f=>f.id)),out={};
  for(const [key,p] of Object.entries(raw)){if(!known.has(key)||!p||!['H','D','A'].includes(p.outcome))throw new Error('Unknown prediction fixture/outcome');let score=null;if(p.score!==null&&p.score!==undefined){if(!Array.isArray(p.score)||p.score.length!==2)throw new Error('Invalid predicted score');score=p.score.map(v=>number(v,0,9,true));if(outcome(...score)!==p.outcome)throw new Error('Score/outcome mismatch');}out[key]={outcome:p.outcome,score};}return out;
 }
 function scoreChallenge(picks,model,results,fixtures){const clean=cleanPicks(picks,fixtures),byId=Object.fromEntries(results.map(r=>[r.id,r]));let you=0,ai=0,scored=0;const rows=fixtures.map(f=>{const r=byId[f.id];if(!r)return {id:f.id,pending:true};const y=points(clean[f.id],r.hg,r.ag),m=points(model[f.id],r.hg,r.ag);you+=y;ai+=m;scored++;return {id:f.id,hg:r.hg,ag:r.ag,you:y,model:m,pending:false};});return {you,model:ai,scored,pending:fixtures.length-scored,rows};}
 const API={VERSION,RULES,TACTICS,TRAINING,INSTRUCTIONS,MAX_SUBS,cleanBase,create,configure,transfer,advance,restore,preview,roster,clubOf,rank,rounds,fixturesNow,modifiers,lambdas,summary,goalEvents,rand,salt,sample,probabilities,outcome,points,cleanPicks,scoreChallenge,clone,
            beginMatch,firstHalf,complete,completeMatch:complete,cleanPlan,buildInbox,chooseInbox,failedObjective,poisson,ownFixture};
 root.NT90_GAME=API;if(typeof module!=='undefined'&&module.exports)module.exports=API;
})(typeof globalThis!=='undefined'?globalThis:this);
