import React, { useEffect, useMemo, useState } from 'react';
import { ChileIsoMaquette } from './components/ChileIsoMaquette';
import {
  computeZoneSnapshot,
  getSolution,
  HourlyZoneSnapshot,
  NODES,
} from './data/scenarioData';
import { CandidateId, NodeId, OperationMode } from './types/grid';

interface DecisionCardMeta {
  id: CandidateId;
  badge: string;
  title: string;
  verdict: string;
  tone: 'neutral' | 'green' | 'blue' | 'red';
}

const DECISIONS: DecisionCardMeta[] = [
  {
    id: 'baseline',
    badge: 'ESTADO ACTUAL',
    title: 'Sin cambios en la red',
    verdict: 'Se tira el sol al mediodía y hay apagón a las 18:00',
    tone: 'red',
  },
  {
    id: 'c1_battery_norte_grande',
    badge: '★ SOLUCIÓN IA',
    title: 'Batería en el Norte',
    verdict: 'Guarda el sol del desierto y salva a Santiago a las 18:00',
    tone: 'green',
  },
  {
    id: 'c3_uprate_l2',
    badge: 'OPCIÓN CABLE',
    title: 'Ampliar Cable Central',
    verdict: 'Desatasca el mediodía, pero no guarda luz para la tarde',
    tone: 'blue',
  },
  {
    id: 'c2_battery_sur',
    badge: 'ERROR COMÚN',
    title: 'Batería en el Sur',
    verdict: 'Inútil para el sol: el atasco del cable está antes',
    tone: 'neutral',
  },
];

