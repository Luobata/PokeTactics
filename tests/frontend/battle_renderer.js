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
/** PMD bundle straight from assets/pmd (what /api/pmd/manifest serves). */
function pmdBundle() {
  const dir = path.join(root, 'assets/pmd');
  const index = JSON.parse(fs.readFileSync(path.join(dir, 'index.json'), 'utf8'));
  const species = {}, fallback = {};
  for (const unit of script.units) {
    const row = index.species[String(unit.sid)];
    if (row) species[unit.sid] = JSON.parse(fs.readFileSync(path.join(dir, row.file), 'utf8'));
    else fallback[unit.sid] = index.fallback[String(unit.sid)] || {style: 'classic', reason: 'missing'};
  }
  const actions = JSON.parse(fs.readFileSync(path.join(dir, 'actions.json'), 'utf8'));
  return {base: '/pmd/', species, fallback, actions};
}
const pmdPlan = () => R.compile(JSON.parse(JSON.stringify(script)), R.mergePacks(JSON.parse(JSON.stringify(packs))), {style: 'pmd', pmd: pmdBundle()});

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
  pmd() {
    const bundle = pmdBundle();
    const plan = pmdPlan();
    // every unit resolves to PMD frames or an explicit classic fallback
    for (const unit of script.units) {
      assert.ok(plan.units[unit.idx].pmd || bundle.fallback[unit.sid], `#${unit.sid} has neither PMD nor a fallback`);
    }
    const pmdUnits = Object.values(plan.units).filter((u) => u.pmd);
    assert.ok(pmdUnits.length >= script.units.length - 1, 'nearly every arena unit has PMD frames');
    // HitFrame lands exactly on the authoritative impact (impacts never move)
    const byIndex = new Map(script.actions.map((a) => [a.i, a]));
    let checked = 0;
    for (const a of plan.actions) {
      const unit = plan.units[a.actor];
      if (!unit.pmd || a.secondary || a.terrain || !a.pmdAnim || !a.pmdAnim.main) continue;
      assert.equal(a.impact, byIndex.get(a.i).impact);
      const anim = unit.pmd.anims[a.pmdAnim.main];
      if (!Number.isInteger(anim.hit) || unit.death && unit.death.t <= a.end) continue;
      const at = R.unitPose(plan, unit, a.impact);
      if (!at.pmd || at.pmd.anim !== a.pmdAnim.main) continue;
      assert.equal(at.pmd.frame, anim.hit, `action ${a.i}: hit frame at impact`);
      if (anim.hit > 0) {
        const before = R.unitPose(plan, unit, a.impact - 1e-4);
        if (before.pmd.anim === a.pmdAnim.main) assert.ok(before.pmd.frame < anim.hit, `action ${a.i}: before impact`);
      }
      checked++;
    }
    assert.ok(checked >= 10, `checked ${checked} actions`);
    // determinism with style: scrubbing order does not change draw lists
    const times = [0.2, 1.1, plan.duration * 0.4, plan.duration * 0.75];
    const fwd = times.map((t) => JSON.stringify(R.frame(plan, t)));
    const other = pmdPlan();
    const back = times.slice().reverse().map((t) => JSON.stringify(R.frame(other, t))).reverse();
    assert.deepEqual(fwd, back);
    const sprites = JSON.parse(fwd[1]).items.filter((it) => it.op === 'sprite' && it.pmd);
    assert.ok(sprites.length > 0 && sprites.every((it) => it.pmd.dir >= 0 && it.pmd.dir <= 4), 'stored directions only');
    // style switch keeps the timeline: same actions/impacts, classic sprites
    const classic = freshPlan();
    assert.deepEqual(classic.actions.map((a) => [a.i, a.start, a.release, a.impact, a.end]),
      plan.actions.map((a) => [a.i, a.start, a.release, a.impact, a.end]));
    assert.ok(R.frame(classic, times[1]).items.filter((it) => it.op === 'sprite').every((it) => !it.pmd));
    // style param
    assert.equal(R.spriteStyle('?sprites=classic'), 'classic');
    assert.equal(R.spriteStyle('?sprites=pmd'), 'pmd');
    assert.equal(R.spriteStyle(''), 'pmd');
    console.log('OK renderer pmd', pmdUnits.length, checked);
  },
  causeLinks() {
    const plan = freshPlan();
    // Outcomes come only from payload cast_index / action_index ownership.
    const byIndex = new Map(plan.actions.map((a) => [a.i, a]));
    let linked = 0;
    for (const row of script.events) {
      if (!['skill_effect', 'combo_effect', 'field_effect'].includes(row[2])) continue;
      const payload = row[7] || {};
      const owner = byIndex.get(payload.cast_index) || byIndex.get(payload.action_index);
      if (!owner || row[6] === 'expire' || row[6] === 'absorb') continue;
      assert.ok(owner.outcomes.some((o) => o.t === row[0] && o.tgt === row[4] && o.sub === row[6]), `outcome of ${owner.i} missing`);
      linked++;
    }
    assert.ok(linked > 10, 'fixture has cause-linked effects');
    for (const chain of plan.chains) {
      const owner = byIndex.get(chain.cause);
      assert.ok(owner, 'every chain names its owning action');
      for (const beat of chain.beats.slice(1)) assert.ok(owner.outcomes.some((o) => o.tgt === beat.unit), 'beats are owned outcomes');
      for (let k = 1; k < chain.beats.length; k++) assert.ok(chain.beats[k].t >= chain.beats[k - 1].t - 1e-9, 'beats are staged in order');
    }
    console.log('OK renderer cause links', linked, plan.chains.length);
  },
  parts() {
    const plan = freshPlan();
    const melee = plan.actions.find((a) => a.melee && !a.secondary && a.release - a.start > 0.1);
    const mid = R.toPlayback(plan, (melee.start + melee.release) / 2);
    const sprite = R.frame(plan, mid).items.find((it) => it.op === 'sprite' && it.idx === melee.actor && !it.ghost);
    assert.ok(Math.abs(sprite.parts.lean) > 1, `anticipation leans the body: ${JSON.stringify(sprite.parts)}`);
    const bare = freshPlan();
    for (const u of Object.values(bare.units)) u.parts = {};
    const still = R.frame(bare, mid).items.find((it) => it.op === 'sprite' && it.idx === melee.actor && !it.ghost);
    assert.equal(still.parts.lean, 0, 'without part tracks the body is not deformed');
    const hit = plan.hits.find((h) => h.ratio > 0.05);
    const hs = R.frame(plan, R.toPlayback(plan, hit.t + 0.05)).items.find((it) => it.op === 'sprite' && it.idx === hit.unit && !it.ghost);
    assert.ok(hs.parts.wobble > 1, 'hits ring a wobble through the body');
    console.log('OK renderer parts');
  },
  paintAll() {
    // Every op and fx shape paints through a recording 2D context without throwing.
    const calls = {n: 0};
    const ctx = new Proxy({}, {get: (target, key) => {
      if (key in target) return target[key];
      if (key === 'createRadialGradient' || key === 'createLinearGradient') return () => ({addColorStop() {}});
      if (key === 'measureText') return () => ({width: 10});
      if (key === 'getImageData') return () => ({data: new Uint8ClampedArray(4)});
      return () => { if (['fill', 'stroke', 'fillRect', 'drawImage', 'fillText', 'strokeText'].includes(key)) calls.n++; };
    }, set: (target, key, value) => { target[key] = value; return true; }});
    globalThis.OffscreenCanvas = class { constructor(w, h) { this.width = w; this.height = h; } getContext() { return ctx; } };
    const plan = freshPlan();
    for (let t = 0; t <= plan.playbackDuration; t += 0.25) R.paint(ctx, plan, R.frame(plan, t), {});
    const shapes = JSON.parse(process.argv[4]);
    const camera = {fx: 480, fy: 320, zoom: 1, shakeX: 0, shakeY: 0, dim: 0, focus: []};
    const pal = R.TYPE_COLORS.FIRE;
    for (const shape of shapes) {
      for (const k of [0.1, 0.4]) {
        const before = calls.n;
        R.paint(ctx, plan, {camera, items: [{op: 'fx', shape, x: 400, y: 300, bx: 520, by: 260, fy: 330, size: 50, k, raw: k, pal, seed: 7,
          count: 6, dir: 0.4, particle: 'ember', material: {gravity: 100, size: [2, 4]}, frame: 3, layer: 6}]}, {});
        assert.ok(calls.n > before, `${shape} draws something at k=${k}`);
      }
    }
    console.log('OK renderer paint', shapes.length);
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
