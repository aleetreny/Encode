"""GridPilot optimisation core: deterministic dispatch solver, independent validator, comparison.

Public API — see ``optimisation/DESIGN.md``.
"""

from .compare import compare
from .model import solve
from .scenario import ScenarioError, load_scenario, modification_menu
from .validate import validate

__all__ = ["solve", "validate", "compare", "modification_menu", "load_scenario", "ScenarioError"]
