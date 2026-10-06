"""Career worlds are deterministic, validated, useful and isolated from official football data."""
import copy
import json
import os
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


def test_game_starts_at_the_actual_current_table_not_an_invented_blank_season():
    p=pack();summary=json.loads(Path(ROOT,'data/predictions_2026_27_summary.json').read_text())
    assert p['world']['asOf']==summary['meta']['as_of_date'][:10]
    assert len(p['world']['teams'])==20 and sum(t['p'] for t in p['world']['teams'])==100
    assert len(p['world']['fixtures'])==330 and len(p['world']['players'])==52


def test_game_data_is_not_a_prediction_or_actual_results_write():
    for name in ('playground.py','static/game/engine.js','static/game/ui.js'):
        text=Path(ROOT,name).read_text()
        assert 'predictions_2026_27_summary.json").write' not in text
        assert 'score_ledger.lock_gameweek' not in text
    assert 'simulated scores never enter' in Path(ROOT,'static/game/engine.js').read_text().lower()


def test_snapshot_hash_is_deterministic_and_changes_with_actual_input_changes():
    a=pack();b=pack();assert a['world']['hash']==b['world']['hash']
    assert len(a['world']['hash'])==32
    with tempfile.TemporaryDirectory() as tmp:
        for name in ('predictions_2026_27_summary.json','player_ui_2026_27.json','teams_2026_27.csv','players_2026_27.csv','projected_fixtures_2026_27.csv','matches_2026_27_played.csv'):
            shutil.copy(Path(ROOT,'data',name),Path(tmp,name))
        import csv
        path=Path(tmp,'teams_2026_27.csv')
        with path.open(newline='') as f:
            reader=csv.DictReader(f);fields=reader.fieldnames;values=list(reader)
        values[0]['GF']=str(int(values[0]['GF'])+1)
        with path.open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(values)
        assert playground.payload(tmp)['world']['hash']!=a['world']['hash']


def test_current_fixture_targets_and_all_goal_rates_are_finite():
    p=pack()
    for f in p['world']['fixtures']:
        assert .1<=f['lh']<=6 and .1<=f['la']<=6 and f['gw']>=6
    assert all(1<=t['target']<=20 for t in p['world']['teams'])


def test_game_transfer_prices_are_fictional_credits_with_no_real_money_endpoint():
    assert all(20<=p['price']<=90 for p in pack()['world']['players'])
    text=Path(ROOT,'static/game/shell.html').read_text()
    assert 'Fictional credits' in text and 'not real fees or money' in text.lower()
    assert 'fetch(' not in Path(ROOT,'static/game/ui.js').read_text()


def test_first_career_fixture_matches_current_gw_and_same_seed_same_outcome():
    out=node("let a=G.create(P.world,'ARS',42),b=G.create(P.world,'ARS',42);a=G.advance(a);b=G.advance(b);return {same:JSON.stringify(a)===JSON.stringify(b),week:a.last.gw,count:a.step};")
    assert out=={'same':True,'week':6,'count':1}


def test_advancing_does_not_mutate_the_frozen_base_or_previous_state():
    out=node("let a=G.create(P.world,'ARS',42),before=JSON.stringify(a),original=JSON.stringify(P.world);G.advance(a);G.configure(a,{tactic:'pressing'});return [JSON.stringify(a)===before,JSON.stringify(P.world)===original];")
    assert out==[True,True]


def test_neutral_whole_season_is_identical_to_its_same_engine_control_path():
    out=node("let s=G.create(P.world,'ARS',42);while(!G.summary(s).done)s=G.advance(s);return {summary:G.summary(s),equal:JSON.stringify(s.table)===JSON.stringify(s.control),played:s.table.map(t=>t.p)};")
    assert out['equal'] and out['summary']['delta']==0 and out['summary']['played']==33
    assert out['played']==[38]*20


def test_end_of_season_cannot_be_advanced_again():
    assert node("let s=G.create(P.world,'ARS',42);while(!G.summary(s).done)s=G.advance(s);try{G.advance(s);return false}catch(e){return true}")


