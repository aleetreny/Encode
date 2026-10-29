import { build } from 'esbuild';
import { readFile, readdir, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

// Exercise the real controller and committed solver outputs without a browser or API.
const temp = await mkdtemp(join(tmpdir(), 'andes-portfolio-'));
try {
  const entry = resolve('src/live/offline.ts');
  const output = join(temp, 'controller.mjs');
  await build({
    entryPoints: [entry], bundle: true, format: 'esm', platform: 'node', outfile: output,
    plugins: [{ name: 'raw-fixture', setup(builder) {
      builder.onResolve({ filter: /\?raw$/ }, args => ({ path: resolve(args.resolveDir, args.path.slice(0, -4)), namespace: 'raw' }));
      builder.onLoad({ filter: /.*/, namespace: 'raw' }, async args => ({ contents: await readFile(args.path, 'utf8'), loader: 'text' }));
    } }],
  });
  const { strict: assert } = await import('node:assert');
  const library = await readdir(resolve('public/incidents'));
  let cases = 0;
  for (const file of library.filter(file => file.endsWith('.jsonl'))) {
    const rows = (await readFile(resolve('public/incidents', file), 'utf8')).trim().split('\n').map(JSON.parse);
    const ready = rows.find(row => row.type === 'options.ready');
    assert.ok(ready, file + ': missing options');
    assert.equal(ready.model_execution.cached, true, file + ': must be a replay');
    assert.equal(ready.options.length, 2);
    for (const option of ready.options) {
      assert.equal(option.validation.passed, true, file + ': invalid option');
      assert.ok(option.solution, file + ': missing actual solution');
    }
    cases++;
  }
  console.log(`Checked ${cases} committed outage cases.`);
  const { OfflineSessionController } = await import(pathToFileURL(output));
  const ticks = new Map();
  let timerId = 0;
  globalThis.window = {
    setInterval(callback) { ticks.set(++timerId, callback); return timerId; },
  };
  globalThis.clearInterval = id => ticks.delete(id);
  globalThis.fetch = async url => {
    assert.ok(url.startsWith('/incidents/'), 'only local committed incidents may be fetched');
    try { return new Response(await readFile(resolve('public' + url), 'utf8')); }
    catch { return new Response('', { status: 404 }); }
  };
  const events = [];
  const controller = new OfflineSessionController(event => events.push(event));
  controller.start();
  assert.ok(events.some(e => e.type === 'session.snapshot'));
  await controller.postClockCommand('offline', { action: 'seek', hour: 18.2 });
  await controller.injectCrisis('gas_centro');
  const options = events.findLast(e => e.type === 'options.ready');
  assert.ok(options && options.options.length === 2);
  assert.equal(options.hour, 18, 'recorded case uses its actual hour');
  assert.equal(options.model_execution.cached, true);
  for (const choice of options.options) {
    assert.equal(choice.validation.passed, true);
    assert.ok(choice.solution);
  }
  const alternative = options.options.find(o => o.option_id !== options.recommended_id) ?? options.options[1];
  await controller.postDecisionCommand('offline', { decision: 'apply', incident_id: options.incident_id, option_id: alternative.option_id });
  assert.equal(events.findLast(e => e.type === 'plan.applied').option_id, alternative.option_id);
  assert.deepEqual(events.findLast(e => e.type === 'solution.updated').solution, alternative.solution);
  for (let i = 0; i < 100; i++) for (const callback of ticks.values()) callback();
  assert.deepEqual(events.findLast(e => e.type === 'solution.updated').solution, alternative.solution, 'old walkthrough cannot overwrite chosen solution');
  await controller.injectCrisis('L2');
  const next = events.findLast(e => e.type === 'options.ready');
  assert.notEqual(next.incident_id, options.incident_id);
  const appliedCount = events.filter(e => e.type === 'plan.applied').length;
  await controller.postDecisionCommand('offline', { decision: 'apply', incident_id: next.incident_id, option_id: 'missing-option' });
  assert.equal(events.at(-1).type, 'error');
  assert.equal(events.filter(e => e.type === 'plan.applied').length, appliedCount);
  await controller.postDecisionCommand('offline', { decision: 'veto', incident_id: next.incident_id, option_id: next.recommended_id });
  assert.equal(events.filter(e => e.type === 'plan.applied').length, appliedCount);
  assert.equal(events.at(-1).type, 'plan.vetoed');
  await controller.injectCrisis('missing_asset');
  assert.equal(events.at(-1).type, 'error');
  controller.resetAndPlayDemo();
  assert.equal(events.at(-1).type, 'session.snapshot');
  controller.stop();
  assert.equal(ticks.size, 0);
  console.log('Portfolio verified: local cases, real options, alternative applied, no stale overwrite, veto, errors and restart.');
} finally { await rm(temp, { recursive: true, force: true }); }
