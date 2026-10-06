/* NINETY+ Club Manager. Original management sandbox, not EA game assets/code.
 * Pure deterministic engine; simulated scores never enter official prediction/result data.
 */
(function(root){
 'use strict';
 const VERSION=1, RULES='club-manager/1';
 const TACTICS={balanced:{attack:0,defence:0,cost:5},attacking:{attack:12,defence:8,cost:10},defensive:{attack:-8,defence:-10,cost:4},pressing:{attack:7,defence:3,cost:14}};
 const TRAINING={recovery:{attack:0,defence:0,fitness:12},attack:{attack:4,defence:0,fitness:-4},defence:{attack:0,defence:-4,fitness:-3}};
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
 function probabilities(lh,la){let h=0,d=0,a=0;matrix(lh,la).forEach(c=>{if(c.h>c.a)h+=c.p;else if(c.h<c.a)a+=c.p;else d+=c.p;});return {h:Math.round(h*1000)/10,d:Math.round(d*1000)/10,a:Math.round(a*1000)/10};}
 function rank(table){return [...table].sort((a,b)=>b.pts-a.pts||(b.gf-b.ga)-(a.gf-a.ga)||b.gf-a.gf||a.code.localeCompare(b.code));}
 function rounds(state){return [...new Set(state.base.fixtures.map(f=>f.gw))];}
 function fixturesNow(state){const gw=rounds(state)[state.step];return state.base.fixtures.filter(f=>f.gw===gw);}
 function clubOf(state,player){return state.moves[player.id]||player.club;}
 function roster(state,club){return state.base.players.filter(p=>clubOf(state,p)===club);}
 function create(raw,club,seed){
  const base=cleanBase(raw);if(!base.teams.some(t=>t.code===club))throw new Error('Choose a current club');number(seed,0,4294967295,true);
  return {v:VERSION,base,club,seed:seed>>>0,step:0,table:clone(base.teams),control:clone(base.teams),credits:100,fitness:100,tactic:'balanced',training:'recovery',rested:[],moves:{},bought:{},transferUsed:false,pending:[],journal:[],last:null};
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
  Object.values(mods).forEach(m=>{m.attack=clamp(m.attack,-30,30);m.defence=clamp(m.defence,-25,25);});return mods;
 }
 function lambdas(s,f){const m=modifiers(s),h=m[f.h],a=m[f.a];return [clamp(f.lh*(1+h.attack/100)*(1+a.defence/100),.2,5),clamp(f.la*(1+a.attack/100)*(1+h.defence/100),.2,5)];}
 function preview(s){const f=fixturesNow(s).find(f=>f.h===s.club||f.a===s.club);if(!f)return null;const [lh,la]=lambdas(s,f);return {...f,lh,la,prob:probabilities(lh,la),original:probabilities(f.lh,f.la)};}
 function apply(table,f,score){const h=table.find(t=>t.code===f.h),a=table.find(t=>t.code===f.a),[hg,ag]=score;h.p++;a.p++;h.gf+=hg;h.ga+=ag;a.gf+=ag;a.ga+=hg;if(hg>ag){h.w++;h.pts+=3;a.l++;}else if(ag>hg){a.w++;a.pts+=3;h.l++;}else{h.d++;a.d++;h.pts++;a.pts++;}}
 function advance(raw){
  const s=clone(raw),fixtures=fixturesNow(s);if(!fixtures.length)throw new Error('Career season is finished');
  const scores=[],controlScores=[],settings={tactic:s.tactic,training:s.training,rested:[...s.rested],transfers:clone(s.pending)};
  for(const f of fixtures){const u=rand(salt(s.seed,f.id+'@'+f.gw)),[lh,la]=lambdas(s,f),actual=sample(lh,la,u),original=sample(f.lh,f.la,u);apply(s.table,f,actual);apply(s.control,f,original);scores.push({id:f.id,gw:f.gw,h:f.h,a:f.a,hg:actual[0],ag:actual[1]});controlScores.push({id:f.id,gw:f.gw,h:f.h,a:f.a,hg:original[0],ag:original[1]});}
  const own=scores.find(r=>r.h===s.club||r.a===s.club),gf=own?(own.h===s.club?own.hg:own.ag):0,ga=own?(own.h===s.club?own.ag:own.hg):0;
  if(own){s.credits+=2+(gf>ga?3:gf===ga?1:0);s.fitness=clamp(s.fitness+TRAINING[s.training].fitness-TACTICS[s.tactic].cost+5,25,100);}
  s.last={gw:fixtures[0].gw,scores,controlScores,own,settings};s.journal.push({gw:fixtures[0].gw,...settings,own:clone(own||null)});s.step++;s.rested=[];s.pending=[];s.transferUsed=false;return s;
 }
 function restore(raw){
  if(!raw||raw.v!==VERSION||!Array.isArray(raw.journal)||raw.journal.length>38||!Array.isArray(raw.pending)||raw.pending.length>1)throw new Error('Unsupported or damaged career save');
  let s=create(raw.base,code(raw.club),number(raw.seed,0,4294967295,true));
  for(const entry of raw.journal){if(entry.gw!==rounds(s)[s.step]||!Array.isArray(entry.transfers)||entry.transfers.length>1)throw new Error('Career journal is out of order');for(const tx of entry.transfers){if(typeof tx.release!=='boolean')throw new Error('Invalid transfer');s=transfer(s,id(tx.pid),tx.release);}s=configure(s,{tactic:entry.tactic,training:entry.training,rested:entry.rested});s=advance(s);}
  if(s.step<rounds(s).length){for(const tx of raw.pending){if(typeof tx.release!=='boolean')throw new Error('Invalid transfer');s=transfer(s,id(tx.pid),tx.release);}s=configure(s,{tactic:raw.tactic,training:raw.training,rested:raw.rested});}
  return s; // Recompute points, credits, fitness and transfers; never trust editable derived totals.
 }
 function summary(s){const table=rank(s.table),position=table.findIndex(t=>t.code===s.club)+1,team=table[position-1],control=s.control.find(t=>t.code===s.club),target=s.base.teams.find(t=>t.code===s.club).target;return {position,pts:team.pts,delta:team.pts-control.pts,target,objective:position<=target,done:s.step===rounds(s).length,played:s.step,total:rounds(s).length};}
 function goalEvents(s,result){
  if(!result)return [];let events=[];const current=roster(s,s.club).filter(p=>p.pos!=='GK'&&!s.last.settings.rested.includes(p.id));
  for(const [club,goals] of [[result.h,result.hg],[result.a,result.ag]])for(let i=0;i<goals;i++){const seed=salt(s.seed,result.id+'goal'+club+i),minute=1+Math.floor(rand(seed)*90),scorer=club===s.club&&current.length?current[Math.floor(rand(seed+31)*current.length)].name:'Team goal';events.push({minute,club,scorer});}
  return events.sort((a,b)=>a.minute-b.minute||a.club.localeCompare(b.club));
 }
 function outcome(h,a){return h>a?'H':h<a?'A':'D';}
 function points(pick,h,a){if(!pick)return 0;const match=pick.outcome===outcome(h,a),exact=pick.score&&pick.score[0]===h&&pick.score[1]===a;return (match?3:0)+(exact?2:0);}
 function cleanPicks(raw,fixtures){
  if(!raw||typeof raw!=='object'||Array.isArray(raw)||Object.keys(raw).length>20)throw new Error('Invalid prediction picks');const known=new Set(fixtures.map(f=>f.id)),out={};
  for(const [key,p] of Object.entries(raw)){if(!known.has(key)||!p||!['H','D','A'].includes(p.outcome))throw new Error('Unknown prediction fixture/outcome');let score=null;if(p.score!==null&&p.score!==undefined){if(!Array.isArray(p.score)||p.score.length!==2)throw new Error('Invalid predicted score');score=p.score.map(v=>number(v,0,9,true));if(outcome(...score)!==p.outcome)throw new Error('Score/outcome mismatch');}out[key]={outcome:p.outcome,score};}return out;
 }
 function scoreChallenge(picks,model,results,fixtures){const clean=cleanPicks(picks,fixtures),byId=Object.fromEntries(results.map(r=>[r.id,r]));let you=0,ai=0,scored=0;const rows=fixtures.map(f=>{const r=byId[f.id];if(!r)return {id:f.id,pending:true};const y=points(clean[f.id],r.hg,r.ag),m=points(model[f.id],r.hg,r.ag);you+=y;ai+=m;scored++;return {id:f.id,hg:r.hg,ag:r.ag,you:y,model:m,pending:false};});return {you,model:ai,scored,pending:fixtures.length-scored,rows};}
 const API={VERSION,RULES,TACTICS,TRAINING,cleanBase,create,configure,transfer,advance,restore,preview,roster,clubOf,rank,rounds,fixturesNow,modifiers,lambdas,summary,goalEvents,rand,salt,sample,probabilities,outcome,points,cleanPicks,scoreChallenge,clone};
 root.NT90_GAME=API;if(typeof module!=='undefined'&&module.exports)module.exports=API;
})(typeof globalThis!=='undefined'?globalThis:this);