def test_league_point_and_goal_conservation_after_a_round():
    out=node("let s=G.advance(G.create(P.world,'ARS',42));return {gf:s.table.reduce((a,t)=>a+t.gf,0),ga:s.table.reduce((a,t)=>a+t.ga,0),played:s.table.reduce((a,t)=>a+t.p,0),draws:s.last.scores.filter(r=>r.hg===r.ag).length,added:s.table.reduce((a,t)=>a+t.pts,0)-P.world.teams.reduce((a,t)=>a+t.pts,0)};")
    assert out['gf']==out['ga'] and out['played']==120 and out['added']==30-out['draws']


def test_tactical_choices_change_preview_without_changing_base_rates():
    out=node("const s=G.create(P.world,'ARS',42),a=G.preview(s),b=G.preview(G.configure(s,{tactic:'attacking'})),c=G.preview(G.configure(s,{tactic:'defensive'}));return {base:a.lh,attack:b.lh,defend:c.lh,ga:a.la,attga:b.la,defga:c.la};")
    assert out['attack']>out['base']>out['defend'] and out['attga']>out['ga']>out['defga']


def test_training_and_high_press_make_fitness_a_real_game_resource():
    out=node("let s=G.configure(G.create(P.world,'ARS',42),{tactic:'pressing',training:'attack'});s=G.advance(s);const tired=s.fitness;s=G.configure(s,{tactic:'balanced',training:'recovery'});s=G.advance(s);return {tired,recovered:s.fitness};")
    assert out['tired']<100 and out['recovered']>out['tired']


def test_resting_a_tracked_star_changes_only_the_game_chances_and_clears_next_round():
    out=node("let s=G.create(P.world,'ARS',42),p=G.preview(s);s=G.configure(s,{rested:['saka']});let rested=G.preview(s);s=G.advance(s);return {lower:rested.lh<p.lh,rested:s.rested};")
    assert out['lower'] and out['rested']==[]


def test_cannot_rest_a_player_at_another_club():
    assert node("try{G.configure(G.create(P.world,'ARS',42),{rested:['haaland']});return false}catch(e){return true}")


def test_signing_affects_both_game_clubs_without_moving_official_roster():
    out=node("const base=G.create(P.world,'ARS',42),s=G.transfer(base,'haaland'),a=G.modifiers(s);return {club:G.clubOf(s,s.base.players.find(p=>p.id==='haaland')),actual:P.world.players.find(p=>p.id==='haaland').club,ars:a.ARS.attack,mci:a.MCI.attack,credits:s.credits};")
    assert out['club']=='ARS' and out['actual']=='MCI' and out['ars']>0 and out['mci']<0 and out['credits']<100


def test_only_one_transfer_per_round_and_cannot_sign_your_own_star():
    assert node("let n=0;try{G.transfer(G.transfer(G.create(P.world,'ARS',42),'haaland'),'palmer')}catch(e){n++}try{G.transfer(G.create(P.world,'ARS',42),'saka')}catch(e){n++}return n===2;")


def test_release_refunds_half_and_never_creates_a_money_loop():
    out=node("let s=G.transfer(G.create(P.world,'ARS',42),'haaland'),paid=s.bought.haaland;s=G.advance(s);const before=s.credits;s=G.transfer(s,'haaland',true);return {refund:s.credits-before,paid,club:G.clubOf(s,s.base.players.find(p=>p.id==='haaland'))};")
    assert out['refund']==out['paid']//2 and out['club']=='MCI'


def test_budget_cannot_be_overdrawn_by_multiple_expensive_signings():
    assert node("let s=G.transfer(G.create(P.world,'ARS',42),'haaland');s=G.advance(s);try{G.transfer(s,'palmer');return false}catch(e){return true}")


def test_all_management_modifiers_are_capped():
    out=node("let s=G.configure(G.create(P.world,'ARS',42),{tactic:'attacking',training:'attack',rested:G.roster(G.create(P.world,'ARS',42),'ARS').map(p=>p.id)});return G.modifiers(s).ARS;")
    assert -30<=out['attack']<=30 and -25<=out['defence']<=25


