"""Run against review project/worktree. Imports require complete project dependencies."""
import argparse,json,sys
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--project',required=True);args=p.parse_args()
root=Path(args.project).resolve();sys.path.insert(0,str(root/'src'))
from fusion_mvp.workbench.scenario import generate_observations,get_preset
from fusion_mvp.workbench.scenario_challenges import CHALLENGE_PRESET_BUILDERS,validate_challenge_geometry

geometries=[]
for name,builder in CHALLENGE_PRESET_BUILDERS.items():
    sc=builder();geo=validate_challenge_geometry(sc)
    geometries.append({'scenario':name,**geo})
identity=[]
for name in ['challenge_simultaneous_cross_with_id','challenge_near_parallel_2m_with_id','challenge_near_parallel_2m_anon']:
    sc=get_preset(name);bundle=generate_observations(sc)
    rows=[]
    for a in sc.aircraft:
        obs=[o for o in bundle['observations'] if bundle['obs_truth_map'][o['observationId']]==a.truth_id]
        rows.append({'aircraft':a.label,'sources':sorted({o['source'] for o in obs}),'emitted_nonempty_aircraftIds':sorted({o['aircraftId'] for o in obs if o['aircraftId']})})
    identity.append({'scenario':name,'aircraft':rows})
print(json.dumps({'geometry':geometries,'identity':identity},ensure_ascii=False,indent=2))
