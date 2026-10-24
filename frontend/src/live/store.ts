import React, { createContext, useContext, useEffect, useReducer, useRef, useState, ReactNode } from 'react';
import { 
  Catalog, LiveEvent, Solution, Disruption, GridState, Option, 
  ClockCommandRequest, DisruptCommandRequest, JuryDisruptCommandRequest, DecideCommandRequest 
} from './types';
import * as client from './client';
// offline.ts will be implemented later, we'll import it type-safe
import { OfflineSessionController } from './offline';

export interface LiveSessionState {
  sessionId: string | null;
  lastSeq: number;
  catalog: Catalog | null;
  grid_state: GridState;
  clock: {
    sim_hour: number;
    running: boolean;
    speed_hours_per_sec: number;
    autonomy_mode: boolean;
  };
  active_incidents: Disruption[];
  solution: Solution | null;
  validation: any | null;
  comparison: any | null;
  agent_status: {
    phase: 'idle' | 'analyzing' | 'awaiting_operator' | 'executing' | 'resolved';
    detail_es: string;
    started_at_utc: string | null;
  };
  thoughts: { text_es: string; ts_utc: string; sim_hour: number }[];
  tool_calls: Extract<LiveEvent, { type: 'agent.tool_call' }>[];
  options: [Option, Option] | null;
  countdown: { candidate_id: string; seconds_left: number; active: boolean } | null;
  notes: { text_es: string; ts_utc: string; sim_hour: number }[];
}

export function createInitialLiveState(sessionId?: string): LiveSessionState {
  return {
    sessionId: sessionId || null,
    lastSeq: -1,
    catalog: null,
    grid_state: 'normal',
    clock: {
      sim_hour: 12, // Default
      running: false,
      speed_hours_per_sec: 0.25, // 1/4 = 4s per hour
      autonomy_mode: false,
    },
    active_incidents: [],
    solution: null,
    validation: null,
    comparison: null,
    agent_status: {
      phase: 'idle',
      detail_es: '',
      started_at_utc: null,
    },
    thoughts: [],
    tool_calls: [],
    options: null,
    countdown: null,
    notes: [],
  };
}

function keepLast<T>(arr: T[], item: T, max = 50): T[] {
  const newArr = [...arr, item];
  return newArr.length > max ? newArr.slice(newArr.length - max) : newArr;
}

export function liveReducer(state: LiveSessionState, event: LiveEvent): LiveSessionState {
  if (event.seq <= state.lastSeq && event.type !== 'session.snapshot') {
    return state;
  }
  
  const newState = { ...state, lastSeq: Math.max(state.lastSeq, event.seq) };

  switch (event.type) {
    case 'session.snapshot': {
      return {
        ...createInitialLiveState(event.session_id),
        lastSeq: event.seq,
        catalog: event.catalog,
        solution: event.solution,
        grid_state: event.grid_state,
        active_incidents: event.active_events,
        clock: {
          sim_hour: event.clock.hour,
          running: event.clock.running,
          speed_hours_per_sec: 1 / (event.clock.speed_s_per_hour || 4),
          autonomy_mode: event.autonomy,
        }
      };
    }
    case 'clock.tick': {
      return {
        ...newState,
        clock: {
          ...newState.clock,
          running: event.running,
          sim_hour: event.hour,
        }
      };
    }
    case 'incident.detected': {
      return {
        ...newState,
        active_incidents: [...newState.active_incidents, event.disruption],
        clock: { ...newState.clock, sim_hour: event.hour },
        agent_status: { ...newState.agent_status, phase: 'analyzing' },
      };
    }
    case 'solution.updated': {
      const isResolved = event.reason === 'plan_applied' || event.reason === 'event_ended';
      return {
        ...newState,
        solution: event.solution,
        grid_state: event.grid_state,
        validation: event.solution?.validation || null,
        agent_status: isResolved ? { ...newState.agent_status, phase: 'resolved' } : newState.agent_status,
      };
    }
    case 'agent.thought': {
      return {
        ...newState,
        thoughts: keepLast(newState.thoughts, { text_es: event.delta, ts_utc: event.ts_utc, sim_hour: event.hour })
      };
    }
    case 'agent.tool_call': {
      return {
        ...newState,
        tool_calls: keepLast(newState.tool_calls, event)
      };
    }
    case 'options.ready': {
      return {
        ...newState,
        options: event.options,
        agent_status: { ...newState.agent_status, phase: 'awaiting_operator' },
        countdown: { candidate_id: event.recommended_id, seconds_left: 0, active: false }
      };
    }
    case 'autonomy.countdown': {
      return {
        ...newState,
        countdown: { candidate_id: event.option_id, seconds_left: event.seconds_left, active: event.seconds_left > 0 }
      };
    }
    case 'plan.applied': {
      return {
        ...newState,
        countdown: null,
        agent_status: { ...newState.agent_status, phase: 'executing' }
      };
    }
    case 'plan.vetoed': {
      return {
        ...newState,
        countdown: null,
        agent_status: { ...newState.agent_status, phase: 'idle' } // or whatever makes sense
      };
    }
    case 'event.ended': {
      return {
        ...newState,
        active_incidents: newState.active_incidents.filter(i => i.event_id !== event.event_id)
      };
    }
    case 'agent.note': {
      return {
        ...newState,
        notes: keepLast(newState.notes, { text_es: event.text_es, ts_utc: event.ts_utc, sim_hour: event.hour })
      };
    }
    case 'error': {
      return {
        ...newState,
        agent_status: { ...newState.agent_status, detail_es: event.message_es }
      };
    }
    default:
      return newState;
  }
}

