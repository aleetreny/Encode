import React, { useState, useEffect, useReducer, useRef, useCallback } from 'react';
import type {
  LiveEvent,
  LiveSessionHook,
  LiveSessionState,
  Disruption,
  Solution,
  ValidationSummary,
  ClockCommandRequest,
  DisruptCommandRequest,
  JuryDisruptCommandRequest,
  DecideCommandRequest,
  Option,
} from './types';
import demoStreamRaw from './fixtures/demo-stream.jsonl?raw';

function parseDemoStreamEvents(): LiveEvent[] {
  return demoStreamRaw
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line) as LiveEvent);
}

function createDefaultLiveState(sessionId: string): LiveSessionState {
  return {
    sessionId,
    lastSeq: -1,
    catalog: null,
    grid_state: 'normal',
    clock: {
      sim_hour: 12,
      running: true,
      speed_hours_per_sec: 0.25,
      autonomy_mode: false,
    },
    active_incidents: [],
    solution: null,
    validation: null,
    comparison: null,
    agent_status: {
      phase: 'idle',
      detail_es: 'Sistema operando en estado normal',
      started_at_utc: null,
    },
    thoughts: [],
    tool_calls: [],
    options: null,
    countdown: null,
    notes: [],
  };
}

function sessionReducer(state: LiveSessionState, event: LiveEvent): LiveSessionState {
  if (event.seq <= state.lastSeq && event.type !== 'session.snapshot') {
    return state;
  }
  const next = { ...state, lastSeq: Math.max(state.lastSeq, event.seq) };

  switch (event.type) {
    case 'session.snapshot':
      return {
        ...state,
        sessionId: event.session_id,
        lastSeq: event.seq,
        catalog: event.catalog,
        solution: event.solution,
        grid_state: event.grid_state,
        active_incidents: event.active_events,
        clock: {
          sim_hour: event.clock.hour,
          running: event.clock.running,
          speed_hours_per_sec: event.clock.speed_s_per_hour ? 1 / event.clock.speed_s_per_hour : 0.25,
          autonomy_mode: event.autonomy,
        },
      };

    case 'clock.tick':
      return {
        ...next,
        clock: {
          ...next.clock,
          running: event.running,
          sim_hour: event.hour !== undefined ? event.hour : next.clock.sim_hour,
        },
      };

    case 'incident.detected': {
      const exists = next.active_incidents.some((i) => i.event_id === event.disruption.event_id);
      return {
        ...next,
        active_incidents: exists ? next.active_incidents : [...next.active_incidents, event.disruption],
        clock: { ...next.clock, sim_hour: event.hour },
        agent_status: {
          phase: 'analyzing',
          detail_es: `Incidente detectado en ${event.disruption.asset_id}`,
          started_at_utc: event.ts_utc,
        },
      };
    }

    case 'solution.updated':
      return {
        ...next,
        solution: event.solution,
        grid_state: event.grid_state,
        validation: event.solution?.validation || null,
        agent_status:
          event.reason === 'plan_applied'
            ? { ...next.agent_status, phase: 'executing', detail_es: 'Plan de mitigación aplicado' }
            : event.reason === 'event_ended'
            ? { ...next.agent_status, phase: 'resolved', detail_es: 'Evento finalizado' }
            : next.agent_status,
      };

    case 'agent.thought':
      return {
        ...next,
        agent_status: { ...next.agent_status, detail_es: event.delta },
        thoughts: [...next.thoughts.slice(-49), { text_es: event.delta, ts_utc: event.ts_utc, sim_hour: event.hour }],
      };

    case 'agent.tool_call':
      return {
        ...next,
        tool_calls: [...next.tool_calls.slice(-49), event],
      };

    case 'options.ready':
      return {
        ...next,
        options: event.options,
        agent_status: {
          phase: 'awaiting_operator',
          detail_es: event.diagnosis_es,
          started_at_utc: next.agent_status.started_at_utc,
        },
        countdown: { candidate_id: event.recommended_id, seconds_left: 0, active: false },
      };

    case 'autonomy.countdown':
      return {
        ...next,
        countdown: { candidate_id: event.option_id, seconds_left: event.seconds_left, active: event.seconds_left > 0 },
      };

    case 'plan.applied':
      return {
        ...next,
        countdown: null,
        agent_status: {
          phase: 'executing',
          detail_es: `Plan ${event.option_id} aplicado por ${event.by}`,
          started_at_utc: next.agent_status.started_at_utc,
        },
      };

    case 'plan.vetoed':
      return {
        ...next,
        countdown: null,
        agent_status: {
          phase: 'idle',
          detail_es: `Plan ${event.option_id} vetado`,
          started_at_utc: next.agent_status.started_at_utc,
        },
      };

    case 'event.ended':
      return {
        ...next,
        active_incidents: next.active_incidents.filter((i) => i.event_id !== event.event_id),
      };

    case 'agent.note':
      return {
        ...next,
        notes: [...next.notes.slice(-49), { text_es: event.text_es, ts_utc: event.ts_utc, sim_hour: event.hour }],
      };

    case 'error':
      return {
        ...next,
        agent_status: { ...next.agent_status, detail_es: `Error: ${event.message_es}` },
      };

    default:
      return next;
  }
}

