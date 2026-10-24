import React, { useEffect, useMemo, useState } from 'react';
import { ChileIsoMaquette } from './components/ChileIsoMaquette';
import {
  CEN_EVIDENCE,
  computeZoneSnapshot,
  getSolution,
  HourlyZoneSnapshot,
  NODES,
} from './data/scenarioData';
import { CandidateId, NodeId, OperationMode } from './types/grid';

export function App() {
  // Default to the signature warm-paper light theme from skills.wheresryan.sh/anatomy, with 1-click dark toggle
  const [theme, setTheme] = useState<'light' | 'dark'>('light');

  // Core simulation state: 13:00 CLST (step 52) shows the midday Atacama solar bottleneck immediately
  const [step96, setStep96] = useState<number>(52);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [mode, setMode] = useState<OperationMode>('normal');
  const [candidateId, setCandidateId] = useState<CandidateId>('c1_battery_norte_grande');
  const [selectedZone, setSelectedZone] = useState<NodeId | 'all'>('all');

  // Smooth playback loop
  useEffect(() => {
    if (!isPlaying) return;
    const timer = window.setInterval(() => {
      setStep96((prev) => (prev + 1) % 96);
    }, 260);
    return () => window.clearInterval(timer);
  }, [isPlaying]);

  const activeSolution = useMemo(
    () => getSolution(mode, candidateId),
    [mode, candidateId]
  );

  const baselineSolution = useMemo(
    () => getSolution(mode, 'baseline'),
    [mode]
  );

  // National snapshot for the maquette
  const nationalSnapshot = useMemo(
    () => computeZoneSnapshot(activeSolution, step96, 'all'),
    [activeSolution, step96]
  );

  // Per-zone snapshots for the 5 SEN zone blocks on the maquette
  const zoneSnapshots = useMemo(() => {
    const map = {} as Record<NodeId, HourlyZoneSnapshot>;
    for (const n of NODES) {
      map[n.id] = computeZoneSnapshot(activeSolution, step96, n.id);
    }
    return map;
  }, [activeSolution, step96]);

  // Selected zone or national snapshot for the bottom inspector strip
  const inspectedSnapshot = useMemo(
    () =>
      selectedZone === 'all'
        ? nationalSnapshot
        : zoneSnapshots[selectedZone],
    [selectedZone, nationalSnapshot, zoneSnapshots]
  );

  // 24h KPI comparisons vs baseline
  const baseCurtailment = baselineSolution.metrics.curtailment_mwh;
  const activeCurtailment = activeSolution.metrics.curtailment_mwh;
  const savedSolarMwh = Math.max(0, baseCurtailment - activeCurtailment);

  const baseUnserved = baselineSolution.metrics.unserved_mwh;
  const activeUnserved = activeSolution.metrics.unserved_mwh;
  const avoidedBlackoutMwh = Math.max(0, baseUnserved - activeUnserved);

  const l2Flow = nationalSnapshot.lineFlows.L2;

  const handleModeSwitch = (nextMode: OperationMode) => {
    setMode(nextMode);
    if (nextMode === 'sudden_outage' && step96 < 68) {
      // Jump directly to 18:00 CLST (step 72) so the user immediately sees the evening crisis on the maquette
      setStep96(72);
    } else if (nextMode === 'normal' && step96 >= 68) {
      setStep96(52);
    }
  };

  return (
    <div className="iso anatomy-shell" data-theme={theme}>
      <main className="anatomy-page">
        {/* 1. MINIMALIST HEADER */}
        <header className="anatomy-header">
          <div>
            <div className="anatomy-eyebrow">
              SEN · CHILE · MAQUETA DE DESPACHO ELÉCTRICO (24H)
            </div>
            <h1 className="anatomy-title">
              El Cuello de Botella Solar de Chile
            </h1>
            <p className="anatomy-subtitle">
              Al mediodía, el desierto del <strong>Norte Grande</strong> produce más energía solar de la que el cable{' '}
              <strong>L2 (400 MW máx.)</strong> puede llevar hacia <strong>Santiago</strong>. Prueba cómo instalar la{' '}
              <strong>Batería Norte (IA)</strong> absorbe ese sol y evita apagones a las 18:00.
            </p>
          </div>

          <button
            type="button"
            className="anatomy-play-btn"
            onClick={() => setTheme((t) => (t === 'light' ? 'dark' : 'light'))}
            title="Cambiar tema de color"
          >
            {theme === 'light' ? '☾ MODO OSCURO' : '☀ MODO PAPEL'}
          </button>
        </header>

        {/* 2. TACTILE HARDWARE SWITCHES (INTERVENCIÓN + ESCENARIO) */}
        <section className="anatomy-controls-row" aria-label="Controles del escenario">
          <div className="anatomy-seg-group" role="group" aria-label="Intervención en la red">
            <button
              type="button"
              className="anatomy-seg-btn"
              data-active={candidateId === 'baseline'}
              onClick={() => setCandidateId('baseline')}
            >
              01 · RED ACTUAL
            </button>
            <button
              type="button"
              className="anatomy-seg-btn"
              data-active={candidateId === 'c1_battery_norte_grande'}
              onClick={() => setCandidateId('c1_battery_norte_grande')}
            >
              ★ 02 · BATERÍA NORTE IA
            </button>
            <button
              type="button"
              className="anatomy-seg-btn"
              data-active={candidateId === 'c3_uprate_l2'}
              onClick={() => setCandidateId('c3_uprate_l2')}
            >
              03 · AMPLIAR L2
            </button>
            <button
              type="button"
              className="anatomy-seg-btn"
              data-active={candidateId === 'c2_battery_sur'}
              onClick={() => setCandidateId('c2_battery_sur')}
            >
              04 · BATERÍA SUR
            </button>
          </div>

          <div className="anatomy-seg-group" role="group" aria-label="Condición operativa">
            <button
              type="button"
              className="anatomy-seg-btn"
              data-active={mode === 'normal'}
              onClick={() => handleModeSwitch('normal')}
            >
              DÍA NORMAL
            </button>
            <button
              type="button"
              className="anatomy-seg-btn"
              data-alert="true"
              data-active={mode === 'sudden_outage'}
              onClick={() => handleModeSwitch('sudden_outage')}
            >
              ⚡ FALLA 18:00
            </button>
          </div>
        </section>

        {/* 3. THE ISOMETRIC MAQUETTE OF CHILE (ANATOMY PLATE) */}
        <ChileIsoMaquette
          snapshot={nationalSnapshot}
          zoneSnapshots={zoneSnapshots}
          candidateId={candidateId}
          mode={mode}
          selectedZone={selectedZone}
          onSelectZone={setSelectedZone}
        />

        {/* 4. TIME SCRUBBER & KEY HOURS */}
        <section className="anatomy-scrubber" aria-label="Control de hora del día">
          <button
            type="button"
            className="anatomy-play-btn"
            onClick={() => setIsPlaying((p) => !p)}
          >
            {isPlaying ? '❚❚ PAUSAR' : '▶ SIMULAR 24H'} ({nationalSnapshot.chileTimeLabel})
          </button>

          <div className="anatomy-slider-wrap">
            <input
              type="range"
              min={0}
              max={95}
              value={step96}
              onChange={(e) => {
                setIsPlaying(false);
                setStep96(Number(e.target.value));
              }}
              className="anatomy-range"
              aria-label="Hora del día"
            />
          </div>

          <div className="anatomy-presets">
            <button
              type="button"
              className="anatomy-seg-btn"
              data-active={nationalSnapshot.hourIndex >= 11 && nationalSnapshot.hourIndex <= 14}
              onClick={() => {
                setIsPlaying(false);
                setStep96(52); // 13:00
              }}
            >
              ☀ 13:00 SOL PICO
            </button>
            <button
              type="button"
              className="anatomy-seg-btn"
              data-alert="true"
              data-active={nationalSnapshot.hourIndex >= 17 && nationalSnapshot.hourIndex <= 19}
              onClick={() => {
                setIsPlaying(false);
                setMode('sudden_outage');
                setStep96(72); // 18:00
              }}
            >
              ⚡ 18:00 CRISIS
            </button>
            <button
              type="button"
              className="anatomy-seg-btn"
              data-active={nationalSnapshot.hourIndex >= 20}
              onClick={() => {
                setIsPlaying(false);
                setStep96(84); // 21:00
              }}
            >
              ☾ 21:00 NOCHE
            </button>
          </div>
        </section>

        {/* 5. THREE-COLUMN TABULAR SUMMARY */}
        <section className="anatomy-metrics" aria-label="Indicadores principales de 24 horas">
          <div className="anatomy-metric-cell">
            <div className="anatomy-metric-label">
              01 · Sol Desperdiciado (24h)
            </div>
            <div className="anatomy-metric-value">
              {Math.round(activeCurtailment).toLocaleString()} MWh
            </div>
            <div
              className="anatomy-metric-delta"
              data-tone={savedSolarMwh > 10 ? 'green' : 'red'}
            >
              {savedSolarMwh > 10
                ? `✓ −${Math.round(savedSolarMwh)} MWh solares salvados vs Red Actual`
                : 'Excedente atrapado al norte del cable L2'}
            </div>
          </div>

          <div className="anatomy-metric-cell">
            <div className="anatomy-metric-label">
              02 · Cable L2 (Norte → Santiago)
            </div>
            <div className="anatomy-metric-value">
              {Math.round(Math.abs(l2Flow?.flowMw || 0))} / {Math.round(l2Flow?.capacityMw || 400)} MW
            </div>
            <div
              className="anatomy-metric-delta"
              data-tone={l2Flow?.isBinding ? 'red' : 'blue'}
            >
              {l2Flow?.isBinding
                ? '100% SATURADO (Cuello de botella activo)'
                : `${Math.round(l2Flow?.utilizationPct || 0)}% de capacidad utilizada`}
            </div>
          </div>

          <div className="anatomy-metric-cell">
            <div className="anatomy-metric-label">
              03 · Suministro Santiago (18:00)
            </div>
            <div className="anatomy-metric-value">
              {mode === 'normal'
                ? '100% Cubierto'
                : activeUnserved < 1500
                ? 'Protegido (+243 MWh)'
                : 'Apagón Parcial'}
            </div>
            <div
              className="anatomy-metric-delta"
              data-tone={
                mode === 'normal' || avoidedBlackoutMwh > 10 ? 'green' : 'red'
              }
            >
              {mode === 'normal'
                ? 'Sin racionamiento en operación normal'
                : avoidedBlackoutMwh > 10
                ? '✓ ~98,000 hogares reconectados con Batería C1'
                : 'Falla térmica deja 1,922 MWh sin servir'}
            </div>
          </div>
        </section>

        {/* 6. ZONE INSPECTOR STRIP (SYNCS WITH MAQUETTE CLICKS) */}
        <section className="anatomy-zone-bar" aria-label="Detalle por zona de la maqueta">
          <div className="anatomy-zone-tabs">
            <button
              type="button"
              className="anatomy-seg-btn"
              data-active={selectedZone === 'all'}
              onClick={() => setSelectedZone('all')}
            >
              TODO CHILE
            </button>
            {NODES.map((n, idx) => (
              <button
                key={n.id}
                type="button"
                className="anatomy-seg-btn"
                data-active={selectedZone === n.id}
                onClick={() =>
                  setSelectedZone(selectedZone === n.id ? 'all' : n.id)
                }
              >
                {`0${idx + 1} · ${n.shortName.toUpperCase()}`}
              </button>
            ))}
          </div>

          <div className="anatomy-zone-stats">
            <div>
              <span style={{ color: 'var(--anatomy-muted)', display: 'block', fontSize: 10 }}>
                SOLAR PV
              </span>
              <strong>{Math.round(inspectedSnapshot.solarMw)} MW</strong>
              {inspectedSnapshot.curtailedMw > 1 ? (
                <span style={{ color: 'var(--anatomy-red)', marginLeft: 6 }}>
                  (−{Math.round(inspectedSnapshot.curtailedMw)} MW vertido)
                </span>
              ) : null}
            </div>
            <div>
              <span style={{ color: 'var(--anatomy-muted)', display: 'block', fontSize: 10 }}>
                EÓLICA + HIDRO
              </span>
              <strong>
                {Math.round(inspectedSnapshot.windMw + inspectedSnapshot.hydroMw)} MW
              </strong>
            </div>
            <div>
              <span style={{ color: 'var(--anatomy-muted)', display: 'block', fontSize: 10 }}>
                BATERÍA (SAE)
              </span>
              <strong>
                {inspectedSnapshot.batteryChargeMw > 1
                  ? `Cargando +${Math.round(inspectedSnapshot.batteryChargeMw)} MW`
                  : inspectedSnapshot.batteryDischargeMw > 1
                  ? `Inyectando ${Math.round(inspectedSnapshot.batteryDischargeMw)} MW`
                  : `En espera (${Math.round(inspectedSnapshot.batterySocMwh)} MWh)`}
              </strong>
            </div>
            <div>
              <span style={{ color: 'var(--anatomy-muted)', display: 'block', fontSize: 10 }}>
                TÉRMICA (GAS/CARBÓN)
              </span>
              <strong>
                {Math.round(
                  inspectedSnapshot.gasMw +
                    inspectedSnapshot.coalMw +
                    inspectedSnapshot.dieselMw
                )}{' '}
                MW
              </strong>
            </div>
            <div>
              <span style={{ color: 'var(--anatomy-muted)', display: 'block', fontSize: 10 }}>
                DEMANDA ZONA
              </span>
              <strong>{Math.round(inspectedSnapshot.demandMw)} MW</strong>
            </div>
          </div>
        </section>

        {/* 7. SUBTLE COLLAPSIBLE TECHNICAL / AI AUDIT DRAWER */}
        <details className="anatomy-details">
          <summary>
            Detalles técnicos · Verificación LP HiGHS (16/16 checks) y Agente Gemini 4 Argon
          </summary>
          <div style={{ marginTop: 12, display: 'grid', gap: 8, color: 'var(--anatomy-text)' }}>
            <p style={{ margin: 0 }}>
              <strong>¿Por qué funciona la Batería en el Norte (C1) y no en el Sur (C2)?</strong>{' '}
              Porque entre las 09:00 y las 16:00 el corredor <code>L2 (Norte Chico → Santiago)</code> ya está al 100% de su límite físico (<code>400 MW</code>). Una batería en el Sur no puede recibir ni un solo megavatio adicional del desierto (<code>0 MWh</code> de reducción de vertimiento). En cambio, colocada en <code>Norte Grande</code> (aguas arriba del cuello de botella), absorbe <code>631.6 MWh</code> solares al mediodía y los despacha a las <code>18:00</code> cuando cae el sol.
            </p>
            <p style={{ margin: 0, fontFamily: 'var(--anatomy-mono)', fontSize: 11.5, color: 'var(--anatomy-muted)' }}>
              Motor: HiGHS LP 1.14 · 16/16 restricciones físicas validadas (balance nodal, límites térmicos L1–L4, dinámica SOC) · Evidencia real CEN Chile ({CEN_EVIDENCE.event_date}).
            </p>
          </div>
        </details>
      </main>
    </div>
  );
}

export default App;
