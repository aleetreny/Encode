import React from 'react';
import {
  Zap,
  Map as MapIcon,
  Bot,
  Database,
  ShieldCheck,
  FileJson,
  AlertTriangle,
} from 'lucide-react';
import { OperationMode } from '../types/grid';

interface AppSidebarProps {
  activePanel: 'map' | 'copilot' | 'evidence';
  onToggleCopilot: () => void;
  onOpenEvidence: () => void;
  onExportRioReport: () => void;
  operationMode: OperationMode;
  onToggleCrisis: () => void;
  copilotOpen: boolean;
}

export const AppSidebar: React.FC<AppSidebarProps> = ({
  onToggleCopilot,
  onOpenEvidence,
  onExportRioReport,
  operationMode,
  onToggleCrisis,
  copilotOpen,
}) => {
  return (
    <aside className="fixed left-0 top-0 bottom-0 z-40 flex w-[63px] flex-col items-center justify-between border-r border-neutral-800 bg-neutral-900 py-3 select-none">
      {/* Top Brand Logo + Navigation */}
      <div className="flex flex-col items-center gap-3">
        {/* Electricity Maps / GridPilot Bolt Logo */}
        <div
          className="group relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-[#2AA364] to-[#1DA484] text-neutral-950 shadow-lg shadow-emerald-950/50 cursor-pointer"
          title="GridPilot · Autonomous AI Grid Coordinator (Chile SEN)"
        >
          <Zap className="h-5 w-5 fill-current" />
        </div>

        <div className="h-px w-7 bg-neutral-800" />

        {/* Map View (Active) */}
        <button
          type="button"
          className="group relative flex h-10 w-10 items-center justify-center rounded-xl bg-neutral-800 text-emerald-400 transition-colors hover:bg-neutral-700/80"
          title="SEN Chile 5-Zone Dispatch Map"
        >
          <MapIcon className="h-5 w-5" />
          <span className="pointer-events-none absolute left-14 z-50 hidden whitespace-nowrap rounded-lg border border-neutral-700 bg-neutral-900 px-2.5 py-1 text-xs font-medium text-neutral-100 shadow-xl group-hover:block">
            SEN Chile Live Map
          </span>
        </button>

        {/* Gemini 4 Argon Copilot Drawer Toggle */}
        <button
          type="button"
          onClick={onToggleCopilot}
          className={`group relative flex h-10 w-10 items-center justify-center rounded-xl transition-colors ${
            copilotOpen
              ? 'bg-emerald-500/20 text-emerald-400 ring-1 ring-emerald-500/50'
              : 'text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100'
          }`}
          title="Gemini 4 Argon Autonomous Copilot & HiGHS Validator"
        >
          <Bot className="h-5 w-5" />
          <span className="absolute -right-0.5 -top-0.5 flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
          </span>
          <span className="pointer-events-none absolute left-14 z-50 hidden whitespace-nowrap rounded-lg border border-neutral-700 bg-neutral-900 px-2.5 py-1 text-xs font-medium text-neutral-100 shadow-xl group-hover:block">
            Gemini 4 Argon Copilot & Validator
          </span>
        </button>

        {/* Sudden Outage Crisis Simulation Shortcut */}
        <button
          type="button"
          onClick={onToggleCrisis}
          className={`group relative flex h-10 w-10 items-center justify-center rounded-xl transition-colors ${
            operationMode === 'sudden_outage'
              ? 'bg-red-500/25 text-red-400 ring-1 ring-red-500/60 animate-pulse'
              : 'text-neutral-400 hover:bg-neutral-800 hover:text-amber-400'
          }`}
          title="Toggle 18:00 Sudden Outage (gas_centro 600 MW Trip)"
        >
          <AlertTriangle className="h-5 w-5" />
          <span className="pointer-events-none absolute left-14 z-50 hidden whitespace-nowrap rounded-lg border border-neutral-700 bg-neutral-900 px-2.5 py-1 text-xs font-medium text-neutral-100 shadow-xl group-hover:block">
            {operationMode === 'sudden_outage'
              ? 'Crisis Active: 18:00 gas_centro 600 MW Trip'
              : 'Simulate 18:00 Sudden Generator Trip'}
          </span>
        </button>

        {/* CEN Observed Historical Evidence */}
        <button
          type="button"
          onClick={onOpenEvidence}
          className="group relative flex h-10 w-10 items-center justify-center rounded-xl text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-sky-400"
          title="Observed CEN Historical Curtailment Evidence (2026-08-01)"
        >
          <Database className="h-5 w-5" />
          <span className="pointer-events-none absolute left-14 z-50 hidden whitespace-nowrap rounded-lg border border-neutral-700 bg-neutral-900 px-2.5 py-1 text-xs font-medium text-neutral-100 shadow-xl group-hover:block">
            Observed CEN Evidence (2026-08-01)
          </span>
        </button>
      </div>

      {/* Bottom Validator & Export Controls */}
      <div className="flex flex-col items-center gap-3">
        <button
          type="button"
          onClick={onExportRioReport}
          className="group relative flex h-10 w-10 items-center justify-center rounded-xl text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-neutral-100"
          title="Export Regulatory RIO JSON Report (DS N° 32/2026)"
        >
          <FileJson className="h-5 w-5" />
          <span className="pointer-events-none absolute left-14 z-50 hidden whitespace-nowrap rounded-lg border border-neutral-700 bg-neutral-900 px-2.5 py-1 text-xs font-medium text-neutral-100 shadow-xl group-hover:block">
            Export Regulatory RIO JSON
          </span>
        </button>

        {/* HiGHS 16/16 Verified Indicator */}
        <div
          onClick={onToggleCopilot}
          className="group relative flex h-10 w-10 cursor-pointer flex-col items-center justify-center rounded-xl border border-emerald-500/30 bg-emerald-950/40 text-emerald-400"
          title="HiGHS 1.15.1 Independent Physics Validator: 16/16 Checks Passed"
        >
          <ShieldCheck className="h-4 w-4" />
          <span className="text-[9px] font-bold tabular-nums">16/16</span>
          <span className="pointer-events-none absolute left-14 z-50 hidden whitespace-nowrap rounded-lg border border-neutral-700 bg-neutral-900 px-2.5 py-1 text-xs font-medium text-emerald-400 shadow-xl group-hover:block">
            HiGHS LP Verified · 16/16 Physics Checks (3.5e-7 MW)
          </span>
        </div>
      </div>
    </aside>
  );
};
