import React from 'react';
import {
  Database,
  X,
  Sun,
  Wind,
  ExternalLink,
  ShieldCheck,
  Info,
} from 'lucide-react';
import { CEN_EVIDENCE } from '../data/scenarioData';
import { GlassContainer } from './GlassContainer';

interface CenEvidenceModalProps {
  open: boolean;
  onClose: () => void;
}

export const CenEvidenceModal: React.FC<CenEvidenceModalProps> = ({ open, onClose }) => {
  if (!open) return null;

  const solarTech = CEN_EVIDENCE.technologies.find((t) => t.technology === 'solar')!;
  const windTech = CEN_EVIDENCE.technologies.find((t) => t.technology === 'wind')!;
  const maxHourlyTotal = Math.max(
    ...CEN_EVIDENCE.hour_labels.map(
      (_, i) => (solarTech.hourly_mwh[i] || 0) + (windTech.hourly_mwh[i] || 0)
    )
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <GlassContainer className="overflow-hidden border-neutral-700">
          {/* Modal Header */}
          <div className="flex items-center justify-between border-b border-neutral-800 px-5 py-4">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-sky-500/20 text-sky-400 ring-1 ring-sky-500/40">
                <Database className="h-5 w-5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="font-poppins text-base font-semibold text-white">
                    Observed CEN Historical Curtailment Evidence
                  </h2>
                  <span className="rounded-full bg-sky-500/20 px-2 py-0.5 font-mono text-[10px] font-semibold text-sky-300 ring-1 ring-sky-500/40">
                    OBSERVED · {CEN_EVIDENCE.event_date}
                  </span>
                </div>
                <p className="text-xs text-neutral-400">
                  Coordinador Eléctrico Nacional (CEN) Official ERV Reduction Workbook
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={onClose}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-neutral-400 hover:bg-neutral-800 hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Modal Body */}
          <div className="p-5 space-y-4 max-h-[80vh] overflow-y-auto">
            {/* Key Observed Totals */}
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-xl border border-neutral-800 bg-neutral-950/70 p-3">
                <div className="flex items-center gap-1.5 text-xs text-amber-300 font-medium">
                  <Sun className="h-4 w-4 text-[#FFC700]" />
                  <span>Observed Solar Curtailed</span>
                </div>
                <div className="mt-1 font-mono text-lg font-bold text-white tabular-nums">
                  {solarTech.daily_mwh.toLocaleString('en-US', { maximumFractionDigits: 1 })} MWh
                </div>
                <div className="text-[11px] text-neutral-400">
                  Across {solarTech.plant_count} PV plants · {solarTech.coverage}
                </div>
              </div>

              <div className="rounded-xl border border-neutral-800 bg-neutral-950/70 p-3">
                <div className="flex items-center gap-1.5 text-xs text-sky-300 font-medium">
                  <Wind className="h-4 w-4 text-[#69D6F8]" />
                  <span>Observed Wind Curtailed</span>
                </div>
                <div className="mt-1 font-mono text-lg font-bold text-white tabular-nums">
                  {windTech.daily_mwh.toLocaleString('en-US', { maximumFractionDigits: 1 })} MWh
                </div>
                <div className="text-[11px] text-neutral-400">
                  Across {windTech.plant_count} wind farms · {windTech.coverage}
                </div>
              </div>

              <div className="rounded-xl border border-neutral-800 bg-neutral-950/70 p-3">
                <div className="flex items-center gap-1.5 text-xs text-emerald-300 font-medium">
                  <ShieldCheck className="h-4 w-4 text-emerald-400" />
                  <span>Workbook Audit Residual</span>
                </div>
                <div className="mt-1 font-mono text-lg font-bold text-emerald-400 tabular-nums">
                  3.41e-13 MWh
                </div>
                <div className="font-mono text-[10px] text-neutral-400 truncate" title={CEN_EVIDENCE.source_sha256}>
                  SHA256: {CEN_EVIDENCE.source_sha256.slice(0, 16)}…
                </div>
              </div>
            </div>

            {/* 24-Hour Stacked Observed Solar + Wind Reduction Chart */}
            <div className="rounded-xl border border-neutral-800 bg-neutral-950/80 p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="font-poppins text-xs font-semibold text-neutral-200">
                  Hourly Observed Renewable Reductions on {CEN_EVIDENCE.event_date} (Hours 1–24)
                </span>
                <div className="flex items-center gap-3 text-[11px]">
                  <span className="flex items-center gap-1 text-neutral-300">
                    <span className="h-2.5 w-2.5 rounded-sm bg-[#FFC700]" /> Solar PV (77 plants)
                  </span>
                  <span className="flex items-center gap-1 text-neutral-300">
                    <span className="h-2.5 w-2.5 rounded-sm bg-[#69D6F8]" /> Wind (56 plants)
                  </span>
                </div>
              </div>

              <div className="h-36 flex items-end gap-1.5 pt-2">
                {CEN_EVIDENCE.hour_labels.map((hrLabel, idx) => {
                  const sVal = solarTech.hourly_mwh[idx] || 0;
                  const wVal = windTech.hourly_mwh[idx] || 0;
                  const sPct = (sVal / maxHourlyTotal) * 100;
                  const wPct = (wVal / maxHourlyTotal) * 100;

                  return (
                    <div
                      key={hrLabel}
                      className="flex-1 h-full flex flex-col justify-end items-center group"
                      title={`Workbook Hour ${hrLabel}: Solar ${sVal.toFixed(1)} MWh + Wind ${wVal.toFixed(1)} MWh`}
                    >
                      <div
                        className="w-full rounded-t bg-[#FFC700] transition-all"
                        style={{ height: `${sPct}%` }}
                      />
                      <div
                        className="w-full bg-[#69D6F8] transition-all"
                        style={{ height: `${wPct}%` }}
                      />
                      <span className="mt-1 font-mono text-[9px] text-neutral-500 group-hover:text-white">
                        {hrLabel}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Strict Data Hygiene & Provenance Classification */}
            <div className="rounded-xl border border-amber-500/30 bg-amber-950/20 p-3.5">
              <div className="flex items-center gap-2 text-xs font-semibold text-amber-300 mb-1.5">
                <Info className="h-4 w-4 shrink-0" />
                <span>Strict Provenance Separation (Observed vs. Synthetic Simulation)</span>
              </div>
              <ul className="space-y-1 text-xs text-neutral-300 list-disc pl-4">
                <li>
                  <strong className="text-white">Observed (CEN Workbook):</strong> Plant-level solar
                  (6,501.2 MWh) and wind (11,060.9 MWh) curtailment totals from official Coordinador
                  Eléctrico Nacional spreadsheet exports.
                </li>
                <li>
                  <strong className="text-white">Simulated (Synthetic 5-Node SEN):</strong> Network
                  topology (<code className="text-emerald-300">L1–L4</code>), nodal demand profiles,
                  generator variable costs, and HiGHS LP counterfactual dispatch are synthetic
                  assumptions shaped after the Chilean North–Central solar corridor pattern.
                </li>
              </ul>

              <div className="mt-3 flex flex-wrap gap-2">
                {CEN_EVIDENCE.source_urls.map((url, i) => (
                  <a
                    key={url}
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 rounded-lg border border-neutral-700 bg-neutral-900 px-2.5 py-1 text-[11px] font-medium text-sky-300 hover:bg-neutral-800"
                  >
                    <ExternalLink className="h-3 w-3" />
                    <span>{i === 0 ? 'Official CEN August 2026 XLSX' : 'CEN ERV Portal'}</span>
                  </a>
                ))}
              </div>
            </div>
          </div>
        </GlassContainer>
      </div>
    </div>
  );
};
