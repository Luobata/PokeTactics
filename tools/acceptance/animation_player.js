/* Shared by current-arena authoring and classic device previews. */
(() => {
  'use strict';
  const modes = ['arena', 'classic'];
  const abortError = () => Object.assign(new Error('预览已取消。'), {name: 'AbortError'});
  const previewMode = value => modes.includes(value) ? value : 'arena';
  const presetMode = preset => preset?.mode == null ? 'classic' : modes.includes(preset.mode) ? preset.mode : null;
  const metadata = (result, expectedMode) => {
    const value = {...result?.meta, ...result};
    const mode = value.mode == null ? previewMode(expectedMode) : value.mode;
    if (!modes.includes(mode) || expectedMode && mode !== expectedMode) throw new Error('预览模式与当前选择不一致。');
    const width = value.width ?? (mode === 'arena' ? 960 : 240);
    const height = value.height ?? (mode === 'arena' ? 640 : 320);
    if ((mode === 'arena' && (width !== 960 || height !== 640)) || (mode === 'classic' && (width !== 240 || height !== 320))) throw new Error('预览画布尺寸与模式不一致。');
    if (value.presentation != null && typeof value.presentation !== 'string') throw new Error('预览表现版本无效。');
    return {...value, mode, width, height, presentation: value.presentation || (mode === 'classic' ? 'device-v1' : 'web-arena-v2-articulated')};
  };
  function normalizePlayback(result, {mode, baseURL} = {}) {
    const value = metadata(result, mode);
    const origin = new URL(baseURL || (typeof location !== 'undefined' ? location.href : 'http://localhost/'));
    const frames = value.frames, baseline = value.base_frames || frames;
    if (!Array.isArray(frames) || !frames.length || frames.length > 12000 || !Array.isArray(baseline) || baseline.length !== frames.length || value.n != null && value.n !== frames.length) throw new Error('默认与调参帧数量无效或不一致。');
    if (!Number.isFinite(value.dt) || value.dt <= 0 || value.dt > 1 || value.clip_start != null && !Number.isFinite(value.clip_start)) throw new Error('预览帧的时间信息无效。');
    const resource = path => {
      if (typeof path !== 'string' || !path) throw new Error('预览帧地址无效。');
      const url = new URL(path, origin);
      if (url.origin !== origin.origin || !['http:', 'https:'].includes(url.protocol)) throw new Error('预览只能加载本站帧资源。');
      if (value.render_revision) url.searchParams.set('v', value.render_revision);
      return url.href;
    };
    return {...value, n: frames.length, clip_start: value.clip_start || 0, frames: frames.map(resource), base_frames: baseline.map(resource)};
  }
  async function requestJSON(url, {method = 'GET', body, signal, timeout = 120000} = {}) {
    const controller = new AbortController();
    const stop = () => controller.abort();
    if (signal?.aborted) controller.abort();
    else signal?.addEventListener('abort', stop, {once: true});
    const timer = setTimeout(stop, timeout);
    try {
      const response = await fetch(url, {method, cache: 'no-store', credentials: 'same-origin', signal: controller.signal,
        headers: body == null ? {Accept: 'application/json'} : {'Content-Type': 'application/json', 'X-PokeTactics-Preview': '1'},
        ...(body == null ? {} : {body: typeof body === 'string' ? body : JSON.stringify(body)})});
      let result;
      try { result = await response.json(); } catch { throw new Error('服务器未返回有效 JSON。'); }
      if (!response.ok || !result || result.ok !== true) throw new Error(typeof result?.error === 'string' ? result.error : `请求失败（HTTP ${response.status}）。`);
      return result;
    } catch (error) {
      if (error.name === 'AbortError' && !signal?.aborted) throw new Error('预览等待超时，请重试。');
      throw error;
    } finally { clearTimeout(timer); signal?.removeEventListener('abort', stop); }
  }
  class PreviewPlayer {
    constructor({canvases, maxCache, onFrame = () => {}, onState = () => {}, baseURL} = {}) {
      if (!Array.isArray(canvases) || ![1, 2].includes(canvases.length)) throw new Error('预览需要一个或两个画布。');
      this.canvases = canvases; this.onFrame = onFrame; this.onState = onState; this.baseURL = baseURL;
      this.maxCache = Math.round(Math.max(4, Math.min(80, Number(maxCache) || (typeof window !== 'undefined' && window.matchMedia?.('(max-width: 720px)')?.matches ? 12 : 24))));
      this.generation = 0; this.cache = new Map(); this.pending = new Map(); this.failed = new Set(); this.loaded = new Set();
      this.frame = 0; this.requested = null; this.wanted = false; this.playing = false; this.raf = 0; this.speed = 1; this.result = null;
    }
    getState() { return {status: this.status || 'idle', wanted: this.wanted, frame: this.frame, requested: this.requested, n: this.result?.n || 0, cached: this.cache.size, loaded: this.loaded.size, maxCache: this.maxCache, playing: this.playing, buffering: ['loading', 'buffering'].includes(this.status) || this.requested != null, error: this.error || null}; }
    emit(status, error = null) { this.status = status; this.error = error; this.onState({...this.getState(), status}); }
    pause() {
      this.wanted = false; this.playing = false; cancelAnimationFrame(this.raf); this.raf = 0; this.lastTick = null;
      if (this.requestedReason === 'play') { this.requested = null; this.requestedReason = null; }
      if (this.result) this.emit('paused');
    }
    cancel() {
      this.generation++; this.pause();
      for (const request of this.pending.values()) request.cancel();
      this.pending.clear(); this.cache.clear(); this.failed.clear(); this.loaded.clear();
      this.rejectReady?.(abortError()); this.resolveReady = this.rejectReady = null;
      this.result = null; this.requested = null; this.requestedReason = null; this.retryIndex = null; this.emit('cancelled');
    }
    load(result, {autoplay = false, startFrame = 0, mode} = {}) {
      const validated = normalizePlayback(result, {mode, baseURL: this.baseURL});
      this.cancel(); this.result = validated; this.frame = 0; this.cursor = 0; this.lastTick = null;
      this.requested = Math.max(0, Math.min(validated.n - 1, Math.round(Number(startFrame) || 0))); this.requestedReason = 'seek'; this.wanted = autoplay;
      const ready = new Promise((resolve, reject) => { this.resolveReady = resolve; this.rejectReady = reject; });
      this.emit('loading'); this.pump(); return ready;
    }
    paint(index) {
      const images = this.cache.get(index);
      if (!images || !this.result) return false;
      const {width, height} = this.result;
      this.canvases.forEach((canvas, track) => {
        if (canvas.width !== width) canvas.width = width;
        if (canvas.height !== height) canvas.height = height;
        canvas.dataset.mode = this.result.mode;
        const context = canvas.getContext('2d');
        context.imageSmoothingEnabled = this.result.presentation.startsWith('web-arena-');
        context.clearRect(0, 0, width, height); context.drawImage(images[track], 0, 0, width, height);
      });
      this.frame = index; this.cursor = index;
      if (this.requested === index) { this.requested = null; this.requestedReason = null; }
      this.error = null;
      this.onFrame({frame: index, time: this.result.clip_start + index * this.result.dt, n: this.result.n, result: this.result});
      this.resolveReady?.(this.result); this.resolveReady = this.rejectReady = null;
      if (index === this.result.n - 1) { this.pause(); this.emit('complete'); }
      else this.emit(this.playing ? 'playing' : 'ready');
      return true;
    }
    seek(index, {resume = false} = {}) {
      if (!this.result) return;
      this.pause(); this.wanted = resume;
      const target = Math.max(0, Math.min(this.result.n - 1, Math.round(Number(index) || 0)));
      this.requested = target; this.requestedReason = 'seek';
      if (!this.paint(target)) this.emit(this.failed.has(target) ? 'error' : 'buffering', this.failed.has(target) ? '这一帧读取失败，请重试。' : null);
      this.pump(); this.start();
    }
    step(delta) { this.seek(this.frame + delta); }
    setSpeed(speed) { this.speed = Math.max(.25, Math.min(4, Number(speed) || 1)); this.lastTick = null; }
    play() {
      if (!this.result) return;
      if (this.frame === this.result.n - 1 && this.requested == null) return this.seek(0, {resume: true});
      this.wanted = true; this.start(); this.pump();
    }
    retry() {
      if (!this.result) return;
      const target = this.retryIndex ?? this.requested ?? this.frame, resume = this.wanted;
      this.failed.delete(target); this.retryIndex = null; this.error = null;
      this.seek(target, {resume});
    }
    start() {
      if (!this.result || !this.wanted || this.playing || this.requested != null || (typeof document !== 'undefined' && document.hidden)) return;
      const next = Math.min(this.result.n - 1, this.frame + 1);
      if (!this.cache.has(next)) {
        if (this.failed.has(next)) { this.retryIndex = next; this.emit('error', '接下来的画面读取失败，请重试。'); }
        else this.emit('buffering');
        return;
      }
      this.playing = true; this.cursor = this.frame; this.lastTick = null; this.emit('playing');
      const generation = this.generation;
      const tick = now => {
        if (generation !== this.generation || !this.playing || !this.result) return;
        if (this.lastTick != null) {
          const position = Math.min(this.result.n - 1, this.cursor + (now - this.lastTick) / 1000 * this.speed / this.result.dt);
          const target = Math.floor(position + 1e-8);
          if (target !== this.frame) {
            if (!this.paint(target)) {
              this.playing = false; this.raf = 0; this.lastTick = null;
              this.requested = target; this.requestedReason = 'play';
              if (this.failed.has(target)) { this.retryIndex = target; this.emit('error', '这一帧读取失败，请重试。'); }
              else this.emit('buffering');
              this.pump(); return;
            }
            this.pump();
          }
          this.cursor = position;
        }
        this.lastTick = now;
        if (this.playing) this.raf = requestAnimationFrame(tick);
      };
      this.raf = requestAnimationFrame(tick);
    }
    trim() {
      if (this.cache.size <= this.maxCache) return;
      const center = this.requested ?? this.frame, start = Math.max(0, center - 2), end = center + this.maxCache - 3;
      for (const index of [...this.cache.keys()]) {
        if (this.cache.size <= this.maxCache) break;
        if ((index < start || index > end) && index !== this.frame && index !== this.requested) this.cache.delete(index);
      }
      const far = [...this.cache.keys()].sort((a, b) => Math.abs(b - center) - Math.abs(a - center));
      for (const index of far) {
        if (this.cache.size <= this.maxCache) break;
        if (index !== this.frame && index !== this.requested) this.cache.delete(index);
      }
    }
    pump() {
      if (!this.result) return;
      this.trim();
      const center = this.requested ?? this.frame, end = Math.min(this.result.n - 1, center + this.maxCache - 3);
      const candidates = [center];
      for (let i = center + 1; i <= end; i++) candidates.push(i);
      for (let i = center - 1; i >= Math.max(0, center - 2); i--) candidates.push(i);
      // A failed distant seek must retain the painted frame without evicting and
      // refetching the same prefetch frame forever. Reserve its cache slot.
      if (this.cache.has(this.frame) && !candidates.includes(this.frame)) candidates.push(this.frame);
      while (candidates.length > this.maxCache) {
        const removable = candidates.filter(i => i !== center && i !== this.frame).sort((a,b) => Math.abs(b-center)-Math.abs(a-center))[0];
        candidates.splice(candidates.indexOf(removable),1);
      }
      const wanted = new Set(candidates);
      for (const [index, request] of [...this.pending]) if (!wanted.has(index)) request.cancel();
      while (this.pending.size < 4) {
        const index = candidates.find(i => !this.cache.has(i) && !this.pending.has(i) && !this.failed.has(i));
        if (index == null) break;
        this.fetchPair(index);
      }
    }
    fetchPair(index) {
      const generation = this.generation;
      const urls = this.canvases.length === 1 ? [this.result.frames[index]] : [this.result.base_frames[index], this.result.frames[index]];
      const unique = [...new Set(urls)], images = new Map(), timers = [], instances = [];
      let done = false;
      const request = {cancel: () => {
        if (done) return; done = true;
        timers.forEach(clearTimeout); instances.forEach(image => { image.onload = image.onerror = null; image.removeAttribute?.('src'); });
        if (this.pending.get(index) === request) this.pending.delete(index);
      }};
      const finish = error => {
        if (done) return;
        if (!error && images.size !== unique.length) return;
        done = true; timers.forEach(clearTimeout); instances.forEach(image => image.onload = image.onerror = null);
        if (generation !== this.generation || this.pending.get(index) !== request || !this.result) return;
        this.pending.delete(index);
        if (error) {
          this.failed.add(index);
          if (this.requested === index) { this.retryIndex = index; this.emit('error', error.message); this.rejectReady?.(error); this.resolveReady = this.rejectReady = null; }
        } else {
          this.cache.set(index, urls.map(url => images.get(url))); this.loaded.add(index);
          if (this.requested === index) this.paint(index);
        }
        this.trim(); this.start(); this.pump();
      };
      this.pending.set(index, request);
      unique.forEach(url => {
        const image = new Image(); instances.push(image);
        timers.push(setTimeout(() => finish(new Error('读取预览帧超时，请重试。')), 15000));
        image.onload = () => {
          if (generation !== this.generation || done || !this.result) return;
          if (image.naturalWidth !== this.result.width || image.naturalHeight !== this.result.height) return finish(new Error('服务器帧尺寸与所选模式不一致。'));
          images.set(url, image); finish();
        };
        image.onerror = () => finish(new Error('预览帧读取失败，请重试。'));
        image.src = url;
      });
    }
  }
  const api = {PreviewPlayer, normalizePlayback, metadata, previewMode, presetMode, requestJSON};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.PokeAnimation = api;
})();
