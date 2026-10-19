import json
import sys
from pathlib import Path

from fusion_mvp.workbench.runner import WorkbenchRunner
from fusion_mvp.workbench.scenario import generate_observations, get_preset

sc = get_preset("seven_aircraft_combinations")
bundle = generate_observations(sc)
bundle["scenario"] = sc.to_dict()
r = WorkbenchRunner().run_scenario_bundle(bundle, mode="realtime")
Path(sys.argv[1]).write_text(json.dumps(r), encoding="utf-8")
