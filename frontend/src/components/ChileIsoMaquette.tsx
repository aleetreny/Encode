import React, { useMemo } from 'react';
import * as k from '../iso/iso-kit';
import {
  Dots,
  FaceText,
  IsoFigure,
  Line,
  Plate,
  Solid,
  Wire,
} from '../iso/react/draw';
import { useEased } from '../iso/react/live';
import { HourlyZoneSnapshot } from '../data/scenarioData';
import { CandidateId, NodeId, OperationMode } from '../types/grid';

interface ChileIsoMaquetteProps {
  snapshot: HourlyZoneSnapshot;
  zoneSnapshots: Record<NodeId, HourlyZoneSnapshot>;
  candidateId: CandidateId;
  mode: OperationMode;
  selectedZone: NodeId | 'all';
  onSelectZone: (zone: NodeId | 'all') => void;
  onSelectCandidate: (candidate: CandidateId) => void;
}

const W = 680;
const H = 290;

const PLATE: k.Plan = { x: -154, y: -48, w: 308, d: 96, r: 7.5 };

const P = k.fitProjection(
  [...k.boxCorners(PLATE, -16, 32)],
  W,
  H,
  { pad: 10, azimuth: 66, elevation: 33 }
);

function roundPolygon(pts: k.Plane[], radius = 2.2, steps = 4): k.Plane[] {
  const out: k.Plane[] = [];
  const n = pts.length;
  for (let i = 0; i < n; i++) {
    const prev = pts[(i - 1 + n) % n]!;
    const curr = pts[i]!;
    const next = pts[(i + 1) % n]!;
    const v1x = prev[0] - curr[0];
    const v1y = prev[1] - curr[1];
    const v2x = next[0] - curr[0];
    const v2y = next[1] - curr[1];
    const len1 = Math.hypot(v1x, v1y) || 1;
    const len2 = Math.hypot(v2x, v2y) || 1;
    const d = Math.min(radius, len1 * 0.35, len2 * 0.35);
    const pA: k.Plane = [curr[0] + (v1x / len1) * d, curr[1] + (v1y / len1) * d];
    const pB: k.Plane = [curr[0] + (v2x / len2) * d, curr[1] + (v2y / len2) * d];
    for (let s = 0; s <= steps; s++) {
      const t = s / steps;
      const u = 1 - t;
      out.push([
        u * u * pA[0] + 2 * u * t * curr[0] + t * t * pB[0],
        u * u * pA[1] + 2 * u * t * curr[1] + t * t * pB[1],
      ]);
    }
  }
  return out;
}

interface ZoneSculpt {
  id: NodeId;
  num: string;
  shortLabel: string;
  roleTitle: string;
  plainStory: string;
  originX: number;
  baseH: number;
  contour: k.Plane[];
  andesStep1: k.Plane[];
  andesStep2: k.Plane[];
  andesH1: number;
  andesH2: number;
  islandContour?: k.Plane[];
  labelPos: k.Plane;
  pinWorld: k.Point3;
}

