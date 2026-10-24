# Integration status

Person 3's executable `feature/optimisation` code at `fbf0fdfc360a06043ad619b741894050d6cedf9a` is merged unchanged into `feature/data-backend`. Main has not been merged or modified. The actual HiGHS solver, independent validator and their full test suite are available on this branch.

The design is more detailed than the original README and identifies interface differences. The backend includes `backend/p3_adapter.py` so the common fixed-asset path can be integrated without changing the numerical package:

| Native P3 design | API boundary |
|---|---|
| `solve(..., options={allow_unserved: ...})` | Correct keyword dispatch; API options are never mistaken for a candidate positional argument |
| `validate(scenario, solution)` | Preserved two-argument native call |
| `objective` block and explicit efficiencies | Translated from declared API assumptions |
| `timeseries.generation_mw`, `battery_soc_mwh`, etc. | Normalised canonical maps; complete native result retained |
| Structured violations and `error` status | Canonical validation messages and `failed` status |
| Asset modifications, events, ramps and asset-based baseline | Beyond current v1 fixed-asset fixture contract; must not be silently dropped |
| Native `SOC_final >= SOC_initial` | Integrated scenario explicitly declares `final_soc_policy=at_least` |
| Native default curtailment penalty 0 and throughput cost 0.5 | Bridge preserves explicit v1 objective assumptions instead of changing them invisibly |

The bridge is verified against the actual production solver and validator, directly and through HTTP. Canonical arrays must match the retained native output. Additional acceptance checks use a `1e-4` tolerance, allowing for native rounding to `1e-6`. Agent readiness remains false until the real Gemini module is installed; numerical readiness is independent.

The initial objective incentivised simultaneous charge/discharge, which both validators rejected. The integrated data now explicitly use curtailment penalty 0, battery throughput cost 0.5 USD/MWh and a final-SOC floor equal to initial SOC. The bridge sets transmission tie-break cost to 0 explicitly so the canonical total objective has no unreported terms. These adaptations are in Person 4's backend/data files; the numerical package is unchanged.

The first integrated path compares disabled/enabled battery dispatch on fixed assets. If the final demo instead uses battery additions, line uprates or outages, extend the shared scenario/candidate/result schemas, preserve both effective scenarios and their common exogenous inputs, and update independent acceptance tests before labelling those outputs verified. The native module's own tests cover its advanced features independently. The API's `assumed_cost_usd` is the total assumed objective proxy; native `metrics.assumed_cost_proxy_usd` is dispatch-only and must not be substituted. API integration tests compare canonical cost to native `objective.total_usd`.

The agent and frontend branches must consume the checked-in contract fixtures and client. Final integration is a real task with actual module outputs, not a claim satisfied by compatible-looking mock objects.
