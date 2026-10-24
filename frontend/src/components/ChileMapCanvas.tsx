import React, { useState } from 'react';
import {
  Plus,
  Minus,
  RotateCcw,
  Sun,
  Wind,
  BatteryCharging,
  Activity,
  AlertOctagon,
  Sparkles,
  CheckCircle2,
  Layers,
} from 'lucide-react';
import {
  CandidateId,
  LineId,
  NodeId,
  OperationMode,
  SolverSolution,
} from '../types/grid';
import {
  CANDIDATE_OPTIONS,
  computeZoneSnapshot,
  NODES,
} from '../data/scenarioData';
import { GlassContainer } from './GlassContainer';

interface ChileMapCanvasProps {
  baselineSolution: SolverSolution;
  activeSolution: SolverSolution;
  step96: number;
  selectedZone: NodeId | 'all';
  onSelectZone: (zone: NodeId | 'all') => void;
  candidateId: CandidateId;
  onSelectCandidate: (id: CandidateId) => void;
  operationMode: OperationMode;
  onSelectOperationMode: (mode: OperationMode) => void;
  copilotOpen: boolean;
}

interface ZoneGeometry {
  id: NodeId;
  path: string;
  hubX: number;
  hubY: number;
  labelX: number;
  labelY: number;
}

// High-precision stylized SVG geography of Chile's 5 SEN Macro-Zones
// ViewBox: 0 0 900 980 (Centered so Chile's long coastline and Andes border sit cleanly between LeftPanel and RightDrawer)
const CHILE_ZONE_GEOMETRIES: ZoneGeometry[] = [
  {
    id: 'n_norte_grande',
    // Arica, Tarapacá, Antofagasta (Atacama Desert)
    path: 'M 445 65 L 495 65 L 518 115 L 535 175 L 525 245 L 442 245 L 436 180 L 440 115 Z',
    hubX: 482,
    hubY: 162,
    labelX: 548,
    labelY: 155,
  },
  {
    id: 'n_norte_chico',
    // Atacama South & Coquimbo (Serena / Copiapó)
    path: 'M 442 245 L 525 245 L 512 325 L 502 405 L 430 405 L 434 325 Z',
    hubX: 468,
    hubY: 328,
    labelX: 528,
    labelY: 325,
  },
  {
    id: 'n_centro',
    // Valparaíso, RM Santiago, O'Higgins
    path: 'M 430 405 L 502 405 L 496 480 L 488 545 L 418 545 L 424 475 Z',
    hubX: 456,
    hubY: 476,
    labelX: 514,
    labelY: 472,
  },
  {
    id: 'n_centro_sur',
    // Maule, Ñuble, Biobío (Concepción)
    path: 'M 418 545 L 488 545 L 482 625 L 476 695 L 405 695 L 412 620 Z',
    hubX: 446,
    hubY: 622,
    labelX: 502,
    labelY: 620,
  },
  {
    id: 'n_sur',
    // Araucanía, Los Ríos, Los Lagos (Puerto Montt & Chiloé)
    path: 'M 405 695 L 476 695 L 472 785 L 464 875 L 392 875 L 398 785 Z',
    hubX: 434,
    hubY: 785,
    labelX: 492,
    labelY: 782,
  },
];

const CORRIDOR_META: Record<
  LineId,
  {
    id: LineId;
    name: string;
    voltageLabel: string;
    fromZone: NodeId;
    toZone: NodeId;
    x1: number;
    y1: number;
    x2: number;
    y2: number;
    midX: number;
    midY: number;
  }
> = {
  L1: {
    id: 'L1',
    name: 'L1 · Nueva Cardones – Polpaico Norte',
    voltageLabel: '2×500 kV',
    fromZone: 'n_norte_grande',
    toZone: 'n_norte_chico',
    x1: 482,
    y1: 162,
    x2: 468,
    y2: 328,
    midX: 475,
    midY: 245,
  },
  L2: {
    id: 'L2',
    name: 'L2 · Norte Chico → Centro (Polpaico)',
    voltageLabel: '2×500 kV Trunk',
    fromZone: 'n_norte_chico',
    toZone: 'n_centro',
    x1: 468,
    y1: 328,
    x2: 456,
    y2: 476,
    midX: 462,
    midY: 405,
  },
  L3: {
    id: 'L3',
    name: 'L3 · Alto Jahuel – Charrúa',
    voltageLabel: '2×500 kV',
    fromZone: 'n_centro',
    toZone: 'n_centro_sur',
    x1: 456,
    y1: 476,
    x2: 446,
    y2: 622,
    midX: 451,
    midY: 545,
  },
  L4: {
    id: 'L4',
    name: 'L4 · Charrúa – Pichirropulli (Sur)',
    voltageLabel: '2×220 kV',
    fromZone: 'n_centro_sur',
    toZone: 'n_sur',
    x1: 446,
    y1: 622,
    x2: 434,
    y2: 785,
    midX: 440,
    midY: 695,
  },
};