const ZONES: ZoneSculpt[] = [
  {
    id: 'n_norte_grande',
    num: '01',
    shortLabel: 'NORTE GRANDE',
    roleTitle: '☀️ Desierto de Atacama (Generación Solar)',
    plainStory:
      'Aquí sobra energía solar gratuita al mediodía, pero está a 1.500 km de Santiago.',
    originX: -138,
    baseH: 7.2,
    contour: roundPolygon(
      [
        [-138, -22],
        [-90, -24],
        [-88, 7],
        [-114, 10],
        [-138, 6],
      ],
      2.6,
      5
    ),
    andesStep1: roundPolygon(
      [
        [-136, -34],
        [-91, -35],
        [-91, -21],
        [-136, -20],
      ],
      1.8,
      4
    ),
    andesStep2: roundPolygon(
      [
        [-133, -33],
        [-94, -34],
        [-94, -25],
        [-133, -24],
      ],
      1.4,
      4
    ),
    andesH1: 11.5,
    andesH2: 16.5,
    labelPos: [-133, 5.2],
    pinWorld: [-114, -18, 19],
  },
  {
    id: 'n_norte_chico',
    num: '02',
    shortLabel: 'NORTE CHICO',
    roleTitle: '🌬️ Paso del Norte (Sol + Viento)',
    plainStory:
      'Recibe toda la electricidad del desierto e intenta enviarla hacia Santiago por el cable L2.',
    originX: -82,
    baseH: 6.4,
    contour: roundPolygon(
      [
        [-82, -21],
        [-36, -22],
        [-34, 8],
        [-58, 6],
        [-82, 9],
      ],
      2.6,
      5
    ),
    andesStep1: roundPolygon(
      [
        [-80, -33],
        [-37, -34],
        [-37, -20],
        [-80, -19],
      ],
      1.8,
      4
    ),
    andesStep2: roundPolygon(
      [
        [-77, -32],
        [-40, -33],
        [-40, -24],
        [-77, -23],
      ],
      1.4,
      4
    ),
    andesH1: 12.0,
    andesH2: 17.5,
    labelPos: [-77, 5.5],
    pinWorld: [-59, -15, 16],
  },
  {
    id: 'n_centro',
    num: '03',
    shortLabel: 'SANTIAGO · RM',
    roleTitle: '🏙️ Gran Santiago (Donde se consume la luz)',
    plainStory:
      'Concentra la mayor parte de los hogares e industrias de Chile. Cuando cae el sol a las 18:00, su consumo se dispara.',
    originX: -28,
    baseH: 6.8,
    contour: roundPolygon(
      [
        [-28, -22],
        [20, -22],
        [22, 9],
        [-4, 11],
        [-28, 8],
      ],
      2.6,
      5
    ),
    andesStep1: roundPolygon(
      [
        [-26, -35],
        [19, -35],
        [19, -20],
        [-26, -20],
      ],
      1.8,
      4
    ),
    andesStep2: roundPolygon(
      [
        [-22, -34],
        [15, -34],
        [15, -24],
        [-22, -24],
      ],
      1.5,
      4
    ),
    andesH1: 13.0,
    andesH2: 19.5,
    labelPos: [-23, 6.8],
    pinWorld: [-4, -18, 22],
  },
  {
    id: 'n_centro_sur',
    num: '04',
    shortLabel: 'CENTRO-SUR',
    roleTitle: '🏭 Zona Centro-Sur (Maule · Biobío)',
    plainStory:
      'Zona industrial y forestal conectada entre Santiago y los embalses del Sur.',
    originX: 28,
    baseH: 6.2,
    contour: roundPolygon(
      [
        [28, -20],
        [74, -20],
        [76, 8],
        [52, 10],
        [28, 7],
      ],
      2.6,
      5
    ),
    andesStep1: roundPolygon(
      [
        [30, -32],
        [72, -32],
        [72, -19],
        [30, -19],
      ],
      1.8,
      4
    ),
    andesStep2: roundPolygon(
      [
        [34, -31],
        [68, -31],
        [68, -23],
        [34, -23],
      ],
      1.4,
      4
    ),
    andesH1: 10.5,
    andesH2: 14.5,
    labelPos: [33, 6.2],
    pinWorld: [52, -14, 16],
  },
  {
    id: 'n_sur',
    num: '05',
    shortLabel: 'SUR · AUSTRAL',
    roleTitle: '💧 Sur de Chile (Agua y Viento)',
    plainStory:
      'Produce energía limpia con ríos y viento, pero está al otro extremo del país respecto al desierto solar.',
    originX: 82,
    baseH: 5.8,
    contour: roundPolygon(
      [
        [82, -19],
        [132, -17],
        [126, 6],
        [104, 5],
        [82, 8],
      ],
      2.6,
      5
    ),
    andesStep1: roundPolygon(
      [
        [84, -30],
        [130, -28],
        [130, -16],
        [84, -17],
      ],
      1.6,
      4
    ),
    andesStep2: roundPolygon(
      [
        [88, -29],
        [124, -27],
        [124, -20],
        [88, -21],
      ],
      1.2,
      4
    ),
    andesH1: 9.0,
    andesH2: 12.5,
    islandContour: roundPolygon(
      [
        [108, 10],
        [129, 11],
        [127, 17],
        [107, 16],
      ],
      1.4,
      4
    ),
    labelPos: [87, 4.8],
    pinWorld: [108, -12, 16],
  },
];

const CORRIDORS = [
  { id: 'L1', x0: -88, x1: -82, y: -6 },
  { id: 'L2', x0: -34, x1: -28, y: -6 },
  { id: 'L3', x0: 22, x1: 28, y: -6 },
  { id: 'L4', x0: 76, x1: 82, y: -6 },
] as const;

const DIAL_X = -31;
const DIAL_Y = 21;
const DIAL_R = 11.0;
const DIAL_Z = 3.2;

const DIAL_TICKS = k.radialTicks(
  DIAL_X,
  DIAL_Y,
  DIAL_R - 2.1,
  24,
  4,
  DIAL_Z,
  [1.1, 2.2],
  P,
  -Math.PI * 0.75,
  Math.PI * 1.5
);

const RULER: k.Plan = { x: -138, y: 34, w: 274, d: 8.5, r: 1.5 };
const RULER_TICKS = k.topTicks(
  RULER.x + 8,
  RULER.x + RULER.w - 8,
  5.2,
  5,
  RULER.y,
  0.6,
  [2.5, 4.8],
  P,
  'x'
);

const NAMEPLATE: k.Plan = { x: -142, y: 17, w: 38, d: 11, r: 1.6 };

const PACIFIC_COAST_CONTOUR: k.Plane[] = roundPolygon(
  [
    [-144, 12],
    [-112, 14],
    [-82, 13],
    [-55, 11],
    [-28, 13],
    [0, 15],
    [32, 13],
    [68, 14],
    [102, 12],
    [136, 19],
    [138, 31],
    [-144, 31],
  ],
  4,
  5
);

const OCEAN_DOTS: k.Flat[] = (() => {
  const pts: k.Flat[] = [];
  for (let x = -92; x <= 98; x += 19) {
    for (let y = 17; y <= 29; y += 6) {
      if (Math.hypot(x - DIAL_X, y - DIAL_Y) < DIAL_R + 6) continue;
      pts.push(k.iso([x, y, 0], P));
    }
  }
  return pts;
})();

const BASE_FEET_POS: k.Plane[] = k.corners(PLATE, 13);

function toPct(world: k.Point3): { left: string; top: string } {
  const [sx, sy] = k.iso(world, P);
  return {
    left: `${((sx / W) * 100).toFixed(2)}%`,
    top: `${((sy / H) * 100).toFixed(2)}%`,
  };
}

