"""Phase 15: visible provenance, immutable manual profiles and honest lock-time evidence."""
import copy
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _util import ROOT, skip
from player_scenarios import club_effects, sanitise_effects
from player_ui import build, embedded, fingerprint, gameweek_evidence, player_status, squad_panel, availability_digest
from safe_embed import script_json
import score_ledger


def load(name):
    return json.loads(Path(ROOT, name).read_text())


def profile(**kw):
    return {"model":"replacement-share/1", "name":"Erling Haaland", "club":"MCI", "tier":1,
            "attack":12., "defence":2., "attack_range":[6.,20.], "defence_range":[1.,4.],
            "source":"synthetic-test-only", "fetched_at":"2026-10-04T12:00:00Z",
            "baseline_as_of":"2026-10-03", "context_hash":"test-only", **kw}


def test_inline_json_cannot_close_a_script_or_inject_an_image():
    hostile={'reason':'</ScRiPt><img src=x onerror=alert(1)>','name':'<script>evil</script>', 'sep':'\u2028'}
    encoded=script_json(hostile)
    assert '<' not in encoded and '</script' not in encoded.lower()
    assert json.loads(encoded)==hostile


def test_profiles_preserve_names_ranges_provenance_and_vintage():
    raw={'haaland':profile()}
    clean,errors=sanitise_effects(raw,{'haaland':4},{'MCI'},{'haaland'},{'haaland':'MCI'})
    assert not errors and clean['haaland']['name']=='Erling Haaland'
    assert clean['haaland']['attack_range']==[6.,20.] and clean['haaland']['baseline_as_of']=='2026-10-03'
    assert clean['haaland']['source']=='synthetic-test-only'


def test_profile_ranges_are_input_assumptions_not_probability_intervals():
    raw={'haaland':profile()}
    clean,_=sanitise_effects(raw,{'haaland':33},{'MCI'},{'haaland'})
    effects=club_effects(clean,{'haaland':33},{'MCI':33})['MCI']
    assert effects['attack']==12 and effects['attack_range']==[6,20]
    short=club_effects(clean,{'haaland':3},{'MCI':30})['MCI']
    assert short['attack']==1.2 and short['defence']==.2


def test_effects_reject_nonfinite_bool_wrong_club_unknown_players_and_future_versions():
    for raw in [profile(attack=float('nan')), profile(defence=True), profile(club='ARS'),
                profile(model='future/99'), profile(tier=True), profile(attack_range=[13,20])]:
        clean,errors=sanitise_effects({'haaland':raw},{'haaland':3},{'MCI','ARS'},{'haaland'},{'haaland':'MCI'})
        assert not clean and errors
    assert sanitise_effects({'intruder':profile()},{'intruder':3},{'MCI'},{'haaland'})[1]


def test_multiple_absence_effects_are_capped_without_duplicate_counting():
    effects={str(i):profile(attack=20,defence=20,attack_range=[15,25],defence_range=[10,25]) for i in range(4)}
    injuries={str(i):33 for i in range(4)}
    out=club_effects(effects,injuries,{'MCI':33})['MCI']
    assert out['attack']==30 and out['defence']==25
    assert max(out['attack_range'])==30 and max(out['defence_range'])==25


def test_restoring_a_player_removes_the_effect():
    assert club_effects({'haaland':profile()},{'haaland':0},{'MCI':33})=={}


def test_server_accepts_frozen_effects_only_as_explicit_scenario_fields():
    from server import validate_scenario
    body={'n_sims':600,'player_injuries':{'haaland':4},'player_effects':{'haaland':profile()}}
    scenario,n,errors=validate_scenario(body,{'MCI'},{'haaland'},{'haaland':'MCI'})
    assert not errors and n==600 and scenario['player_effects']['haaland']['attack']==12
    bad=copy.deepcopy(body);bad['player_effects']['haaland']['model']='unsupported'
    assert validate_scenario(bad,{'MCI'},{'haaland'},{'haaland':'MCI'})[2]


def test_legacy_requests_do_not_acquire_or_reprice_player_profiles():
    from server import validate_scenario
    scene,_,errors=validate_scenario({'n_sims':600,'player_injuries':{'haaland':4}},{'MCI'},{'haaland'})
    assert not errors and 'player_effects' not in scene