export interface LiveSessionActions {
  setClock(cmd: ClockCommandRequest): Promise<void>;
  injectEvent(cmd: DisruptCommandRequest): Promise<void>;
  submitJuryAction(cmd: JuryDisruptCommandRequest): Promise<Response>;
  submitOperatorDecision(cmd: DecideCommandRequest): Promise<void>;
  vetoCountdown(incidentId: string, optionId: string): Promise<void>;
  switchMode(mode: 'live' | 'offline'): void;
  replayOfflineDemo(): void;
  downloadReportUrl(): string;
}

export interface LiveSessionHook {
  state: LiveSessionState;
  catalog: Catalog | null;
  connected: boolean;
  connectionMode: 'live' | 'offline' | 'connecting';
  actions: LiveSessionActions;
  interpolatedSimHour: number;
}

const LiveSessionContext = createContext<LiveSessionHook | null>(null);

export function useLiveSession(): LiveSessionHook {
  const ctx = useContext(LiveSessionContext);
  if (!ctx) throw new Error('useLiveSession must be used within LiveSessionProvider');
  return ctx;
}

export function LiveSessionProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(liveReducer, createInitialLiveState());
  const [connectionMode, setConnectionMode] = useState<'live' | 'offline' | 'connecting'>('connecting');
  const [connected, setConnected] = useState(false);
  const [interpolatedSimHour, setInterpolatedSimHour] = useState(12);
  const offlineController = useRef<OfflineSessionController | null>(null);

  // Smooth interpolation
  const lastUpdateRef = useRef<number>(performance.now());
  const simHourRef = useRef<number>(state.clock.sim_hour);

  useEffect(() => {
    simHourRef.current = state.clock.sim_hour;
    setInterpolatedSimHour(state.clock.sim_hour);
  }, [state.clock.sim_hour]);

  useEffect(() => {
    let animFrame: number;
    const animate = (time: number) => {
      const deltaMs = time - lastUpdateRef.current;
      lastUpdateRef.current = time;

      if (state.clock.running) {
        simHourRef.current += (deltaMs / 1000) * state.clock.speed_hours_per_sec;
        simHourRef.current = simHourRef.current % 24;
        if (simHourRef.current < 0) simHourRef.current += 24;
        setInterpolatedSimHour(simHourRef.current);
      }
      animFrame = requestAnimationFrame(animate);
    };
    animFrame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animFrame);
  }, [state.clock.running, state.clock.speed_hours_per_sec]);

  // Connection logic
  useEffect(() => {
    let cleanup: (() => void) | null = null;
    let mounted = true;

    async function connectLive() {
      try {
        setConnectionMode('connecting');
        await client.fetchLiveCatalog(); // verify backend is up
        const { session_id } = await client.createLiveSession();
        if (!mounted) return;
        
        cleanup = client.connectLiveStream(session_id, {
          onEvent: (ev) => dispatch(ev),
          onOpen: () => {
            if (mounted) {
              setConnected(true);
              setConnectionMode('live');
            }
          },
          onError: () => {
            if (mounted) fallbackToOffline();
          }
        });
      } catch (err) {
        if (mounted) fallbackToOffline();
      }
    }

    function fallbackToOffline() {
      setConnectionMode('offline');
      setConnected(true);
      if (!offlineController.current) {
        offlineController.current = new OfflineSessionController((ev) => dispatch(ev));
      }
      offlineController.current.start();
    }

    if (connectionMode === 'live' || connectionMode === 'connecting') {
      connectLive();
    } else if (connectionMode === 'offline') {
      fallbackToOffline();
    }

    return () => {
      mounted = false;
      cleanup?.();
      offlineController.current?.stop();
    };
  }, [connectionMode]);

  const actions: LiveSessionActions = {
    async setClock(cmd) {
      if (connectionMode === 'offline' && offlineController.current) {
        return offlineController.current.postClockCommand(state.sessionId || 'offline', cmd);
      }
      if (state.sessionId) await client.postClockCommand(state.sessionId, cmd);
    },
    async injectEvent(cmd) {
      if (connectionMode === 'offline' && offlineController.current) {
        return offlineController.current.postEventCommand(state.sessionId || 'offline', cmd);
      }
      if (state.sessionId) await client.postEventCommand(state.sessionId, cmd);
    },
    async submitJuryAction(cmd) {
      if (connectionMode === 'offline' && offlineController.current) {
        return offlineController.current.postJuryCommand(state.sessionId || 'offline', cmd);
      }
      if (state.sessionId) return client.postJuryCommand(state.sessionId, cmd);
      return new Response(null, { status: 400 });
    },
    async submitOperatorDecision(cmd) {
      if (connectionMode === 'offline' && offlineController.current) {
        return offlineController.current.postDecisionCommand(state.sessionId || 'offline', cmd);
      }
      if (state.sessionId) await client.postDecisionCommand(state.sessionId, cmd);
    },
    async vetoCountdown(incidentId, optionId) {
      const cmd: DecideCommandRequest = { incident_id: incidentId, option_id: optionId, decision: 'veto' };
      if (connectionMode === 'offline' && offlineController.current) {
        return offlineController.current.postDecisionCommand(state.sessionId || 'offline', cmd);
      }
      if (state.sessionId) await client.postDecisionCommand(state.sessionId, cmd);
    },
    switchMode(mode) {
      setConnectionMode(mode);
    },
    replayOfflineDemo() {
      setConnectionMode('offline');
      offlineController.current?.resetAndPlayDemo();
    },
    downloadReportUrl() {
      if (connectionMode === 'offline') return '#';
      return state.sessionId ? client.getReportUrl(state.sessionId, 'html') : '#';
    }
  };

  return (
    <LiveSessionContext.Provider value={{
      state,
      catalog: state.catalog,
      connected,
      connectionMode,
      actions,
      interpolatedSimHour
    }}>
      {children}
    </LiveSessionContext.Provider>
  );
}
