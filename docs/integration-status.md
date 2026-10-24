# Integration status at branch preparation

The upstream main commit was `62101a7`; it contains the original README. During implementation, a new `feature/optimisation` branch appeared at `932faea6c8dcef99e2806076f80d185f0dac32bd`. It currently contains `optimisation/DESIGN.md`, not executable solver/validator modules. No other owner's files were merged or modified.

The design is more detailed than the original README and identifies interface differences. The backend includes `backend/p3_adapter.py` so the common fixed-asset path can be integrated without changing the numerical package:

| Native P3 design | API boundary |
|---|---|
| `solve(..., options={allow_unserved: ...})` | Correct keyword dispatch; API options are never mistaken for a candidate positional argument |
| `validate(scenario, solution)` | Preserved two-argument native call |
| `objective` block and explicit efficiencies | Translated from declared API assumptions |
| `timeseries.generation_mw`, `battery_soc_mwh`, etc. | Normalised canonical maps; complete native result retained |
| Structured violations and `error` status | Canonical validation messages and `failed` status |
| Asset modifications, events, ramps and asset-based baseline | Beyond current v1 fixed-asset fixture contract; must not be silently dropped |
| Native `SOC_final >= SOC_initial` | v1 API additionally requires its declared final SOC equality |
| Native default curtailment penalty 0 and throughput cost 0.5 | Bridge preserves explicit v1 objective assumptions instead of changing them invisibly |

The current bridge is tested against native-envelope doubles derived from the published design. **Actual native integration has not been verified because executable code was not available at inspection.** Readiness remains false while native functions are missing. The bridge checks its transitive dependencies, so the presence of a wrapper alone cannot make the service claim live readiness.

For the first integrated path, keep the existing fixed-asset scenario and call the bridge from the agent. If the final demo instead uses battery additions, line uprates or outages, extend the shared scenario/candidate/result schemas, preserve both effective scenarios and their common exogenous inputs, and update independent acceptance tests before labelling those outputs verified. Native comparison/cost semantics must be agreed explicitly: the design distinguishes dispatchable-cost proxy from total objective including penalties, while the current API labels its total objective proxy.

The agent and frontend branches must consume the checked-in contract fixtures and client. Final integration is a real task with actual module outputs, not a claim satisfied by compatible-looking mock objects.
