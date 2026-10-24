import * as React from 'react';
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
import {
  CandidateId,
  LineId,
  NodeId,
  OperationMode,
} from '../types/grid';
import { HourlyZoneSnapshot } from '../data/scenarioData';

interface ChileIsoMaquetteProps {
  snapshot: HourlyZoneSnapshot;
  zoneSnapshots: Record<NodeId, HourlyZoneSnapshot>;
  candidateId: CandidateId;
  mode: OperationMode;
  selectedZone: NodeId | 'all';
  onSelectZone: (zone: NodeId | 'all') => void;
}

const W = 680;
const H = 290;

const PLATE: k.Plan = { x: -154, y: -48, w: 308, d: 96, r: 7.5 };
const RULER: k.Plan = { x: -138, y: 34, w: 276, d: 7, r: 1.2 };
const NAMEPLATE: k.Plan = { x: -146, y: 19, w: 35, d: 11, r: 1.5 };

// Fit isometric camera to the maquette envelope (azimuth 66° fills the full card width cleanly)
const P = k.fitProjection(
  [
    ...k.boxCorners(PLATE, -16, 32),
  ],
  W,
  H,
  { pad: 10, azimuth: 66, elevation: 33 }
);

// Helper to round polygon vertices for CNC-machined architectural contour slabs
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
      // Quadratic Bezier corner rounding
      const u = 1 - t;
      out.push([
        u * u * pA[0] + 2 * u * t * curr[0] + t * t * pB[0],
        u * u * pA[1] + 2 * u * t * curr[1] + t * t * pB[1],
      ]);
    }
  }
  return out;
}

interface ZoneConfig {
  id: NodeId;
  num: string;
  shortLabel: string;
  latLabel: string;
  originX: number;
  contour: k.Plane[];
  andesStep1: k.Plane[];
  andesStep2: k.Plane[];
  height: number;
  andesH1: number;
  andesH2: number;
  labelPos: k.Plane;
}

// Sculpted 5-zone relief silhouette of Chile (North at -X to South at +X, Andes at -Y, Pacific Coast at +Y)
const ZONES: ZoneConfig[] = [
  {
    id: 'n_norte_grande',
    num: '01',
    shortLabel: 'NORTE GRANDE',
    latLabel: '20°S · ATACAMA',
    originX: -140,
    // Wide Altiplano & Mejillones peninsula contour
    contour: roundPolygon([
      [-142, -26],
      [-92, -25],
      [-90, 9],
      [-104, 13], // Mejillones / Antofagasta peninsula
      [-118, 9],
      [-136, 11],
      [-142, -4],
    ]),
    andesStep1: roundPolygon([
      [-141, -40],
      [-92, -39],
      [-92, -24],
      [-141, -25],
    ]),
    andesStep2: roundPolygon([
      [-136, -38],
      [-97, -37],
      [-97, -27],
      [-136, -28],
    ]),
    height: 6.2,
    andesH1: 13,
    andesH2: 22,
    labelPos: [-136, 7.5],
  },
  {
    id: 'n_norte_chico',
    num: '02',
    shortLabel: 'NORTE CHICO',
    latLabel: '29°S · COQUIMBO',
    originX: -80,
    // Narrower transverse valleys & Punta Lengua de Vaca / Coquimbo bay
    contour: roundPolygon([
      [-82, -24],
      [-36, -23],
      [-35, 8],
      [-52, 12],
      [-68, 7],
      [-82, 8],
    ]),
    andesStep1: roundPolygon([
      [-81, -38],
      [-36, -38],
      [-36, -23],
      [-81, -24],
    ]),
    andesStep2: roundPolygon([
      [-76, -36],
      [-41, -36],
      [-41, -26],
      [-76, -27],
    ]),
    height: 5.6,
    andesH1: 12,
    andesH2: 20,
    labelPos: [-77, 6.2],
  },
  {
    id: 'n_centro',
    num: '03',
    shortLabel: 'SANTIAGO · RM',
    latLabel: '33°S · CENTRO',
    originX: -24,
    // Central Valley + Valparaíso / San Antonio coastal curve + towering Aconcagua/Tupungato Andes
    contour: roundPolygon([
      [-26, -24],
      [26, -24],
      [26, 10],
      [4, 13], // Valparaíso / San Antonio coast
      [-14, 9],
      [-26, 9],
    ]),
    andesStep1: roundPolygon([
      [-25, -41],
      [25, -40],
      [25, -24],
      [-25, -24],
    ]),
    andesStep2: roundPolygon([
      [-20, -39],
      [20, -38],
      [20, -27],
      [-20, -27],
    ]),
    height: 6.0,
    andesH1: 16,
    andesH2: 27,
    labelPos: [-21, 7.8],
  },
  {
    id: 'n_centro_sur',
    num: '04',
    shortLabel: 'CENTRO-SUR',
    latLabel: '37°S · BIOBÍO',
    originX: 36,
    // Maule & Biobío + Arauco Peninsula jutting toward the Pacific
    contour: roundPolygon([
      [34, -22],
      [78, -21],
      [78, 13], // Arauco Peninsula
      [60, 14],
      [48, 9],
      [34, 9],
    ]),
    andesStep1: roundPolygon([
      [35, -36],
      [77, -35],
      [77, -21],
      [35, -22],
    ]),
    andesStep2: roundPolygon([
      [40, -34],
      [72, -33],
      [72, -24],
      [40, -25],
    ]),
    height: 5.2,
    andesH1: 10,
    andesH2: 17,
    labelPos: [38, 8.2],
  },
  {
    id: 'n_sur',
    num: '05',
    shortLabel: 'SUR · AUSTRAL',
    latLabel: '41°S · LOS LAGOS',
    originX: 88,
    // Lake District & Seno de Reloncaví (with separate Isla de Chiloé slab off the coast)
    contour: roundPolygon([
      [86, -20],
      [136, -18],
      [136, 4],
      [114, 5], // Gulf of Ancud indentation
      [104, 10],
      [86, 10],
    ]),
    andesStep1: roundPolygon([
      [87, -33],
      [135, -31],
      [135, -18],
      [87, -20],
    ]),
    andesStep2: roundPolygon([
      [93, -31],
      [129, -29],
      [129, -21],
      [93, -22],
    ]),
    height: 4.8,
    andesH1: 8,
    andesH2: 13,
    labelPos: [90, 6.8],
  },
];

