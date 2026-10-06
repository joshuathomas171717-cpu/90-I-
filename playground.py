"""Build a self-contained, free career sandbox + personal prediction challenge.

Games freeze their world and do not write official results/predictions/locks. Management coefficients,
credits and board targets are explicit game rules, not measured football effects or real market fees.
"""
import csv
import hashlib
import json
from pathlib import Path

from safe_embed import script_json
from player_data import atomic_json
from feeds import parse_window

ROOT = Path(__file__).resolve().parent
DATA = ROOT/'data'
SRC = ROOT/'static'/'game'
OUT = ROOT/'static'/'play.html'
MANIFEST = DATA/'playground_manifest.json'


def rows(name, data=DATA):
    with open(data/name, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def payload(data=DATA):
    data=Path(data)
    summary=json.loads((data/'predictions_2026_27_summary.json').read_text())
    ui=json.loads((data/'player_ui_2026_27.json').read_text())
    by_id={p['player_id']:p for p in ui['players']}
    projections=sorted(summary['table_projections'],key=lambda t:-t['proj_pts'])
    expected={p['code']:i+1 for i,p in enumerate(projections)}
    teams=[]
    for t in rows('teams_2026_27.csv',data):
        rank=expected[t['code']]
        teams.append({'code':t['code'],'name':t['name'],'short':t['short'],'color':t['primary_color'],
                      **{k:int(t[col]) for k,col in [('p','P'),('w','W'),('d','D'),('l','L'),('gf','GF'),('ga','GA'),('pts','Pts')]},
                      'target':4 if rank<=6 else 10 if rank<=12 else 17})
    players=[]
    for p in rows('players_2026_27.csv',data):
        context=by_id.get(p['player_id']) or {};profile=context.get('effect_profile') or {}
        # Fallbacks are GAME priors only, not new production-model inputs.
        attack=max(0,min(30,float(profile.get('attack',0 if p['pos']=='GK' else 4))))
        defence=max(0,min(25,float(profile.get('defence',6 if p['pos']=='GK' else 1))))
        form=context.get('score');form=50 if form is None else float(form)
        price=max(20,min(90,round(22+45*attack/30+35*defence/25+form/4)))
        players.append({'id':p['player_id'],'name':p['name'],'club':p['club'],'pos':p['pos'],
                        'attack':round(attack,4),'defence':round(defence,4),'price':price,
                        'source':', '.join(context.get('sources') or ['game prior'])[:160]})
    fixtures=[{'id':f["home"]+'-'+f['away'],'gw':int(f['gw']),'h':f['home'],'a':f['away'],
               'lh':float(f['lambda_home']),'la':float(f['lambda_away']),'dates':f['dates']}
              for f in rows('projected_fixtures_2026_27.csv',data)]
    world={'version':2,'rules':'club-manager/2','season':'2026-27','asOf':summary['meta']['as_of_date'][:10],
           'teams':teams,'players':players,'fixtures':fixtures}
    world['hash']=hashlib.sha256(json.dumps(world,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:32]
    next_gw=int(summary['meta']['next_gw'])
    predictions=summary['next_gw_predictions']
    selected=[];model={}
    for p in predictions:
        key=p['home']+'-'+p['away']
        selected.append({'id':key,'gw':next_gw,'h':p['home'],'a':p['away'],'lh':p['lambda_home'],'la':p['lambda_away'],'dates':p['dates']})
        values=[('H',p['prob_home']),('D',p['prob_draw']),('A',p['prob_away'])]
        call=max(values,key=lambda item:item[1])[0]
        consistent=[s for s in p['top_scorelines'] if ('H' if s['home_goals']>s['away_goals'] else 'A' if s['away_goals']>s['home_goals'] else 'D')==call]
        if not consistent:
            raise ValueError('model challenge needs a score consistent with its outcome call')
        model[key]={'outcome':call,'score':[consistent[0]['home_goals'],consistent[0]['away_goals']]}
    window=parse_window(selected[0]['dates']) if selected else (None,None)
    # Conservative whole-matchweek window start, NOT an invented exact kickoff.
    deadline=window[0].isoformat()+'T00:00:00Z' if window[0] else None
    actual=[{'id':r['home']+'-'+r['away'],'gw':int(r['gw']),'hg':int(r['home_goals']),'ag':int(r['away_goals'])}
            for r in rows('matches_2026_27_played.csv',data)]
    return {'world':world,'challenge':{'version':1,'season':'2026-27','gw':next_gw,'deadline':deadline,
                                      'asOf':world['asOf'],'fixtures':selected,'model':model,'actual':actual}}


def build(data=DATA, output=OUT, manifest=MANIFEST):
    pack=payload(data)
    parts={p:(SRC/p).read_text() for p in ('shell.html','style.css','engine.js','ui.js')}
    fonts=(ROOT/'static/src/fonts.css').read_text()
    store=(ROOT/'static/src/store.js').read_text()
    digest=hashlib.sha256(json.dumps(pack,sort_keys=True,separators=(',',':')).encode())
    for key in sorted(parts):digest.update(parts[key].encode())
    digest.update(store.encode());fingerprint=digest.hexdigest()[:16]
    pack['build']={'version':'club-manager/2','fingerprint':fingerprint}
    html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Club Manager & Beat the Model — NINETY+</title><meta name="description" content="Take a club through a simulated season: tactics, training, tracked-player transfers and your own match predictions. Free, browser-only and clearly separate from real football results.">
<meta name="playground-fingerprint" content="%s"><style>%s\n%s</style></head><body>%s<script>
const PLAY_DATA = %s;
%s\n%s\n%s
</script></body></html>''' % (fingerprint,fonts,parts['style.css'],parts['shell.html'],script_json(pack),store,parts['engine.js'],parts['ui.js'])
    Path(output).parent.mkdir(parents=True,exist_ok=True);Path(output).write_text(html)
    result={'version':'club-manager/2','fingerprint':fingerprint,'world_hash':pack['world']['hash'],
            'season':'2026-27','as_of':pack['world']['asOf'],'players':len(pack['world']['players']),
            'fixtures':len(pack['world']['fixtures']),'page':'play.html'}
    atomic_json(str(manifest),result)
    return result


if __name__=='__main__':
    result=build();print('Playground built: %d tracked players, %d remaining fixtures; career worlds and personal challenges isolated from official data.' % (result['players'],result['fixtures']))
