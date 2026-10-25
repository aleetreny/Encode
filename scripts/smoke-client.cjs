/** Exercise the shared frontend TypeScript client against the real backend.
 * No UI or Google execution is implied by a deterministic/replay run.
 * Compile contracts to CommonJS in a scratch directory before invoking this.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {createHash} = require('node:crypto');

async function main() {
  const [moduleDir, base = 'http://127.0.0.1:8000', mode = 'deterministic', reportDir = 'var/demo-client-verification'] = process.argv.slice(2);
  if (!moduleDir || !['live', 'replay', 'deterministic'].includes(mode)) {
    throw new Error('Usage: node scripts/smoke-client.cjs <compiled-contract-directory> [backend-origin] [live|replay|deterministic] [report-directory]');
  }
  const {nativeGridPilotClient} = require(path.resolve(moduleDir, 'native-client.js'));
  const api = nativeGridPilotClient(base, process.env.GRIDPILOT_API_TOKEN || '');
  const scenario = await api.scenario();
  assert.equal(scenario.schema_version, '2.0.0');
  let run = await api.start(mode, {allow_cached_fallback: false}, 'operator_approval', scenario.scenario_id);
  const deadline = Date.now() + 120_000;
  while (['queued', 'running'].includes(run.status)) {
    assert.ok(Date.now() < deadline, 'Investigation polling timed out');
    await new Promise(resolve => setTimeout(resolve, 250));
    run = await api.run(run.run_id);
  }
  assert.equal(run.status, 'completed', JSON.stringify(run.error));
  assert.equal(run.execution_mode, mode, 'Substituted execution cannot pass the client demo gate');
  assert.equal(run.provenance.live_gemini, mode === 'live');
  assert.ok(!run.fallback, 'Fallback cannot pass a strict demo test');
  assert.equal(run.validation.passed, true);
  assert.equal(run.candidate.accepted, true);
  assert.equal(run.approval_status, 'pending');
  const approved = await api.decision(run, 'approved', 'shared TypeScript client smoke', 'Simulation-only integration test');
  const persisted = await api.run(run.run_id);
  assert.equal(approved.approval_status, 'approved');
  assert.equal(persisted.approval_status, 'approved');
  assert.equal(persisted.revision, approved.revision);
  assert.equal(persisted.decision.scope, 'simulation_only');
  const response = await fetch(api.reportUrl(run.run_id));
  assert.ok(response.ok, `Report HTTP ${response.status}`);
  assert.match(response.headers.get('Content-Disposition') || '', /attachment/);
  const raw = await response.text();
  const report = JSON.parse(raw);
  assert.equal(report.run_id, run.run_id);
  assert.equal(report.approval_status, 'approved');
  assert.equal(report.execution_mode, mode);
  assert.equal(report.decision.scope, 'simulation_only');
  assert.equal(report.validation.passed, true);
  await fs.mkdir(reportDir, {recursive: true});
  const file = path.resolve(reportDir, `${mode}-${run.run_id}.json`);
  await fs.writeFile(file, raw);
  console.log(JSON.stringify({
    client: 'contracts/native-client.ts',
    scenario_id: scenario.scenario_id,
    run_id: run.run_id,
    execution_mode: run.execution_mode,
    live_gemini: run.provenance.live_gemini,
    validation_passed: true,
    persisted_approval: persisted.approval_status,
    downloaded_report: file,
    report_sha256: createHash('sha256').update(raw).digest('hex'),
    browser_ui_verified: false,
  }));
}
main().catch(error => {
  console.error(JSON.stringify({passed: false, error: error.message, status: error.status, details: error.details}));
  process.exitCode = 1;
});