def node_eval(script):
    if not shutil.which('node'):skip('node not installed; browser harness is dev-only')
    page=Path(ROOT,'static/index.html').read_text()
    start=page.index('const EMBEDDED = ')+len('const EMBEDDED = ')
    payload,_=json.JSONDecoder().raw_decode(page[start:])
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp,'payload.json');path.write_text(json.dumps(payload))
        setup="const vm=require('vm'),fs=require('fs');const c={window:{},document:{getElementById:()=>null,readyState:'loading',addEventListener:()=>{}},console,btoa:s=>Buffer.from(s,'binary').toString('base64'),atob:s=>Buffer.from(s,'base64').toString('binary'),location:{origin:'https://example.test',pathname:'/',protocol:'https:',search:'',href:'https://example.test/'}};vm.createContext(c);"
        setup+='vm.runInContext("const EMBEDDED = "+fs.readFileSync('+json.dumps(str(path))+',"utf8")+";",c);'
        for part in ('core.js','players.js','share.js'):
            setup+='vm.runInContext(fs.readFileSync('+json.dumps(str(Path(ROOT,'static/src',part)))+',"utf8"),c);'
        setup+='const r=vm.runInContext('+json.dumps(script)+',c);console.log(JSON.stringify(r));'
        result=subprocess.run(['node','-e',setup],capture_output=True,text=True,cwd=ROOT,timeout=30)
        assert result.returncode==0,result.stderr
        return json.loads(result.stdout.strip())


def test_new_share_link_round_trips_frozen_names_and_effects_as_v2():
    script='''(()=>{const scene={player_injuries:{haaland:4},player_effects:{haaland:PROFILE}};const token=window.NT90_SHARE.encode(scene);const parsed=window.NT90_SHARE.decode(token);return {token,scene:parsed.scenario};})()'''.replace('PROFILE',json.dumps(profile()))
    out=node_eval(script)
    assert out['token'].startswith('v2-')
    assert out['scene']['player_effects']['haaland']['name']=='Erling Haaland'
    assert out['scene']['player_effects']['haaland']['attack_range']==[6,20]


def test_old_share_links_keep_v1_and_no_profiles():
    out=node_eval('''(()=>{const t=window.NT90_SHARE.encode({player_injuries:{haaland:4}});return {token:t,scene:window.NT90_SHARE.decode(t).scenario};})()''')
    assert out['token'].startswith('v1-') and 'player_effects' not in out['scene']


def test_both_scenario_readers_keep_the_new_field_and_reject_future_versions():
    share=Path(ROOT,'static/src/share.js').read_text();ux=Path(ROOT,'static/src/ux.js').read_text()
    assert 'player_effects: version >= 2' in share and 'player_effects: version >= 2' in ux
    assert 'compact.e=SCENARIO.player_effects' in ux and 'token.length>48000' in share
    out=node_eval('''(()=>{try{window.NT90_SHARE.decode('v99-e30');return false}catch(e){return true}})()''')
    assert out is True


def test_malformed_profile_does_not_silently_fall_back_to_legacy_pricing():
    out=node_eval('''sanitizeScenario({player_injuries:{haaland:4},player_effects:{haaland:{model:'future/99'}}})''')
    assert out['player_injuries']=={} and not out.get('player_effects')


def test_profile_metadata_markup_is_escaped_not_executed():
    p=profile(name='</script><img src=x onerror=alert(1)>')
    script='''(()=>{const raw={player_injuries:{haaland:4},player_effects:{haaland:PROFILE}};return sanitizeScenario(raw)})()'''.replace('PROFILE',json.dumps(p))
    out=node_eval(script)
    assert out['player_effects']['haaland']['attack']==12
    render=Path(ROOT,'static/src/render.js').read_text()
    assert 'esc(profileDescription' in render and 'esc(p.name)' in render


def test_prototype_keys_never_become_known_clubs_or_players():
    out=node_eval('''sanitizeScenario(JSON.parse('{"player_injuries":{"constructor":4,"__proto__":4},"team_boosts":{"constructor":25}}'))''')
    assert out['player_injuries']=={} and out['team_boosts']=={}


def test_python_and_browser_club_effect_math_agree():
    effects={'haaland':profile(),'raya':profile(club='ARS',name='David Raya',attack=0,defence=6,attack_range=[0,0],defence_range=[3,10])}
    injuries={'haaland':5,'raya':3};remaining={'MCI':33,'ARS':33}
    expected=club_effects(effects,injuries,remaining)
    out=node_eval('NT90_PLAYERS.clubEffects('+json.dumps(effects)+','+json.dumps(injuries)+','+json.dumps(remaining)+')')
    assert out==expected


def test_current_ui_contains_all_tracked_names_sources_and_honest_missing_trends():
    layer=load('data/player_ui_2026_27.json')
    assert len(layer['players'])==52 and len({p['club'] for p in layer['players']})==20
    assert all(p['trend']['delta'] is None for p in layer['players'])
    assert all(p['sources'] and p['fetched_at'] for p in layer['players'])
    assert all(p['availability']['status']=='unknown' for p in layer['players'])