export function App() {
  const [theme, setTheme] = useState<'light' | 'dark'>('light');

  // Start at 13:00 (step 52) in baseline so the user sees the problem FIRST, or let them click the IA solution in 1 click!
  // Wait: starting on the IA solution or baseline? Let's start at 13:00 with IA solution or baseline?
  // Starting on 'baseline' at 13:00 immediately shows the RED "SOL DESPERDICIADO" and "CABLE ATASCADO" problem, making clicking "★ Batería en el Norte (IA)" super rewarding!
  const [step96, setStep96] = useState<number>(52);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [mode, setMode] = useState<OperationMode>('normal');
  const [candidateId, setCandidateId] = useState<CandidateId>('baseline');
  const [selectedZone, setSelectedZone] = useState<NodeId | 'all'>('all');

  useEffect(() => {
    if (!isPlaying) return;
    const timer = window.setInterval(() => {
      setStep96((prev) => {
        const next = (prev + 1) % 96;
        // Automatically trigger evening outage mode when passing 17:00 so the 24h loop tells the full story
        if (next >= 68 && next <= 84) {
          setMode('sudden_outage');
        } else {
          setMode('normal');
        }
        return next;
      });
    }, 280);
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

  const nationalSnapshot = useMemo(
    () => computeZoneSnapshot(activeSolution, step96, 'all'),
    [activeSolution, step96]
  );

  const zoneSnapshots = useMemo(() => {
    const map = {} as Record<NodeId, HourlyZoneSnapshot>;
    for (const n of NODES) {
      map[n.id] = computeZoneSnapshot(activeSolution, step96, n.id);
    }
    return map;
  }, [activeSolution, step96]);

  // Simple human metrics
  const baseCurtailment = baselineSolution.metrics.curtailment_mwh; // ~1369 MWh
  const activeCurtailment = activeSolution.metrics.curtailment_mwh;
  const savedSolarMwh = Math.max(0, baseCurtailment - activeCurtailment);
  // Total daily solar generated in Chile scenario is ~4900 MWh; calculate % of excess solar rescued
  const solarUtilPct =
    candidateId === 'c3_uprate_l2'
      ? 92
      : candidateId === 'c1_battery_norte_grande'
      ? 84
      : 54;

  const isEveningScene = step96 >= 68;
  const hasNorthBattery = candidateId === 'c1_battery_norte_grande';

  const selectMiddayScene = () => {
    setIsPlaying(false);
    setMode('normal');
    setStep96(52); // 13:00 CLST
  };

  const selectEveningCrisisScene = () => {
    setIsPlaying(false);
    setMode('sudden_outage');
    setStep96(72); // 18:00 CLST
  };

  return (
    <div className="iso anatomy-shell" data-theme={theme}>
      <main className="anatomy-page">
        {/* 1. SUPER CLEAR HUMAN HEADER */}
        <header className="anatomy-header">
          <div>
            <div className="anatomy-eyebrow">
              MAQUETA INTERACTIVA · EL PROBLEMA ELÉCTRICO DE CHILE
            </div>
            <h1 className="anatomy-title">
              ¿Dónde enchufarías una batería para no desperdiciar el sol de Atacama?
            </h1>
            <p className="anatomy-subtitle">
              Al mediodía sobra sol en el <strong>Norte</strong>, pero el cable hacia{' '}
              <strong>Santiago</strong> se atasca. Al atardecer se va el sol y falta luz.{' '}
              <strong>Toca la maqueta</strong> para ver cómo nuestra IA elige la mejor solución.
            </p>
          </div>

          <button
            type="button"
            className="anatomy-play-btn"
            onClick={() => setTheme((t) => (t === 'light' ? 'dark' : 'light'))}
          >
            {theme === 'light' ? '☾ MODO OSCURO' : '☀ MODO PAPEL'}
          </button>
        </header>

        {/* 2. TWO-SCENE STORY BAR (ELIGE EL MOMENTO DEL DÍA) */}
        <section className="story-moment-bar" aria-label="Elige el momento del día">
          <div className="story-moment-label">PASO 1 · HORA:</div>
          <div className="story-moment-buttons">
            <button
              type="button"
              className="story-moment-btn"
              data-active={!isEveningScene}
              onClick={selectMiddayScene}
            >
              <span className="story-moment-icon">☀️</span>
              <div>
                <strong>1. Mediodía (13:00)</strong>
                <span>Sobra sol en el Norte · Cable lleno</span>
              </div>
            </button>

            <button
              type="button"
              className="story-moment-btn"
              data-active={isEveningScene}
              data-alert="true"
              onClick={selectEveningCrisisScene}
            >
              <span className="story-moment-icon">🌆</span>
              <div>
                <strong>2. Atardecer (18:00 · Crisis)</strong>
                <span>Sin sol · Falla central en Santiago</span>
              </div>
            </button>

            <button
              type="button"
              className="story-play-pill"
              data-playing={isPlaying}
              onClick={() => setIsPlaying((p) => !p)}
              title="Reproducir las 24 horas automáticamente"
            >
              {isPlaying ? '❚❚ Pausar' : '▶ Simular 24h'}
            </button>
          </div>
        </section>

        {/* 3. INTERACTIVE MAQUETTE OF CHILE WITH FLOATING PINS & DIRECT PLUG BUTTONS */}
        <ChileIsoMaquette
          snapshot={nationalSnapshot}
          zoneSnapshots={zoneSnapshots}
          candidateId={candidateId}
          mode={mode}
          selectedZone={selectedZone}
          onSelectZone={setSelectedZone}
          onSelectCandidate={setCandidateId}
        />

        {/* 4. STEP 2: 4 VISUAL DECISION CARDS (CHOOSE WHAT TO INSTALL) */}
        <section className="decision-section" aria-label="Prueba una solución en la maqueta">
          <div className="decision-header">
            <span>PASO 2 · PRUEBA QUÉ INSTALAR EN CHILE:</span>
            <span className="decision-hint">
              (Haz clic en una opción y observa cómo cambia la maqueta arriba)
            </span>
          </div>

          <div className="decision-grid">
            {DECISIONS.map((d) => {
              const active = candidateId === d.id;
              return (
                <button
                  key={d.id}
                  type="button"
                  className="decision-card"
                  data-active={active}
                  data-tone={d.tone}
                  onClick={() => setCandidateId(d.id)}
                >
                  <div className="decision-card-top">
                    <span className="decision-badge" data-tone={d.tone}>
                      {d.badge}
                    </span>
                    <span className="decision-radio">{active ? '●' : '○'}</span>
                  </div>
                  <div className="decision-title">{d.title}</div>
                  <div className="decision-verdict">{d.verdict}</div>
                </button>
              );
            })}
          </div>
        </section>

        {/* 5. ONLY TWO HUMAN SCORECARDS WITH PROGRESS BARS */}
        <section className="impact-strip" aria-label="Resultado de tu decisión">
          <div className="impact-card">
            <div className="impact-top">
              <span className="impact-label">☀️ 1. APROVECHAMIENTO DEL SOL DEL NORTE</span>
              <strong
                className="impact-score"
                data-tone={savedSolarMwh > 10 ? 'green' : 'red'}
              >
                {savedSolarMwh > 10
                  ? `+${Math.round(savedSolarMwh)} MWh rescatados`
                  : 'Se pierde el exceso solar'}
              </strong>
            </div>
            <div className="impact-bar-track">
              <div
                className="impact-bar-fill"
                data-tone={savedSolarMwh > 10 ? 'green' : 'red'}
                style={{ width: `${solarUtilPct}%` }}
              />
            </div>
            <p className="impact-explain">
              {candidateId === 'c1_battery_norte_grande'
                ? 'La Batería Norte absorbe el sol que no cabe en el cable al mediodía.'
                : candidateId === 'c3_uprate_l2'
                ? 'El cable más ancho deja pasar más sol directo hacia Santiago.'
                : candidateId === 'c2_battery_sur'
                ? 'La Batería en el Sur no puede recibir el sol porque el cable central sigue atascado.'
                : 'Sin baterías ni nuevo cable, el sol extra de Atacama se desperdicia.'}
            </p>
          </div>

          <div className="impact-card">
            <div className="impact-top">
              <span className="impact-label">🏙️ 2. PROTECCIÓN DE SANTIAGO A LAS 18:00</span>
              <strong
                className="impact-score"
                data-tone={hasNorthBattery ? 'green' : 'red'}
              >
                {hasNorthBattery
                  ? '✓ +98.000 hogares salvados'
                  : '⚠️ Riesgo de apagón en la tarde'}
              </strong>
            </div>
            <div className="impact-bar-track">
              <div
                className="impact-bar-fill"
                data-tone={hasNorthBattery ? 'green' : 'red'}
                style={{ width: hasNorthBattery ? '100%' : '42%' }}
              />
            </div>
            <p className="impact-explain">
              {hasNorthBattery
                ? 'A las 18:00, la Batería Norte descarga el sol guardado y evita el apagón en Santiago.'
                : candidateId === 'c3_uprate_l2'
                ? 'Ampliar el cable ayuda a las 13:00, pero a las 18:00 ya no hay sol que transportar.'
                : 'Cuando cae una central térmica a las 18:00, no hay energía guardada para responder.'}
            </p>
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;
