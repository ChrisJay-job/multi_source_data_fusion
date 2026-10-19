import json,sys
from pathlib import Path
from fusion_mvp.workbench.scenario import get_preset,generate_observations
from fusion_mvp.workbench.runner import WorkbenchRunner
r=WorkbenchRunner().run_scenario_bundle(generate_observations(get_preset('seven_aircraft_combinations')),mode='realtime')
Path(sys.argv[1]).write_text(json.dumps(r),encoding='utf-8')
