"""Validation workbench: scenario generation, import, evaluation (truth never enters fusion)."""

from .importer import MappingTemplate, import_sql_stream, import_tabular

__all__ = [
    "MappingTemplate",
    "import_tabular",
    "import_sql_stream",
    "Scenario",
    "generate_observations",
    "load_scenario",
    "preset_three_aircraft",
    "evaluate_run",
    "WorkbenchRunner",
]


def __getattr__(name: str):
    if name in {
        "Scenario",
        "generate_observations",
        "load_scenario",
        "preset_three_aircraft",
    }:
        from . import scenario as _scenario

        return getattr(_scenario, name)
    if name == "evaluate_run":
        from .evaluator import evaluate_run

        return evaluate_run
    if name == "WorkbenchRunner":
        from .runner import WorkbenchRunner

        return WorkbenchRunner
    raise AttributeError(name)
