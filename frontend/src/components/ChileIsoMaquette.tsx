import React from 'react';
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

export type StationId =
  | 'solar'
  | 'thermal'
  | 'battery'
  | 'grid'
  | 'houses';

export interface GridSandboxState {
  // User-controlled game parameters
  sunPct: number; // 0..100%
  demandMw: number; // 300..900 MW demanded by the neighborhood
  cableCapMw: number; // 300..650 MW max capacity of central line
  thermalBroken: boolean; // Whether the gas plant is tripped
  agentEnabled: boolean; // Whether the AI Agent is actively managing the grid

  // Computed real-time physics & AI Agent flows
  solarAvailableMw: number;
  solarUsedMw: number;
  solarWastedMw: number;
  thermalOutputMw: number;
  windOutputMw: number;
  batteryFlowMw: number; // positive = discharging to houses, negative = charging from solar
  batterySocPct: number; // 0..100%
  cableFlowMw: number;
  cableUtilPct: number;
  cableSaturated: boolean;
  housesServedMw: number;
  housesBlackoutMw: number;
  housesLitPct: number; // 0..100%
  agentActionTitle: string;
  agentActionReason: string;
  agentTone: 'green' | 'blue' | 'red' | 'neutral';
}

interface ChileIsoMaquetteProps {
  state: GridSandboxState;
  selectedStation: StationId | null;
  onSelectStation: (id: StationId | null) => void;
  onToggleThermalBreak: () => void;
  onToggleAgent: () => void;
}

const W = 860;
const H = 400;

// Clean isometric camera where +X goes right-down and +Y goes left-down,
// or let's use azimuth 54, elevation 32 so our schematic left-to-right layout fills the canvas spaciously!
const SCENE_BOUNDS: k.Plan = { x: -165, y: -95, w: 330, d: 190, r: 8 };
const P = k.fitProjection(
  [...k.boxCorners(SCENE_BOUNDS, -12, 36)],
  W,
  H,
  { pad: 18, azimuth: 56, elevation: 32 }
);

// Five independent 3D Maquette Plinths arranged in a clean schematic flow:
// Left: Solar Plant (top-left) & Thermal/Wind Plant (bottom-left)
// Center: AI Battery Station (top-center) & Central Grid Substation (bottom-center)
// Right: Neighborhood of Houses (consumer final)
const SOLAR_PAD: k.Plan = { x: -156, y: -76, w: 78, d: 58, r: 6 };
const THERMAL_PAD: k.Plan = { x: -156, y: 12, w: 78, d: 62, r: 6 };
const BATTERY_PAD: k.Plan = { x: -38, y: -82, w: 78, d: 58, r: 6 };
const GRID_PAD: k.Plan = { x: -38, y: 10, w: 78, d: 62, r: 6 };
const HOUSES_PAD: k.Plan = { x: 76, y: -48, w: 86, d: 98, r: 7 };

const DIAL_X = 0;
const DIAL_Y = 48;
const DIAL_R = 14.5;
const DIAL_Z = 5.2;

const DIAL_TICKS = k.radialTicks(
  DIAL_X,
  DIAL_Y,
  DIAL_R - 2.4,
  24,
  4,
  DIAL_Z,
  [1.4, 2.8],
  P,
  -Math.PI * 0.75,
  Math.PI * 1.5
);

function toPct(world: k.Point3): { left: string; top: string } {
  const [sx, sy] = k.iso(world, P);
  return {
    left: `${((sx / W) * 100).toFixed(2)}%`,
    top: `${((sy / H) * 100).toFixed(2)}%`,
  };
}

