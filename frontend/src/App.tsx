import React, { useEffect, useMemo, useState } from 'react';
import {
  ChileIsoMaquette,
  GridSandboxState,
  StationId,
} from './components/ChileIsoMaquette';

export function App() {
  const [theme, setTheme] = useState<'light' | 'dark'>('light');

  // 4 Simple Game Controls that the user alters in real time
  const [sunPct, setSunPct] = useState<number>(95); // 0..100%
  const [demandMw, setDemandMw] = useState<number>(420); // 300..850 MW
  const [cableCapMw, setCableCapMw] = useState<number>(420); // 300..650 MW
  const [thermalBroken, setThermalBroken] = useState<boolean>(false);
  const [agentEnabled, setAgentEnabled] = useState<boolean>(true);
  const [selectedStation, setSelectedStation] = useState<StationId | null>(null);

  // Live battery charge level that evolves smoothly when charging/discharging
  const [batterySocPct, setBatterySocPct] = useState<number>(62);

  // Compute real-time grid physics & AI Agent response from the 4 controls
  const sandboxState: GridSandboxState = useMemo(() => {
    const solarAvailableMw = Math.round((sunPct / 100) * 700); // up to 700 MW solar
    const windOutputMw = 140; // steady 140 MW wind
    const maxThermalMw = thermalBroken ? 0 : 320;

    // Step 1: How much solar + wind can pass through the central cable toward the houses?
    const rawCleanGen = solarAvailableMw + windOutputMw;

    let batteryFlowMw = 0; // negative = charging, positive = discharging
    let solarWastedMw = 0;
    let cableFlowMw = 0;
    let thermalOutputMw = 0;
    let housesServedMw = 0;
    let housesBlackoutMw = 0;

    let agentActionTitle = '';
    let agentActionReason = '';
    let agentTone: 'green' | 'blue' | 'red' | 'neutral' = 'green';

    // Check if there is excess solar blocked by the cable OR excess solar above house demand
    const maxDeliverableViaCable = Math.min(rawCleanGen, cableCapMw);
    const excessSolarAtSource = Math.max(0, rawCleanGen - maxDeliverableViaCable);

    // Deficit at the neighborhood if only clean energy + available thermal is used
    const totalPossibleToHouses = Math.min(
      cableCapMw,
      rawCleanGen + maxThermalMw
    );
    const deficitWithoutBattery = Math.max(0, demandMw - totalPossibleToHouses);

    if (agentEnabled) {
      if (deficitWithoutBattery > 5 && batterySocPct > 5) {
        // AI AGENT EMERGENCY DISCHARGE: Inject battery power directly to save the neighborhood!
        const neededFromBattery = Math.min(380, deficitWithoutBattery);
        batteryFlowMw = neededFromBattery;
        cableFlowMw = totalPossibleToHouses;
        thermalOutputMw = Math.min(
          maxThermalMw,
          Math.max(0, cableFlowMw - rawCleanGen)
        );
        housesServedMw = Math.min(demandMw, cableFlowMw + batteryFlowMw);
        housesBlackoutMw = Math.max(0, demandMw - housesServedMw);

        agentTone = housesBlackoutMw > 5 ? 'red' : 'blue';
        agentActionTitle = `⚡ Agente IA inyectando +${Math.round(
          batteryFlowMw
        )} MW desde la batería hacia el barrio`;
        agentActionReason = thermalBroken
          ? 'Detectó la avería en la Central Térmica y activó el respaldo instantáneo para evitar el apagón en las casas.'
          : 'El cable central llegó a su límite; el Agente IA suple el pico de consumo de las casas con energía guardada.';
      } else if (excessSolarAtSource > 10 && batterySocPct < 99) {
        // AI AGENT SMART CHARGE: Absorb excess solar that doesn't fit in the cable!
        const absorbedMw = Math.min(420, excessSolarAtSource);
        batteryFlowMw = -absorbedMw; // charging
        solarWastedMw = Math.max(0, excessSolarAtSource - absorbedMw);
        cableFlowMw = Math.min(demandMw, maxDeliverableViaCable);
        thermalOutputMw = Math.min(
          maxThermalMw,
          Math.max(0, demandMw - cableFlowMw)
        );
        housesServedMw = Math.min(demandMw, cableFlowMw + thermalOutputMw);
        housesBlackoutMw = Math.max(0, demandMw - housesServedMw);

        agentTone = 'green';
        agentActionTitle = `🔋 Agente IA desviando +${Math.round(
          absorbedMw
        )} MW solares a la batería`;
        agentActionReason =
          'El cable central está lleno. En lugar de desperdiciar el sol sobrante de Atacama, el Agente lo almacena para la noche.';
      } else {
        // Balanced grid: AI optimizes clean dispatch & minimizes gas
        cableFlowMw = Math.min(demandMw, maxDeliverableViaCable);
        const remainingDemand = Math.max(0, demandMw - cableFlowMw);
        if (remainingDemand > 0 && batterySocPct > 25 && sunPct < 40) {
          // Use battery before burning gas at night
          batteryFlowMw = Math.min(180, remainingDemand);
        }
        thermalOutputMw = Math.min(
          maxThermalMw,
          Math.max(0, demandMw - cableFlowMw - Math.max(0, batteryFlowMw))
        );
        housesServedMw = Math.min(
          demandMw,
          cableFlowMw + thermalOutputMw + Math.max(0, batteryFlowMw)
        );
        housesBlackoutMw = Math.max(0, demandMw - housesServedMw);
        solarWastedMw = Math.max(0, rawCleanGen - cableFlowMw);

        agentTone = 'green';
        agentActionTitle =
          batteryFlowMw > 5
            ? `🌙 Agente IA alimentando casas con sol nocturno (+${Math.round(
                batteryFlowMw
              )} MW)`
            : '✅ Agente IA equilibrando el flujo hacia el barrio (100% cubierto)';
        agentActionReason =
          batteryFlowMw > 5
            ? 'Prioriza descargar energía limpia de la batería antes de encender más gas.'
            : 'Red estable: toda la demanda del barrio se cubre sin atascos ni cortes.';
      }
    } else {
      // AI AGENT DISABLED: No battery intervention!
      batteryFlowMw = 0;
      cableFlowMw = Math.min(demandMw, maxDeliverableViaCable);
      thermalOutputMw = Math.min(
        maxThermalMw,
        Math.max(0, Math.min(cableCapMw, demandMw) - cableFlowMw)
      );
      cableFlowMw = Math.min(cableCapMw, cableFlowMw + thermalOutputMw);
      housesServedMw = Math.min(demandMw, cableFlowMw);
      housesBlackoutMw = Math.max(0, demandMw - housesServedMw);
      solarWastedMw = Math.max(0, solarAvailableMw - Math.max(0, cableFlowMw - windOutputMw));

      agentTone = 'neutral';
      agentActionTitle = '⚠️ Agente IA desactivado (Red sin control inteligente)';
      agentActionReason =
        housesBlackoutMw > 5
          ? `¡Se apagaron casas! Faltan ${Math.round(
              housesBlackoutMw
            )} MW en el barrio porque la batería está desconectada.`
          : solarWastedMw > 10
          ? `Se están tirando a la basura ${Math.round(
              solarWastedMw
            )} MW de sol porque nadie los guarda en la batería.`
          : 'Activa el Agente IA para que gestione automáticamente los excesos y cortes.';
    }

    const solarUsedMw = Math.max(0, solarAvailableMw - solarWastedMw);
    const cableUtilPct = Math.min(100, (cableFlowMw / cableCapMw) * 100);
    const cableSaturated = cableUtilPct >= 97;
    const housesLitPct =
      demandMw > 0 ? Math.min(100, (housesServedMw / demandMw) * 100) : 100;

    return {
      sunPct,
      demandMw,
      cableCapMw,
      thermalBroken,
      agentEnabled,
      solarAvailableMw,
      solarUsedMw,
      solarWastedMw,
      thermalOutputMw,
      windOutputMw,
      batteryFlowMw,
      batterySocPct,
      cableFlowMw,
      cableUtilPct,
      cableSaturated,
      housesServedMw,
      housesBlackoutMw,
      housesLitPct,
      agentActionTitle,
      agentActionReason,
      agentTone,
    };
  }, [sunPct, demandMw, cableCapMw, thermalBroken, agentEnabled, batterySocPct]);

  // Animate battery SOC % slowly in real time as it charges or discharges
  useEffect(() => {
    if (!agentEnabled || Math.abs(sandboxState.batteryFlowMw) < 5) return;
    const timer = window.setInterval(() => {
      setBatterySocPct((prev) => {
        const delta = sandboxState.batteryFlowMw < 0 ? 1.2 : -1.2;
        const next = prev + delta;
        if (next > 96) return 28; // loop smoothly for continuous visual feedback
        if (next < 12) return 85;
        return next;
      });
    }, 350);
    return () => window.clearInterval(timer);
  }, [agentEnabled, sandboxState.batteryFlowMw]);

  // Quick 1-click preset situations
  const applyPreset = (preset: 'sunny_bottleneck' | 'night_crisis' | 'peak_storm') => {
    if (preset === 'sunny_bottleneck') {
      setSunPct(95);
      setDemandMw(420);
      setCableCapMw(420);
      setThermalBroken(false);
    } else if (preset === 'night_crisis') {
      setSunPct(0);
      setDemandMw(390);
      setCableCapMw(480);
      setThermalBroken(true);
    } else if (preset === 'peak_storm') {
      setSunPct(35);
      setDemandMw(720);
      setCableCapMw(500);
      setThermalBroken(false);
    }
  };

  return (
    <div className="iso anatomy-shell" data-theme={theme}>
      <main className="anatomy-page">
        {/* 1. MINIMALIST HEADER + QUICK SITUATIONS */}
        <header className="anatomy-header">
          <div>
            <div className="anatomy-eyebrow">
              SIMULADOR INTERACTIVO · RED ELÉCTRICA Y AGENTE IA
            </div>
            <h1 className="anatomy-title">
              Pon a prueba al Agente IA de la Red Eléctrica
            </h1>
            <p className="anatomy-subtitle">
              Altera el <strong>sol</strong>, el <strong>consumo del barrio</strong> o provoca una{' '}
              <strong>avería en la planta térmica</strong> y observa en el esquema 3D cómo reacciona el{' '}
              <strong>Agente IA</strong> en tiempo real para llevar luz a las casas.
            </p>
          </div>

          <div className="header-actions">
            <button
              type="button"
              className="anatomy-play-btn"
              onClick={() => setTheme((t) => (t === 'light' ? 'dark' : 'light'))}
            >
              {theme === 'light' ? '☾ MODO OSCURO' : '☀ MODO PAPEL'}
            </button>
          </div>
        </header>

        {/* QUICK PRESET SCENARIOS */}
        <section className="preset-bar" aria-label="Situaciones rápidas">
          <span className="preset-label">SITUACIONES RÁPIDAS:</span>
          <div className="preset-buttons">
            <button
              type="button"
              className="preset-pill"
              onClick={() => applyPreset('sunny_bottleneck')}
            >
              ☀️ 1. Mediodía: Exceso de Sol y Cable Atascado
            </button>
            <button
              type="button"
              className="preset-pill"
              onClick={() => applyPreset('night_crisis')}
            >
              💥 2. Noche: Avería en Planta Térmica
            </button>
            <button
              type="button"
              className="preset-pill"
              onClick={() => applyPreset('peak_storm')}
            >
              🏘️ 3. Pico Máximo de Consumo en el Barrio
            </button>
          </div>
        </section>

        {/* 2. BIG SCHEMATIC 3D MAQUETTE (PLANTS -> AI BATTERY & GRID -> HOUSES) */}
        <ChileIsoMaquette
          state={sandboxState}
          selectedStation={selectedStation}
          onSelectStation={setSelectedStation}
          onToggleThermalBreak={() => setThermalBroken((b) => !b)}
          onToggleAgent={() => setAgentEnabled((a) => !a)}
        />

        {/* 3. REAL-TIME AI AGENT REACTION BANNER */}
        <section
          className="agent-live-banner"
          data-tone={sandboxState.agentTone}
          aria-label="Respuesta del Agente IA en tiempo real"
        >
          <div className="agent-live-left">
            <span className="agent-live-tag">REACCIÓN DEL AGENTE IA EN TIEMPO REAL</span>
            <strong className="agent-live-title">
              {sandboxState.agentActionTitle}
            </strong>
            <p className="agent-live-reason">{sandboxState.agentActionReason}</p>
          </div>

          <button
            type="button"
            className="agent-toggle-btn"
            data-active={agentEnabled}
            onClick={() => setAgentEnabled((a) => !a)}
          >
            {agentEnabled ? '🤖 Agente IA: ACTIVADO' : '⚠️ Agente IA: APAGADO (Activar)'}
          </button>
        </section>

        {/* 4. FEW SIMPLE GAME PARAMETERS (MUEVE LOS VALORES Y MIRA CÓMO REACCIONA) */}
        <section className="sandbox-controls" aria-label="Parámetros de la red">
          {/* SLIDER 1: SUN INTENSITY */}
          <div className="control-card">
            <div className="control-top">
              <label htmlFor="slider-sun">☀️ 1. Sol en Planta Solar</label>
              <strong>{sunPct}% ({sandboxState.solarAvailableMw} MW)</strong>
            </div>
            <input
              id="slider-sun"
              type="range"
              min={0}
              max={100}
              step={5}
              value={sunPct}
              onChange={(e) => setSunPct(Number(e.target.value))}
              className="anatomy-range"
            />
            <div className="control-Ends">
              <span>☾ Noche (0%)</span>
              <span>☀️ Sol Máximo (100%)</span>
            </div>
          </div>

          {/* SLIDER 2: NEIGHBORHOOD HOUSE DEMAND */}
          <div className="control-card">
            <div className="control-top">
              <label htmlFor="slider-demand">🏘️ 2. Consumo del Barrio (Casas)</label>
              <strong>{demandMw} MW</strong>
            </div>
            <input
              id="slider-demand"
              type="range"
              min={300}
              max={850}
              step={20}
              value={demandMw}
              onChange={(e) => setDemandMw(Number(e.target.value))}
              className="anatomy-range"
            />
            <div className="control-Ends">
              <span>Bajo (300 MW)</span>
              <span>Pico en Casas (850 MW)</span>
            </div>
          </div>

          {/* SLIDER 3: CENTRAL CABLE CAPACITY */}
          <div className="control-card">
            <div className="control-top">
              <label htmlFor="slider-cable">⚡ 3. Capacidad del Cable Central</label>
              <strong>{cableCapMw} MW máx.</strong>
            </div>
            <input
              id="slider-cable"
              type="range"
              min={300}
              max={650}
              step={25}
              value={cableCapMw}
              onChange={(e) => setCableCapMw(Number(e.target.value))}
              className="anatomy-range"
            />
            <div className="control-Ends">
              <span>Cuello estrecho (300)</span>
              <span>Cable amplio (650)</span>
            </div>
          </div>

          {/* BUTTON 4: SABOTAGE / BREAK THERMAL PLANT */}
          <div className="control-card control-card--button">
            <div className="control-top">
              <span>🔥 4. Estado Planta Térmica</span>
              <strong
                style={{
                  color: thermalBroken
                    ? 'var(--anatomy-red)'
                    : 'var(--anatomy-green)',
                }}
              >
                {thermalBroken ? '💥 AVERIADA (0 MW)' : '✓ Operativa (320 MW)'}
              </strong>
            </div>
            <button
              type="button"
              className="sabotage-btn"
              data-broken={thermalBroken}
              onClick={() => setThermalBroken((b) => !b)}
            >
              {thermalBroken
                ? '🔧 Reparar Central Térmica'
                : '💥 Provocar Avería en Central Térmica'}
            </button>
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;
