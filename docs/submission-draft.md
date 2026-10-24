# GridPilot — submission working copy

Status: **not submitted**. Public app, final integrated release and video are not yet available in this workstream. Fill the final fields only with verified results.

## Problem and user

GridPilot helps electricity-system analysts investigate renewable curtailment and compare explainable, reproducible dispatch counterfactuals. Official CEN evidence provides historical context. A deliberately small synthetic network makes assumptions and numerical constraints visible.

## Implemented backend contribution

The service includes versioned contracts, source preservation and provenance, a reproducible CEN extraction pipeline with quality findings, FastAPI routes, isolated job execution, persistent local run history, idempotency, independent acceptance checks, deterministic comparison metrics, downloadable audit reports and simulation-only approval/rejection. The integrated production HiGHS solver and independent validator supply honestly labelled replay fixtures and a synthetic fallback.

The 1 August 2026 CEN evidence is complete for the extracted solar/wind records. Historical demand and actual generation have not been aligned to calibrate the synthetic model. GridPilot does not operate or reproduce Chile's actual dispatch and does not claim real cost or emissions savings.

## Final team fields

- Repository: https://github.com/aleetreny/Encode
- Public application: **pending integrated deployment**
- Final release commit: **pending team integration**
- Three-minute video: **pending actual recording**
- Gemini model and agent tools actually used: **pending Person 2 live execution evidence**
- Production solver and independent validator: **Person 3 HiGHS 1.15.1 module integrated and API-tested on the fixed-asset path**
- Frontend: **pending Person 1 integration**
- Live verification outcome: **pending real live smoke and report**

Do not describe the offline replay as a live model run. Replace the pending fields using the deployed application's actual report and video. The final entry should state the actual model identifiers, sources, limitations and operator control.
