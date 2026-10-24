import React, { useEffect, useRef, useState } from 'react';
import * as k from '../iso/iso-kit';
import {
  Dots,
  Line,
  Solid,
  Wire,
} from '../iso/react/draw';
import { Stage, useEased, useLoop } from '../iso/react/live';
import {
  IncidentPresetId,
  postOperatorDecision,
  startBackendAgentRun,
} from '../api/client';

export type NodeId =
  | 'solar'
  | 'wind'
  | 'thermal'
  | 'battery'
  | 'substation'
  | 'houses';

type AnimStage = 'steady' | 'perturbing' | 'ai_solving';
type Pt2 = [number, number];

const W = 1440;
const H = 860;

// True isometric projection calibrated so our 6 free-floating 3D nodes
// span the entire full-screen white canvas from Left -> Center -> Right.
const ALL_ANCHORS: k.Point3[] = [
  [-245, -45, -10],
  [-160, 35, 32],
  [-175, 75, -10],
  [-95, 155, 38],
  [-75, 150, -10],
  [10, 230, 36],
  [-95, -105, -10],
  [-10, -25, 34],
  [10, 25, -10],
  [95, 105, 32],
  [90, -135, -10],
  [195, -35, 32],
];

const P = k.fitProjection(ALL_ANCHORS, W, H, {
  pad: 132,
  azimuth: 54,
  elevation: 30,
});

// Exact 3D world centers for the 6 free-floating infrastructure objects:
// Left column (Generation):
const SOLAR_C: k.Point3 = [-202, -6, 0];      // 01 · Planta Solar Atacama (Top-Left)
const WIND_C: k.Point3 = [-135, 110, 0];      // 02 · Parque Eólico Norte (Middle-Left)
const THERMAL_C: k.Point3 = [-36, 186, 0];    // 03 · Central Térmica Gas (Bottom-Left)

// Center column (AI Battery & 500 kV Substation):
const BATTERY_C: k.Point3 = [-53, -65, 0];    // 04 · Batería Agente IA BESS (Upper-Center)
const SUBSTATION_C: k.Point3 = [53, 62, 0];   // 05 · Subestación Troncal L2 (Lower-Center)

// Right column (Residential Neighborhood of Houses):
const HOUSES_C: k.Point3 = [134, -88, 0];     // 06 · Barrio Residencial (Center-Right)

function toPct(world: k.Point3): { left: string; top: string } {
  const [sx, sy] = k.iso(world, P);
  return {
    left: `${((sx / W) * 100).toFixed(2)}%`,
    top: `${((sy / H) * 100).toFixed(2)}%`,
  };
}

// Helper: interpolate a 2D point along a piecewise 2D polyline at t in [0, 1]
function samplePolyline(pts: Pt2[], tRaw: number): Pt2 {
  if (pts.length === 0) return [0, 0];
  if (pts.length === 1) return pts[0];
  const t = ((tRaw % 1) + 1) % 1;
  const segLengths: number[] = [];
  let total = 0;
  for (let i = 0; i < pts.length - 1; i++) {
    const dx = pts[i + 1][0] - pts[i][0];
    const dy = pts[i + 1][1] - pts[i][1];
    const len = Math.hypot(dx, dy);
    segLengths.push(len);
    total += len;
  }
  if (total <= 1e-6) return pts[0];
  let target = t * total;
  for (let i = 0; i < segLengths.length; i++) {
    const seg = segLengths[i];
    if (target <= seg || i === segLengths.length - 1) {
      const localT = seg > 1e-6 ? target / seg : 0;
      return [
        pts[i][0] + (pts[i + 1][0] - pts[i][0]) * localT,
        pts[i][1] + (pts[i + 1][1] - pts[i][1]) * localT,
      ];
    }
    target -= seg;
  }
  return pts[pts.length - 1];
}

