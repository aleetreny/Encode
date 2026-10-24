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

export const LIBRARY_HOURS = [9, 12, 13, 18, 19, 20];

export class OfflineSessionController {
  private events: LiveEvent[] = offlineEvents;
  private onEvent: (ev: LiveEvent) => void;
  
  private clockInterval: number | null = null;
  private countdownInterval: number | null = null;
  private simHour = 12.0;
  private running = true;
  private speedSPerHour = 4.0;
  private currentSeq = 0;
  private autonomy = false;
  private isVetoed = false;
  private lastOptionsReady: Extract<LiveEvent, { type: 'options.ready' }> | null = null;

  constructor(onEvent: (ev: LiveEvent) => void) {
    this.onEvent = onEvent;
  }

  start() {
    const snapshot = this.events.find(e => e.type === 'session.snapshot') as Extract<LiveEvent, { type: 'session.snapshot' }>;
    if (snapshot) {
      this.simHour = snapshot.clock.hour;
      this.running = snapshot.clock.running;
      this.speedSPerHour = snapshot.clock.speed_s_per_hour;
      this.autonomy = snapshot.autonomy ?? false;
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
    this.cancelCountdown();
  }

  getClosestLibraryHour(simHour: number): number {
    return LIBRARY_HOURS.reduce((prev, curr) =>
      Math.abs(curr - simHour) < Math.abs(prev - simHour) ? curr : prev
    );
  }

  setAutonomy(enabled: boolean) {
    this.autonomy = enabled;
    if (!enabled) {
      this.cancelCountdown();
    }
  }

  getAutonomy(): boolean {
    return this.autonomy;
  }

  private cancelCountdown() {
    if (this.countdownInterval !== null) {
      clearInterval(this.countdownInterval);
      this.countdownInterval = null;
    }
  }

  private startClock() {
    this.stop();
    const TICK_RATE_MS = 100;
    
    this.clockInterval = window.setInterval(() => {
      if (this.running) {
        const simHoursPerTick = (TICK_RATE_MS / 1000) / this.speedSPerHour;
        this.simHour = (this.simHour + simHoursPerTick) % 24;
      }
      this.emitPendingEvents();
    }, TICK_RATE_MS);
  }

  private emitPendingEvents() {
    const nextEvents = this.events.filter(e => 
      e.seq > this.currentSeq && e.hour <= this.simHour
    );
    
    for (const ev of nextEvents) {
      this.onEvent(ev);
      this.currentSeq = ev.seq;
    }

    this.currentSeq++;
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
    this.cancelCountdown();
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
    await this.injectCrisis(cmd.asset_id);
  }

  async postJuryCommand(sessionId: string, cmd: JuryDisruptCommandRequest): Promise<Response> {
    await this.injectCrisis(cmd.asset_id);
    return new Response(null, { status: 202 });
  }

  async postAutonomyCommand(sessionId: string, cmd: { autonomy: boolean }): Promise<void> {
    this.setAutonomy(cmd.autonomy);
  }

  async injectCrisis(assetId: string): Promise<void> {
    const nearestHour = this.getClosestLibraryHour(this.simHour);
    try {
      const res = await fetch(`/incidents/${assetId}_${nearestHour}.jsonl`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const text = await res.text();
      const lines = text.split('\n').filter(l => l.trim().length > 0);
      if (lines.length === 0) throw new Error('Empty incident library file');
      const libraryEvents = lines.map(l => JSON.parse(l) as LiveEvent);

      this.cancelCountdown();
      this.isVetoed = false;

      // Replay incident events into onEvent up to options.ready
      for (const ev of libraryEvents) {
        if (ev.type === 'session.snapshot') continue;
        if (ev.type === 'plan.applied') continue;
        if (ev.type === 'solution.updated' && ev.reason === 'plan_applied') continue;

        this.currentSeq++;
        const stamped: LiveEvent = {
          ...ev,
          seq: this.currentSeq,
          session_id: 'offline',
          hour: this.simHour,
          ts_utc: new Date().toISOString(),
        };

        if (stamped.type === 'options.ready') {
          stamped.model_execution = {
            ...stamped.model_execution,
            cached: true,
          };
          this.lastOptionsReady = stamped;
        }

        this.onEvent(stamped);

        if (stamped.type === 'options.ready' && this.autonomy) {
          this.startAutonomyCountdown(stamped.incident_id, stamped.recommended_id);
        }
      }
    } catch {
      // Fallback: replay the crisis segment from demo-stream.jsonl
      this.cancelCountdown();
      this.isVetoed = false;
      const crisisEvents = parseDemoStream().filter(
        e => e.seq >= 3 && e.type !== 'plan.applied' && !(e.type === 'solution.updated' && e.reason === 'plan_applied')
      );
      for (const ev of crisisEvents) {
        this.currentSeq++;
        const stamped: LiveEvent = {
          ...ev,
          seq: this.currentSeq,
          session_id: 'offline',
          hour: this.simHour,
          ts_utc: new Date().toISOString(),
        };
        if (stamped.type === 'options.ready') {
          stamped.model_execution = {
            ...stamped.model_execution,
            cached: true,
          };
          this.lastOptionsReady = stamped;
        }
        this.onEvent(stamped);
        if (stamped.type === 'options.ready' && this.autonomy) {
          this.startAutonomyCountdown(stamped.incident_id, stamped.recommended_id);
        }
      }
    }
  }

  private startAutonomyCountdown(incidentId: string, optionId: string) {
    this.cancelCountdown();
    let secondsLeft = 5;

    this.countdownInterval = window.setInterval(() => {
      if (this.isVetoed || !this.autonomy) {
        this.cancelCountdown();
        return;
      }

      this.currentSeq++;
      this.onEvent({
        seq: this.currentSeq,
        session_id: 'offline',
        hour: this.simHour,
        ts_utc: new Date().toISOString(),
        type: 'autonomy.countdown',
        incident_id: incidentId,
        option_id: optionId,
        seconds_left: secondsLeft,
      });

      if (secondsLeft <= 0) {
        this.cancelCountdown();
        if (!this.isVetoed && this.autonomy) {
          this.postDecisionCommand('offline', {
            incident_id: incidentId,
            option_id: optionId,
            decision: 'apply',
          });
        }
      } else {
        secondsLeft--;
      }
    }, 1000);
  }

  async postDecisionCommand(sessionId: string, cmd: DecideCommandRequest): Promise<void> {
    this.cancelCountdown();
    this.currentSeq++;
    
    if (cmd.decision === 'veto') {
      this.isVetoed = true;
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
        by: this.autonomy ? 'gemini_autonomous' : 'operator'
      });

      const opt = this.lastOptionsReady?.options?.find(o => o.option_id === cmd.option_id)
        || this.lastOptionsReady?.options?.[0];

      if (opt?.solution) {
        this.currentSeq++;
        this.onEvent({
          seq: this.currentSeq,
          session_id: 'offline',
          hour: this.simHour,
          ts_utc: new Date().toISOString(),
          type: 'solution.updated',
          reason: 'plan_applied',
          solution: opt.solution,
          grid_state: 'normal',
        });
      }
    }
  }
}
