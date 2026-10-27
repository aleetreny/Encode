import React from 'react';
import './about.css';

export function About() {
  return <main className="portfolio-about">
    <nav><a href="/">← Explore the interactive demo</a><a href="https://github.com/aleetreny/Encode">Source code ↗</a></nav>
    <p className="portfolio-eyebrow">Encode London Hackathon · 24–25 October 2026 · Team of four</p>
    <h1>Andes / GridPilot</h1>
    <p className="portfolio-lead">Explore how a power grid recovers from a sudden outage.</p>
    <p>A control-room simulation of Chile’s north–south electricity corridor. Trigger a plant or transmission outage, inspect the impact, compare recovery options and choose which plan to apply. The map shows the resulting generation, line flows and equivalent household supply.</p>
    <a className="portfolio-launch" href="/">Open the demo →</a>
    <h2>A demo built to last</h2>
    <p>This public edition runs in your browser without a Google API key or a backend. It replays committed results calculated by the HiGHS optimisation solver and checked by an independent validator. It does not call an AI model or calculate new dispatch plans in your browser.</p>
    <p>Each outage opens an independent four-hour contingency at the nearest recorded hour: 09:00, 12:00, 13:00, 18:00, 19:00 or 20:00. Applying either plan displays that plan’s recorded solution. Outages are separate cases; they do not accumulate into a newly solved scenario. “Replay session” restarts the recorded walkthrough.</p>
    <h2>The original hackathon system</h2>
    <p>Gemini investigated disruptions, called operational tools and explained recovery options. A deterministic solver calculated dispatch and an independent validator checked the constraints. The operator could approve or veto a plan; an autonomous simulation mode could apply a validated recommendation after a countdown.</p>
    <p>The original Gemini adapter, Python backend, solver, validator, reports and datasets remain in the repository. They can be run separately; the public demo does not depend on them being online.</p>
    <h2>What the data means</h2>
    <p>The historical-day scenario uses committed CEN data from 14 August 2026 alongside a reduced five-zone model. Aggregate assets, corridor capacities, household equivalences and other assumptions are documented in the repository. Observations, assumptions and simulated outcomes describe different things. Homes shown as reconnected are model equivalents, not measured household reconnections.</p>
    <p>This is a simulation. It does not control Chile’s physical grid, issue SCADA commands or reproduce the complete national network.</p>
    <h2>What the team built</h2>
    <ul><li>An interactive grid visualisation with outage and recovery states.</li><li>Operational optimisation with transmission, generation and storage constraints.</li><li>Independent physics validation and a human decision gate.</li><li>A Gemini tool loop, an event-streaming backend and auditable reports.</li><li>Historical data ingestion, provenance and reproducible scenarios.</li></ul>
    <p>This was a four-person project. Contributions and authorship are preserved in Git history.</p>
    <h2>Explore the implementation</h2>
    <p><a href="https://github.com/aleetreny/Encode">Repository and team history ↗</a> · <a href="https://github.com/aleetreny/Encode/tree/feature/real-day">Historical-day implementation ↗</a></p>
    <footer>React + TypeScript · FastAPI + Python · HiGHS · independent validation · optional Gemini integration</footer>
  </main>;
}