// Sculpted Isla Grande de Chiloé + Austral islands off Zone 5
const CHILOE_ISLAND = roundPolygon([
  [114, 8.5],
  [135, 7.5],
  [136, 15.5],
  [115, 16.0],
], 1.6, 3);

// Etched Pacific Ocean coastal bathymetry contour line on the baseplate
const PACIFIC_COAST_CONTOUR = roundPolygon([
  [-146, -28],
  [-146, 14],
  [-104, 17],
  [-65, 13],
  [4, 17],
  [65, 18],
  [140, 19],
  [142, -22],
], 5, 5);

const CORRIDORS: Array<{
  id: LineId;
  x0: number;
  x1: number;
  y: number;
}> = [
  { id: 'L1', x0: -90, x1: -82, y: -5 },
  { id: 'L2', x0: -35, x1: -26, y: -5 },
  { id: 'L3', x0: 26, x1: 34, y: -5 },
  { id: 'L4', x0: 78, x1: 86, y: -5 },
];

// Precompute static base geometry once at module load
const BASE_FEET_POS: k.Plane[] = (
  [
    ...k.corners(PLATE, 20),
    [0, PLATE.y + 20] as k.Plane,
    [0, PLATE.y + PLATE.d - 20] as k.Plane,
  ] as k.Plane[]
).sort((a, b) => k.depthOf([a[0], a[1], -15], P) - k.depthOf([b[0], b[1], -15], P));

const RULER_TICKS = k.topTicks(
  RULER.x + 6,
  RULER.x + RULER.w - 6,
  4,
  5,
  RULER.y + 0.8,
  0.6,
  [1.8, 3.3],
  P,
  'x'
);

// Subtle Pacific Ocean dot grid on the front coastal shelf
const OCEAN_DOTS = k.dotGrid(-136, 19, 34, 3, 8, 0, P);

// L2 Bottleneck Dial Gauge center (mounted on front deck directly below L2)
const DIAL_X = -30.5;
const DIAL_Y = 23.5;
const DIAL_R = 10.2;
const DIAL_Z = 4.5;
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

