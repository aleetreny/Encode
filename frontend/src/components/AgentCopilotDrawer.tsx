import React, { useState } from 'react';
import {
  Bot,
  CheckCircle2,
  XCircle,
  Sparkles,
  ShieldCheck,
  Scale,
  Play,
  FileJson,
  X,
  AlertTriangle,
  RefreshCw,
  Check,
  Terminal,
} from 'lucide-react';
import {
  CandidateId,
  OperationMode,
  SolverSolution,
} from '../types/grid';
import {
  VALIDATION_CANDIDATE,
  VALIDATION_INFEASIBLE,
} from '../data/scenarioData';
import { GlassContainer } from './GlassContainer';

interface AgentCopilotDrawerProps {
  open: boolean;
  onClose: () => void;
  candidateId: CandidateId;
  onSelectCandidate: (id: CandidateId) => void;
  operationMode: OperationMode;
  onSelectOperationMode: (mode: OperationMode) => void;
  activeSolution: SolverSolution;
  onExportRioReport: () => void;
}

export const AgentCopilotDrawer: React.FC<AgentCopilotDrawerProps> = ({
  open,
  onClose,
  candidateId,
  onSelectCandidate,
  operationMode,
  onSelectOperationMode,
  activeSolution,
  onExportRioReport,
}) => {
  const [activeTab, setActiveTab] = useState<'trace' | 'validator' | 'legal'>('trace');
  const [isRunningLoop, setIsRunningLoop] = useState(false);
  const [activeStepIdx, setActiveStepIdx] = useState<number>(7);
  const [approvalStatus, setApprovalStatus] = useState<'pending' | 'approved' | 'rejected'>(
    'pending'
  );
  const [showInfeasibleProof, setShowInfeasibleProof] = useState(false);

  if (!open) return null;

  const runLiveInvestigationReplay = () => {
    setIsRunningLoop(true);
    setApprovalStatus('pending');
    setActiveStepIdx(0);
    let step = 0;
    const interval = setInterval(() => {
      step += 1;
      if (step >= 7) {
        setActiveStepIdx(7);
        setIsRunningLoop(false);
        onSelectCandidate('c1_battery_norte_grande');
        clearInterval(interval);
      } else {
        setActiveStepIdx(step);
      }
    }, 380);
  };

  const toolTraceSteps = [
    {
      idx: 1,
      tool: 'load_scenario("chile-demo-001")',
      badge: '5 nodes · 4 lines',
      status: 'done',
      detail:
        'Loaded 24h synthetic SEN topology (Norte Grande → Sur) + 9 generators + 30 MW Centro battery.',
    },
    {
      idx: 2,
      tool: 'inspect_evidence("cen-2026-08-01")',
      badge: 'SHA-256 verified',
      status: 'done',
      detail:
        'Observed CEN workbook: 6,501.2 MWh solar (77 plants) & 11,060.9 MWh wind (56 plants) curtailed.',
    },
    {
      idx: 3,
      tool: 'run_optimisation("baseline")',
      badge: 'HiGHS LP ·optimal',
      status: 'done',
      detail:
        'Diagnosed bottleneck: Corridor L2 (Norte Chico → Centro) binds at 400 MW for 8 hours (09:00–16:00), curtailing 1,368.2 MWh of solar_ng.',
    },
    {
      idx: 4,
      tool: 'run_optimisation("c2_battery_sur")',
      badge: 'SELF-CORRECTION',
      status: 'rejected',
      detail:
        'Hypothesis rejected: 150 MW battery at n_sur sits downstream of congested L2 → 0.0 MWh midday solar curtailment reduction.',
    },
    {
      idx: 5,
      tool: 'simulate_crisis("gas_centro", hr=18..21, strict=true)',
      badge: 'INFEASIBLE CAUGHT',
      status: 'self_corrected',
      detail:
        '600 MW thermal trip at 18:00: strict mode (allow_unserved=false) rejected by validator (demand 1,769 MW > max supply 1,237 MW). Switched to NTSyCS EDAC recovery.',
    },
    {
      idx: 6,
      tool: 'compare_results("c1_battery_norte_grande" vs "c3_uprate_l2")',
      badge: '16/16 checks',
      status: 'done',
      detail:
        'C3 (L2 uprate) cuts normal-day curtailment by 993 MWh but gives 0 MWh crisis relief. C1 (North BESS) cuts curtailment by 631.6 MWh AND saves 391.9 MWh (~98k households) during the 18:00 outage.',
    },
    {
      idx: 7,
      tool: 'generate_operator_report(recommend="c1_battery_norte_grande")',
      badge: 'DS 32/2026 Ready',
      status: 'done',
      detail:
        'Recommended C1 North Battery (150 MW / 600 MWh at n_norte_grande) as the only resilience-compliant intervention. Waiting for human operator sign-off.',
    },
  ];

  const displayedValidation = showInfeasibleProof ? VALIDATION_INFEASIBLE : VALIDATION_CANDIDATE;

  return (
    <div className="fixed right-3 top-3 bottom-3 z-30 w-[412px] flex flex-col pointer-events-none">
      <GlassContainer className="pointer-events-auto flex h-full flex-col overflow-hidden">
        {/* Top Header */}
        <div className="border-b border-neutral-800 px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-emerald-500/20 text-emerald-400 ring-1 ring-emerald-500/40">
              <Bot className="h-4.5 w-4.5" />
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <h2 className="font-poppins text-sm font-semibold text-white">
                  Gemini 4 Argon Copilot
                </h2>
                <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 font-mono text-[9.5px] font-semibold text-emerald-300">
                  HiGHS 1.15.1
                </span>
              </div>
              <p className="text-[11px] text-neutral-400">
                Autonomous Dispatch Loop & Physics Validator
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={runLiveInvestigationReplay}
              disabled={isRunningLoop}
              className="inline-flex items-center gap-1 rounded-lg bg-emerald-500 px-2.5 py-1 text-[11px] font-semibold text-neutral-950 shadow hover:bg-emerald-400 disabled:opacity-50 transition-colors"
              title="Run autonomous Gemini 4 Argon investigation loop"
            >
              {isRunningLoop ? (
                <RefreshCw className="h-3 w-3 animate-spin" />
              ) : (
                <Play className="h-3 w-3 fill-current" />
              )}
              <span>{isRunningLoop ? 'Solving...' : 'Run AI Loop'}</span>
            </button>
            <button
              type="button"
              onClick={onClose}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-neutral-400 hover:bg-neutral-800 hover:text-white"
              title="Collapse Copilot Drawer"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="grid grid-cols-3 border-b border-neutral-800 bg-neutral-950/60 p-1 text-xs font-medium">
          <button
            type="button"
            onClick={() => setActiveTab('trace')}
            className={`flex items-center justify-center gap-1.5 rounded-lg py-1.5 transition-colors ${
              activeTab === 'trace'
                ? 'bg-neutral-800 text-white shadow'
                : 'text-neutral-400 hover:text-neutral-200'
            }`}
          >
            <Terminal className="h-3.5 w-3.5 text-emerald-400" />
            <span>AI Tool Trace</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('validator')}
            className={`flex items-center justify-center gap-1.5 rounded-lg py-1.5 transition-colors ${
              activeTab === 'validator'
                ? 'bg-neutral-800 text-white shadow'
                : 'text-neutral-400 hover:text-neutral-200'
            }`}
          >
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
            <span>16/16 Checks</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('legal')}
            className={`flex items-center justify-center gap-1.5 rounded-lg py-1.5 transition-colors ${
              activeTab === 'legal'
                ? 'bg-neutral-800 text-white shadow'
                : 'text-neutral-400 hover:text-neutral-200'
            }`}
          >
            <Scale className="h-3.5 w-3.5 text-sky-400" />
            <span>Chile Legal</span>
          </button>
        </div>

        {/* Tab Content Area */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {activeTab === 'trace' && (
            <>
              {/* Executive Decision Card */}
              <div className="rounded-xl border border-emerald-500/40 bg-emerald-950/30 p-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-300">
                    <Sparkles className="h-3.5 w-3.5" />
                    Verified AI Recommendation
                  </span>
                  <span className="font-mono text-[10px] text-emerald-400">
                    residual: 3.5e-7 MW
                  </span>
                </div>
                <p className="text-xs text-neutral-200 leading-relaxed">
                  Deploy <strong>Candidate C1 (150 MW / 600 MWh BESS at Norte Grande)</strong>. It
                  captures <strong className="text-white">631.6 MWh</strong> of curtailed solar
                  upstream of <code className="text-amber-300">L2</code> and is the{' '}
                  <strong className="text-emerald-300">only candidate</strong> that mitigates both
                  midday congestion and the 18:00 <code className="text-red-300">gas_centro</code>{' '}
                  crisis (<strong className="text-white">−391.9 MWh blackout · ~98k households</strong>
                  ).
                </p>
                <div className="mt-2.5 flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => {
                      onSelectCandidate('c1_battery_norte_grande');
                      onSelectOperationMode('normal');
                    }}
                    className={`flex-1 rounded-lg px-2 py-1 text-[11px] font-medium transition-colors ${
                      candidateId === 'c1_battery_norte_grande' && operationMode === 'normal'
                        ? 'bg-emerald-500 text-neutral-950 font-semibold'
                        : 'bg-neutral-800 text-neutral-200 hover:bg-neutral-700'
                    }`}
                  >
                    Inspect C1 Normal Day
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      onSelectCandidate('c1_battery_norte_grande');
                      onSelectOperationMode('sudden_outage');
                    }}
                    className={`flex-1 rounded-lg px-2 py-1 text-[11px] font-medium transition-colors ${
                      candidateId === 'c1_battery_norte_grande' &&
                      operationMode === 'sudden_outage'
                        ? 'bg-red-500 text-white font-semibold'
                        : 'bg-neutral-800 text-neutral-200 hover:bg-neutral-700'
                    }`}
                  >
                    ⚡ Inspect C1 in 18:00 Crisis
                  </button>
                </div>
              </div>

              {/* Step-by-Step Autonomous Tool Trace */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-[11px] text-neutral-400">
                  <span className="font-semibold uppercase tracking-wider">
                    Agent Tool Call Trajectory
                  </span>
                  <span className="font-mono">7 / 7 Verified</span>
                </div>

                {toolTraceSteps.slice(0, activeStepIdx).map((step) => {
                  const isRejected = step.status === 'rejected';
                  const isSelfCorrected = step.status === 'self_corrected';

                  return (
                    <div
                      key={step.idx}
                      className={`rounded-xl border p-2.5 transition-all ${
                        isRejected
                          ? 'border-amber-500/40 bg-amber-950/20'
                          : isSelfCorrected
                          ? 'border-red-500/40 bg-red-950/20'
                          : 'border-neutral-800 bg-neutral-900/75'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <div className="flex items-center gap-1.5 min-w-0">
                          {isRejected || isSelfCorrected ? (
                            <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                          ) : (
                            <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
                          )}
                          <code className="truncate font-mono text-[11px] font-semibold text-neutral-100">
                            {step.tool}
                          </code>
                        </div>
                        <span
                          className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-[9.5px] font-semibold ${
                            isRejected
                              ? 'bg-amber-500/20 text-amber-300'
                              : isSelfCorrected
                              ? 'bg-red-500/25 text-red-300'
                              : 'bg-neutral-800 text-emerald-400'
                          }`}
                        >
                          {step.badge}
                        </span>
                      </div>
                      <p className="text-[11px] leading-snug text-neutral-300">{step.detail}</p>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {activeTab === 'validator' && (
            <div className="space-y-3">
              {/* Toggle between Optimal Candidate Validation and Infeasible Crisis Rejection */}
              <div className="flex items-center justify-between rounded-xl border border-neutral-800 bg-neutral-950/80 p-2">
                <span className="text-xs font-medium text-neutral-300">Validator Mode:</span>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setShowInfeasibleProof(false)}
                    className={`rounded-lg px-2 py-1 text-[11px] font-medium ${
                      !showInfeasibleProof
                        ? 'bg-emerald-500 text-neutral-950 font-semibold'
                        : 'bg-neutral-800 text-neutral-400'
                    }`}
                  >
                    Optimal (16/16 Pass)
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowInfeasibleProof(true)}
                    className={`rounded-lg px-2 py-1 text-[11px] font-medium ${
                      showInfeasibleProof
                        ? 'bg-red-500 text-white font-semibold'
                        : 'bg-neutral-800 text-neutral-400'
                    }`}
                  >
                    Strict Outage (Rejected)
                  </button>
                </div>
              </div>

              {/* Validation Status Summary Banner */}
              <div
                className={`rounded-xl border p-3 ${
                  displayedValidation.passed
                    ? 'border-emerald-500/40 bg-emerald-950/25'
                    : 'border-red-500/50 bg-red-950/30'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {displayedValidation.passed ? (
                      <ShieldCheck className="h-5 w-5 text-emerald-400" />
                    ) : (
                      <XCircle className="h-5 w-5 text-red-400" />
                    )}
                    <div>
                      <h3 className="font-poppins text-xs font-semibold text-white">
                        {displayedValidation.passed
                          ? 'Independent Physics Validator: PASSED'
                          : 'Independent Physics Validator: REJECTED (INFEASIBLE)'}
                      </h3>
                      <p className="font-mono text-[10.5px] text-neutral-300">
                        Checks: {displayedValidation.checks_run.length} · Violations:{' '}
                        {displayedValidation.violation_count} · Max Residual:{' '}
                        {displayedValidation.max_residual_mw.toExponential(2)} MW
                      </p>
                    </div>
                  </div>
                </div>

                {!displayedValidation.passed && displayedValidation.violations[0] && (
                  <div className="mt-2 rounded-lg bg-red-950/80 border border-red-500/40 p-2 font-mono text-[10px] text-red-200 leading-relaxed">
                    {displayedValidation.violations[0].detail}
                  </div>
                )}
              </div>

              {/* Grid of all 16 Independent Physical Conservation Checks */}
              <div className="space-y-1.5">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-neutral-400">
                  16 Physical & Mathematical Constraints (DS N° 32/2026)
                </span>
                <div className="grid grid-cols-2 gap-1.5">
                  {VALIDATION_CANDIDATE.checks_run.map((checkName) => {
                    const isFailed =
                      !displayedValidation.passed && checkName === 'status';
                    return (
                      <div
                        key={checkName}
                        className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 font-mono text-[10.5px] ${
                          isFailed
                            ? 'border-red-500/50 bg-red-950/40 text-red-300'
                            : 'border-neutral-800 bg-neutral-900/80 text-neutral-200'
                        }`}
                      >
                        {isFailed ? (
                          <XCircle className="h-3.5 w-3.5 shrink-0 text-red-400" />
                        ) : (
                          <Check className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
                        )}
                        <span className="truncate">{checkName}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'legal' && (
            <div className="space-y-2.5">
              <div className="rounded-xl border border-sky-500/30 bg-sky-950/25 p-3">
                <h3 className="font-poppins text-xs font-semibold text-sky-300 mb-1">
                  Chilean Regulatory Compliance Architecture
                </h3>
                <p className="text-[11px] text-neutral-300 leading-snug">
                  Every GridPilot simulation, validator check, and operator report is anchored to
                  Chile&apos;s vigente electricity legislation:
                </p>
              </div>

              {[
                {
                  code: 'LGSE · DFL N° 4/2006 (Art. 72°-1)',
                  title: 'Coordinador Eléctrico Nacional (CEN) Mandate',
                  desc: 'Requires preserving global grid security alongside minimum-cost economic dispatch across the SEN.',
                },
                {
                  code: 'Supreme Decree N° 32/2026 (Art. 117 bis)',
                  title: 'Audited SCED & Mathematical Residual Verification',
                  desc: 'Mandates independently verifiable linear programming (HiGHS 1.15.1) with nodal balance residuals < 1e-6 MW.',
                },
                {
                  code: 'NTSyCS (CNE Technical Standard)',
                  title: 'N-1 Security & Emergency Load Shedding (EDAC)',
                  desc: 'Governs the 18:00 gas_centro (600 MW) sudden outage simulation and emergency load-shedding recovery.',
                },
                {
                  code: 'Law N° 21.505 (Storage & Electromobility)',
                  title: 'Sistemas de Almacenamiento de Energía (SAE)',
                  desc: 'Legal basis for Candidate C1 (150 MW / 600 MWh BESS at Norte Grande) for curtailment absorption & peak capacity.',
                },
                {
                  code: 'NTD / SEC Residential Equivalence',
                  title: 'Social Impact Metric (~1,000 Households / MW)',
                  desc: 'Translates C1’s −391.9 MWh evening blackout reduction into ~97,975 household-hours of protected electricity service.',
                },
              ].map((law) => (
                <div
                  key={law.code}
                  className="rounded-xl border border-neutral-800 bg-neutral-900/80 p-2.5"
                >
                  <div className="font-mono text-[10.5px] font-semibold text-emerald-400">
                    {law.code}
                  </div>
                  <div className="font-poppins text-xs font-semibold text-white mt-0.5">
                    {law.title}
                  </div>
                  <p className="text-[11px] text-neutral-400 mt-0.5 leading-snug">{law.desc}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Bottom Sticky Human-in-the-Loop Operator Decision Bar */}
        <div className="border-t border-neutral-800 bg-neutral-950/90 px-4 py-3 space-y-2">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-neutral-400">Human-in-the-Loop Sign-Off:</span>
            <span
              className={`font-mono font-semibold ${
                approvalStatus === 'approved'
                  ? 'text-emerald-400'
                  : approvalStatus === 'rejected'
                  ? 'text-red-400'
                  : 'text-amber-300'
              }`}
            >
              {approvalStatus === 'approved'
                ? '✓ PLAN APPROVED (RIO LOGGED)'
                : approvalStatus === 'rejected'
                ? '✕ PLAN REJECTED'
                : 'AWAITING CEN OPERATOR'}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setApprovalStatus('approved')}
              className={`flex-1 flex items-center justify-center gap-1.5 rounded-xl py-2 text-xs font-semibold transition-all ${
                approvalStatus === 'approved'
                  ? 'bg-emerald-500 text-neutral-950 ring-2 ring-emerald-300'
                  : 'bg-[#2AA364] text-neutral-950 hover:bg-emerald-400'
              }`}
            >
              <CheckCircle2 className="h-4 w-4" />
              <span>Approve Simulated Plan</span>
            </button>

            <button
              type="button"
              onClick={() => setApprovalStatus('rejected')}
              className="rounded-xl border border-neutral-700 bg-neutral-800 px-3 py-2 text-xs font-medium text-neutral-300 hover:bg-red-950/60 hover:border-red-500/50 hover:text-red-300 transition-colors"
            >
              Reject
            </button>

            <button
              type="button"
              onClick={onExportRioReport}
              className="flex items-center justify-center rounded-xl border border-neutral-700 bg-neutral-800 p-2 text-neutral-200 hover:bg-neutral-700 transition-colors"
              title="Download Audited RIO JSON Report (DS N° 32/2026)"
            >
              <FileJson className="h-4 w-4 text-emerald-400" />
            </button>
          </div>
        </div>
      </GlassContainer>
    </div>
  );
};