export const ChileIsoMaquette: React.FC<ChileIsoMaquetteProps> = ({
  snapshot,
  zoneSnapshots,
  candidateId,
  mode,
  selectedZone,
  onSelectZone,
  onSelectCandidate,
}) => {
  const hasNorthBattery = candidateId === 'c1_battery_norte_grande';
  const hasSouthBattery = candidateId === 'c2_battery_sur';
  const isL2Uprated = candidateId === 'c3_uprate_l2';
  const isOutageActive =
    mode === 'sudden_outage' && snapshot.hourIndex >= 17;

  const northBatSeated = useEased(hasNorthBattery ? 1 : 0, 0.18);
  const southBatSeated = useEased(hasSouthBattery ? 1 : 0, 0.18);
  const breakerTrip = useEased(isOutageActive ? 1 : 0, 0.14);

  const zLift0 = useEased(selectedZone === 'n_norte_grande' ? 3.5 : 0, 0.14);
  const zLift1 = useEased(selectedZone === 'n_norte_chico' ? 3.5 : 0, 0.14);
  const zLift2 = useEased(selectedZone === 'n_centro' ? 3.5 : 0, 0.14);
  const zLift3 = useEased(selectedZone === 'n_centro_sur' ? 3.5 : 0, 0.14);
  const zLift4 = useEased(selectedZone === 'n_sur' ? 3.5 : 0, 0.14);

  const zoneLifts: Record<NodeId, number> = {
    n_norte_grande: zLift0,
    n_norte_chico: zLift1,
    n_centro: zLift2,
    n_centro_sur: zLift3,
    n_sur: zLift4,
  };

  const l2Info = snapshot.lineFlows.L2;
  const l2UtilRatio = Math.min(1, (l2Info?.utilizationPct || 0) / 100);
  const easedL2Ratio = useEased(l2UtilRatio, 0.14);
  const socRatio = useEased(
    Math.min(1, snapshot.batterySocMwh / 680),
    0.15
  );

  const needleAngle = -Math.PI * 0.75 + easedL2Ratio * (Math.PI * 1.5);
  const needleTip: k.Plane = [
    DIAL_X + Math.cos(needleAngle) * (DIAL_R - 2.6),
    DIAL_Y + Math.sin(needleAngle) * (DIAL_R - 2.6),
  ];
  const needleTail: k.Plane = [
    DIAL_X - Math.cos(needleAngle) * 2.2,
    DIAL_Y - Math.sin(needleAngle) * 2.2,
  ];

  // Clear human callouts for the 3 key spots on the maquette
  const northStatus = useMemo(() => {
    const z1 = zoneSnapshots.n_norte_grande;
    if (z1.batteryChargeMw > 5) {
      return {
        tone: 'green' as const,
        badge: '🔋 BATERÍA CARGANDO SOL',
        detail: `Guardando +${Math.round(z1.batteryChargeMw)} MW del desierto`,
      };
    }
    if (z1.batteryDischargeMw > 5) {
      return {
        tone: 'blue' as const,
        badge: '⚡ BATERÍA ENVIANDO LUZ',
        detail: `Inyectando ${Math.round(z1.batteryDischargeMw)} MW hacia Santiago`,
      };
    }
    if (z1.curtailedMw > 15) {
      return {
        tone: 'red' as const,
        badge: '❌ SOL DESPERDICIADO',
        detail: `Se pierden ${Math.round(z1.curtailedMw)} MW porque el cable se atasca`,
      };
    }
    if (z1.solarMw > 50) {
      return {
        tone: 'green' as const,
        badge: '☀️ PRODUCIENDO SOL',
        detail: `${Math.round(z1.solarMw)} MW solares activos`,
      };
    }
    return {
      tone: 'neutral' as const,
      badge: '☾ DESIERTO DE NOCHE',
      detail: hasNorthBattery
        ? `Batería lista (${Math.round(z1.batterySocMwh)} MWh)`
        : 'Sin generación solar nocturna',
    };
  }, [zoneSnapshots, hasNorthBattery]);

  const cableStatus = useMemo(() => {
    if (l2Info?.isBinding) {
      return {
        tone: 'red' as const,
        badge: '⚠️ CABLE ATASCADO (100%)',
        detail: `Tope de ${Math.round(l2Info.capacityMw)} MW lleno`,
      };
    }
    if (isL2Uprated) {
      return {
        tone: 'blue' as const,
        badge: '✅ CABLE AMPLIADO (600 MW)',
        detail: `Pasan ${Math.round(Math.abs(l2Info?.flowMw || 0))} MW sin atasco`,
      };
    }
    return {
      tone: 'blue' as const,
      badge: `🔌 CABLE AL ${Math.round(l2Info?.utilizationPct || 0)}%`,
      detail: `Flujo Norte → Santiago estable`,
    };
  }, [l2Info, isL2Uprated]);

  const santiagoStatus = useMemo(() => {
    const z3 = zoneSnapshots.n_centro;
    if (isOutageActive) {
      if (hasNorthBattery) {
        return {
          tone: 'green' as const,
          badge: '✅ SANTIAGO SALVADO',
          detail: '+98.000 hogares con luz gracias a la Batería Norte',
        };
      }
      return {
        tone: 'red' as const,
        badge: '🚨 APAGÓN EN SANTIAGO',
        detail: 'Falla central térmica y falta energía del Norte',
      };
    }
    return {
      tone: 'green' as const,
      badge: '🏙️ SANTIAGO CON LUZ (100%)',
      detail: `Demanda cubierta sin cortes`,
    };
  }, [zoneSnapshots, isOutageActive, hasNorthBattery]);

  const inspectedZoneObj = useMemo(
    () => ZONES.find((z) => z.id === selectedZone) || null,
    [selectedZone]
  );

  // Pin positions in % of the SVG box (placed in the clean margin around the maquette so 3D models are 100% visible)
  const northPinPos = toPct([-105, -36, 26]);
  const santiagoPinPos = toPct([16, -34, 26]);
  const cablePinPos = toPct([-38, 30, 0]);
  const northSocketPos = toPct([-132, 25, 0]);
  const southSocketPos = toPct([102, 26, 0]);

  return (
    <Plate
      fig="MAQUETA INTERACTIVA DE CHILE"
      title="NORTE SOLAR (IZQUIERDA)  →  CABLE CENTRAL  →  SANTIAGO Y SUR (DERECHA)"
      hint="HAZ CLIC EN LOS BOTONES SOBRE LA MAQUETA O EN CUALQUIER REGIÓN"
      readout={`HORA: ${snapshot.chileTimeLabel}`}
    >
      <div className="maquette-stage">
        {/* FLOATING CALLOUT PINS DIRECTLY ON THE MAQUETTE */}
        <div className="maquette-overlay" aria-hidden="false">
          {/* 1. NORTH CALLOUT */}
          <button
            type="button"
            className="maquette-pin"
            data-tone={northStatus.tone}
            style={{ left: northPinPos.left, top: northPinPos.top }}
            onClick={() => onSelectZone('n_norte_grande')}
          >
            <span className="maquette-pin-zone">1. NORTE (ATACAMA)</span>
            <strong className="maquette-pin-badge">{northStatus.badge}</strong>
            <span className="maquette-pin-sub">{northStatus.detail}</span>
          </button>

          {/* 2. SANTIAGO CALLOUT */}
          <button
            type="button"
            className="maquette-pin"
            data-tone={santiagoStatus.tone}
            style={{ left: santiagoPinPos.left, top: santiagoPinPos.top }}
            onClick={() => onSelectZone('n_centro')}
          >
            <span className="maquette-pin-zone">2. SANTIAGO (HOGARES)</span>
            <strong className="maquette-pin-badge">{santiagoStatus.badge}</strong>
            <span className="maquette-pin-sub">{santiagoStatus.detail}</span>
          </button>

          {/* 3. CABLE L2 CALLOUT (BOTTOM CENTER BY GAUGE) */}
          <button
            type="button"
            className="maquette-pin maquette-pin--bottom"
            data-tone={cableStatus.tone}
            style={{ left: cablePinPos.left, top: cablePinPos.top }}
            onClick={() =>
              onSelectCandidate(
                isL2Uprated ? 'c1_battery_norte_grande' : 'c3_uprate_l2'
              )
            }
          >
            <span className="maquette-pin-zone">CABLE NORTE → SANTIAGO</span>
            <strong className="maquette-pin-badge">{cableStatus.badge}</strong>
            <span className="maquette-pin-sub">{cableStatus.detail}</span>
          </button>

          {/* INTERACTIVE SOCKET BUTTON: PLUG BATTERY IN NORTH */}
          <button
            type="button"
            className="maquette-socket-btn"
            data-active={hasNorthBattery}
            data-recommended="true"
            style={{ left: northSocketPos.left, top: northSocketPos.top }}
            onClick={() =>
              onSelectCandidate(
                hasNorthBattery ? 'baseline' : 'c1_battery_norte_grande'
              )
            }
          >
            {hasNorthBattery
              ? '✓ Batería Norte instalada (Quitar)'
              : '＋ Enchufar Batería aquí (★ IA)'}
          </button>

          {/* INTERACTIVE SOCKET BUTTON: PLUG BATTERY IN SOUTH */}
          <button
            type="button"
            className="maquette-socket-btn"
            data-active={hasSouthBattery}
            style={{ left: southSocketPos.left, top: southSocketPos.top }}
            onClick={() =>
              onSelectCandidate(
                hasSouthBattery ? 'baseline' : 'c2_battery_sur'
              )
            }
          >
            {hasSouthBattery
              ? '✓ Batería Sur instalada (Quitar)'
              : '＋ Probar Batería en el Sur'}
          </button>
        </div>

        <IsoFigure
          width={W}
          height={H}
          label="Maqueta isométrica interactiva de Chile"
        >
          {/* 1. BASEPLATE HALO & MACHINED FEET */}
          <path className="iso-halo" d={k.haloOf(PLATE, -16, 11, P)} />
          {BASE_FEET_POS.map(([fx, fy], idx) => (
            <g key={`foot-${idx}`}>
              <Solid paths={k.cylinder(fx, fy, 6.2, -16, 1.5, P, 24)} tone="lo" crease="none" />
              <Solid paths={k.cylinder(fx, fy, 4.8, -14.5, 3.5, P, 24)} tone="mid" crease="none" />
            </g>
          ))}

          {/* 2. MAIN MACHINED BASE SLAB */}
          <Solid
            paths={k.slabOf(PLATE, -11, 11, P, 8, 1.5)}
            tone="mid"
            crease="faint"
            inner={<Line d={k.sideSeam(PLATE, -5.5, P, 8)} tone="faint" />}
          />

          {/* Perimeter recessed groove & corner screws */}
          <Line d={k.planOutline(k.insetPlan(PLATE, 4.5), 0, P)} tone="lo" />
          {k.corners(PLATE, 9.5).map(([sx, sy], idx) => (
            <g key={`screw-${idx}`}>
              <Line d={k.ring(sx, sy, 2.1, 0, P, 16)} tone="lo" />
              <Dots points={[k.iso([sx, sy, 0], P)]} size={0.5} tone="mid" />
            </g>
          ))}

          {/* Etched Pacific Ocean coastal bathymetry contour & subtle dot grid */}
          <Line d={k.onTop(PACIFIC_COAST_CONTOUR, 0, P, true)} tone="faint" />
          <Dots points={OCEAN_DOTS} size={0.38} tone="faint" />
          <FaceText
            transform={k.topMatrix([52, 27.5], 0, P)}
            size={2.8}
            tone="lo"
          >
            OCÉANO PACÍFICO
          </FaceText>

          {/* 3. CONTINUOUS PRECISION GUIDE RAILS UNDER CHILE'S SPINE */}
          {[-12, 2].map((ry, idx) => (
            <Solid
              key={`rail-${idx}`}
              paths={k.slabOf({ x: -144, y: ry, w: 284, d: 3.0, r: 0.8 }, 0, 1.8, P, 3, 0.25)}
              tone="mid"
              crease="faint"
            />
          ))}

          {/* 4. STEPPED CORDILLERA DE LOS ANDES TOPOGRAPHIC SPINE (BACK EDGE) */}
          {ZONES.map((z, idx) => (
            <g key={`andes-${z.id}`}>
              <Solid
                paths={k.extrude(z.andesStep1, 0, z.andesH1, P, { convex: false, bevel: 0.6 })}
                tone="lo"
                crease="faint"
              />
              <Solid
                paths={k.extrude(z.andesStep2, z.andesH1, z.andesH2 - z.andesH1, P, {
                  convex: false,
                  bevel: 0.5,
                })}
                tone="lo"
                crease="faint"
              />
              {idx === 2 ? (
                <FaceText
                  transform={k.topMatrix([-18, -33], z.andesH2 + 0.2, P)}
                  size={2.6}
                  tone="mid"
                >
                  CORDILLERA DE LOS ANDES
                </FaceText>
              ) : null}
            </g>
          ))}

          {/* 5. INTER-ZONE TRANSMISSION BRIDGES */}
          {CORRIDORS.map((cor) => {
            const lData = snapshot.lineFlows[cor.id];
            const isBinding = lData ? lData.isBinding : false;
            const conduitHeight = cor.id === 'L2' && isL2Uprated ? 3.0 : 2.0;

            return (
              <g key={`corridor-base-${cor.id}`}>
                <Solid
                  paths={k.slabOf(
                    { x: cor.x0 - 1.5, y: cor.y - 2.6, w: cor.x1 - cor.x0 + 3, d: 5.2, r: 0.8 },
                    1.8,
                    conduitHeight,
                    P,
                    3,
                    0.3
                  )}
                  tone={isBinding ? 'hi' : 'mid'}
                  lit={cor.id === 'L2' && isL2Uprated}
                />
              </g>
            );
          })}

          {/* 6. FIVE SCULPTED CHILE REGIONAL TERRACES & 3D POWER INSTRUMENTS */}
          {ZONES.map((zone) => {
            const zSnap = zoneSnapshots[zone.id];
            const lift = zoneLifts[zone.id];
            const isSelected = selectedZone === zone.id;
            const topZ = zone.baseH;
            const ox = zone.originX;

            const isProblemZone =
              (zone.id === 'n_norte_grande' && zSnap.curtailedMw > 15) ||
              (zone.id === 'n_centro' && zSnap.unservedMw > 1);

            return (
              <g
                key={zone.id}
                transform={k.translateAlong(P, [0, 0, lift])}
                style={{ cursor: 'pointer' }}
                onClick={() =>
                  onSelectZone(selectedZone === zone.id ? 'all' : zone.id)
                }
              >
                {/* Sculpted Regional Landmass Block */}
                <Solid
                  paths={k.extrude(zone.contour, 1.8, topZ - 1.8, P, {
                    convex: false,
                    bevel: 0.85,
                  })}
                  tone={isSelected ? 'hi' : 'mid'}
                  lit={isSelected}
                />

                {/* Chiloé Island in Sur */}
                {zone.islandContour && (
                  <Solid
                    paths={k.extrude(zone.islandContour, 0, 3.8, P, {
                      convex: false,
                      bevel: 0.45,
                    })}
                    tone={isSelected ? 'hi' : 'mid'}
                  />
                )}

                {/* Alert outline when problem is happening in this region */}
                {(isSelected || isProblemZone) && (
                  <Line
                    d={k.onTop(zone.contour, topZ + 0.08, P, true)}
                    tone={isProblemZone ? 'red' : 'lit'}
                  />
                )}

                {/* Engraved Regional Name */}
                <FaceText
                  transform={k.topMatrix(zone.labelPos, topZ + 0.1, P)}
                  size={3.1}
                  tone="hi"
                >
                  {`${zone.num} ${zone.shortLabel}`}
                </FaceText>

                {/* ZONE 1: NORTE GRANDE (SOLAR + PLUG-IN NORTH BATTERY) */}
                {zone.id === 'n_norte_grande' && (
                  <g key="assets-z1">
                    {[0, 1, 2].map((idx) => {
                      const sx = ox + 3 + idx * 8.2;
                      const sy = -19;
                      const panelPlan: k.Plan = { x: sx, y: sy, w: 7.0, d: 11, r: 0.8 };
                      const solarActive = zSnap.solarMw > 25;
                      return (
                        <g key={`pv-z1-${idx}`}>
                          <Solid
                            paths={k.slabOf(panelPlan, topZ, 1.8 + idx * 0.4, P, 3, 0.2)}
                            tone={solarActive ? 'hi' : 'mid'}
                            inner={
                              <Line
                                d={
                                  k.lineOnTop(
                                    [sx + 1, sy + 3.6],
                                    [sx + 6.0, sy + 3.6],
                                    topZ + 1.8 + idx * 0.4,
                                    P
                                  ) +
                                  k.lineOnTop(
                                    [sx + 1, sy + 7.2],
                                    [sx + 6.0, sy + 7.2],
                                    topZ + 1.8 + idx * 0.4,
                                    P
                                  )
                                }
                                tone={solarActive ? 'green' : 'faint'}
                              />
                            }
                          />
                        </g>
                      );
                    })}

                    <Solid
                      paths={k.cylinder(ox + 38, -14, 4.0, topZ, 6.2, P, 24, 0.4)}
                      tone="mid"
                    />

                    {/* Curtailment Plume when Solar is Wasted */}
                    {zSnap.curtailedMw > 15 && (
                      <g>
                        <Line
                          d={k.rise([ox + 15, -13], topZ + 3, topZ + 13, P)}
                          tone="red"
                          dashed
                          flow
                        />
                        <Line
                          d={k.ring(ox + 15, -13, 4.2, topZ + 13, P, 20)}
                          tone="red"
                        />
                      </g>
                    )}

                    {/* North Battery Mounting Bay */}
                    <Line
                      d={k.planOutline(
                        { x: ox + 22, y: -5.5, w: 19, d: 10.5, r: 1.5 },
                        topZ,
                        P,
                        4
                      )}
                      tone={hasNorthBattery ? 'green' : 'faint'}
                      dashed={!hasNorthBattery}
                    />

                    {/* ★ PLUG-IN NORTH BATTERY MODULE */}
                    {northBatSeated > 0.02 && (
                      <g
                        transform={k.translateAlong(P, [0, 0, (1 - northBatSeated) * 16])}
                        opacity={Math.min(1, northBatSeated * 1.2)}
                      >
                        <Solid
                          paths={k.slabOf(
                            { x: ox + 23, y: -4.8, w: 17, d: 9.2, r: 1.4 },
                            topZ,
                            7.2,
                            P,
                            4,
                            0.55
                          )}
                          tone="hi"
                          lit
                        />
                        {[0, 1, 2].map((cIdx) => (
                          <Solid
                            key={`cell-${cIdx}`}
                            paths={k.cylinder(
                              ox + 26.5 + cIdx * 5,
                              -0.2,
                              1.7,
                              topZ + 7.2,
                              1.6 + socRatio * 3.4,
                              P,
                              20,
                              0.2
                            )}
                            tone="hi"
                            lit
                          />
                        ))}
                        <Line
                          d={k.planOutline(
                            { x: ox + 22.2, y: -5.5, w: 18.6, d: 10.5, r: 1.6 },
                            topZ + 0.2,
                            P,
                            4
                          )}
                          tone={
                            zSnap.batteryChargeMw > 5
                              ? 'green'
                              : zSnap.batteryDischargeMw > 5
                              ? 'blue'
                              : 'lit'
                          }
                        />
                      </g>
                    )}
                  </g>
                )}

                {/* ZONE 2: NORTE CHICO (SOLAR + WIND) */}
                {zone.id === 'n_norte_chico' && (
                  <g key="assets-z2">
                    {[0, 1].map((idx) => {
                      const sx = ox + 4 + idx * 8.8;
                      const sy = -17;
                      const solarActive = zSnap.solarMw > 15;
                      return (
                        <Solid
                          key={`pv-z2-${idx}`}
                          paths={k.slabOf({ x: sx, y: sy, w: 7.2, d: 13, r: 0.8 }, topZ, 2.0, P, 3, 0.2)}
                          tone={solarActive ? 'hi' : 'mid'}
                        />
                      );
                    })}

                    {[0, 1].map((wIdx) => {
                      const wx = ox + 27 + wIdx * 9.5;
                      const wy = -11 + wIdx * 6.5;
                      const towerH = 13.5 - wIdx * 2;
                      const rotorPhase = snapshot.hourIndex * 0.65 + wIdx * 1.1;
                      return (
                        <g key={`wind-z2-${wIdx}`}>
                          <Solid
                            paths={k.cylinder(wx, wy, 2.6, topZ, 1.6, P, 20)}
                            tone="mid"
                            crease="none"
                          />
                          <Solid
                            paths={k.cylinder(wx, wy, 1.2, topZ + 1.6, towerH, P, 18)}
                            tone="hi"
                            crease="none"
                          />
                          <Solid
                            paths={k.slabOf(
                              { x: wx - 2.0, y: wy - 1.5, w: 4.0, d: 3.0, r: 0.7 },
                              topZ + 1.6 + towerH,
                              2.2,
                              P,
                              3
                            )}
                            tone="hi"
                          />
                          {[0, 1, 2].map((bIdx) => {
                            const ang = rotorPhase + (bIdx * Math.PI * 2) / 3;
                            const tipY = wy + Math.cos(ang) * 6.2;
                            const tipZ = topZ + 2.7 + towerH + Math.sin(ang) * 6.2;
                            return (
                              <Line
                                key={`blade-${bIdx}`}
                                d={k.segment(
                                  [wx, wy + 1.5, topZ + 2.7 + towerH],
                                  [wx + 1.1, tipY, tipZ],
                                  P
                                )}
                                tone={zSnap.windMw > 10 ? 'green' : 'hi'}
                              />
                            );
                          })}
                        </g>
                      );
                    })}
                  </g>
                )}

                {/* ZONE 3: SANTIAGO (METROPOLITAN TOWERS + THERMAL BREAKER) */}
                {zone.id === 'n_centro' && (
                  <g key="assets-z3">
                    {[
                      { dx: 3, dy: -19, w: 8.5, d: 8.5, h: 16.0 },
                      { dx: 13.5, dy: -19, w: 8.0, d: 8.0, h: 12.0 },
                      { dx: 3, dy: -9, w: 8.5, d: 8.5, h: 10.5 },
                      { dx: 13.5, dy: -9, w: 8.0, d: 8.5, h: 8.2 },
                    ].map((b, bIdx) => {
                      const bx = ox + b.dx;
                      const by = b.dy;
                      const hasBlackout = zSnap.unservedMw > 1 && !hasNorthBattery;
                      return (
                        <Solid
                          key={`scl-bldg-${bIdx}`}
                          paths={k.slabOf({ x: bx, y: by, w: b.w, d: b.d, r: 1 }, topZ, b.h, P, 4, 0.45)}
                          tone={hasBlackout ? 'mid' : 'hi'}
                          lit={!hasBlackout && isOutageActive && bIdx === 0}
                        />
                      );
                    })}

                    <g>
                      <Solid
                        paths={k.slabOf(
                          { x: ox + 27, y: -18, w: 15, d: 11, r: 1.4 },
                          topZ,
                          6.8,
                          P,
                          4,
                          0.5
                        )}
                        tone={isOutageActive ? 'mid' : 'hi'}
                      />
                      <g transform={k.translateAlong(P, [0, 0, breakerTrip * 4.5])}>
                        <Solid
                          paths={k.cylinder(ox + 34.5, -12.5, 3.0, topZ + 6.8, 3.4, P, 24, 0.3)}
                          tone="hi"
                          lit={isOutageActive}
                        />
                      </g>
                      {isOutageActive && (
                        <Line
                          d={k.ring(ox + 34.5, -12.5, 5.8, topZ + 7.0, P, 24)}
                          tone="red"
                        />
                      )}
                    </g>
                  </g>
                )}

                {/* ZONE 4: CENTRO-SUR */}
                {zone.id === 'n_centro_sur' && (
                  <g key="assets-z4">
                    <Solid
                      paths={k.slabOf(
                        { x: ox + 3, y: -17, w: 17, d: 14, r: 1.4 },
                        topZ,
                        8.0,
                        P,
                        4,
                        0.55
                      )}
                      tone="mid"
                    />
                    {[0, 1].map((sIdx) => (
                      <Solid
                        key={`stack-${sIdx}`}
                        paths={k.cylinder(
                          ox + 8 + sIdx * 6.5,
                          -10,
                          2.2,
                          topZ + 8.0,
                          7.5,
                          P,
                          20,
                          0.2
                        )}
                        tone="hi"
                      />
                    ))}
                    <Solid
                      paths={k.slabOf(
                        { x: ox + 23, y: -14, w: 10.5, d: 11, r: 1.2 },
                        topZ,
                        5.0,
                        P,
                        3,
                        0.4
                      )}
                      tone="mid"
                    />
                  </g>
                )}

                {/* ZONE 5: SUR (HYDRO + WIND + OPTIONAL SOUTH BATTERY) */}
                {zone.id === 'n_sur' && (
                  <g key="assets-z5">
                    <Line
                      d={k.planOutline(
                        { x: ox + 3, y: -17.5, w: 15, d: 10, r: 1.4 },
                        topZ + 0.1,
                        P,
                        4
                      )}
                      tone="blue"
                    />
                    <Solid
                      paths={k.slabOf(
                        { x: ox + 3, y: -7.5, w: 15, d: 6.0, r: 1.2 },
                        topZ,
                        7.5,
                        P,
                        4,
                        0.5
                      )}
                      tone="hi"
                    />
                    <Solid
                      paths={k.cylinder(ox + 29, -11, 1.3, topZ, 12.5, P, 18)}
                      tone="hi"
                      crease="none"
                    />
                    <Solid
                      paths={k.slabOf(
                        { x: ox + 27, y: -12.5, w: 3.8, d: 2.8, r: 0.6 },
                        topZ + 12.5,
                        2.0,
                        P,
                        3
                      )}
                      tone="hi"
                    />
                    {[0, 1, 2].map((bIdx) => {
                      const ang = snapshot.hourIndex * 0.6 + (bIdx * Math.PI * 2) / 3;
                      return (
                        <Line
                          key={`sur-blade-${bIdx}`}
                          d={k.segment(
                            [ox + 29, -9.5, topZ + 13.5],
                            [
                              ox + 30,
                              -9.5 + Math.cos(ang) * 5.8,
                              topZ + 13.5 + Math.sin(ang) * 5.8,
                            ],
                            P
                          )}
                          tone="green"
                        />
                      );
                    })}

                    {/* South Battery Mounting Outline */}
                    <Line
                      d={k.planOutline(
                        { x: ox + 20.5, y: -5.8, w: 16, d: 9.0, r: 1.4 },
                        topZ,
                        P,
                        4
                      )}
                      tone={hasSouthBattery ? 'blue' : 'faint'}
                      dashed={!hasSouthBattery}
                    />

                    {southBatSeated > 0.02 && (
                      <g
                        transform={k.translateAlong(P, [0, 0, (1 - southBatSeated) * 15])}
                        opacity={Math.min(1, southBatSeated * 1.2)}
                      >
                        <Solid
                          paths={k.slabOf(
                            { x: ox + 21, y: -5.5, w: 15, d: 8.5, r: 1.4 },
                            topZ,
                            6.4,
                            P,
                            4,
                            0.5
                          )}
                          tone="hi"
                          lit
                        />
                      </g>
                    )}
                  </g>
                )}
              </g>
            );
          })}

          {/* 6B. HIGH-VOLTAGE OVERHEAD TRANSMISSION CONDUITS & DIRECTIONAL FLOW WIRES (L1-L4) */}
          {CORRIDORS.map((cor) => {
            const lData = snapshot.lineFlows[cor.id];
            const flowMw = lData ? lData.flowMw : 0;
            const absFlow = Math.abs(flowMw);
            const isBinding = lData ? lData.isBinding : false;
            const isFlowing = absFlow > 5;

            let flowTone: k.LineTone = 'lo';
            if (isBinding) {
              flowTone = 'red';
            } else if (cor.id === 'L2' && isL2Uprated && absFlow > 380) {
              flowTone = 'blue';
            } else if (cor.id === 'L1' && snapshot.solarMw > 150) {
              flowTone = 'green';
            } else if (absFlow > 15) {
              flowTone = 'blue';
            }

            const zWire = 8.4;
            const xLeft = cor.x0 - 2.2;
            const xRight = cor.x1 + 2.2;
            const pStart = k.iso([flowMw >= 0 ? xLeft : xRight, cor.y, zWire], P);
            const pEnd = k.iso([flowMw >= 0 ? xRight : xLeft, cor.y, zWire], P);

            return (
              <g key={`corridor-top-${cor.id}`}>
                <Solid
                  paths={k.cylinder(xLeft, cor.y, 1.7, 7.2, 1.4, P, 18)}
                  tone="mid"
                  crease="none"
                />
                <Solid
                  paths={k.cylinder(xRight, cor.y, 1.7, 7.2, 1.4, P, 18)}
                  tone="mid"
                  crease="none"
                />
                <Wire
                  from={pStart}
                  to={pEnd}
                  tone={flowTone}
                  flow={isFlowing}
                  ends="both"
                  size={1.3}
                />
              </g>
            );
          })}

          {/* 7. FRONT INSTRUMENT DECK: L2 BOTTLENECK DIAL GAUGE + RULER + NAMEPLATE */}
          <Solid paths={k.slabOf(NAMEPLATE, 0, 0.7, P, 3)} tone="lo" crease="none" />
          <Line d={k.planOutline(k.insetPlan(NAMEPLATE, 1.2), 0.7, P, 3)} tone="faint" />
          <FaceText
            transform={k.topMatrix([NAMEPLATE.x + 3.5, NAMEPLATE.y + 7.2], 0.7, P)}
            size={3.0}
            tone="hi"
          >
            CHILE · SEN
          </FaceText>

          {/* Precision Dial Gauge for L2 Corridor */}
          <g key="l2-dial-gauge">
            <Solid
              paths={k.slabOf({ x: DIAL_X - 2.2, y: 10, w: 4.4, d: 5, r: 0.8 }, 0, 2.0, P, 3)}
              tone="mid"
            />
            <Solid
              paths={k.cylinder(DIAL_X, DIAL_Y, DIAL_R, 0, DIAL_Z, P, 48, 0.6)}
              tone="hi"
              crease="lo"
              lit={l2Info?.isBinding}
              inner={
                <Line
                  d={
                    k.knurl(DIAL_X, DIAL_Y, DIAL_R, 1.4, DIAL_Z, 52, P, 0.3) +
                    k.sideArc(DIAL_X, DIAL_Y, DIAL_R, 1.4, P, 32)
                  }
                  tone="lo"
                />
              }
            />
            <Line d={k.ring(DIAL_X, DIAL_Y, DIAL_R - 1.5, DIAL_Z, P, 48)} tone="lo" />
            <Line d={DIAL_TICKS.minor} tone="lo" />
            <Line d={DIAL_TICKS.major} tone="mid" />
            <Line
              d={k.lineOnTop(needleTail, needleTip, DIAL_Z + 0.2, P)}
              tone={l2Info?.isBinding ? 'red' : isL2Uprated ? 'blue' : 'lit'}
            />
            <Line d={k.ring(DIAL_X, DIAL_Y, 1.3, DIAL_Z + 0.2, P, 16)} tone="hi" />
          </g>

          {/* Front Coastal Latitude Ruler Strip */}
          <Solid paths={k.slabOf(RULER, 0, 0.6, P, 3)} tone="lo" crease="none" />
          <Line d={RULER_TICKS.minor} tone="lo" />
          <Line d={RULER_TICKS.major} tone="mid" />
        </IsoFigure>

        {/* IF USER CLICKS A ZONE ON THE MAQUETTE, SHOW A SIMPLE 1-LINE POPOVER CARD */}
        {inspectedZoneObj && (
          <div className="maquette-zone-toast">
            <div>
              <strong>{inspectedZoneObj.roleTitle}</strong>
              <p>{inspectedZoneObj.plainStory}</p>
            </div>
            <button
              type="button"
              className="maquette-toast-close"
              onClick={() => onSelectZone('all')}
            >
              Cerrar ×
            </button>
          </div>
        )}
      </div>
    </Plate>
  );
};