def test_save_restore_replays_decisions_without_rerolling_results():
    out=node("let s=G.transfer(G.create(P.world,'ARS',42),'haaland');s=G.configure(s,{tactic:'pressing',training:'attack',rested:['raya']});for(let i=0;i<4;i++)s=G.advance(s);const r=G.restore(s);return {equal:JSON.stringify(s)===JSON.stringify(r),next:JSON.stringify(G.advance(s))===JSON.stringify(G.advance(r))};")
    assert out['equal'] and out['next']


def test_tampered_derived_table_credits_and_fitness_are_ignored_on_restore():
    out=node("let s=G.advance(G.create(P.world,'ARS',42)),original=G.summary(s);s.credits=999999;s.fitness=999;s.table[0].pts=999;const r=G.restore(s);return {same:JSON.stringify(G.summary(r))===JSON.stringify(original),credits:r.credits,fitness:r.fitness};")
    assert out['same'] and out['credits']<200 and out['fitness']<=100


def test_illegal_transfers_in_a_save_fail_closed():
    assert node("let s=G.advance(G.create(P.world,'ARS',42));s.journal[0].transfers=[{pid:'haaland',release:false},{pid:'palmer',release:false}];try{G.restore(s);return false}catch(e){return true}")


def test_reordered_journal_is_rejected():
    assert node("let s=G.advance(G.create(P.world,'ARS',42));s.journal[0].gw=38;try{G.restore(s);return false}catch(e){return true}")


def test_future_versions_invalid_identifiers_and_nonfinite_coefficients_are_rejected():
    assert node("let n=0;for(const mutate of [p=>p.version=99,p=>p.players[0].id='__proto__',p=>p.fixtures[0].lh=NaN,p=>p.teams[0].code='<img>',p=>p.fixtures.push(p.fixtures[0])]){let b=G.clone(P.world);mutate(b);try{G.create(b,'ARS',42)}catch(e){n++}}return n===5;")


def test_no_random_reroll_is_hidden_in_render_or_restore():
    source=Path(ROOT,'static/game/engine.js').read_text()
    assert 'Math.random' not in source and 'Date.now' not in source
    assert 'Recompute points, credits' in source


def test_goal_reveal_is_deterministic_fiction_and_uses_only_available_tracked_stars():
    out=node("let s=G.configure(G.create(P.world,'ARS',42),{rested:['saka']});s=G.advance(s);const events=G.goalEvents(s,s.last.own);return {equal:JSON.stringify(events)===JSON.stringify(G.goalEvents(s,s.last.own)),valid:events.every(e=>e.minute>=1&&e.minute<=90&&e.scorer!=='Bukayo Saka')};")
    assert out['equal'] and out['valid']


def test_challenge_model_score_pick_is_consistent_with_its_outcome():
    assert node("return Object.values(P.challenge.model).every(p=>G.outcome(...p.score)===p.outcome);")


def test_challenge_has_a_visible_window_deadline_not_an_invented_kickoff():
    p=pack();assert p['challenge']['gw']==6 and p['challenge']['deadline']=='2026-10-10T00:00:00Z'
    assert 'not an invented exact kickoff' in Path(ROOT,'static/game/shell.html').read_text()


def test_three_outcome_points_plus_two_exact_score_points():
    assert node("return [G.points({outcome:'H',score:[2,1]},2,1),G.points({outcome:'H',score:null},2,1),G.points({outcome:'A',score:null},2,1),G.points(null,2,1)];")==[5,3,0,0]


def test_actual_scoring_does_not_award_missing_results():
    out=node("const picks=G.clone(P.challenge.model),r=G.scoreChallenge(picks,P.challenge.model,[],P.challenge.fixtures);return r;")
    assert out['you']==0 and out['model']==0 and out['scored']==0 and out['pending']==10


def test_completed_challenge_scores_only_matching_real_fixtures():
    out=node("const f=P.challenge.fixtures[0],picks=G.clone(P.challenge.model),score=picks[f.id].score,r=G.scoreChallenge(picks,P.challenge.model,[{id:f.id,hg:score[0],ag:score[1]},{id:'NOT-A-FIXTURE',hg:8,ag:0}],P.challenge.fixtures);return r;")
    assert out['scored']==1 and out['you']==5 and out['pending']==9