def test_preview_compacts_duplicates_without_hiding_source_dates_or_profile_values():
    layer=load('data/player_ui_2026_27.json');view=embedded(layer,6,[p['player_id'] for p in layer['players']])
    assert len(view['players'])==52 and list(view['by_gameweek'])==['6']
    p=next(p for p in view['players'] if p['player_id']=='haaland')
    original=next(p for p in layer['players'] if p['player_id']=='haaland')
    assert p['sources']==original['sources'] and p['fetched_at']==original['fetched_at']
    assert p['effect_profile']['attack']==original['effect_profile']['attack']
    assert len(p['absence'])<=3


def test_built_player_subtree_matches_the_exact_source_preview():
    page=Path(ROOT,'static/index.html').read_text();start=page.index('const EMBEDDED = ')+len('const EMBEDDED = ')
    blob,_=json.JSONDecoder().raw_decode(page[start:])
    layer=load('data/player_ui_2026_27.json');summary=load('data/predictions_2026_27_summary.json')
    known=[p['player_id'] for p in blob['inputs']['players']+blob['inputs']['gks']]
    assert blob['player_layer']==embedded(layer,summary['meta']['next_gw'],known)
    assert blob['baseline']['meta']['player_ui']['fingerprint']==fingerprint(layer)


def test_all_club_pages_have_source_labelled_squad_panels():
    pages=list(Path(ROOT,'static/club').glob('*.html'));assert len(pages)==20
    for page in pages:
        text=page.read_text()
        assert 'squad-panel' in text and 'Fetched/exported:' in text and 'Context only' in text
        assert 'Trend unavailable' in text and 'not a complete squad' in text


def test_every_gameweek_page_has_a_snapshot_digest_not_a_fake_empty_list():
    pages=list(Path(ROOT,'static/gameweek').glob('mw*.html'));assert len(pages)==38
    for page in pages:
        text=page.read_text()
        assert 'missing-digest' in text and 'Availability unknown' in text
        assert 'Later team news never replaces' in text


def test_receipts_do_not_backfill_the_old_gw6_lock_with_current_news():
    text=Path(ROOT,'static/receipts.html').read_text()
    assert 'No sealed availability record at this lock' in text and 'Current team news is not backfilled' in text
    layer=load('data/player_ui_2026_27.json')
    assert layer['by_gameweek']['6']['capture'] is None and layer['by_gameweek']['6']['status']=='not-recorded-at-lock'


def temporary_lock(tmp, seal=True):
    folder=Path(tmp);snapshot={'gameweek':6,'generated':'test only','as_of':'test only','predictions':[{'home':'ARS','away':'MCI','prob_home':60,'prob_draw':20,'prob_away':20}]}
    if seal:
        snapshot['availability']={'captured_at':(dt.datetime.now(dt.timezone.utc)-dt.timedelta(seconds=2)).isoformat(),
                                  'tracked':False,'source':'none','gameweek':6,'clubs':{'ARS':[],'MCI':[]},'coverage':{'ARS':'unknown','MCI':'unknown'}}
    (folder/'gw06.json').write_text(json.dumps(snapshot))
    ledger,lock,_=score_ledger.lock_gameweek(snapshot,path=str(folder/'ledger.json'),source_file='gw06.json')
    return snapshot,ledger,lock


def test_new_availability_lock_is_hash_sealed_bound_to_chain_and_verifiable():
    from check_live import verify_published_chain
    with tempfile.TemporaryDirectory() as tmp:
        snap,ledger,lock=temporary_lock(tmp)
        assert lock['availability_hash']==score_ledger.content_hash(snap['availability'])
        assert score_ledger.availability_evidence(lock,snap)['status']=='sealed-at-lock'
        assert score_ledger.verify(str(Path(tmp,'ledger.json')),snapshot_dir=tmp)['ok']
        assert verify_published_chain(ledger)['ok']
        assert any(r['event']=='availability-locked' for r in ledger['revisions'])


def test_snapshot_availability_tampering_is_detected_without_changing_predictions():
    with tempfile.TemporaryDirectory() as tmp:
        snap,ledger,lock=temporary_lock(tmp)
        snap['availability']['source']='tampered-test-only'
        Path(tmp,'gw06.json').write_text(json.dumps(snap))
        report=score_ledger.verify(str(Path(tmp,'ledger.json')),snapshot_dir=tmp)
        assert not report['ok'] and any('availability changed' in p for p in report['problems'])


def test_deleting_or_rewriting_a_seal_is_detected_by_public_reader():
    from check_live import verify_published_chain
    with tempfile.TemporaryDirectory() as tmp:
        snap,ledger,lock=temporary_lock(tmp)
        bad=copy.deepcopy(ledger);bad['locks'][0].pop('availability_hash');bad['locks'][0].pop('availability')
        assert not verify_published_chain(bad)['ok']
        changed=copy.deepcopy(ledger);changed['locks'][0]['locked_at']='2000-01-01T00:00:00Z'
        assert not verify_published_chain(changed)['ok']


