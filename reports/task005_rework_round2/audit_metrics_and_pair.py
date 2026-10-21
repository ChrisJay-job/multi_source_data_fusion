"""Small independent counterexamples; run with --project pointing to the delivered project."""
import argparse,json,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--project',required=True);a=p.parse_args();root=Path(a.project).resolve();sys.path.insert(0,str(root/'src'))
from fusion_mvp.workbench.evaluator import position_errors
from fusion_mvp.workbench.scenario import get_preset,generate_observations
from fusion_mvp.workbench.scenario_challenges import validate_challenge_geometry
from fusion_mvp.workbench.runner import WorkbenchRunner

# Exact synthetic contract: commit at t=0 is (0,0); display prediction at t=2 is 20m east.
# Ground truth is identical to both correct states, so each time-aligned error should be zero.
truth={'T':[{'time':'2026-04-09T12:00:00Z','lat':0.,'lon':0.}, {'time':'2026-04-09T12:00:02Z','lat':0.,'lon':20/111320.}]}
tr={'fusionId':'F','stateTime':'2026-04-09T12:00:00Z','displayStateTime':'2026-04-09T12:00:02Z','positionMode':'predicted','latitude':0.,'longitude':20/111320.,'committedHistory':[{'stateTime':'2026-04-09T12:00:00Z','latitude':0.,'longitude':0.}]}
committed=position_errors(truth,[tr],{'F':'T'},mode='committed')
display=position_errors(truth,[tr],{'F':'T'},mode='display')
geo=validate_challenge_geometry(get_preset('seven_plus_challenges_with_id'))
sc=get_preset('seven_aircraft_combinations');sc.aircraft=sc.aircraft[:1];sc.duration_s=1
out=WorkbenchRunner().run_scenario_bundle(generate_observations(sc),mode='realtime')
first=out['snapshots'][0]
result={'rmse_alignment':{'expected_committed_error_m':0,'actual_committed_mode_error_m':committed[0]['error_m'],'expected_display_error_m':0,'actual_display_mode_error_m':display[0]['error_m'],'explanation':'committed mode selects stateTime, but still uses display-predicted latitude/longitude instead of committedHistory'},'near_pair':{'focused_pair':['J','K'],'global_pair':geo['min_truth_distance_pair'],'global_distance_m':geo['min_truth_distance_m'],'global_time_s':geo['min_truth_distance_at_s'],'pair_check':next(c for c in geo['checks'] if c['kind']=='near_parallel_spacing')},'buffer_counterexample':{'processingTime':first['processingTime'],'watermark':first['watermark'],'n_tracks':len(first['tracks']),'counts_at':first['counts_at'],'expected_processed_observations_at_first_snapshot':0,'ui_current_alias':'已处理观测数 = delivered_at_t; 仅绑定事件 = source_binds'}}
print(json.dumps(result,ensure_ascii=False,indent=2))
