import React, { useState, useEffect, useReducer, useRef, useCallback } from 'react';
import type {
  Catalog,
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
} from './types';
import demoStreamRaw from './fixtures/demo-stream.jsonl?raw';

export interface JuryCardDef {
  id: string;
  title: string;
  description: string;
  asset_id: string;
  action: {
    type: 'generator_outage' | 'line_outage' | 'stress_recipe';
    asset_id?: string;
    asset_ids?: string[];
    recipe_id?: string;
    duration_h?: number;
  };
}

export const DEFAULT_JURY_CARDS: JuryCardDef[] = [
  {
    id: 'trip_gas_centro',
    title: 'Derribar Central Gas Centro',
    description: '600 MW en Polpaico',
    asset_id: 'gas_centro',
    action: { type: 'generator_outage', asset_id: 'gas_centro', duration_h: 4 },
  },
  {
    id: 'trip_l2',
    title: 'Cortar Troncal L2 Norte-Centro',
    description: '400 MW Cardones-Polpaico',
    asset_id: 'L2',
    action: { type: 'line_outage', asset_id: 'L2', duration_h: 4 },
  },
  {
    id: 'trip_l3',
    title: 'Cortar Troncal L3 Centro-Sur',
    description: '350 MW Polpaico-Charrúa',
    asset_id: 'L3',
    action: { type: 'line_outage', asset_id: 'L3', duration_h: 4 },
  },
  {
    id: 'trip_coal_cs',
    title: 'Disparar Carbonera Centro-Sur',
    description: '350 MW en Charrúa',
    asset_id: 'coal_cs',
    action: { type: 'generator_outage', asset_id: 'coal_cs', duration_h: 4 },
  },
  {
    id: 'stress_terremoto',
    title: 'Simular Terremoto Norte',
    description: 'Falla simultánea L1 + Gas Norte Grande',
    asset_id: 'L1',
    action: {
      type: 'stress_recipe',
      recipe_id: 'stress_terremoto',
      asset_ids: ['L1', 'gas_ng'],
      duration_h: 4,
    },
  },
];

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
          detail_es: `Incidente detectado en ${event.disruption.asset_id}: ${event.impact.households_off_peak} hogares afectados`,
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
            ? { ...next.agent_status, phase: 'executing', detail_es: 'Plan de mitigación aplicado a la red' }
            : event.reason === 'event_ended'
            ? { ...next.agent_status, phase: 'resolved', detail_es: 'Falla normalizada, red en recuperación' }
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
          detail_es: `Plan ${event.option_id} ejecutado por ${event.by}`,
          started_at_utc: next.agent_status.started_at_utc,
        },
      };

    case 'plan.vetoed':
      return {
        ...next,
        countdown: null,
        agent_status: {
          phase: 'idle',
          detail_es: `Plan ${event.option_id} vetado por el operador`,
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

function useBuiltinLiveSession(defaultSessionId?: string): LiveSessionHook {
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
          // Backend is offline or not serving SSE -> fallback to offline replay
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
      }
    },
    injectEvent: async (cmd: DisruptCommandRequest) => {
      if (connectionMode === 'live') {
        await fetch(`/api/live/sessions/${resolvedSessionId}/disrupt`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(cmd),
        });
      }
    },
    submitJuryAction: async (cmd: JuryDisruptCommandRequest & { device_id?: string; card_id?: string; action?: any }) => {
      if (connectionMode === 'live') {
        try {
          const res = await fetch(`/api/live/sessions/${resolvedSessionId}/jury`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cmd),
          });
          if (res.status === 404) {
            return await fetch(`/api/live/sessions/${resolvedSessionId}/jury/disrupt`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ asset_id: cmd.asset_id, jury_name: cmd.jury_name }),
            });
          }
          return res;
        } catch (e) {
          return new Response(JSON.stringify({ error: 'Network failure' }), { status: 503 });
        }
      } else {
        // Offline simulation
        const syntheticDisruption: Disruption = {
          event_id: `ev-jury-${Date.now()}`,
          type: cmd.asset_id?.startsWith('L') ? 'line_outage' : 'generator_outage',
          asset_id: cmd.asset_id,
          from_hour: Math.floor(interpolatedSimHour),
          to_hour: Math.floor(interpolatedSimHour) + 4,
          source: 'jury',
          jury_name: cmd.jury_name,
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
            unserved_mw_peak: 450,
            households_off_peak: 450000,
            nodes_affected: ['n_centro'],
            lines_overloaded: [],
          },
        });
        return new Response(JSON.stringify({ ok: true, event_id: syntheticDisruption.event_id }), { status: 202 });
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