function useBuiltinDevLiveSession(defaultSessionId?: string): LiveSessionHook {
  const [resolvedSessionId, setResolvedSessionId] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      const sp = new URLSearchParams(window.location.search);
      return sp.get('session') || sp.get('s') || defaultSessionId || 'demo';
    }
    return defaultSessionId || 'demo';
  });

  const [state, dispatch] = useReducer(sessionReducer, createDefaultLiveState(resolvedSessionId));
  const [connectionMode, setConnectionMode] = useState<'live' | 'offline' | 'connecting'>('connecting');
  const [connected, setConnected] = useState(false);
  const [interpolatedSimHour, setInterpolatedSimHour] = useState(state.clock.sim_hour);

  const lastTimeRef = useRef(performance.now());
  const hourRef = useRef(state.clock.sim_hour);
  const replayTimerRef = useRef<any>(null);

  useEffect(() => {
    hourRef.current = state.clock.sim_hour;
    setInterpolatedSimHour(state.clock.sim_hour);
  }, [state.clock.sim_hour]);

  useEffect(() => {
    let animId: number;
    const loop = (now: number) => {
      const deltaSec = (now - lastTimeRef.current) / 1000;
      lastTimeRef.current = now;
      if (state.clock.running) {
        hourRef.current = (hourRef.current + deltaSec * state.clock.speed_hours_per_sec) % 24;
        if (hourRef.current < 0) hourRef.current += 24;
        setInterpolatedSimHour(hourRef.current);
      }
      animId = requestAnimationFrame(loop);
    };
    animId = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(animId);
  }, [state.clock.running, state.clock.speed_hours_per_sec]);

  const replayOfflineDemo = useCallback(() => {
    if (replayTimerRef.current) clearInterval(replayTimerRef.current);
    const events = parseDemoStreamEvents();
    if (events.length === 0) return;

    setConnectionMode('offline');
    setConnected(true);

    const snapshot = events.find((e) => e.type === 'session.snapshot') || events[0];
    dispatch(snapshot);

    let idx = 1;
    replayTimerRef.current = setInterval(() => {
      if (idx < events.length) {
        dispatch(events[idx]);
        idx++;
      } else {
        clearInterval(replayTimerRef.current);
      }
    }, 1500);
  }, []);

  useEffect(() => {
    let active = true;
    let eventSource: EventSource | null = null;

    async function initSession() {
      try {
        const streamUrl = `/api/live/sessions/${resolvedSessionId}/stream`;
        eventSource = new EventSource(streamUrl);

        eventSource.onopen = () => {
          if (!active) return;
          setConnected(true);
          setConnectionMode('live');
        };

        eventSource.onmessage = (msg) => {
          if (!active) return;
          try {
            const ev = JSON.parse(msg.data) as LiveEvent;
            dispatch(ev);
          } catch (e) {
            console.error('Error parsing live SSE event', e);
          }
        };

        eventSource.onerror = () => {
          if (!active) return;
          if (eventSource) {
            eventSource.close();
            eventSource = null;
          }
          replayOfflineDemo();
        };
      } catch (err) {
        if (!active) return;
        replayOfflineDemo();
      }
    }

    initSession();

    return () => {
      active = false;
      if (eventSource) eventSource.close();
      if (replayTimerRef.current) clearInterval(replayTimerRef.current);
    };
  }, [resolvedSessionId, replayOfflineDemo]);

  const actions = {
    setClock: async (cmd: ClockCommandRequest) => {
      if (connectionMode === 'live') {
        await fetch(`/api/live/sessions/${resolvedSessionId}/clock`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(cmd),
        });
      } else {
        if (cmd.action === 'play') dispatch({ seq: Date.now(), session_id: resolvedSessionId, hour: state.clock.sim_hour, ts_utc: new Date().toISOString(), type: 'clock.tick', running: true });
        if (cmd.action === 'pause') dispatch({ seq: Date.now(), session_id: resolvedSessionId, hour: state.clock.sim_hour, ts_utc: new Date().toISOString(), type: 'clock.tick', running: false });
        if (cmd.action === 'seek' && cmd.hour !== undefined) {
          dispatch({ seq: Date.now(), session_id: resolvedSessionId, hour: cmd.hour, ts_utc: new Date().toISOString(), type: 'clock.tick', running: state.clock.running });
        }
      }
    },
    injectEvent: async (cmd: DisruptCommandRequest) => {
      if (connectionMode === 'live') {
        await fetch(`/api/live/sessions/${resolvedSessionId}/disrupt`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(cmd),
        });
      } else {
        const syntheticDisruption: Disruption = {
          event_id: `ev-op-${Date.now()}`,
          type: cmd.asset_id.startsWith('L') ? 'line_outage' : 'generator_outage',
          asset_id: cmd.asset_id,
          from_hour: Math.floor(interpolatedSimHour),
          to_hour: Math.floor(interpolatedSimHour) + (cmd.duration_h || 4),
          source: cmd.source || 'operator',
        };
        dispatch({
          seq: Date.now(),
          session_id: resolvedSessionId,
          hour: interpolatedSimHour,
          ts_utc: new Date().toISOString(),
          type: 'incident.detected',
          incident_id: `inc-${cmd.asset_id}`,
          disruption: syntheticDisruption,
          impact: {
            unserved_mw_peak: 350,
            households_off_peak: 350000,
            nodes_affected: ['n_centro'],
            lines_overloaded: [],
          },
        });
      }
    },
    submitJuryAction: async (cmd: JuryDisruptCommandRequest) => {
      if (connectionMode === 'live') {
        return await fetch(`/api/live/sessions/${resolvedSessionId}/jury`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(cmd),
        });
      } else {
        return new Response(JSON.stringify({ ok: true }), { status: 202 });
      }
    },
    submitOperatorDecision: async (cmd: DecideCommandRequest) => {
      if (connectionMode === 'live') {
        await fetch(`/api/live/sessions/${resolvedSessionId}/decide`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(cmd),
        });
      } else {
        if (cmd.decision === 'apply') {
          dispatch({
            seq: Date.now(),
            session_id: resolvedSessionId,
            hour: interpolatedSimHour,
            ts_utc: new Date().toISOString(),
            type: 'plan.applied',
            incident_id: cmd.incident_id,
            option_id: cmd.option_id,
            by: 'operator',
          });
        } else {
          dispatch({
            seq: Date.now(),
            session_id: resolvedSessionId,
            hour: interpolatedSimHour,
            ts_utc: new Date().toISOString(),
            type: 'plan.vetoed',
            incident_id: cmd.incident_id,
            option_id: cmd.option_id,
          });
        }
      }
    },
    vetoCountdown: async (incidentId: string, optionId: string) => {
      await actions.submitOperatorDecision({ incident_id: incidentId, option_id: optionId, decision: 'veto' });
    },
    switchMode: (mode: 'live' | 'offline') => {
      setConnectionMode(mode);
      if (mode === 'offline') replayOfflineDemo();
    },
    replayOfflineDemo,
    downloadReportUrl: () => `/api/live/sessions/${resolvedSessionId}/report?format=html`,
  };

  return {
    state,
    catalog: state.catalog,
    connected,
    connectionMode,
    actions,
    interpolatedSimHour,
  };
}