export const ChileMapCanvas: React.FC<ChileMapCanvasProps> = ({
  baselineSolution,
  activeSolution,
  step96,
  selectedZone,
  onSelectZone,
  candidateId,
  onSelectCandidate,
  operationMode,
  onSelectOperationMode,
  copilotOpen,
}) => {
  const [zoom, setZoom] = useState<number>(1);
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [hoveredLine, setHoveredLine] = useState<LineId | null>(null);
  const [hoveredZone, setHoveredZone] = useState<NodeId | null>(null);
  const [showCorridors, setShowCorridors] = useState(true);
  const [showAssets, setShowAssets] = useState(true);

  const hourIndex = Math.min(23, Math.floor(step96 / 4));
  const isCrisisHour = operationMode === 'sudden_outage' && hourIndex >= 18 && hourIndex <= 21;

  // Compute snapshots for each of the 5 zones
  const zoneSnapshots = NODES.reduce(
    (acc, node) => {
      acc[node.id] = computeZoneSnapshot(activeSolution, step96, node.id);
      return acc;
    },
    {} as Record<NodeId, ReturnType<typeof computeZoneSnapshot>>
  );

  const baselineNational = computeZoneSnapshot(baselineSolution, step96, 'all');
  const activeNational = computeZoneSnapshot(activeSolution, step96, 'all');

  const handleMouseDown = (e: React.MouseEvent<SVGSVGElement>) => {
    if ((e.target as HTMLElement).closest('[data-interactive="true"]')) return;
    setIsDragging(true);
    setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
  };

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!isDragging) return;
    setPan({
      x: Math.max(-280, Math.min(280, e.clientX - dragStart.x)),
      y: Math.max(-220, Math.min(220, e.clientY - dragStart.y)),
    });
  };

  const handleMouseUp = () => setIsDragging(false);

  const resetView = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#262626] select-none">
      {/* Top-Center Floating Scenario & Candidate Switcher Bar (Instant 1-Glance Control) */}
      <div
        className={`fixed top-3 z-30 flex flex-wrap items-center gap-2 transition-all duration-300 ${
          copilotOpen
            ? 'left-[505px] right-[430px] justify-center'
            : 'left-[505px] right-16 justify-between'
        }`}
      >
        <GlassContainer className="flex items-center gap-1.5 px-2.5 py-1.5">
          {/* Regime Selector: Normal SCED vs 18:00 Sudden Outage */}
          <div className="flex items-center rounded-xl bg-neutral-950/90 p-0.5 border border-neutral-800">
            <button
              type="button"
              onClick={() => onSelectOperationMode('normal')}
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition-all ${
                operationMode === 'normal'
                  ? 'bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/50 shadow'
                  : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              <Sun className="h-3.5 w-3.5 text-[#FFC700]" />
              <span>Normal SCED Day</span>
            </button>
            <button
              type="button"
              onClick={() => onSelectOperationMode('sudden_outage')}
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition-all ${
                operationMode === 'sudden_outage'
                  ? 'bg-red-500/25 text-red-300 ring-1 ring-red-500/60 shadow'
                  : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              <AlertOctagon className="h-3.5 w-3.5 text-red-400" />
              <span>⚡ 18:00 Crisis (gas_centro 600 MW Trip)</span>
            </button>
          </div>

          <div className="h-4 w-px bg-neutral-700/70 mx-0.5" />

          {/* Candidate Intervention Selector */}
          <div className="flex items-center gap-1">
            {CANDIDATE_OPTIONS.map((opt) => {
              const isSelected = candidateId === opt.candidate_id;
              const isRecommended = opt.candidate_id === 'c1_battery_norte_grande';
              return (
                <button
                  key={opt.candidate_id}
                  type="button"
                  onClick={() => onSelectCandidate(opt.candidate_id)}
                  className={`flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium transition-all ${
                    isSelected
                      ? isRecommended
                        ? 'bg-[#2AA364] text-neutral-950 font-semibold shadow-md shadow-emerald-950/50'
                        : 'bg-neutral-100 text-neutral-950 font-semibold'
                      : 'bg-neutral-800/70 text-neutral-300 hover:bg-neutral-700/70'
                  }`}
                  title={opt.description}
                >
                  {isRecommended && <Sparkles className="h-3 w-3 shrink-0" />}
                  <span>{opt.shortTitle}</span>
                </button>
              );
            })}
          </div>
        </GlassContainer>

        {/* National / Zone Reset Pill */}
        {selectedZone !== 'all' && (
          <GlassContainer className="px-3 py-1.5">
            <button
              type="button"
              onClick={() => onSelectZone('all')}
              className="flex items-center gap-1.5 text-xs font-medium text-emerald-400 hover:text-emerald-300"
            >
              <Layers className="h-3.5 w-3.5" />
              <span>View All 5 SEN Zones (National)</span>
            </button>
          </GlassContainer>
        )}
      </div>

      {/* Interactive SVG Map Canvas */}
      <svg
        viewBox="0 0 900 980"
        className={`h-full w-full ${isDragging ? 'cursor-grabbing' : 'cursor-grab'}`}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <defs>
          {/* Subtle Ocean Grid Pattern */}
          <pattern id="em-grid" width="60" height="60" patternUnits="userSpaceOnUse">
            <path
              d="M 60 0 L 0 0 0 60"
              fill="none"
              stroke="rgba(255,255,255,0.03)"
              strokeWidth="1"
            />
          </pattern>

          {/* Diagonal Hatch Pattern for Curtailed Solar Overload */}
          <pattern
            id="curtailment-hatch"
            width="10"
            height="10"
            patternTransform="rotate(45 0 0)"
            patternUnits="userSpaceOnUse"
          >
            <line x1="0" y1="0" x2="0" y2="10" stroke="rgba(0,0,0,0.28)" strokeWidth="3" />
          </pattern>

          {/* Glow Filter for Active Corridor / Node */}
          <filter id="glow-emerald" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
          <filter id="glow-red" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* Ocean Background */}
        <rect width="900" height="980" fill="#262626" onClick={() => onSelectZone('all')} />
        <rect width="900" height="980" fill="url(#em-grid)" onClick={() => onSelectZone('all')} />

        <g
          transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}
          style={{ transformOrigin: '470px 480px', transition: isDragging ? 'none' : 'transform 0.2s ease-out' }}
        >
          {/* Pacific Ocean Coordinate Labels */}
          <g className="pointer-events-none opacity-30">
            <text x="295" y="165" fill="#9ca3af" fontSize="10" fontFamily="JetBrains Mono">
              23.6°S · Tropic of Capricorn
            </text>
            <line
              x1="290"
              y1="172"
              x2="435"
              y2="172"
              stroke="#9ca3af"
              strokeDasharray="3 3"
              strokeWidth="0.7"
            />
            <text x="295" y="478" fill="#9ca3af" fontSize="10" fontFamily="JetBrains Mono">
              33.4°S · Santiago RM
            </text>
            <line
              x1="290"
              y1="484"
              x2="418"
              y2="484"
              stroke="#9ca3af"
              strokeDasharray="3 3"
              strokeWidth="0.7"
            />
            <text x="295" y="785" fill="#9ca3af" fontSize="10" fontFamily="JetBrains Mono">
              41.5°S · Puerto Montt
            </text>
            <line
              x1="290"
              y1="791"
              x2="392"
              y2="791"
              stroke="#9ca3af"
              strokeDasharray="3 3"
              strokeWidth="0.7"
            />
            <text
              x="315"
              y="390"
              fill="#6b7280"
              fontSize="12"
              fontWeight="600"
              letterSpacing="0.2em"
            >
              PACIFIC OCEAN
            </text>
          </g>

          {/* Neighboring South America Land (Electricity Maps #3A4046 muted land fill) */}
          <g className="pointer-events-none">
            {/* Peru / Bolivia North-East Context */}
            <path
              d="M 445 65 L 430 15 L 680 15 L 680 235 L 535 175 L 518 115 L 495 65 Z"
              fill="#33383E"
              stroke="#4B525A"
              strokeWidth="1"
            />
            <text x="560" y="95" fill="#6E7781" fontSize="11" fontWeight="600" letterSpacing="0.12em">
              BOLIVIA
            </text>

            {/* Argentina East Context */}
            <path
              d="M 535 175 L 680 235 L 680 945 L 455 945 L 464 875 L 472 785 L 476 695 L 482 625 L 488 545 L 496 480 L 502 405 L 512 325 L 525 245 Z"
              fill="#363C42"
              stroke="#4B525A"
              strokeWidth="1"
            />
            <text x="565" y="520" fill="#6E7781" fontSize="12" fontWeight="600" letterSpacing="0.16em">
              ARGENTINA
            </text>

            {/* Southern Patagonia Continuation */}
            <path
              d="M 392 875 L 464 875 L 455 945 L 385 945 Z"
              fill="#33383E"
              stroke="#4B525A"
              strokeWidth="1"
            />
          </g>

          {/* 5 Interactive Chilean SEN Zone Polygons */}
          {CHILE_ZONE_GEOMETRIES.map((geo) => {
            const snap = zoneSnapshots[geo.id];
            const nodeMeta = NODES.find((n) => n.id === geo.id)!;
            const isSelected = selectedZone === geo.id;
            const isHovered = hoveredZone === geo.id;
            const hasUnserved = snap.unservedMw > 1;
            const hasCurtailment = snap.curtailedMw > 15;

            return (
              <g
                key={geo.id}
                data-interactive="true"
                className="cursor-pointer transition-opacity"
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectZone(selectedZone === geo.id ? 'all' : geo.id);
                }}
                onMouseEnter={() => setHoveredZone(geo.id)}
                onMouseLeave={() => setHoveredZone(null)}
              >
                {/* Zone Polygon colored by Electricity Maps intensity scale */}
                <path
                  d={geo.path}
                  fill={snap.stressColor}
                  fillOpacity={
                    selectedZone === 'all' || isSelected ? (isHovered ? 0.96 : 0.88) : 0.42
                  }
                  stroke={
                    hasUnserved
                      ? '#FCA5A5'
                      : isSelected
                      ? '#FFFFFF'
                      : isHovered
                      ? '#E5E7EB'
                      : '#262626'
                  }
                  strokeWidth={isSelected ? 2.8 : isHovered ? 2 : 1.4}
                  className="transition-colors duration-300"
                />

                {/* Diagonal Hatch Overlay when Solar/Wind is Curtailed in this Zone */}
                {hasCurtailment && (
                  <path
                    d={geo.path}
                    fill="url(#curtailment-hatch)"
                    pointerEvents="none"
                  />
                )}

                {/* Zone Substation Hub Circle */}
                <circle
                  cx={geo.hubX}
                  cy={geo.hubY}
                  r={isSelected ? 8 : 6}
                  fill="#171717"
                  stroke={hasUnserved ? '#EF4444' : '#FFFFFF'}
                  strokeWidth={2.2}
                />
                <circle
                  cx={geo.hubX}
                  cy={geo.hubY}
                  r={3}
                  fill={
                    hasUnserved
                      ? '#EF4444'
                      : snap.curtailedMw > 10
                      ? '#FFC700'
                      : '#2AA364'
                  }
                />

                {/* Right-hand Zone Callout Card on Map */}
                {showAssets && (
                  <g transform={`translate(${geo.labelX}, ${geo.labelY - 22})`}>
                    {/* Connector line from hub to callout */}
                    <line
                      x1={geo.hubX - geo.labelX + 8}
                      y1={geo.hubY - (geo.labelY - 22)}
                      x2={0}
                      y2={20}
                      stroke={isSelected ? '#10B981' : 'rgba(255,255,255,0.28)'}
                      strokeWidth={1.2}
                      strokeDasharray={isSelected ? 'none' : '2 2'}
                    />
                    <rect
                      x={0}
                      y={0}
                      width={198}
                      height={hasUnserved || hasCurtailment ? 56 : 44}
                      rx={9}
                      fill="rgba(23, 23, 23, 0.90)"
                      stroke={
                        hasUnserved
                          ? '#EF4444'
                          : isSelected
                          ? '#10B981'
                          : 'rgba(115, 115, 115, 0.5)'
                      }
                      strokeWidth={isSelected || hasUnserved ? 1.5 : 1}
                    />
                    {/* Zone Name & Region Code */}
                    <text
                      x={10}
                      y={16}
                      fill="#F5F5F5"
                      fontSize="11.5"
                      fontWeight="600"
                      fontFamily="Poppins"
                    >
                      {nodeMeta.shortName}
                    </text>
                    <text
                      x={188}
                      y={16}
                      textAnchor="end"
                      fill="#9CA3AF"
                      fontSize="10"
                      fontFamily="JetBrains Mono"
                    >
                      {Math.round(snap.renewableSharePct)}% REN
                    </text>

                    {/* Generation vs Demand Readout */}
                    <text
                      x={10}
                      y={32}
                      fill="#D4D4D8"
                      fontSize="10.5"
                      fontFamily="JetBrains Mono"
                    >
                      Gen {Math.round(snap.totalGenerationMw)} MW · Load {Math.round(snap.demandMw)} MW
                    </text>

                    {/* Alert line if Curtailed or Unserved */}
                    {hasUnserved ? (
                      <text
                        x={10}
                        y={47}
                        fill="#F87171"
                        fontSize="10"
                        fontWeight="700"
                        fontFamily="JetBrains Mono"
                      >
                        ⚠ EDAC BLACKOUT: {Math.round(snap.unservedMw)} MW
                      </text>
                    ) : hasCurtailment ? (
                      <text
                        x={10}
                        y={47}
                        fill="#FBBF24"
                        fontSize="10"
                        fontWeight="600"
                        fontFamily="JetBrains Mono"
                      >
                        ☀ Curtailed Solar: {Math.round(snap.curtailedMw)} MW
                      </text>
                    ) : null}
                  </g>
                )}

                {/* Special Asset Pill on Left Side of Chile (Ocean Side) */}
                {showAssets && geo.id === 'n_norte_grande' && candidateId === 'c1_battery_norte_grande' && (
                  <g transform={`translate(${geo.hubX - 225}, ${geo.hubY - 22})`}>
                    <line
                      x1={190}
                      y1={22}
                      x2={217}
                      y2={22}
                      stroke="#1DA484"
                      strokeWidth="1.5"
                    />
                    <rect
                      x={0}
                      y={0}
                      width={190}
                      height={44}
                      rx={10}
                      fill="rgba(6, 78, 59, 0.92)"
                      stroke="#10B981"
                      strokeWidth="1.5"
                      filter="url(#glow-emerald)"
                    />
                    <text x={10} y={17} fill="#6EE7B7" fontSize="10.5" fontWeight="700" fontFamily="Poppins">
                      ★ C1 NORTH BESS (150 MW)
                    </text>
                    <text x={10} y={33} fill="#ECFDF5" fontSize="10" fontFamily="JetBrains Mono">
                      {snap.batteryChargeMw > 1
                        ? `⚡ Charging +${Math.round(snap.batteryChargeMw)} MW`
                        : snap.batteryDischargeMw > 1
                        ? `🔋 Discharging ${Math.round(snap.batteryDischargeMw)} MW`
                        : '🔋 Standby'}{' '}
                      · SOC {Math.round(snap.batterySocMwh)} MWh
                    </text>
                  </g>
                )}

                {/* Sudden Outage Badge at Centro when Crisis is Active */}
                {showAssets && geo.id === 'n_centro' && isCrisisHour && (
                  <g transform={`translate(${geo.hubX - 232}, ${geo.hubY - 20})`}>
                    <line
                      x1={195}
                      y1={22}
                      x2={224}
                      y2={22}
                      stroke="#EF4444"
                      strokeWidth="1.8"
                    />
                    <rect
                      x={0}
                      y={0}
                      width={195}
                      height={44}
                      rx={10}
                      fill="rgba(127, 29, 29, 0.95)"
                      stroke="#F87171"
                      strokeWidth="1.8"
                      filter="url(#glow-red)"
                    />
                    <text x={10} y={17} fill="#FCA5A5" fontSize="10.5" fontWeight="700" fontFamily="Poppins">
                      ⚡ GAS_CENTRO OUTAGE
                    </text>
                    <text x={10} y={33} fill="#FEE2E2" fontSize="10" fontFamily="JetBrains Mono">
                      −600 MW Thermal Trip (Hr 18–21)
                    </text>
                  </g>
                )}
              </g>
            );
          })}

          {/* Electricity Maps Animated Exchange Corridors (L1..L4) */}
          {showCorridors &&
            (Object.keys(CORRIDOR_META) as LineId[]).map((lineId) => {
              const meta = CORRIDOR_META[lineId];
              const lineSnap = activeNational.lineFlows[lineId];
              const baseLineSnap = baselineNational.lineFlows[lineId];
              if (!lineSnap) return null;

              const isBinding = lineSnap.isBinding;
              const isPositive = lineSnap.flowMw >= 0; // North -> South
              const absFlow = Math.abs(lineSnap.flowMw);
              const strokeColor = isBinding
                ? '#F59E0B'
                : candidateId === 'c3_uprate_l2' && lineId === 'L2'
                ? '#10B981'
                : '#E5E7EB';

              return (
                <g
                  key={lineId}
                  data-interactive="true"
                  className="cursor-pointer"
                  onMouseEnter={() => setHoveredLine(lineId)}
                  onMouseLeave={() => setHoveredLine(null)}
                >
                  {/* Corridor Base Track */}
                  <line
                    x1={meta.x1}
                    y1={meta.y1}
                    x2={meta.x2}
                    y2={meta.y2}
                    stroke="#171717"
                    strokeWidth={7}
                    strokeLinecap="round"
                  />

                  {/* Animated Electricity Maps Directional Dash Stream */}
                  <line
                    x1={isPositive ? meta.x1 : meta.x2}
                    y1={isPositive ? meta.y1 : meta.y2}
                    x2={isPositive ? meta.x2 : meta.x1}
                    y2={isPositive ? meta.y2 : meta.y1}
                    stroke={strokeColor}
                    strokeWidth={3.5}
                    strokeDasharray="6 6"
                    className={
                      absFlow > 250 ? 'animate-corridor-flow-fast' : 'animate-corridor-flow'
                    }
                  />

                  {/* Electricity Maps Capsule Pill on Zone Border */}
                  <g transform={`translate(${meta.midX - 52}, ${meta.midY - 12})`}>
                    <rect
                      x={0}
                      y={0}
                      width={104}
                      height={24}
                      rx={12}
                      fill={isBinding ? '#78350F' : '#171717'}
                      stroke={
                        isBinding
                          ? '#F59E0B'
                          : hoveredLine === lineId
                          ? '#FFFFFF'
                          : '#525252'
                      }
                      strokeWidth={isBinding ? 1.8 : 1.2}
                    />
                    <text
                      x={52}
                      y={15.5}
                      textAnchor="middle"
                      fill={isBinding ? '#FDE68A' : '#F5F5F5'}
                      fontSize="10"
                      fontWeight="600"
                      fontFamily="JetBrains Mono"
                    >
                      {lineId} {isPositive ? '↓' : '↑'} {Math.round(absFlow)}/{Math.round(lineSnap.capacityMw)}
                    </text>
                  </g>

                  {/* Binding Bottleneck Callout Badge on Left Side for L2 */}
                  {isBinding && lineId === 'L2' && (
                    <g transform={`translate(${meta.midX - 222}, ${meta.midY - 14})`}>
                      <line
                        x1={162}
                        y1={14}
                        x2={170}
                        y2={14}
                        stroke="#F59E0B"
                        strokeWidth="1.5"
                      />
                      <rect
                        x={0}
                        y={0}
                        width={162}
                        height={28}
                        rx={8}
                        fill="rgba(120, 53, 15, 0.95)"
                        stroke="#F59E0B"
                        strokeWidth="1.5"
                      />
                      <text
                        x={81}
                        y={18}
                        textAnchor="middle"
                        fill="#FEF3C7"
                        fontSize="10"
                        fontWeight="700"
                        fontFamily="JetBrains Mono"
                      >
                        ⚠ L2 BINDING (400 MW MAX)
                      </text>
                    </g>
                  )}

                  {/* Hover ExchangeTooltip (Exact Electricity Maps ExchangeTooltip replica) */}
                  {hoveredLine === lineId && (
                    <g transform={`translate(${meta.midX - 245}, ${meta.midY - 45})`}>
                      <rect
                        x={0}
                        y={0}
                        width={225}
                        height={82}
                        rx={10}
                        fill="rgba(17, 17, 17, 0.96)"
                        stroke="#737373"
                        strokeWidth={1.2}
                      />
                      <text x={12} y={20} fill="#FFFFFF" fontSize="11" fontWeight="600" fontFamily="Poppins">
                        {meta.name}
                      </text>
                      <text x={12} y={38} fill="#D4D4D8" fontSize="10.5" fontFamily="JetBrains Mono">
                        Flow: {lineSnap.flowMw >= 0 ? 'N → S' : 'S → N'} {Math.abs(lineSnap.flowMw).toFixed(1)} MW ({Math.round(lineSnap.utilizationPct)}%)
                      </text>
                      <text x={12} y={54} fill="#A1A1AA" fontSize="10" fontFamily="JetBrains Mono">
                        Capacity: {lineSnap.capacityMw} MW ({meta.voltageLabel})
                      </text>
                      <text
                        x={12}
                        y={70}
                        fill={isBinding ? '#FBBF24' : '#34D399'}
                        fontSize="10"
                        fontWeight="600"
                        fontFamily="JetBrains Mono"
                      >
                        {candidateId !== 'baseline'
                          ? `Δ vs Base: ${(Math.abs(lineSnap.flowMw) - Math.abs(baseLineSnap.flowMw) >= 0 ? '+' : '') + (Math.abs(lineSnap.flowMw) - Math.abs(baseLineSnap.flowMw)).toFixed(1)} MW`
                          : isBinding
                          ? 'Status: 100% CONGESTED (8h/day)'
                          : 'Status: Within N-1 Thermal Limit'}
                      </text>
                    </g>
                  )}
                </g>
              );
            })}
        </g>
      </svg>

      {/* Top-Right Electricity Maps Layer & Zoom Controls */}
      <div
        className={`fixed top-16 z-30 flex flex-col gap-2 transition-all duration-300 ${
          copilotOpen ? 'right-[432px]' : 'right-4'
        }`}
      >
        <GlassContainer className="flex flex-col p-1">
          <button
            type="button"
            onClick={() => setZoom((z) => Math.min(1.6, Number((z + 0.15).toFixed(2))))}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-neutral-300 hover:bg-neutral-800 hover:text-white"
            title="Zoom In"
          >
            <Plus className="h-4 w-4" />
          </button>
          <div className="h-px w-full bg-neutral-800" />
          <button
            type="button"
            onClick={() => setZoom((z) => Math.max(0.75, Number((z - 0.15).toFixed(2))))}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-neutral-300 hover:bg-neutral-800 hover:text-white"
            title="Zoom Out"
          >
            <Minus className="h-4 w-4" />
          </button>
          <div className="h-px w-full bg-neutral-800" />
          <button
            type="button"
            onClick={resetView}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-neutral-300 hover:bg-neutral-800 hover:text-white"
            title="Reset Map View"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
        </GlassContainer>

        <GlassContainer className="flex flex-col p-1 gap-0.5">
          <button
            type="button"
            onClick={() => setShowCorridors((v) => !v)}
            className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${
              showCorridors
                ? 'bg-emerald-500/20 text-emerald-400'
                : 'text-neutral-500 hover:bg-neutral-800'
            }`}
            title="Toggle 500 kV Transmission Corridors (L1..L4)"
          >
            <Activity className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setShowAssets((v) => !v)}
            className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${
              showAssets
                ? 'bg-amber-500/20 text-amber-400'
                : 'text-neutral-500 hover:bg-neutral-800'
            }`}
            title="Toggle Zone Asset Readouts & BESS Callouts"
          >
            <BatteryCharging className="h-4 w-4" />
          </button>
        </GlassContainer>
      </div>

      {/* Bottom-Right Electricity Maps Horizontal Colorbar Legend */}
      <div
        className={`fixed bottom-3 z-30 transition-all duration-300 ${
          copilotOpen ? 'right-[432px]' : 'right-4'
        }`}
      >
        <GlassContainer className="px-3.5 py-2.5 min-w-[270px]">
          <div className="flex items-center justify-between text-[11px] font-medium text-neutral-300 mb-1.5">
            <span>Grid Dispatch & Curtailment Intensity</span>
            <span className="font-mono text-[10px] text-neutral-400">SEN Chile</span>
          </div>
          {/* Electricity Maps 5-stop gradient bar */}
          <div
            className="h-2.5 w-full rounded-full"
            style={{
              background:
                'linear-gradient(90deg, #2AA364 0%, #87B953 28%, #F5EB4D 55%, #9E4229 80%, #DC2626 100%)',
            }}
          />
          <div className="mt-1 flex justify-between text-[9.5px] font-mono text-neutral-400">
            <span>Clean Optimal</span>
            <span>Balanced</span>
            <span>L2 Congested</span>
            <span>Curtailed</span>
            <span className="text-red-400 font-semibold">EDAC Crisis</span>
          </div>
        </GlassContainer>
      </div>
    </div>
  );
};