export interface JuryPageProps {
  sessionHook?: LiveSessionHook;
}

export function JuryPage({ sessionHook }: JuryPageProps) {
  const builtinHook = useBuiltinLiveSession();
  const hook = sessionHook || builtinHook;

  // Juror identity in localStorage
  const [juryName, setJuryName] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('gridpilot_jury_name') || '';
    }
    return '';
  });

  const [deviceId, setDeviceId] = useState(() => {
    if (typeof window !== 'undefined') {
      let id = localStorage.getItem('gridpilot_device_id');
      if (!id) {
        id = typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `dev-${Math.random().toString(36).substring(2, 10)}`;
        localStorage.setItem('gridpilot_device_id', id);
      }
      return id;
    }
    return 'dev-default';
  });

  // Cooldown timer (30s)
  const [cooldownRemaining, setCooldownRemaining] = useState<number>(() => {
    if (typeof window !== 'undefined') {
      const untilStr = localStorage.getItem('gridpilot_jury_cooldown_until');
      if (untilStr) {
        const remaining = Math.ceil((parseInt(untilStr, 10) - Date.now()) / 1000);
        return remaining > 0 ? remaining : 0;
      }
    }
    return 0;
  });

  const [rateLimitMessage, setRateLimitMessage] = useState<string | null>(null);
  const [submittingCardId, setSubmittingCardId] = useState<string | null>(null);

  // Cooldown countdown effect
  useEffect(() => {
    if (cooldownRemaining <= 0) return;
    const timer = setInterval(() => {
      setCooldownRemaining((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          localStorage.removeItem('gridpilot_jury_cooldown_until');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [cooldownRemaining]);

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setJuryName(val);
    if (typeof window !== 'undefined') {
      localStorage.setItem('gridpilot_jury_name', val);
    }
  };

  const handleTriggerCard = async (card: JuryCardDef) => {
    if (cooldownRemaining > 0) return;
    if (hook.state.active_incidents.length >= 2) {
      setRateLimitMessage('Dos crisis en curso — espera a que el agente resuelva una o a que termine tu enfriamiento.');
      return;
    }

    setSubmittingCardId(card.id);
    setRateLimitMessage(null);

    try {
      const res = await hook.actions.submitJuryAction({
        asset_id: card.asset_id,
        jury_name: juryName.trim() || undefined,
        device_id: deviceId,
        card_id: card.id,
        action: card.action,
      });

      if (res && res.status === 429) {
        setRateLimitMessage('Dos crisis en curso — espera a que el agente resuelva una o a que termine tu enfriamiento.');
      } else if (res && res.ok) {
        // Successful trigger -> start 30-second cooldown
        const until = Date.now() + 30000;
        localStorage.setItem('gridpilot_jury_cooldown_until', String(until));
        setCooldownRemaining(30);
      }
    } catch (err) {
      console.error('Trigger error:', err);
    } finally {
      setSubmittingCardId(null);
    }
  };

  // Households calculation: unserved_mw * 1000 or solution.households_off
  const hourIdx = Math.min(23, Math.max(0, Math.floor(hook.interpolatedSimHour)));
  let householdsWithoutSupply = 0;
  if (hook.state.solution) {
    if (hook.state.solution.households_off) {
      householdsWithoutSupply = Object.values(hook.state.solution.households_off).reduce(
        (acc, arr) => acc + (arr[hourIdx] || 0),
        0
      );
    } else if (hook.state.solution.unserved_mw) {
      const totalUnservedMw = Object.values(hook.state.solution.unserved_mw).reduce(
        (acc, arr) => acc + (arr[hourIdx] || 0),
        0
      );
      householdsWithoutSupply = totalUnservedMw * 1000;
    }
  }

  const isLimitReached = hook.state.active_incidents.length >= 2;
  const isCooldownActive = cooldownRemaining > 0;
  const showRateLimitBanner = isLimitReached || rateLimitMessage !== null;

  const formatHour = (h: number) => {
    const hours = Math.floor(h) % 24;
    const mins = Math.floor((h - Math.floor(h)) * 60);
    return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')} hrs`;
  };

  return (
    <div
      data-testid="jury-page"
      style={{
        maxWidth: '640px',
        margin: '0 auto',
        padding: '16px',
        fontFamily: 'system-ui, -apple-system, sans-serif',
        color: '#111827',
        backgroundColor: '#f9fafb',
        minHeight: '100vh',
      }}
    >
      {/* Header */}
      <header style={{ marginBottom: '20px', borderBottom: '1px solid #e5e7eb', paddingBottom: '12px' }}>
        <h1 style={{ fontSize: '24px', fontWeight: 'bold', margin: '0 0 6px 0' }}>
          GridPilot Live Ops — Panel del Jurado
        </h1>
        <p style={{ margin: 0, color: '#4b5563', fontSize: '14px' }}>
          Desafía la red eléctrica en tiempo real. Gemini 4 Argon detecta, simula y propone mitigaciones.
        </p>
      </header>

      {/* Name and Device Identification */}
      <section style={{ marginBottom: '20px', backgroundColor: '#ffffff', padding: '14px', borderRadius: '8px', border: '1px solid #e5e7eb' }}>
        <label style={{ display: 'block', fontSize: '14px', fontWeight: '600', marginBottom: '6px' }}>
          Nombre del Jurado (opcional):
        </label>
        <input
          data-testid="jury-name-input"
          type="text"
          value={juryName}
          onChange={handleNameChange}
          placeholder="Ej: Jurado Encode #1"
          style={{
            width: '100%',
            padding: '8px 12px',
            borderRadius: '6px',
            border: '1px solid #d1d5db',
            fontSize: '14px',
            boxSizing: 'border-box',
          }}
        />
        <div style={{ fontSize: '11px', color: '#6b7280', marginTop: '6px' }}>
          Dispositivo ID: <code>{deviceId}</code>
        </div>
      </section>

      {/* Cooldown Banner */}
      {isCooldownActive && (
        <aside
          data-testid="jury-cooldown-banner"
          style={{
            backgroundColor: '#eff6ff',
            color: '#1e40af',
            padding: '10px 14px',
            borderRadius: '6px',
            marginBottom: '16px',
            border: '1px solid #bfdbfe',
            fontWeight: '600',
            fontSize: '14px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span>Enfriamiento por dispositivo activo:</span>
          <span>{cooldownRemaining}s restantes</span>
        </aside>
      )}

      {/* Rate Limit / Max Events Alert Message */}
      {showRateLimitBanner && (
        <div
          data-testid="jury-rate-limit-message"
          style={{
            backgroundColor: '#fef2f2',
            color: '#991b1b',
            padding: '12px 14px',
            borderRadius: '6px',
            marginBottom: '16px',
            border: '1px solid #fecaca',
            fontWeight: '600',
            fontSize: '14px',
          }}
        >
          Dos crisis en curso — espera a que el agente resuelva una o a que termine tu enfriamiento.
        </div>
      )}

      {/* 5 Action Cards */}
      <section style={{ marginBottom: '24px' }}>
        <h2 style={{ fontSize: '18px', fontWeight: 'bold', marginBottom: '12px' }}>
          Disrupciones del Sistema (Selecciona una acción)
        </h2>
        <div style={{ display: 'grid', gap: '12px' }}>
          {DEFAULT_JURY_CARDS.map((card) => {
            const isDisabled = isCooldownActive || isLimitReached || submittingCardId === card.id;
            return (
              <article
                key={card.id}
                data-testid={`jury-card-${card.id}`}
                style={{
                  backgroundColor: '#ffffff',
                  borderRadius: '8px',
                  border: '1px solid #e5e7eb',
                  padding: '14px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px',
                  opacity: isDisabled ? 0.7 : 1,
                  boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                }}
              >
                <div>
                  <h3 style={{ margin: '0 0 4px 0', fontSize: '16px', fontWeight: '600', color: '#111827' }}>
                    {card.title}
                  </h3>
                  <p style={{ margin: 0, fontSize: '13px', color: '#4b5563' }}>
                    {card.description}
                  </p>
                </div>
                <button
                  data-testid={`jury-trigger-${card.id}`}
                  onClick={() => handleTriggerCard(card)}
                  disabled={isDisabled}
                  style={{
                    alignSelf: 'flex-start',
                    backgroundColor: isDisabled ? '#9ca3af' : '#dc2626',
                    color: '#ffffff',
                    border: 'none',
                    padding: '8px 16px',
                    borderRadius: '6px',
                    fontWeight: '600',
                    fontSize: '14px',
                    cursor: isDisabled ? 'not-allowed' : 'pointer',
                    transition: 'background-color 0.2s',
                  }}
                >
                  {submittingCardId === card.id ? 'Ejecutando...' : 'Tumbar / Provocar Falla'}
                </button>
              </article>
            );
          })}
        </div>
      </section>

      {/* Live System Status & Agent Reaction Summary */}
      <section
        data-testid="jury-live-status"
        style={{
          backgroundColor: '#ffffff',
          borderRadius: '8px',
          border: '1px solid #e5e7eb',
          padding: '16px',
          marginBottom: '20px',
        }}
      >
        <h2 style={{ fontSize: '16px', fontWeight: 'bold', margin: '0 0 10px 0', borderBottom: '1px solid #f3f4f6', paddingBottom: '6px' }}>
          Estado en Vivo del Sistema Eléctrico
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '10px', fontSize: '13px' }}>
          <div>
            <span style={{ color: '#6b7280', display: 'block' }}>Hora Simulada:</span>
            <strong style={{ fontSize: '15px' }}>{formatHour(hook.interpolatedSimHour)}</strong>
          </div>
          <div>
            <span style={{ color: '#6b7280', display: 'block' }}>Fase del Agente:</span>
            <strong style={{ fontSize: '14px', textTransform: 'capitalize' }}>{hook.state.agent_status.phase}</strong>
          </div>
          <div>
            <span style={{ color: '#6b7280', display: 'block' }}>Hogares sin Suministro:</span>
            <strong style={{ fontSize: '15px', color: householdsWithoutSupply > 0 ? '#dc2626' : '#16a34a' }}>
              {Math.round(householdsWithoutSupply).toLocaleString('es-CL')}
            </strong>
          </div>
          <div>
            <span style={{ color: '#6b7280', display: 'block' }}>Crisis Activas:</span>
            <strong style={{ fontSize: '15px', color: hook.state.active_incidents.length > 0 ? '#b91c1c' : '#111827' }}>
              {hook.state.active_incidents.length} / 2 máx
            </strong>
          </div>
        </div>

        <div style={{ marginTop: '12px', padding: '8px 10px', backgroundColor: '#f9fafb', borderRadius: '6px', fontSize: '12px', color: '#374151' }}>
          <strong>Detalle:</strong> {hook.state.agent_status.detail_es || 'Supervisión en curso.'}
        </div>

        {/* Active Incidents listing */}
        {hook.state.active_incidents.length > 0 && (
          <div style={{ marginTop: '12px' }}>
            <span style={{ fontSize: '12px', fontWeight: '600', color: '#991b1b' }}>Fallas activas:</span>
            <ul style={{ margin: '4px 0 0 0', paddingLeft: '20px', fontSize: '12px', color: '#b91c1c' }}>
              {hook.state.active_incidents.map((inc) => (
                <li key={inc.event_id}>
                  {inc.asset_id} ({inc.type}) por {inc.jury_name || inc.source} hasta {inc.to_hour}:00
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* Agent Recommendation Summary */}
      {hook.state.options && (
        <section
          data-testid="jury-agent-recommendation"
          style={{
            backgroundColor: '#f0fdf4',
            border: '1px solid #bbf7d0',
            borderRadius: '8px',
            padding: '16px',
            marginBottom: '20px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 'bold', color: '#166534' }}>
              Recomendación Gemini 4 Argon
            </h3>
            <span style={{ fontSize: '11px', backgroundColor: '#dcfce7', color: '#15803d', padding: '2px 8px', borderRadius: '12px', fontWeight: '600' }}>
              Optimizador HiGHS Validado
            </span>
          </div>

          {(() => {
            const recId = hook.state.countdown?.candidate_id;
            const rec = hook.state.options.find((o) => o.option_id === recId) || hook.state.options[0];
            return (
              <div>
                <p style={{ margin: '0 0 6px 0', fontSize: '14px', fontWeight: '600', color: '#14532d' }}>
                  {rec.title_es}
                </p>
                <p style={{ margin: '0 0 10px 0', fontSize: '13px', color: '#166534', lineHeight: 1.4 }}>
                  {rec.rationale_es}
                </p>
                <div style={{ fontSize: '12px', color: '#15803d', display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                  <span>Reconexión: {Math.round(rec.metrics.households_reconnected).toLocaleString('es-CL')} hogares</span>
                  <span>•</span>
                  <span>Costo: ${Math.round(rec.metrics.cost_delta_usd).toLocaleString('es-CL')} USD</span>
                  <span>•</span>
                  <span>Trade-off: {rec.tradeoff_tag}</span>
                </div>
              </div>
            );
          })()}
        </section>
      )}

      {/* Footer */}
      <footer style={{ textAlign: 'center', fontSize: '12px', color: '#9ca3af', marginTop: '24px' }}>
        GridPilot Live Ops • Modo: {hook.connectionMode.toUpperCase()} • Sesión: {hook.state.sessionId || 'demo'}
      </footer>
    </div>
  );
}

export default JuryPage;
