import React, { useEffect, useState } from 'react';
import {
  CandidateId,
  NodeId,
  OperationMode,
  TimeGranularity,
} from './types/grid';
import {
  CEN_EVIDENCE,
  computeZoneSnapshot,
  getSolution,
  SCENARIO_META,
  VALIDATION_CANDIDATE,
} from './data/scenarioData';
import { AppSidebar } from './components/AppSidebar';
import { ChileMapCanvas } from './components/ChileMapCanvas';
import { LeftPanel } from './components/LeftPanel';
import { FloatingTimeController } from './components/FloatingTimeController';
import { AgentCopilotDrawer } from './components/AgentCopilotDrawer';
import { CenEvidenceModal } from './components/CenEvidenceModal';

export const App: React.FC = () => {
  // Default to C1 North Battery at 12:00 CLST (step 48 = 12:00) so the user immediately sees
  // the solar corridor, L2 bottleneck, and C1 battery absorbing curtailed solar
  const [operationMode, setOperationMode] = useState<OperationMode>('normal');
  const [candidateId, setCandidateId] = useState<CandidateId>('c1_battery_norte_grande');
  const [selectedZone, setSelectedZone] = useState<NodeId | 'all'>('all');
  const [step96, setStep96] = useState<number>(12 * 4); // 12:00 CLST
  const [granularity, setGranularity] = useState<TimeGranularity>('15min');
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [copilotOpen, setCopilotOpen] = useState<boolean>(true);
  const [evidenceOpen, setEvidenceOpen] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const baselineSolution = getSolution(operationMode, 'baseline');
  const activeSolution = getSolution(operationMode, candidateId);
  const currentSnap = computeZoneSnapshot(activeSolution, step96, selectedZone);

  // Playback interval for 15-min or Hourly timeline
  useEffect(() => {
    if (!isPlaying) return;
    const stepDelta = granularity === '15min' ? 1 : 4;
    const timer = setInterval(() => {
      setStep96((prev) => (prev + stepDelta) % 96);
    }, 320);
    return () => clearInterval(timer);
  }, [isPlaying, granularity]);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => {
      setToastMessage((curr) => (curr === msg ? null : curr));
    }, 3500);
  };

  // Automatically jump to 19:00 CLST when user activates 18:00 Sudden Outage mode
  // or back to 12:00 CLST when switching to Normal Day if currently in the evening
  const handleSelectOperationMode = (mode: OperationMode) => {
    setOperationMode(mode);
    if (mode === 'sudden_outage') {
      setStep96(19 * 4);
      showToast('⚡ Crisis Mode Active: 18:00 gas_centro (600 MW) Sudden Outage at Hour 19:00 CLST');
    } else {
      setStep96(12 * 4);
      showToast('☀ Normal SCED Day Active: Viewing 12:00 CLST Midday Solar Peak');
    }
  };

  const handleExportRioReport = () => {
    const rioReport = {
      report_type: 'CEN_AUDITED_RIO_DISPATCH_REPORT',
      generated_at_utc: new Date().toISOString(),
      regulatory_framework: [
        'LGSE DFL N° 4/2006 Art. 72°-1',
        'Supreme Decree N° 32/2026 Art. 117 bis (Audited SCED)',
        'NTSyCS (CNE N-1 & EDAC Load Shedding)',
        'Law N° 21.505 (Storage & Electromobility SAE)',
      ],
      provenance: {
        simulation_scenario: SCENARIO_META.scenario_id,
        simulation_mode: SCENARIO_META.mode,
        observed_cen_evidence_id: CEN_EVIDENCE.evidence_id,
        observed_cen_sha256: CEN_EVIDENCE.source_sha256,
      },
      operation_regime: operationMode,
      selected_candidate: candidateId,
      solver_verification: activeSolution.solver,
      independent_physics_validation: VALIDATION_CANDIDATE,
      baseline_metrics: baselineSolution.metrics,
      candidate_metrics: activeSolution.metrics,
    };

    const blob = new Blob([JSON.stringify(rioReport, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `GridPilot_RIO_${candidateId}_${operationMode}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Exported DS N° 32/2026 Audited RIO JSON Report');
  };

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#262626] text-neutral-100">
      {/* 1. Fixed 63px Left Sidebar (Electricity Maps AppSidebar) */}
      <AppSidebar
        activePanel={evidenceOpen ? 'evidence' : copilotOpen ? 'copilot' : 'map'}
        onToggleCopilot={() => setCopilotOpen((v) => !v)}
        onOpenEvidence={() => setEvidenceOpen(true)}
        onExportRioReport={handleExportRioReport}
        operationMode={operationMode}
        onToggleCrisis={() =>
          handleSelectOperationMode(operationMode === 'normal' ? 'sudden_outage' : 'normal')
        }
        copilotOpen={copilotOpen}
      />

      {/* 2. Full-Screen Interactive Chile SEN 5-Zone Map Canvas */}
      <ChileMapCanvas
        baselineSolution={baselineSolution}
        activeSolution={activeSolution}
        step96={step96}
        selectedZone={selectedZone}
        onSelectZone={setSelectedZone}
        candidateId={candidateId}
        onSelectCandidate={setCandidateId}
        operationMode={operationMode}
        onSelectOperationMode={handleSelectOperationMode}
        copilotOpen={copilotOpen}
      />

      {/* 3. Floating Left Zone Details Panel */}
      <LeftPanel
        baselineSolution={baselineSolution}
        activeSolution={activeSolution}
        step96={step96}
        onChangeStep96={setStep96}
        selectedZone={selectedZone}
        onSelectZone={setSelectedZone}
        candidateId={candidateId}
        onSelectCandidate={setCandidateId}
        operationMode={operationMode}
        onOpenEvidence={() => setEvidenceOpen(true)}
      />

      {/* 4. Floating Bottom-Left Time Controller (15-min / Hourly Day-Night Slider) */}
      <FloatingTimeController
        step96={step96}
        onChangeStep96={setStep96}
        isPlaying={isPlaying}
        onTogglePlay={() => setIsPlaying((p) => !p)}
        granularity={granularity}
        onChangeGranularity={setGranularity}
        operationMode={operationMode}
        chileTimeLabel={currentSnap.chileTimeLabel}
      />

      {/* 5. Collapsible Right Gemini 4 Argon Copilot & Validator Drawer */}
      <AgentCopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        candidateId={candidateId}
        onSelectCandidate={setCandidateId}
        operationMode={operationMode}
        onSelectOperationMode={handleSelectOperationMode}
        activeSolution={activeSolution}
        onExportRioReport={handleExportRioReport}
      />

      {/* 6. CEN Observed Historical Evidence Modal */}
      <CenEvidenceModal open={evidenceOpen} onClose={() => setEvidenceOpen(false)} />

      {/* Toast Notification Pill */}
      {toastMessage && (
        <div className="fixed bottom-16 left-1/2 z-50 -translate-x-1/2 rounded-full border border-emerald-500/50 bg-neutral-900/95 px-4 py-1.5 text-xs font-medium text-emerald-300 shadow-2xl backdrop-blur-md">
          {toastMessage}
        </div>
      )}
    </div>
  );
};

export default App;
