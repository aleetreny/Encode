"""GridPilot optimisation core: deterministic dispatch solver, independent validator, comparison.

Public API — see ``optimisation/DESIGN.md``.
"""

from .compare import compare
from .model import nodal_prices, solve
from .scenario import ScenarioError, load_scenario, modification_menu
from .summary import summarise
from .validate import validate

__all__ = ["solve", "validate", "compare", "summarise", "nodal_prices", "modification_menu", "load_scenario", "ScenarioError"]