// Helper to draw a 3D isometric house with a pitched roof on the Neighborhood Maquette
function PitchedHouse({
  x,
  y,
  w,
  d,
  z,
  wallH,
  roofH,
  lit,
  blackout,
}: {
  x: number;
  y: number;
  w: number;
  d: number;
  z: number;
  wallH: number;
  roofH: number;
  lit: boolean;
  blackout: boolean;
}) {
  const zTop = z + wallH;
  const zPeak = zTop + roofH;
  const yMid = y + d / 2;

  // Roof overhang
  const x0 = x - 0.8;
  const x1 = x + w + 0.8;
  const yFront = y + d + 0.8;
  const yBack = y - 0.8;

  const r0 = k.iso([x0, yMid, zPeak], P);
  const r1 = k.iso([x1, yMid, zPeak], P);
  const f0 = k.iso([x0, yFront, zTop], P);
  const f1 = k.iso([x1, yFront, zTop], P);
  const b1 = k.iso([x1, yBack, zTop], P);

  const frontSlopePath = k.pathOf([r0, r1, f1, f0], true);
  const rightGablePath = k.pathOf([r1, b1, f1], true);
  const roofOutlinePath =
    k.pathOf([f0, r0, r1, b1, f1, f0], false) + k.pathOf([r1, f1], false);

  // Two front windows on y + d wall
  const winZ0 = z + 1.8;
  const winZ1 = z + wallH - 1.4;
  const win1Path = k.pathOf(
    [
      k.iso([x + 2.0, y + d + 0.05, winZ0], P),
      k.iso([x + 5.2, y + d + 0.05, winZ0], P),
      k.iso([x + 5.2, y + d + 0.05, winZ1], P),
      k.iso([x + 2.0, y + d + 0.05, winZ1], P),
    ],
    true
  );
  const win2Path = k.pathOf(
    [
      k.iso([x + w - 5.2, y + d + 0.05, winZ0], P),
      k.iso([x + w - 2.0, y + d + 0.05, winZ0], P),
      k.iso([x + w - 2.0, y + d + 0.05, winZ1], P),
      k.iso([x + w - 5.2, y + d + 0.05, winZ1], P),
    ],
    true
  );

  // Side window on x + w wall
  const sideWinPath = k.pathOf(
    [
      k.iso([x + w + 0.05, y + d * 0.32, winZ0], P),
      k.iso([x + w + 0.05, y + d * 0.68, winZ0], P),
      k.iso([x + w + 0.05, y + d * 0.68, winZ1], P),
      k.iso([x + w + 0.05, y + d * 0.32, winZ1], P),
    ],
    true
  );

  const isHouseLit = lit && !blackout;
  const roofSilhouette = k.pathOf([f0, r0, r1, b1, f1], true);

  return (
    <g>
      {/* House Walls */}
      <Solid
        paths={k.slabOf({ x, y, w, d, r: 0.7 }, z, wallH, P, 3, 0.25)}
        tone={blackout ? 'lo' : 'hi'}
        lit={isHouseLit}
        inner={
          <path
            d={win1Path + win2Path + sideWinPath}
            fill={isHouseLit ? '#fde047' : 'rgba(100, 116, 139, 0.35)'}
            fillOpacity={isHouseLit ? 0.9 : 0.55}
            stroke={blackout ? '#dc2626' : isHouseLit ? '#d97706' : 'rgba(71, 85, 105, 0.7)'}
            strokeWidth={0.38}
            strokeLinejoin="round"
          />
        }
      />
      {/* Pitched Roof */}
      <Solid
        paths={{
          fill: roofSilhouette,
          shades: [frontSlopePath, '', rightGablePath, ''],
          top: frontSlopePath,
          crease: k.pathOf([r1, f1], false),
          bevel: '',
          outline: roofOutlinePath,
        }}
        tone={blackout ? 'lo' : 'hi'}
        lit={isHouseLit}
      />
    </g>
  );
}

// Helper to draw a machined plinth base for each of the 5 stations
function StationPlinth({
  plan,
  selected,
  alert,
}: {
  plan: k.Plan;
  selected: boolean;
  alert?: boolean;
}) {
  return (
    <g>
      <path className="iso-halo" d={k.haloOf(plan, -7, 7, P)} />
      {k.corners(plan, 7).map(([fx, fy], idx) => (
        <Solid
          key={idx}
          paths={k.cylinder(fx, fy, 3.4, -7, 2.2, P, 18)}
          tone="lo"
          crease="none"
        />
      ))}
      <Solid
        paths={k.slabOf(plan, -5, 5, P, 6, 0.9)}
        tone={selected ? 'hi' : 'mid'}
        lit={selected}
        crease="faint"
        inner={<Line d={k.sideSeam(plan, -2.5, P, 6)} tone="faint" />}
      />
      <Line
        d={k.planOutline(k.insetPlan(plan, 2.6), 0, P, 5)}
        tone={alert ? 'red' : selected ? 'lit' : 'lo'}
      />
    </g>
  );
}

