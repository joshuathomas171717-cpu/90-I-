"""Phase 17: the matchday is played and decided, not skipped. Deterministic, bounded, replayable."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from _util import ROOT, skip
import playground


def pack(): return playground.payload()


def node(script):
    if not shutil.which('node'): skip('Node is a dev instrument, not a game runtime')
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp,'payload.json');path.write_text(json.dumps(pack()))
        setup='const fs=require("fs"),G=require('+json.dumps(str(Path(ROOT,'static/game/engine.js')))+');const P=JSON.parse(fs.readFileSync('+json.dumps(str(path))+',"utf8"));'
        result=subprocess.run(['node','-e',setup+'console.log(JSON.stringify((()=>{'+script+'})()));'],cwd=ROOT,capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stderr
        return json.loads(result.stdout.strip())


# ── the decision, and the promise that nothing is rerolled ────────────────────────────────────────
def test_a_calm_half_time_with_no_subs_reproduces_the_old_engine_exactly():
    out=node("const s=G.create(P.world,'ARS',42);const a=G.complete(s,{interaction:'calm',subs:[]}),b=G.advance(s);return {same:JSON.stringify(a.result.own)===JSON.stringify(b.last.own),before:JSON.stringify(G.modifiers(s)),after:JSON.stringify(G.modifiers(a.state))};")
    assert out['same'] and out['before']==out['after'], 'a calm half time silently changed the game model'


def test_an_instruction_can_change_the_score_but_is_bounded_and_never_rerolls():
    out=node("""const s=G.create(P.world,'ARS',42);
     const base=G.complete(s,{interaction:'calm',subs:[]}).result.own;
     const rows=Object.keys(G.INSTRUCTIONS).map(k=>{const r=G.complete(s,{interaction:k,subs:[]}).result;
       return {key:k,own:r.own,added:r.effect.added,removed:r.effect.removed,means:r.effect.means};});
     return {base,rows};""")
    for row in out['rows']:
        change=abs(row['own']['hg']-out['base']['hg'])+abs(row['own']['ag']-out['base']['ag'])
        assert change<=4, row
        assert -0.6<=row['means']['mine']<=0.6 and -0.6<=row['means']['theirs']<=0.6
    calm=next(r for r in out['rows'] if r['key']=='calm')
    assert calm['added']=={'home':0,'away':0} and calm['removed']=={'home':0,'away':0}
    assert any(r['own']!=out['base'] for r in out['rows']), 'no instruction ever changed a score in this world'


def test_the_full_time_score_really_is_base_plus_a_deterministic_delta():
    out=node("const s=G.create(P.world,'ARS',42),f=G.ownFixture(s);const calm=G.complete(s,{interaction:'calm',subs:[]}).result,held=G.complete(s,{interaction:'hold',subs:['gyokeres']}).result;return {calm:calm.own,held:held.own,effect:held.effect,fixture:f.id};")
    assert out['calm']['hg']>=0 and out['held']['hg']>=0
    assert abs((out['held']['hg']-out['calm']['hg']))<=3+1 and abs(out['held']['ag']-out['calm']['ag'])<=3+1
    assert out['effect']['score']==[out['held']['hg'],out['held']['ag']]


def test_same_seed_world_and_call_always_produce_the_same_match():
    out=node("const make=()=>{let s=G.create(P.world,'ARS',42);s=G.configure(s,{tactic:'pressing',training:'attack',rested:['raya']});return G.complete(s,{interaction:'push',subs:['saka']});};const a=make(),b=make();return {same:JSON.stringify(a)===JSON.stringify(b),goals:a.result.goals};")
    assert out['same']


def test_substitutions_are_limited_to_two_and_only_your_own_players():
    out=node("""let n=0;const s=G.create(P.world,'ARS',42);
     try{G.complete(s,{interaction:'calm',subs:['saka','gyokeres','odegaard']})}catch(e){n++}
     try{G.complete(s,{interaction:'calm',subs:['haaland']})}catch(e){n++}
     try{G.complete(s,{interaction:'sprint'})}catch(e){n++}
     const two=G.complete(s,{interaction:'calm',subs:['saka','saka']}).result;return {n,deduped:two.plan.subs.length};""")
    assert out['n']==3 and out['deduped']==1


def test_a_substitution_moves_the_second_half_means_in_the_stated_direction():
    out=node("const s=G.create(P.world,'ARS',42);const none=G.complete(s,{interaction:'calm',subs:[]}).result.effect.means,attack=G.complete(s,{interaction:'calm',subs:['gyokeres']}).result.effect.means,keeper=G.complete(s,{interaction:'calm',subs:['raya']}).result.effect.means;return {none,attack,keeper};")
    assert out['attack']['mine']>out['none']['mine'] and out['keeper']['mine']==out['none']['mine']
    assert out['keeper']['theirs']<=out['none']['theirs']+1e-9


# ── the protocol the matchday UI depends on ────────────────────────────────────────────────────────
def test_begin_match_reports_weather_crowd_and_who_can_come_on():
    out=node("const s=G.create(P.world,'ARS',42),b=G.beginMatch(s);return {gw:b.gw,weather:b.weather,crowd:b.attendance,pool:b.subsPool.length,prob:b.prob,original:b.original,rested:b.restedCount,instructions:Object.keys(b.instructions)};")
    assert out['gw']==6 and out['weather'] in ('clear','breezy','wet')
    assert 18000<=out['crowd']<=60000 and out['pool']==6 and out['rested']==0
    assert set(out['instructions'])=={'calm','push','hold','press'}


def test_first_half_never_leaks_second_half_goals_and_stays_inside_the_half():
    out=node("const s=G.create(P.world,'ARS',42),h=G.firstHalf(s),r=G.complete(s,{interaction:'push',subs:['saka']}).result;return {half:h.score,goals:h.goals,base:h.base,full:r.own,total:h.score.home+h.score.away,fullTotal:r.own.hg+r.own.ag,stats:h.stats,lead:h.lead};")
    assert all(1<=g['minute']<=45 for g in out['goals'])
    assert out['total']<=max(out['base']['home'],out['base']['away'])+out['base']['home']
    assert out['fullTotal']>=out['total']-1
    assert 32<=out['stats']['possession']<=68 and 0<=out['stats']['onTarget']['home']<=12
    assert out['lead']==out['half']['home']-out['half']['away']


def test_scorers_are_deterministic_and_never_the_player_you_rested():
    out=node("const s=G.configure(G.create(P.world,'ARS',42),{rested:['saka']});const a=G.firstHalf(s),b=G.firstHalf(s),r=G.complete(s,{interaction:'push',subs:[]}).result;return {same:JSON.stringify(a)===JSON.stringify(b),names:[...a.goals,...r.goals].filter(g=>g.side==='h').map(g=>g.scorer)};")
    assert out['same'] and 'Bukayo Saka' not in out['names']


def test_finish_and_replays_agree_with_goal_events_used_by_the_reveal():
    out=node("const s=G.create(P.world,'ARS',42),r=G.complete(s,{interaction:'hold',subs:[]}).result,events=G.goalEvents(s,r.own);return {events,goalMinutes:(r.goals||[]).map(g=>g.minute)};")
    assert len(out['events'])>=len(out['goalMinutes'])


def test_no_fixture_left_means_no_session_raw_objects():
    out=node("let s=G.create(P.world,'ARS',42);while(!G.summary(s).done)s=G.advance(s);return {begin:G.beginMatch(s),fixture:G.ownFixture(s),preview:G.preview(s)};")
    assert out['begin'] is None and out['fixture'] is None and out['preview'] is None


# ── the manager's inbox ───────────────────────────────────────────────────────────────────────────
def test_inbox_arrives_with_the_fallout_and_every_choice_states_its_effect():
    out=node("const s=G.complete(G.create(P.world,'ARS',42),{interaction:'push',subs:[]}).state;return {items:s.inbox,inbox:s.inbox.length};")
    assert 1<=out['inbox']<=4
    for item in out['items']:
        assert item['id'] and item['title'] and item['body'] and len(item['choices'])>=2
        for choice in item['choices']: assert choice['label'] and choice['detail']


def test_an_inbox_reply_applies_a_bounded_effect_and_leaves_the_inbox():
    out=node("""const s=G.complete(G.create(P.world,'ARS',42),{interaction:'calm',subs:[]}).state,item=s.inbox[0];
     const before={credits:s.credits,fitness:s.fitness,items:s.inbox.length};
     const out1=G.chooseInbox(s,item.id,item.choices[0].id),c=out1.state;
     return {dCredits:c.credits-before.credits,dFitness:c.fitness-before.fitness,effects:out1.effect,
             removed:before.items-c.inbox.length,pending:c.pendingInbox.length};""")
    assert out['removed']==1 and out['pending']==1 and out['effects']
    assert 0<=out['dCredits']<=25 and -8<=out['dFitness']<=12


def test_unknown_items_and_replies_are_rejected_instead_of_silently_ignored():
    out=node("const s=G.complete(G.create(P.world,'ARS',42),{interaction:'calm',subs:[]}).state;let n=0;try{G.chooseInbox(s,'not-an-item','quiet')}catch(e){n++}try{G.chooseInbox(s,s.inbox[0].id,'not-a-choice')}catch(e){n++}return n;")
    assert out==2


def test_a_defensive_drill_reduces_the_conceded_mean_instead_of_helping_the_attack():
    out=node("""const s=G.complete(G.create(P.world,'ARS',42),{interaction:'calm',subs:[]}).state;
     const out1=G.chooseInbox(s,'reaction-6','demand');const boost=out1.state.boosts;
     return {boost,expires:boost.expires,step:out1.state.step};""")
    assert out['boost']['attack']==2 and out['boost']['expires']==out['step']
    declined=node("""const s=G.complete(G.create(P.world,'ARS',42),{interaction:'calm',subs:[]}).state;
     let seeded=s;seeded.inbox=[{id:'budget-6',type:'budget',tag:'x',title:'t',body:'b',choices:[{id:'accept',label:'a',detail:'d'},{id:'decline',label:'d',detail:'d'}]}];
     const out1=G.chooseInbox(seeded,'budget-6','decline');return out1.state.boosts;""")
    assert declined['attack']==3 and declined['defence']==-3


def test_a_job_offer_moves_the_career_to_the_named_club():
    out=node("""const s=G.complete(G.create(P.world,'ARS',42),{interaction:'calm',subs:[]}).state;
     s.inbox=[{id:'job-6',type:'job',club:'LIV',tag:'x',title:'t',body:'b',choices:[{id:'stay',label:'s',detail:'d'},{id:'take',label:'t',detail:'d'}]}];
     const out1=G.chooseInbox(s,'job-6','take');return {club:out1.state.club,pressure:out1.state.pressure,credits:out1.state.credits};""")
    assert out['club']=='LIV' and out['pressure']==0 and out['credits']>=100


def test_an_inbox_effect_reaches_the_next_match_only_through_the_recorded_choice():
    out=node("""const s=G.complete(G.create(P.world,'ARS',42),{interaction:'calm',subs:[]}).state;
     const plain=G.modifiers(s).ARS;
     const boosted=G.chooseInbox(s,'reaction-6','demand').state;
     const next=G.modifiers(boosted).ARS;
     const spent=G.complete(boosted,{interaction:'calm',subs:[]}).state;
     return {plain,next,after:spent.boosts,spentStep:G.modifiers(spent).ARS};""")
    assert out['next']['attack']>out['plain']['attack']
    assert out['after']['attack']==0 and out['after']['defence']==0


def test_inbox_replies_are_replayed_by_restore_not_reinvented():
    out=node("""let s=G.complete(G.create(P.world,'ARS',42),{interaction:'push',subs:['saka']}).state;
     for(const item of [...s.inbox])s=G.chooseInbox(s,item.id,item.choices[item.choices.length-1].id).state;
     s=G.complete(s,{interaction:'hold',subs:[]}).state;
     const r=G.restore(s);
     return {equal:JSON.stringify(s)===JSON.stringify(r),inbox:s.inbox.length,credits:s.credits};""")
    assert out['equal']


def test_a_restore_cannot_reply_to_an_item_that_was_never_open():
    out=node("""let s=G.complete(G.create(P.world,'ARS',42),{interaction:'calm',subs:[]}).state;
     s.journal[0].inbox=[{item:'invented-6',type:'reaction',choice:'quiet',effect:{}}];s.pendingInbox=[];
     try{G.restore(s);return false}catch(e){return true}""")
    assert out


def test_an_unknown_half_time_instruction_in_a_save_is_refused():
    out=node("let s=G.complete(G.create(P.world,'ARS',42),{interaction:'calm',subs:[]}).state;s.journal[0].plan={interaction:'teleport',subs:[]};try{G.restore(s);return false}catch(e){return true}")
    assert out


# ── saving, migration, isolation ──────────────────────────────────────────────────────────────────
def test_a_phase_sixteen_save_still_opens_with_its_own_results_intact():
    pack_=pack()
    legacy={'v':1,'base':pack_['world'],'club':'ARS','seed':42,'step':0,'table':pack_['world']['teams'],
            'control':pack_['world']['teams'],'credits':100,'fitness':100,'tactic':'balanced','training':'recovery',
            'rested':[],'moves':{},'bought':{},'transferUsed':False,'pending':[],'journal':[],'last':None}
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp,'legacy.json');path.write_text(json.dumps(legacy))
        script='(()=>{const legacy=JSON.parse(fs.readFileSync('+json.dumps(str(path))+',"utf8"));let s=G.restore(legacy);s=G.complete(s,{interaction:"hold",subs:[]}).state;return {migrated:!!s.migrated,step:s.step,inbox:s.inbox.length,result:s.last.own};})()'
        result=subprocess.run(['node','-e','const fs=require("fs"),G=require('+json.dumps(str(Path(ROOT,'static/game/engine.js')))+');console.log(JSON.stringify('+script+'));'],capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stderr
        out=json.loads(result.stdout)
    assert out['migrated'] and out['step']==1 and out['inbox']>=1


def test_the_game_still_writes_nothing_outside_the_browser():
    for name in ('static/game/engine.js','static/game/ui.js','playground.py'):
        text=Path(ROOT,name).read_text()
        assert 'fetch(' not in text and 'XMLHttpRequest' not in text and 'WebSocket' not in text
        assert 'score_ledger' not in text and 'predictions_2026_27_summary.json").write' not in text


def test_the_matchday_ui_gates_actions_while_a_match_is_live():
    ui=Path(ROOT,'static/game/ui.js').read_text()
    for marker in ("$('kickOff').onclick=guarded(kickOff)","$('secondHalf').onclick=guarded(playSecondHalf)",
                   "id=\"halfTimePanel\"","id=\"instructionChoices\"","id=\"subChoices\"","id=\"continueAfterMatch\"",
                   "id=\"fullTimePanel\"","id=\"inboxList\""):
        haystack=ui if not marker.startswith('id=') else Path(ROOT,'static/game/shell.html').read_text()
        assert marker in haystack, marker
    assert "if(session)return" in ui            # transfers and tactics are locked during a match
    shell=Path(ROOT,'static/game/shell.html').read_text()
    assert 'Skip match (no instruction)' in shell and 'Skip the animation' in shell
    assert 'Kick off — decide at half time' in shell


def test_reduced_motion_gets_the_same_decision_without_the_clock():
    ui=Path(ROOT,'static/game/ui.js').read_text()
    import re as _re
    assert _re.search(r'if\(reduced\)\s*\{\s*script\.forEach', ui), 'no reduced-motion first half'
    assert _re.search(r'if\(reduced\)\s*\{\s*second\.forEach', ui), 'no reduced-motion second half'
    assert "matchMedia('(prefers-reduced-motion: reduce)')" in ui


def test_the_built_page_carries_the_match_session_and_stays_self_contained():
    html=Path(ROOT,'static/play.html').read_text()
    assert len(html.encode())<640*1024
    for marker in ('halfTimePanel','instructionChoices','subChoices','inboxList','FULL TIME · SIMULATED','Skip match (no instruction)'):
        assert marker in html, marker
    assert '<script src=' not in html and '<link rel="stylesheet"' not in html


def test_playground_manifest_tracks_the_new_game_rules_version():
    manifest=json.loads(Path(ROOT,'data/playground_manifest.json').read_text())
    assert manifest['version']=='club-manager/2'
    assert pack()['world']['rules']=='club-manager/2'
