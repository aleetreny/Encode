"""Prepare the shared five-node native scenario and audited two-stage cached run."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import ROOT
from backend.models import wire
from backend.native_models import InvestigationSettings, NativeScenario
from backend.native_service import computational_settings, investigate
from backend.worker import fingerprint
from scripts.prepare_data import save


def scenario():
    value = json.loads((ROOT / "optimisation/fixtures/demo_scenario.json").read_text())
    value.update(schema_version="2.0.0", scenario_id="chile-sen-5node-demo")
    value["provenance"].update(
        evidence_id="cen-2026-08-01",
        source_timezone="America/Santiago",
        observed_source_urls=[
            "https://www.coordinador.cl/operacion/documentos/reducciones-de-generacion-renovable/"
        ],
        observed_fields=[],
        derived_fields=["provenance.evidence_id"],
        synthetic_fields=[
            "network_topology",
            "line_limits",
            "generators",
            "batteries",
            "demand_mw_by_node",
            "renewable_availability_mw_by_generator",
            "objective",
            "household_mapping",
        ],
        notes="Synthetic five-node SEN-shaped scenario from Person 3. Official CEN evidence is separate historical context only; no observed generation or demand profile has been aligned or calibrated.",
    )
    value["household_mapping"] = dict(
        households_per_mw=1000,
        residential_share_by_node={n["id"]: 1 for n in value["nodes"]},
        classification="synthetic_assumption",
        interpretation="All modelled unserved load is expressed as residential-equivalent demand at an assumed 1000 households/MW. This is not an official Chilean conversion factor or an actual customer count.",
    )
    value["regulatory_framework"] = [
        dict(
            id="LGSE",
            title="LGSE, DFL 4/2006, Art. 72-1 (reference)",
            url="https://www.bcn.cl/leychile/Navegar?idNorma=258171",
        ),
        dict(
            id="DS32",
            title="DS 32/2026, Art. 117 bis (reference)",
            url="https://www.bcn.cl/leychile/Navegar?idNorma=1225248&idVersion=2026-06-17",
        ),
        dict(
            id="NTSyCS",
            title="CNE technical standards catalog, NTSyCS January 2026",
            url="https://www.cne.cl/normativas/electrica/normas-tecnicas/",
        ),
        dict(
            id="Ley21505",
            title="Ley 21.505, storage (reference)",
            url="https://www.bcn.cl/leychile/navegar?idNorma=1184572",
        ),
    ]
    return wire(NativeScenario.model_validate(value))


def main():
    s = scenario()
    settings = wire(InvestigationSettings())
    bundle = investigate(s, settings)
    save(ROOT / "data/demo/chile-sen-5node-demo.native-scenario.json", s)
    save(
        ROOT / "data/demo/chile-sen-5node-demo.native-replay.json",
        dict(
            scenario_sha256=fingerprint(s),
            computational_settings=computational_settings(s, settings),
            execution_mode="replay",
            live_gemini=False,
            bundle=bundle,
        ),
    )
    print(
        json.dumps(
            dict(
                normal=bundle["comparison"]["curtailment_reduction_mwh"],
                crisis=bundle["crisis_analysis"]["unserved_reduction_mwh"],
                households=bundle["crisis_analysis"]["household_impact"][
                    "average_households_reconnected_equivalent"
                ],
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
