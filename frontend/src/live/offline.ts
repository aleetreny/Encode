import { 
  Catalog, LiveEvent, ClockCommandRequest, DisruptCommandRequest, 
  JuryDisruptCommandRequest, DecideCommandRequest 
} from './types';
import demoStreamRaw from './fixtures/demo-stream.jsonl?raw';

function parseDemoStream(): LiveEvent[] {
  return demoStreamRaw
    .split('\n')
    .filter(line => line.trim().length > 0)
    .map(line => JSON.parse(line) as LiveEvent);
}

const offlineEvents = parseDemoStream();
const snapshotEvent = offlineEvents.find(e => e.type === 'session.snapshot') as Extract<LiveEvent, { type: 'session.snapshot' }>;

export const OFFLINE_CATALOG: Catalog = {
  ...snapshotEvent.catalog,
  batteries: [
    ...snapshotEvent.catalog.batteries,
    { id: 'b_reserve_ng', name: 'BESS Reserva Norte Grande', node_id: 'n_norte_grande', power_mw: 50, energy_mwh: 100, standby: true },
    { id: 'b_reserve_centro', name: 'BESS Reserva Centro', node_id: 'n_centro', power_mw: 100, energy_mwh: 200, standby: true }
  ]
};

export class OfflineSessionController {
  private events: LiveEvent[] = offlineEvents;
  private onEvent: (ev: LiveEvent) => void;
  
  private clockInterval: number | null = null;
  private simHour = 12.0;
  private running = true;
  private speedSPerHour = 4.0;
  private currentSeq = 0;

  constructor(onEvent: (ev: LiveEvent) => void) {
    this.onEvent = onEvent;
  }

  start() {
    const snapshot = this.events.find(e => e.type === 'session.snapshot') as Extract<LiveEvent, { type: 'session.snapshot' }>;
    if (snapshot) {
      this.simHour = snapshot.clock.hour;
      this.running = snapshot.clock.running;
      this.speedSPerHour = snapshot.clock.speed_s_per_hour;
      this.onEvent({ ...snapshot, catalog: OFFLINE_CATALOG });
      this.currentSeq = snapshot.seq;
    }
    
    this.startClock();
  }

  stop() {
    if (this.clockInterval) {
      clearInterval(this.clockInterval);
      this.clockInterval = null;
    }
  }

  private startClock() {
    this.stop();
    const TICK_RATE_MS = 100;
    
    this.clockInterval = window.setInterval(() => {
      if (this.running) {
        // speedSPerHour means 1 hour simulated time = speedSPerHour seconds real time
        // tick is TICK_RATE_MS (0.1s)
        const simHoursPerTick = (TICK_RATE_MS / 1000) / this.speedSPerHour;
        this.simHour = (this.simHour + simHoursPerTick) % 24;
      }
      this.emitPendingEvents();
    }, TICK_RATE_MS);
  }

  private emitPendingEvents() {
    // Basic offline replay by sequence
    // It emits all events from demo-stream.jsonl that are scheduled at <= this.simHour
    // We only care about events seq > currentSeq
    const nextEvents = this.events.filter(e => 
      e.seq > this.currentSeq && e.hour <= this.simHour
    );
    
    for (const ev of nextEvents) {
      this.onEvent(ev);
      this.currentSeq = ev.seq;
    }

    // Always emit clock tick to keep UI interpolated smooth sync
    this.currentSeq++; // dummy increment to let reducer accept it if we want, or handle seq strictly
    this.onEvent({
      seq: this.currentSeq,
      session_id: 'offline',
      hour: this.simHour,
      ts_utc: new Date().toISOString(),
      type: 'clock.tick',
      running: this.running
    });
  }

  resetAndPlayDemo() {
    this.currentSeq = 0;
    this.events = parseDemoStream();
    this.start();
  }

  async postClockCommand(sessionId: string, cmd: ClockCommandRequest): Promise<void> {
    if (cmd.action === 'play') this.running = true;
    if (cmd.action === 'pause') this.running = false;
    if (cmd.action === 'seek' && cmd.hour !== undefined) {
      this.simHour = cmd.hour;
    }
  }

  async postEventCommand(sessionId: string, cmd: DisruptCommandRequest): Promise<void> {
    this.injectCrisis(cmd.asset_id);
  }

  async postJuryCommand(sessionId: string, cmd: JuryDisruptCommandRequest): Promise<Response> {
    await this.injectCrisis(cmd.asset_id);
    return new Response(null, { status: 202 });
  }

  private async injectCrisis(assetId: string) {
    try {
      const res = await fetch(`/incidents/${assetId}_${Math.floor(this.simHour)}.jsonl`);
      if (res.ok) {
        const text = await res.text();
        const newEvents = text
          .split('\n')
          .filter(l => l.trim().length > 0)
          .map(l => JSON.parse(l) as LiveEvent);
        
        // Re-number sequences
        const baseSeq = this.currentSeq;
        const mapped = newEvents.map((ev, i) => ({ ...ev, seq: baseSeq + i + 1, session_id: 'offline' }));
        this.events = [...this.events, ...mapped];
      } else {
        throw new Error('Fallback to demo');
      }
    } catch {
      // fallback: replay the crisis segment (seq >= 3) from demo-stream.jsonl
      const crisisEvents = parseDemoStream().filter(e => e.seq >= 3);
      const baseSeq = this.currentSeq;
      const mapped = crisisEvents.map((ev, i) => ({ ...ev, seq: baseSeq + i + 1, session_id: 'offline' }));
      this.events = [...this.events, ...mapped];
    }
  }

  async postDecisionCommand(sessionId: string, cmd: DecideCommandRequest): Promise<void> {
    this.currentSeq++;
    
    if (cmd.decision === 'veto') {
      this.onEvent({
        seq: this.currentSeq,
        session_id: 'offline',
        hour: this.simHour,
        ts_utc: new Date().toISOString(),
        type: 'plan.vetoed',
        incident_id: cmd.incident_id,
        option_id: cmd.option_id
      });
    } else {
      this.onEvent({
        seq: this.currentSeq,
        session_id: 'offline',
        hour: this.simHour,
        ts_utc: new Date().toISOString(),
        type: 'plan.applied',
        incident_id: cmd.incident_id,
        option_id: cmd.option_id,
        by: 'operator'
      });
    }
  }
}