def test_unknown_picks_bool_scores_and_mismatched_score_outcomes_are_rejected():
    assert node("let n=0;for(const p of [{'__proto__':{outcome:'H'}},{'NO-TEAM':{outcome:'H'}},{'ARS-LEE':{outcome:'H',score:[true,1]}},{'ARS-LEE':{outcome:'H',score:[0,2]}}]){try{G.cleanPicks(p,P.challenge.fixtures)}catch(e){n++}}return n>=3;")


def test_practice_points_are_separate_from_the_real_locked_scorecard():
    source=Path(ROOT,'static/game/ui.js').read_text()
    practice=source[source.index('function practise()'):source.index('function lock()')]
    assert "STORE.set('predictionChallenges'" not in practice
    assert 'PRACTICE ONLY' in practice and 'PLAY_DATA.challenge.actual.filter' in source


def test_deadline_and_duplicate_lock_checks_exist_at_the_save_boundary():
    source=Path(ROOT,'static/game/ui.js').read_text()
    block=source[source.index('function lock()'):source.index("$('careerTab').onclick")]
    assert 'lockedCurrent()||deadlinePassed()' in block and 'Date.now()' in block
    assert 'Real picks cannot be changed' in block


def test_unverified_client_saves_are_not_claimed_as_a_public_leaderboard():
    text=Path(ROOT,'static/game/shell.html').read_text()
    assert 'not a verified competition or public leaderboard' in text
    assert 'client clocks/saves can be edited' in text


def test_game_import_is_size_and_schema_validated_before_storage():
    source=Path(ROOT,'static/game/ui.js').read_text()
    assert 'f.size>350000' in source and "data.kind!=='ninety-plus-career'" in source
    assert source.index('const restored=G.restore(data.state)')<source.index('active=restored')


def test_game_ui_escapes_all_imported_names_and_never_evaluates_them():
    source=Path(ROOT,'static/game/ui.js').read_text()
    assert 'esc(p.name)' in source and 'esc(e.scorer)' in source
    assert 'eval(' not in source and 'new Function' not in source and '.innerHTML=f' not in source


def test_storage_v3_migration_preserves_scenarios_and_adds_game_fields():
    source=Path(ROOT,'static/src/store.js').read_text()
    assert 'var VERSION = 4' in source and 'MIGRATIONS[3]' in source
    assert 'careers: []' in source and 'predictionChallenges: []' in source


def test_generated_play_page_is_self_contained_small_and_has_two_distinct_modes():
    html=Path(ROOT,'static/play.html').read_text()
    assert len(html.encode())<640*1024
    assert '<script src=' not in html and '<link rel="stylesheet"' not in html
    assert 'Career Mode' in html and 'Beat the Model' in html and 'NT90_GAME' in html
    assert 'Simulated' in html and 'Official forecasts and historical locks are read-only' in html


def test_homepage_has_obvious_game_entry_controls_not_only_an_advanced_tab():
    html=Path(ROOT,'static/index.html').read_text()
    for marker in ('id="playHub"','id="hubClub"','id="hubCareer"','id="hubChallenge"','Start Career Mode'):
        assert marker in html
    assert html.index('id="playHub"')<html.index('id="hero"')


def test_playground_is_on_both_rebuild_paths_before_dashboard_generation():
    for name in ('run_all.py','update_week.py'):
        text=Path(ROOT,name).read_text();assert text.index('playground.py')<text.index('build_dashboard.py')


def test_deployment_verifier_detects_game_only_changes():
    from tools.verify_deployment import compare,committed
    want=committed();got=copy.deepcopy(want);got['playground']='wrong'
    assert any(c[0]=='playground' and c[-1] is False for c in compare(want,got))


def test_play_manifest_and_page_fingerprints_agree():
    p=json.loads(Path(ROOT,'data/playground_manifest.json').read_text())
    page=Path(ROOT,'static/play.html').read_text()
    assert p['fingerprint'] in page and p['world_hash']==pack()['world']['hash']


def test_game_is_listed_in_sitemap_after_generation():
    assert 'play.html' in Path(ROOT,'static/sitemap.xml').read_text()


def test_privacy_covers_new_game_storage_and_clear_scope():
    text=Path(ROOT,'static/privacy.html').read_text()
    assert 'Career Mode saves' in text and 'Beat the Model predictions' in text
    assert 'personal challenge records' in text and 'receipt feedback' in text