// Animated suspended transmission line with traveling energy packets & mid-air flow badge
function AnimatedPowerLink({
  from,
  via = [],
  to,
  mw,
  tone,
  phase,
  reverse = false,
  isPerturbed = false,
  isAiSolving = false,
  midLabel,
  labelT = 0.58,
}: {
  from: Pt2;
  via?: Pt2[];
  to: Pt2;
  mw: number;
  tone: 'green' | 'blue' | 'red' | 'hi' | 'lo';
  phase: number;
  reverse?: boolean;
  isPerturbed?: boolean;
  isAiSolving?: boolean;
  midLabel?: string;
  labelT?: number;
}) {
  const pts = [from, ...via, to];
  const dPath = k.pathOf(pts, false);
  const absMw = Math.abs(mw);
  const activeFlow = absMw >= 5;

  const strokeSize =
    isPerturbed || isAiSolving
      ? 2.5
      : activeFlow
      ? Math.min(2.1, 1.25 + (absMw / 700) * 0.85)
      : 1.0;

  const auraColor =
    tone === 'red'
      ? '#e5484d'
      : tone === 'green'
      ? '#16a34a'
      : tone === 'blue'
      ? '#2563eb'
      : '#71717a';

  const packetCount = isPerturbed || isAiSolving ? 5 : activeFlow ? 3 : 0;
  const speedMult = isPerturbed
    ? 2.25
    : isAiSolving
    ? 2.0
    : Math.max(0.45, Math.min(1.55, absMw / 360));
  const labelPt = samplePolyline(pts, labelT);

  return (
    <g className="animated-power-link">
      {/* Stage 1 / Stage 2 luminous aura along the wire */}
      {(isPerturbed || isAiSolving) && (
        <path
          d={dPath}
          fill="none"
          stroke={auraColor}
          strokeWidth={isPerturbed ? 8.0 : 6.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity={isPerturbed ? 0.22 : 0.18}
        />
      )}

      {/* Main isometric wire with animated dashes */}
      <Wire
        from={from}
        via={via}
        to={to}
        tone={activeFlow ? tone : 'lo'}
        flow={activeFlow}
        size={strokeSize}
      />

      {/* Traveling luminous energy packets moving along the 3D wire */}
      {packetCount > 0 &&
        Array.from({ length: packetCount }).map((_, idx) => {
          const rawOffset = idx / packetCount + phase * speedMult * (reverse ? -1 : 1);
          const [px, py] = samplePolyline(pts, rawOffset);
          const rCore = isPerturbed ? 3.6 : isAiSolving ? 3.3 : 2.15;
          return (
            <g key={idx}>
              {(isPerturbed || isAiSolving) && (
                <circle
                  cx={px.toFixed(1)}
                  cy={py.toFixed(1)}
                  r={(rCore * 2.35).toFixed(1)}
                  fill={auraColor}
                  opacity={0.26}
                />
              )}
              <circle
                cx={px.toFixed(1)}
                cy={py.toFixed(1)}
                r={rCore.toFixed(1)}
                fill={auraColor}
                stroke="#ffffff"
                strokeWidth="0.9"
              />
            </g>
          );
        })}

      {/* Floating borderless mid-air telemetry tag directly on the wire */}
      {midLabel && (
        <g transform={`translate(${labelPt[0].toFixed(1)}, ${(labelPt[1] - 11).toFixed(1)})`}>
          <rect
            x={-midLabel.length * 3.05 - 6}
            y={-9}
            width={midLabel.length * 6.1 + 12}
            height={14}
            rx={3}
            fill="#ffffff"
            fillOpacity={0.94}
          />
          <text
            x={0}
            y={1}
            textAnchor="middle"
            fill={auraColor}
            style={{
              fontFamily: 'var(--anatomy-mono, ui-monospace, monospace)',
              fontSize: '9.5px',
              fontWeight: 700,
              letterSpacing: '0.06em',
            }}
          >
            {midLabel}
          </text>
        </g>
      )}
    </g>
  );
}

// Free-floating 3D isometric pitched-roof house (no ground plate)
function FloatingHouse({
  x,
  y,
  w,
  d,
  z,
  wallH,
  roofH,
  highlighted,
  powered = true,
}: {
  x: number;
  y: number;
  w: number;
  d: number;
  z: number;
  wallH: number;
  roofH: number;
  highlighted: boolean;
  powered?: boolean;
}) {
  const zTop = z + wallH;
  const zPeak = zTop + roofH;
  const yMid = y + d / 2;

  const x0 = x - 0.9;
  const x1 = x + w + 0.9;
  const yFront = y + d + 0.9;
  const yBack = y - 0.9;

  const r0 = k.iso([x0, yMid, zPeak], P);
  const r1 = k.iso([x1, yMid, zPeak], P);
  const f0 = k.iso([x0, yFront, zTop], P);
  const f1 = k.iso([x1, yFront, zTop], P);
  const b1 = k.iso([x1, yBack, zTop], P);

  const frontSlopePath = k.pathOf([r0, r1, f1, f0], true);
  const rightGablePath = k.pathOf([r1, b1, f1], true);
  const roofOutlinePath =
    k.pathOf([f0, r0, r1, b1, f1, f0], false) + k.pathOf([r1, f1], false);
  const roofSilhouette = k.pathOf([f0, r0, r1, b1, f1], true);

  const winZ0 = z + 2.0;
  const winZ1 = z + wallH - 1.5;
  const win1Path = k.pathOf(
    [
      k.iso([x + 2.2, y + d + 0.06, winZ0], P),
      k.iso([x + 5.4, y + d + 0.06, winZ0], P),
      k.iso([x + 5.4, y + d + 0.06, winZ1], P),
      k.iso([x + 2.2, y + d + 0.06, winZ1], P),
    ],
    true
  );
  const win2Path = k.pathOf(
    [
      k.iso([x + w - 5.4, y + d + 0.06, winZ0], P),
      k.iso([x + w - 2.2, y + d + 0.06, winZ0], P),
      k.iso([x + w - 2.2, y + d + 0.06, winZ1], P),
      k.iso([x + w - 5.4, y + d + 0.06, winZ1], P),
    ],
    true
  );
  const sideWinPath = k.pathOf(
    [
      k.iso([x + w + 0.06, y + d * 0.3, winZ0], P),
      k.iso([x + w + 0.06, y + d * 0.7, winZ0], P),
      k.iso([x + w + 0.06, y + d * 0.7, winZ1], P),
      k.iso([x + w + 0.06, y + d * 0.3, winZ1], P),
    ],
    true
  );

  return (
    <g>
      <path
        className="iso-halo"
        d={k.haloOf({ x, y, w, d, r: 1 }, z - 1.5, 2.5, P)}
      />
      <Solid
        paths={k.slabOf({ x, y, w, d, r: 0.7 }, z, wallH, P, 3, 0.25)}
        tone={powered ? 'hi' : 'mid'}
        lit={highlighted}
        inner={
          <path
            d={win1Path + win2Path + sideWinPath}
            fill={powered ? '#fde047' : '#94a3b8'}
            fillOpacity={powered ? 0.9 : 0.45}
            stroke={powered ? '#d97706' : '#64748b'}
            strokeWidth={0.38}
            strokeLinejoin="round"
          />
        }
      />
      <Solid
        paths={{
          fill: roofSilhouette,
          shades: [frontSlopePath, '', rightGablePath, ''],
          top: frontSlopePath,
          crease: k.pathOf([r1, f1], false),
          bevel: '',
          outline: roofOutlinePath,
        }}
        tone={powered ? 'hi' : 'mid'}
        lit={highlighted}
      />
    </g>
  );
}

// Free-floating 3D Wind Turbine
function FloatingWindTurbine({
  tx,
  ty,
  tz,
  towerH,
  bladeR,
  angleRad,
  highlighted,
}: {
  tx: number;
  ty: number;
  tz: number;
  towerH: number;
  bladeR: number;
  angleRad: number;
  highlighted: boolean;
}) {
  const hubZ = tz + towerH + 1.8;
  const hubX = tx + 2.8;
  const hubY = ty + 2.8;

  return (
    <g>
      <path
        className="iso-halo"
        d={k.haloOf({ x: tx - 4, y: ty - 4, w: 8, d: 8, r: 4 }, tz - 1, 2.5, P)}
      />
      <Solid
        paths={k.cylinder(tx, ty, 3.6, tz, 1.8, P, 18)}
        tone="mid"
        lit={highlighted}
      />
      <Solid
        paths={k.cylinder(tx, ty, 1.45, tz + 1.8, towerH, P, 16)}
        tone="hi"
        lit={highlighted}
      />
      <Solid
        paths={k.slabOf(
          { x: tx - 2.4, y: ty - 2.2, w: 5.8, d: 4.8, r: 1.0 },
          tz + towerH,
          3.4,
          P,
          3,
          0.3
        )}
        tone="hi"
        lit={highlighted}
      />
      {[0, 1, 2].map((bIdx) => {
        const theta = angleRad + (bIdx * Math.PI * 2) / 3;
        const tipX = hubX + Math.cos(theta) * bladeR * 0.72;
        const tipY = hubY - Math.cos(theta) * bladeR * 0.42;
        const tipZ = hubZ + Math.sin(theta) * bladeR;
        return (
          <Line
            key={bIdx}
            d={k.pathOf([k.iso([hubX, hubY, hubZ], P), k.iso([tipX, tipY, tipZ], P)])}
            tone="hi"
          />
        );
      })}
      <Dots points={[k.iso([hubX, hubY, hubZ], P)]} size={1.1} tone="hi" />
    </g>
  );
}

// 3D Mid-Air Transmission Pylon / Insulator Post along the wires
function MidAirPylon({ x, y, z }: { x: number; y: number; z: number }) {
  return (
    <g>
      <Solid
        paths={k.cylinder(x, y, 1.5, z - 2, 5.5, P, 12)}
        tone="mid"
        crease="none"
      />
      <Dots points={[k.iso([x, y, z + 3.8], P)]} size={0.95} tone="hi" pulse />
    </g>
  );
}

export const ChileIsoMaquette: React.FC = () => {
  const [activeNode, setActiveNode] = useState<NodeId | null>(null);

  // ============================================================================
  // REAL CHILE SEN 5-NODE PARAMETERS (from chile-sen-5node-demo HiGHS LP solver)
  // ============================================================================
  const [solarMw, setSolarMw] = useState<number>(620);     // 0..989 MW (solar_ng + solar_nc)
  const [windMw, setWindMw] = useState<number>(180);       // 40..400 MW (wind_nc + wind_sur)
  const [thermalMw, setThermalMw] = useState<number>(380); // 0..600 MW (gas_centro)
  const [l2CapMw, setL2CapMw] = useState<number>(400);     // 300..600 MW (L2 Norte Chico -> Centro bottleneck)
  const [demandMw, setDemandMw] = useState<number>(780);   // 500..1300 MW (Centro + Sur residential load)
  const [aiEnabled, setAiEnabled] = useState<boolean>(true);
  const [activePreset, setActivePreset] = useState<IncidentPresetId>('normal');

  // Two-stage animation state machine:
  // Stage 1 ('perturbing'): Plant parameter changes -> connected wire surges first
  // Stage 2 ('ai_solving'): AI Agent BESS automatically dispatches counter-flow to solve it
  const [animStage, setAnimStage] = useState<AnimStage>('steady');
  const [perturbedNode, setPerturbedNode] = useState<NodeId | null>(null);
  const stageTimer1 = useRef<number | null>(null);
  const stageTimer2 = useRef<number | null>(null);

  const triggerTwoStageReaction = (sourceNode: NodeId, nextAiEnabled = aiEnabled) => {
    if (stageTimer1.current) window.clearTimeout(stageTimer1.current);
    if (stageTimer2.current) window.clearTimeout(stageTimer2.current);

    setPerturbedNode(sourceNode);
    setAnimStage('perturbing');

    stageTimer1.current = window.setTimeout(() => {
      if (nextAiEnabled) {
        setAnimStage('ai_solving');
        stageTimer2.current = window.setTimeout(() => {
          setAnimStage('steady');
        }, 3200);
      } else {
        setAnimStage('steady');
      }
    }, 820);
  };

  useEffect(() => {
    return () => {
      if (stageTimer1.current) window.clearTimeout(stageTimer1.current);
      if (stageTimer2.current) window.clearTimeout(stageTimer2.current);
    };
  }, []);

  // Continuous animation loop for wind rotors, traveling wire packets, and AI sonar ring
  const [rotorPhase, setRotorPhase] = useState<number>(0);
  const [wirePhase, setWirePhase] = useState<number>(0);

  const windSpeedFactor = Math.max(0.4, windMw / 180);

  useLoop((dt, calm) => {
    if (calm) return false;
    setRotorPhase((p) => (p + dt * 1.35 * windSpeedFactor) % (Math.PI * 2));
    setWirePhase((p) => (p + dt * 0.42) % 1);
    return true;
  }, true);

  // ============================================================================
  // LIVE POWER-FLOW & AI AGENT DISPATCH PHYSICS (HiGHS LP Grounded)
  // ============================================================================
  const northRenewableMw = solarMw + windMw;
  const rawCorridorOverflowMw = Math.max(0, northRenewableMw - l2CapMw);

  // How much excess solar the AI Agent absorbs into BESS (up to 600 MW total storage absorption)
  const aiAbsorbMw = aiEnabled ? Math.min(600, rawCorridorOverflowMw) : 0;
  const curtailedSolarMw = Math.max(0, rawCorridorOverflowMw - aiAbsorbMw);

  // Flow reaching the 500 kV Substation from North renewables + Thermal gas
  const solarToBessMw = aiAbsorbMw;
  const windToSubMw = Math.min(windMw, l2CapMw);
  const solarToSubMw = Math.max(0, Math.min(solarMw - solarToBessMw - curtailedSolarMw, l2CapMw - windToSubMw));
  const thermalToSubMw = thermalMw;

  const substationInflowMw = solarToSubMw + windToSubMw + thermalToSubMw;
  const rawDeficitMw = Math.max(0, demandMw - substationInflowMw);

  // If thermal drops or demand spikes, AI Agent injects emergency BESS power!
  const aiInjectMw = aiEnabled && rawDeficitMw > 0 ? Math.min(480, rawDeficitMw) : 0;
  const unservedMw = Math.max(0, rawDeficitMw - aiInjectMw);

  // Net BESS flow (+ charging from solar excess, - discharging to rescue homes)
  const netBessMw = aiInjectMw > 0 ? -aiInjectMw : aiAbsorbMw;
  const bessTargetSoc =
    aiInjectMw > 0
      ? Math.max(24, Math.round(82 - (aiInjectMw / 480) * 48))
      : aiAbsorbMw > 0
      ? Math.min(96, Math.round(56 + (aiAbsorbMw / 600) * 38))
      : 68;

  const subToHousesMw = Math.min(demandMw, substationInflowMw);
  const bessToHousesMw = aiInjectMw;
  const bessToSubMw =
    aiAbsorbMw > 0
      ? Math.round(aiAbsorbMw * 0.25)
      : aiInjectMw > 0
      ? -Math.round(aiInjectMw * 0.35)
      : 45;

  const supplyRatio = demandMw > 0 ? Math.min(1, (subToHousesMw + bessToHousesMw) / demandMw) : 1;
  const litHousesCount = unservedMw <= 15 ? 6 : Math.max(1, Math.round(supplyRatio * 6));
  const freqHz = unservedMw > 20 ? 49.42 : curtailedSolarMw > 80 ? 50.18 : 50.0;

  // Smoothly eased 3D heights & gauge angles
  const solarLift = useEased(
    activeNode === 'solar' || (animStage === 'perturbing' && perturbedNode === 'solar') ? 4.8 : 0,
    0.22
  );
  const windLift = useEased(
    activeNode === 'wind' || (animStage === 'perturbing' && perturbedNode === 'wind') ? 4.8 : 0,
    0.22
  );
  const thermalLift = useEased(
    activeNode === 'thermal' || (animStage === 'perturbing' && perturbedNode === 'thermal') ? 4.8 : 0,
    0.22
  );
  const batteryLift = useEased(
    activeNode === 'battery' || animStage === 'ai_solving' ? 5.2 : 0,
    0.22
  );
  const subLift = useEased(
    activeNode === 'substation' || (animStage === 'perturbing' && perturbedNode === 'substation') ? 4.8 : 0,
    0.22
  );
  const housesLift = useEased(
    activeNode === 'houses' || (animStage === 'perturbing' && perturbedNode === 'houses') ? 4.8 : 0,
    0.22
  );

  // Physical 3D battery core cylinder height responds smoothly to State of Charge (SoC)
  const bessCoreHeight = useEased(4.8 + (bessTargetSoc / 100) * 7.4, 0.16);

  // Smoothly eased Substation 500 kV Dial Gauge Needle
  const corridorLoadRatio = Math.min(1.12, (solarToSubMw + windToSubMw) / Math.max(1, l2CapMw));
  const easedDialRatio = useEased(corridorLoadRatio, 0.18);

  const dialX = SUBSTATION_C[0] - 12;
  const dialY = SUBSTATION_C[1] + 16;
  const dialR = 13.5;
  const dialZ = SUBSTATION_C[2] + 3.2 + subLift;

  const dialTicks = k.radialTicks(
    dialX,
    dialY,
    dialR - 2.2,
    24,
    4,
    dialZ,
    [1.3, 2.6],
    P,
    -Math.PI * 0.75,
    Math.PI * 1.5
  );

  const needleAngle = -Math.PI * 0.75 + easedDialRatio * Math.PI * 1.5;
  const needleTip: k.Point3 = [
    dialX + Math.cos(needleAngle) * (dialR - 3.6),
    dialY + Math.sin(needleAngle) * (dialR - 3.6),
    dialZ + 0.4,
  ];

  // ============================================================================
  // PRESET SCENARIOS FROM TEAMMATES' HiGHS LP SOLVER
  // ============================================================================
  const applyScenarioPreset = (preset: IncidentPresetId) => {
    setActivePreset(preset);
    if (preset === 'normal') {
      // Peak Atacama solar congestion on L2 (880 MW solar + 180 MW wind, 400 MW L2 cap, 380 MW thermal, 780 MW demand)
      setSolarMw(880);
      setWindMw(180);
      setThermalMw(380);
      setL2CapMw(400);
      setDemandMw(780);
      setAiEnabled(true);
      triggerTwoStageReaction('solar', true);
    } else if (preset === 'sudden_outage') {
      // Sudden thermal crash at 18:00-22:00 (gas_centro drops to 0 MW, evening demand 780 MW, solar 180 MW, wind 220 MW)
      setSolarMw(180);
      setWindMw(220);
      setThermalMw(0);
      setL2CapMw(400);
      setDemandMw(780);
      setAiEnabled(true);
      triggerTwoStageReaction('thermal', true);
    } else if (preset === 'planned_maintenance') {
      // Planned maintenance + L2 uprate to 600 MW (c3_uprate_l2)
      setSolarMw(720);
      setWindMw(220);
      setThermalMw(200);
      setL2CapMw(600);
      setDemandMw(800);
      setAiEnabled(true);
      triggerTwoStageReaction('substation', true);
    }
    void startBackendAgentRun(preset);
    void postOperatorDecision({
      investigation_id: `sen-${preset}`,
      candidate_id: preset === 'planned_maintenance' ? 'uprate_l2' : 'north_bess',
      decision: 'approved',
    });
  };

  // Live two-stage narrative text for top borderless telemetry bar (exact HiGHS LP numbers from Bernardo's feature/optimisation)
  let stage1Summary = '';
  let stage2Summary = '';

  if (unservedMw > 10) {
    stage1Summary = `ALERTA DE RED: Déficit térmico de ${Math.round(rawDeficitMw)} MW hacia 06 · Barrio Residencial (1,921.9 MWh apagón base)`;
    stage2Summary = `AGENTE IA APAGADO: ${Math.round(unservedMw)} MW sin suministro (${6 - litHousesCount} manzanas a oscuras · Activa north_bess para salvar 391,875 hogares-h)`;
  } else if (aiInjectMw > 0) {
    stage1Summary = `FASE 1 · PERTURBACIÓN: Caída súbita en 03 · Central Gas (18:00–22:00) deja déficit de ${Math.round(rawDeficitMw)} MW en hora punta`;
    stage2Summary = `FASE 2 · SOLUCIÓN AGENTE IA (north_bess / south_bess): Inyecta +${Math.round(aiInjectMw)} MW → 100% hogares iluminados (-391.9 MWh apagón · 391,875 hogares-h protegidos)`;
  } else if (curtailedSolarMw > 10) {
    stage1Summary = `SATURACIÓN L2: Excedente renovable de +${Math.round(rawCorridorOverflowMw)} MW supera capacidad de 05 · Troncal L2 (${l2CapMw} MW)`;
    stage2Summary = `AGENTE IA APAGADO: Se desperdician ${Math.round(curtailedSolarMw)} MW solares (1,368.2 MWh/día en baseline · Activa IA para almacenar en BESS)`;
  } else if (aiAbsorbMw > 0) {
    const savedUsd = Math.round((aiAbsorbMw / 480) * 74230);
    const savedMwh = ((aiAbsorbMw / 480) * 631.6).toFixed(1);
    stage1Summary = `FASE 1 · PERTURBACIÓN: Generación Norte (${Math.round(northRenewableMw)} MW) supera capacidad de 05 · Troncal L2 (${l2CapMw} MW)`;
    stage2Summary = `FASE 2 · SOLUCIÓN AGENTE IA (north_bess): Absorbe +${Math.round(aiAbsorbMw)} MW por línea directa → 0 MW recorte (-${savedMwh} MWh · -$${savedUsd.toLocaleString()} USD/día)`;
  } else {
    stage1Summary = `FLUJO NOMINAL SEN: Generación limpia (${Math.round(northRenewableMw)} MW) + Térmica (${thermalMw} MW) abasteciendo ${demandMw} MW`;
    stage2Summary = `AGENTE IA EN GUARDIA (HiGHS LP): Corredor L2 al ${Math.round(corridorLoadRatio * 100)}% (${Math.round(solarToSubMw + windToSubMw)}/${l2CapMw} MW) · 50.00 Hz estables`;
  }

  // 4-datum minimalist borderless specifications + inline parameter controls
  const nodeSpecs: Array<{
    id: NodeId;
    pos: { left: string; top: string };
    align: 'left' | 'right' | 'center';
    dotColor: string;
    name: string;
    d1: string;
    d2: string;
    d3: string;
    slider?: {
      value: number;
      min: number;
      max: number;
      step: number;
      unit: string;
      accent: string;
      onChange: (v: number) => void;
      quickLabel?: string;
      onQuickClick?: () => void;
    };
  }> = [
    {
      id: 'solar',
      pos: toPct([SOLAR_C[0] - 8, SOLAR_C[1] - 32, 20]),
      align: 'center',
      dotColor: curtailedSolarMw > 10 ? '#e5484d' : '#16a34a',
      name: '01 · PLANTA SOLAR ATACAMA',
      d1: `${solarMw} MW · FV NORTE GRANDE`,
      d2:
        aiAbsorbMw > 0
          ? `→ +${Math.round(aiAbsorbMw)} MW A BATERÍA IA · ${Math.round(solarToSubMw)} MW A L2`
          : `220 kV DC/AC → ${Math.round(solarToSubMw)} MW EN L2`,
      d3:
        curtailedSolarMw > 10
          ? `▲ ${Math.round(curtailedSolarMw)} MW RECORTE SOLAR`
          : `${Math.round((solarMw / 989) * 100)}% IRRADIANCIA · 0 VERTIMIENTO`,
      slider: {
        value: solarMw,
        min: 0,
        max: 989,
        step: 25,
        unit: 'MW',
        accent: '#16a34a',
        onChange: (v) => {
          setSolarMw(v);
          triggerTwoStageReaction('solar');
        },
        quickLabel: solarMw < 850 ? 'Pico 880 MW' : 'Base 420 MW',
        onQuickClick: () => {
          const next = solarMw < 850 ? 880 : 420;
          setSolarMw(next);
          triggerTwoStageReaction('solar');
        },
      },
    },
    {
      id: 'wind',
      pos: toPct([WIND_C[0] - 16, WIND_C[1] + 20, -18]),
      align: 'center',
      dotColor: '#16a34a',
      name: '02 · PARQUE EÓLICO NORTE',
      d1: `${windMw} MW · EÓLICA`,
      d2: `220 kV AC → ${Math.round(windToSubMw)} MW EN L2`,
      d3: `${(8.5 + (windMw / 400) * 9.5).toFixed(1)} RPM · 3 TURBINAS`,
      slider: {
        value: windMw,
        min: 40,
        max: 400,
        step: 20,
        unit: 'MW',
        accent: '#16a34a',
        onChange: (v) => {
          setWindMw(v);
          triggerTwoStageReaction('wind');
        },
        quickLabel: windMw < 340 ? 'Ráfaga 360 MW' : 'Base 180 MW',
        onQuickClick: () => {
          const next = windMw < 340 ? 360 : 180;
          setWindMw(next);
          triggerTwoStageReaction('wind');
        },
      },
    },
    {
      id: 'thermal',
      pos: toPct([THERMAL_C[0] + 6, THERMAL_C[1] + 28, -12]),
      align: 'center',
      dotColor: thermalMw === 0 ? '#e5484d' : '#2563eb',
      name: '03 · CENTRAL TÉRMICA GAS',
      d1: thermalMw === 0 ? '0 MW · FUERA DE SERVICIO' : `${thermalMw} MW · CICLO COMBINADO`,
      d2: '500 kV AC · GAS_CENTRO',
      d3: thermalMw === 0 ? '▲ CAÍDA FORZADA 18:00–22:00' : 'RESERVA SINCRÓNICA ACTIVA',
      slider: {
        value: thermalMw,
        min: 0,
        max: 600,
        step: 50,
        unit: 'MW',
        accent: thermalMw === 0 ? '#e5484d' : '#2563eb',
        onChange: (v) => {
          setThermalMw(v);
          triggerTwoStageReaction('thermal');
        },
        quickLabel: thermalMw > 0 ? 'Provocar caída 0 MW' : 'Restaurar 380 MW',
        onQuickClick: () => {
          if (thermalMw > 0) {
            applyScenarioPreset('sudden_outage');
          } else {
            setThermalMw(380);
            setSolarMw(620);
            triggerTwoStageReaction('thermal');
          }
        },
      },
    },
    {
      id: 'battery',
      pos: toPct([BATTERY_C[0] - 2, BATTERY_C[1] - 32, 20]),
      align: 'center',
      dotColor: !aiEnabled ? '#71717a' : aiInjectMw > 0 ? '#2563eb' : '#16a34a',
      name: '04 · BATERÍA AGENTE IA (BESS)',
      d1: !aiEnabled
        ? '0 MW · AGENTE IA EN PAUSA'
        : netBessMw > 0
        ? `+${Math.round(netBessMw)} MW · ABSORBIENDO EXCEDENTE`
        : netBessMw < 0
        ? `+${Math.round(Math.abs(netBessMw))} MW · INYECCIÓN RESCATE`
        : 'EN GUARDIA · OPTIMIZADOR HiGHS',
      d2: '800 MWh NORTE + 600 MWh SUR',
      d3: `${bessTargetSoc}% SoC · ${aiEnabled ? 'DESPACHO IA AUTOMÁTICO' : 'MODO MANUAL SIN IA'}`,
    },
    {
      id: 'substation',
      pos: toPct([SUBSTATION_C[0] - 2, SUBSTATION_C[1] + 34, -11]),
      align: 'center',
      dotColor: curtailedSolarMw > 10 ? '#e5484d' : '#2563eb',
      name: '05 · SUBESTACIÓN TRONCAL L2',
      d1: `${Math.round(solarToSubMw + windToSubMw)} / ${l2CapMw} MW · CORREDOR L2`,
      d2: '500 kV / 220 kV · NORTE → CENTRO',
      d3: `${freqHz.toFixed(2)} Hz · ${l2CapMw > 450 ? 'AMPLIACIÓN c3 ACTIVA' : 'CAPACIDAD NOMINAL'}`,
      slider: {
        value: l2CapMw,
        min: 300,
        max: 600,
        step: 50,
        unit: 'MW',
        accent: '#2563eb',
        onChange: (v) => {
          setL2CapMw(v);
          triggerTwoStageReaction('substation');
        },
        quickLabel: l2CapMw < 600 ? 'Ampliar L2 a 600 MW' : 'Base 400 MW',
        onQuickClick: () => {
          const next = l2CapMw < 600 ? 600 : 400;
          setL2CapMw(next);
          triggerTwoStageReaction('substation');
        },
      },
    },
    {
      id: 'houses',
      pos: toPct([HOUSES_C[0] - 10, HOUSES_C[1] - 26, 29]),
      align: 'center',
      dotColor: unservedMw > 15 ? '#e5484d' : '#16a34a',
      name: '06 · BARRIO RESIDENCIAL',
      d1: `${demandMw} MW · DEMANDA HOGARES`,
      d2: aiInjectMw > 0 ? `+${Math.round(aiInjectMw)} MW RESPALDO BESS IA` : '23 kV / 220 V AC · CENTRO-SUR',
      d3:
        unservedMw > 15
          ? `▲ ${Math.round(unservedMw)} MW DÉFICIT (${litHousesCount}/6 MANZANAS)`
          : `100% SUMINISTRO (${litHousesCount}/6 MANZANAS ILUMINADAS)`,
      slider: {
        value: demandMw,
        min: 500,
        max: 1200,
        step: 40,
        unit: 'MW',
        accent: unservedMw > 15 ? '#e5484d' : '#16a34a',
        onChange: (v) => {
          setDemandMw(v);
          triggerTwoStageReaction('houses');
        },
        quickLabel: demandMw < 1050 ? 'Punta 1,100 MW' : 'Base 780 MW',
        onQuickClick: () => {
          const next = demandMw < 1050 ? 1100 : 780;
          setDemandMw(next);
          triggerTwoStageReaction('houses');
        },
      },
    },
  ];

  return (
    <Stage className="iso iso-fullspace">
      <div className="fullspace-stage">
        {/* =========================================================
            TOP BORDERLESS TELEMETRY & 2-STAGE AI AGENT NARRATIVE
           ========================================================= */}
        <header className="bare-top-telemetry">
          <div className="bare-top-row">
            <span className="bare-brand-tag">
              <span
                className="bare-live-dot"
                style={{
                  backgroundColor:
                    animStage === 'perturbing'
                      ? '#e5484d'
                      : animStage === 'ai_solving'
                      ? '#16a34a'
                      : '#2563eb',
                }}
              />
              SEN CHILE · RED 3D & AGENTE IA (HiGHS LP)
            </span>

            <div className="bare-preset-links">
              <button
                type="button"
                className={`bare-link-btn ${activePreset === 'normal' ? 'is-current' : ''}`}
                onClick={() => applyScenarioPreset('normal')}
              >
                01 · Pico Solar (880 MW)
              </button>
              <span className="bare-sep">·</span>
              <button
                type="button"
                className={`bare-link-btn ${activePreset === 'sudden_outage' ? 'is-current' : ''}`}
                onClick={() => applyScenarioPreset('sudden_outage')}
              >
                02 · Caída Gas (0 MW)
              </button>
              <span className="bare-sep">·</span>
              <button
                type="button"
                className={`bare-link-btn ${activePreset === 'planned_maintenance' ? 'is-current' : ''}`}
                onClick={() => applyScenarioPreset('planned_maintenance')}
              >
                03 · Ampliación L2 (600 MW)
              </button>
              <span className="bare-sep">|</span>
              <button
                type="button"
                className={`bare-ai-toggle ${aiEnabled ? 'is-on' : 'is-off'}`}
                onClick={() => {
                  const next = !aiEnabled;
                  setAiEnabled(next);
                  triggerTwoStageReaction('battery', next);
                }}
              >
                {aiEnabled ? '● AGENTE IA: ACTIVO' : '○ AGENTE IA: APAGADO'}
              </button>
            </div>
          </div>

          <div className="bare-narrative-strip">
            <span
              className={`bare-stage-line ${
                animStage === 'perturbing' ? 'is-highlighting-perturb' : ''
              }`}
            >
              {stage1Summary}
            </span>
            <span className="bare-arrow-sep">→</span>
            <span
              className={`bare-stage-line ${
                animStage === 'ai_solving'
                  ? 'is-highlighting-ai'
                  : !aiEnabled
                  ? 'is-ai-disabled'
                  : 'is-ai-steady'
              }`}
            >
              {stage2Summary}
            </span>
          </div>
        </header>

        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="fullspace-svg"
          aria-label="Esquema 3D interactivo de la red eléctrica de Chile"
        >
          {/* =========================================================
              SUSPENDED MID-AIR NETWORK WIRES WITH 2-STAGE ANIMATION
             ========================================================= */}
          <g className="network-wires">
            {/* Render Mid-Air Junction Pylons first so wire telemetry badges stay crisp on top */}
            <MidAirPylon x={-132} y={-38} z={2} />
            <MidAirPylon x={-68} y={92} z={1} />
            <MidAirPylon x={0} y={0} z={2} />
            <MidAirPylon x={28} y={-76} z={2} />
            <MidAirPylon x={96} y={12} z={2} />

            {/* 1. Solar Plant -> AI Battery (Direct DC/AC AI Solar Absorption Link) */}
            <AnimatedPowerLink
              from={k.iso([SOLAR_C[0] + 24, SOLAR_C[1] - 4, 2 + solarLift], P)}
              via={[
                k.iso([-132, -38, 2], P),
                k.iso([-95, -52, 2], P),
              ]}
              to={k.iso([BATTERY_C[0] - 24, BATTERY_C[1] + 2, 2 + batteryLift], P)}
              mw={solarToBessMw}
              tone="green"
              phase={wirePhase}
              isPerturbed={animStage === 'perturbing' && perturbedNode === 'solar' && solarToBessMw > 0}
              isAiSolving={
                (animStage === 'ai_solving' && solarToBessMw > 0) ||
                (aiEnabled && solarToBessMw >= 100)
              }
              labelT={0.64}
              midLabel={
                solarToBessMw > 0
                  ? `IA +${Math.round(solarToBessMw)} MW → CARGA BESS`
                  : undefined
              }
            />

            {/* 2. Solar Plant -> 500 kV Substation (Corridor L1/L2) */}
            <AnimatedPowerLink
              from={k.iso([SOLAR_C[0] + 22, SOLAR_C[1] + 12, 2 + solarLift], P)}
              via={[
                k.iso([-115, 22, 1], P),
                k.iso([-42, 48, 1], P),
              ]}
              to={k.iso([SUBSTATION_C[0] - 26, SUBSTATION_C[1] - 6, 2 + subLift], P)}
              mw={solarToSubMw}
              tone={curtailedSolarMw > 10 ? 'red' : 'green'}
              phase={wirePhase}
              isPerturbed={animStage === 'perturbing' && perturbedNode === 'solar'}
              labelT={0.5}
              midLabel={
                animStage === 'perturbing' && perturbedNode === 'solar'
                  ? `PICO SOLAR ${solarMw} MW → L2`
                  : curtailedSolarMw > 10
                  ? `L2 SATURADA (+${Math.round(curtailedSolarMw)} MW RECORTE)`
                  : `${Math.round(solarToSubMw)} MW SOLAR → L2`
              }
            />

            {/* 3. Wind Farm -> 500 kV Substation */}
            <AnimatedPowerLink
              from={k.iso([WIND_C[0] + 24, WIND_C[1] - 4, 2 + windLift], P)}
              via={[
                k.iso([-68, 92, 1], P),
                k.iso([-12, 78, 1], P),
              ]}
              to={k.iso([SUBSTATION_C[0] - 24, SUBSTATION_C[1] + 8, 2 + subLift], P)}
              mw={windToSubMw}
              tone="green"
              phase={wirePhase}
              isPerturbed={animStage === 'perturbing' && perturbedNode === 'wind'}
              labelT={0.62}
              midLabel={
                animStage === 'perturbing' && perturbedNode === 'wind'
                  ? `${windMw} MW EÓLICA → L2`
                  : undefined
              }
            />

            {/* 4. Thermal Gas Plant -> 500 kV Substation */}
            <AnimatedPowerLink
              from={k.iso([THERMAL_C[0] + 24, THERMAL_C[1] - 12, 2 + thermalLift], P)}
              via={[
                k.iso([8, 144, 1], P),
                k.iso([35, 108, 1], P),
              ]}
              to={k.iso([SUBSTATION_C[0] - 6, SUBSTATION_C[1] + 22, 2 + subLift], P)}
              mw={thermalToSubMw}
              tone={thermalMw === 0 ? 'red' : 'blue'}
              phase={wirePhase}
              isPerturbed={animStage === 'perturbing' && perturbedNode === 'thermal'}
              labelT={0.5}
              midLabel={
                thermalMw === 0
                  ? '0 MW · CAÍDA GAS_CENTRO'
                  : animStage === 'perturbing' && perturbedNode === 'thermal'
                  ? `${thermalMw} MW TÉRMICA`
                  : undefined
              }
            />

            {/* 5. Bidirectional AI Battery <-> 500 kV Substation Link */}
            <AnimatedPowerLink
              from={k.iso([BATTERY_C[0] + 4, BATTERY_C[1] + 20, 2 + batteryLift], P)}
              via={[k.iso([0, 0, 2], P)]}
              to={k.iso([SUBSTATION_C[0] - 4, SUBSTATION_C[1] - 20, 2 + subLift], P)}
              mw={aiEnabled ? Math.max(60, Math.abs(bessToSubMw)) : 0}
              tone={aiInjectMw > 0 ? 'blue' : 'green'}
              phase={wirePhase}
              reverse={bessToSubMw > 0}
              isAiSolving={animStage === 'ai_solving'}
              labelT={0.68}
              midLabel={
                animStage === 'ai_solving'
                  ? aiAbsorbMw > 0
                    ? 'IA DESCONGESTIONA L2'
                    : 'IA ESTABILIZA 50 Hz'
                  : undefined
              }
            />

            {/* 6. AI Battery -> Residential Neighborhood (Emergency AI Dispatch Line) */}
            <AnimatedPowerLink
              from={k.iso([BATTERY_C[0] + 26, BATTERY_C[1] - 4, 2 + batteryLift], P)}
              via={[
                k.iso([28, -76, 2], P),
                k.iso([78, -82, 2], P),
              ]}
              to={k.iso([HOUSES_C[0] - 32, HOUSES_C[1] - 8, 2 + housesLift], P)}
              mw={bessToHousesMw}
              tone="blue"
              phase={wirePhase}
              isAiSolving={bessToHousesMw > 0}
              labelT={0.62}
              midLabel={
                bessToHousesMw > 0
                  ? `RESCATE IA +${Math.round(bessToHousesMw)} MW → HOGARES`
                  : undefined
              }
            />

            {/* 7. 500 kV Substation -> Residential Neighborhood (Main Trunk Feeder) */}
            <AnimatedPowerLink
              from={k.iso([SUBSTATION_C[0] + 26, SUBSTATION_C[1] - 6, 2 + subLift], P)}
              via={[
                k.iso([96, 12, 2], P),
                k.iso([118, -32, 2], P),
              ]}
              to={k.iso([HOUSES_C[0] - 18, HOUSES_C[1] + 26, 2 + housesLift], P)}
              mw={subToHousesMw}
              tone={unservedMw > 15 ? 'red' : 'blue'}
              phase={wirePhase}
              isPerturbed={
                animStage === 'perturbing' &&
                (perturbedNode === 'substation' || perturbedNode === 'houses')
              }
              labelT={0.62}
              midLabel={
                unservedMw > 15
                  ? `DÉFICIT -${Math.round(unservedMw)} MW`
                  : `${Math.round(subToHousesMw)} MW TRONCAL`
              }
            />
          </g>

          {/* =========================================================
              NODE 01: PLANTA SOLAR ATACAMA (Free-floating 3D arrays)
             ========================================================= */}
          <g
            className="maquette-station-group"
            onMouseEnter={() => setActiveNode('solar')}
            onMouseLeave={() => setActiveNode(null)}
            onClick={() => setActiveNode((n) => (n === 'solar' ? null : 'solar'))}
          >
            {[-18, -5, 8, 21].map((dx) =>
              [-14, 4].map((dy) => {
                const px = SOLAR_C[0] + dx - 10;
                const py = SOLAR_C[1] + dy;
                const pz = SOLAR_C[2] + solarLift;
                return (
                  <g key={`pv-${dx}-${dy}`}>
                    <path
                      className="iso-halo"
                      d={k.haloOf({ x: px, y: py, w: 10.5, d: 12.5, r: 1 }, pz - 1, 2, P)}
                    />
                    <Solid
                      paths={k.cylinder(px + 5.2, py + 6.2, 1.3, pz - 2, 2.2, P, 12)}
                      tone="lo"
                      crease="none"
                    />
                    <Solid
                      paths={k.slabOf(
                        { x: px, y: py, w: 10.5, d: 12.5, r: 0.9 },
                        pz,
                        2.4,
                        P,
                        4,
                        0.4
                      )}
                      tone={solarMw > 50 ? 'hi' : 'mid'}
                      lit={activeNode === 'solar' || solarMw >= 800}
                      inner={
                        <Line
                          d={
                            k.topTicks(
                              px + 1.8,
                              px + 8.8,
                              2.4,
                              1,
                              py + 1.4,
                              pz + 2.4,
                              [9.6, 9.6],
                              P,
                              'x'
                            ).minor +
                            k.topTicks(
                              py + 2.2,
                              py + 10.4,
                              2.8,
                              1,
                              px + 1.4,
                              pz + 2.4,
                              [7.8, 7.8],
                              P,
                              'y'
                            ).minor
                          }
                          tone={curtailedSolarMw > 10 ? 'red' : 'green'}
                        />
                      }
                    />
                  </g>
                );
              })
            )}

            <Solid
              paths={k.slabOf(
                { x: SOLAR_C[0] + 15, y: SOLAR_C[1] - 10, w: 10, d: 18, r: 1.2 },
                SOLAR_C[2] + solarLift,
                7.5,
                P,
                4,
                0.5
              )}
              tone="hi"
              lit={activeNode === 'solar'}
            />
            <Solid
              paths={k.cylinder(
                SOLAR_C[0] + 20,
                SOLAR_C[1] - 1,
                2.0,
                SOLAR_C[2] + 7.5 + solarLift,
                4.2,
                P,
                14
              )}
              tone="mid"
            />
          </g>

          {/* =========================================================
              NODE 04: BATERÍA AGENTE IA (BESS) (Upper-Center in space)
             ========================================================= */}
          <g
            className="maquette-station-group"
            onMouseEnter={() => setActiveNode('battery')}
            onMouseLeave={() => setActiveNode(null)}
            onClick={() => setActiveNode((n) => (n === 'battery' ? null : 'battery'))}
          >
            {/* Expanding 3D Isometric AI Agent Sonar Rings during Stage 2 solution */}
            {(animStage === 'ai_solving' || aiAbsorbMw > 0 || aiInjectMw > 0) &&
              aiEnabled && (
                <g>
                  <path
                    d={k.ring(
                      BATTERY_C[0],
                      BATTERY_C[1] + 2,
                      26 + wirePhase * 16,
                      BATTERY_C[2] + 1 + batteryLift,
                      P,
                      36
                    )}
                    fill="none"
                    stroke={aiInjectMw > 0 ? '#2563eb' : '#16a34a'}
                    strokeWidth={1.3}
                    opacity={Math.max(0, 0.65 - wirePhase * 0.65)}
                  />
                  <path
                    d={k.ring(
                      BATTERY_C[0],
                      BATTERY_C[1] + 2,
                      26 + ((wirePhase + 0.5) % 1) * 16,
                      BATTERY_C[2] + 1 + batteryLift,
                      P,
                      36
                    )}
                    fill="none"
                    stroke={aiInjectMw > 0 ? '#2563eb' : '#16a34a'}
                    strokeWidth={1.1}
                    opacity={Math.max(0, 0.55 - ((wirePhase + 0.5) % 1) * 0.55)}
                  />
                </g>
              )}

            {/* 4 Modular BESS Rack Enclosures (back row) */}
            {[-20, -8, 4, 16].map((dx, i) => {
              const bx = BATTERY_C[0] + dx;
              const by = BATTERY_C[1] - 14;
              const bz = BATTERY_C[2] + batteryLift;
              return (
                <g key={`bess-rack-${i}`}>
                  <path
                    className="iso-halo"
                    d={k.haloOf({ x: bx, y: by, w: 9.5, d: 11, r: 1.2 }, bz - 1, 2.2, P)}
                  />
                  <Solid
                    paths={k.slabOf(
                      { x: bx, y: by, w: 9.5, d: 11, r: 1.1 },
                      bz,
                      9.5,
                      P,
                      4,
                      0.5
                    )}
                    tone={aiEnabled ? 'hi' : 'mid'}
                    lit={aiEnabled}
                    inner={
                      <Line
                        d={
                          k.sideTicks(
                            bx + 1.8,
                            bx + 7.7,
                            2.0,
                            1,
                            by + 11,
                            bz + 7.5,
                            [5.2, 5.2],
                            P,
                            'x'
                          ).minor
                        }
                        tone={!aiEnabled ? 'lo' : aiInjectMw > 0 ? 'blue' : 'green'}
                      />
                    }
                  />
                </g>
              );
            })}

            {/* 4 Cylindrical Energy Cores (height physically rises/falls with SoC) */}
            {[-15, -5, 5, 15].map((dx, idx) => {
              const cx = BATTERY_C[0] + dx;
              const cy = BATTERY_C[1] + 6;
              const cz = BATTERY_C[2] + batteryLift;
              return (
                <g key={`cell-${idx}`}>
                  <path
                    className="iso-halo"
                    d={k.haloOf({ x: cx - 4, y: cy - 4, w: 8, d: 8, r: 4 }, cz - 1, 2, P)}
                  />
                  <Solid
                    paths={k.cylinder(cx, cy, 4.0, cz, 2.0, P, 20)}
                    tone="lo"
                  />
                  <Solid
                    paths={k.cylinder(cx, cy, 3.4, cz + 2.0, bessCoreHeight, P, 20)}
                    tone={aiEnabled ? 'hi' : 'mid'}
                    lit={aiEnabled}
                    inner={
                      <Line
                        d={k.ring(cx, cy, 2.2, cz + 2.0 + bessCoreHeight, P, 18)}
                        tone={!aiEnabled ? 'lo' : aiInjectMw > 0 ? 'blue' : 'green'}
                      />
                    }
                  />
                </g>
              );
            })}

            {/* AI Dispatch Core Module */}
            <Solid
              paths={k.slabOf(
                { x: BATTERY_C[0] - 8, y: BATTERY_C[1] + 15, w: 16, d: 9, r: 1.4 },
                BATTERY_C[2] + batteryLift,
                5.5,
                P,
                4,
                0.5
              )}
              tone="hi"
              lit={aiEnabled}
            />
            <Dots
              points={[
                k.iso([BATTERY_C[0] - 3, BATTERY_C[1] + 19.5, BATTERY_C[2] + 5.8 + batteryLift], P),
                k.iso([BATTERY_C[0], BATTERY_C[1] + 19.5, BATTERY_C[2] + 5.8 + batteryLift], P),
                k.iso([BATTERY_C[0] + 3, BATTERY_C[1] + 19.5, BATTERY_C[2] + 5.8 + batteryLift], P),
              ]}
              size={1.15}
              tone="hi"
              pulse={aiEnabled}
            />
          </g>

          {/* =========================================================
              NODE 02: PARQUE EÓLICO NORTE (Middle-Left in space)
             ========================================================= */}
          <g
            className="maquette-station-group"
            onMouseEnter={() => setActiveNode('wind')}
            onMouseLeave={() => setActiveNode(null)}
            onClick={() => setActiveNode((n) => (n === 'wind' ? null : 'wind'))}
          >
            <FloatingWindTurbine
              tx={WIND_C[0] - 14}
              ty={WIND_C[1] - 10}
              tz={WIND_C[2] + windLift}
              towerH={24}
              bladeR={12.5}
              angleRad={rotorPhase}
              highlighted={activeNode === 'wind'}
            />
            <FloatingWindTurbine
              tx={WIND_C[0] + 4}
              ty={WIND_C[1] - 2}
              tz={WIND_C[2] + windLift}
              towerH={26}
              bladeR={13.5}
              angleRad={rotorPhase + 1.1}
              highlighted={activeNode === 'wind'}
            />
            <FloatingWindTurbine
              tx={WIND_C[0] - 6}
              ty={WIND_C[1] + 14}
              tz={WIND_C[2] + windLift}
              towerH={22}
              bladeR={11.5}
              angleRad={rotorPhase + 2.3}
              highlighted={activeNode === 'wind'}
            />
            <Solid
              paths={k.slabOf(
                { x: WIND_C[0] + 12, y: WIND_C[1] + 6, w: 11, d: 11, r: 1.2 },
                WIND_C[2] + windLift,
                6.5,
                P,
                4,
                0.5
              )}
              tone="hi"
              lit={activeNode === 'wind'}
            />
          </g>

          {/* =========================================================
              NODE 05: SUBESTACIÓN TRONCAL L2 500 kV (Lower-Center)
             ========================================================= */}
          <g
            className="maquette-station-group"
            onMouseEnter={() => setActiveNode('substation')}
            onMouseLeave={() => setActiveNode(null)}
            onClick={() => setActiveNode((n) => (n === 'substation' ? null : 'substation'))}
          >
            <path
              className="iso-halo"
              d={k.haloOf(
                { x: SUBSTATION_C[0] - 22, y: SUBSTATION_C[1] - 18, w: 44, d: 20, r: 2 },
                SUBSTATION_C[2] - 1 + subLift,
                3,
                P
              )}
            />
            <Solid
              paths={k.slabOf(
                { x: SUBSTATION_C[0] - 22, y: SUBSTATION_C[1] - 18, w: 44, d: 20, r: 1.8 },
                SUBSTATION_C[2] + subLift,
                7.2,
                P,
                5,
                0.7
              )}
              tone="hi"
              lit={activeNode === 'substation' || l2CapMw > 450}
              inner={
                <Line
                  d={
                    k.coil(
                      SUBSTATION_C[0] - 14,
                      SUBSTATION_C[0] + 14,
                      [SUBSTATION_C[1] + 2, SUBSTATION_C[2] + 3.6 + subLift],
                      3.2,
                      l2CapMw > 450 ? 12 : 9,
                      'x',
                      P
                    ).front
                  }
                  tone={curtailedSolarMw > 10 ? 'red' : 'blue'}
                />
              }
            />
            {[-15, -5, 5, 15].map((dx, idx) => (
              <Solid
                key={`bushing-${idx}`}
                paths={k.cylinder(
                  SUBSTATION_C[0] + dx,
                  SUBSTATION_C[1] - 13,
                  1.5,
                  SUBSTATION_C[2] + 7.2 + subLift,
                  6.2,
                  P,
                  14
                )}
                tone="mid"
              />
            ))}

            {/* Precision 50.00 Hz / MVA Dial Gauge floating in front of the transformer */}
            <path
              className="iso-halo"
              d={k.haloOf(
                { x: dialX - dialR, y: dialY - dialR, w: dialR * 2, d: dialR * 2, r: dialR },
                SUBSTATION_C[2] - 1 + subLift,
                2.5,
                P
              )}
            />
            <Solid
              paths={k.cylinder(
                dialX,
                dialY,
                dialR,
                SUBSTATION_C[2] + subLift,
                3.2,
                P,
                36
              )}
              tone="hi"
              lit={activeNode === 'substation'}
              inner={
                <g>
                  <Line
                    d={k.knurl(
                      dialX,
                      dialY,
                      dialR,
                      SUBSTATION_C[2] + 0.4 + subLift,
                      SUBSTATION_C[2] + 2.8 + subLift,
                      28,
                      P
                    )}
                    tone="faint"
                  />
                  <Line d={dialTicks.minor} tone="lo" />
                  <Line d={dialTicks.major} tone="hi" />
                  <Line
                    d={k.ring(dialX, dialY, dialR - 1.5, dialZ, P, 32)}
                    tone={curtailedSolarMw > 10 || unservedMw > 15 ? 'red' : 'blue'}
                  />
                  <Line
                    d={k.pathOf([
                      k.iso([dialX, dialY, dialZ + 0.4], P),
                      k.iso(needleTip, P),
                    ])}
                    tone={curtailedSolarMw > 10 || unservedMw > 15 ? 'red' : 'blue'}
                  />
                </g>
              }
            />
            <Solid
              paths={k.cylinder(dialX, dialY, 2.0, dialZ, 1.3, P, 16)}
              tone="mid"
            />
          </g>

          {/* =========================================================
              NODE 03: CENTRAL TÉRMICA GAS (Bottom-Left in space)
             ========================================================= */}
          <g
            className="maquette-station-group"
            onMouseEnter={() => setActiveNode('thermal')}
            onMouseLeave={() => setActiveNode(null)}
            onClick={() => setActiveNode((n) => (n === 'thermal' ? null : 'thermal'))}
          >
            <path
              className="iso-halo"
              d={k.haloOf(
                { x: THERMAL_C[0] - 24, y: THERMAL_C[1] - 16, w: 38, d: 28, r: 2 },
                THERMAL_C[2] - 1 + thermalLift,
                3.5,
                P
              )}
            />
            <Solid
              paths={k.slabOf(
                { x: THERMAL_C[0] - 24, y: THERMAL_C[1] - 16, w: 34, d: 24, r: 1.8 },
                THERMAL_C[2] + thermalLift,
                11.5,
                P,
                5,
                0.8
              )}
              tone={thermalMw === 0 ? 'mid' : 'hi'}
              lit={activeNode === 'thermal'}
              inner={
                <Line
                  d={
                    k.sideTicks(
                      THERMAL_C[0] - 20,
                      THERMAL_C[0] + 6,
                      3.2,
                      2,
                      THERMAL_C[1] + 8,
                      THERMAL_C[2] + 9.0 + thermalLift,
                      [6.5, 6.5],
                      P,
                      'x'
                    ).minor
                  }
                  tone={thermalMw === 0 ? 'red' : 'lo'}
                />
              }
            />
            <Solid
              paths={k.slabOf(
                { x: THERMAL_C[0] + 10, y: THERMAL_C[1] - 12, w: 14, d: 18, r: 1.4 },
                THERMAL_C[2] + thermalLift,
                8.5,
                P,
                4,
                0.6
              )}
              tone="mid"
              lit={activeNode === 'thermal'}
            />
            <Solid
              paths={k.cylinder(
                THERMAL_C[0] - 14,
                THERMAL_C[1] - 4,
                3.2,
                THERMAL_C[2] + 11.5 + thermalLift,
                13.5,
                P,
                20
              )}
              tone="mid"
            />
            <Solid
              paths={k.cylinder(
                THERMAL_C[0] - 2,
                THERMAL_C[1] - 4,
                3.2,
                THERMAL_C[2] + 11.5 + thermalLift,
                11.0,
                P,
                20
              )}
              tone="mid"
            />
            <Solid
              paths={k.cylinder(
                THERMAL_C[0] - 14,
                THERMAL_C[1] + 18,
                6.2,
                THERMAL_C[2] + thermalLift,
                7.2,
                P,
                24
              )}
              tone={thermalMw === 0 ? 'mid' : 'hi'}
              lit={activeNode === 'thermal'}
            />
          </g>

          {/* =========================================================
              NODE 06: BARRIO RESIDENCIAL · CASAS (Right in space)
             ========================================================= */}
          <g
            className="maquette-station-group"
            onMouseEnter={() => setActiveNode('houses')}
            onMouseLeave={() => setActiveNode(null)}
            onClick={() => setActiveNode((n) => (n === 'houses' ? null : 'houses'))}
          >
            <Line
              d={k.pathOf([
                k.iso([HOUSES_C[0] - 24, HOUSES_C[1] - 8, 5 + housesLift], P),
                k.iso([HOUSES_C[0] + 24, HOUSES_C[1] - 8, 5 + housesLift], P),
              ])}
              tone="faint"
              dashed
            />
            <Line
              d={k.pathOf([
                k.iso([HOUSES_C[0] - 24, HOUSES_C[1] + 16, 5 + housesLift], P),
                k.iso([HOUSES_C[0] + 24, HOUSES_C[1] + 16, 5 + housesLift], P),
              ])}
              tone="faint"
              dashed
            />

            {[
              { hx: HOUSES_C[0] - 28, hy: HOUSES_C[1] - 28, hw: 15, hd: 16, wallH: 6.8, roofH: 4.8 },
              { hx: HOUSES_C[0] - 6,  hy: HOUSES_C[1] - 28, hw: 15, hd: 16, wallH: 7.5, roofH: 5.2 },
              { hx: HOUSES_C[0] + 16, hy: HOUSES_C[1] - 28, hw: 15, hd: 16, wallH: 6.4, roofH: 4.5 },
              { hx: HOUSES_C[0] - 28, hy: HOUSES_C[1] - 2,  hw: 15, hd: 16, wallH: 7.2, roofH: 5.0 },
              { hx: HOUSES_C[0] - 6,  hy: HOUSES_C[1] - 2,  hw: 15, hd: 16, wallH: 8.0, roofH: 5.4 },
              { hx: HOUSES_C[0] + 16, hy: HOUSES_C[1] - 2,  hw: 15, hd: 16, wallH: 6.8, roofH: 4.8 },
            ].map((h, idx) => (
              <FloatingHouse
                key={`house-${idx}`}
                x={h.hx}
                y={h.hy}
                w={h.hw}
                d={h.hd}
                z={HOUSES_C[2] + housesLift}
                wallH={h.wallH}
                roofH={h.roofH}
                highlighted={activeNode === 'houses'}
                powered={idx < litHousesCount}
              />
            ))}

            <Solid
              paths={k.cylinder(
                HOUSES_C[0] - 32,
                HOUSES_C[1] - 8,
                1.8,
                HOUSES_C[2] + housesLift,
                8.5,
                P,
                14
              )}
              tone="mid"
            />
            <Dots
              points={[
                k.iso([HOUSES_C[0] - 32, HOUSES_C[1] - 8, HOUSES_C[2] + 8.8 + housesLift], P),
              ]}
              size={1.2}
              tone="hi"
              pulse={unservedMw <= 15}
            />
          </g>
        </svg>

        {/* =========================================================
            BORDERLESS 4-DATUM LABELS + INLINE PARAMETER SLIDERS
           ========================================================= */}
        {nodeSpecs.map((spec) => {
          const isPerturbedThis = animStage === 'perturbing' && perturbedNode === spec.id;
          const isAiThis = animStage === 'ai_solving' && spec.id === 'battery';
          return (
            <div
              key={spec.id}
              className={`bare-node-label align-${spec.align} ${
                activeNode === spec.id || isPerturbedThis || isAiThis ? 'is-active' : ''
              }`}
              style={spec.pos}
              onMouseEnter={() => setActiveNode(spec.id)}
              onMouseLeave={() => setActiveNode(null)}
            >
              <div
                className="bare-node-title"
                onClick={() => setActiveNode((n) => (n === spec.id ? null : spec.id))}
              >
                <span
                  className="bare-node-dot"
                  style={{ backgroundColor: spec.dotColor }}
                />
                {spec.name}
              </div>

              <div className="bare-node-meta">
                <span className="bare-datum-primary">{spec.d1}</span>
                <span>{spec.d2}</span>
                <span>{spec.d3}</span>
              </div>

              {/* Minimalist borderless inline parameter slider directly under the plant */}
              {spec.slider && (
                <div
                  className="bare-inline-control"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    type="button"
                    className="bare-step-btn"
                    title="Reducir parámetro"
                    onClick={() =>
                      spec.slider!.onChange(
                        Math.max(spec.slider!.min, spec.slider!.value - spec.slider!.step)
                      )
                    }
                  >
                    −
                  </button>
                  <input
                    type="range"
                    className="bare-range-slider"
                    min={spec.slider.min}
                    max={spec.slider.max}
                    step={spec.slider.step}
                    value={spec.slider.value}
                    style={
                      {
                        '--slider-accent': spec.slider.accent,
                      } as React.CSSProperties
                    }
                    onChange={(e) => spec.slider!.onChange(Number(e.target.value))}
                  />
                  <button
                    type="button"
                    className="bare-step-btn"
                    title="Aumentar parámetro"
                    onClick={() =>
                      spec.slider!.onChange(
                        Math.min(spec.slider!.max, spec.slider!.value + spec.slider!.step)
                      )
                    }
                  >
                    +
                  </button>
                  {spec.slider.quickLabel && spec.slider.onQuickClick && (
                    <button
                      type="button"
                      className="bare-quick-trigger"
                      onClick={spec.slider.onQuickClick}
                    >
                      {spec.slider.quickLabel}
                    </button>
                  )}
                </div>
              )}

              {/* Special inline AI Agent switch directly on 04 · BATERÍA AGENTE IA */}
              {spec.id === 'battery' && (
                <div
                  className="bare-inline-control"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    type="button"
                    className="bare-quick-trigger"
                    onClick={() => {
                      const next = !aiEnabled;
                      setAiEnabled(next);
                      triggerTwoStageReaction('battery', next);
                    }}
                  >
                    {aiEnabled ? 'Pausar Agente IA' : 'Activar Agente IA'}
                  </button>
                  <span className="bare-sep">·</span>
                  <button
                    type="button"
                    className="bare-quick-trigger"
                    onClick={() => applyScenarioPreset('normal')}
                  >
                    Simular Absorción Solar
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Stage>
  );
};
