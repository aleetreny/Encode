import { 
  Catalog, 
  LiveEvent, 
  ClockCommandRequest, 
  DisruptCommandRequest as InjectEventRequest, 
  JuryDisruptCommandRequest as JuryCommandRequest, 
  DecideCommandRequest as OperatorDecisionRequest,
  ImpactPreviewResponse
} from './types';
import { LiveSessionState } from './store';

const API_BASE = import.meta.env?.VITE_API_BASE_URL || '/api';
const EXTRA_HEADERS: Record<string, string> = API_BASE.includes('ngrok')
  ? { 'ngrok-skip-browser-warning': '1' }
  : {};
const JSON_HEADERS: Record<string, string> = {
  'Content-Type': 'application/json',
  ...EXTRA_HEADERS,
};

export type AutonomyMode = boolean;

export async function fetchLiveCatalog(): Promise<Catalog> {
  const res = await fetch(`${API_BASE}/live/catalog`, { headers: EXTRA_HEADERS });
  if (!res.ok) throw new Error('Failed to fetch catalog');
  return res.json();
}

export async function createLiveSession(opts?: { 
  session_id?: string;
  scenario_id?: string; 
  sim_hour?: number; 
  speed_hours_per_sec?: number; 
  autonomy_mode?: AutonomyMode 
}): Promise<{ session_id: string; state: LiveSessionState }> {
  const payload: any = {};
  if (opts?.session_id) payload.session_id = opts.session_id;
  if (opts?.scenario_id) payload.scenario_id = opts.scenario_id;
  if (opts?.sim_hour !== undefined) payload.start_hour = opts.sim_hour;
  if (opts?.speed_hours_per_sec !== undefined) payload.speed_s_per_hour = 1 / opts.speed_hours_per_sec;
  if (opts?.autonomy_mode !== undefined) payload.autonomy = opts.autonomy_mode;

  const res = await fetch(`${API_BASE}/live/sessions`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error('Failed to create session');
  const data = await res.json();
  
  // As required by the prompt, we also return a state placeholder or fetch it
  // Since POST /api/live/sessions usually just returns { session_id }, we'll cast state.
  return { session_id: data.session_id, state: null as any };
}

export async function getLiveSession(sessionId: string): Promise<LiveSessionState> {
  const res = await fetch(`${API_BASE}/live/sessions/${encodeURIComponent(sessionId)}`, {
    headers: EXTRA_HEADERS,
  });
  if (!res.ok) throw new Error('Failed to fetch session state');
  return res.json();
}

export function connectLiveStream(
  sessionId: string, 
  opts: { 
    lastEventId?: number; 
    onEvent: (ev: LiveEvent) => void; 
    onOpen?: () => void; 
    onError?: (err: unknown) => void 
  }
): () => void {
  const url = new URL(`${API_BASE}/live/sessions/${encodeURIComponent(sessionId)}/stream`, window.location.origin);
  if (opts.lastEventId !== undefined) {
    url.searchParams.set('last_event_id', opts.lastEventId.toString());
  }

  if (url.hostname.includes('ngrok') && typeof fetch !== 'undefined') {
    const controller = new AbortController();
    (async () => {
      try {
        const res = await fetch(url.toString(), {
          headers: { Accept: 'text/event-stream', ...EXTRA_HEADERS },
          signal: controller.signal,
        });
        if (!res.ok || !res.body) {
          throw new Error(`SSE HTTP ${res.status}`);
        }
        opts.onOpen?.();
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split('\n');
          buf = lines.pop() ?? '';
          for (const raw of lines) {
            const line = raw.trim();
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6));
                opts.onEvent(data as LiveEvent);
              } catch (err) {
                console.error('Failed to parse SSE', err);
              }
            }
          }
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          opts.onError?.(err);
        }
      }
    })();
    return () => controller.abort();
  }

  const es = new EventSource(url.toString());
  
  es.onopen = () => opts.onOpen?.();
  es.onerror = (err) => opts.onError?.(err);
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      opts.onEvent(data as LiveEvent);
    } catch (err) {
      console.error('Failed to parse SSE', err);
    }
  };

  return () => {
    es.close();
  };
}

export async function postClockCommand(sessionId: string, cmd: ClockCommandRequest): Promise<void> {
  const res = await fetch(`${API_BASE}/live/sessions/${encodeURIComponent(sessionId)}/clock`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(cmd)
  });
  if (!res.ok) throw new Error('Clock command failed');
}

export async function postEventCommand(sessionId: string, cmd: InjectEventRequest): Promise<void> {
  const res = await fetch(`${API_BASE}/live/sessions/${encodeURIComponent(sessionId)}/disrupt`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(cmd)
  });
  if (!res.ok) throw new Error('Event command failed');
}

export async function postJuryCommand(sessionId: string, cmd: JuryCommandRequest): Promise<Response> {
  return fetch(`${API_BASE}/live/sessions/${encodeURIComponent(sessionId)}/jury/disrupt`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(cmd)
  });
}

export async function postDecisionCommand(sessionId: string, cmd: OperatorDecisionRequest): Promise<void> {
  const res = await fetch(`${API_BASE}/live/sessions/${encodeURIComponent(sessionId)}/decide`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(cmd)
  });
  if (!res.ok) throw new Error('Decision command failed');
}

export function getReportUrl(sessionId: string, format: 'md' | 'html' = 'html'): string {
  return `${API_BASE}/live/sessions/${encodeURIComponent(sessionId)}/report?format=${format}`;
}

export async function fetchImpactPreview(sessionId: string): Promise<ImpactPreviewResponse> {
  const res = await fetch(`${API_BASE}/live/sessions/${encodeURIComponent(sessionId)}/impact_preview`, {
    headers: EXTRA_HEADERS,
  });
  if (!res.ok) throw new Error('Failed to fetch impact preview');
  return res.json();
}
