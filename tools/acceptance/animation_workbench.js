/* Battle animation workbench (docs/58): A/B preview, multi-track timeline,
 * keyframe/timing/VFX editing and the monotony dashboard. Uses the same
 * battle_renderer.js as /play; edits stay in this page until saved. */
(() => {
  "use strict";
  const PB = window.PokeBattle;
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
  const FRAME = 1 / 60;
  const EASES = Object.keys(PB.EASE);
  const SLOT_ZH = { idle: "待机", walk: "移动", attack_melee: "近战攻击", attack_ranged: "远程攻击", cast: "技能", hit: "受击", ko: "退场", victory: "胜利" };
  const PHASE_ZH = { loop: "循环", anticipation: "蓄力", dash: "冲刺", contact: "命中", release: "出手", recover: "收招", react: "受击", fall: "倒下" };
  const TIMING_ZH = { anticipation: "普攻蓄力 s", recover: "普攻收招 s", cast_anticipation: "技能蓄力 s", cast_recover: "技能收招 s", weight: "原型体重", dash_speed: "冲刺速度 px/s", offset_range: "单位偏移幅度 s", idle_period: "待机周期 s" };
  const TIMING_LIMITS = { anticipation: [0.04, 1.2, 0.01], recover: [0.04, 1.2, 0.01], cast_anticipation: [0.08, 1.6, 0.01], cast_recover: [0.06, 1.6, 0.01], weight: [0, 1, 0.01], dash_speed: [100, 4000, 10], offset_range: [0, 0.2, 0.005], idle_period: [0.4, 6, 0.05] };
  const EVENT_COLORS = { attack: "#9a8f6a", cast: "#7b5cc8", die: "#b8432f", move: "#5d8fb3", status: "#c2732f", skill_effect: "#4e8f6a", combo_effect: "#d0a23c", field_effect: "#6a7f3a", effect: "#c03c6a" };
  const CAM_COLORS = { ult: "#7b5cc8", ko: "#b8432f", chain: "#d0a23c", focus: "#5d8fb3" };
  const ROLE_ZH = { attack: "攻击", defense: "防守", support: "辅助" };

  const state = {
    source: "preview", packsA: null, packsB: null, mergedA: null, mergedB: null, dirty: new Set(),
    script: null, rendA: null, rendB: null, p: 0, playing: false, speed: 1, raf: 0, last: 0,
    sel: { unit: null, action: null }, clipId: null, phase: null, keyRow: 0, editor: "keys",
    timelineRows: [], characters: {},
    partsClipId: null, partsRow: 0, loop: null, gallery: [], galleryShown: [], gallerySkill: null,
  };
  const PART_LIMITS = { lean: [-24, 24], head_x: [-16, 16], head_y: [-16, 16], belly: [-30, 40], wobble: [0, 12] };
  const PART_COLS = ["lean", "head_x", "head_y", "belly", "wobble"];
  const PART_COLORS = ["#3d7fb0", "#a04c3d", "#c2732f", "#6a9a5c", "#7b5cc8"];
  const CATEGORY_ZH = { burst: "爆发", technique: "技能机", area: "范围", chain: "连锁", combo: "连击", drain: "汲取", lifesteal: "伤害转治疗",
    energy: "回能", heal: "治疗", rescue: "救援", shield: "护盾", guard: "守护", cleanse: "净化", clear: "清场", displacement: "位移",
    root: "定身", pursuit: "追击", assassin: "刺杀", taunt: "嘲讽", terrain: "地形", poison: "中毒", vulnerability: "易伤",
    execute: "处决", pierce: "贯穿", retaliation: "反击", control: "控制" };
  const SUB_ZH = { side_hit: "溅射命中", chain: "连锁跳跃", heal: "治疗", guard: "守护", shield: "护盾", knockback: "击退", pull: "拉拽",
    energy: "回能", energy_drain: "夺能", drain: "汲取", cleanse: "净化", taunt: "嘲讽", root: "定身", apply: "施加", thorns: "反伤",
    thorn_hit: "反伤命中", execute: "处决", flinch: "畏缩", status: "异常", vulnerability: "易伤", tempo: "节拍", wet: "潮湿" };

  // ------------------------------------------------------------ helpers
  function status(text, error = false) {
    const el = $("wb-status");
    el.textContent = text;
    el.classList.toggle("error", !!error);
  }
  async function getJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    let body = null;
    try { body = await response.json(); } catch { body = null; }
    if (!response.ok || !body || body.ok === false) throw new Error((body && body.error) || `请求失败（${response.status}）`);
    return body;
  }
  const plan = () => state.rendB && state.rendB.plan;
  const duration = () => (state.rendB ? state.rendB.duration : 0);

  // ------------------------------------------------------------ packs
  function stemOwning(group, key, field) {
    const packs = state.packsB[group];
    const stems = Object.keys(packs).sort();
    let owner = null;
    for (const stem of stems) if (packs[stem] && packs[stem][field] && Object.hasOwn(packs[stem][field], key)) owner = stem;
    return owner;
  }
  function remergeB() {
    state.mergedB = PB.mergePacks(state.packsB);
    if (state.rendB) {
      state.rendB.setPack(state.mergedB);
      state.rendB.render(state.p);
    }
    updateDirty();
    drawTimeline();
    renderDashboard();
  }
  function markDirty(group, stem) {
    state.dirty.add(group + "/" + stem);
    remergeB();
  }
  function updateDirty() {
    const n = state.dirty.size;
    $("wb-dirty-note").textContent = n ? `已修改 ${[...state.dirty].map((k) => k + ".json").join("、")}` : "与 A 相同";
    $("wb-save").disabled = !n;
    $("wb-revert").disabled = !n;
  }

  // ------------------------------------------------------------ source
  function setSource(kind) {
    state.source = kind;
    for (const b of document.querySelectorAll("[data-source]")) b.setAttribute("aria-selected", String(b.dataset.source === kind));
    for (const panel of document.querySelectorAll("[data-panel]")) panel.hidden = panel.dataset.panel !== kind;
    document.querySelector("[data-seed]").hidden = kind === "battle";
    $("wb-load").textContent = kind === "gallery" ? "施放所选技能" : "载入战斗脚本";
    if (kind !== "gallery") { state.loop = null; $("wb-g-panel").hidden = true; }
  }
  async function loadCatalogs() {
    try {
      const data = await getJson("/api/animation/characters?mode=arena");
      state.characters = data.characters || {};
      const rows = Object.values(state.characters).sort((a, b) => a.species - b.species);
      $("wb-species").innerHTML = rows.map((c) => `<option value="${c.species}">#${String(c.species).padStart(3, "0")} ${esc(c.name)} · ${esc(c.role || "")}${c.range > 1 ? " · 远程" : " · 近战"}</option>`).join("");
      $("wb-species").disabled = false;
    } catch (error) {
      $("wb-species").innerHTML = "<option>角色目录读取失败</option>";
    }
    try {
      const response = await fetch("/api/scenarios?mode=arena", { cache: "no-store" });
      const rows = await response.json();
      $("wb-scenario").innerHTML = rows.map((r) => `<option value="${esc(r.key)}"${r.key === "arena_showcase" ? " selected" : ""}>${esc(r.label)}</option>`).join("");
      $("wb-scenario").disabled = false;
    } catch {
      $("wb-scenario").innerHTML = "<option>场景目录读取失败</option>";
    }
  }
  function scriptUrl() {
    const seed = clamp(Math.round(Number($("wb-seed").value) || 0), 0, 4294967295);
    if (state.source === "scenario") return `/api/battle/script/scenario?${new URLSearchParams({ key: $("wb-scenario").value, seed })}`;
    if (state.source === "battle") return `/api/battle/script?${new URLSearchParams({ sid: $("wb-sid").value.trim(), round: $("wb-round").value })}`;
    if (state.source === "gallery") {
      const skill = state.gallery.find((g) => g.id === $("wb-g-list").value);
      if (!skill) return null;
      return `/api/battle/script/preview?${new URLSearchParams({ species: skill.species, kind: "cast", scene: $("wb-g-scene").value, seed })}`;
    }
    return `/api/battle/script/preview?${new URLSearchParams({ species: $("wb-species").value, kind: $("wb-kind").value, scene: $("wb-scene").value, seed })}`;
  }
  async function loadScript(event) {
    event?.preventDefault();
    const url = scriptUrl();
    if (!url) { status("先在技能库中选择一个技能。", true); return; }
    $("wb-load").disabled = true;
    status("正在生成战斗脚本（真实模拟，不写入存档）…");
    try {
      const script = await getJson(url);
      if (script.schema !== "poketactics.battle_script") throw new Error("返回的不是战斗脚本");
      useScript(script);
      if (state.source === "gallery") enterGallery($("wb-g-list").value);
      const src = script.source || {};
      status(`已载入：${src.kind === "scenario" ? "场景 " + src.scenario : src.kind === "preview" ? "单个动作 #" + src.species + " · " + src.action : "对局 " + (src.sid || "") + " 第 " + (src.round || "") + " 轮"}，${script.units.length} 名单位、${script.actions.length} 个动作。`);
    } catch (error) {
      status("载入失败：" + error.message, true);
    } finally {
      $("wb-load").disabled = false;
    }
  }
  function useScript(script) {
    stop();
    state.script = script;
    state.rendA?.destroy(); state.rendB?.destroy();
    state.rendA = new PB.BattleRenderer($("wb-canvas-a"), script, { pack: state.mergedA });
    state.rendB = new PB.BattleRenderer($("wb-canvas-b"), script, { pack: state.mergedB });
    $("wb-empty-a").hidden = $("wb-empty-b").hidden = true;
    state.p = 0;
    $("wb-seek").max = String(duration());
    $("wb-seek").disabled = false;
    $("wb-play").disabled = false;
    $("wb-dur").textContent = `/ ${duration().toFixed(2)} s`;
    const meta = $("wb-script-meta");
    const teams = [0, 1].map((t) => script.units.filter((u) => u.team === t).map((u) => u.name).join("、"));
    meta.innerHTML = `<dt>时长</dt><dd>${Number(script.clock.duration).toFixed(2)} s</dd><dt>动作</dt><dd>${script.actions.filter((a) => !a.secondary).length} 主动作 · ${script.actions.length} 总</dd><dt>事件</dt><dd>${script.events.length} 条</dd><dt>我方</dt><dd>${esc(teams[0])}</dd><dt>敌方</dt><dd>${esc(teams[1])}</dd>`;
    // default selection: the first primary action of unit 0 (the preview hero)
    const first = plan().actions.find((a) => !a.secondary && !a.terrain && a.actor === script.units[0].idx) || plan().actions.find((a) => !a.secondary);
    if (first) selectAction(first, false);
    else selectUnit(script.units[0].idx, "idle");
    Promise.all([state.rendA.ready, state.rendB.ready]).then(() => seek(state.p));
    seek(0);
    drawTimeline();
    renderDashboard();
  }

  // ------------------------------------------------------------ transport
  function seek(p) {
    if (!state.rendB) return;
    state.p = clamp(p, 0, duration());
    state.rendA.render(state.p);
    state.rendB.render(state.p);
    $("wb-seek").value = String(state.p);
    $("wb-time").textContent = `${state.p.toFixed(3)} s`;
    $("wb-sim").textContent = `模拟 ${PB.toSim(plan(), state.p).toFixed(3)} s`;
    drawTimeline();
  }
  function tick(now) {
    if (!state.playing) return;
    const dt = Math.min(0.1, (now - state.last) / 1000);
    state.last = now;
    let next = state.p + dt * state.speed;
    if (state.loop && $("wb-loop").checked && (next >= state.loop.to || next < state.loop.from - 0.5)) next = state.loop.from;
    if (next >= duration()) {
      if ($("wb-loop").checked) next = 0;
      else { seek(duration()); stop(); return; }
    }
    seek(next);
    state.raf = requestAnimationFrame(tick);
  }
  function play() {
    if (!state.rendB) return;
    if (state.p >= duration() - 1e-6) state.p = state.loop ? state.loop.from : 0;
    state.playing = true;
    state.last = performance.now();
    $("wb-play").textContent = "暂停";
    state.raf = requestAnimationFrame(tick);
  }
  function stop() {
    state.playing = false;
    cancelAnimationFrame(state.raf);
    $("wb-play").textContent = "播放";
  }

  // ------------------------------------------------------------ timeline
  const TL = { label: 112, ruler: 18, row: 22, gap: 2 };
  function timelineWindow() {
    const d = duration() || 1;
    const zoom = Number($("wb-zoom").value) || 1;
    const span = d / zoom;
    const start = clamp(state.p - span / 2, 0, Math.max(0, d - span));
    return { start, span };
  }
  function drawTimeline() {
    const canvas = $("wb-timeline");
    const pl = plan();
    const width = Math.max(320, canvas.parentElement.clientWidth - 32);
    const unitRows = pl ? pl.order.length : 0;
    const height = TL.ruler + (3 + unitRows) * (TL.row + TL.gap) + 6;
    const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
      canvas.style.height = height + "px";
    }
    const g = canvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, width, height);
    g.font = "11px -apple-system, 'PingFang SC', sans-serif";
    state.timelineRows = [];
    if (!pl) { g.fillStyle = "#62715d"; g.fillText("载入战斗脚本后显示轨道", 12, 30); return; }
    const { start, span } = timelineWindow();
    const x0 = TL.label, x1 = width - 6;
    const X = (p) => x0 + (p - start) / span * (x1 - x0);
    const P = (s) => PB.toPlayback(pl, s);
    // ruler
    g.fillStyle = "#f5f1df"; g.fillRect(0, 0, width, TL.ruler);
    const step = span > 20 ? 2 : span > 8 ? 1 : span > 3 ? 0.5 : 0.1;
    g.fillStyle = "#62715d"; g.strokeStyle = "#d6d8c6";
    for (let t = Math.ceil(start / step) * step; t <= start + span + 1e-9; t += step) {
      const x = X(t);
      g.beginPath(); g.moveTo(x, TL.ruler - 5); g.lineTo(x, height); g.stroke();
      g.fillText(t.toFixed(step < 1 ? 1 : 0) + "s", x + 2, 12);
    }
    let y = TL.ruler + 2;
    const rowLabel = (text, sub) => {
      g.fillStyle = "#283d34"; g.fillText(text, 6, y + 14);
      if (sub) { g.fillStyle = "#62715d"; g.fillText(sub, 6 + g.measureText(text).width + 4, y + 14); }
    };
    const seg = (pa, pb, color, h = TL.row - 6, dy = 3) => {
      const a = X(pa), b = X(pb);
      if (b < x0 || a > x1) return;
      g.fillStyle = color; g.fillRect(Math.max(x0, a), y + dy, Math.max(1.5, Math.min(x1, b) - Math.max(x0, a)), h);
    };
    // camera track
    rowLabel("镜头");
    for (const c of pl.cameras) seg(P(c.t0), P(c.t1), CAM_COLORS[c.kind] || "#5d8fb3", 8, c.kind === "chain" || c.kind === "focus" ? 12 : 4);
    state.timelineRows.push({ kind: "camera", y });
    y += TL.row + TL.gap;
    // hitstops + banners
    rowLabel("顿帧/横幅");
    for (const b of pl.banners) seg(P(b.t), P(b.t + b.dur), "rgba(123,92,200,0.35)", 8, 12);
    for (const h of pl.hitstops || []) {
      seg(h.p0, h.p1 + 0.01, "#c03c6a", 14, 2);
      if (h.slow) seg(P(h.at - h.slow), h.p0, "rgba(192,60,106,0.35)", 6, 6);
    }
    state.timelineRows.push({ kind: "stops", y });
    y += TL.row + TL.gap;
    // events
    rowLabel("事件");
    for (const ev of pl.script.events) {
      const kind = ev[2];
      if (kind === "unit_state" || kind === "deploy") continue;
      const x = X(P(ev[0]));
      if (x < x0 || x > x1) continue;
      g.fillStyle = EVENT_COLORS[kind] || "#8a8a7a";
      g.fillRect(x - 1, y + (kind === "die" ? 2 : 6), kind === "die" ? 3 : 2, kind === "die" ? TL.row - 4 : TL.row - 12);
    }
    state.timelineRows.push({ kind: "events", y });
    y += TL.row + TL.gap;
    // units
    for (const idx of pl.order) {
      const unit = pl.units[idx];
      g.fillStyle = unit.team ? "rgba(249,111,111,0.10)" : "rgba(87,193,247,0.10)";
      g.fillRect(0, y, width, TL.row);
      if (state.sel.unit === idx) { g.fillStyle = "rgba(188,148,75,0.18)"; g.fillRect(0, y, width, TL.row); }
      g.fillStyle = unit.team ? "#b84a3e" : "#2f6f99";
      g.fillRect(0, y, 3, TL.row);
      rowLabel(`${unit.name}`, `${unit.arche}`);
      for (const a of unit.actions) {
        if (a.secondary || a.terrain) {
          const x = X(P(a.impact));
          if (x >= x0 && x <= x1) { g.fillStyle = "#62715d"; g.beginPath(); g.arc(x, y + TL.row / 2, 2, 0, Math.PI * 2); g.fill(); }
          continue;
        }
        seg(P(a.start), P(a.release), "#d9b25a");
        seg(P(a.release), P(a.impact), "#d9774a");
        seg(P(a.impact), P(a.end), "#8fa98a");
        const xi = X(P(a.impact));
        if (xi >= x0 && xi <= x1) {
          g.fillStyle = "#2d3b33"; g.fillRect(xi - 1, y + 1, 2, TL.row - 2);
          if (a.ult) { g.fillStyle = "#7b5cc8"; g.beginPath(); g.moveTo(xi, y - 1); g.lineTo(xi + 5, y + 5); g.lineTo(xi - 5, y + 5); g.fill(); }
          if (a.ko) { g.fillStyle = "#b8432f"; g.fillRect(xi + 2, y + TL.row - 8, 7, 7); }
        }
        if (state.sel.action === a.i) {
          g.strokeStyle = "#283d34"; g.lineWidth = 2;
          const a0 = X(P(a.start)), a1 = X(P(a.end));
          g.strokeRect(Math.max(x0, a0) - 1, y + 1, Math.min(x1, a1) - Math.max(x0, a0) + 2, TL.row - 2);
          g.lineWidth = 1;
        }
      }
      if (unit.death) {
        const x = X(P(unit.death.t));
        if (x >= x0 && x <= x1) { g.fillStyle = "#b8432f"; g.font = "bold 12px sans-serif"; g.fillText("✕", x - 4, y + 15); g.font = "11px -apple-system, 'PingFang SC', sans-serif"; }
      }
      state.timelineRows.push({ kind: "unit", idx, y });
      y += TL.row + TL.gap;
    }
    // playhead
    const xp = X(state.p);
    g.strokeStyle = "#a04c3d"; g.lineWidth = 2;
    g.beginPath(); g.moveTo(xp, 0); g.lineTo(xp, height); g.stroke(); g.lineWidth = 1;
    state.timelineGeom = { x0, x1, start, span };
  }
  function timelineClick(event) {
    const pl = plan();
    if (!pl || !state.timelineGeom) return;
    const rect = $("wb-timeline").getBoundingClientRect();
    const x = event.clientX - rect.left, y = event.clientY - rect.top;
    const { x0, x1, start, span } = state.timelineGeom;
    if (x < x0) {
      const row = state.timelineRows.find((r) => y >= r.y && y < r.y + TL.row);
      if (row && row.kind === "unit") selectUnit(row.idx, null);
      return;
    }
    const p = start + (x - x0) / (x1 - x0) * span;
    const row = state.timelineRows.find((r) => y >= r.y && y < r.y + TL.row);
    if (row && row.kind === "unit") {
      const unit = pl.units[row.idx];
      const s = PB.toSim(pl, p);
      const hit = unit.actions.filter((a) => !a.secondary && !a.terrain).find((a) => s >= a.start - 0.03 && s <= a.end + 0.03);
      if (hit) { selectAction(hit, true); return; }
      selectUnit(row.idx, null);
    }
    stop();
    seek(p);
  }

  // ------------------------------------------------------------ selection
  function selectAction(action, jump) {
    const pl = plan();
    state.sel = { unit: action.actor, action: action.i };
    const unit = pl.units[action.actor];
    const phase = action.slot === "attack_melee" ? "dash" : "anticipation";
    state.partsClipId = (unit.partSource && unit.partSource[action.slot]) || unit.clips[action.slot + "_id"];
    setClip(unit.clips[action.slot + "_id"], phase);
    $("wb-arche").value = unit.arche;
    const zhKind = action.isCast ? (action.skill?.name || "技能") : "普攻";
    $("wb-selection").innerHTML = `<b>${esc(unit.name)}</b> · ${esc(zhKind)} → ${esc(pl.units[action.target]?.name || "")} · 片段 <code>${esc(unit.clips[action.slot + "_id"])}</code> · 蓄力 ${action.anticipation.toFixed(2)}s / 出手 ${action.travel.toFixed(2)}s / 收招 ${action.recover.toFixed(2)}s · 弹道 ${esc(action.family)} · 配方 <code>${esc(action.recipe)}</code>${action.ult ? " · 大招" : ""}${action.ko ? " · 击倒" : ""}`;
    selectRecipe(action.recipe);
    renderTiming();
    if (jump) { stop(); seek(PB.toPlayback(pl, action.start) - 0.08); }
    else drawTimeline();
  }
  function selectUnit(idx, slot) {
    const pl = plan();
    const unit = pl.units[idx];
    if (!unit) return;
    state.sel = { unit: idx, action: null };
    const chosen = slot || "idle";
    state.partsClipId = (unit.partSource && unit.partSource[chosen]) || unit.clips[chosen + "_id"];
    setClip(unit.clips[chosen + "_id"], null);
    $("wb-arche").value = unit.arche;
    $("wb-selection").innerHTML = `<b>${esc(unit.name)}</b> · ${esc(ROLE_ZH[unit.role] || unit.role)} · 原型 ${esc(unit.arche)} · 体重 ${unit.weight.toFixed(2)} · 稳定偏移 ${unit.offset >= 0 ? "+" : ""}${unit.offset.toFixed(3)}s · 待机周期 ${unit.idlePeriod.toFixed(2)}s`;
    renderTiming();
    drawTimeline();
  }

  // ------------------------------------------------------------ clip editor
  function clipOptions() {
    const clips = state.mergedB.clips;
    const groups = {};
    for (const id of Object.keys(clips).sort()) {
      const slot = clips[id].slot;
      (groups[slot] ||= []).push(id);
    }
    $("wb-clip").innerHTML = Object.entries(groups).map(([slot, ids]) => `<optgroup label="${esc(SLOT_ZH[slot] || slot)}">${ids.map((id) => `<option value="${esc(id)}">${esc(id)}</option>`).join("")}</optgroup>`).join("");
  }
  function setClip(id, phase) {
    if (!id || !state.mergedB.clips[id]) return;
    state.clipId = id;
    if ($("wb-clip").value !== id) $("wb-clip").value = id;
    const clip = state.mergedB.clips[id];
    const phases = Object.keys(clip.phases);
    state.phase = phase && phases.includes(phase) ? phase : phases[0];
    $("wb-phase").innerHTML = phases.map((p) => `<option value="${p}"${p === state.phase ? " selected" : ""}>${PHASE_ZH[p] || p}</option>`).join("");
    state.keyRow = Math.min(state.keyRow, clip.phases[state.phase].length - 1);
    const owner = stemOwning("motion", id, "clips");
    $("wb-owner").textContent = owner ? `编辑 assets/motion/${owner}.json` : "内置后备片段（只读）";
    $("wb-clip-note").textContent = `${SLOT_ZH[clip.slot] || clip.slot}${clip.period ? " · 周期 " + clip.period + "s" : ""}${clip.note ? " · " + clip.note : ""}。单位为源精灵像素，前进方向为 +dx；角度顺时针；缩放 100 为原尺寸。`;
    if (!state.partsClipId || state.mergedB.clips[state.partsClipId]?.slot !== clip.slot) state.partsClipId = id;
    renderKeys();
    partsClipOptions();
    renderParts();
  }
  function editableClip() {
    const owner = stemOwning("motion", state.clipId, "clips");
    return owner ? { owner, clip: state.packsB.motion[owner].clips[state.clipId] } : null;
  }
  const FIELDS = [["at", 0, 1, 0.01], ["dx", -48, 48, 1], ["dy", -48, 48, 1], ["angle", -180, 180, 1], ["sx", 50, 150, 1], ["sy", 50, 150, 1]];
  function renderKeys() {
    const clip = state.mergedB.clips[state.clipId];
    const keys = clip?.phases[state.phase] || [];
    const editable = !!editableClip();
    $("wb-keys").innerHTML = keys.map((k, r) => `<tr data-row="${r}"${r === state.keyRow ? ' class="selected"' : ""}>${FIELDS.map(([name, lo, hi, step], f) => `<td><input type="number" data-f="${f}" min="${lo}" max="${hi}" step="${step}" value="${k[f]}" aria-label="${name}"${editable ? "" : " disabled"}${f === 0 && (r === 0 || r === keys.length - 1) ? " readonly title=\"端点固定为 0 与 1\"" : ""}></td>`).join("")}<td><input type="checkbox" data-f="6"${k[6] ? " checked" : ""}${editable ? "" : " disabled"} aria-label="可见"></td><td><select data-f="7"${editable ? "" : " disabled"} aria-label="缓动">${EASES.map((e) => `<option${e === k[7] ? " selected" : ""}>${e}</option>`).join("")}</select></td><td>${keys.length > 2 && r > 0 && r < keys.length - 1 && editable ? `<button type="button" data-remove="${r}" aria-label="删除关键帧">✕</button>` : ""}</td></tr>`).join("");
    $("wb-add-key").disabled = !editable || keys.length >= 16;
    $("wb-ease-preset").disabled = !editable;
    drawEasePlot();
    drawPosePlot();
  }
  function validateKeys(keys) {
    if (keys.length < 2 || keys.length > 16) return "每个阶段需要 2–16 个关键帧";
    if (keys[0][0] !== 0 || keys[keys.length - 1][0] !== 1) return "首尾关键帧时间必须是 0 和 1";
    for (let i = 0; i < keys.length; i++) {
      const k = keys[i];
      if (i && !(k[0] > keys[i - 1][0])) return `第 ${i + 1} 帧时间必须严格递增`;
      for (let f = 1; f < 6; f++) if (!Number.isInteger(k[f])) return `第 ${i + 1} 帧的位移/角度/缩放必须是整数`;
      if (Math.abs(k[1]) > 48 || Math.abs(k[2]) > 48) return `第 ${i + 1} 帧位移超出 ±48`;
      if (Math.abs(k[3]) > 180) return `第 ${i + 1} 帧角度超出 ±180`;
      if (k[4] < 50 || k[4] > 150 || k[5] < 50 || k[5] > 150) return `第 ${i + 1} 帧缩放超出 50–150`;
      if (!EASES.includes(k[7])) return `第 ${i + 1} 帧缓动未知`;
    }
    return null;
  }
  function keyInput(event) {
    const target = event.target;
    const row = target.closest("tr")?.dataset.row;
    if (row == null || target.dataset.f == null) return;
    const edit = editableClip();
    if (!edit) return;
    const keys = edit.clip.phases[state.phase];
    const r = Number(row), f = Number(target.dataset.f);
    state.keyRow = r;
    let value;
    if (f === 6) value = target.checked ? 1 : 0;
    else if (f === 7) value = target.value;
    else {
      value = Number(target.value);
      if (!Number.isFinite(value)) { target.classList.add("bad"); return; }
      value = f === 0 ? Math.round(value * 1000) / 1000 : Math.round(value);
    }
    const before = keys[r][f];
    keys[r][f] = value;
    const problem = validateKeys(keys);
    $("wb-key-error").hidden = !problem;
    $("wb-key-error").textContent = problem || "";
    target.classList.toggle("bad", !!problem);
    if (problem) { keys[r][f] = before; return; }
    for (const tr of $("wb-keys").children) tr.classList.toggle("selected", tr.dataset.row === String(r));
    markDirty("motion", edit.owner);
    drawEasePlot(); drawPosePlot();
  }
  function addKey() {
    const edit = editableClip();
    if (!edit) return;
    const keys = edit.clip.phases[state.phase];
    if (keys.length >= 16) return;
    // insert after the selected row (or before the last), sampled from the curve
    let r = Math.min(state.keyRow, keys.length - 2);
    const a = keys[r], b = keys[r + 1];
    const at = Math.round((a[0] + b[0]) / 2 * 1000) / 1000;
    if (!(at > a[0] && at < b[0])) return;
    const pose = PB.sampleTrack(keys, at);
    const key = [at, Math.round(pose.dx), Math.round(pose.dy), Math.round(pose.angle), Math.round(pose.sx * 100), Math.round(pose.sy * 100), a[6], a[7]];
    keys.splice(r + 1, 0, key);
    state.keyRow = r + 1;
    markDirty("motion", edit.owner);
    renderKeys();
  }
  function removeKey(r) {
    const edit = editableClip();
    if (!edit) return;
    const keys = edit.clip.phases[state.phase];
    if (keys.length <= 2 || r <= 0 || r >= keys.length - 1) return;
    keys.splice(r, 1);
    state.keyRow = Math.max(0, r - 1);
    markDirty("motion", edit.owner);
    renderKeys();
  }
  function applyEasePreset(name) {
    const edit = editableClip();
    if (!edit || !name) return;
    const keys = edit.clip.phases[state.phase];
    const presets = { snappy: ["easeOutExpo", "easeOutBack"], heavy: ["easeInCubic", "easeOutBounce"], soft: ["easeInOutQuad"], linear: ["linear"] };
    const list = presets[name];
    keys.forEach((k, i) => { k[7] = list[Math.min(i, list.length - 1)]; });
    markDirty("motion", edit.owner);
    renderKeys();
    $("wb-ease-preset").value = "";
  }
  function drawEasePlot() {
    const c = $("wb-ease-plot"), g = c.getContext("2d");
    const keys = state.mergedB.clips[state.clipId]?.phases[state.phase] || [];
    const name = keys[state.keyRow]?.[7] || "linear";
    g.clearRect(0, 0, c.width, c.height);
    const pad = 14, w = c.width - pad * 2, h = c.height - pad * 2 - 8;
    g.strokeStyle = "#d6d8c6"; g.strokeRect(pad, pad, w, h);
    g.strokeStyle = "#344f3e"; g.lineWidth = 2; g.beginPath();
    for (let i = 0; i <= 60; i++) {
      const x = i / 60, y = PB.EASE[name](x);
      const px = pad + x * w, py = pad + h - y * h;
      i ? g.lineTo(px, py) : g.moveTo(px, py);
    }
    g.stroke(); g.lineWidth = 1;
    g.fillStyle = "#62715d"; g.font = "11px ui-monospace, monospace"; g.fillText(name, pad, c.height - 4);
  }
  function drawPosePlot() {
    const c = $("wb-pose-plot"), g = c.getContext("2d");
    const keys = state.mergedB.clips[state.clipId]?.phases[state.phase] || [];
    g.clearRect(0, 0, c.width, c.height);
    if (!keys.length) return;
    const pad = 10, w = c.width - pad * 2, h = c.height - pad * 2;
    const mid = pad + h / 2;
    g.strokeStyle = "#d6d8c6"; g.beginPath(); g.moveTo(pad, mid); g.lineTo(pad + w, mid); g.stroke();
    const series = [["dx", "#3d7fb0", (p) => p.dx / 48], ["dy", "#c2732f", (p) => p.dy / 48], ["sy", "#6a9a5c", (p) => (p.sy - 1) / 0.5]];
    for (const [, color, fn] of series) {
      g.strokeStyle = color; g.lineWidth = 2; g.beginPath();
      for (let i = 0; i <= 80; i++) {
        const q = i / 80, v = fn(PB.sampleTrack(keys, q));
        const px = pad + q * w, py = mid - clamp(v, -1, 1) * h / 2;
        i ? g.lineTo(px, py) : g.moveTo(px, py);
      }
      g.stroke();
    }
    g.lineWidth = 1;
    for (const [i, k] of keys.entries()) {
      g.fillStyle = i === state.keyRow ? "#a04c3d" : "#283d34";
      g.fillRect(pad + k[0] * w - 2, pad + h - 6, 4, 6);
    }
  }

  // ------------------------------------------------------------ part deformation
  function partsClipOptions() {
    const clips = state.mergedB.clips;
    const slot = clips[state.clipId]?.slot;
    const ids = Object.keys(clips).filter((id) => clips[id].slot === slot).sort();
    $("wb-parts-clip").innerHTML = ids.map((id) => `<option value="${esc(id)}"${id === state.partsClipId ? " selected" : ""}>${esc(id)}${clips[id].parts ? " ●" : ""}</option>`).join("");
  }
  function editablePartsClip() {
    const owner = stemOwning("motion", state.partsClipId, "clips");
    return owner ? { owner, clip: state.packsB.motion[owner].clips[state.partsClipId] } : null;
  }
  function roleClipFor(slot) {
    const pl = plan();
    const unit = pl && state.sel.unit != null ? pl.units[state.sel.unit] : null;
    const arche = unit ? unit.arche : $("wb-arche").value;
    const id = state.mergedB.archetypes[arche]?.clips?.[slot];
    return id && state.mergedB.clips[id] ? { id, clip: state.mergedB.clips[id], arche } : null;
  }
  function renderParts() {
    const clip = state.mergedB.clips[state.partsClipId];
    const keys = clip?.parts?.[state.phase] || [];
    const edit = editablePartsClip();
    const role = clip ? roleClipFor(clip.slot) : null;
    const pl = plan();
    const unit = pl && state.sel.unit != null ? pl.units[state.sel.unit] : null;
    let note;
    if (!clip) note = "—";
    else if (keys.length) note = `${edit ? "可编辑 · assets/motion/" + edit.owner + ".json" : "内置（只读）"}${unit && unit.partSource && Object.values(unit.partSource).includes(state.partsClipId) ? " · 选中单位正在使用" : ""}`;
    else if (clip.parts) note = `该片段没有「${PHASE_ZH[state.phase] || state.phase}」阶段的形变轨道（此阶段不形变）。`;
    else note = role && role.clip.parts ? `该片段没有形变轨道，渲染时沿用原型 ${role.id}。` : "该片段没有形变轨道。";
    $("wb-parts-note").textContent = note;
    $("wb-parts").innerHTML = keys.map((k, r) => `<tr data-row="${r}"${r === state.partsRow ? ' class="selected"' : ""}><td><input type="number" data-f="0" min="0" max="1" step="0.01" value="${k[0]}"${edit ? "" : " disabled"}${r === 0 || r === keys.length - 1 ? ' readonly title="端点固定为 0 与 1"' : ""} aria-label="at"></td>${PART_COLS.map((name, i) => `<td><input type="number" data-f="${i + 1}" min="${PART_LIMITS[name][0]}" max="${PART_LIMITS[name][1]}" step="0.5" value="${k[i + 1]}"${edit ? "" : " disabled"} aria-label="${name}"></td>`).join("")}<td><select data-f="6"${edit ? "" : " disabled"} aria-label="缓动">${EASES.map((e) => `<option${e === k[6] ? " selected" : ""}>${e}</option>`).join("")}</select></td><td>${edit && keys.length > 2 && r > 0 && r < keys.length - 1 ? `<button type="button" data-premove="${r}" aria-label="删除形变帧">✕</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="8" class="wb-note">无关键帧</td></tr>`;
    $("wb-parts-add").disabled = !edit || keys.length < 2 || keys.length >= 16;
    $("wb-parts-new").disabled = !edit || keys.length > 0 || !clip?.phases?.[state.phase];
    $("wb-parts-copy").disabled = !edit || !!clip?.parts || !(role && role.clip.parts && role.id !== state.partsClipId);
    $("wb-parts-copy").title = role ? `复制 ${role.id} 的全部形变轨道` : "";
    drawPartsPlot();
  }
  function validateParts(keys) {
    if (!Array.isArray(keys) || keys.length < 2 || keys.length > 16) return "每个阶段需要 2–16 个形变帧";
    if (keys[0][0] !== 0 || keys[keys.length - 1][0] !== 1) return "首尾形变帧时间必须是 0 和 1";
    for (let i = 0; i < keys.length; i++) {
      const k = keys[i];
      if (k.length !== 7) return `第 ${i + 1} 帧字段数应为 7`;
      if (i && !(k[0] > keys[i - 1][0])) return `第 ${i + 1} 帧时间必须严格递增`;
      for (const [j, name] of PART_COLS.entries()) {
        const [lo, hi] = PART_LIMITS[name];
        if (!Number.isFinite(k[j + 1]) || k[j + 1] < lo || k[j + 1] > hi) return `第 ${i + 1} 帧 ${name} 超出 ${lo}…${hi}`;
      }
      if (!EASES.includes(k[6])) return `第 ${i + 1} 帧缓动未知`;
    }
    return null;
  }
  function partsInput(event) {
    const target = event.target;
    const row = target.closest("tr")?.dataset.row;
    if (row == null || target.dataset.f == null) return;
    const edit = editablePartsClip();
    if (!edit) return;
    const keys = edit.clip.parts[state.phase];
    const r = Number(row), f = Number(target.dataset.f);
    state.partsRow = r;
    let value = target.value;
    if (f !== 6) {
      value = Number(value);
      if (!Number.isFinite(value)) { target.classList.add("bad"); return; }
      value = f === 0 ? Math.round(value * 1000) / 1000 : Math.round(value * 10) / 10;
    }
    const before = keys[r][f];
    keys[r][f] = value;
    const problem = validateParts(keys);
    $("wb-parts-error").hidden = !problem;
    $("wb-parts-error").textContent = problem || "";
    target.classList.toggle("bad", !!problem);
    if (problem) { keys[r][f] = before; setTimeout(() => { target.value = String(before); target.classList.remove("bad"); }, 1600); return; }
    markDirty("motion", edit.owner);
    drawPartsPlot();
  }
  function addPartKey() {
    const edit = editablePartsClip();
    const keys = edit?.clip.parts?.[state.phase];
    if (!keys || keys.length >= 16) return;
    const r = Math.min(state.partsRow, keys.length - 2);
    const a = keys[r], b = keys[r + 1];
    const at = Math.round((a[0] + b[0]) / 2 * 1000) / 1000;
    if (!(at > a[0] && at < b[0])) return;
    const v = PB.sampleParts(keys, at);
    keys.splice(r + 1, 0, [at, ...PART_COLS.map((name) => Math.round(v[name] * 10) / 10), a[6]]);
    state.partsRow = r + 1;
    markDirty("motion", edit.owner);
    renderParts();
  }
  function removePartKey(r) {
    const edit = editablePartsClip();
    const keys = edit?.clip.parts?.[state.phase];
    if (!keys || keys.length <= 2 || r <= 0 || r >= keys.length - 1) return;
    keys.splice(r, 1);
    state.partsRow = Math.max(0, r - 1);
    markDirty("motion", edit.owner);
    renderParts();
  }
  function newPartsTrack() {
    const edit = editablePartsClip();
    if (!edit || !edit.clip.phases?.[state.phase]) return;
    edit.clip.parts = edit.clip.parts || {};
    if (edit.clip.parts[state.phase]) return;
    // start from what the renderer currently uses for this slot/phase
    const role = roleClipFor(edit.clip.slot);
    const fallback = role?.clip.parts?.[state.phase];
    edit.clip.parts[state.phase] = fallback ? clone(fallback) : [[0, 0, 0, 0, 0, 0, "easeInOutQuad"], [1, 0, 0, 0, 0, 0, "easeInOutQuad"]];
    state.partsRow = 0;
    markDirty("motion", edit.owner);
    partsClipOptions();
    renderParts();
  }
  function copyRoleParts() {
    const edit = editablePartsClip();
    if (!edit || edit.clip.parts) return;
    const role = roleClipFor(edit.clip.slot);
    if (!role || !role.clip.parts) return;
    edit.clip.parts = clone(role.clip.parts);
    for (const phase of Object.keys(edit.clip.parts)) if (!edit.clip.phases[phase]) delete edit.clip.parts[phase];
    state.partsRow = 0;
    markDirty("motion", edit.owner);
    partsClipOptions();
    renderParts();
    $("wb-save-note").textContent = `已把 ${role.id} 的形变轨道复制到 ${state.partsClipId}（B）。`;
  }
  function drawPartsPlot() {
    const c = $("wb-parts-plot"), g = c.getContext("2d");
    const keys = state.mergedB.clips[state.partsClipId]?.parts?.[state.phase] || [];
    g.clearRect(0, 0, c.width, c.height);
    const pad = 10, w = c.width - pad * 2, h = c.height - pad * 2, mid = pad + h / 2;
    g.strokeStyle = "#d6d8c6"; g.beginPath(); g.moveTo(pad, mid); g.lineTo(pad + w, mid); g.stroke();
    if (!keys.length) { g.fillStyle = "#62715d"; g.font = "11px sans-serif"; g.fillText("无形变轨道", pad + 4, mid - 6); return; }
    PART_COLS.forEach((name, i) => {
      const span = Math.max(Math.abs(PART_LIMITS[name][0]), Math.abs(PART_LIMITS[name][1]));
      g.strokeStyle = PART_COLORS[i]; g.lineWidth = 2; g.beginPath();
      for (let j = 0; j <= 80; j++) {
        const q = j / 80, v = PB.sampleParts(keys, q)[name] / span;
        const px = pad + q * w, py = mid - clamp(v, -1, 1) * h / 2;
        j ? g.lineTo(px, py) : g.moveTo(px, py);
      }
      g.stroke();
    });
    g.lineWidth = 1;
    for (const [i, k] of keys.entries()) { g.fillStyle = i === state.partsRow ? "#a04c3d" : "#283d34"; g.fillRect(pad + k[0] * w - 2, pad + h - 6, 4, 6); }
  }

  // ------------------------------------------------------------ skill gallery
  function buildGallery() {
    const merged = state.mergedB;
    const bindings = merged.vfx.bindings.skill || {};
    const owners = {};
    for (const c of Object.values(state.characters)) {
      const id = c.skill && c.skill.native_id;
      if (id) (owners[id] ||= []).push(c);
    }
    state.gallery = Object.entries(bindings).map(([id, recipeId]) => {
      const recipe = merged.vfx.recipes[recipeId] || {};
      const category = String(recipe.extends || "").replace(/^cat\./, "") || "—";
      const holders = (owners[id] || []).sort((a, b) => a.species - b.species);
      const name = holders[0]?.skill?.name || String(recipe.note || id).split(" · ")[0];
      return { id, recipe: recipeId, category, name, note: recipe.note || "", species: holders[0]?.species ?? null,
        holder: holders[0]?.name || "", holders: holders.map((c) => `#${c.species} ${c.name}`) };
    }).filter((g) => g.species != null).sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name, "zh"));
    const cats = [...new Set(state.gallery.map((g) => g.category))].sort();
    const current = $("wb-g-cat").value;
    $("wb-g-cat").innerHTML = `<option value="">全部类别（${state.gallery.length}）</option>` + cats.map((c) => `<option value="${esc(c)}"${c === current ? " selected" : ""}>${esc(CATEGORY_ZH[c] || c)} · ${esc(c)}（${state.gallery.filter((g) => g.category === c).length}）</option>`).join("");
    renderGalleryList();
  }
  function renderGalleryList() {
    const cat = $("wb-g-cat").value, q = $("wb-g-search").value.trim().toLowerCase();
    const keep = $("wb-g-list").value;
    state.galleryShown = state.gallery.filter((g) => (!cat || g.category === cat)
      && (!q || [g.id, g.name, g.note, ...g.holders].some((t) => String(t).toLowerCase().includes(q))));
    const groups = {};
    for (const g of state.galleryShown) (groups[g.category] ||= []).push(g);
    $("wb-g-list").innerHTML = Object.entries(groups).map(([c, rows]) => `<optgroup label="${esc(CATEGORY_ZH[c] || c)}">${rows.map((g) => `<option value="${esc(g.id)}"${g.id === keep ? " selected" : ""}>${esc(g.name)} · ${esc(g.holder)}${g.holders.length > 1 ? " 等" + g.holders.length : ""}</option>`).join("")}</optgroup>`).join("");
    $("wb-g-count").textContent = `${state.galleryShown.length} 个`;
  }
  function stepGallery(delta) {
    if (!state.galleryShown.length) return;
    const i = state.galleryShown.findIndex((g) => g.id === $("wb-g-list").value);
    const next = state.galleryShown[(i < 0 ? 0 : (i + delta + state.galleryShown.length) % state.galleryShown.length)];
    $("wb-g-list").value = next.id;
    if (state.source !== "gallery") setSource("gallery");
    loadScript();
  }
  function galleryCast() {
    const pl = plan();
    if (!pl) return null;
    return pl.actions.find((a) => a.kind === "cast" && a.actor === state.script.units[0].idx && !a.secondary)
      || pl.actions.find((a) => a.kind === "cast" && !a.secondary) || null;
  }
  function enterGallery(skillId) {
    state.gallerySkill = state.gallery.find((g) => g.id === skillId) || null;
    const cast = galleryCast();
    if (!cast) { state.loop = null; $("wb-g-panel").hidden = true; return; }
    const pl = plan();
    const from = Math.max(0, PB.toPlayback(pl, cast.start - 0.2));
    const to = Math.min(duration(), PB.toPlayback(pl, Math.max(cast.end, cast.lastOutcome || 0) + 0.9));
    state.loop = { from, to };
    selectAction(cast, false);
    // open the recipe editor on the skill's own recipe
    const tab = document.querySelector('[data-editor="vfx"]');
    if (tab) tab.click();
    selectRecipe(state.gallerySkill && state.mergedB.vfx.recipes[state.gallerySkill.recipe] ? state.gallerySkill.recipe : cast.recipe);
    $("wb-g-panel").hidden = false;
    renderGalleryInfo();
    seek(from);
    play();
  }
  function renderGalleryInfo() {
    const cast = galleryCast();
    const pl = plan();
    if (!cast || !pl) return;
    const merged = state.mergedB;
    const raw = merged.vfx.recipes[cast.recipe] || {};
    const resolved = PB.resolveRecipe(merged, cast.recipe).layers;
    const nAdd = (raw.add || []).length, nOwn = (raw.layers || []).length, nBase = resolved.length - nAdd - nOwn;
    const skill = state.gallerySkill;
    $("wb-g-title").textContent = `${skill?.name || cast.skill?.name || ""} · ${CATEGORY_ZH[cast.skill?.category] || cast.skill?.category || ""} · 施放者 ${pl.units[cast.actor].name}`;
    $("wb-g-recipe").textContent = `${cast.recipe}${raw.extends ? " ← " + raw.extends : ""}${raw.scale ? " · 缩放 ×" + raw.scale : ""}${raw.family ? " · 弹道 " + raw.family : ""}`;
    $("wb-g-layers").innerHTML = resolved.map((l, i) => {
      const from = i < nBase ? ["cat", raw.extends || "类别"] : i < nBase + nOwn ? ["own", "技能"] : ["add", "技能附加"];
      const on = l.on ? (Array.isArray(l.on) ? l.on : [l.on]).map((x) => SUB_ZH[x] || x).join(" / ") : "—";
      return `<tr class="${from[0]}"><td>${i + 1}</td><td><span class="wb-tag ${from[0]}">${esc(from[1])}</span></td><td>${esc(l.layer)}</td><td>${esc(l.shape)}</td><td>${esc(l.at || "impact")}${l.offset ? "+" + l.offset : ""}</td><td>${esc(on)}${l.from ? " · 从 " + esc(l.from) : ""}${l.to ? " → " + esc(l.to) : ""}</td><td>${esc(l.palette || "@type")}</td><td>${l.duration != null ? l.duration + "s" : "—"}</td></tr>`;
    }).join("");
    const outs = (cast.outcomes || []).slice().sort((a, b) => a.t + (a.delay || 0) - (b.t + (b.delay || 0)));
    const matched = (o) => resolved.some((l) => l.on && (Array.isArray(l.on) ? l.on.includes(o.sub) : l.on === o.sub || l.on === "*"));
    $("wb-g-outcomes").innerHTML = outs.map((o) => `<li><span>${esc(SUB_ZH[o.sub] || o.sub)} <code>${esc(o.sub)}</code></span><span>→ ${esc(pl.units[o.tgt]?.name || "#" + o.tgt)}${pl.units[o.origin] && o.origin !== cast.actor ? "（自 " + esc(pl.units[o.origin].name) + "）" : ""}${matched(o) ? "" : ' <span class="wb-tag">无配方层</span>'}</span><span class="wb-muted">+${(o.delay || 0).toFixed(2)}s</span></li>`).join("")
      || '<li><span class="wb-muted">本次施放没有附带结果事件（纯伤害）。</span><span></span><span></span></li>';
  }

  // ------------------------------------------------------------ timing + vfx
  function renderTiming() {
    const arche = $("wb-arche").value;
    const owner = stemOwning("motion", arche, "archetypes");
    const row = owner ? state.packsB.motion[owner].archetypes[arche] : null;
    const timing = (row && row.timing) || {};
    $("wb-timing").innerHTML = Object.keys(TIMING_ZH).map((key) => {
      const [lo, hi, step] = TIMING_LIMITS[key];
      return `<label class="wb-field"><span>${TIMING_ZH[key]}</span><input type="number" data-timing="${key}" min="${lo}" max="${hi}" step="${step}" value="${timing[key] ?? ""}"${owner ? "" : " disabled"}></label>`;
    }).join("");
    const pl = plan();
    const unit = pl && state.sel.unit != null ? pl.units[state.sel.unit] : null;
    const sOwner = unit ? stemOwning("motion", String(unit.sid), "species") : null;
    $("wb-weight").disabled = !sOwner;
    if (unit) {
      const value = sOwner ? state.packsB.motion[sOwner].species[String(unit.sid)].timing?.weight : null;
      $("wb-weight").value = String(value ?? unit.weight);
      $("wb-weight-out").textContent = `${unit.name} ${(value ?? unit.weight).toFixed(2)}`;
    } else $("wb-weight-out").textContent = "未选择单位";
  }
  function timingInput(event) {
    const key = event.target.dataset.timing;
    if (!key) return;
    const arche = $("wb-arche").value;
    const owner = stemOwning("motion", arche, "archetypes");
    if (!owner) return;
    const [lo, hi] = TIMING_LIMITS[key];
    const value = Number(event.target.value);
    if (!Number.isFinite(value) || value < lo || value > hi) { event.target.classList.add("bad"); return; }
    event.target.classList.remove("bad");
    const row = state.packsB.motion[owner].archetypes[arche];
    row.timing = { ...(row.timing || {}), [key]: value };
    markDirty("motion", owner);
  }
  function weightInput() {
    const pl = plan();
    const unit = pl && state.sel.unit != null ? pl.units[state.sel.unit] : null;
    if (!unit) return;
    const owner = stemOwning("motion", String(unit.sid), "species");
    if (!owner) return;
    const row = state.packsB.motion[owner].species[String(unit.sid)];
    const value = Math.round(Number($("wb-weight").value) * 100) / 100;
    row.timing = { ...(row.timing || {}), weight: value };
    $("wb-weight-out").textContent = `${unit.name} ${value.toFixed(2)}`;
    markDirty("motion", owner);
  }
  function recipeOptions() {
    const ids = Object.keys(state.mergedB.vfx.recipes).sort();
    $("wb-recipe").innerHTML = ids.map((id) => `<option value="${esc(id)}">${esc(id)}</option>`).join("");
  }
  function selectRecipe(id) {
    if (!id || !state.mergedB.vfx.recipes[id]) return;
    $("wb-recipe").value = id;
    $("wb-recipe-json").value = JSON.stringify(state.mergedB.vfx.recipes[id], null, 1);
    $("wb-recipe-error").hidden = true;
    const owner = stemOwning("vfx", id, "recipes");
    $("wb-recipe-owner").textContent = owner ? `assets/vfx/${owner}.json` : "内置（只读）";
  }
  function applyRecipe() {
    const id = $("wb-recipe").value;
    const owner = stemOwning("vfx", id, "recipes");
    const error = (text) => { $("wb-recipe-error").hidden = false; $("wb-recipe-error").textContent = text; };
    if (!owner) return error("该配方不属于任何 assets/vfx 文件，无法编辑。");
    let value;
    try { value = JSON.parse($("wb-recipe-json").value); } catch (e) { return error("JSON 解析失败：" + e.message); }
    if (!value || typeof value !== "object") return error("配方必须是对象。");
    if (value.extends != null && !state.mergedB.vfx.recipes[value.extends]) return error(`extends 指向不存在的配方 ${value.extends}。`);
    if (value.extends === id) return error("配方不能继承自身。");
    if (value.extends == null && (!Array.isArray(value.layers) || !value.layers.length)) return error("配方需要非空 layers 数组，或用 extends 继承类别配方。");
    const layers = ["charge", "projectile", "trail", "impact", "ground", "aura", "link", "screen"];
    for (const group of ["layers", "add"]) {
      if (value[group] == null) continue;
      if (!Array.isArray(value[group])) return error(`${group} 必须是数组。`);
      const bad = value[group].findIndex((l) => !l || !layers.includes(l.layer) || typeof l.shape !== "string");
      if (bad >= 0) return error(`${group} 第 ${bad + 1} 层缺少有效的 layer / shape。`);
    }
    state.packsB.vfx[owner].recipes[id] = value;
    $("wb-recipe-error").hidden = true;
    markDirty("vfx", owner);
    if (state.source === "gallery" && state.gallerySkill) renderGalleryInfo();
  }

  // ------------------------------------------------------------ save/export
  async function save() {
    const changed = [...state.dirty];
    if (!changed.length) return;
    for (const key of changed) {
      const [group, stem] = key.split("/");
      if (group === "motion") {
        for (const [id, clip] of Object.entries(state.packsB.motion[stem].clips || {})) {
          for (const [phase, keys] of Object.entries(clip.phases)) {
            const problem = validateKeys(keys);
            if (problem) { $("wb-save-note").textContent = `未保存：${id} · ${PHASE_ZH[phase] || phase}：${problem}`; return; }
          }
          for (const [phase, keys] of Object.entries(clip.parts || {})) {
            const problem = validateParts(keys);
            if (problem) { $("wb-save-note").textContent = `未保存：${id} · 形变 ${PHASE_ZH[phase] || phase}：${problem}`; return; }
          }
        }
      }
    }
    $("wb-save").disabled = true;
    $("wb-save-note").textContent = "正在保存…";
    const saved = [];
    try {
      for (const key of changed) {
        const [group, stem] = key.split("/");
        const response = await fetch("/api/animation/pack/save", {
          method: "POST", cache: "no-store",
          headers: { "Content-Type": "application/json", "X-PokeTactics-Workbench": "1" },
          body: JSON.stringify({ group, name: stem, data: state.packsB[group][stem] }),
        });
        let body = null;
        try { body = await response.json(); } catch { body = null; }
        if (!response.ok || !body?.ok) throw new Error(`${key}.json：${body?.error || "保存失败（" + response.status + "）"}`);
        state.packsA[group][stem] = clone(state.packsB[group][stem]);
        state.dirty.delete(key);
        saved.push(body.path);
      }
      $("wb-save-note").textContent = `已保存 ${saved.join("、")}。`;
    } catch (error) {
      $("wb-save-note").textContent = "保存失败：" + error.message + (saved.length ? `（已保存 ${saved.join("、")}）` : "");
    }
    state.mergedA = PB.mergePacks(state.packsA);
    if (state.rendA) { state.rendA.setPack(state.mergedA); state.rendA.render(state.p); }
    updateDirty();
    renderDashboard();
  }
  function exportJson() {
    const keys = state.dirty.size ? [...state.dirty] : [...Object.keys(state.packsB.motion).map((s) => "motion/" + s), ...Object.keys(state.packsB.vfx).map((s) => "vfx/" + s)];
    const out = { schema_version: 1, exported_from: "animation-workbench", packs: {} };
    for (const key of keys) { const [group, stem] = key.split("/"); out.packs[key + ".json"] = state.packsB[group][stem]; }
    const blob = new Blob([JSON.stringify(out, null, 1)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = state.dirty.size ? "poketactics-motion-edits.json" : "poketactics-motion-packs.json";
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  function revert() {
    state.packsB = clone(state.packsA);
    state.dirty.clear();
    remergeB();
    clipOptions(); recipeOptions(); buildGallery();
    setClip(state.clipId, state.phase);
    renderTiming();
    selectRecipe($("wb-recipe").value);
    $("wb-save-note").textContent = "B 已还原为已保存数据。";
  }

  // ------------------------------------------------------------ dashboard
  const pct = (x) => `${(x * 100).toFixed(1)}%`;
  function barRow(label, value, max, cls = "", limit = null, text = null) {
    const w = max > 0 ? clamp(value / max, 0, 1) * 100 : 0;
    return `<div class="wb-bar"><span title="${esc(label)}">${esc(label)}</span><span class="wb-track"><i class="${cls}" style="width:${w.toFixed(1)}%"></i>${limit != null ? `<b class="limit" style="left:${clamp(limit / max, 0, 1) * 100}%" title="目标上限"></b>` : ""}</span><span>${esc(text ?? String(value))}</span></div>`;
  }
  function renderDashboard() {
    const box = $("wb-dashboard");
    if (!state.rendA || !state.rendB) return;
    const A = state.rendA.monotony(), B = state.rendB.monotony();
    const kpi = (label, a, b, note = "") => `<div class="wb-kpi"><dt>${esc(label)}</dt><dd>${esc(b)} <small>A ${esc(a)}${note ? " · " + esc(note) : ""}</small></dd></div>`;
    const topRows = B.combos.rows.slice(0, 6);
    const rawTop = B.timeline_combos.rows.slice(0, 3);
    const famKeys = [...new Set([...Object.keys(A.families), ...Object.keys(B.families)])].sort();
    const famMax = Math.max(1, ...famKeys.map((k) => Math.max(A.families[k] || 0, B.families[k] || 0)));
    const stopsB = B.hitstops;
    box.innerHTML = `
      <dl class="wb-kpis">
        ${kpi("最常见节奏占比", pct(A.combos.share), pct(B.combos.share), "目标 < 35%")}
        ${kpi("原时间轴最常见占比", pct(A.timeline_combos.share), pct(B.timeline_combos.share), "Python 节拍")}
        ${kpi("最多同时动作", A.max_simultaneous, B.max_simultaneous)}
        ${kpi("清晰焦点帧", A.clear_focus_pct + "%", B.clear_focus_pct + "%")}
        ${kpi("可见顿帧（≥2 帧）", `${A.hitstop_visible}/${A.hitstops.length}`, `${B.hitstop_visible}/${B.hitstops.length}`)}
        ${kpi("弹道家族种类", A.family_variety, B.family_variety)}
        ${kpi("击倒 / 大招 / 连锁", `${A.kos}/${A.ults}/${A.chains}`, `${B.kos}/${B.ults}/${B.chains}`)}
        ${kpi("主动作数", A.actions, B.actions)}
      </dl>
      <div><h3>节奏组合分布（B，蓄力/出手/收招，0.05s 取整）</h3><div class="wb-bars">
        ${barRow("A 最常见", A.combos.share, 1, "", 0.35, pct(A.combos.share))}
        ${barRow("B 最常见", B.combos.share, 1, "b", 0.35, pct(B.combos.share))}
        ${topRows.map(([key, n]) => barRow(key, n, B.actions, "b", null, `${n} · ${pct(n / Math.max(1, B.actions))}`)).join("")}
      </div><p class="wb-note">原时间轴前三：${rawTop.map(([k, n]) => `<span class="wb-chip warn">${esc(k)} ×${n}</span>`).join("") || "—"}</p></div>
      <div><h3>弹道家族（A 绿 / B 橙）</h3><div class="wb-bars">
        ${famKeys.map((k) => barRow(k + " A", A.families[k] || 0, famMax) + barRow(k + " B", B.families[k] || 0, famMax, "b")).join("") || '<p class="wb-note">无</p>'}
      </div></div>
      <div><h3>顿帧（B，60fps 帧数）</h3><p>${stopsB.map((h) => `<span class="wb-chip ${h.frames60 >= 2 ? "ok" : "warn"}">${h.kind === "ko" ? "击倒" : h.kind === "ult" ? "大招" : "重击"} ${h.at.toFixed(2)}s · ${h.frames60} 帧</span>`).join("") || '<span class="wb-note">本场没有顿帧（无击倒/大招/重击）。</span>'}</p></div>`;
  }

  // ------------------------------------------------------------ wiring
  function wire() {
    for (const b of document.querySelectorAll("[data-source]")) b.addEventListener("click", () => setSource(b.dataset.source));
    for (const b of document.querySelectorAll("[data-editor]")) b.addEventListener("click", () => {
      state.editor = b.dataset.editor;
      for (const x of document.querySelectorAll("[data-editor]")) x.setAttribute("aria-selected", String(x === b));
      for (const panel of document.querySelectorAll("[data-editor-panel]")) panel.hidden = panel.dataset.editorPanel !== state.editor;
    });
    $("wb-source-form").addEventListener("submit", loadScript);
    $("wb-play").addEventListener("click", () => (state.playing ? stop() : play()));
    $("wb-prev").addEventListener("click", () => { stop(); seek(state.p - FRAME); });
    $("wb-next").addEventListener("click", () => { stop(); seek(state.p + FRAME); });
    $("wb-seek").addEventListener("input", () => { stop(); seek(Number($("wb-seek").value)); });
    $("wb-speed").addEventListener("change", () => { state.speed = Number($("wb-speed").value) || 1; });
    $("wb-zoom").addEventListener("input", drawTimeline);
    $("wb-solo").addEventListener("change", () => { $("wb-previews").classList.toggle("solo", $("wb-solo").checked); });
    $("wb-timeline").addEventListener("click", timelineClick);
    $("wb-clip").addEventListener("change", () => {
      const id = $("wb-clip").value;
      if (state.mergedB.clips[id]?.parts) state.partsClipId = id;
      setClip(id, null);
    });
    $("wb-parts-clip").addEventListener("change", () => { state.partsClipId = $("wb-parts-clip").value; state.partsRow = 0; renderParts(); });
    $("wb-parts").addEventListener("change", partsInput);
    $("wb-parts").addEventListener("click", (event) => {
      const remove = event.target.closest("[data-premove]");
      if (remove) return removePartKey(Number(remove.dataset.premove));
      const tr = event.target.closest("tr[data-row]");
      if (tr) { state.partsRow = Number(tr.dataset.row); for (const row of $("wb-parts").children) row.classList.toggle("selected", row === tr); }
    });
    $("wb-parts-add").addEventListener("click", addPartKey);
    $("wb-parts-new").addEventListener("click", newPartsTrack);
    $("wb-parts-copy").addEventListener("click", copyRoleParts);
    $("wb-g-cat").addEventListener("change", () => renderGalleryList());
    $("wb-g-search").addEventListener("input", () => renderGalleryList());
    $("wb-g-list").addEventListener("change", () => loadScript());
    $("wb-g-prev").addEventListener("click", () => stepGallery(-1));
    $("wb-g-next").addEventListener("click", () => stepGallery(1));
    $("wb-g-scene").addEventListener("change", () => { if ($("wb-g-list").value) loadScript(); });
    $("wb-phase").addEventListener("change", () => { state.phase = $("wb-phase").value; state.keyRow = 0; state.partsRow = 0; renderKeys(); renderParts(); });
    $("wb-keys").addEventListener("change", keyInput);
    $("wb-keys").addEventListener("click", (event) => {
      const remove = event.target.closest("[data-remove]");
      if (remove) return removeKey(Number(remove.dataset.remove));
      const tr = event.target.closest("tr[data-row]");
      if (tr) { state.keyRow = Number(tr.dataset.row); for (const row of $("wb-keys").children) row.classList.toggle("selected", row === tr); drawEasePlot(); drawPosePlot(); }
    });
    $("wb-add-key").addEventListener("click", addKey);
    $("wb-ease-preset").addEventListener("change", () => applyEasePreset($("wb-ease-preset").value));
    $("wb-arche").addEventListener("change", renderTiming);
    $("wb-timing").addEventListener("change", timingInput);
    $("wb-weight").addEventListener("change", weightInput);
    $("wb-recipe").addEventListener("change", () => selectRecipe($("wb-recipe").value));
    $("wb-recipe-apply").addEventListener("click", applyRecipe);
    $("wb-save").addEventListener("click", save);
    $("wb-export").addEventListener("click", exportJson);
    $("wb-revert").addEventListener("click", revert);
    window.addEventListener("resize", drawTimeline);
    document.addEventListener("keydown", (event) => {
      if (event.target.closest("input, select, textarea")) return;
      if (event.key === " ") { event.preventDefault(); state.playing ? stop() : play(); }
      else if (event.key === "ArrowLeft") { stop(); seek(state.p - FRAME); }
      else if (event.key === "ArrowRight") { stop(); seek(state.p + FRAME); }
    });
    document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
  }

  async function init() {
    wire();
    const q = new URLSearchParams(location.search);
    if (q.get("sid")) { $("wb-sid").value = q.get("sid"); $("wb-round").value = q.get("round") || "1"; setSource("battle"); }
    else if (q.get("scenario")) setSource("scenario");
    try {
      const packs = await getJson("/api/animation/pack");
      state.packsA = { motion: packs.motion || {}, vfx: packs.vfx || {} };
      state.packsB = clone(state.packsA);
      state.mergedA = PB.mergePacks(state.packsA);
      state.mergedB = PB.mergePacks(state.packsB);
      clipOptions(); recipeOptions(); renderTiming();
      const nClips = Object.keys(state.mergedA.clips).length, nRecipes = Object.keys(state.mergedA.vfx.recipes).length;
      status(`动作数据：${Object.keys(packs.motion || {}).length} 个 motion 文件、${nClips} 个片段；${nRecipes} 个特效配方。选择来源后点「载入战斗脚本」。`);
    } catch (error) {
      status("动作数据读取失败：" + error.message, true);
      return;
    }
    await loadCatalogs();
    buildGallery();
    if (q.get("skill")) {
      const hit = state.gallery.find((g) => g.id === q.get("skill"));
      if (hit) { setSource("gallery"); $("wb-g-list").value = hit.id; }
    }
    if (q.get("species") && state.characters[q.get("species")]) $("wb-species").value = q.get("species");
    if (q.get("kind")) $("wb-kind").value = q.get("kind");
    if (q.get("scenario")) $("wb-scenario").value = q.get("scenario");
    drawTimeline();
    if (q.get("autoload") !== "0" && (q.get("sid") || q.get("scenario") || q.get("species") || (q.get("skill") && state.source === "gallery"))) loadScript();
  }
  window.WB = { state, seek, play, stop, selectAction, loadScript, save, setSource, stepGallery, renderParts };
  init();
})();