def test_old_lock_is_never_retroactively_sealed_on_an_idempotent_rerun():
    with tempfile.TemporaryDirectory() as tmp:
        snap,ledger,lock=temporary_lock(tmp,seal=False)
        snap['availability']={'tracked':True,'source':'later-test-only','captured_at':dt.datetime.now(dt.timezone.utc).isoformat()}
        after,new,changed=score_ledger.lock_gameweek(snap,path=str(Path(tmp,'ledger.json')),source_file='gw06.json')
        assert changed is False and 'availability_hash' not in new
        assert gameweek_evidence(6,after,snap['availability'])['capture'] is None


def test_capture_after_the_lock_cannot_claim_to_be_lock_time_evidence():
    with tempfile.TemporaryDirectory() as tmp:
        _,_,lock=temporary_lock(tmp)
        lock['availability']['captured_at']='2099-01-01T00:00:00Z'
        lock['availability_hash']=score_ledger.content_hash(lock['availability'])
        assert score_ledger.availability_evidence(lock)['status']=='mismatch'


def test_missing_source_unknown_and_stale_never_render_as_healthy():
    p={'club':'ARS','player_id':'saka','name':'Bukayo Saka'}
    assert player_status(p,{'tracked':False})['status']=='unknown'
    old={'tracked':True,'captured_at':'2000-01-01T00:00:00Z','coverage':{'ARS':'checked'},'clubs':{'ARS':[]}}
    assert player_status(p,old)['status']=='stale'
    panel=availability_digest({'status':'not-recorded','capture':None},['ARS'])
    assert 'Availability unknown' in panel and 'not a clean bill' in panel


def test_squad_and_digest_escape_names_and_reasons():
    marker='<img src=x onerror=alert(1)>'
    layer={'players':[{'player_id':'x','name':marker,'club':'ARS','position':'FWD','score':None,'sources':[marker], 'minutes_by_competition':{},'availability':{'label':marker},'absence':{},'trend':{}}]}
    panel=squad_panel(layer,'ARS');assert marker not in panel and '&lt;img' in panel
    capture={'tracked':True,'source':'test','coverage':{'ARS':'checked'},'clubs':{'ARS':[{'player':marker,'reason':marker}]}}
    panel=availability_digest({'capture':capture,'status':'test'},['ARS']);assert marker not in panel and '&lt;img' in panel


def test_publication_guard_holds_credentials_and_never_echoes_values():
    from tools.publication_gate import inspect_bytes
    token='gh'+'p_'+'aB2cD4eF6gH8iJ0kL2mN4oP6qR8sT0uV2wX4'
    findings=inspect_bytes('static/test.html',('const leaked="'+token+'"').encode())
    assert findings and token not in json.dumps(findings)
    key='a1b2c3d4e5f60718293a4b5c6d7e8f90'
    findings=inspect_bytes('test.json',json.dumps({'note':'API_FOOTBALL_KEY="'+key+'"'}).encode())
    assert findings and key not in json.dumps(findings)


def test_publication_guard_flags_private_files_and_allows_dynamic_reads():
    from tools.publication_gate import inspect_bytes
    assert inspect_bytes('.env',b'EMPTY=')
    assert not inspect_bytes('.env.example',b'API_FOOTBALL_KEY=')
    assert not inspect_bytes('provider.py',b'key = os.environ.get("API_FOOTBALL_KEY")')
    private='-----BEGIN'+' OPENSSH PRIVATE KEY-----'
    assert inspect_bytes('oops.txt',private.encode())


def test_publication_pipeline_checks_security_before_commit_and_artifact_upload():
    workflow=Path(ROOT,'.github/workflows/weekly-update.yml').read_text()
    assert workflow.index('python3 tools/publication_gate.py --staged')<workflow.index('git commit -m')
    assert "steps.audit_safety.outputs.safe == 'true'" in workflow
    ci=Path(ROOT,'.github/workflows/ci.yml').read_text();assert "steps.public_safety.outputs.safe == 'true'" in ci
    assert 'tools/publication_gate.py' in Path(ROOT,'run_all.py').read_text()


def test_saved_storage_migration_is_versioned_without_rewriting_old_scenario_methods():
    store=Path(ROOT,'static/src/store.js').read_text()
    assert 'var VERSION = 4' in store and 'MIGRATIONS[2]' in store and 'MIGRATIONS[3]' in store
    assert 'JSON.parse(JSON.stringify(scenario || {}))' in store


def test_new_controls_and_degradation_reach_the_self_contained_app():
    page=Path(ROOT,'static/index.html').read_text()
    for marker in ('id="squadClub"','id="missingDigest"','NT90_PLAYERS','playerEffectSummary','Context only'):
        assert marker in page
    assert 'Ranges are input assumptions, not win/points intervals' in page
    assert Path(ROOT,'static/players.json').exists()