export const ChileIsoMaquette: React.FC<ChileIsoMaquetteProps> = ({
  snapshot,
  zoneSnapshots,
  candidateId,
  mode,
  selectedZone,
  onSelectZone,
}) => {
  const [hoveredZone, setHoveredZone] = React.useState<NodeId | null>(null);

  const hasNorthBattery = candidateId === 'c1_battery_norte_grande';
  const hasSouthBattery = candidateId === 'c2_battery_sur';
  const isL2Uprated = candidateId === 'c3_uprate_l2';

  // Smooth eased values for physical benchtop motion
  const northBatSeated = useEased(hasNorthBattery ? 1 : 0, 0.18);
  const southBatSeated = useEased(hasSouthBattery ? 1 : 0, 0.18);

  const socRatio = useEased(
    snapshot.batteryCapacityMwh > 0
      ? Math.min(1, Math.max(0.05, snapshot.batterySocMwh / snapshot.batteryCapacityMwh))
      : 0.2,
    0.15
  );

  const l2Info = snapshot.lineFlows.L2;
  const l2Ratio = useEased(
    l2Info ? Math.min(1.05, Math.abs(l2Info.flowMw) / l2Info.capacityMw) : 0,
    0.14
  );

  const isOutageActive = mode === 'sudden_outage' && snapshot.hourIndex >= 17;
  const breakerTrip = useEased(isOutageActive ? 1 : 0, 0.14);

  const liftZ1 = useEased(
    selectedZone === 'n_norte_grande' ? 3.2 : hoveredZone === 'n_norte_grande' ? 1.5 : 0,
    0.12
  );
  const liftZ2 = useEased(
    selectedZone === 'n_norte_chico' ? 3.2 : hoveredZone === 'n_norte_chico' ? 1.5 : 0,
    0.12
  );
  const liftZ3 = useEased(
    selectedZone === 'n_centro' ? 3.2 : hoveredZone === 'n_centro' ? 1.5 : 0,
    0.12
  );
  const liftZ4 = useEased(
    selectedZone === 'n_centro_sur' ? 3.2 : hoveredZone === 'n_centro_sur' ? 1.5 : 0,
    0.12
  );
  const liftZ5 = useEased(
    selectedZone === 'n_sur' ? 3.2 : hoveredZone === 'n_sur' ? 1.5 : 0,
    0.12
  );
  const zoneLifts: Record<NodeId, number> = {
    n_norte_grande: liftZ1,
    n_norte_chico: liftZ2,
    n_centro: liftZ3,
    n_centro_sur: liftZ4,
    n_sur: liftZ5,
  };

  // Dial needle coordinates
  const needleAngle = -Math.PI * 0.75 + l2Ratio * Math.PI * 1.5;
  const needleTip: k.Plane = [
    DIAL_X + Math.sin(needleAngle) * (DIAL_R - 2.5),
    DIAL_Y - Math.cos(needleAngle) * (DIAL_R - 2.5),
  ];
  const needleTail: k.Plane = [
    DIAL_X - Math.sin(needleAngle) * 1.8,
    DIAL_Y + Math.cos(needleAngle) * 1.8,
  ];

  // Live corner readout string
  const activeZoneObj = ZONES.find(
    (z) => z.id === (hoveredZone || (selectedZone !== 'all' ? selectedZone : null))
  );
  const activeSnap = activeZoneObj ? zoneSnapshots[activeZoneObj.id] : snapshot;
  const readoutText = activeZoneObj
    ? `${activeZoneObj.shortLabel} · ${snapshot.chileTimeLabel} · GEN ${Math.round(activeSnap.totalGenerationMw)} MW · DEM ${Math.round(activeSnap.demandMw)} MW`
    : `SEN CHILE · ${snapshot.chileTimeLabel} · SOL ${Math.round(snapshot.solarMw)} MW · L2 ${Math.round(Math.abs(l2Info?.flowMw || 0))}/${Math.round(l2Info?.capacityMw || 400)} MW`;

  // Dynamic plain-Spanish caption
  const dynamicCaption = React.useMemo(() => {
    if (isOutageActive) {
      if (snapshot.unservedMw > 1) {
        return `⚡ Crisis 18:00 en Santiago: Falla térmica de −270 MW en Centro. Sin batería en el Norte, hay ${Math.round(snapshot.unservedMw)} MW de apagón urbano.`;
      }
      return `⚡ Crisis 18:00 superada: La Batería Norte (C1) inyecta energía almacenada por L1→L2 y protege a Santiago (~98,000 hogares reconectados).`;
    }
    if (snapshot.curtailedMw > 30) {
      return `☀️ Mediodía solar (${snapshot.chileTimeLabel}): El corredor L2 hacia Santiago está al ${Math.round(l2Info?.utilizationPct || 100)}% (${Math.round(Math.abs(l2Info?.flowMw || 0))} MW). Se desperdician ${Math.round(snapshot.curtailedMw)} MW solares en Atacama.`;
    }
    if (snapshot.batteryChargeMw > 10) {
      return `🔋 Carga solar (${snapshot.chileTimeLabel}): La Batería Norte absorbe +${Math.round(snapshot.batteryChargeMw)} MW de excedente solar en Atacama (SOC ${Math.round((snapshot.batterySocMwh / Math.max(1, snapshot.batteryCapacityMwh)) * 100)}%).`;
    }
    if (snapshot.batteryDischargeMw > 10) {
      return `⚡ Descarga vespertina (${snapshot.chileTimeLabel}): La Batería inyecta ${Math.round(snapshot.batteryDischargeMw)} MW limpios hacia Santiago para cubrir el pico nocturno.`;
    }
    return `Maqueta física del Sistema Eléctrico Nacional (SEN) en 5 zonas geográficas desde Atacama (18°S) hasta Chiloé/Los Lagos (42°S). Haz clic en cualquier bloque para inspeccionarlo.`;
  }, [isOutageActive, snapshot, l2Info]);

  return (
    <Plate
      fig="Fig 01 · MAQUETA DE CHILE"
      title="RELIEVE TOPOGRÁFICO Y ELÉCTRICO · SEN (18°S — 42°S)"
      hint="CLICK EN UNA REGIÓN PARA ELEVARLA · DESLIZA LA HORA ABAJO"
      readout={readoutText}
      keys={[
        { mark: 'lit', label: 'Módulo / región activa' },
        { mark: 'green', label: 'Solar / carga batería' },
        { mark: 'blue', label: 'Transmisión / descarga' },
        { mark: 'red', label: 'Cuello L2 / falla térmica' },
      ]}
      caption={dynamicCaption}
    >
      <IsoFigure
        width={W}
        height={H}
        label="Maqueta isométrica del relieve y red eléctrica de Chile en 5 zonas"
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
          size={2.6}
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
            {/* Lower Andean Terrace */}
            <Solid
              paths={k.extrude(z.andesStep1, 0, z.andesH1, P, { convex: false, bevel: 0.6 })}
              tone="lo"
              crease="faint"
            />
            {/* Upper Andean Summit Ridge */}
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
                transform={k.topMatrix([-16, -33], z.andesH2 + 0.2, P)}
                size={2.4}
                tone="mid"
              >
                CORDILLERA DE LOS ANDES
              </FaceText>
            ) : null}
          </g>
        ))}

        {/* 5. INTER-ZONE TRANSMISSION BRIDGES (STRUCTURAL SUB-BRIDGES IN CHANNELS) */}
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
              <FaceText
                transform={k.topMatrix([(cor.x0 + cor.x1) / 2 - 3.5, 15.5], 0.2, P)}
                size={2.8}
                tone={isBinding ? 'hi' : 'mid'}
              >
                {cor.id}
              </FaceText>
            </g>
          );
        })}

        {/* 6. FIVE SCULPTED CHILE REGIONAL TERRACES & 3D POWER INSTRUMENTS */}
        {ZONES.map((zone) => {
          const zSnap = zoneSnapshots[zone.id];
          const lift = zoneLifts[zone.id];
          const isSelected = selectedZone === zone.id || hoveredZone === zone.id;
          const topZ = 1.8 + zone.height;
          const translate = k.translateAlong(P, [0, 0, lift]);
          const ox = zone.originX;

          return (
            <g
              key={zone.id}
              transform={translate}
              style={{ cursor: 'pointer' }}
              onClick={() => onSelectZone(selectedZone === zone.id ? 'all' : zone.id)}
              onMouseEnter={() => setHoveredZone(zone.id)}
              onMouseLeave={() => setHoveredZone((prev) => (prev === zone.id ? null : prev))}
            >
              {/* Sculpted Geographic Relief Slab for the Region */}
              <Solid
                paths={k.extrude(zone.contour, 1.8, zone.height, P, {
                  convex: false,
                  bevel: 0.65,
                })}
                tone="hi"
                crease="lo"
                lit={isSelected}
              />

              {/* Isla Grande de Chiloé off Zone 5 (Sur) */}
              {zone.id === 'n_sur' && (
                <Solid
                  paths={k.extrude(CHILOE_ISLAND, 1.2, 3.4, P, {
                    convex: true,
                    bevel: 0.4,
                  })}
                  tone="hi"
                  crease="lo"
                  lit={isSelected}
                />
              )}

              {/* Engraved Regional Name on Coastal Terrace */}
              <FaceText
                transform={k.topMatrix(zone.labelPos, topZ + 0.1, P)}
                size={3.0}
                tone="hi"
              >
                {`${zone.num} ${zone.shortLabel}`}
              </FaceText>

              {/* ZONE 1: NORTE GRANDE (ATACAMA SOLAR ARRAY + GAS + PLUG-IN NORTH BATTERY C1) */}
              {zone.id === 'n_norte_grande' && (
                <g key="assets-z1">
                  {/* 3 Stepped Solar PV Collector Plates */}
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
                        {solarActive && (
                          <Dots
                            points={[
                              k.iso([sx + 3.5, sy + 2.2, topZ + 2.0 + idx * 0.4], P),
                              k.iso([sx + 3.5, sy + 8.8, topZ + 2.0 + idx * 0.4], P),
                            ]}
                            size={0.55}
                            tone="hi"
                            pulse
                          />
                        )}
                      </g>
                    );
                  })}

                  {/* Gas Turbine Cylinder at back-right of Z1 */}
                  <Solid
                    paths={k.cylinder(ox + 38, -14, 4.0, topZ, 6.2, P, 24, 0.4)}
                    tone="mid"
                    inner={
                      <Line
                        d={k.sideArc(ox + 38, -14, 4.0, topZ + 3.1, P, 16)}
                        tone="faint"
                      />
                    }
                  />

                  {/* Curtailment Plume when Solar is Wasted at Midday */}
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

                  {/* North Battery Mounting Bay (Atacama Storage Dock) */}
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

                  {/* ★ PLUG-IN SAE BATTERY MODULE (C1 · 150 MW / 600 MWh) */}
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
                        inner={
                          <Line
                            d={
                              k.sideTicks(
                                ox + 25,
                                ox + 38,
                                2.2,
                                2,
                                4.4,
                                topZ + 6.2,
                                [3.0, 4.5],
                                P,
                                'x'
                              ).minor
                            }
                            tone="lo"
                          />
                        }
                      />
                      {/* 3 Modular Lithium Cell Cylinders on Top + SOC Column */}
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
                      <FaceText
                        transform={k.topMatrix([ox + 24.5, 3.2], topZ + 7.3, P)}
                        size={2.4}
                        tone="hi"
                      >
                        BESS C1
                      </FaceText>
                    </g>
                  )}
                </g>
              )}

              {/* ZONE 2: NORTE CHICO (SOLAR + 2 COQUIMBO WIND TURBINES) */}
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
                        inner={
                          <Line
                            d={k.lineOnTop([sx + 1, sy + 6.5], [sx + 6.2, sy + 6.5], topZ + 2.0, P)}
                            tone={solarActive ? 'green' : 'faint'}
                          />
                        }
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

              {/* ZONE 3: CENTRO / SANTIAGO (METROPOLITAN HIGH-RISES + GAS_CENTRO BREAKER) */}
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
                    const hasBlackout = zSnap.unservedMw > 1;
                    return (
                      <Solid
                        key={`scl-bldg-${bIdx}`}
                        paths={k.slabOf({ x: bx, y: by, w: b.w, d: b.d, r: 1 }, topZ, b.h, P, 4, 0.45)}
                        tone={hasBlackout ? 'mid' : 'hi'}
                        lit={!hasBlackout && isOutageActive && bIdx === 0}
                        inner={
                          <Line
                            d={
                              k.sideTicks(
                                bx + 1.4,
                                bx + b.w - 1.4,
                                2.1,
                                2,
                                by + b.d,
                                topZ + b.h - 1,
                                [b.h - 2.2, b.h - 2.2],
                                P,
                                'x'
                              ).minor
                            }
                            tone={hasBlackout ? 'red' : 'faint'}
                          />
                        }
                      />
                    );
                  })}

                  {zSnap.unservedMw > 1 && (
                    <Line
                      d={k.planOutline(
                        { x: ox + 1.5, y: -20.2, w: 21.5, d: 21, r: 1.8 },
                        topZ + 0.3,
                        P,
                        4
                      )}
                      tone="red"
                    />
                  )}

                  {/* Central Térmica Santiago (gas_centro · 600 MW) + Crisis Trip Plunger */}
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
                      inner={
                        <Line
                          d={k.sideSeam(
                            { x: ox + 27, y: -18, w: 15, d: 11, r: 1.4 },
                            topZ + 3.4,
                            P,
                            4
                          )}
                          tone={isOutageActive ? 'red' : 'faint'}
                        />
                      }
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
                    {/* Existing small Centro BESS (30 MW) */}
                    <Solid
                      paths={k.slabOf(
                        { x: ox + 28, y: -5, w: 13, d: 6.0, r: 1 },
                        topZ,
                        3.2,
                        P,
                        3,
                        0.3
                      )}
                      tone="mid"
                    />
                  </g>
                </g>
              )}

              {/* ZONE 4: CENTRO-SUR (THERMAL BASELOAD + TRANSFORMER COIL) */}
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
                    inner={
                      <Line
                        d={k.sideSeam(
                          { x: ox + 3, y: -17, w: 17, d: 14, r: 1.4 },
                          topZ + 4.0,
                          P,
                          4
                        )}
                        tone="faint"
                      />
                    }
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
                      inner={
                        <Line
                          d={k.sideArc(
                            ox + 8 + sIdx * 6.5,
                            -10,
                            2.2,
                            topZ + 13,
                            P,
                            14
                          )}
                          tone="lo"
                        />
                      }
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
                  <Line
                    d={
                      k.coil(
                        ox + 25,
                        ox + 31.5,
                        [-8.5, topZ + 6.2],
                        1.9,
                        5,
                        'x',
                        P
                      ).front
                    }
                    tone="hi"
                  />
                </g>
              )}

              {/* ZONE 5: SUR (HYDRO DAM + WIND + OPTIONAL C2 SOUTH BATTERY) */}
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
                    inner={
                      <Line
                        d={
                          k.sideTicks(
                            ox + 5.5,
                            ox + 15.5,
                            2.4,
                            2,
                            -1.5,
                            topZ + 7.0,
                            [5.5, 5.5],
                            P,
                            'x'
                          ).minor
                        }
                        tone="blue"
                      />
                    }
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
                      <FaceText
                        transform={k.topMatrix([ox + 23, 1.5], topZ + 6.5, P)}
                        size={2.4}
                        tone="hi"
                      >
                        BESS C2
                      </FaceText>
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
                size={1.25}
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
          SEN · CHILE
        </FaceText>

        {/* Precision Dial Gauge for L2 Corridor (Norte Chico -> Santiago) */}
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
          <FaceText
            transform={k.topMatrix([DIAL_X + 13, DIAL_Y + 2.5], 0.3, P)}
            size={2.6}
            tone={l2Info?.isBinding ? 'hi' : 'mid'}
          >
            {`L2 · ${Math.round(Math.abs(l2Info?.flowMw || 0))}/${Math.round(l2Info?.capacityMw || 400)} MW`}
          </FaceText>
        </g>

        {/* Front Coastal Latitude Ruler Strip (18°S to 42°S) */}
        <Solid paths={k.slabOf(RULER, 0, 0.6, P, 3)} tone="lo" crease="none" />
        <Line d={RULER_TICKS.minor} tone="lo" />
        <Line d={RULER_TICKS.major} tone="mid" />
        {ZONES.map((z) => (
          <FaceText
            key={`lat-${z.id}`}
            transform={k.topMatrix([z.originX + 6, RULER.y + 5.6], 0.6, P)}
            size={2.5}
            tone="mid"
          >
            {z.latLabel}
          </FaceText>
        ))}
      </IsoFigure>
    </Plate>
  );
};