export interface DevConsoleProps {
  sessionHook?: LiveSessionHook;
}

export function DevConsole({ sessionHook }: DevConsoleProps) {
  const builtinHook = useBuiltinDevLiveSession();
  const hook = sessionHook || builtinHook;

  const [speed, setSpeed] = useState('0.25');
  const [autonomyMode, setAutonomyMode] = useState<'autopilot' | 'human_in_loop' | 'manual'>('human_in_loop');

  const handleSpeedChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value;
    setSpeed(val);
    const speedHoursPerSec = parseFloat(val);
    const speedSPerHour = speedHoursPerSec > 0 ? 1 / speedHoursPerSec : 4;
    // Notify server of speed parameter if supported
    if (hook.state.sessionId && hook.connectionMode === 'live') {
      fetch(`/api/live/sessions/${hook.state.sessionId}/clock`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'speed', speed_s_per_hour: speedSPerHour }),
      }).catch(() => {});
    }
  };

  const handleAutonomyChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const mode = e.target.value as 'autopilot' | 'human_in_loop' | 'manual';
    setAutonomyMode(mode);
    const enabled = mode === 'autopilot';
    if (hook.state.sessionId && hook.connectionMode === 'live') {
      fetch(`/api/live/sessions/${hook.state.sessionId}/autonomy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      }).catch(() => {});
    }
  };

  const sessionId = hook.state.sessionId || 'demo';
  const qrUrl = `/api/live/sessions/${sessionId}/qr.svg`;
  const reportUrl = `/api/live/sessions/${sessionId}/report?format=html`;

  const activeIncId = hook.state.active_incidents[0]?.event_id || 'inc-active';

  return (
    <div
      data-testid="dev-console"
      style={{
        padding: '20px',
        fontFamily: 'monospace',
        backgroundColor: '#111827',
        color: '#f3f4f6',
        minHeight: '100vh',
      }}
    >
      <header style={{ borderBottom: '1px solid #374151', paddingBottom: '12px', marginBottom: '20px' }}>
        <h1 style={{ margin: '0 0 8px 0', fontSize: '20px', color: '#60a5fa' }}>
          Andes · Operación de la red eléctrica con IA — Developer Console (/dev)
        </h1>
        <div style={{ display: 'flex', gap: '16px', alignItems: 'center', flexWrap: 'wrap' }}>
          <div>
            <span>Conexión: </span>
            <span
              data-testid="dev-connection-mode"
              style={{
                backgroundColor: hook.connectionMode === 'live' ? '#065f46' : '#78350f',
                color: '#ffffff',
                padding: '2px 8px',
                borderRadius: '4px',
                fontWeight: 'bold',
              }}
            >
              {hook.connectionMode === 'live' ? 'LIVE' : 'OFFLINE REPLAY'}
            </span>
          </div>

          <button
            data-testid="dev-replay-fixture-btn"
            onClick={hook.actions.replayOfflineDemo}
            style={{
              backgroundColor: '#374151',
              color: '#ffffff',
              border: '1px solid #4b5563',
              padding: '4px 10px',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            Replay demo-stream.jsonl
          </button>

          <a
            data-testid="dev-qr-link"
            href={qrUrl}
            target="_blank"
            rel="noreferrer"
            style={{ color: '#93c5fd', textDecoration: 'underline' }}
          >
            Ver QR Jurado
          </a>

          <a
            data-testid="dev-report-link"
            href={reportUrl}
            target="_blank"
            rel="noreferrer"
            style={{ color: '#93c5fd', textDecoration: 'underline' }}
          >
            Descargar Informe RIO
          </a>
        </div>
      </header>

      {/* Clock Controls */}
      <section
        data-testid="dev-clock-controls"
        style={{
          border: '1px solid #374151',
          padding: '12px',
          borderRadius: '6px',
          marginBottom: '20px',
          backgroundColor: '#1f2937',
        }}
      >
        <h2 style={{ margin: '0 0 10px 0', fontSize: '15px', color: '#9ca3af' }}>Control de Reloj y Autonomía</h2>
        <div style={{ display: 'flex', gap: '16px', alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            data-testid="dev-clock-toggle"
            onClick={() => hook.actions.setClock({ action: hook.state.clock.running ? 'pause' : 'play' })}
            style={{
              backgroundColor: hook.state.clock.running ? '#b91c1c' : '#15803d',
              color: '#ffffff',
              border: 'none',
              padding: '6px 14px',
              borderRadius: '4px',
              cursor: 'pointer',
              fontWeight: 'bold',
            }}
          >
            {hook.state.clock.running ? 'Pausar Reloj' : 'Reanudar Reloj'}
          </button>

          <label>
            Velocidad (h/s):{' '}
            <select
              data-testid="dev-clock-speed"
              value={speed}
              onChange={handleSpeedChange}
              style={{
                backgroundColor: '#111827',
                color: '#ffffff',
                border: '1px solid #4b5563',
                padding: '4px 8px',
                borderRadius: '4px',
              }}
            >
              <option value="0.25">0.25 (1h = 4s)</option>
              <option value="0.5">0.5 (1h = 2s)</option>
              <option value="1">1.0 (1h = 1s)</option>
              <option value="2">2.0 (1h = 0.5s)</option>
            </select>
          </label>

          <label>
            Modo Autonomía:{' '}
            <select
              data-testid="dev-autonomy-select"
              value={autonomyMode}
              onChange={handleAutonomyChange}
              style={{
                backgroundColor: '#111827',
                color: '#ffffff',
                border: '1px solid #4b5563',
                padding: '4px 8px',
                borderRadius: '4px',
              }}
            >
              <option value="autopilot">autopilot (Gemini decide y aplica)</option>
              <option value="human_in_loop">human_in_loop (Gemini propone con cuenta regresiva)</option>
              <option value="manual">manual (Operador aprueba exclusivamente)</option>
            </select>
          </label>

          <div style={{ marginLeft: 'auto', fontSize: '14px', color: '#34d399' }}>
            Hora: {hook.interpolatedSimHour.toFixed(2)} hrs ({hook.state.clock.running ? 'CORRIENDO' : 'PAUSADO'})
          </div>
        </div>
      </section>

      {/* Incident & Stress Recipe Injector */}
      <section
        data-testid="dev-incident-injector"
        style={{
          border: '1px solid #374151',
          padding: '12px',
          borderRadius: '6px',
          marginBottom: '20px',
          backgroundColor: '#1f2937',
        }}
      >
        <h2 style={{ margin: '0 0 10px 0', fontSize: '15px', color: '#9ca3af' }}>Inyector de Incidentes y Recetas de Estrés</h2>
        
        <div style={{ marginBottom: '12px' }}>
          <span style={{ fontSize: '12px', color: '#9ca3af', display: 'block', marginBottom: '6px' }}>Generadores:</span>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            {[
              { id: 'gas_centro', label: 'Gas Centro (600 MW)' },
              { id: 'solar_ng', label: 'Solar Crucero (700 MW)' },
              { id: 'coal_cs', label: 'Carbón Coronel (350 MW)' },
              { id: 'gas_ng', label: 'Gas Mejillones (350 MW)' },
              { id: 'hydro_sur', label: 'Ralco Chapo (200 MW)' },
              { id: 'diesel_centro', label: 'Diésel Renca (150 MW)' },
            ].map((gen) => (
              <button
                key={gen.id}
                onClick={() => hook.actions.injectEvent({ asset_id: gen.id, duration_h: 4, source: 'operator' })}
                style={{
                  backgroundColor: '#374151',
                  color: '#e5e7eb',
                  border: '1px solid #4b5563',
                  padding: '4px 8px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '12px',
                }}
              >
                Falla {gen.label}
              </button>
            ))}
          </div>
        </div>

        <div style={{ marginBottom: '12px' }}>
          <span style={{ fontSize: '12px', color: '#9ca3af', display: 'block', marginBottom: '6px' }}>Líneas de Transmisión:</span>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            {[
              { id: 'L1', label: 'L1 Crucero-Cardones (400 MW)' },
              { id: 'L2', label: 'L2 Cardones-Polpaico (400 MW)' },
              { id: 'L3', label: 'L3 Polpaico-Charrúa (350 MW)' },
              { id: 'L4', label: 'L4 Charrúa-P.Montt (300 MW)' },
            ].map((line) => (
              <button
                key={line.id}
                onClick={() => hook.actions.injectEvent({ asset_id: line.id, duration_h: 4, source: 'operator' })}
                style={{
                  backgroundColor: '#374151',
                  color: '#e5e7eb',
                  border: '1px solid #4b5563',
                  padding: '4px 8px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '12px',
                }}
              >
                Corte {line.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <span style={{ fontSize: '12px', color: '#9ca3af', display: 'block', marginBottom: '6px' }}>Recetas de Estrés Compuesto:</span>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            {[
              { id: 'stress_terremoto', label: 'Terremoto Norte (L1 + Gas NG)', asset: 'L1' },
              { id: 'stress_ola_calor', label: 'Ola de Calor Centro (Demanda +20%)', asset: 'gas_centro' },
              { id: 'stress_sequia', label: 'Sequía Sur (Ralco -50%)', asset: 'hydro_sur' },
              { id: 'stress_n_minus_2', label: 'Contingencia N-2 (L2 + L3)', asset: 'L2' },
            ].map((recipe) => (
              <button
                key={recipe.id}
                onClick={() => hook.actions.injectEvent({ asset_id: recipe.asset, duration_h: 4, source: 'operator' })}
                style={{
                  backgroundColor: '#7f1d1d',
                  color: '#fecaca',
                  border: '1px solid #991b1b',
                  padding: '4px 10px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '12px',
                  fontWeight: 'bold',
                }}
              >
                {recipe.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* Live Agent Stream Inspector */}
      <section style={{ border: '1px solid #374151', padding: '12px', borderRadius: '6px', marginBottom: '20px', backgroundColor: '#1f2937' }}>
        <h2 style={{ margin: '0 0 10px 0', fontSize: '15px', color: '#9ca3af' }}>Supervisión del Agente Gemini 4 Argon</h2>

        <div style={{ display: 'flex', gap: '16px', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap' }}>
          <div data-testid="dev-agent-phase" style={{ fontSize: '14px' }}>
            <strong>Fase:</strong>{' '}
            <span style={{ color: '#fbbf24', textTransform: 'uppercase' }}>
              {hook.state.agent_status.phase}
            </span>{' '}
            — {hook.state.agent_status.detail_es}
          </div>

          <div
            data-testid="dev-countdown"
            style={{
              fontSize: '14px',
              backgroundColor: '#111827',
              padding: '4px 10px',
              borderRadius: '4px',
              border: '1px solid #374151',
            }}
          >
            Cuenta regresiva:{' '}
            {hook.state.countdown && hook.state.countdown.active ? (
              <span style={{ color: '#ef4444', fontWeight: 'bold' }}>
                {hook.state.countdown.seconds_left}s (Opción: {hook.state.countdown.candidate_id})
              </span>
            ) : (
              <span style={{ color: '#9ca3af' }}>Inactivo</span>
            )}
          </div>

          <button
            data-testid="dev-veto-btn"
            onClick={() =>
              hook.actions.vetoCountdown(activeIncId, hook.state.countdown?.candidate_id || 'opt-rec')
            }
            disabled={!hook.state.countdown || !hook.state.countdown.active}
            style={{
              backgroundColor: hook.state.countdown?.active ? '#dc2626' : '#4b5563',
              color: '#ffffff',
              border: 'none',
              padding: '6px 14px',
              borderRadius: '4px',
              cursor: hook.state.countdown?.active ? 'pointer' : 'not-allowed',
              fontWeight: 'bold',
            }}
          >
            Veto Gemini Plan
          </button>
        </div>

        {/* Thought Stream */}
        <div style={{ marginBottom: '16px' }}>
          <h3 style={{ margin: '0 0 6px 0', fontSize: '13px', color: '#93c5fd' }}>Flujo de Razonamiento (Thoughts):</h3>
          <div
            data-testid="dev-thoughts"
            style={{
              maxHeight: '120px',
              overflowY: 'auto',
              backgroundColor: '#111827',
              padding: '8px',
              borderRadius: '4px',
              fontSize: '12px',
              border: '1px solid #374151',
            }}
          >
            {hook.state.thoughts.length === 0 ? (
              <span style={{ color: '#6b7280' }}>Sin pensamientos recientes.</span>
            ) : (
              hook.state.thoughts.map((th, i) => (
                <div key={i} style={{ marginBottom: '4px', color: '#e5e7eb' }}>
                  <span style={{ color: '#60a5fa' }}>[{th.sim_hour.toFixed(2)}h]</span> {th.text_es}
                </div>
              ))
            )}
          </div>
        </div>

        {/* Tool Call Log */}
        <div style={{ marginBottom: '16px' }}>
          <h3 style={{ margin: '0 0 6px 0', fontSize: '13px', color: '#93c5fd' }}>Registro de Herramientas (Tool Calls):</h3>
          <div
            data-testid="dev-tool-calls"
            style={{
              maxHeight: '140px',
              overflowY: 'auto',
              backgroundColor: '#111827',
              padding: '8px',
              borderRadius: '4px',
              fontSize: '12px',
              border: '1px solid #374151',
            }}
          >
            {hook.state.tool_calls.length === 0 ? (
              <span style={{ color: '#6b7280' }}>Sin llamadas a herramientas registradas.</span>
            ) : (
              hook.state.tool_calls.map((tc, i) => (
                <div key={i} style={{ marginBottom: '4px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <span
                    style={{
                      backgroundColor: tc.status === 'pass' ? '#065f46' : '#7f1d1d',
                      color: '#ffffff',
                      padding: '1px 5px',
                      borderRadius: '3px',
                      fontSize: '10px',
                      fontWeight: 'bold',
                    }}
                  >
                    {tc.status.toUpperCase()}
                  </span>
                  <span style={{ color: '#fbbf24', fontWeight: 'bold' }}>{tc.tool}</span>
                  <span style={{ color: '#d1d5db' }}>{tc.args_summary_es}</span>
                  {tc.duration_ms !== undefined && (
                    <span style={{ color: '#9ca3af', marginLeft: 'auto' }}>{tc.duration_ms}ms</span>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {/* Pareto Options Table */}
        <div>
          <h3 style={{ margin: '0 0 8px 0', fontSize: '13px', color: '#93c5fd' }}>Frente de Pareto y Opciones Disponibles:</h3>
          <div
            data-testid="dev-options-table"
            style={{
              overflowX: 'auto',
              backgroundColor: '#111827',
              borderRadius: '4px',
              border: '1px solid #374151',
            }}
          >
            {!hook.state.options ? (
              <div style={{ padding: '12px', color: '#6b7280', fontSize: '12px' }}>
                No hay opciones activas en este momento (esperando detección de incidente).
              </div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', textAlign: 'left' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #374151', color: '#9ca3af' }}>
                    <th style={{ padding: '8px' }}>Opción ID</th>
                    <th style={{ padding: '8px' }}>Título</th>
                    <th style={{ padding: '8px' }}>Trade-off</th>
                    <th style={{ padding: '8px' }}>Hogares Reconectados</th>
                    <th style={{ padding: '8px' }}>MWh No Suministrados Evitados</th>
                    <th style={{ padding: '8px' }}>Delta Costo (USD)</th>
                    <th style={{ padding: '8px' }}>Delta CO2 (t)</th>
                    <th style={{ padding: '8px' }}>Delta Recorte (MWh)</th>
                    <th style={{ padding: '8px' }}>Validador</th>
                    <th style={{ padding: '8px' }}>Acción</th>
                  </tr>
                </thead>
                <tbody>
                  {hook.state.options.map((opt: Option) => {
                    const isPassed = opt.validation && opt.validation.passed;
                    return (
                      <tr key={opt.option_id} style={{ borderBottom: '1px solid #1f2937' }}>
                        <td style={{ padding: '8px', color: '#60a5fa', fontWeight: 'bold' }}>{opt.option_id}</td>
                        <td style={{ padding: '8px' }}>{opt.title_es}</td>
                        <td style={{ padding: '8px', color: '#fbbf24' }}>{opt.tradeoff_tag}</td>
                        <td style={{ padding: '8px' }}>{Math.round(opt.metrics.households_reconnected).toLocaleString()}</td>
                        <td style={{ padding: '8px' }}>{opt.metrics.unserved_mwh_avoided.toFixed(1)}</td>
                        <td style={{ padding: '8px' }}>${Math.round(opt.metrics.cost_delta_usd).toLocaleString()}</td>
                        <td style={{ padding: '8px' }}>{opt.metrics.co2_delta_t.toFixed(1)}</td>
                        <td style={{ padding: '8px' }}>{opt.metrics.curtailment_delta_mwh.toFixed(1)}</td>
                        <td style={{ padding: '8px' }}>
                          <span
                            style={{
                              backgroundColor: isPassed ? '#065f46' : '#7f1d1d',
                              color: '#ffffff',
                              padding: '2px 6px',
                              borderRadius: '3px',
                              fontSize: '11px',
                            }}
                          >
                            {isPassed ? 'PASSED' : 'FAILED'}
                          </span>
                        </td>
                        <td style={{ padding: '8px' }}>
                          <button
                            data-testid={`dev-approve-option-${opt.option_id}`}
                            onClick={() =>
                              hook.actions.submitOperatorDecision({
                                incident_id: activeIncId,
                                option_id: opt.option_id,
                                decision: 'apply',
                              })
                            }
                            style={{
                              backgroundColor: '#2563eb',
                              color: '#ffffff',
                              border: 'none',
                              padding: '4px 10px',
                              borderRadius: '4px',
                              cursor: 'pointer',
                              fontSize: '11px',
                              fontWeight: 'bold',
                            }}
                          >
                            Aprobar
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </section>

      <footer style={{ color: '#6b7280', fontSize: '12px' }}>
        Andes · Operación de la red eléctrica con IA DevConsole • Sesión Activa: {sessionId} • Eventos registrados: {hook.state.lastSeq + 1}
      </footer>
    </div>
  );
}

export default DevConsole;
