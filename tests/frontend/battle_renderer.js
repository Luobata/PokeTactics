/* Browser battle renderer contracts: run as
 *   node tests/frontend/battle_renderer.js <script.json> <scenario>
 * The script comes from tools/acceptance/battle_script.py (a real battle). */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const R = require('../../tools/acceptance/battle_renderer.js');

const root = path.resolve(__dirname, '../..');
const readDir = (dir) => Object.fromEntries(fs.readdirSync(path.join(root, dir)).filter((f) => f.endsWith('.json'))
  .map((f) => [f.slice(0, -5), JSON.parse(fs.readFileSync(path.join(root, dir, f), 'utf8'))]));
const packs = {motion: readDir('assets/motion'), vfx: readDir('assets/vfx')};
const script = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const scenario = process.argv[3];
const freshPlan = () => R.compile(JSON.parse(JSON.stringify(script)), R.mergePacks(JSON.parse(JSON.stringify(packs))));

const cases = {
  determinism() {
    const a = freshPlan(), b = freshPlan();
    const times = [0, 0.37, 1.25, a.duration * 0.3, a.duration * 0.55, a.duration * 0.8, a.duration];
    const forward = times.map((t) => JSON.stringify(R.frame(a, t)));
    // Scrubbing order (backwards, repeated) must not change any draw list.
    const backward = times.slice().reverse().map((t) => JSON.stringify(R.frame(b, t))).reverse();
    assert.deepEqual(forward, backward, 'same script + t must give the same draw list');
    assert.equal(JSON.stringify(R.frame(a, times[3])), forward[3], 'repeat evaluation is stable');
    for (const list of forward) assert.ok(JSON.parse(list).items.length > 0);
    // Every primary action draws something while its window is open.
    const sample = a.actions.find((x) => !x.secondary && !x.terrain);
    const mid = R.toPlayback(a, (sample.release + sample.impact) / 2);
    assert.ok(R.frame(a, mid).items.some((it) => it.op === 'sprite' && it.idx === sample.actor));
    console.log('OK renderer determinism');
  },
  variety() {
    const plan = freshPlan();
    const m = R.monotony(plan);
    assert.ok(m.actions >= 20, 'fixture needs a real multi-unit battle');
    assert.ok(m.combos.share < 0.35, `top timing combo share ${m.combos.share} must be < 35%`);
    assert.ok(m.combos.share < m.timeline_combos.share, 'retiming must be more varied than the raw timeline');
    assert.ok(m.family_variety >= 3, 'several projectile / contact families are used');
    for (const h of m.hitstops) assert.ok(h.frames60 >= 2, 'every hitstop is visible for at least 2 frames at 60 fps');
    console.log('OK renderer variety', m.combos.share.toFixed(3), m.timeline_combos.share.toFixed(3));
  },
  invariants() {
    const plan = freshPlan();
    // Impacts are authoritative: retiming may move windup/recovery only.
    const byIndex = new Map(script.actions.map((a) => [a.i, a]));
    for (const a of plan.actions) {
      assert.equal(a.impact, byIndex.get(a.i).impact);
      assert.ok(a.start <= a.release + 1e-9 && a.release <= a.impact + 1e-9 && a.impact <= a.end + 1e-9, `action ${a.i} order`);
    }
    // Per actor, windows never overlap.
    const byActor = {};
    for (const a of plan.actions.filter((x) => !x.secondary && !x.terrain)) (byActor[a.actor] ||= []).push(a);
    for (const list of Object.values(byActor)) {
      list.sort((x, y) => x.impact - y.impact);
      for (let k = 1; k < list.length; k++) assert.ok(list[k].start >= list[k - 1].end - 1e-6, 'actor windows overlap');
    }
    // The warp keeps total length and is monotonic.
    assert.ok(Math.abs(R.toSim(plan, plan.playbackDuration) - plan.duration) < 1e-6);
    let prev = -1;
    for (let p = 0; p <= plan.playbackDuration; p += 1 / 60) {
      const s = R.toSim(plan, p);
      assert.ok(s >= prev - 1e-9, 'warp must be monotonic');
      prev = s;
    }
    // Team telemetry at the end equals the authoritative last states.
    const totals = R.teamTotals(plan, plan.playbackDuration);
    for (const team of [0, 1]) {
      const hp = script.units.filter((u) => u.team === team)
        .reduce((sum, u) => sum + Math.max(0, script.states[u.idx].at(-1)[1]), 0);
      assert.equal(totals.hp[team], hp);
    }
    console.log('OK renderer invariants');
  },
  unknownEvents() {
    const copy = JSON.parse(JSON.stringify(script));
    const t = Math.min(2, copy.clock.duration / 2);
    const a = copy.units[0].idx, b = copy.units.at(-1).idx;
    copy.events.push([t, t, 'effect', a, b, 'frost_mark', {label: '霜印', value: 12, kind: 'debuff', camera: 'focus'}]);
    copy.events.push([t, t, 'mystery_kind', a, b, {anything: [1, 2]}]);
    copy.events.push([t, t, 'effect', a, null, 'odd', 'not-a-dict']);
    // arena_v2: team-wide effects use -1 for source and target.
    copy.events.push([t, t, 'effect', -1, -1, 'charge_horn', {source: 'augment', team: 1, kind: 'shield', label: '冲锋号', value: 49}]);
    copy.events.push([t, t, 'effect', a, a, 'charge_horn', {source: 'augment', team: 0, kind: 'move', label: '跃进', value: 0, origin: [1, 4], destination: [1, 3]}]);
    copy.arena.terrain = {id: 'mana_spring', name: '能量泉', cells: [[2, 3, 0], [3, 2, 1]]};
    copy.events.sort((x, y) => x[0] - y[0]);
    const plan = R.compile(copy, R.mergePacks(packs));
    const list = R.frame(plan, R.toPlayback(plan, t + 0.2));
    // Linked effects at one instant are staged one after another (chain beats),
    // so collect the labels across the chain window.
    const labels = [0.2, 0.45, 0.75].flatMap((dt) => R.frame(plan, R.toPlayback(plan, t + dt)).items)
      .filter((it) => it.op === 'label').map((it) => it.text)
      .filter((text, index, all) => all.indexOf(text) === index);
    assert.ok(labels.includes('霜印 12'), `effect label rendered: ${labels}`);
    assert.ok(labels.some((text) => /mystery/.test(text)), 'unknown kinds degrade to a generic pop');
    assert.ok(labels.includes('冲锋号 +49'), `team-wide effect pops once: ${labels}`);
    assert.equal(labels.filter((text) => text === '冲锋号 +49').length, 1);
    assert.ok(labels.includes('跃进'), 'move effects show the label without a zero value');
    assert.equal(list.items.filter((it) => it.op === 'cell').length, 2, 'terrain cells are tinted');
    assert.ok(plan.cameras.some((c) => c.kind === 'focus'), 'camera: focus payload is honoured');
    console.log('OK renderer unknown events');
  },
  portableSampler() {
    // Linear keys sample exactly like esp32_runtime.animation.sample_track.
    const expected = JSON.parse(process.argv[4]);
    const keys = expected.keys;
    for (const [p, pose] of expected.samples) assert.deepEqual(R.samplePortable(keys, p), pose, `progress ${p}`);
    // The eased render sampler agrees at keyframes.
    for (const key of keys) {
      const pose = R.sampleTrack(keys.map((k) => [...k, 'easeOutBack']), key[0]);
      assert.equal(Math.round(pose.dx), key[1]);
    }
    console.log('OK renderer sampler');
  },
};

if (!cases[scenario]) throw new Error(`unknown scenario ${scenario}`);
cases[scenario]();
