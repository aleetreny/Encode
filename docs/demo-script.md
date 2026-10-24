# Three-minute demo script

This script becomes the final demo only after the actual frontend, Gemini agent and production solver are integrated. Until then, use it to rehearse backend behavior with an explicit replay label.

| Time | Show | Say |
|---|---|---|
| 0:00–0:25 | Official CEN source and 1 August evidence | “An energy analyst needs to investigate renewable curtailment. This is CEN historical evidence. It is separate from our model outputs.” |
| 0:25–0:45 | Synthetic topology and assumptions | “We use a five-node, 24-hour illustrative network to explore a constrained counterfactual. Its demand, generation availability and capacities are assumptions.” |
| 0:45–1:35 | Run a live investigation; actual tools and checks | “The agent investigates and calls software tools. The solver calculates dispatch; the independent validator and API checks verify it.” |
| 1:35–2:15 | Baseline/candidate, line bottleneck, battery SOC | “These are simulated MW/MWh results under identical exogenous inputs and a final SOC at least equal to initial SOC. The displayed comparison comes from deterministic checks.” |
| 2:15–2:40 | Validation and export | “The report records assumptions, historical sources, full results and the pass/fail checks. Invalid proposals cannot be approved.” |
| 2:40–3:00 | Operator approve/reject | “This approves a simulated plan only. No commands are sent to physical assets.” |

If replay is used, say “This is an offline replay of verified HiGHS dispatch outputs, not a live Gemini invocation.” The default native fixture reduces simulated normal curtailment by approximately 631.578947 MWh. Under the sudden gas outage, it reduces whole-horizon unserved energy by 391.875 MWh. The event-window average is 66,862.5 household equivalents, using the explicit synthetic factor of 1,000 households/MW; this is not a count of actual reconnections. This value is reproducible for that fixture, not an observed Chilean improvement. Do not prestate it as the outcome of a different future live scenario.

Record the actual application screen with the mode label, tool trace, numerical verification and operator decision visible. Include one genuine failure/revision only if it really runs. Record the final video after live smoke passes, and keep the source commit and scenario hash with the recording.

Show normal dispatch first, then the sudden gas outage during hours 18–22. Show the strict infeasible attempt and the feasible recovery with shedding, the independent no-hindsight check, household units and crisis approval gate. `--mode deterministic` executes this workflow with the real numerical core without Gemini.
