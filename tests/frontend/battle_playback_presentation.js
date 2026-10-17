/* Run shipped replay controls against a controlled DOM, image loader, and clock. */
const assert = require('node:assert/strict');
const {page, stateFixture, ranking} = require('./battle_report_presentation.js');
const scenario = process.argv[4];

function fixture(options = {}) {
  const state = stateFixture({phase: options.phase || 'battle'});
  const n = options.n ?? 9;
  state.last_battle = {...state.last_battle, n, dt: .05,
    width: 960, height: 640, presentation: 'web-arena-v2-articulated', render_revision: 'web-arena-v2-articulated',
    duration: (n - 1) * .05,
    combatants: [
      {idx: 0, team: 0, sid: 26, name: '雷丘', star: 2, role: 'attack', range: 3, max_hp: 100},
      {idx: 1, team: 1, sid: 68, name: '怪力', star: 2, role: 'attack', range: 1, max_hp: 100},
    ],
    team_frames: Array.from({length: n}, (_, i) => ({alive: [1, i === n - 1 ? 0 : 1], hp: [100, 100 - Math.round(i / Math.max(1, n - 1) * 100)]})),
    events: [{t: 0, text: '战斗开始'}, {t: .1, text: '雷丘击中怪力'}, {t: (n - 1) * .05, text: '战斗结束'}],
    ...options,
  };
  return state;
}
const imageOptions = {imageWidth: 960, imageHeight: 640};
const frameIndex = src => Number(new URL(src, 'http://fixture.invalid').pathname.match(/\/(\d+)\.png$/)?.[1]);
const lastDraw = p => p.events.canvas.filter(row => row[0] === 'drawImage').at(-1);
const currentFrame = p => lastDraw(p) ? frameIndex(lastDraw(p)[1]) : null;
const intervals = p => [...p.timers.values()].filter(timer => timer.kind === 'interval');
const imagesFor = (p, index) => p.imageRecords.filter(record => frameIndex(record.src) === index);
function visibleTime(p) {
  const text = p.element('battle-clock').textContent.trim();
  const clock = text.match(/^(\d+):(\d+(?:\.\d+)?)/);
  return clock ? Number(clock[1]) * 60 + Number(clock[2]) : Number(text.match(/\d+(?:\.\d+)?/)?.[0]);
}
const liveImages = p => p.pendingImages().filter(record => record.image.onload || record.image.onerror);
function noFinalReport(p) {
  assert.equal(p.element('battle-verdict').hidden, true, 'Playback must not reveal the final verdict early');
  assert.equal(p.element('battle-statistics').querySelectorAll('[data-stat-unit]').length, 0,
    'Playback must not build final statistics before the ending is reached');
  assert.equal(p.element('battle-rewards').hidden, true, 'Rewards must wait for the ending');
}
async function loadAllPending(p) {
  for (let turns = 0; turns < 120; turns++) {
    const pending = liveImages(p);
    if (!pending.length) {await p.settle(); if (!liveImages(p).length) return;}
    for (const record of pending) record.load();
    await p.settle();
  }
  assert.fail('Image prefetch did not settle within the bounded fixture');
}
async function openManual(options = {}, pageOptions = {}) {
  const p = await page(fixture(options), {...imageOptions, manualImages: true, ...pageOptions});
  const opening = await p.startClick(p.element('fight-button'));
  assert.equal(p.element('battle-dialog').open, true);
  return {p, opening};
}
async function seek(p, index) {
  const slider = p.element('battle-seek'); slider.value = String(index);
  await p.dispatch('battle-seek', 'input');
}
const cases = {
  async controls() {
    const p = await page(fixture(), imageOptions);
    await p.click(p.element('fight-button'));
    assert.equal(p.element('battle-dialog').open, true);
    assert.equal(currentFrame(p), 0); noFinalReport(p);
    assert.equal(p.element('battle-canvas').width, 960);
    assert.equal(p.element('battle-canvas').height, 640);
    assert.equal(p.element('battle-canvas').getContext('2d').imageSmoothingEnabled, true);
    assert.equal(new URL(lastDraw(p)[1], 'http://fixture.invalid').searchParams.get('v'), 'web-arena-v2-articulated');
    assert.equal(intervals(p).length, 1);
    await p.tick(2); assert.equal(currentFrame(p), 2); noFinalReport(p);
    await p.click(p.element('battle-pause')); assert.equal(intervals(p).length, 0);
    const draws = p.events.canvas.length;
    await p.tick(3); assert.equal(p.events.canvas.length, draws, 'Paused playback must not advance');
    await p.change('battle-speed', 4); assert.equal(intervals(p).length, 0, 'Speed changes do not resume paused playback');
    await p.click(p.element('battle-pause')); assert.equal(intervals(p).length, 1);
    assert.equal(intervals(p)[0].delay, 12.5);
    await p.tick(); assert.equal(currentFrame(p), 3);
    const requests = p.events.images.length;
    await seek(p, 1); assert.equal(currentFrame(p), 1);
    assert.equal(intervals(p).length, 0, 'Scrubbing pauses the old playback timer');
    assert.equal(p.events.images.length, requests, 'Seeking to cached frames does not download them again');
    noFinalReport(p); p.unchanged();
    const currentUrl = p.events.images.find(src => frameIndex(src) === 0);
    for (const [presentation, smooth, dimensions] of [
      ['web-arena-v1', true, imageOptions],
      ['device-v1', false, {imageWidth: 240, imageHeight: 320}],
    ]) {
      const previous = await page(fixture({presentation, render_revision: presentation}), dimensions);
      await previous.click(previous.element('fight-button'));
      assert.equal(previous.element('battle-canvas').getContext('2d').imageSmoothingEnabled, smooth,
        `Smoothing must keep ${presentation} compatible`);
      assert.equal(new URL(lastDraw(previous)[1], 'http://fixture.invalid').searchParams.get('v'), presentation);
      assert.equal(new URL(lastDraw(previous)[1], 'http://fixture.invalid').pathname, new URL(currentUrl, 'http://fixture.invalid').pathname);
      assert.notEqual(lastDraw(previous)[1], currentUrl, 'Render revisions must have separate browser cache identities');
      assert.equal(previous.element('battle-canvas').width, dimensions.imageWidth);
      assert.equal(previous.element('battle-canvas').height, dimensions.imageHeight);
      noFinalReport(previous); previous.unchanged();
    }
  },
  async progressive() {
    const {p, opening} = await openManual({n: 120});
    noFinalReport(p); assert.equal(currentFrame(p), null);
    const first = imagesFor(p, 0)[0]; assert.ok(first, 'The opening frame is requested immediately');
    const later = liveImages(p).find(record => frameIndex(record.src) > 0);
    assert.ok(later, 'Loading uses more than one worker');
    later.load(); await p.settle();
    assert.equal(currentFrame(p), null, 'An early prefetch cannot become the current frame');
    assert.equal(p.element('battle-enemy-hp-bar').style.width, '100%', 'Prefetch does not show future damage');
    assert.equal(visibleTime(p), 0);
    first.load(); await p.settle(); assert.equal(currentFrame(p), 0);
    await loadAllPending(p); await opening.done; await p.settle();
    assert.equal(currentFrame(p), 0, 'Prefetching changes loaded progress but does not advance playback');
    assert.ok(Number(p.element('battle-status').dataset.loadedFrames) > 1);
    assert.equal(p.element('battle-seek').value, '0');
    assert.equal(p.element('battle-enemy-hp-bar').style.width, '100%');
    assert.ok(p.events.images.length < 120, 'Long battles do not download every frame before playback');
    assert.ok(intervals(p).length <= 1);
    await p.tick(2); assert.equal(currentFrame(p), 2);
    await seek(p, 110);
    assert.equal(currentFrame(p), 2, 'A pending seek keeps the last rendered frame until its image arrives');
    assert.equal(p.element('battle-loading').hidden, false);
    await loadAllPending(p); await p.settle();
    assert.equal(currentFrame(p), 110); noFinalReport(p);
    assert.equal(visibleTime(p), 5.5);
    assert.equal(p.element('battle-seek').value, '110');
    assert.equal(p.element('battle-enemy-hp-bar').parentElement.title, '剩余总生命 8 / 100');
    assert.ok(Number(p.element('battle-status').dataset.cachedFrames) <= 72, 'Decoded image caching remains bounded after a large seek');
    const oldOpeningRequests = imagesFor(p, 0).length;
    await seek(p, 0); assert.equal(currentFrame(p), 110, 'Seeking to an evicted frame holds the previous image');
    assert.ok(imagesFor(p, 0).length > oldOpeningRequests, 'Seeking backwards reloads the evicted opening frame');
    await loadAllPending(p); await p.settle();
    assert.equal(currentFrame(p), 0); assert.equal(visibleTime(p), 0); noFinalReport(p);
    assert.equal(p.element('battle-enemy-hp-bar').style.width, '100%');
    assert.ok(Number(p.element('battle-status').dataset.cachedFrames) <= 72);
    p.unchanged();
  },
  async rollingCache() {
    for (const mobile of [false, true]) {
      const {p, opening} = await openManual({n: 240}, {mobile});
      await loadAllPending(p); await opening.done;
      const limit = mobile ? 36 : 72;
      for (let frame = 1; frame <= 100; frame++) {
        await p.tick(); await loadAllPending(p);
        assert.equal(currentFrame(p), frame, 'Moving-window prefetch keeps playback advancing');
        assert.ok(Number(p.element('battle-status').dataset.cachedFrames) <= limit,
          'Desktop and mobile keep their decoded image window bounded');
        noFinalReport(p);
      }
      const requested = p.events.images.map(frameIndex);
      assert.equal(new Set(requested).size, requested.length,
        'Continuous forward playback must not evict and endlessly re-request its far lookahead');
      assert.equal(visibleTime(p), 5); assert.equal(p.events.fetches.length, 1);
      p.unchanged();
    }
  },
  async ending() {
    const p = await page(fixture(), imageOptions);
    await p.click(p.element('fight-button')); noFinalReport(p);
    await p.click(p.element('battle-statistics-tab')); noFinalReport(p);
    assert.equal(p.element('battle-statistics-panel').hidden, false);
    await p.click(p.element('battle-rewards-tab')); noFinalReport(p);
    await p.click(p.element('battle-skip'));
    assert.equal(currentFrame(p), 8); assert.equal(intervals(p).length, 0);
    assert.equal(p.element('battle-verdict').hidden, false);
    assert.deepEqual(ranking(p, 'battle'), [0, 1, 3, 2]);
    const requests = p.events.images.length;
    await seek(p, 2); assert.equal(currentFrame(p), 2); noFinalReport(p);
    assert.doesNotMatch(p.element('battle-result').textContent, /当前回合胜利/);
    await p.click(p.element('battle-replay'));
    assert.equal(currentFrame(p), 0); assert.equal(intervals(p).length, 1); noFinalReport(p);
    assert.equal(p.events.images.length, requests, 'Replay uses existing image frames');
    await p.tick(8); assert.equal(currentFrame(p), 8);
    assert.equal(intervals(p).length, 0); assert.equal(p.element('battle-verdict').hidden, false);
    assert.equal(p.events.fetches.length, 1, 'Replay does not replay simulation or grant rewards');
    p.unchanged();
  },
  async failure() {
    const {p, opening} = await openManual();
    imagesFor(p, 0)[0].fail(); await p.settle();
    assert.equal(p.element('battle-retry').hidden, true, 'A first failure silently schedules an automatic retry');
    await p.expireTimeouts(1200);
    assert.equal(imagesFor(p, 0).length, 2, 'The failed frame is automatically requested again');
    imagesFor(p, 0)[1].fail(); await p.settle(); await p.expireTimeouts(1200);
    assert.equal(imagesFor(p, 0).length, 3, 'The second failure gets one more automatic attempt');
    imagesFor(p, 0)[2].fail(); await p.settle();
    await loadAllPending(p); await opening.done; await p.settle();
    assert.equal(currentFrame(p), null); assert.equal(intervals(p).length, 0); noFinalReport(p);
    assert.equal(p.element('battle-retry').hidden, false, 'Only repeated failures offer an explicit retry');
    const before = imagesFor(p, 0).length;
    await p.startClick(p.element('battle-retry'));
    assert.ok(imagesFor(p, 0).length > before, 'Retry issues a fresh request for the failed frame');
    await loadAllPending(p); await p.settle(); assert.equal(currentFrame(p), 0); noFinalReport(p);
    await p.tick(2); assert.equal(currentFrame(p), 2);
    await p.click(p.element('battle-close')); assert.equal(p.element('battle-dialog').open, false);
    assert.equal(intervals(p).length, 0); assert.equal(p.events.fetches.length, 1); p.unchanged();
  },
  async autoRetryRecovery() {
    const {p, opening} = await openManual();
    const first = imagesFor(p, 0)[0]; first.fail(); await p.settle();
    assert.equal(currentFrame(p), null, 'A failed opening frame is not drawn');
    await p.expireTimeouts(1200);
    await loadAllPending(p); await opening.done; await p.settle();
    assert.equal(currentFrame(p), 0, 'A transient failure recovers without any manual retry');
    assert.equal(p.element('battle-retry').hidden, true);
    await p.tick(2); assert.equal(currentFrame(p), 2); noFinalReport(p);
    assert.equal(p.events.fetches.length, 1); p.unchanged();
  },
  async midstreamFailure() {
    const {p, opening} = await openManual();
    for (const record of [...liveImages(p)]) record.load();
    await p.settle();
    const failed = imagesFor(p, 5)[0]; assert.ok(failed, 'The lookahead requests the future frame');
    failed.fail(); await p.settle();
    assert.equal(p.element('battle-retry').hidden, true, 'A single prefetch failure stays silent');
    await p.expireTimeouts(1200);
    assert.ok(imagesFor(p, 5).length > 1, 'The failed future frame is automatically re-requested');
    await loadAllPending(p); await opening.done;
    assert.equal(currentFrame(p), 0); assert.equal(intervals(p).length, 1);
    await p.tick(5);
    assert.equal(currentFrame(p), 5, 'Automatic retry lets playback cross the recovered frame');
    assert.equal(visibleTime(p), .3); noFinalReport(p);
    assert.equal(intervals(p).length, 1);
    assert.equal(p.element('battle-retry').hidden, true, 'Recovery needs no explicit retry');
    p.unchanged();
  },
  async explicitFailureResult() {
    const {p, opening} = await openManual();
    for (let turns = 0; turns < 10 && !imagesFor(p, 8).length; turns++) {
      for (const record of [...liveImages(p)]) record.load();
      await p.settle();
    }
    for (let tries = 0; tries < 3; tries++) {
      const record = imagesFor(p, 8).at(-1);
      assert.ok(record && !record.settled, 'The ending frame is re-requested after each automatic retry');
      record.fail(); await p.settle(); await p.expireTimeouts(1200);
    }
    await loadAllPending(p); await opening.done; noFinalReport(p);
    assert.equal(currentFrame(p), 0);
    await p.click(p.element('battle-skip'));
    assert.equal(currentFrame(p), 0, 'A failed ending image cannot overwrite the last valid frame');
    assert.equal(p.element('battle-verdict').hidden, false, 'Explicitly viewing the saved result works even when the final image is missing');
    assert.deepEqual(ranking(p, 'battle'), [0, 1, 3, 2]);
    assert.equal(p.element('battle-next').disabled, false, 'Image failure must not lock progression after explicit result viewing');
    assert.equal(intervals(p).length, 0); assert.equal(p.events.fetches.length, 1); p.unchanged();
  },
  async staleLoads() {
    const {p, opening} = await openManual();
    const old = [...liveImages(p)];
    const callbacks = old.map(record => ({record, onload: record.image.onload, onerror: record.image.onerror}));
    const oldTimeouts = [...p.timers.values()].filter(timer => timer.kind === 'timeout' && timer.delay >= 10000);
    await p.click(p.element('battle-close'));
    assert.equal(p.element('battle-dialog').open, false); assert.equal(intervals(p).length, 0);
    const closed = {draws: p.events.canvas.length, requests: p.events.images.length,
      status: p.element('battle-status').textContent};
    for (const {record, onload, onerror} of callbacks) {
      record.image.naturalWidth = 960; record.image.naturalHeight = 640;
      onload?.(); onerror?.();
    }
    for (const timer of oldTimeouts) timer.callback();
    await p.settle();
    assert.equal(p.events.canvas.length, closed.draws, 'Closing prevents late frames from drawing');
    assert.equal(p.events.images.length, closed.requests, 'Closing prevents late loads from scheduling prefetch');
    assert.equal(p.element('battle-status').textContent, closed.status);
    const reopened = await p.startClick(p.element('fight-button'));
    assert.equal(p.element('battle-dialog').open, true);
    for (const {onload, onerror} of callbacks) {onload?.(); onerror?.();}
    for (const timer of oldTimeouts) timer.callback();
    await p.settle(); noFinalReport(p);
    await loadAllPending(p); await reopened.done; await p.settle();
    assert.equal(currentFrame(p), 0); assert.equal(intervals(p).length, 1);
    assert.equal(p.element('battle-loading').hidden, true);
    await opening.done; p.unchanged();
  },
  async renderStatus() {
    const responses = [
      {ok: true, status: 'rendering', frames: 2, total: 9, updated_at: 1, queued: false, error: null},
      {ok: true, status: 'rendering', frames: 5, total: 9, updated_at: 2, queued: false, error: null},
      {ok: true, status: 'ready', frames: 9, total: 9, updated_at: 3, queued: false, error: null},
    ];
    const {p, opening} = await openManual({}, {
      renderStatusResponder: (request, call) => {
        assert.match(request.pathname, new RegExp(`/demo/render-status/${p.fixture.sid}/r31$`));
        return responses[call - 1];
      },
    });
    imagesFor(p, 0)[0].fail(); await p.settle();
    assert.equal(p.events.renderStatusFetches.length, 1);
    assert.equal(liveImages(p).length, 0, 'A rendering round does not keep missing-image requests active');
    assert.equal(imagesFor(p, 0).length, 1, 'Missing images are not retried while rendering');
    assert.match(p.element('battle-loading-copy').textContent, /正在渲染战斗画面 2 \/ 9 帧/);
    assert.equal(p.element('battle-render-progress').hidden, false);
    assert.equal(p.element('battle-render-progress').value, '2');
    const slider = p.element('battle-seek');
    slider.value = '6';
    await p.dispatch('battle-seek', 'pointerdown');
    await p.dispatch('battle-seek', 'input');
    assert.equal(p.element('battle-seek').value, '6', 'A seek target survives while rendering is blocked');
    await p.dispatch('battle-seek', 'change');
    await p.expireTimeouts(1000);
    assert.equal(p.events.renderStatusFetches.length, 2);
    assert.equal(imagesFor(p, 0).length, 1);
    assert.match(p.element('battle-loading-copy').textContent, /正在渲染战斗画面 5 \/ 9 帧/);
    assert.equal(p.element('battle-render-progress').value, '5');
    await p.expireTimeouts(2000);
    assert.equal(p.events.renderStatusFetches.length, 3);
    await loadAllPending(p); await opening.done; await p.settle();
    assert.equal(currentFrame(p), 6, 'Ready recovery loads the frame requested during rendering');
    assert.equal(visibleTime(p), .3);
    assert.equal(p.element('battle-render-progress').hidden, true);
    assert.equal(intervals(p).length, 1, 'The seek resume intent is restored after ready');
    await p.tick(); assert.equal(currentFrame(p), 7); noFinalReport(p);
    p.unchanged();
  },
  async renderRetryDeadline() {
    let clock = 0;
    const rendering = () => ({ok: true, status: 'rendering', frames: 2, total: 9,
      updated_at: 1, queued: false, error: null});
    const {p, opening} = await openManual({}, {
      clock: () => clock,
      renderStatusResponder: (request, call) => call === 3
        ? {ok: true, status: 'ready', frames: 9, total: 9, updated_at: 2, queued: false, error: null}
        : rendering(),
    });
    imagesFor(p, 0)[0].fail(); await p.settle();
    assert.equal(p.events.renderStatusFetches.length, 1);
    clock = 180000;
    await p.expireTimeouts(1000);
    assert.equal(p.events.renderStatusFetches.length, 1, 'An expired no-progress window does not poll again automatically');
    assert.equal(p.element('battle-retry').hidden, false);
    assert.match(p.element('battle-loading-copy').textContent, /长时间没有进展/);
    await p.startClick(p.element('battle-retry')); await p.settle();
    assert.equal(p.events.renderStatusFetches.length, 2, 'Manual retry checks the stalled renderer immediately');
    clock = 359999;
    await p.expireTimeouts(1000);
    assert.equal(p.events.renderStatusFetches.length, 3, 'Manual retry grants a fresh no-progress window');
    await loadAllPending(p); await opening.done; await p.settle();
    assert.equal(currentFrame(p), 0);
    assert.equal(p.element('battle-loading').hidden, true);
    assert.equal(p.events.renderStatusFetches.length, 3);
    p.unchanged();
  },
  async renderDead() {
    const {p, opening} = await openManual({}, {
      renderStatusResponder: () => ({ok: true, status: 'dead', frames: null, total: null,
        updated_at: null, queued: false, error: 'worker exited'}),
    });
    imagesFor(p, 0)[0].fail(); await p.settle(); await opening.done;
    assert.equal(p.events.renderStatusFetches.length, 1);
    assert.equal(imagesFor(p, 0).length, 1, 'Dead renders do not receive another image request');
    assert.equal(liveImages(p).length, 0);
    assert.equal(p.element('battle-retry').hidden, true);
    assert.equal(p.element('battle-verdict').hidden, false);
    assert.equal(p.element('battle-next').disabled, false);
    assert.deepEqual(ranking(p, 'battle'), [0, 1, 3, 2]);
    assert.equal(intervals(p).length, 0);
    p.unchanged();
  },
  async statusTimeout() {
    const rejectOnAbort = init => new Promise((_, reject) => init.signal?.addEventListener('abort', () => {
      const error = new Error('status timeout');
      error.name = 'TimeoutError';
      reject(error);
    }));
    const {p, opening} = await openManual({}, {renderStatusResponder: (query, call, init) => rejectOnAbort(init)});
    imagesFor(p, 0)[0].fail(); await p.settle();
    await p.expireTimeouts(5000); await p.expireTimeouts(1000);
    await p.expireTimeouts(5000); await p.expireTimeouts(1000);
    await p.expireTimeouts(5000); await opening.done;
    assert.equal(p.events.renderStatusFetches.length, 3);
    assert.equal(liveImages(p).length, 0);
    assert.equal(p.element('battle-retry').hidden, false);
    assert.match(p.element('battle-loading-copy').textContent, /无法获取渲染进度/);
    assert.equal(p.element('battle-verdict').hidden, false);
    assert.equal(p.element('battle-next').disabled, false);
    assert.equal(p.timers.size, 1, 'Only the bounded heal timer remains; status polling stops');
    p.unchanged();
  },
  async mutationTimeout() {
    const original = fixture({phase: 'prep'});
    const p = await page(original, {
      pendingMutation: true,
      mutationResponder: query => ({ok: true, sid: original.sid, state: original}),
    });
    await p.settle();
    const refresh = p.element('refresh-button');
    const pending = refresh.onclick({target: refresh});
    await p.settle();
    await p.expireTimeouts(12000);
    await pending; await p.settle();
    assert.equal(p.events.fetches.filter(url => url.includes('cmd=refresh')).length, 1,
      'A timed-out mutation is never automatically resubmitted');
    assert.match(p.element('save-status').textContent, /连接超时|继续存档/);
    await p.click(p.element('resume-button'));
    assert.equal(p.events.fetches.filter(url => url.includes('cmd=refresh')).length, 1);
    assert.equal(p.events.fetches.filter(url => url.includes('cmd=resume')).length, 2);
    p.unchanged();
  },
  async restored() {
    const state = fixture({n: 0, restored: true});
    const p = await page(state, imageOptions);
    await p.click(p.element('fight-button'));
    assert.equal(p.events.images.length, 0); assert.equal(intervals(p).length, 0);
    assert.equal(p.element('battle-verdict').hidden, false);
    assert.deepEqual(ranking(p, 'battle'), [0, 1, 3, 2]);
    assert.match(p.element('battle-status').textContent, /存档|恢复|历史/);
    assert.equal(p.element('battle-next').disabled, false);
    assert.equal(p.element('battle-replay').disabled, true);
    assert.equal(p.element('battle-seek').disabled, true);
    assert.equal(p.events.fetches.length, 1); p.unchanged();
  },
};
(async () => {assert.ok(cases[scenario], `Unknown scenario ${scenario}`); await cases[scenario]();
  console.log(`OK playback ${scenario}`);})()
  .catch(error => {console.error(error); process.exitCode = 1;});