export const ChileIsoMaquette: React.FC<ChileIsoMaquetteProps> = ({
  state,
  selectedStation,
  onSelectStation,
  onToggleThermalBreak,
  onToggleAgent,
}) => {
  const liftSolar = useEased(selectedStation === 'solar' ? 3.5 : 0, 0.15);
  const liftThermal = useEased(selectedStation === 'thermal' ? 3.5 : 0, 0.15);
  const liftBattery = useEased(selectedStation === 'battery' ? 3.5 : 0, 0.15);
  const liftGrid = useEased(selectedStation === 'grid' ? 3.5 : 0, 0.15);
  const liftHouses = useEased(selectedStation === 'houses' ? 3.5 : 0, 0.15);

  const easedSoc = useEased(state.batterySocPct / 100, 0.14);
  const easedCableRatio = useEased(
    Math.min(1.05, state.cableUtilPct / 100),
    0.14
  );
  const easedBreaker = useEased(state.thermalBroken ? 1 : 0, 0.16);
  const easedAgent = useEased(state.agentEnabled ? 1 : 0, 0.16);

  // Dial gauge needle
  const needleAngle = -Math.PI * 0.75 + easedCableRatio * Math.PI * 1.5;
  const needleTip: k.Plane = [
    DIAL_X + Math.cos(needleAngle) * (DIAL_R - 3.0),
    DIAL_Y + Math.sin(needleAngle) * (DIAL_R - 3.0),
  ];
  const needleTail: k.Plane = [
    DIAL_X - Math.cos(needleAngle) * 2.5,
    DIAL_Y - Math.sin(needleAngle) * 2.5,
  ];

  // HTML Badge Coordinates above each of the 5 3D Maquette Stations
  const solarPin = toPct([-117, -76, 17]);
  const thermalPin = toPct([-117, 74, -2]);
  const batteryPin = toPct([1, -82, 22]);
  const gridPin = toPct([1, 74, -2]);
  const housesPin = toPct([119, -48, 22]);

  const isCharging = state.batteryFlowMw < -5;
  const isDischarging = state.batteryFlowMw > 5;
  const hasBlackout = state.housesBlackoutMw > 5;

  // Station detail popover if user clicks a 3D station
  const stationInfo: Record<
    StationId,
    { title: string; subtitle: string; metric: string }
  > = {
    solar: {
      title: '☀️ Maqueta 01 · Planta Solar (Atacama)',
      subtitle:
        'Paneles fotovoltaicos que generan energía limpia gratis cuando brilla el sol. Si el cable central se llena y el Agente IA está apagado, el excedente se pierde.',
      metric: `Producción actual: ${Math.round(state.solarAvailableMw)} MW (${
        state.solarWastedMw > 5
          ? `${Math.round(state.solarWastedMw)} MW desperdiciados`
          : '100% aprovechado'
      })`,
    },
    thermal: {
      title: '🔥 Maqueta 02 · Central Térmica y Eólica',
      subtitle:
        'Respaldo convencional de gas + aerogeneradores. Puedes provocarle una avería con un clic para ver cómo el Agente IA protege al barrio usando la batería.',
      metric: state.thermalBroken
        ? `🚨 PLANTA AVERIADA (0 MW de gas · ${Math.round(state.windOutputMw)} MW eólicos)`
        : `Producción firme: ${Math.round(state.thermalOutputMw + state.windOutputMw)} MW`,
    },
    battery: {
      title: '🤖 Maqueta 03 · Super-Batería del Agente IA',
      subtitle:
        'El cerebro de la red. Cuando sobra sol, el Agente IA la carga automáticamente; cuando falta luz en las casas o se rompe la central térmica, la descarga al instante.',
      metric: isCharging
        ? `🔋 Guardando +${Math.round(Math.abs(state.batteryFlowMw))} MW solares`
        : isDischarging
        ? `⚡ Inyectando +${Math.round(state.batteryFlowMw)} MW hacia el barrio`
        : `En espera · Carga al ${Math.round(state.batterySocPct)}%`,
    },
    grid: {
      title: '⚡ Maqueta 04 · Subestación y Cable Central',
      subtitle:
        'Autopista eléctrica que lleva la energía de las plantas hacia el barrio de casas. Tiene un límite físico que puedes ajustar abajo.',
      metric: `Flujo actual: ${Math.round(state.cableFlowMw)} / ${Math.round(
        state.cableCapMw
      )} MW (${Math.round(state.cableUtilPct)}%)`,
    },
    houses: {
      title: '🏘️ Maqueta 05 · Barrio Residencial (Consumidor Final)',
      subtitle:
        'Representa los hogares de Chile donde llega la electricidad. Las ventanas y tejados muestran en vivo si todas las familias tienen luz.',
      metric: hasBlackout
        ? `🚨 APAGÓN PARCIAL: Faltan ${Math.round(state.housesBlackoutMw)} MW en el barrio`
        : `✅ 100% de las casas iluminadas (${Math.round(state.housesServedMw)} MW)`,
    },
  };

  return (
    <Plate
      fig="ESQUEMA INTERACTIVO 3D · RED ELÉCTRICA"
      title="PLANTAS GENERADORAS (IZQ.)  →  RED Y AGENTE IA (CENTRO)  →  BARRIO DE CASAS (DER.)"
      hint="TOCA CUALQUIER MAQUETA 3D O MUEVE LOS CONTROLES DE ABAJO"
      readout={
        state.agentEnabled ? '🤖 AGENTE IA: ACTIVO' : '⚠️ AGENTE IA: APAGADO'
      }
    >
      <div className="maquette-stage">
        {/* FLOATING LABELS FOR EACH OF THE 5 SCHEMATIC 3D STATIONS */}
        <div className="maquette-overlay">
          {/* 1. SOLAR PLANT LABEL */}
          <button
            type="button"
            className="station-tag"
            data-tone={
              state.solarWastedMw > 10
                ? 'red'
                : state.solarAvailableMw > 20
                ? 'green'
                : 'neutral'
            }
            style={{ left: solarPin.left, top: solarPin.top }}
            onClick={() =>
              onSelectStation(selectedStation === 'solar' ? null : 'solar')
            }
          >
            <span className="station-tag-title">☀️ PLANTA SOLAR</span>
            <strong className="station-tag-val">
              {Math.round(state.solarAvailableMw)} MW
            </strong>
            <span className="station-tag-sub">
              {state.solarWastedMw > 10
                ? `❌ Pierde ${Math.round(state.solarWastedMw)} MW`
                : state.solarAvailableMw > 20
                ? '✓ Enviando sol a la red'
                : '☾ De noche (0 MW)'}
            </span>
          </button>

          {/* 2. THERMAL + WIND PLANT LABEL */}
          <button
            type="button"
            className="station-tag station-tag--bottom"
            data-tone={state.thermalBroken ? 'red' : 'blue'}
            style={{ left: thermalPin.left, top: thermalPin.top }}
            onClick={onToggleThermalBreak}
            title="Haz clic para averiar o reparar la central térmica"
          >
            <span className="station-tag-title">🔥 CENTRAL TÉRMICA + EÓLICA</span>
            <strong className="station-tag-val">
              {state.thermalBroken
                ? '💥 AVERIADA'
                : `${Math.round(state.thermalOutputMw + state.windOutputMw)} MW`}
            </strong>
            <span className="station-tag-sub">
              {state.thermalBroken
                ? 'Clic aquí para reparar planta'
                : 'Clic aquí para simular avería'}
            </span>
          </button>

          {/* 3. AI BATTERY STATION LABEL */}
          <button
            type="button"
            className="station-tag"
            data-tone={
              !state.agentEnabled
                ? 'neutral'
                : isCharging
                ? 'green'
                : isDischarging
                ? 'blue'
                : 'green'
            }
            style={{ left: batteryPin.left, top: batteryPin.top }}
            onClick={onToggleAgent}
            title="Haz clic para encender o apagar el Agente IA"
          >
            <span className="station-tag-title">🤖 BATERÍA AGENTE IA</span>
            <strong className="station-tag-val">
              {!state.agentEnabled
                ? 'DESACTIVADA'
                : isCharging
                ? `CARGANDO +${Math.round(Math.abs(state.batteryFlowMw))} MW`
                : isDischarging
                ? `INYECTANDO +${Math.round(state.batteryFlowMw)} MW`
                : `LISTA (${Math.round(state.batterySocPct)}%)`}
            </strong>
            <span className="station-tag-sub">
              {!state.agentEnabled
                ? 'Clic para activar Agente IA'
                : isCharging
                ? 'Guardando sol que no cabe en cable'
                : isDischarging
                ? 'Enviando luz de emergencia a casas'
                : 'Vigilando la red en tiempo real'}
            </span>
          </button>

          {/* 4. CENTRAL CABLE / SUBSTATION LABEL */}
          <button
            type="button"
            className="station-tag station-tag--bottom"
            data-tone={state.cableSaturated ? 'red' : 'blue'}
            style={{ left: gridPin.left, top: gridPin.top }}
            onClick={() =>
              onSelectStation(selectedStation === 'grid' ? null : 'grid')
            }
          >
            <span className="station-tag-title">⚡ CABLE CENTRAL</span>
            <strong className="station-tag-val">
              {Math.round(state.cableFlowMw)} / {Math.round(state.cableCapMw)} MW
            </strong>
            <span className="station-tag-sub">
              {state.cableSaturated
                ? '⚠️ CABLE AL 100% (Atasco)'
                : `Capacidad al ${Math.round(state.cableUtilPct)}%`}
            </span>
          </button>

          {/* 5. NEIGHBORHOOD OF HOUSES LABEL */}
          <button
            type="button"
            className="station-tag"
            data-tone={hasBlackout ? 'red' : 'green'}
            style={{ left: housesPin.left, top: housesPin.top }}
            onClick={() =>
              onSelectStation(selectedStation === 'houses' ? null : 'houses')
            }
          >
            <span className="station-tag-title">🏘️ BARRIO DE CASAS</span>
            <strong className="station-tag-val">
              {hasBlackout
                ? `🚨 APAGÓN (${Math.round(state.housesLitPct)}% luz)`
                : '✅ 100% CON LUZ'}
            </strong>
            <span className="station-tag-sub">
              {hasBlackout
                ? `Faltan ${Math.round(state.housesBlackoutMw)} MW en hogares`
                : `Consumiendo ${Math.round(state.demandMw)} MW sin cortes`}
            </span>
          </button>
        </div>

        <IsoFigure
          width={W}
          height={H}
          label="Esquema isométrico 3D de plantas eléctricas, batería IA y barrio de casas"
        >
          {/* ============================================================
              STATION 1 (TOP-LEFT): ☀️ PLANTA SOLAR ATACAMA
             ============================================================ */}
          <g
            transform={k.translateAlong(P, [0, 0, liftSolar])}
            style={{ cursor: 'pointer' }}
            onClick={() =>
              onSelectStation(selectedStation === 'solar' ? null : 'solar')
            }
          >
            <StationPlinth
              plan={SOLAR_PAD}
              selected={selectedStation === 'solar'}
              alert={state.solarWastedMw > 10}
            />

            {/* 6 Tilted Solar PV Collector Arrays in 2 rows of 3 */}
            {[0, 1].map((row) =>
              [0, 1, 2].map((col) => {
                const sx = SOLAR_PAD.x + 8 + col * 21;
                const sy = SOLAR_PAD.y + 8 + row * 19;
                const active = state.solarAvailableMw > 25;
                const h = 2.4 + row * 0.8;
                return (
                  <g key={`pv-${row}-${col}`}>
                    <Solid
                      paths={k.slabOf(
                        { x: sx, y: sy, w: 16, d: 13, r: 1.0 },
                        0,
                        h,
                        P,
                        3,
                        0.3
                      )}
                      tone={active ? 'hi' : 'mid'}
                      lit={active && state.sunPct >= 60}
                      inner={
                        <Line
                          d={
                            k.lineOnTop(
                              [sx + 2, sy + 4.3],
                              [sx + 14, sy + 4.3],
                              h,
                              P
                            ) +
                            k.lineOnTop(
                              [sx + 2, sy + 8.6],
                              [sx + 14, sy + 8.6],
                              h,
                              P
                            )
                          }
                          tone={active ? 'green' : 'faint'}
                        />
                      }
                    />
                  </g>
                );
              })
            )}

            {/* Curtailment plume if solar energy is being wasted */}
            {state.solarWastedMw > 10 && (
              <g>
                <Line
                  d={k.rise([-117, -48], 4, 18, P)}
                  tone="red"
                  dashed
                  flow
                />
                <Line d={k.ring(-117, -48, 6, 18, P, 24)} tone="red" />
              </g>
            )}

            <FaceText
              transform={k.topMatrix([SOLAR_PAD.x + 8, SOLAR_PAD.y + 51], 0.2, P)}
              size={3.4}
              tone="hi"
            >
              01 · PLANTA SOLAR
            </FaceText>
          </g>

          {/* ============================================================
              STATION 2 (BOTTOM-LEFT): 🔥 CENTRAL TÉRMICA + EÓLICA
             ============================================================ */}
          <g
            transform={k.translateAlong(P, [0, 0, liftThermal])}
            style={{ cursor: 'pointer' }}
            onClick={() =>
              onSelectStation(selectedStation === 'thermal' ? null : 'thermal')
            }
          >
            <StationPlinth
              plan={THERMAL_PAD}
              selected={selectedStation === 'thermal'}
              alert={state.thermalBroken}
            />

            {/* Main Turbine Generator Hall */}
            <Solid
              paths={k.slabOf(
                { x: THERMAL_PAD.x + 8, y: THERMAL_PAD.y + 10, w: 36, d: 28, r: 2 },
                0,
                11,
                P,
                4,
                0.7
              )}
              tone={state.thermalBroken ? 'lo' : 'hi'}
              inner={
                <Line
                  d={k.sideSeam(
                    { x: THERMAL_PAD.x + 8, y: THERMAL_PAD.y + 10, w: 36, d: 28, r: 2 },
                    5.5,
                    P,
                    4
                  )}
                  tone={state.thermalBroken ? 'red' : 'faint'}
                />
              }
            />

            {/* Two Exhaust Chimneys + Trip Valve */}
            {[0, 1].map((cIdx) => (
              <Solid
                key={`chimney-${cIdx}`}
                paths={k.cylinder(
                  THERMAL_PAD.x + 18 + cIdx * 13,
                  THERMAL_PAD.y + 22,
                  4.2,
                  11,
                  11,
                  P,
                  24,
                  0.35
                )}
                tone={state.thermalBroken ? 'lo' : 'hi'}
                inner={
                  <Line
                    d={k.sideArc(
                      THERMAL_PAD.x + 18 + cIdx * 13,
                      THERMAL_PAD.y + 22,
                      4.2,
                      19,
                      P,
                      16
                    )}
                    tone={state.thermalBroken ? 'red' : 'lo'}
                  />
                }
              />
            ))}

            {/* Red Fault Breaker Plunger when Thermal Plant is Broken */}
            <g transform={k.translateAlong(P, [0, 0, easedBreaker * 6])}>
              <Solid
                paths={k.cylinder(
                  THERMAL_PAD.x + 26,
                  THERMAL_PAD.y + 30,
                  3.5,
                  11,
                  4,
                  P,
                  20
                )}
                tone="hi"
                lit={state.thermalBroken}
              />
            </g>
            {state.thermalBroken && (
              <Line
                d={k.ring(THERMAL_PAD.x + 26, THERMAL_PAD.y + 30, 8, 12, P, 24)}
                tone="red"
              />
            )}

            {/* Wind Turbine on the right side of Station 2 */}
            <g>
              <Solid
                paths={k.cylinder(
                  THERMAL_PAD.x + 58,
                  THERMAL_PAD.y + 24,
                  3.8,
                  0,
                  2.2,
                  P,
                  20
                )}
                tone="mid"
                crease="none"
              />
              <Solid
                paths={k.cylinder(
                  THERMAL_PAD.x + 58,
                  THERMAL_PAD.y + 24,
                  1.6,
                  2.2,
                  19,
                  P,
                  20
                )}
                tone="hi"
                crease="none"
              />
              <Solid
                paths={k.slabOf(
                  {
                    x: THERMAL_PAD.x + 55,
                    y: THERMAL_PAD.y + 22,
                    w: 6,
                    d: 4.5,
                    r: 1,
                  },
                  21.2,
                  3.2,
                  P,
                  3
                )}
                tone="hi"
              />
              {[0, 1, 2].map((bIdx) => {
                const ang = (state.sunPct * 0.05) + (bIdx * Math.PI * 2) / 3;
                const wx = THERMAL_PAD.x + 58;
                const wy = THERMAL_PAD.y + 24;
                return (
                  <Line
                    key={`wind-b-${bIdx}`}
                    d={k.segment(
                      [wx, wy + 2.2, 22.8],
                      [
                        wx + 1.5,
                        wy + 2.2 + Math.cos(ang) * 9.5,
                        22.8 + Math.sin(ang) * 9.5,
                      ],
                      P
                    )}
                    tone="green"
                  />
                );
              })}
            </g>

            <FaceText
              transform={k.topMatrix([THERMAL_PAD.x + 8, THERMAL_PAD.y + 54], 0.2, P)}
              size={3.4}
              tone="hi"
            >
              02 · TÉRMICA + EÓLICA
            </FaceText>
          </g>

          {/* ============================================================
              STATION 3 (CENTER-TOP): 🤖 BATERÍA DEL AGENTE IA
             ============================================================ */}
          <g
            transform={k.translateAlong(P, [0, 0, liftBattery])}
            style={{ cursor: 'pointer' }}
            onClick={() =>
              onSelectStation(selectedStation === 'battery' ? null : 'battery')
            }
          >
            <StationPlinth
              plan={BATTERY_PAD}
              selected={selectedStation === 'battery'}
            />

            {/* Main Battery Enclosure & AI Controller Core */}
            <g
              transform={k.translateAlong(P, [0, 0, (1 - easedAgent) * 5])}
              opacity={0.45 + easedAgent * 0.55}
            >
              <Solid
                paths={k.slabOf(
                  {
                    x: BATTERY_PAD.x + 9,
                    y: BATTERY_PAD.y + 9,
                    w: 60,
                    d: 34,
                    r: 2.5,
                  },
                  0,
                  9.5,
                  P,
                  5,
                  0.7
                )}
                tone={state.agentEnabled ? 'hi' : 'lo'}
                lit={state.agentEnabled && (isCharging || isDischarging)}
                inner={
                  <Line
                    d={
                      k.sideTicks(
                        BATTERY_PAD.x + 14,
                        BATTERY_PAD.x + 64,
                        4.2,
                        2,
                        BATTERY_PAD.y + 43,
                        8.2,
                        [5.5, 6.8],
                        P,
                        'x'
                      ).minor
                    }
                    tone={
                      isCharging
                        ? 'green'
                        : isDischarging
                        ? 'blue'
                        : 'lo'
                    }
                  />
                }
              />

              {/* 4 Vertical Storage Cells whose height reflects real-time SOC % */}
              {[0, 1, 2, 3].map((cIdx) => {
                const cx = BATTERY_PAD.x + 18 + cIdx * 13.5;
                const cy = BATTERY_PAD.y + 25;
                const cellH = 2.5 + easedSoc * 9.5;
                return (
                  <Solid
                    key={`bcell-${cIdx}`}
                    paths={k.cylinder(cx, cy, 4.2, 9.5, cellH, P, 24, 0.35)}
                    tone="hi"
                    lit={state.agentEnabled}
                    inner={
                      <Line
                        d={k.sideArc(cx, cy, 4.2, 9.5 + cellH * 0.6, P, 16)}
                        tone={isCharging ? 'green' : isDischarging ? 'blue' : 'lo'}
                      />
                    }
                  />
                );
              })}

              {/* Glowing perimeter ring showing AI Agent activity */}
              {state.agentEnabled && (
                <Line
                  d={k.planOutline(
                    {
                      x: BATTERY_PAD.x + 7,
                      y: BATTERY_PAD.y + 7,
                      w: 64,
                      d: 38,
                      r: 3,
                    },
                    0.3,
                    P,
                    4
                  )}
                  tone={
                    isCharging ? 'green' : isDischarging ? 'blue' : 'lit'
                  }
                />
              )}
            </g>

            <FaceText
              transform={k.topMatrix([BATTERY_PAD.x + 8, BATTERY_PAD.y + 51], 0.2, P)}
              size={3.4}
              tone="hi"
            >
              03 · BATERÍA AGENTE IA
            </FaceText>
          </g>

          {/* ============================================================
              STATION 4 (CENTER-BOTTOM): ⚡ SUBESTACIÓN Y CABLE CENTRAL
             ============================================================ */}
          <g
            transform={k.translateAlong(P, [0, 0, liftGrid])}
            style={{ cursor: 'pointer' }}
            onClick={() =>
              onSelectStation(selectedStation === 'grid' ? null : 'grid')
            }
          >
            <StationPlinth
              plan={GRID_PAD}
              selected={selectedStation === 'grid'}
              alert={state.cableSaturated}
            />

            {/* High-Voltage Transformer Block + Copper Coils */}
            <Solid
              paths={k.slabOf(
                { x: GRID_PAD.x + 10, y: GRID_PAD.y + 8, w: 58, d: 20, r: 2 },
                0,
                7.5,
                P,
                4,
                0.55
              )}
              tone="mid"
            />
            <Line
              d={
                k.coil(
                  GRID_PAD.x + 18,
                  GRID_PAD.x + 60,
                  [GRID_PAD.y + 18, 9.5],
                  3.5,
                  9,
                  'x',
                  P
                ).front
              }
              tone={state.cableSaturated ? 'red' : 'hi'}
            />

            {/* Precision Analog Dial Gauge for Central Cable Load */}
            <Solid
              paths={k.cylinder(DIAL_X, DIAL_Y, DIAL_R, 0, DIAL_Z, P, 48, 0.7)}
              tone="hi"
              crease="lo"
              lit={state.cableSaturated}
              inner={
                <Line
                  d={
                    k.knurl(DIAL_X, DIAL_Y, DIAL_R, 1.6, DIAL_Z, 52, P, 0.3) +
                    k.sideArc(DIAL_X, DIAL_Y, DIAL_R, 1.6, P, 32)
                  }
                  tone="lo"
                />
              }
            />
            <Line
              d={k.ring(DIAL_X, DIAL_Y, DIAL_R - 1.8, DIAL_Z, P, 48)}
              tone="lo"
            />
            <Line d={DIAL_TICKS.minor} tone="lo" />
            <Line d={DIAL_TICKS.major} tone="mid" />
            <Line
              d={k.lineOnTop(needleTail, needleTip, DIAL_Z + 0.25, P)}
              tone={state.cableSaturated ? 'red' : 'blue'}
            />
            <Line
              d={k.ring(DIAL_X, DIAL_Y, 1.6, DIAL_Z + 0.25, P, 16)}
              tone="hi"
            />
          </g>

          {/* ============================================================
              STATION 5 (RIGHT): 🏘️ BARRIO DE CASAS (CONSUMIDOR FINAL)
             ============================================================ */}
          <g
            transform={k.translateAlong(P, [0, 0, liftHouses])}
            style={{ cursor: 'pointer' }}
            onClick={() =>
              onSelectStation(selectedStation === 'houses' ? null : 'houses')
            }
          >
            <StationPlinth
              plan={HOUSES_PAD}
              selected={selectedStation === 'houses'}
              alert={hasBlackout}
            />

            {/* Neighborhood Streets & Internal Power Distribution Lines */}
            <Line
              d={
                k.lineOnTop(
                  [HOUSES_PAD.x + 8, HOUSES_PAD.y + 44],
                  [HOUSES_PAD.x + 78, HOUSES_PAD.y + 44],
                  0.15,
                  P
                ) +
                k.lineOnTop(
                  [HOUSES_PAD.x + 43, HOUSES_PAD.y + 10],
                  [HOUSES_PAD.x + 43, HOUSES_PAD.y + 78],
                  0.15,
                  P
                )
              }
              tone={hasBlackout ? 'red' : 'green'}
            />

            {/* 6 Isometric Houses with Pitched Roofs in a Neighborhood Grid */}
            {[
              { hx: HOUSES_PAD.x + 10, hy: HOUSES_PAD.y + 12, w: 22, d: 18, wallH: 7.5, roofH: 5.2, idx: 0 },
              { hx: HOUSES_PAD.x + 48, hy: HOUSES_PAD.y + 12, w: 24, d: 18, wallH: 8.5, roofH: 5.5, idx: 1 },
              { hx: HOUSES_PAD.x + 10, hy: HOUSES_PAD.y + 34, w: 22, d: 18, wallH: 7.0, roofH: 4.8, idx: 2 },
              { hx: HOUSES_PAD.x + 48, hy: HOUSES_PAD.y + 34, w: 24, d: 18, wallH: 8.0, roofH: 5.2, idx: 3 },
              { hx: HOUSES_PAD.x + 10, hy: HOUSES_PAD.y + 56, w: 22, d: 18, wallH: 7.2, roofH: 4.8, idx: 4 },
              { hx: HOUSES_PAD.x + 48, hy: HOUSES_PAD.y + 56, w: 24, d: 18, wallH: 7.5, roofH: 5.0, idx: 5 },
            ].map((h) => {
              // If there is a partial blackout, the last houses lose power first
              const houseThresholdPct = ((h.idx + 1) / 6) * 100;
              const isHouseDark =
                hasBlackout && state.housesLitPct < houseThresholdPct;
              return (
                <PitchedHouse
                  key={`house-${h.idx}`}
                  x={h.hx}
                  y={h.hy}
                  w={h.w}
                  d={h.d}
                  z={0}
                  wallH={h.wallH}
                  roofH={h.roofH}
                  lit={!isHouseDark}
                  blackout={isHouseDark}
                />
              );
            })}

            {/* Streetlight / Neighborhood Power Poles */}
            <Dots
              points={[
                k.iso([HOUSES_PAD.x + 43, HOUSES_PAD.y + 24, 1.5], P),
                k.iso([HOUSES_PAD.x + 43, HOUSES_PAD.y + 44, 1.5], P),
                k.iso([HOUSES_PAD.x + 43, HOUSES_PAD.y + 64, 1.5], P),
              ]}
              size={0.85}
              tone={hasBlackout ? 'hi' : 'hi'}
              pulse={!hasBlackout}
            />

            <FaceText
              transform={k.topMatrix([HOUSES_PAD.x + 10, HOUSES_PAD.y + 88], 0.2, P)}
              size={3.4}
              tone="hi"
            >
              05 · BARRIO DE CASAS
            </FaceText>
          </g>

          {/* ============================================================
              SCHEMATIC ENERGY FLOW WIRES CONNECTING THE 5 STATIONS
             ============================================================ */}
          {/* 1. Solar Plant -> AI Battery (when AI charges from solar) */}
          <Wire
            from={k.iso([-78, -48, 4], P)}
            to={k.iso([-38, -52, 4], P)}
            tone={isCharging ? 'green' : state.solarAvailableMw > 20 ? 'lo' : 'faint'}
            flow={isCharging}
            ends="both"
            size={1.4}
          />

          {/* 2. Solar Plant -> Central Substation */}
          <Wire
            from={k.iso([-78, -32, 3], P)}
            via={[k.iso([-58, -10, 3], P)]}
            to={k.iso([-38, 22, 3], P)}
            tone={
              state.solarAvailableMw > 20
                ? state.cableSaturated
                  ? 'red'
                  : 'green'
                : 'faint'
            }
            flow={state.solarAvailableMw > 20}
            ends="both"
            size={1.4}
          />

          {/* 3. Thermal + Wind Plant -> Central Substation */}
          <Wire
            from={k.iso([-78, 38, 3], P)}
            to={k.iso([-38, 38, 3], P)}
            tone={
              state.thermalBroken
                ? 'red'
                : state.thermalOutputMw + state.windOutputMw > 20
                ? 'blue'
                : 'lo'
            }
            flow={state.thermalOutputMw + state.windOutputMw > 20}
            ends="both"
            size={1.4}
          />

          {/* 4. AI Battery <-> Central Substation / Neighborhood */}
          <Wire
            from={k.iso([1, -24, 4], P)}
            to={k.iso([1, 10, 4], P)}
            tone={
              isDischarging
                ? 'blue'
                : isCharging
                ? 'green'
                : 'lo'
            }
            flow={isCharging || isDischarging}
            ends="both"
            size={1.4}
          />

          {/* Direct Emergency AI Feed from Battery -> Neighborhood of Houses */}
          <Wire
            from={k.iso([40, -52, 4], P)}
            to={k.iso([76, -24, 4], P)}
            tone={isDischarging ? 'blue' : 'faint'}
            flow={isDischarging}
            ends="both"
            size={1.45}
          />

          {/* 5. Central Substation -> Neighborhood of Houses (Main Consumer Line) */}
          <Wire
            from={k.iso([40, 32, 4], P)}
            to={k.iso([76, 12, 4], P)}
            tone={
              hasBlackout
                ? 'red'
                : state.cableSaturated
                ? 'red'
                : 'green'
            }
            flow={state.housesServedMw > 10}
            ends="both"
            size={1.55}
          />
        </IsoFigure>

        {/* OPTIONAL POPOVER IF USER CLICKS A 3D MAQUETTE */}
        {selectedStation && (
          <div className="maquette-zone-toast">
            <div>
              <strong>{stationInfo[selectedStation].title}</strong>
              <p>{stationInfo[selectedStation].subtitle}</p>
              <span className="toast-metric">
                {stationInfo[selectedStation].metric}
              </span>
            </div>
            <button
              type="button"
              className="maquette-toast-close"
              onClick={() => onSelectStation(null)}
            >
              Cerrar ×
            </button>
          </div>
        )}
      </div>
    </Plate>
  );
};
