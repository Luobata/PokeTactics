/* Phase-aware background music (docs/64). Original procedural chiptune, WebAudio only.
 *
 * Tracks follow the game: calm / mid / tense preparation, battle (normal,
 * wild round, final stage), results, plus victory / defeat jingles. Switching
 * crossfades. Music starts on the first user gesture (browser autoplay rules),
 * pauses while the tab is hidden, and is toggled with #music-button
 * (localStorage "poketactics.music", default on, volume "poketactics.music.volume").
 */
(function () {
  "use strict";
  const KEY = "poketactics.music", VOL_KEY = "poketactics.music.volume";
  const MAJOR = [0, 2, 4, 5, 7, 9, 11], MINOR = [0, 2, 3, 5, 7, 8, 10], DORIAN = [0, 2, 3, 5, 7, 9, 10];
  // Scale-degree sequences (0-based, may exceed 6 for the next octave); null = rest.
  const TRACKS = {
    prep_calm: {bpm: 88, root: 60, scale: MAJOR, prog: [0, 5, 3, 4], lead: "triangle", leadVol: .05,
      motif: [4, null, 2, null, 4, 5, 4, null, 2, null, 0, null, 1, 2, null, null],
      bass: "x...x...x...x...", bassWave: "sine", hat: "..x...x...x...x.", kick: "", snare: "", pad: true},
    prep_mid: {bpm: 100, root: 62, scale: MAJOR, prog: [0, 4, 5, 3], lead: "square", leadVol: .035,
      motif: [0, 2, 4, null, 4, 5, 4, 2, 1, null, 2, 4, 2, null, 0, null],
      bass: "x..x..x.x..x..x.", bassWave: "triangle", hat: "x.x.x.x.x.x.x.x.", kick: "x.......x.......", snare: "", pad: true},
    prep_tense: {bpm: 112, root: 57, scale: MINOR, prog: [0, 5, 2, 6], lead: "square", leadVol: .035,
      motif: [4, null, 4, 3, 2, null, 0, null, 4, null, 5, 4, 2, null, 1, null],
      bass: "x.x.x.x.x.x.x.x.", bassWave: "sawtooth", hat: "xxxxxxxxxxxxxxxx", kick: "x...x...x...x...", snare: "....x.......x...", pad: true},
    battle: {bpm: 142, root: 64, scale: MINOR, prog: [0, 6, 5, 6], lead: "square", leadVol: .04, arp: true,
      motif: [0, 2, 4, 7, 4, 2, 0, 2, 4, 7, 9, 7, 4, 2, 4, 2],
      bass: "x.xx.x.xx.xx.x.x", bassWave: "sawtooth", hat: "x.x.x.x.x.x.x.x.", kick: "x...x...x...x.x.", snare: "....x.......x..."},
    battle_wild: {bpm: 132, root: 62, scale: DORIAN, prog: [0, 3, 0, 6], lead: "sawtooth", leadVol: .03, arp: true,
      motif: [0, 4, 7, 4, 3, 4, 0, null, 0, 4, 7, 8, 7, 4, 3, null],
      bass: "x..xx..xx..xx.x.", bassWave: "square", hat: "x.xxx.xxx.xxx.xx", kick: "x..x..x.x..x..x.", snare: "....x.......x..x"},
    battle_final: {bpm: 156, root: 66, scale: MINOR, prog: [0, 5, 6, 4], lead: "square", leadVol: .042, arp: true,
      motif: [7, 4, 2, 0, 2, 4, 7, 9, 7, 4, 2, 4, 5, 4, 2, 1],
      bass: "xxxxxxxxxxxxxxxx", bassWave: "sawtooth", hat: "xxxxxxxxxxxxxxxx", kick: "x.x.x.x.x.x.x.x.", snare: "....x.......x.x."},
    results: {bpm: 76, root: 65, scale: MAJOR, prog: [0, 3, 5, 4], lead: "triangle", leadVol: .05,
      motif: [4, null, null, 2, null, null, 0, null, 1, null, 2, null, 4, null, null, null],
      bass: "x.......x.......", bassWave: "sine", hat: "", kick: "", snare: "", pad: true},
  };
  const JINGLES = {
    victory: {bpm: 168, root: 64, scale: MAJOR, notes: [[0, 1], [2, 1], [4, 1], [7, 3], [4, 1], [7, 4]], wave: "square"},
    defeat: {bpm: 96, root: 57, scale: MINOR, notes: [[4, 2], [2, 2], [1, 2], [0, 6]], wave: "triangle"},
    levelup: {bpm: 200, root: 72, scale: MAJOR, notes: [[0, 1], [2, 1], [4, 1], [7, 2]], wave: "square"},
  };

  let ctx = null, master = null, noise = null;
  let enabled = readEnabled();
  let volume = readVolume();
  let current = null;           // {name, bus, step, nextTime}
  let fading = [];
  let timer = null, info = {};

  function readEnabled() { try { return localStorage.getItem(KEY) !== "off"; } catch (_) { return true; } }
  function readVolume() { try { const v = Number(localStorage.getItem(VOL_KEY)); return v > 0 && v <= 1 ? v : .6; } catch (_) { return .6; } }

  function ensure() {
    if (ctx) return ctx.state !== "closed";
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    ctx = new AC();
    master = ctx.createGain();
    master.gain.value = .5 * volume;
    const comp = ctx.createDynamicsCompressor();
    master.connect(comp).connect(ctx.destination);
    noise = ctx.createBuffer(1, Math.floor(ctx.sampleRate * .25), ctx.sampleRate);
    const data = noise.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
    return true;
  }

  const freq = (midi) => 440 * Math.pow(2, (midi - 69) / 12);
  function pitch(track, degree, octave = 0) {
    const n = track.scale.length, oct = Math.floor(degree / n), idx = ((degree % n) + n) % n;
    return track.root + track.scale[idx] + 12 * (oct + octave);
  }

  function tone(bus, time, midi, dur, wave, vol, {attack = .008, release = .06, detune = 0} = {}) {
    const osc = ctx.createOscillator(), gain = ctx.createGain();
    osc.type = wave;
    osc.frequency.setValueAtTime(freq(midi), time);
    if (detune) osc.detune.setValueAtTime(detune, time);
    gain.gain.setValueAtTime(0, time);
    gain.gain.linearRampToValueAtTime(vol, time + attack);
    gain.gain.setValueAtTime(vol, time + Math.max(attack, dur - release));
    gain.gain.linearRampToValueAtTime(0, time + dur);
    osc.connect(gain).connect(bus);
    osc.start(time);
    osc.stop(time + dur + .02);
  }
  function drum(bus, time, kind) {
    if (kind === "kick") {
      const osc = ctx.createOscillator(), gain = ctx.createGain();
      osc.frequency.setValueAtTime(140, time);
      osc.frequency.exponentialRampToValueAtTime(42, time + .12);
      gain.gain.setValueAtTime(.32, time);
      gain.gain.exponentialRampToValueAtTime(.001, time + .18);
      osc.connect(gain).connect(bus);
      osc.start(time);
      osc.stop(time + .2);
      return;
    }
    const src = ctx.createBufferSource(), filter = ctx.createBiquadFilter(), gain = ctx.createGain();
    src.buffer = noise;
    filter.type = kind === "hat" ? "highpass" : "bandpass";
    filter.frequency.value = kind === "hat" ? 7000 : 1800;
    const len = kind === "hat" ? .04 : .14;
    gain.gain.setValueAtTime(kind === "hat" ? .05 : .16, time);
    gain.gain.exponentialRampToValueAtTime(.001, time + len);
    src.connect(filter).connect(gain).connect(bus);
    src.start(time);
    src.stop(time + len + .02);
  }

  function playStep(track, bus, step, time) {
    const sixteenth = 60 / track.bpm / 4;
    const bar = Math.floor(step / 16) % track.prog.length, s = step % 16;
    const chord = track.prog[bar];
    const variation = Math.floor(step / 16 / track.prog.length) % 2;  // second pass varies the motif
    let degree = track.motif[s];
    if (degree != null) {
      if (variation && s % 4 === 3) degree += 1;
      tone(bus, time, pitch(track, chord + degree, 1), sixteenth * (track.arp ? .9 : 1.8), track.lead, track.leadVol);
    }
    if (track.bass[s] === "x") tone(bus, time, pitch(track, chord, -1), sixteenth * (track.bass === "x...x...x...x..." ? 3.5 : .9), track.bassWave, .07);
    if (track.pad && s === 0) {
      for (const third of [0, 2, 4]) tone(bus, time, pitch(track, chord + third), sixteenth * 15.5, "triangle", .018, {attack: .25, release: .4, detune: third * 3});
    }
    if (track.kick[s] === "x") drum(bus, time, "kick");
    if (track.snare[s] === "x") drum(bus, time, "snare");
    if (track.hat[s] === "x") drum(bus, time, "hat");
  }

  function startTrack(name) {
    if (current?.name === name) return;
    const now = ctx.currentTime;
    if (current) {
      current.bus.gain.cancelScheduledValues(now);
      current.bus.gain.setValueAtTime(current.bus.gain.value, now);
      current.bus.gain.linearRampToValueAtTime(0, now + .8);
      const old = current.bus;
      fading.push(old);
      setTimeout(() => { old.disconnect(); fading = fading.filter((b) => b !== old); }, 1200);
    }
    if (!name) { current = null; return; }
    const bus = ctx.createGain();
    bus.gain.setValueAtTime(0, now);
    bus.gain.linearRampToValueAtTime(1, now + .8);
    bus.connect(master);
    current = {name, bus, step: 0, nextTime: now + .05};
  }

  function desired() {
    const battle = document.getElementById("battle-dialog")?.open;
    const results = document.getElementById("result-dialog")?.open || info.phase === "over";
    if (results) return "results";
    if (battle) return info.pve ? "battle_wild" : info.round >= 20 ? "battle_final" : "battle";
    if (info.round >= 20 || (info.hp != null && info.hp <= 30)) return "prep_tense";
    if (info.round >= 10) return "prep_mid";
    return "prep_calm";
  }

  function tick() {
    if (!ctx || !enabled || document.hidden) return;
    const name = desired();
    if (current?.name !== name) startTrack(name);
    if (!current) return;
    const track = TRACKS[current.name];
    const sixteenth = 60 / track.bpm / 4;
    while (current.nextTime < ctx.currentTime + .15) {
      playStep(track, current.bus, current.step, current.nextTime);
      current.step++;
      current.nextTime += sixteenth;
    }
  }

  function start() {
    if (!enabled || !ensure()) return;
    ctx.resume().catch(() => {});
    if (!timer) timer = setInterval(tick, 30);
    tick();
  }
  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
    if (ctx) startTrack(null);
  }

  function jingle(name) {
    if (!enabled || !ctx || ctx.state !== "running") return;
    const spec = JINGLES[name];
    if (!spec) return;
    if (current) {  // duck the loop under the jingle
      const now = ctx.currentTime;
      current.bus.gain.cancelScheduledValues(now);
      current.bus.gain.setValueAtTime(current.bus.gain.value, now);
      current.bus.gain.linearRampToValueAtTime(.15, now + .1);
      current.bus.gain.linearRampToValueAtTime(1, now + 2.4);
    }
    const beat = 60 / spec.bpm / 2;
    let time = ctx.currentTime + .05;
    for (const [degree, len] of spec.notes) {
      tone(master, time, pitch(spec, degree, 1), beat * len * .95, spec.wave, .07);
      tone(master, time, pitch(spec, degree, 0), beat * len * .95, "triangle", .04);
      time += beat * len;
    }
  }

  function setEnabled(value) {
    enabled = Boolean(value);
    try { localStorage.setItem(KEY, enabled ? "on" : "off"); } catch (_) { /* private mode */ }
    if (enabled) start(); else stop();
    syncButton();
  }
  function setVolume(value) {
    volume = Math.max(.05, Math.min(1, Number(value) || .6));
    try { localStorage.setItem(VOL_KEY, String(volume)); } catch (_) { /* private mode */ }
    if (master) master.gain.setTargetAtTime(.5 * volume, ctx.currentTime, .05);
  }
  function syncButton() {
    const button = document.getElementById("music-button");
    if (!button) return;
    button.setAttribute("aria-pressed", String(enabled));
    button.classList.toggle("muted", !enabled);
    button.title = enabled ? "背景音乐：开（点击关闭）" : "背景音乐：关（点击开启）";
  }

  function update(next) {
    info = {...info, ...next};
  }

  // Creating an AudioContext costs ~100ms; never do it inside the click that the
  // player is waiting on. Sticky user activation still allows playback afterwards.
  let kicked = false;
  const kick = () => {
    if (!enabled || timer || kicked) return;
    kicked = true;
    const later = window.requestIdleCallback || ((fn) => setTimeout(fn, 250));
    later(() => { kicked = false; start(); }, {timeout: 800});
  };
  document.addEventListener("pointerdown", kick, {passive: true});
  document.addEventListener("keydown", kick);
  document.addEventListener("visibilitychange", () => {
    if (!ctx) return;
    if (document.hidden) ctx.suspend().catch(() => {});
    else if (enabled) ctx.resume().catch(() => {});
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest?.("#music-button")) return;
    // Enabled but not playing yet (first gesture): this click means "play", not "mute".
    if (enabled && !timer) start();
    else setEnabled(!enabled);
  });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", syncButton);
  else syncButton();

  // Called by play_mobile.js inside the first tap (docs/72): iOS only lets a context
  // start from a gesture, and a one-sample silent buffer wakes its output route.
  function unlock() {
    if (!enabled || !ensure()) return false;
    try {
      const source = ctx.createBufferSource();
      source.buffer = ctx.createBuffer(1, 1, ctx.sampleRate);
      source.connect(ctx.destination);
      source.start();
    } catch (_) { /* best effort */ }
    ctx.resume().catch(() => {});
    if (!timer) start();
    return true;
  }

  window.PlayMusic = {update, jingle, setEnabled, setVolume, unlock, enabled: () => enabled, current: () => current?.name || null,
                      desired, tracks: Object.keys(TRACKS), state: () => ctx?.state || "none"};
})();
