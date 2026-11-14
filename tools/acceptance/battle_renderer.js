/* PokeTactics browser battle renderer (docs/58).
 *
 * Input: a battle script from /api/battle/script (authoritative event stream +
 * AnimationTimeline schedule + state snapshots) and the data packs from
 * /api/animation/pack (assets/motion, assets/vfx). Output: Canvas2D frames.
 *
 *   compile(script, pack)  -> plan      pure, deterministic
 *   frame(plan, t)         -> drawList  pure: same plan + t => same list
 *   paint(ctx, plan, list, images)      side effects only here
 *
 * Presentation retiming never moves an impact: HP snapshots stay registered to
 * the hits that caused them. Anticipation and recovery vary per role, body
 * weight, a stable per-unit offset and a per-action jitter; hitstop/slow-mo use
 * a global warp whose total length equals the timeline duration.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PokeBattle = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const W = 960, H = 640;
  const SPRITE_SCALE = 1.62;         // 56 px source cels read at ~106 px near the camera
  const SOURCE_PX = 56;
  const MOVE_TIME = 0.25;
  const DEATH_TIME = 0.75;
  const ENTRANCE = 0.45;
  const FRAME60 = 1 / 60;

  // ------------------------------------------------------------------ easing
  const c1 = 1.70158, c3 = c1 + 1;
  const EASE = {
    linear: (x) => x,
    step: (x) => (x < 1 ? 0 : 1),
    easeInQuad: (x) => x * x,
    easeOutQuad: (x) => 1 - (1 - x) * (1 - x),
    easeInOutQuad: (x) => (x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2),
    easeInCubic: (x) => x * x * x,
    easeOutCubic: (x) => 1 - Math.pow(1 - x, 3),
    easeInOutCubic: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
    easeOutBack: (x) => 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2),
    easeInBack: (x) => c3 * x * x * x - c1 * x * x,
    easeOutElastic: (x) => (x === 0 || x === 1 ? x : Math.pow(2, -10 * x) * Math.sin((x * 10 - 0.75) * (2 * Math.PI / 3)) + 1),
    easeOutBounce: (x) => {
      const n1 = 7.5625, d1 = 2.75;
      if (x < 1 / d1) return n1 * x * x;
      if (x < 2 / d1) return n1 * (x -= 1.5 / d1) * x + 0.75;
      if (x < 2.5 / d1) return n1 * (x -= 2.25 / d1) * x + 0.9375;
      return n1 * (x -= 2.625 / d1) * x + 0.984375;
    },
    easeOutExpo: (x) => (x === 1 ? 1 : 1 - Math.pow(2, -10 * x)),
    easeInExpo: (x) => (x === 0 ? 0 : Math.pow(2, 10 * x - 10)),
  };
  const ease = (name, x) => (EASE[name] || EASE.linear)(clamp01(x));
  const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);
  const clamp = (x, lo, hi) => (x < lo ? lo : x > hi ? hi : x);
  const lerp = (a, b, k) => a + (b - a) * k;
  const round3 = (x) => Math.round(x * 1000) / 1000;

  // ------------------------------------------------------------- determinism
  function hash() {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < arguments.length; i++) {
      let v = arguments[i];
      if (typeof v === "string") {
        for (let j = 0; j < v.length; j++) { h ^= v.charCodeAt(j); h = Math.imul(h, 16777619) >>> 0; }
        continue;
      }
      v = Math.round(Number(v) * 1000) | 0;
      for (let k = 0; k < 4; k++) { h ^= (v >>> (k * 8)) & 255; h = Math.imul(h, 16777619) >>> 0; }
    }
    h ^= h >>> 15; h = Math.imul(h, 2246822507) >>> 0; h ^= h >>> 13; h = Math.imul(h, 3266489909) >>> 0; h ^= h >>> 16;
    return h >>> 0;
  }
  const rand = function () { return hash.apply(null, arguments) / 4294967296; };

  // --------------------------------------------------------- track sampling
  /** Portable sampler: exactly esp32_runtime.animation.sample_track for linear
   *  keys (Python round = ties-to-even), applied to the 7-field projection. */
  function roundHalfEven(x) {
    const r = Math.round(x);
    return (Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r) || 0;  // never -0
  }
  function samplePortable(keys, progress) {
    if (progress <= keys[0][0]) return keys[0].slice(1, 7);
    const last = keys[keys.length - 1];
    if (progress >= last[0]) return last.slice(1, 7);
    for (let i = 0; i < keys.length - 1; i++) {
      const a = keys[i], b = keys[i + 1];
      if (a[0] <= progress && progress < b[0]) {
        const mix = (progress - a[0]) / (b[0] - a[0]);
        const out = [];
        for (let f = 1; f < 6; f++) out.push(roundHalfEven(a[f] + (b[f] - a[f]) * mix));
        out.push(a[6]);
        return out;
      }
    }
    return last.slice(1, 7);
  }
  /** Render sampler: same keys, eased per segment (key[7]), sub-pixel. */
  function sampleTrack(keys, progress) {
    const pose = { dx: 0, dy: 0, angle: 0, sx: 1, sy: 1, visible: 1 };
    if (!keys || !keys.length) return pose;
    let a = keys[0], b = keys[0], mix = 0;
    if (progress <= keys[0][0]) a = b = keys[0];
    else if (progress >= keys[keys.length - 1][0]) a = b = keys[keys.length - 1];
    else {
      for (let i = 0; i < keys.length - 1; i++) {
        if (keys[i][0] <= progress && progress < keys[i + 1][0]) {
          a = keys[i]; b = keys[i + 1];
          mix = ease(a[7] || "linear", (progress - a[0]) / (b[0] - a[0]));
          break;
        }
      }
    }
    pose.dx = lerp(a[1], b[1], mix); pose.dy = lerp(a[2], b[2], mix); pose.angle = lerp(a[3], b[3], mix);
    pose.sx = lerp(a[4], b[4], mix) / 100; pose.sy = lerp(a[5], b[5], mix) / 100; pose.visible = a[6];
    return pose;
  }
  function addPose(a, b, k = 1) {
    a.dx += b.dx * k; a.dy += b.dy * k; a.angle += b.angle * k;
    a.sx *= 1 + (b.sx - 1) * k; a.sy *= 1 + (b.sy - 1) * k;
    if (!b.visible && k >= 1) a.visible = 0;
    return a;
  }

  // ------------------------------------------------------------------ packs
  const FALLBACK_TIMING = {
    melee: { anticipation: .2, recover: .22, cast_anticipation: .4, cast_recover: .3, weight: .35, dash_speed: 950, offset_range: .06, idle_period: 1.2 },
    ranged: { anticipation: .16, recover: .16, cast_anticipation: .38, cast_recover: .26, weight: .25, dash_speed: 900, offset_range: .05, idle_period: 1.6 },
    support: { anticipation: .24, recover: .2, cast_anticipation: .46, cast_recover: .32, weight: .2, dash_speed: 800, offset_range: .07, idle_period: 1.4 },
    tank: { anticipation: .3, recover: .3, cast_anticipation: .52, cast_recover: .36, weight: .8, dash_speed: 650, offset_range: .06, idle_period: 2.2 },
  };
  const K = (at, dx, dy, an, sx, sy, v, e) => [at, dx, dy, an, sx, sy, v === undefined ? 1 : v, e || "easeInOutQuad"];
  const FALLBACK_CLIPS = {
    "fb.idle": { slot: "idle", period: 1.6, phases: { loop: [K(0, 0, 0, 0, 100, 100), K(.5, 0, -2, 0, 97, 104), K(1, 0, 0, 0, 100, 100)] } },
    "fb.walk": { slot: "walk", period: .36, phases: { loop: [K(0, 0, 0, 0, 100, 100), K(.25, 0, -6, -4, 95, 107), K(.5, 0, 0, 0, 107, 93), K(.75, 0, -6, 4, 95, 107), K(1, 0, 0, 0, 100, 100)] } },
    "fb.melee": { slot: "attack_melee", phases: {
      anticipation: [K(0, 0, 0, 0, 100, 100, 1, "easeOutCubic"), K(1, -11, 4, -14, 114, 86)],
      dash: [K(0, -11, 4, -14, 114, 86, 1, "easeInQuad"), K(1, 6, -2, 14, 86, 116)],
      contact: [K(0, 6, -2, 14, 86, 116, 1, "easeOutBack"), K(.3, 10, 1, 18, 120, 84), K(1, 4, 0, 6, 104, 97)],
      recover: [K(0, 4, 0, 6, 104, 97), K(1, 0, 0, 0, 100, 100)] } },
    "fb.ranged": { slot: "attack_ranged", phases: {
      anticipation: [K(0, 0, 0, 0, 100, 100, 1, "easeOutCubic"), K(1, -7, 2, -9, 110, 92, 1, "easeOutExpo")],
      release: [K(0, -7, 2, -9, 110, 92, 1, "easeOutExpo"), K(.25, 8, -1, 8, 90, 112), K(1, -6, 0, -5, 104, 97)],
      recover: [K(0, -6, 0, -5, 104, 97, 1, "easeOutBack"), K(1, 0, 0, 0, 100, 100)] } },
    "fb.cast": { slot: "cast", phases: {
      anticipation: [K(0, 0, 0, 0, 100, 100), K(1, -2, -11, -3, 89, 115, 1, "easeOutExpo")],
      release: [K(0, -2, -11, -3, 89, 115, 1, "easeOutExpo"), K(.3, 4, 3, 4, 118, 86), K(1, 0, 0, 0, 104, 97)],
      recover: [K(0, 0, 0, 0, 104, 97, 1, "easeOutBack"), K(1, 0, 0, 0, 100, 100)] } },
    "fb.hit": { slot: "hit", phases: { react: [K(0, 0, 0, 0, 100, 100, 1, "easeOutExpo"), K(.18, -8, 0, -10, 88, 112), K(.55, -4, 0, -3, 106, 95, 1, "easeOutBack"), K(1, 0, 0, 0, 100, 100)] } },
    "fb.ko": { slot: "ko", phases: { fall: [K(0, 0, 0, 0, 100, 100), K(.3, -4, -6, -10, 92, 110, 1, "easeInQuad"), K(1, -10, 12, -80, 112, 60, 0)] } },
    "fb.victory": { slot: "victory", period: .6, phases: { loop: [K(0, 0, 0, 0, 100, 100, 1, "easeOutQuad"), K(.4, 0, -10, 0, 94, 108, 1, "easeInQuad"), K(1, 0, 0, 0, 100, 100)] } },
  };
  const FALLBACK_SLOTS = { idle: "fb.idle", walk: "fb.walk", attack_melee: "fb.melee", attack_ranged: "fb.ranged", cast: "fb.cast", hit: "fb.hit", ko: "fb.ko", victory: "fb.victory" };
  const TYPE_COLORS = {
    NORMAL: ["#fffbe8", "#f4ecd0", "#d8cfae", "#8c8468"], FIRE: ["#fff6c4", "#ffc35a", "#ff7a2e", "#b8321a"],
    WATER: ["#effcff", "#9fe3ff", "#3fa7f0", "#1d5fa8"], ELECTRIC: ["#ffffff", "#fff27a", "#ffd21f", "#c08a00"],
    GRASS: ["#f4ffd8", "#b6f07a", "#58c24a", "#2c7a32"], ICE: ["#ffffff", "#d8f8ff", "#8fe0f5", "#4a9ec4"],
    FIGHTING: ["#fff0e0", "#ffb08a", "#e0623e", "#8c2c1e"], POISON: ["#f8e8ff", "#dba6ff", "#a85ae0", "#5e2a8c"],
    GROUND: ["#fff4dc", "#e8c98a", "#bf9550", "#6e5028"], FLYING: ["#ffffff", "#e2ecff", "#a8c2f5", "#5c78b8"],
    PSYCHIC: ["#fff0fa", "#ffaee0", "#f05aa8", "#9a2a6a"], BUG: ["#f8ffd8", "#d6ec7a", "#9ac23a", "#5a7a1c"],
    ROCK: ["#f6f0e0", "#d8c8a0", "#a8906a", "#5e4e36"], GHOST: ["#f4ecff", "#c4aef5", "#7e62c8", "#3e2c78"],
    DRAGON: ["#f0ecff", "#b8a8ff", "#6e58f0", "#38259c"], DARK: ["#f0e8e0", "#b0a090", "#6a5a50", "#2a2220"],
    STEEL: ["#ffffff", "#e0e6ee", "#a8b4c4", "#5c6878"], FAIRY: ["#fff4fc", "#ffd0f0", "#f59ad8", "#b0508e"],
    HEAL: ["#f4fff0", "#c4ffb8", "#6ee07a", "#2c9a48"], SHIELD: ["#ffffff", "#d8f6ff", "#8fd8f5", "#3c8cb8"],
    KO: ["#ffffff", "#fff2d0", "#ffcf6a", "#a8601e"],
  };
  const FALLBACK_VFX = {
    palettes: TYPE_COLORS,
    materials: {},
    projectiles: { straight: { size: 9, trail: .8 }, arc: { size: 10, arc: .45, trail: .5 }, homing: { size: 8, wobble: 26, trail: .9 }, beam: { width: 9 }, ground: { size: 12, trail: .6 }, volley: { size: 7, count: 3, stagger: .06, trail: .6 } },
    recipes: {
      generic_pop: { layers: [{ layer: "impact", shape: "ring", at: "impact", palette: "@type", size: 30, duration: .3 }] },
    },
    bindings: { archetype: {}, type_projectile: {}, category: {}, skill: {} },
    screen: { ult: { zoom: 1.08, dim: .42, slowmo: .45, slowmo_s: .3, banner_s: .9, hitstop: .1 }, ko: { zoom: 1.05, dim: .25, hitstop: .1, zoom_s: .55 }, crit: { hitstop: .066, threshold: .22 }, shake: { base: 1.5, per_weight: 9, decay: .3, max: 12 }, combo: { window: .9, follow: .35 } },
  };

  /** Merge pack files (alphabetical, later wins) into one lookup structure. */
  function mergePacks(packs) {
    const out = { clips: { ...FALLBACK_CLIPS }, archetypes: {}, species: {}, vfx: JSON.parse(JSON.stringify(FALLBACK_VFX)) };
    const motion = (packs && packs.motion) || {};
    for (const name of Object.keys(motion).sort()) {
      const pack = motion[name] || {};
      Object.assign(out.clips, pack.clips || {});
      for (const [k, v] of Object.entries(pack.archetypes || {})) out.archetypes[k] = mergeRow(out.archetypes[k], v);
      for (const [k, v] of Object.entries(pack.species || {})) out.species[k] = mergeRow(out.species[k], v);
    }
    const vfx = (packs && packs.vfx) || {};
    for (const name of Object.keys(vfx).sort()) {
      const pack = vfx[name] || {};
      for (const group of ["palettes", "materials", "projectiles", "recipes", "screen"]) Object.assign(out.vfx[group], pack[group] || {});
      for (const [group, rows] of Object.entries(pack.bindings || {})) out.vfx.bindings[group] = { ...(out.vfx.bindings[group] || {}), ...rows };
    }
    return out;
  }
  function mergeRow(a, b) {
    if (!a) return JSON.parse(JSON.stringify(b));
    return { ...a, ...b, clips: { ...(a.clips || {}), ...(b.clips || {}) }, timing: { ...(a.timing || {}), ...(b.timing || {}) } };
  }

  // --------------------------------------------------------------- geometry
  const BOARD = { top: 150, bottom: 628, topHalf: 300, bottomHalf: 474 };
  const depthCurve = (u) => u * (0.74 + 0.26 * u);
  function rowEdgeY(r, rows) { return lerp(BOARD.top, BOARD.bottom, depthCurve(r / rows)); }
  function rowHalf(r, rows) { return lerp(BOARD.topHalf, BOARD.bottomHalf, depthCurve(r / rows)); }
  /** Continuous cell position (col,row may be fractional) -> foot point + depth scale. */
  function project(col, row, rows = 6, cols = 6) {
    const r = row + 0.5;
    const y = rowEdgeY(r, rows);
    const half = rowHalf(r, rows);
    const x = W / 2 + ((col + 0.5) / cols - 0.5) * half * 2;
    const scale = 0.76 + 0.36 * depthCurve(r / rows);
    return { x, y: y + 14 * scale, scale };
  }
  function cellCorner(col, row, rows = 6, cols = 6) {
    const half = rowHalf(row, rows);
    return [W / 2 + (col / cols - 0.5) * half * 2, rowEdgeY(row, rows)];
  }

  // ------------------------------------------------------------------ labels
  const STATUS_LOOK = {
    burn: ["灼", "#ff964c"], poison: ["毒", "#cd99f4"], paralysis: ["麻", "#fee166"], freeze: ["冻", "#abeefa"],
    sleep: ["眠", "#adb8f9"], flinch: ["晕", "#fddd81"], root: ["缚", "#98d866"], vulnerability: ["破", "#ffad7e"],
    chill: ["寒", "#85dffa"], healing_block: ["封", "#ff8c79"], taunt: ["嘲", "#ffac6d"], thorns: ["刺", "#dfaaf9"],
    guard: ["护", "#aae2f9"], shield: ["盾", "#93e7f9"], wet: ["湿", "#8ee7f0"], tempo: ["拍", "#ffcd74"],
    offense_buff: ["鼓", "#f9b970"], physical_buff: ["力", "#ffd077"], physical_weaken: ["慑", "#cda4ec"],
    weaken: ["慑", "#cda4ec"], lightscreen: ["光", "#8be1f1"], reflect: ["壁", "#9fd9f2"], sworddance: ["攻", "#ffc05b"],
    ward_charge: ["蓄", "#ffcd6f"], weather_speed: ["疾", "#bde299"],
  };
  const STATUS_PRIORITY = ["freeze", "sleep", "flinch", "paralysis", "root", "chill", "healing_block", "taunt",
    "vulnerability", "weaken", "physical_weaken", "shield", "burn", "poison", "guard", "thorns", "wet", "offense_buff", "tempo"];
  const SUB_LABEL = {
    knockback: "击退", pull: "拉拽", guard: "守护", energy: "充能", energy_drain: "夺能", cleanse: "净化", taunt: "嘲讽",
    thorns: "反伤", thorn_hit: "反伤", flinch: "畏缩", root: "束缚", vulnerability: "破防", drain: "吸取",
    tempo: "节拍", empowered_hit: "强化一击", offense_buff: "鼓舞", weaken: "威慑", wet: "潮湿", heal: "滋养",
    status: "异常", shield: "护盾", reaction: "反应", conduct: "导电", bloom: "滋养", chain: "连锁", breach: "突破",
    place: "布阵", physical_buff: "蓄力", physical_weaken: "压制", rescue: "救援", execute: "处决", pierce: "贯穿",
  };
  const KEY_LABEL = {
    bond_combo: "羁绊·连携", bond_inspiration: "羁绊·鼓舞", bond_guard: "羁绊·守护", bond_frostline: "羁绊·冰线",
    bond_spirit: "羁绊·灵魂", bond_mindsong: "羁绊·心歌", bond_dragon_pressure: "羁绊·龙压", bond_erosion: "羁绊·侵蚀",
    element_wet: "潮湿", element_bloom: "水草滋养", element_conduct: "水电导流", element_burst: "元素爆发",
    arena_weather: "天气", healing_block: "封疗", healing_prevented: "封疗", guard: "战术守护",
  };
  const EFFECT_KIND = {
    damage: ["✦", "#ff8a6a"], shield: ["⬡", "#8fe8ff"], heal: ["✚", "#7dff8a"], energy: ["⚡", "#ffe066"],
    buff: ["▲", "#ffb85c"], debuff: ["▼", "#d6a4ff"], move: ["➜", "#f0f4e8"], summon: ["✧", "#ffd86b"],
  };
  const KNOWN_KINDS = new Set(["deploy", "unit_state", "move", "attack", "cast", "status", "die", "regen", "end",
    "skill_effect", "combo_effect", "field_effect", "partner_effect", "tactical_effect", "arena_heal", "combo", "miss", "sash"]);
  const WEATHER_ZH = { rain: "雨天", sun: "晴天", sand: "沙暴", hail: "冰雹" };

  // ------------------------------------------------------------------ compile
  function bsearchLast(rows, t, key = 0) {
    let lo = 0, hi = rows.length - 1, ans = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (rows[mid][key] <= t + 1e-9) { ans = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return ans;
  }

  function archetypeOf(unit) {
    if (unit.role === "defense") return "tank";
    if (unit.role === "support") return "support";
    return unit.melee ? "melee" : "ranged";
  }

  function compile(script, packInput) {
    const pack = packInput && packInput.clips ? packInput : mergePacks(packInput);
    const rows = script.arena?.rows || 6, cols = script.arena?.cols || 6;
    const duration = Number(script.clock?.duration) || 0;
    const units = {}, order = [];
    for (const raw of script.units || []) {
      const arche = archetypeOf(raw);
      const archRow = pack.archetypes[arche] || {};
      const speciesRow = pack.species[String(raw.sid)] || {};
      const timing = { ...FALLBACK_TIMING[arche], ...(archRow.timing || {}), ...(speciesRow.timing || {}) };
      const clips = {};
      for (const slot of Object.keys(FALLBACK_SLOTS)) {
        const id = (speciesRow.clips || {})[slot] || (archRow.clips || {})[slot] || FALLBACK_SLOTS[slot];
        clips[slot] = pack.clips[id] || FALLBACK_CLIPS[FALLBACK_SLOTS[slot]];
        clips[slot + "_id"] = pack.clips[id] ? id : FALLBACK_SLOTS[slot];
      }
      const weight = clamp(Number(timing.weight) || 0.4, 0, 1);
      const offset = (rand("unit", raw.idx, raw.sid) - 0.5) * 2 * (timing.offset_range ?? 0.06);
      const unit = {
        ...raw, arche, timing, clips, weight, offset,
        phase: rand("phase", raw.idx, raw.sid),
        idlePeriod: (clips.idle.period || timing.idle_period || 1.6) * (0.92 + 0.16 * rand("period", raw.idx)),
        type: (raw.types && raw.types[0]) || "NORMAL",
        positions: (script.positions || {})[raw.idx] || [[0, raw.pos[0], raw.pos[1], "deploy"]],
        states: (script.states || {})[raw.idx] || [[0, raw.max_hp, 0, 0]],
        statuses: [], hits: [], actions: [], numbers: [], death: null, entrance: 0.03 * (order.length % 6) + (raw.team ? 0 : 0.08),
      };
      units[raw.idx] = unit;
      order.push(raw.idx);
    }
    for (const row of script.statuses || []) if (units[row.unit]) units[row.unit].statuses.push(row);
    for (const [t, idx] of script.deaths || []) if (units[idx]) units[idx].death = { t };
    const terrain = script.arena && script.arena.terrain;
    const plan = { script, pack, units, order, rows, cols, duration, actions: [], hits: [], numbers: [], pops: [],
      terrainCells: terrain && Array.isArray(terrain.cells) ? terrain.cells.filter((c) => Array.isArray(c) && c.length >= 2) : [],
      terrainColor: terrainColor(terrain && terrain.id),
      chains: [], decals: [], cameras: [], banners: [], warp: null, weather: script.weather || [[0, null]] };
    const unitAt = (idx, t) => unitFoot(plan, units[idx], t);

    // ---- actions: retime anticipation/recovery around the fixed impact
    const rawActions = (script.actions || []).slice().sort((a, b) => a.impact - b.impact || a.i - b.i);
    for (const raw of rawActions) {
      const actor = units[raw.actor], target = units[raw.target];
      if (!actor || !target) continue;
      const skill = raw.skill || null;
      const targeting = skill?.targeting || "enemy";
      const supportive = raw.kind === "cast" && (targeting === "ally" || targeting === "self" || actor.team === target.team);
      const type = (skill && skill.type) || actor.type;
      const isCast = raw.kind === "cast";
      const arche = actor.arche;
      const melee = !raw.secondary && !raw.terrain && !supportive && !isCast && (actor.melee || arche === "tank" && actor.range <= 1)
        || (isCast && !supportive && actor.melee && raw.actor !== raw.target);
      const slot = melee ? "attack_melee" : isCast ? "cast" : "attack_ranged";
      const recipeId = pickRecipe(pack, { raw, skill, arche, supportive, melee, isCast });
      const family = pickFamily(pack, { type, recipeId, skill, melee, supportive });
      const a = {
        i: raw.i, kind: raw.kind, actor: raw.actor, target: raw.target, secondary: !!raw.secondary, terrain: !!raw.terrain,
        type, skill, supportive, melee, slot, recipe: recipeId, family, isCast, ult: isCast && !!skill?.native,
        damage: raw.damage || 0, eff: raw.eff, impact: raw.impact, tl: { start: raw.start, release: raw.release, end: raw.end },
        from: raw.from, to: raw.to, ko: false, crit: false, weight: actor.weight,
      };
      if (a.secondary || a.terrain) {
        a.start = a.release = a.impact; a.end = a.impact; a.anticipation = 0; a.travel = 0; a.recover = 0;
      } else {
        const from = project(raw.from[0], raw.from[1], rows, cols), to = project(raw.to[0], raw.to[1], rows, cols);
        const dist = Math.hypot(to.x - from.x, to.y - from.y);
        const t = actor.timing;
        let travel;
        if (melee) travel = clamp(Math.max(0, dist - 70) / (t.dash_speed || 900), 0.07, 0.22);
        else if (supportive && targeting === "self") travel = 0.12;
        else if (family === "beam") travel = 0.12 + dist / 4200;
        else if (family === "arc") travel = 0.24 + dist / 1700;
        else if (family === "homing") travel = 0.2 + dist / 1500;
        else if (family === "ground") travel = 0.14 + dist / 1000;
        else if (family === "volley") travel = 0.14 + dist / 1300;
        else travel = 0.1 + dist / 1250;
        travel = clamp(travel, 0.07, 0.48);
        const wf = 1 + 0.7 * (actor.weight - 0.4);
        const jitter = (rand("act", raw.i, raw.actor) - 0.5) * 0.07;
        let anticipation = (isCast ? t.cast_anticipation : t.anticipation) * wf + actor.offset + jitter;
        if (a.ult) anticipation += 0.1;
        let recover = (isCast ? t.cast_recover : t.recover) * (1 + 0.5 * (actor.weight - 0.4)) + actor.offset * 0.6
          + (rand("rec", raw.i) - 0.5) * 0.06 + (melee ? 0.06 : 0);
        anticipation = Math.max(0.08, anticipation);
        recover = Math.max(0.08, recover);
        a.release = a.impact - travel;
        a.start = a.release - anticipation;
        a.end = a.impact + recover;
        a.anticipation = anticipation; a.travel = travel; a.recover = recover; a.dist = dist;
      }
      plan.actions.push(a);
    }
    // per-actor sequencing: never overlap an actor's own windows
    const byActor = {};
    for (const a of plan.actions) if (!a.secondary && !a.terrain) (byActor[a.actor] ||= []).push(a);
    for (const list of Object.values(byActor)) {
      list.sort((x, y) => x.impact - y.impact);
      let prev = null;
      for (const a of list) {
        const unit = units[a.actor];
        const floor = Math.max(0.3 + unit.entrance, prev ? prev.impact + 0.06 : 0);
        if (a.start < floor) {
          a.start = floor;
          if (a.release - a.start < 0.06) { a.release = Math.min(a.impact - 0.04, a.start + 0.06); }
          if (a.release < a.start) a.release = a.start;
        }
        if (prev && prev.end > a.start) prev.end = Math.max(prev.impact + 0.08, a.start);
        a.anticipation = a.release - a.start; a.travel = a.impact - a.release; a.recover = a.end - a.impact;
        prev = a;
      }
      for (const a of list) a.end = Math.min(a.end, unitDeathOr(units[a.actor], Infinity) + 0.01);
    }
    for (const a of plan.actions) unitsOf(units, a.actor)?.actions.push(a);

    // ---- hits / numbers from authoritative state snapshots
    const impactIndex = plan.actions.slice().sort((x, y) => x.impact - y.impact);
    const matchAction = (t, idx) => {
      let best = null;
      for (const a of impactIndex) {
        if (a.impact > t + 0.03) break;
        if (Math.abs(a.impact - t) > 0.03) continue;
        if (a.target === idx) return a;
        if (!best && units[a.actor] && units[a.actor].team !== units[idx].team) best = a;
      }
      return best;
    };
    let seq = 0;
    for (const idx of order) {
      const unit = units[idx];
      const states = unit.states;
      for (let k = 1; k < states.length; k++) {
        const [t, hp, , shield] = states[k], prev = states[k - 1];
        const drop = prev[1] - hp, gain = hp - prev[1], shieldGain = shield - prev[3];
        if (drop > 0) {
          const action = matchAction(t, idx);
          const ratio = drop / Math.max(1, unit.max_hp);
          const hit = { t, unit: idx, amount: drop, ratio, action: action ? action.i : null,
            from: action ? action.actor : null, type: action ? action.type : null, seq: seq++ };
          unit.hits.push(hit); plan.hits.push(hit);
          const eff = action && action.isCast ? Number(action.eff) : 1;
          const crit = ratio >= (pack.vfx.screen.crit?.threshold ?? 0.22);
          if (action && crit) action.crit = true;
          plan.numbers.push({ t, unit: idx, text: String(drop), kind: eff >= 1.5 ? "super" : eff > 0 && eff <= 0.75 ? "weak" : crit ? "crit" : "damage", size: ratio, seq: seq++ });
        } else if (gain > 0 && k > 0 && gain >= Math.max(3, unit.max_hp * 0.03)) {
          plan.numbers.push({ t, unit: idx, text: "+" + gain, kind: "heal", size: gain / unit.max_hp, seq: seq++ });
        }
        if (shieldGain > 0) plan.numbers.push({ t, unit: idx, text: "+" + shieldGain, kind: "shield", size: .1, seq: seq++ });
        else if (shieldGain < 0 && drop <= 0) plan.numbers.push({ t, unit: idx, text: "吸收" + (-shieldGain), kind: "absorb", size: .05, seq: seq++ });
      }
      if (unit.death) {
        const killer = impactIndex.filter((a) => a.target === idx && a.impact <= unit.death.t + 1e-6 && a.impact >= unit.death.t - 0.2).pop();
        unit.death.killer = killer ? killer.i : null;
        if (killer) killer.ko = true;
        unit.death.from = killer ? killer.actor : null;
      }
    }

    // ---- event pops, chains, decals, weather beats
    buildPops(plan);
    buildDecals(plan);
    buildWarp(plan);
    buildCameras(plan);
    plan.playbackDuration = duration;
    plan.unitAt = unitAt;
    return plan;
  }
  const unitsOf = (units, idx) => units[idx];
  const TERRAIN_COLORS = { highland: "#e8c98a", mana_spring: "#8fe0ff", brambles: "#7cc95a", sanctum: "#fff2a8", swamp: "#5aa08f", embers: "#ff8a4a" };
  function terrainColor(id) {
    if (!id) return "#e8d890";
    for (const [key, color] of Object.entries(TERRAIN_COLORS)) if (String(id).includes(key)) return color;
    return "#e8d890";
  }
  const unitDeathOr = (unit, fallback) => (unit && unit.death ? unit.death.t : fallback);

  function pickRecipe(pack, { raw, skill, arche, supportive, melee, isCast }) {
    const b = pack.vfx.bindings || {};
    const recipes = pack.vfx.recipes || {};
    const ok = (id) => (id && recipes[id] ? id : null);
    if (skill) {
      const byId = ok((b.skill || {})[skill.id]) || ok((b.skill || {})[skill.arch]);
      if (byId) return byId;
      const byCat = ok((b.category || {})[skill.category]);
      if (byCat && (isCast || !melee)) return byCat;
    }
    if (supportive) return ok((b.archetype || {}).support_cast) || ok("support_channel") || "generic_pop";
    if (isCast) return melee ? ok("combo_flurry") || ok((b.archetype || {}).cast) || "generic_pop" : ok((b.archetype || {}).cast) || "generic_pop";
    if (melee) return ok((b.archetype || {})[arche === "tank" ? "tank" : "melee"]) || "generic_pop";
    return ok((b.archetype || {})[arche === "tank" ? "ranged" : arche]) || ok((b.archetype || {}).ranged) || "generic_pop";
  }
  function pickFamily(pack, { type, recipeId, melee }) {
    if (melee) return "melee";
    const recipe = (pack.vfx.recipes || {})[recipeId];
    const layer = recipe && recipe.layers.find((l) => l.layer === "projectile");
    if (layer && layer.family && layer.family !== "@type") return layer.family;
    return (pack.vfx.bindings.type_projectile || {})[type] || "straight";
  }

  function buildPops(plan) {
    const { units, script } = plan;
    const trait = {};
    for (const u of script.units || []) if (u.trait) trait[u.trait.id] = u.trait.name;
    const linked = [];
    for (const row of script.events || []) {
      const [t, , kind] = row;
      const args = row.slice(3);
      let pop = null;
      if (kind === "skill_effect" || kind === "combo_effect" || kind === "field_effect") {
        const [src, tgt, key, sub, payload] = args;
        if (sub === "expire" || sub === "absorb" || sub === "side_hit" || sub === "heal" && kind === "skill_effect") {
          if (sub === "side_hit") plan.pops.push({ t, unit: tgt, from: src, text: "", kind: "ring", glyph: "", color: "#ffd9a0", seq: plan.pops.length });
          continue;
        }
        if (key === "arena_weather") continue;
        let text = KEY_LABEL[key] || (String(key).startsWith("trait_") ? trait[key] : null);
        const subText = SUB_LABEL[sub];
        if (kind === "skill_effect") text = subText || null;
        else if (text && subText && !KEY_LABEL[key]) text = text + "·" + subText;
        else if (!text) text = subText || null;
        if (!text) continue;
        const color = kind === "combo_effect" ? (String(key).startsWith("bond") ? "#ffe08a" : String(key).startsWith("element") ? "#9fe8ff" : "#ffc98a") : "#f2f0d8";
        pop = { t, unit: tgt != null ? tgt : src, from: src, text, kind: kind === "combo_effect" ? "combo" : "skill", glyph: kind === "combo_effect" ? "◆" : "", color, payload };
        if (kind === "combo_effect" || kind === "field_effect" && sub !== "expire") linked.push(pop);
      } else if (kind === "partner_effect") {
        const [src, tgt, partner, effect] = args;
        pop = { t, unit: tgt, from: src, text: "搭档·" + (SUB_LABEL[effect] || effect || ""), kind: "combo", glyph: "◆", color: "#ffe08a" };
        linked.push(pop);
      } else if (kind === "tactical_effect") {
        const [src, tgt, effect] = args;
        if (/^weather/.test(effect)) continue;
        pop = { t, unit: tgt, from: src, text: KEY_LABEL[effect] || SUB_LABEL[effect] || "战术", kind: "combo", glyph: "◇", color: "#c8f0a8" };
        linked.push(pop);
      } else if (kind === "miss") {
        pop = { t, unit: args[1], from: args[0], text: "闪避", kind: "miss", glyph: "", color: "#d8e0e8" };
      } else if (kind === "sash") {
        pop = { t, unit: args[0], text: "气势披带", kind: "combo", glyph: "✦", color: "#ffd86b" };
      } else if (kind === "status" && args[2] === "apply") {
        const name = args[1] === "para" ? "paralysis" : args[1];
        const look = STATUS_LOOK[name];
        pop = { t, unit: args[0], text: look ? statusName(name) : String(name), kind: "status", glyph: look ? look[0] : "", color: look ? look[1] : "#ddd" };
      } else if (kind === "effect") {
        const [src, tgt, effectId, payload] = args;
        const p = payload && typeof payload === "object" ? payload : {};
        const look = EFFECT_KIND[p.kind] || ["✧", "#f4eecb"];
        const value = p.value != null && p.value !== "" && p.value !== 0 && p.kind !== "move" ? " " + (typeof p.value === "number" && p.value > 0 && ["heal", "shield", "energy"].includes(p.kind) ? "+" : "") + p.value : "";
        // source/target may be -1 for team-wide effects (冲锋号, 先锋壁垒 …):
        // those pop once over the whole team instead of a single body.
        const unit = units[tgt] ? tgt : units[src] ? src : null;
        const team = unit == null && (p.team === 0 || p.team === 1) ? p.team : null;
        pop = { t, unit, team, from: units[src] ? src : null, text: (p.label || humanize(effectId)) + value, kind: team != null ? "team" : "effect",
          glyph: look[0], color: look[1], camera: p.camera === "focus", source: p.source || null };
        linked.push(pop);
      } else if (!KNOWN_KINDS.has(kind)) {
        // Unknown future event: a small generic pop on its target or source.
        const src = Number.isInteger(args[0]) && units[args[0]] ? args[0] : null;
        const tgt = Number.isInteger(args[1]) && units[args[1]] ? args[1] : src;
        if (tgt == null) continue;
        pop = { t, unit: tgt, from: src, text: humanize(kind), kind: "unknown", glyph: "✧", color: "#e8e4c8" };
      }
      if (pop && (units[pop.unit] || pop.team != null)) { pop.seq = plan.pops.length; plan.pops.push(pop); }
    }
    // chains: linked effects that fire close together get staged one after another
    const window = plan.pack.vfx.screen.combo?.window ?? 0.9;
    linked.sort((a, b) => a.t - b.t || a.seq - b.seq);
    let group = [];
    const flush = () => {
      const valid = group.filter((p) => units[p.unit]);
      if (valid.length >= 2) {
        const chain = { t0: valid[0].t, beats: [], units: [] };
        valid.forEach((p, k) => {
          p.delay = Math.min(0.6, k * 0.13);
          chain.beats.push({ t: p.t + p.delay, unit: p.unit, from: p.from, color: p.color });
          if (!chain.units.includes(p.unit)) chain.units.push(p.unit);
        });
        chain.t1 = chain.beats[chain.beats.length - 1].t + 0.45;
        plan.chains.push(chain);
      }
      group = [];
    };
    for (const p of linked) {
      if (group.length && p.t - group[0].t > window) flush();
      group.push(p);
    }
    flush();
    // per-unit stacking so simultaneous labels never overprint
    const lastByUnit = {};
    for (const p of plan.pops.slice().sort((a, b) => (a.t + (a.delay || 0)) - (b.t + (b.delay || 0)))) {
      const at = p.t + (p.delay || 0);
      const prev = lastByUnit[p.unit];
      p.lane = prev && at - prev.at < 0.5 ? (prev.lane + 1) % 3 : 0;
      lastByUnit[p.unit] = { at, lane: p.lane };
    }
    // Same-instant packets on one unit (side hits, multi-state rows) read as
    // one number; the strongest effectiveness wins the colour.
    const rank = { super: 4, crit: 3, damage: 2, weak: 1 };
    const merged = [];
    for (const n of plan.numbers.sort((a, b) => a.t - b.t || a.seq - b.seq)) {
      const prev = merged.find((m) => m.unit === n.unit && Math.abs(m.t - n.t) < 0.03 && (m.kind in rank) === (n.kind in rank) && m.kind !== "absorb" && n.kind !== "absorb" && m.kind !== "shield" && n.kind !== "shield");
      if (prev && n.kind in rank) {
        prev.text = String(Number(prev.text) + Number(n.text)); prev.size += n.size;
        if (rank[n.kind] > rank[prev.kind]) prev.kind = n.kind;
      } else if (prev && n.kind === "heal") {
        prev.text = "+" + (Number(prev.text.slice(1)) + Number(n.text.slice(1)));
      } else merged.push(n);
    }
    plan.numbers = merged;
    // de-duplicate repeated labels on one unit within a short window
    const seenLabel = {};
    plan.pops = plan.pops.filter((p) => {
      const key = p.unit + ":" + p.text;
      if (p.kind !== "ring" && seenLabel[key] != null && p.t - seenLabel[key] < 0.6) return false;
      seenLabel[key] = p.t;
      return true;
    });
    const numLast = {};
    for (const n of plan.numbers) {
      const prev = numLast[n.unit];
      n.lane = prev && n.t - prev.t < 0.45 ? (prev.lane + 1) % 4 : 0;
      numLast[n.unit] = n;
    }
  }
  const statusName = (k) => ({ burn: "灼伤", poison: "中毒", paralysis: "麻痹", freeze: "冰冻", sleep: "睡眠", flinch: "畏缩" }[k] || STATUS_LOOK[k]?.[0] || k);
  const humanize = (s) => String(s || "效果").replace(/^arena_|^trait_|^bond_/, "").replace(/_/g, " ").slice(0, 14);

  function buildDecals(plan) {
    // Fields placed by skills (rock spikes, roots, terrain) stay on the ground
    // until their authoritative expiry event.
    const open = [];
    for (const row of plan.script.events || []) {
      const [t, , kind] = row;
      if (kind !== "field_effect") continue;
      const [src, tgt, key, sub, payload] = row.slice(3);
      const cells = (payload && Array.isArray(payload.cells) && payload.cells.length) ? payload.cells
        : payload && Array.isArray(payload.target_pos) ? [payload.target_pos] : [];
      if (sub === "expire" || sub === "remove" || sub === "clear") {
        for (const d of open) if (d.key === key && d.end == null && (tgt == null || d.unit === tgt || !d.unit)) d.end = t;
        continue;
      }
      const owner = plan.units[src];
      const type = /rock|spike|stone/.test(key) ? "ROCK" : /root|vine|grass/.test(key) ? "GRASS" : owner ? owner.type : "NORMAL";
      const shape = type === "ROCK" ? "spikes" : type === "GRASS" ? "vines" : type === "POISON" ? "puddle" : "ring_decal";
      for (const cell of cells) {
        const d = { t, key, unit: tgt, cell, type, shape, end: null, seed: hash(key, t, cell[0], cell[1]) };
        if (payload && typeof payload.duration === "number") d.end = t + payload.duration;
        open.push(d);
      }
    }
    for (const d of open) if (d.end == null || d.end > plan.duration) d.end = plan.duration;
    plan.decals = open;
  }

  /** Global warp: playback -> simulation time. Dwells (hitstop) and slow-mo
   *  windows are paid for by a bounded speed-up elsewhere; total length equals
   *  the timeline duration so the seek bar and team telemetry stay aligned. */
  function buildWarp(plan) {
    const screen = plan.pack.vfx.screen;
    const D = plan.duration;
    const candidates = [];
    const seenUlt = new Set();
    for (const a of plan.actions) {
      if (a.secondary) continue;
      if (a.ko) candidates.push({ at: a.impact, dwell: screen.ko?.hitstop ?? 0.1, slow: 0, prio: 3, kind: "ko", action: a.i });
      else if (a.ult && !seenUlt.has(a.actor)) {
        seenUlt.add(a.actor);
        candidates.push({ at: a.impact, dwell: screen.ult?.hitstop ?? 0.1, slow: screen.ult?.slowmo_s ?? 0.3, rate: screen.ult?.slowmo ?? 0.45, prio: 2, kind: "ult", action: a.i });
      } else if (a.crit || a.ult) candidates.push({ at: a.impact, dwell: screen.crit?.hitstop ?? 0.066, slow: 0, prio: 1, kind: "crit", action: a.i });
    }
    const maxSlope = 1.08;
    const budget = D > 0 ? D * (1 - 1 / maxSlope) : 0;
    candidates.sort((x, y) => y.prio - x.prio || x.at - y.at);
    const chosen = [];
    let used = 0;
    for (const c of candidates) {
      if (c.at < 0.5 || c.at > D - 0.3) continue;
      if (chosen.some((o) => Math.abs(o.at - c.at) < 0.35)) continue;
      const cost = c.dwell + (c.slow ? c.slow / c.rate - c.slow : 0);
      if (used + cost > budget) continue;
      used += cost;
      chosen.push(c);
    }
    chosen.sort((x, y) => x.at - y.at);
    plan.hitstops = chosen;
    // Fast-forward elsewhere so the total playback length equals D exactly.
    const slowSim = chosen.reduce((sum, c) => sum + (c.slow || 0), 0);
    const slowPlay = chosen.reduce((sum, c) => sum + (c.slow ? c.slow / c.rate : 0) + c.dwell, 0);
    const slope = chosen.length ? (D - slowSim) / Math.max(1e-6, D - slowPlay) : 1;
    // segments [p0, s0, rate]: playback p maps to s0 + (p - p0) * rate
    const segs = [];
    let p = 0, s = 0;
    const run = (until, rate) => {
      if (until <= s + 1e-9) return;
      segs.push([p, s, rate]);
      p += (until - s) / rate; s = until;
    };
    for (const c of chosen) {
      if (c.slow) run(c.at - c.slow, slope);
      if (c.slow) { run(c.at, c.rate); }
      else run(c.at, slope);
      segs.push([p, s, 0]);
      c.p0 = p; c.p1 = p + c.dwell;
      p += c.dwell;
    }
    segs.push([p, s, slope]);
    plan.warp = segs;
  }
  function toSim(plan, p) {
    const segs = plan.warp;
    if (!segs || segs.length < 2) return clamp(p, 0, plan.duration);
    let lo = 0, hi = segs.length - 1, idx = 0;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (segs[m][0] <= p) { idx = m; lo = m + 1; } else hi = m - 1; }
    const [p0, s0, rate] = segs[idx];
    return clamp(s0 + (p - p0) * rate, 0, plan.duration);
  }
  function toPlayback(plan, s) {
    const segs = plan.warp;
    if (!segs || segs.length < 2) return s;
    let ans = segs[0];
    for (const seg of segs) { if (seg[1] <= s + 1e-9 && seg[2] > 0) ans = seg; else if (seg[1] > s) break; }
    return ans[0] + (s - ans[1]) / (ans[2] || 1);
  }

  function buildCameras(plan) {
    const screen = plan.pack.vfx.screen;
    const cams = [];
    const ultSeen = new Set();
    for (const a of plan.actions) {
      if (a.secondary || a.terrain) continue;
      if (a.ult) {
        const last = plan.banners[plan.banners.length - 1];
        const gap = last ? a.start - last.t : 99;
        const banner = (!ultSeen.has(a.actor) && gap > 1.2) || gap > 4.5;
        ultSeen.add(a.actor);
        if (banner) plan.banners.push({ t: a.start, unit: a.actor, name: a.skill?.name || "", type: a.type, team: plan.units[a.actor].team, dur: screen.ult?.banner_s ?? 0.9 });
        cams.push({ t0: a.start, t1: a.impact + 0.3, kind: "ult", prio: 2, focus: [a.actor, a.target], zoom: banner ? (screen.ult?.zoom ?? 1.08) : 1.04, dim: banner ? (screen.ult?.dim ?? 0.4) : 0.22, dimFrom: a.release - 0.12, dimTo: a.impact + 0.22 });
      }
      if (a.ko) {
        const d = plan.units[a.target].death;
        cams.push({ t0: a.impact - 0.12, t1: (d ? d.t : a.impact) + (screen.ko?.zoom_s ?? 0.55), kind: "ko", prio: 3, focus: [a.target], zoom: screen.ko?.zoom ?? 1.05, dim: screen.ko?.dim ?? 0.25, dimFrom: a.impact - 0.05, dimTo: a.impact + 0.4 });
      }
    }
    for (const c of plan.chains) cams.push({ t0: c.t0 - 0.05, t1: c.t1, kind: "chain", prio: 1, focus: c.units, beats: c.beats, zoom: 1.035, dim: 0 });
    for (const p of plan.pops) if (p.camera) {
      const focus = p.team != null ? plan.order.filter((i) => plan.units[i].team === p.team) : [p.unit];
      cams.push({ t0: p.t - 0.05, t1: p.t + 0.6, kind: "focus", prio: 1, focus, zoom: p.team != null ? 1.03 : 1.06, dim: 0 });
    }
    plan.cameras = cams.sort((x, y) => x.t0 - y.t0);
  }

  // --------------------------------------------------------------- unit state
  function unitFoot(plan, unit, s) {
    const pos = unit.positions;
    const i = Math.max(0, bsearchLast(pos, s));
    const cur = pos[i];
    let col = cur[1], row = cur[2], moving = 0, how = cur[3], hidden = false;
    if (i > 0) {
      const prev = pos[i - 1];
      if (how === "blink") {
        const b = cur[4] || {};
        // the timeline emits the blink at landing; it vanished at departure
        if (s < cur[0] + 0.12) { const k = (s - cur[0]) / 0.12; moving = 1 - k; }
      } else {
        const dur = how === "forced" ? 0.2 : MOVE_TIME;
        const k = (s - cur[0]) / dur;
        if (k < 1) {
          const e = how === "forced" ? ease("easeOutCubic", k) : ease("easeInOutQuad", k);
          col = lerp(prev[1], cur[1], e); row = lerp(prev[2], cur[2], e); moving = how === "forced" ? 0 : Math.sin(Math.PI * k);
        }
      }
    }
    // blink departure: the next blink record makes the body vanish early
    const next = pos[i + 1];
    if (next && next[3] === "blink" && next[4] && s >= next[4].departure && s < next[0]) hidden = true;
    const p = project(col, row, plan.rows, plan.cols);
    p.moving = moving; p.how = how; p.hidden = hidden; p.col = col; p.row = row;
    return p;
  }
  function stateAt(unit, s) {
    const i = Math.max(0, bsearchLast(unit.states, s));
    const cur = unit.states[i];
    const prev = unit.states[Math.max(0, i - 1)];
    const age = s - cur[0];
    // chip: displayed health trails the authoritative value for a beat
    const chip = i > 0 && prev[1] > cur[1] && age < 0.55 ? lerp(prev[1], cur[1], ease("easeInQuad", clamp01((age - 0.15) / 0.4))) : cur[1];
    return { hp: cur[1], chip, energy: cur[2], shield: cur[3] };
  }
  function activeStatuses(unit, s) {
    const out = [];
    for (const st of unit.statuses) if (st.start <= s && s < st.end) out.push(st.kind);
    return out;
  }
  function clipPhase(clip, phase, k) {
    const keys = clip && clip.phases && clip.phases[phase];
    return keys ? sampleTrack(keys, clamp01(k)) : sampleTrack(null, 0);
  }

  /** Pose of one unit at sim time s: idle loop + action clip + dash + hits. */
  function unitPose(plan, unit, s, p) {
    const foot = unitFoot(plan, unit, s);
    const pose = { dx: 0, dy: 0, angle: 0, sx: 1, sy: 1, visible: 1 };
    const statuses = activeStatuses(unit, s);
    const frozen = statuses.includes("freeze");
    const asleep = statuses.includes("sleep");
    let facing = foot.x < W / 2 ? 1 : -1;
    let dash = null, acting = null, flash = 0, alpha = 1, dissolve = 0, ghosts = 0, glow = 0;
    // entrance drop
    const entry = (s - unit.entrance) / ENTRANCE;
    if (entry < 1) {
      const k = clamp01(entry);
      pose.dy -= (1 - ease("easeOutBounce", k)) * 34;
      alpha = clamp01(k * 3);
      if (k > 0.55 && k < 0.8) { pose.sx *= 1.12; pose.sy *= 0.9; }
    }
    // idle (breathing with per-unit phase); slows when asleep, stops when frozen
    const idleS = frozen ? Math.min(s, statusStart(unit, "freeze", s)) : s;
    const period = unit.idlePeriod * (asleep ? 1.8 : 1);
    const idleK = (((idleS / period) + unit.phase) % 1 + 1) % 1;
    let idleWeight = 1;
    // action
    for (const a of unit.actions) {
      if (a.secondary || a.terrain || s < a.start || s > a.end) continue;
      acting = a; break;
    }
    if (acting && !frozen) {
      const a = acting;
      idleWeight = 0.25;
      const tgt = plan.units[a.target];
      const tf = tgt ? unitFoot(plan, tgt, Math.min(s, a.impact)) : foot;
      if (Math.abs(tf.x - foot.x) > 4) facing = tf.x > foot.x ? 1 : -1;
      const clip = unit.clips[a.slot];
      let part;
      if (s < a.release) part = clipPhase(clip, "anticipation", (s - a.start) / Math.max(1e-3, a.release - a.start));
      else if (a.melee) {
        const contactHold = Math.min(0.07, a.recover * 0.4);
        if (s < a.impact) part = clipPhase(clip, "dash", (s - a.release) / Math.max(1e-3, a.impact - a.release));
        else if (s < a.impact + contactHold) part = clipPhase(clip, "contact", (s - a.impact) / contactHold * 0.5);
        else part = clipPhase(clip, "recover", (s - a.impact - contactHold) / Math.max(1e-3, a.end - a.impact - contactHold));
        // physical dash to contact and back
        const dir = { x: tf.x - foot.x, y: tf.y - foot.y };
        const len = Math.hypot(dir.x, dir.y) || 1;
        const reach = Math.max(0, len - 58 * foot.scale);
        let k = 0;
        if (s >= a.release && s < a.impact) k = ease("easeInQuad", (s - a.release) / Math.max(1e-3, a.impact - a.release));
        else if (s >= a.impact && s < a.impact + contactHold) k = 1;
        else if (s >= a.impact + contactHold) k = 1 - ease("easeInOutCubic", (s - a.impact - contactHold) / Math.max(1e-3, a.end - a.impact - contactHold));
        dash = { x: dir.x / len * reach * k, y: dir.y / len * reach * k - Math.sin(Math.PI * k) * (unit.arche === "tank" ? 18 : 8) * (s < a.impact ? 1 : 0) };
        ghosts = s >= a.release && s < a.impact + 0.04 ? 1 : 0;
      } else if (s < a.impact) {
        const span = a.impact - a.release;
        part = clipPhase(clip, "release", (s - a.release) / Math.max(1e-3, Math.min(span, 0.3)) * 0.6);
      } else part = clipPhase(clip, "recover", (s - a.impact) / Math.max(1e-3, a.end - a.impact));
      if (s < a.release && a.isCast) glow = clamp01((s - a.start) / Math.max(1e-3, a.release - a.start));
      const k = foot.scale * SPRITE_SCALE * 0.55;
      const dirX = Math.abs(tf.x - foot.x) > 4 ? Math.sign(tf.x - foot.x) : facing;
      pose.dx += part.dx * k * dirX; pose.dy += part.dy * k;
      pose.angle += part.angle * dirX; pose.sx *= part.sx; pose.sy *= part.sy;
    }
    const idle = clipPhase(unit.clips.idle, "loop", idleK);
    pose.dx += idle.dx * idleWeight * foot.scale * SPRITE_SCALE * 0.55;
    pose.dy += idle.dy * idleWeight * foot.scale * SPRITE_SCALE * 0.55;
    pose.angle += idle.angle * idleWeight;
    pose.sx *= 1 + (idle.sx - 1) * idleWeight; pose.sy *= 1 + (idle.sy - 1) * idleWeight;
    // walking hop
    if (foot.moving > 0 && !frozen) {
      const w = clipPhase(unit.clips.walk, "loop", (s / (unit.clips.walk.period || 0.36)) % 1);
      pose.dy += w.dy * foot.scale * 1.4; pose.angle += w.angle; pose.sx *= w.sx; pose.sy *= w.sy;
    }
    // hits: recoil + knockback away from the source + white flash
    for (const h of unit.hits) {
      const age = s - h.t;
      if (age < 0 || age > 0.42) continue;
      const clip = unit.clips.hit;
      const r = clipPhase(clip, "react", age / 0.42);
      let away = { x: 0, y: 0 };
      if (h.from != null && plan.units[h.from]) {
        const src = unitFoot(plan, plan.units[h.from], h.t);
        const dx = foot.x - src.x, dy = foot.y - src.y, len = Math.hypot(dx, dy) || 1;
        away = { x: dx / len, y: dy / len };
      }
      const push = (6 + 6 * clamp01(h.ratio * 4)) * (unit.weight > 0.7 ? 0.7 : 1);
      const kk = age < 0.07 ? ease("easeOutExpo", age / 0.07) : 1 - ease("easeInOutQuad", (age - 0.07) / 0.35);
      pose.dx += away.x * push * kk - r.dx * 0; pose.dy += away.y * push * kk * 0.6;
      pose.angle += r.angle * (away.x >= 0 ? 1 : -1);
      pose.sx *= r.sx; pose.sy *= r.sy;
      flash = Math.max(flash, age < 0.09 ? 1 - age / 0.09 * 0.4 : age < 0.14 ? 0.35 : 0);
      if (statuses.includes("paralysis")) pose.dx += Math.sin(s * 90) * 1.5;
    }
    if (statuses.includes("paralysis") && rand("para", unit.idx, Math.floor(s * 6)) < 0.25) pose.dx += Math.sin(s * 120) * 2.2;
    // KO
    if (unit.death && s >= unit.death.t) {
      const k = (s - unit.death.t) / DEATH_TIME;
      const ko = clipPhase(unit.clips.ko, "fall", k);
      pose.dx += ko.dx * foot.scale * SPRITE_SCALE * 0.55 * facing * -1;
      pose.dy += ko.dy * foot.scale * SPRITE_SCALE * 0.55;
      pose.angle += ko.angle * facing * -1; pose.sx *= ko.sx; pose.sy *= ko.sy;
      flash = Math.max(flash, k < 0.18 ? 1 : 0);
      dissolve = clamp01((k - 0.35) / 0.65);
      alpha *= 1 - ease("easeInQuad", clamp01((k - 0.55) / 0.45));
    }
    // victory hop after the result
    const result = plan.script.result;
    if (result && result.winner === unit.team && s > (result.t || plan.duration) - 0.6 && !unit.death) {
      const v = clipPhase(unit.clips.victory, "loop", ((s + unit.phase) / (unit.clips.victory.period || .6)) % 1);
      pose.dy += v.dy * foot.scale * 1.5; pose.sx *= v.sx; pose.sy *= v.sy;
    }
    if (foot.hidden) alpha = 0;
    if (foot.how === "blink" && foot.moving > 0) { alpha *= 1 - foot.moving * 0.6; pose.sx *= 1 - foot.moving * 0.4; pose.sy *= 1 + foot.moving * 0.5; }
    // Displayed size keeps relative body size but lifts tiny cels toward the
    // common read size: content 24 px -> ~0.75, 56 px -> 1.0 of the base.
    const box = plan.boxes && plan.boxes[unit.sprite];
    const content = box ? Math.max(box.w, box.h) : 48;
    const size = (30 + 0.5 * Math.min(64, content)) * SPRITE_SCALE * foot.scale * (1 + 0.05 * ((unit.star || 1) - 1));
    return { foot, pose, facing, dash, acting, flash, alpha, dissolve, ghosts, glow, statuses, frozen, size };
  }
  function statusStart(unit, kind, s) {
    for (const st of unit.statuses) if (st.kind === kind && st.start <= s && s < st.end) return st.start;
    return s;
  }
  function bodyCenter(plan, unit, s, lift = 0.5) {
    const b = unitPose(plan, unit, s);
    const x = b.foot.x + b.pose.dx + (b.dash ? b.dash.x : 0);
    const y = b.foot.y + b.pose.dy + (b.dash ? b.dash.y : 0) - b.size * lift;
    return { x, y, size: b.size, scale: b.foot.scale };
  }

  // ------------------------------------------------------------------ frame
  function paletteOf(plan, ref, type) {
    const pals = plan.pack.vfx.palettes;
    if (ref && ref[0] === "#") return [ref, ref, ref, ref];
    if (ref && ref !== "@type" && pals[ref]) return pals[ref];
    return pals[type] || TYPE_COLORS[type] || TYPE_COLORS.NORMAL;
  }
  function materialOf(plan, type) {
    return plan.pack.vfx.materials[type] || { particle: "sparkle", gravity: 0, drag: .9, count: 8, size: [2, 4], life: [.25, .5], speed: [60, 160] };
  }

  function weatherAt(plan, s) {
    let name = null, since = 0;
    for (const [t, w] of plan.weather) { if (t <= s + 1e-9) { name = w; since = t; } }
    return { name, since };
  }

  function cameraAt(plan, s, p) {
    let best = null, bestW = 0;
    for (const c of plan.cameras) {
      if (s < c.t0 || s > c.t1) continue;
      const k = Math.min(clamp01((s - c.t0) / 0.18), clamp01((c.t1 - s) / 0.3));
      const w = ease("easeInOutQuad", k);
      if (!best || c.prio > best.prio || c.prio === best.prio && w > bestW) { best = c; bestW = w; }
    }
    const cam = { fx: W / 2, fy: H / 2, zoom: 1, shakeX: 0, shakeY: 0, dim: 0, focus: [] , kind: null };
    if (best) {
      let pts = best.focus.map((i) => plan.units[i]).filter(Boolean).map((u) => bodyCenter(plan, u, s, 0.45));
      if (best.beats) {
        // chain follow: glide between beat units in order
        const active = best.beats.filter((b) => b.t <= s).pop() || best.beats[0];
        const u = plan.units[active.unit];
        if (u) pts = [bodyCenter(plan, u, s, 0.45)];
      }
      if (pts.length) {
        const fx = pts.reduce((a, q) => a + q.x, 0) / pts.length, fy = pts.reduce((a, q) => a + q.y, 0) / pts.length;
        cam.fx = lerp(W / 2, fx, bestW * 0.85); cam.fy = lerp(H / 2, fy, bestW * 0.85);
        cam.zoom = 1 + (best.zoom - 1) * bestW;
        cam.kind = best.kind;
        if (best.dim && s >= best.dimFrom && s <= best.dimTo) {
          const dk = Math.min(clamp01((s - best.dimFrom) / 0.1), clamp01((best.dimTo - s) / 0.2));
          cam.dim = best.dim * dk;
          cam.focus = best.focus.slice();
        }
      }
    }
    // shake: recent hits scaled by weight; driven by playback time so a frozen
    // hitstop frame still trembles
    const sh = plan.pack.vfx.screen.shake || {};
    let amp = 0;
    for (const h of plan.hits) {
      if (h.t > s) break;
      const age = s - h.t;
      if (age > (sh.decay || 0.3)) continue;
      const action = h.action != null ? plan.actions.find((a) => a.i === h.action) : null;
      const weight = clamp01(h.ratio * 3 + (action && action.ult ? 0.4 : 0) + (action && action.ko ? 0.5 : 0));
      if (weight < 0.12) continue;
      amp = Math.max(amp, ((sh.base || 1.5) + (sh.per_weight || 9) * weight) * (1 - age / (sh.decay || 0.3)));
    }
    amp = Math.min(amp, sh.max || 12);
    if (amp > 0.3) { cam.shakeX = Math.sin(p * 97.3) * amp; cam.shakeY = Math.cos(p * 83.1) * amp * 0.6; }
    return cam;
  }

  /** Pure draw list for playback time p (seconds). */
  function frame(plan, p, opts = {}) {
    const s = toSim(plan, p);
    const items = [];
    const cam = cameraAt(plan, s, p);
    const weather = weatherAt(plan, s);
    items.push({ op: "bg", weather: weather.name });
    for (const cell of plan.terrainCells) items.push({ op: "cell", col: cell[0], row: cell[1], color: plan.terrainColor, rows: plan.rows, cols: plan.cols, pulse: 0.5 + 0.5 * Math.sin(s * 2 + cell[0]), layer: 0 });
    // ground decals
    for (const d of plan.decals) {
      if (s < d.t || s > d.end + 0.4) continue;
      const pt = project(d.cell[0], d.cell[1], plan.rows, plan.cols);
      const k = clamp01((s - d.t) / 0.25), out = clamp01((d.end + 0.4 - s) / 0.4);
      items.push({ op: "decal", shape: d.shape, x: pt.x, y: pt.y - 6, size: 46 * pt.scale, pal: paletteOf(plan, d.type, d.type), grow: ease("easeOutBack", k), alpha: out, seed: d.seed });
    }
    // recipe ground layers (scorch, cracks, shockwaves) and auras under bodies
    const vfx = [];
    for (const a of plan.actions) {
      if (s < a.start - 0.05 || s > a.end + 2.6) continue;
      emitAction(plan, a, s, p, items, vfx);
    }
    // bodies
    const bodies = [];
    for (const idx of plan.order) {
      const unit = plan.units[idx];
      if (unit.death && s > unit.death.t + DEATH_TIME + 0.05) continue;
      const b = unitPose(plan, unit, s, p);
      if (b.alpha <= 0.01) continue;
      const x = b.foot.x + b.pose.dx + (b.dash ? b.dash.x : 0);
      const y = b.foot.y + b.pose.dy + (b.dash ? b.dash.y : 0);
      const focus = cam.focus.includes(idx);
      bodies.push({ idx, unit, b, x, y, focus });
    }
    bodies.sort((m, n) => m.y - n.y || m.idx - n.idx);
    for (const body of bodies) {
      const { b, unit } = body;
      const shadowY = b.foot.y + (b.dash ? b.dash.y * 0.2 : 0);
      items.push({ op: "shadow", x: body.x, y: shadowY, w: b.size * 0.5 * b.pose.sx, alpha: 0.42 * b.alpha * (1 - b.dissolve), layer: body.focus ? 5 : 3 });
    }
    for (const body of bodies) pushBody(plan, items, body, s, cam);
    if (cam.dim > 0) items.push({ op: "dim", alpha: cam.dim, layer: 4 });
    for (const v of vfx) items.push(v);
    // chain links between beat units
    for (const c of plan.chains) {
      if (s < c.t0 || s > c.t1 + 0.2) continue;
      for (let k = 1; k < c.beats.length; k++) {
        const b0 = c.beats[k - 1], b1 = c.beats[k];
        if (s < b1.t || b0.unit === b1.unit) continue;
        const u0 = plan.units[b0.unit], u1 = plan.units[b1.unit];
        if (!u0 || !u1) continue;
        const A = bodyCenter(plan, u0, s, 0.5), B = bodyCenter(plan, u1, s, 0.5);
        const age = s - b1.t;
        items.push({ op: "link", ax: A.x, ay: A.y, bx: B.x, by: B.y, color: b1.color, alpha: clamp01(1 - age / 0.7), k: ease("easeOutCubic", age / 0.2), layer: 6 });
      }
    }
    // weather overlay
    if (weather.name) items.push({ op: "weather", name: weather.name, p, since: weather.since, s, layer: 8 });
    // HUD: bars (screen-registered but following the bodies)
    for (const body of bodies) {
      const { unit, b } = body;
      if (unit.death && s >= unit.death.t) continue;
      const st = stateAt(unit, s);
      const statuses = b.statuses.filter((k) => STATUS_LOOK[k]).sort((x, y) => idxOr(x) - idxOr(y)).slice(0, 3).map((k) => STATUS_LOOK[k]);
      items.push({ op: "bar", idx: unit.idx, x: b.foot.x + (b.dash ? b.dash.x * 0.15 : 0), y: b.foot.y - b.size * 1.0 - 12, team: unit.team,
        hp: st.hp, chip: st.chip, max: unit.max_hp, shield: st.shield, energy: st.energy, star: unit.star || 1,
        statuses, name: unit.name, showName: opts.hover === unit.idx || opts.selected === unit.idx, alpha: b.alpha, layer: 9 });
    }
    // numbers and labels
    for (const n of plan.numbers) {
      const age = s - n.t;
      if (age < 0 || age > 0.95) continue;
      const unit = plan.units[n.unit];
      const c = bodyCenter(plan, unit, Math.min(s, n.t + 0.05), 0.6);
      const pop = age < 0.14 ? 1.7 - 0.7 * ease("easeOutBack", age / 0.14) : 1;
      const big = n.kind === "super" || n.kind === "crit";
      items.push({ op: "number", x: c.x + (n.lane % 2 ? 12 : -12) * (n.lane ? 1 : 0), y: c.y - ease("easeOutCubic", age / 0.9) * 30 + n.lane * 24 - 12,
        text: n.text + (n.kind === "super" ? "!" : ""), kind: n.kind, scale: pop, size: (big ? 26 : n.kind === "weak" ? 15 : 19) + Math.min(10, n.size * 30),
        alpha: clamp01((0.95 - age) / 0.25), layer: 10 });
    }
    for (const pp of plan.pops) {
      const at = pp.t + (pp.delay || 0);
      const age = s - at;
      if (age < 0 || age > 1.0) continue;
      if (pp.team != null) {
        // team-wide: one large label over the team's living bodies + a ring under each
        const members = plan.order.map((i) => plan.units[i]).filter((u) => u.team === pp.team && (!u.death || u.death.t > at));
        if (!members.length) continue;
        const centers = members.map((u) => bodyCenter(plan, u, Math.min(s, at + 0.05), 0.5));
        const cx = centers.reduce((sum, q) => sum + q.x, 0) / centers.length;
        const top = Math.min(...centers.map((q) => q.y - q.size * 0.6));
        const scale = age < 0.14 ? 0.5 + 0.5 * ease("easeOutBack", age / 0.14) : 1;
        items.push({ op: "label", x: cx, y: top - 26 - ease("easeOutQuad", age) * 8, text: pp.text, glyph: pp.glyph, color: pp.color,
          kind: "team", big: true, scale: scale * 1.25, alpha: clamp01((1.0 - age) / 0.3), layer: 10 });
        for (const q of centers) items.push({ op: "ring", x: q.x, y: q.y + q.size * 0.5, r: 12 + 34 * ease("easeOutCubic", age / 0.45), color: pp.color, alpha: clamp01(0.85 - age / 0.45), width: 2.5, layer: 7 });
        continue;
      }
      const unit = plan.units[pp.unit];
      if (!unit) continue;
      const c = bodyCenter(plan, unit, Math.min(s, at + 0.05), 1.0);
      if (pp.kind === "ring") {
        items.push({ op: "ring", x: c.x, y: c.y + c.size * 0.45, r: 10 + 40 * ease("easeOutCubic", age / 0.35), color: pp.color, alpha: clamp01(1 - age / 0.35), width: 3, layer: 7 });
        continue;
      }
      const scale = age < 0.12 ? 0.6 + 0.4 * ease("easeOutBack", age / 0.12) : 1;
      items.push({ op: "label", x: c.x, y: c.y - 34 - pp.lane * 21 - ease("easeOutQuad", age) * 8, text: pp.text, glyph: pp.glyph,
        color: pp.color, kind: pp.kind, scale, alpha: clamp01((1.0 - age) / 0.3), layer: 10 });
      if (pp.kind === "combo" || pp.kind === "effect" || pp.kind === "unknown") {
        items.push({ op: "ring", x: c.x, y: c.y + c.size * 0.4, r: 14 + 30 * ease("easeOutCubic", age / 0.4), color: pp.color, alpha: clamp01(0.8 - age / 0.4), width: 2, layer: 7 });
      }
    }
    // KO cards
    for (const idx of plan.order) {
      const u = plan.units[idx];
      if (!u.death) continue;
      const age = s - u.death.t;
      if (age < 0 || age > 0.9) continue;
      const pt = unitFoot(plan, u, u.death.t);
      items.push({ op: "kocard", x: pt.x, y: pt.y + 22, age, team: u.team, layer: 10 });
    }
    // ult banner (screen space)
    for (const bn of plan.banners) {
      const age = s - bn.t;
      if (age < 0 || age > bn.dur) continue;
      items.push({ op: "banner", unit: bn.unit, name: bn.name, type: bn.type, team: bn.team, k: age / bn.dur, pal: paletteOf(plan, bn.type, bn.type), layer: 11 });
    }
    // global flashes
    for (const hs of plan.hitstops || []) {
      if (p >= hs.p0 && p < hs.p1 + 0.05) items.push({ op: "flash", color: hs.kind === "ko" ? "#fff6dc" : "#ffffff", alpha: (hs.kind === "crit" ? 0.06 : 0.12) * (1 - (p - hs.p0) / (hs.p1 - hs.p0 + 0.05)), layer: 8 });
    }
    return { p, s, camera: cam, items, weather: weather.name };
  }
  const idxOr = (k) => { const i = STATUS_PRIORITY.indexOf(k); return i < 0 ? 99 : i; };

  function pushBody(plan, items, body, s, cam) {
    const { unit, b } = body;
    const layer = body.focus ? 5 : 3;
    // afterimages on dashes
    if (b.ghosts && b.acting) {
      for (let g = 1; g <= 3; g++) {
        const gs = s - g * 0.03;
        if (gs < b.acting.release) break;
        const gb = unitPose(plan, unit, gs);
        items.push({ op: "sprite", idx: unit.idx, ghost: true, x: gb.foot.x + gb.pose.dx + (gb.dash ? gb.dash.x : 0), y: gb.foot.y + gb.pose.dy + (gb.dash ? gb.dash.y : 0),
          w: b.size * gb.pose.sx, h: b.size * gb.pose.sy, angle: gb.pose.angle, flip: b.facing > 0, alpha: 0.32 / g, tint: paletteOf(plan, b.acting.type, b.acting.type)[2], tintA: 0.8, layer });
      }
    }
    if (b.glow > 0 && b.acting) {
      const pal = paletteOf(plan, b.acting.type, b.acting.type);
      items.push({ op: "glow", x: body.x, y: body.y - b.size * 0.45, r: b.size * (0.45 + 0.25 * b.glow), color: pal[1], alpha: 0.25 + 0.45 * b.glow, layer });
    }
    // status tints
    let tint = null, tintA = 0;
    const st = b.statuses;
    if (st.includes("freeze")) { tint = "#9fe6ff"; tintA = 0.5; }
    else if (st.includes("poison")) { tint = "#b46ae8"; tintA = 0.22 + 0.08 * Math.sin(s * 6); }
    else if (st.includes("burn")) { tint = "#ff7a3a"; tintA = 0.2 + 0.08 * Math.sin(s * 9); }
    else if (st.includes("paralysis")) { tint = "#ffe45a"; tintA = rand("pz", unit.idx, Math.floor(s * 8)) < 0.3 ? 0.35 : 0.08; }
    else if (st.includes("wet")) { tint = "#5ab4ff"; tintA = 0.14; }
    items.push({ op: "sprite", idx: unit.idx, x: body.x, y: body.y, w: b.size * b.pose.sx, h: b.size * b.pose.sy, angle: b.pose.angle,
      flip: b.facing > 0, alpha: b.alpha, flash: b.flash, tint, tintA, dissolve: b.dissolve, seed: unit.idx, layer });
    // status accents
    const top = body.y - b.size;
    if (st.includes("sleep")) for (let z = 0; z < 2; z++) {
      const k = ((s * 0.7 + z * 0.5 + unit.phase) % 1);
      items.push({ op: "text", x: body.x + 10 + k * 16, y: top + 6 - k * 22, text: "Z", size: 12 + k * 6, color: "#c8d0ff", alpha: 1 - k, layer: 7 });
    }
    if (st.includes("poison") || st.includes("burn") || st.includes("wet")) {
      const kind = st.includes("poison") ? "bubble" : st.includes("burn") ? "ember" : "droplet";
      const color = kind === "bubble" ? "#cf9cff" : kind === "ember" ? "#ffb04a" : "#8fd8ff";
      for (let i = 0; i < 3; i++) {
        const k = ((s * 0.8 + i / 3 + unit.phase) % 1);
        const xo = (rand(kind, unit.idx, i) - 0.5) * b.size * 0.6;
        const yy = kind === "droplet" ? body.y - b.size * 0.7 + k * b.size * 0.6 : body.y - b.size * 0.3 - k * b.size * 0.6;
        items.push({ op: "particle", kind, x: body.x + xo, y: yy, size: 3, color, alpha: 0.8 * (1 - k), rot: 0, layer: 7 });
      }
    }
    if (st.includes("paralysis") && rand("pa", unit.idx, Math.floor(s * 10)) < 0.35) {
      items.push({ op: "particle", kind: "arc", x: body.x + (rand("pax", unit.idx, Math.floor(s * 10)) - 0.5) * b.size * 0.7, y: body.y - b.size * 0.5, size: 12, color: "#fff27a", alpha: 0.9, rot: rand("par", Math.floor(s * 10)) * 6, layer: 7 });
    }
    if (st.includes("root")) items.push({ op: "decal", shape: "vines", x: b.foot.x, y: b.foot.y - 4, size: b.size * 0.42, pal: TYPE_COLORS.GRASS, grow: 1, alpha: 0.9, seed: unit.idx, layer: 2 });
    if (st.includes("taunt")) items.push({ op: "text", x: body.x, y: top - 4 + Math.sin(s * 8) * 2, text: "!", size: 20, color: "#ff7a5a", alpha: 1, layer: 7 });
    if (st.includes("flinch")) for (let i = 0; i < 3; i++) {
      const ang = s * 6 + i * 2.1;
      items.push({ op: "particle", kind: "sparkle", x: body.x + Math.cos(ang) * b.size * 0.3, y: top + 8 + Math.sin(ang) * 5, size: 3, color: "#ffe28a", alpha: 0.9, rot: 0, layer: 7 });
    }
    if (st.includes("guard") || st.includes("shield")) {
      items.push({ op: "ellipse", x: b.foot.x, y: b.foot.y - 2, rx: b.size * 0.42, ry: b.size * 0.13, color: "#9fe2ff", alpha: 0.55 + 0.15 * Math.sin(s * 5), width: 2, layer: 2 });
    }
  }

  /** Recipe layers of one action -> vfx items (pure). */
  function emitAction(plan, a, s, p, items, out) {
    const recipe = plan.pack.vfx.recipes[a.recipe] || plan.pack.vfx.recipes.generic_pop || { layers: [] };
    const actor = plan.units[a.actor], target = plan.units[a.target];
    if (!actor || !target) return;
    const anchors = { start: a.start, anticipation: a.start, release: a.release, impact: a.impact, recover: a.impact, end: a.end };
    const src = () => bodyCenter(plan, actor, Math.min(s, a.impact), 0.5);
    const dst = () => bodyCenter(plan, target, Math.min(s, a.impact + 0.02), 0.45);
    const isSecondary = a.secondary || a.terrain;
    recipe.layers.forEach((layer, li) => {
      if (isSecondary && layer.layer !== "impact") return;
      const t0 = anchors[layer.at || "impact"] + (layer.offset || 0);
      let dur = layer.duration || (layer.at === "anticipation" ? a.release - a.start : 0.35);
      if (layer.layer === "projectile") dur = a.impact - a.release + (a.family === "beam" ? 0.14 : 0);
      if (layer.at === "anticipation" && layer.layer !== "ground") dur = Math.max(0.05, a.release - a.start);
      const age = s - t0;
      if (age < 0 || age > dur) return;
      const k = age / Math.max(1e-3, dur);
      const pal = paletteOf(plan, layer.palette, a.type);
      const size = (layer.size || 30) * (isSecondary ? 0.6 : 1) * (a.ko ? 1.15 : 1);
      const seed = hash(a.i, li);
      const where = layer.target === "actor" ? src() : layer.target === "between" ? mid(src(), dst()) : layer.layer === "charge" || layer.layer === "aura" && layer.at === "anticipation" ? src() : dst();
      const z = (layer.layer === "ground" || layer.layer === "aura" && layer.shape === "shield_dome") ? 2 : 6;
      switch (layer.layer) {
        case "charge":
          out.push({ op: "fx", shape: layer.shape, x: where.x, y: where.y, size: size * where.scale, k: ease(layer.curve || "easeInQuad", k), pal, seed, count: layer.count || 10, particle: particleOf(plan, layer, a), layer: 6 });
          break;
        case "aura": {
          const at = layer.at === "impact" ? (layer.target === "actor" ? src() : dst()) : src();
          const tf = (layer.target === "actor" ? actor : layer.at === "impact" ? target : actor);
          const foot = unitFoot(plan, tf, s);
          out.push({ op: "fx", shape: layer.shape, x: at.x, y: at.y, fy: foot.y, size: size * at.scale, k, pal, seed, count: layer.count || 6, layer: z === 2 ? 2 : 6, alpha: layer.alpha ?? 1 });
          break;
        }
        case "projectile":
          projectileItems(plan, a, layer, s, k, pal, src(), dst(), out);
          break;
        case "trail":
          if (layer.shape === "dust") {
            const f = unitFoot(plan, target, s);
            out.push({ op: "fx", shape: "dust", x: f.x, y: f.y, size: 30 * f.scale, k, pal: paletteOf(plan, "GROUND", "GROUND"), seed, count: layer.count || 8, layer: 6 });
          }
          break;
        case "impact": {
          const c = dst();
          const dir = Math.atan2(c.y - src().y, c.x - src().x);
          out.push({ op: "fx", shape: layer.shape, x: c.x, y: c.y, size: size * c.scale, k: ease(layer.curve || "easeOutQuad", k), raw: k, pal, seed, dir,
            count: Math.round((layer.count || 10) * (isSecondary ? 0.5 : 1) * (a.crit || a.ko ? 1.4 : 1)), particle: particleOf(plan, layer, a), material: materialOf(plan, a.type), layer: 6 });
          break;
        }
        case "ground": {
          const f = unitFoot(plan, layer.target === "actor" ? actor : target, a.impact);
          items.push({ op: "fx", shape: layer.shape, x: f.x, y: f.y - 4, size: size * f.scale, k: ease(layer.curve || "easeOutQuad", k), raw: k, pal, seed, count: layer.count || 6, alpha: (layer.alpha ?? 1) * clamp01((1 - k) / 0.3), layer: 1 });
          break;
        }
        case "screen":
          if (layer.shape === "flash" && !isSecondary) out.push({ op: "flash", color: pal[1], alpha: (layer.alpha ?? 0.3) * (1 - k), layer: 8 });
          break;
      }
    });
  }
  const mid = (A, B) => ({ x: (A.x + B.x) / 2, y: (A.y + B.y) / 2, scale: (A.scale + B.scale) / 2 });
  function particleOf(plan, layer, a) {
    const name = layer.particle && layer.particle !== "@type" ? layer.particle : materialOf(plan, a.type).particle;
    return name || "sparkle";
  }

  function projectileItems(plan, a, layer, s, k, pal, A, B, out) {
    const fam = a.family === "melee" ? "straight" : a.family;
    const spec = plan.pack.vfx.projectiles[fam] || {};
    const size = (layer.size || spec.size || 9) * (A.scale + B.scale) / 2 * (a.isCast ? 1.25 : 1);
    const particle = particleOf(plan, { particle: "@type" }, a);
    const travel = Math.max(1e-3, a.impact - a.release);
    const u = clamp01((s - a.release) / travel);
    if (fam === "beam") {
      const reach = ease("easeOutCubic", clamp01(u * 1.6));
      const fade = s > a.impact ? clamp01(1 - (s - a.impact) / 0.14) : 1;
      out.push({ op: "beam", ax: A.x, ay: A.y, bx: lerp(A.x, B.x, reach), by: lerp(A.y, B.y, reach), width: (spec.width || 9) * (a.isCast ? 1.5 : 1) * (0.8 + 0.2 * Math.sin(s * 40)), pal, alpha: fade, layer: 6, seed: hash(a.i) });
      return;
    }
    if (s > a.impact) return;
    const count = fam === "volley" ? (spec.count || 3) : 1;
    for (let j = 0; j < count; j++) {
      const lag = fam === "volley" ? j * (spec.stagger || 0.06) : 0;
      const uj = clamp01((s - a.release - lag) / Math.max(1e-3, travel - lag));
      if (s < a.release + lag) continue;
      const lateral = fam === "volley" ? (j - (count - 1) / 2) * 14 : 0;
      const pos = (q) => {
        const e = fam === "arc" ? q : ease("easeInQuad", q * 0.6 + 0.4 * q * q) ;
        let x = lerp(A.x, B.x, e), y = lerp(A.y, B.y, e);
        const dx = B.x - A.x, dy = B.y - A.y, len = Math.hypot(dx, dy) || 1, nx = -dy / len, ny = dx / len;
        if (fam === "arc") y -= Math.sin(Math.PI * q) * (spec.arc || 0.45) * len * 0.6;
        if (fam === "homing") { const w = Math.sin(q * Math.PI * 2 + a.i) * (spec.wobble || 26) * (1 - q); x += nx * w; y += ny * w; }
        if (fam === "ground") { const fa = unitFoot(plan, plan.units[a.actor], a.release), fb = unitFoot(plan, plan.units[a.target], a.impact); x = lerp(fa.x, fb.x, q); y = lerp(fa.y, fb.y, q) - 6; }
        x += nx * lateral * (1 - q); y += ny * lateral * (1 - q);
        return [x, y];
      };
      const [x, y] = pos(uj);
      const trail = [];
      for (let q = 1; q <= 5; q++) { const qq = uj - q * 0.045; if (qq < 0) break; trail.push(pos(qq)); }
      out.push({ op: "projectile", family: fam, x, y, size, pal, trail, particle, angle: Math.atan2(B.y - A.y, B.x - A.x), seed: hash(a.i, j), s, layer: 6 });
    }
  }

  // ------------------------------------------------------------------ paint
  function makeCanvas(w, h) {
    if (typeof OffscreenCanvas === "function") return new OffscreenCanvas(w, h);
    const c = document.createElement("canvas"); c.width = w; c.height = h; return c;
  }
  const _bgCache = new Map();
  function background(plan, weather) {
    const key = (weather || "clear") + ":" + plan.rows;
    if (_bgCache.has(key)) return _bgCache.get(key);
    const c = makeCanvas(W, H), g = c.getContext("2d");
    const sky = g.createLinearGradient(0, 0, 0, H);
    const warm = weather === "sun";
    sky.addColorStop(0, warm ? "#2f4a33" : weather === "rain" ? "#14262c" : "#17332d");
    sky.addColorStop(0.35, warm ? "#22392a" : "#112822");
    sky.addColorStop(1, "#0b1d1b");
    g.fillStyle = sky; g.fillRect(0, 0, W, H);
    // canopy silhouettes
    for (let i = 0; i < 46; i++) {
      const x = rand("tree", i) * 1100 - 70, y = 30 + rand("ty", i) * 110, r = 26 + rand("tr", i) * 52;
      g.fillStyle = `rgba(${28 + i % 3 * 5},${62 + i % 4 * 4},${46 + i % 3 * 3},0.9)`;
      g.beginPath(); g.ellipse(x, y, r, r * 0.55, 0, 0, Math.PI * 2); g.fill();
    }
    // light shafts
    for (let i = 0; i < 4; i++) {
      const x = 160 + i * 220 + rand("shaft", i) * 60;
      const grad = g.createLinearGradient(x, 0, x + 80, H * 0.7);
      grad.addColorStop(0, "rgba(255,248,210,0.07)"); grad.addColorStop(1, "rgba(255,248,210,0)");
      g.fillStyle = grad; g.beginPath(); g.moveTo(x, 0); g.lineTo(x + 50, 0); g.lineTo(x + 170, H * 0.75); g.lineTo(x + 70, H * 0.75); g.fill();
    }
    const rows = plan.rows, cols = plan.cols;
    // rim
    const corners = [cellCorner(0, 0, rows, cols), cellCorner(cols, 0, rows, cols), cellCorner(cols, rows, rows, cols), cellCorner(0, rows, rows, cols)];
    g.fillStyle = "#0d1a19"; g.beginPath(); corners.forEach(([x, y], i) => (i ? g.lineTo(x, y + 14) : g.moveTo(x, y + 14))); g.closePath(); g.fill();
    g.lineJoin = "round";
    g.strokeStyle = "#8a9a70"; g.lineWidth = 9; g.beginPath(); corners.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.closePath(); g.stroke();
    g.strokeStyle = "#4e6850"; g.lineWidth = 5; g.stroke();
    for (let r = 0; r < rows; r++) for (let q = 0; q < cols; q++) {
      const a = cellCorner(q, r, rows, cols), b = cellCorner(q + 1, r, rows, cols), cc = cellCorner(q + 1, r + 1, rows, cols), d = cellCorner(q, r + 1, rows, cols);
      let base = (q + r) % 2 ? [74, 87, 72] : [80, 93, 76];
      if (r < rows / 2) base = base.map((v, i) => v + [10, 2, 0][i]); else base = base.map((v, i) => v + [0, 4, 8][i]);
      if (weather === "rain") base = [base[0] - 10, base[1] - 3, base[2] + 8];
      else if (weather === "sand") base = [base[0] + 22, base[1] + 8, base[2] - 6];
      else if (weather === "hail") base = [base[0] + 10, base[1] + 14, base[2] + 20];
      else if (weather === "sun") base = [base[0] + 14, base[1] + 10, base[2] - 2];
      const depth = 0.86 + 0.14 * (r / rows);
      g.fillStyle = `rgb(${base.map((v) => Math.round(v * depth)).join(",")})`;
      g.beginPath(); g.moveTo(...a); g.lineTo(...b); g.lineTo(...cc); g.lineTo(...d); g.closePath(); g.fill();
      g.strokeStyle = "rgba(150,165,125,0.28)"; g.lineWidth = 1; g.stroke();
      // grass tufts and pebbles (seeded)
      const center = project(q, r, rows, cols);
      for (let i = 0; i < 9; i++) {
        const x = center.x + (rand("tuft", q, r, i) - 0.5) * 80 * center.scale, y = center.y - 20 * center.scale + (rand("tufy", q, r, i) - 0.5) * 34 * center.scale;
        g.fillStyle = `rgba(${base[0] + 18},${base[1] + 20},${base[2] + 10},0.5)`;
        g.fillRect(Math.round(x), Math.round(y), 2, 2);
      }
    }
    // midline
    const m0 = cellCorner(0, rows / 2, rows, cols), m1 = cellCorner(cols, rows / 2, rows, cols);
    g.strokeStyle = "rgba(220,226,180,0.55)"; g.lineWidth = 2; g.setLineDash([10, 8]); g.beginPath(); g.moveTo(...m0); g.lineTo(...m1); g.stroke(); g.setLineDash([]);
    // side tints
    for (const [r0, r1, color] of [[0, rows / 2, "rgba(249,111,111,0.06)"], [rows / 2, rows, "rgba(87,193,247,0.06)"]]) {
      const p0 = cellCorner(0, r0, rows, cols), p1 = cellCorner(cols, r0, rows, cols), p2 = cellCorner(cols, r1, rows, cols), p3 = cellCorner(0, r1, rows, cols);
      g.fillStyle = color; g.beginPath(); g.moveTo(...p0); g.lineTo(...p1); g.lineTo(...p2); g.lineTo(...p3); g.closePath(); g.fill();
    }
    // vignette
    const vg = g.createRadialGradient(W / 2, H * 0.55, H * 0.35, W / 2, H * 0.55, H * 0.95);
    vg.addColorStop(0, "rgba(0,0,0,0)"); vg.addColorStop(1, "rgba(0,0,0,0.45)");
    g.fillStyle = vg; g.fillRect(0, 0, W, H);
    g.fillStyle = "rgba(243,244,218,0.85)"; g.font = "600 15px 'PingFang SC', system-ui, sans-serif"; g.textAlign = "center";
    g.fillText("森林竞技场", W / 2, 24);
    g.fillStyle = "rgba(249,111,111,0.75)"; g.font = "600 12px 'PingFang SC', system-ui, sans-serif"; g.fillText("敌方", 40, 182);
    g.fillStyle = "rgba(87,193,247,0.8)"; g.fillText("我方", W - 40, H - 40);
    _bgCache.set(key, c);
    return c;
  }

  const _variant = new WeakMap();
  function spriteVariant(img, kind, color) {
    if (!img || !img.naturalWidth && !img.width) return null;
    let map = _variant.get(img);
    if (!map) { map = new Map(); _variant.set(img, map); }
    const key = kind + (color || "");
    if (map.has(key)) return map.get(key);
    const w = img.naturalWidth || img.width, h = img.naturalHeight || img.height;
    const c = makeCanvas(w, h), g = c.getContext("2d");
    g.drawImage(img, 0, 0);
    g.globalCompositeOperation = "source-in";
    g.fillStyle = kind === "white" ? "#ffffff" : color || "#000";
    g.fillRect(0, 0, w, h);
    map.set(key, c);
    return c;
  }

  function worldToScreen(cam, x, y) {
    return [(x - cam.fx) * cam.zoom + cam.fx + cam.shakeX, (y - cam.fy) * cam.zoom + cam.fy + cam.shakeY];
  }

  function paint(ctx, plan, list, images = {}, opts = {}) {
    const cam = list.camera;
    ctx.save();
    ctx.imageSmoothingEnabled = false;
    const byLayer = list.items.map((it, i) => [it.layer ?? 0, i, it]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const applyCam = () => {
      ctx.setTransform(opts.dpr || 1, 0, 0, opts.dpr || 1, 0, 0);
      ctx.transform(cam.zoom, 0, 0, cam.zoom, cam.fx * (1 - cam.zoom) + cam.shakeX, cam.fy * (1 - cam.zoom) + cam.shakeY);
    };
    const screenSpace = () => ctx.setTransform(opts.dpr || 1, 0, 0, opts.dpr || 1, 0, 0);
    for (const [layer, , it] of byLayer) {
      if (layer >= 8 || it.op === "dim") screenSpace(); else applyCam();
      switch (it.op) {
        case "bg": {
          screenSpace();
          ctx.fillStyle = "#0b1d1b"; ctx.fillRect(0, 0, W, H);
          applyCam();
          ctx.drawImage(background(plan, it.weather), 0, 0);
          break;
        }
        case "decal": drawDecal(ctx, it); break;
        case "cell": {
          const a = cellCorner(it.col, it.row, it.rows, it.cols), b = cellCorner(it.col + 1, it.row, it.rows, it.cols);
          const c = cellCorner(it.col + 1, it.row + 1, it.rows, it.cols), d = cellCorner(it.col, it.row + 1, it.rows, it.cols);
          ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.lineTo(...c); ctx.lineTo(...d); ctx.closePath();
          ctx.fillStyle = hexA(it.color, 0.16 + 0.06 * it.pulse); ctx.fill();
          ctx.strokeStyle = hexA(it.color, 0.55); ctx.lineWidth = 1.5; ctx.setLineDash([5, 4]); ctx.stroke(); ctx.setLineDash([]);
          break;
        }
        case "fx": drawFx(ctx, it); break;
        case "shadow": {
          ctx.fillStyle = `rgba(4,12,10,${it.alpha})`;
          ctx.beginPath(); ctx.ellipse(it.x, it.y, Math.max(4, it.w), Math.max(2, it.w * 0.3), 0, 0, Math.PI * 2); ctx.fill();
          break;
        }
        case "sprite": drawSprite(ctx, plan, it, images); break;
        case "glow": {
          const g = ctx.createRadialGradient(it.x, it.y, 0, it.x, it.y, it.r);
          g.addColorStop(0, hexA(it.color, it.alpha)); g.addColorStop(1, hexA(it.color, 0));
          ctx.globalCompositeOperation = "lighter"; ctx.fillStyle = g; ctx.beginPath(); ctx.arc(it.x, it.y, it.r, 0, Math.PI * 2); ctx.fill();
          ctx.globalCompositeOperation = "source-over";
          break;
        }
        case "dim": ctx.fillStyle = `rgba(4,8,10,${it.alpha})`; ctx.fillRect(0, 0, W, H); break;
        case "particle": drawParticle(ctx, it.kind, it.x, it.y, it.size, it.color, it.alpha, it.rot); break;
        case "projectile": drawProjectile(ctx, it); break;
        case "beam": drawBeam(ctx, it); break;
        case "ring": case "ellipse": {
          ctx.strokeStyle = hexA(it.color, it.alpha); ctx.lineWidth = it.width || 2;
          ctx.beginPath();
          if (it.op === "ring") ctx.ellipse(it.x, it.y, it.r, it.r * 0.4, 0, 0, Math.PI * 2);
          else ctx.ellipse(it.x, it.y, it.rx, it.ry, 0, 0, Math.PI * 2);
          ctx.stroke();
          break;
        }
        case "link": {
          const mx = (it.ax + it.bx) / 2, my = Math.min(it.ay, it.by) - 40;
          ctx.strokeStyle = hexA(it.color, it.alpha); ctx.lineWidth = 3; ctx.setLineDash([6, 5]);
          ctx.beginPath(); ctx.moveTo(it.ax, it.ay);
          const ex = lerp(it.ax, it.bx, it.k), ey = lerp(it.ay, it.by, it.k);
          ctx.quadraticCurveTo(lerp(it.ax, mx, it.k), lerp(it.ay, my, it.k), ex, ey); ctx.stroke(); ctx.setLineDash([]);
          drawParticle(ctx, "sparkle", ex, ey, 5, it.color, it.alpha, 0);
          break;
        }
        case "text": {
          ctx.globalAlpha = it.alpha; ctx.font = `700 ${it.size}px system-ui, sans-serif`; ctx.textAlign = "center";
          ctx.lineWidth = 3; ctx.strokeStyle = "rgba(10,20,24,0.8)"; ctx.strokeText(it.text, it.x, it.y);
          ctx.fillStyle = it.color; ctx.fillText(it.text, it.x, it.y); ctx.globalAlpha = 1;
          break;
        }
        case "weather": drawWeather(ctx, it); break;
        case "flash": ctx.fillStyle = hexA(it.color, it.alpha); ctx.fillRect(0, 0, W, H); break;
        case "bar": drawBar(ctx, cam, it); break;
        case "number": drawNumber(ctx, cam, it); break;
        case "label": drawLabel(ctx, cam, it); break;
        case "kocard": {
          const [x, y] = worldToScreen(cam, it.x, it.y);
          const k = it.age / 0.9, a = clamp01((1 - k) / 0.3);
          const sc = it.age < 0.12 ? 1.6 - 0.6 * ease("easeOutBack", it.age / 0.12) : 1;
          ctx.save(); ctx.translate(x, y - 20 - k * 10); ctx.scale(sc, sc); ctx.globalAlpha = a;
          ctx.fillStyle = it.team ? "#f96f6f" : "#57c1f7"; roundRect(ctx, -30, -13, 60, 24, 5); ctx.fill();
          ctx.fillStyle = "#14201f"; ctx.font = "800 15px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.fillText("击倒", 0, 5);
          ctx.restore();
          break;
        }
        case "banner": drawBanner(ctx, plan, it, images); break;
      }
    }
    ctx.restore();
  }

  function hexA(hex, a) {
    if (!hex || hex[0] !== "#") return hex || `rgba(255,255,255,${a})`;
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${clamp01(a)})`;
  }
  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }

  function drawSprite(ctx, plan, it, images) {
    const unit = plan.units[it.idx];
    const img = images[unit.sprite];
    ctx.save();
    ctx.translate(it.x, it.y);
    ctx.rotate(it.angle * Math.PI / 180);
    ctx.scale(it.flip ? -1 : 1, 1);
    ctx.globalAlpha = it.alpha;
    if (img && (img.naturalWidth || img.width)) {
      // Source rect = the cel's opaque bounds, so feet stand on the shadow.
      const box = (plan.boxes && plan.boxes[unit.sprite]) || { x: 0, y: 0, w: img.naturalWidth || img.width, h: img.naturalHeight || img.height };
      const content = Math.max(box.w, box.h);
      const w = box.w / content * it.w, h = box.h / content * it.h;
      const draw = (source, alpha) => { ctx.globalAlpha = alpha; ctx.drawImage(source, box.x, box.y, box.w, box.h, -w / 2, -h, w, h); };
      if (it.ghost) draw(spriteVariant(img, "tint", it.tint) || img, it.alpha);
      else {
        if (it.dissolve > 0) {
          // ordered dissolve: horizontal bands drop out and drift upward
          const bands = 14;
          for (let b = 0; b < bands; b++) {
            const cut = rand("dis", it.seed, b) * 0.6 + (b / bands) * 0.4;
            if (cut < it.dissolve) continue;
            ctx.drawImage(img, box.x, box.y + box.h * b / bands, box.w, box.h / bands,
              -w / 2 + it.dissolve * (rand("dx", b) - 0.5) * 20, -h + h * b / bands - it.dissolve * 12 * rand("dy", b), w, h / bands + 0.5);
          }
        } else draw(img, it.alpha);
        if (it.tint && it.tintA > 0 && !it.dissolve) draw(spriteVariant(img, "tint", it.tint), it.alpha * it.tintA);
        if (it.flash > 0 && !it.dissolve) draw(spriteVariant(img, "white"), it.alpha * it.flash);
      }
    } else {
      ctx.fillStyle = unit.team ? "#f96f6f" : "#57c1f7";
      ctx.beginPath(); ctx.ellipse(0, -it.h * 0.4, it.w * 0.3, it.h * 0.35, 0, 0, Math.PI * 2); ctx.fill();
    }
    ctx.restore();
  }

  function drawParticle(ctx, kind, x, y, size, color, alpha, rot) {
    if (alpha <= 0.01) return;
    ctx.globalAlpha = clamp01(alpha);
    ctx.fillStyle = color; ctx.strokeStyle = color;
    switch (kind) {
      case "ember": case "flame": case "mote": case "spark":
        ctx.globalCompositeOperation = "lighter";
        ctx.fillRect(x - size / 2, y - size / 2, size, size);
        ctx.globalCompositeOperation = "source-over"; break;
      case "droplet": case "bubble":
        ctx.beginPath(); ctx.arc(x, y, size * 0.6, 0, Math.PI * 2);
        if (kind === "bubble") { ctx.lineWidth = 1.5; ctx.stroke(); } else ctx.fill(); break;
      case "arc": {
        ctx.lineWidth = 2; ctx.globalCompositeOperation = "lighter"; ctx.beginPath(); ctx.moveTo(x, y);
        let px = x, py = y;
        for (let i = 0; i < 4; i++) { px += Math.cos(rot + i * 1.7) * size / 3; py += Math.sin(rot + i * 2.3) * size / 3; ctx.lineTo(px, py); }
        ctx.stroke(); ctx.globalCompositeOperation = "source-over"; break;
      }
      case "leaf": case "shard": case "slash": case "debris": {
        ctx.save(); ctx.translate(x, y); ctx.rotate(rot);
        ctx.beginPath();
        if (kind === "leaf") { ctx.ellipse(0, 0, size, size * 0.45, 0, 0, Math.PI * 2); }
        else if (kind === "shard") { ctx.moveTo(-size * 0.3, 0); ctx.lineTo(0, -size); ctx.lineTo(size * 0.3, 0); ctx.lineTo(0, size * 0.4); }
        else if (kind === "slash") { ctx.moveTo(-size, -1); ctx.lineTo(size, -2); ctx.lineTo(size * 0.6, 2); ctx.lineTo(-size, 1); }
        else { ctx.moveTo(-size / 2, -size / 3); ctx.lineTo(size / 2, -size / 2); ctx.lineTo(size / 3, size / 2); ctx.lineTo(-size / 2, size / 3); }
        ctx.closePath(); ctx.fill(); ctx.restore(); break;
      }
      case "wisp": case "gust": case "ring": case "impact_ring":
        ctx.lineWidth = kind === "gust" ? 2 : 2.5;
        ctx.beginPath();
        if (kind === "gust") ctx.arc(x, y, size, rot, rot + 2.2);
        else ctx.ellipse(x, y, size, size * (kind === "wisp" ? 1.2 : 0.55), 0, 0, Math.PI * 2);
        if (kind === "wisp") { ctx.globalCompositeOperation = "lighter"; ctx.fill(); ctx.globalCompositeOperation = "source-over"; } else ctx.stroke();
        break;
      case "dust":
        ctx.beginPath(); ctx.arc(x, y, size, 0, Math.PI * 2); ctx.fill(); break;
      default: { // sparkle
        ctx.globalCompositeOperation = "lighter";
        ctx.beginPath(); ctx.moveTo(x, y - size * 1.6); ctx.lineTo(x + size * 0.4, y); ctx.lineTo(x, y + size * 1.6); ctx.lineTo(x - size * 0.4, y); ctx.closePath(); ctx.fill();
        ctx.beginPath(); ctx.moveTo(x - size * 1.6, y); ctx.lineTo(x, y + size * 0.4); ctx.lineTo(x + size * 1.6, y); ctx.lineTo(x, y - size * 0.4); ctx.closePath(); ctx.fill();
        ctx.globalCompositeOperation = "source-over";
      }
    }
    ctx.globalAlpha = 1;
  }

  /** Deterministic particle burst: positions are closed-form functions of age. */
  function burst(ctx, it, kind, count, radius, opts = {}) {
    const mat = it.material || {};
    const life = opts.life || 1;
    for (let i = 0; i < count; i++) {
      const r1 = rand(it.seed, i, 1), r2 = rand(it.seed, i, 2), r3 = rand(it.seed, i, 3);
      const ang = (opts.cone != null ? it.dir + (r1 - 0.5) * opts.cone : r1 * Math.PI * 2);
      const sp = radius * (0.45 + 0.75 * r2);
      const k = clamp01((it.raw ?? it.k) / life * (0.7 + 0.5 * r3));
      const d = sp * ease("easeOutCubic", k);
      const g = (mat.gravity || opts.gravity || 0) * 0.0006 * radius * k * k * 60;
      const x = it.x + Math.cos(ang) * d, y = it.y + Math.sin(ang) * d * 0.75 + g;
      const size = (mat.size ? lerp(mat.size[0], mat.size[1], r3) : 3) * (opts.scale || 1);
      drawParticle(ctx, kind, x, y, size * (1 - 0.4 * k), it.pal[r2 < 0.5 ? 1 : 2], (1 - k) * (opts.alpha || 1), ang + k * 4 * (r3 - 0.5));
    }
  }

  function drawFx(ctx, it) {
    const { pal, k } = it;
    const S = it.size;
    switch (it.shape) {
      case "converge": case "spiral": case "sparks": {
        for (let i = 0; i < it.count; i++) {
          const a0 = rand(it.seed, i) * Math.PI * 2 + (it.shape === "spiral" ? k * 4 : 0);
          const r = S * (1 - k) * (0.6 + 0.6 * rand(it.seed, i, 7)) + 4;
          drawParticle(ctx, it.particle || "sparkle", it.x + Math.cos(a0) * r, it.y + Math.sin(a0) * r * 0.7, 3 + 2 * k, pal[i % 2 ? 1 : 2], 0.4 + 0.6 * k, a0);
        }
        glowDot(ctx, it.x, it.y, S * 0.35 * k + 4, pal[0], 0.3 + 0.5 * k);
        break;
      }
      case "glow": glowDot(ctx, it.x, it.y, S * (0.4 + 0.4 * k), pal[1], 0.2 + 0.5 * k); break;
      case "ring": {
        ctx.strokeStyle = hexA(pal[1], 1 - k); ctx.lineWidth = 3 + 3 * (1 - k);
        ctx.beginPath(); ctx.ellipse(it.x, it.y, S * (0.3 + k), S * (0.3 + k) * 0.55, 0, 0, Math.PI * 2); ctx.stroke();
        break;
      }
      case "burst": {
        glowDot(ctx, it.x, it.y, S * (0.3 + 0.5 * k), pal[0], 0.9 * (1 - k));
        burst(ctx, it, it.particle || "sparkle", it.count, S * 1.3);
        break;
      }
      case "flash": glowDot(ctx, it.x, it.y, S * (0.6 + 0.8 * k), "#ffffff", 0.95 * (1 - k)); break;
      case "slash_arc": {
        const sweep = Math.PI * 0.9, r = S * 0.62;
        const a0 = (it.dir || 0) - Math.PI / 2 - sweep / 2 + (rand(it.seed) - 0.5) * 0.8;
        const head = a0 + sweep * clamp01(k * 1.6), tail = a0 + sweep * clamp01((k - 0.25) * 1.6);
        ctx.globalCompositeOperation = "lighter";
        for (const [wdt, col, al] of [[10, pal[2], 0.55], [5, pal[1], 0.9], [2, pal[0], 1]]) {
          ctx.strokeStyle = hexA(col, al * (1 - k * 0.7)); ctx.lineWidth = wdt; ctx.lineCap = "round";
          ctx.beginPath(); ctx.ellipse(it.x, it.y, r, r * 0.7, 0, Math.max(a0, tail), Math.max(a0 + 0.01, head)); ctx.stroke();
        }
        ctx.globalCompositeOperation = "source-over";
        break;
      }
      case "cross": {
        ctx.globalCompositeOperation = "lighter"; ctx.lineCap = "round";
        const L = S * (0.4 + 0.5 * k);
        for (const ang of [0.6, -0.6]) {
          ctx.strokeStyle = hexA(pal[1], 1 - k); ctx.lineWidth = 6 * (1 - k) + 1;
          ctx.beginPath(); ctx.moveTo(it.x - Math.cos(ang) * L, it.y - Math.sin(ang) * L); ctx.lineTo(it.x + Math.cos(ang) * L, it.y + Math.sin(ang) * L); ctx.stroke();
        }
        ctx.globalCompositeOperation = "source-over";
        break;
      }
      case "shards": case "splash": case "petals": case "sparks_burst":
        burst(ctx, it, it.shape === "shards" ? "debris" : it.shape === "splash" ? (it.particle || "droplet") : it.shape === "petals" ? "leaf" : "spark", it.count, S * 1.4, { gravity: 300 });
        break;
      case "sparks2": break;
      case "dust": burst(ctx, { ...it, raw: it.k }, "dust", it.count, S, { alpha: 0.5 }); break;
      case "heal_plus": case "sparkle_up": {
        for (let i = 0; i < it.count; i++) {
          const r1 = rand(it.seed, i), r2 = rand(it.seed, i, 3);
          const kk = clamp01(k * 1.2 - r2 * 0.3);
          const x = it.x + (r1 - 0.5) * S * 1.2, y = it.y + S * 0.4 - kk * S * 1.3;
          if (it.shape === "heal_plus") {
            ctx.globalAlpha = 1 - kk; ctx.fillStyle = pal[2];
            const z = 4 + 3 * r2; ctx.fillRect(x - z, y - z / 3, z * 2, z / 1.5); ctx.fillRect(x - z / 3, y - z, z / 1.5, z * 2); ctx.globalAlpha = 1;
          } else drawParticle(ctx, "sparkle", x, y, 3, pal[1], 1 - kk, 0);
        }
        break;
      }
      case "ring_rise": {
        for (let i = 0; i < 2; i++) {
          const kk = (k + i * 0.5) % 1;
          ctx.strokeStyle = hexA(pal[1], (1 - kk) * 0.9); ctx.lineWidth = 2.5;
          ctx.beginPath(); ctx.ellipse(it.x, (it.fy || it.y) - kk * S * 1.4, S * 0.55, S * 0.18, 0, 0, Math.PI * 2); ctx.stroke();
        }
        break;
      }
      case "shield_dome": {
        const a = (it.alpha ?? 1) * (k < 0.15 ? k / 0.15 : 1 - Math.max(0, (k - 0.6) / 0.4));
        const y = it.fy || it.y;
        ctx.strokeStyle = hexA(pal[1], a); ctx.lineWidth = 2.5; ctx.fillStyle = hexA(pal[2], a * 0.18);
        ctx.beginPath(); ctx.ellipse(it.x, y - S * 0.5, S * 0.75, S * 0.85, 0, Math.PI, 0); ctx.ellipse(it.x, y - S * 0.5, S * 0.75, S * 0.2, 0, 0, Math.PI); ctx.fill(); ctx.stroke();
        for (let i = 0; i < 6; i++) { const ang = Math.PI + (i + 0.5) / 6 * Math.PI; ctx.beginPath(); ctx.moveTo(it.x, y - S * 0.5 - S * 0.85); ctx.lineTo(it.x + Math.cos(ang) * S * 0.75, y - S * 0.5 + Math.sin(ang) * S * 0.85); ctx.strokeStyle = hexA(pal[0], a * 0.35); ctx.lineWidth = 1; ctx.stroke(); }
        break;
      }
      default: drawDecal(ctx, { ...it, grow: ease("easeOutBack", clamp01((it.raw ?? k) * 4)), alpha: it.alpha ?? 1 });
    }
  }
  function glowDot(ctx, x, y, r, color, alpha) {
    if (r <= 0 || alpha <= 0) return;
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, hexA(color, alpha)); g.addColorStop(0.4, hexA(color, alpha * 0.5)); g.addColorStop(1, hexA(color, 0));
    ctx.globalCompositeOperation = "lighter"; ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
    ctx.globalCompositeOperation = "source-over";
  }

  function drawDecal(ctx, it) {
    const { pal } = it, S = it.size * (it.grow ?? 1), a = it.alpha ?? 1;
    if (a <= 0.01) return;
    ctx.save(); ctx.globalAlpha = clamp01(a);
    switch (it.shape) {
      case "spikes": {
        const n = it.count || 6;
        ctx.fillStyle = "rgba(20,16,10,0.35)"; ctx.beginPath(); ctx.ellipse(it.x, it.y, it.size * 0.9, it.size * 0.3, 0, 0, Math.PI * 2); ctx.fill();
        for (let i = 0; i < n; i++) {
          const ox = (rand(it.seed, i) - 0.5) * it.size * 1.4, oy = (rand(it.seed, i, 2) - 0.5) * it.size * 0.35;
          const h = S * (0.35 + 0.35 * rand(it.seed, i, 3)), w = h * 0.4;
          ctx.fillStyle = pal[3]; ctx.beginPath(); ctx.moveTo(it.x + ox - w, it.y + oy); ctx.lineTo(it.x + ox, it.y + oy - h); ctx.lineTo(it.x + ox + w, it.y + oy); ctx.closePath(); ctx.fill();
          ctx.fillStyle = pal[1]; ctx.beginPath(); ctx.moveTo(it.x + ox - w * 0.2, it.y + oy - h * 0.2); ctx.lineTo(it.x + ox, it.y + oy - h); ctx.lineTo(it.x + ox + w * 0.5, it.y + oy - h * 0.1); ctx.closePath(); ctx.fill();
        }
        break;
      }
      case "vines": {
        ctx.strokeStyle = pal[2]; ctx.lineWidth = 3;
        for (let i = 0; i < 5; i++) {
          const ang = i / 5 * Math.PI * 2 + rand(it.seed, i);
          ctx.beginPath(); ctx.moveTo(it.x + Math.cos(ang) * S, it.y + Math.sin(ang) * S * 0.35);
          ctx.quadraticCurveTo(it.x + Math.cos(ang + 0.8) * S * 0.6, it.y - S * 0.5, it.x + Math.cos(ang + 1.6) * S * 0.3, it.y + Math.sin(ang + 1.6) * S * 0.12);
          ctx.stroke();
          ctx.fillStyle = pal[1]; ctx.beginPath(); ctx.ellipse(it.x + Math.cos(ang + 0.8) * S * 0.6, it.y - S * 0.45, 4, 2, ang, 0, Math.PI * 2); ctx.fill();
        }
        break;
      }
      case "puddle": {
        ctx.fillStyle = hexA(pal[2], 0.55); ctx.beginPath(); ctx.ellipse(it.x, it.y, S * 0.9, S * 0.32, 0, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = hexA(pal[1], 0.7); ctx.lineWidth = 2; ctx.stroke();
        break;
      }
      case "scorch": {
        const g = ctx.createRadialGradient(it.x, it.y, 0, it.x, it.y, S);
        g.addColorStop(0, hexA(pal[3], 0.6)); g.addColorStop(1, hexA(pal[3], 0));
        ctx.fillStyle = g; ctx.beginPath(); ctx.ellipse(it.x, it.y, S, S * 0.35, 0, 0, Math.PI * 2); ctx.fill();
        break;
      }
      case "crack": {
        ctx.strokeStyle = hexA(pal[3], 0.9); ctx.lineWidth = 2.5;
        for (let i = 0; i < 6; i++) {
          let ang = rand(it.seed, i) * Math.PI * 2, x = it.x, y = it.y;
          ctx.beginPath(); ctx.moveTo(x, y);
          for (let j = 1; j <= 3; j++) { ang += (rand(it.seed, i, j) - 0.5); x += Math.cos(ang) * S * 0.3; y += Math.sin(ang) * S * 0.12; ctx.lineTo(x, y); }
          ctx.stroke();
        }
        break;
      }
      case "shockwave": {
        const k = it.k ?? 1;
        ctx.strokeStyle = hexA(pal[1], (1 - k) * 0.95); ctx.lineWidth = 6 * (1 - k) + 2;
        ctx.beginPath(); ctx.ellipse(it.x, it.y, S * (0.2 + k), S * (0.2 + k) * 0.32, 0, 0, Math.PI * 2); ctx.stroke();
        ctx.strokeStyle = hexA(pal[0], (1 - k) * 0.6); ctx.lineWidth = 2;
        ctx.beginPath(); ctx.ellipse(it.x, it.y, S * (0.1 + k * 0.7), S * (0.1 + k * 0.7) * 0.32, 0, 0, Math.PI * 2); ctx.stroke();
        break;
      }
      default: { // ring_decal
        ctx.strokeStyle = hexA(pal[1], 0.75); ctx.lineWidth = 2.5;
        ctx.beginPath(); ctx.ellipse(it.x, it.y, S * 0.8, S * 0.28, 0, 0, Math.PI * 2); ctx.stroke();
        ctx.fillStyle = hexA(pal[2], 0.15); ctx.fill();
      }
    }
    ctx.restore();
  }

  function drawProjectile(ctx, it) {
    const { pal } = it;
    // trail
    for (let i = it.trail.length - 1; i >= 0; i--) {
      const [x, y] = it.trail[i];
      const f = 1 - (i + 1) / (it.trail.length + 1);
      drawParticle(ctx, it.family === "ground" ? "dust" : it.particle, x, y, it.size * 0.6 * f + 1, pal[i % 2 ? 2 : 1], 0.6 * f, it.angle + i);
    }
    glowDot(ctx, it.x, it.y, it.size * 2.2, pal[1], 0.75);
    ctx.save(); ctx.translate(it.x, it.y); ctx.rotate(it.angle);
    ctx.fillStyle = pal[2]; ctx.beginPath(); ctx.ellipse(0, 0, it.size * 1.25, it.size * 0.75, 0, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = pal[0]; ctx.beginPath(); ctx.ellipse(it.size * 0.2, 0, it.size * 0.65, it.size * 0.4, 0, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
    if (it.family === "homing" || it.particle === "arc") drawParticle(ctx, "arc", it.x, it.y, it.size * 2, pal[0], 0.8, it.s * 30);
  }
  function drawBeam(ctx, it) {
    const { pal } = it;
    ctx.save(); ctx.globalCompositeOperation = "lighter"; ctx.lineCap = "round";
    for (const [w, c, a] of [[it.width * 2.4, pal[2], 0.35], [it.width, pal[1], 0.8], [it.width * 0.4, pal[0], 1]]) {
      ctx.strokeStyle = hexA(c, a * it.alpha); ctx.lineWidth = w;
      ctx.beginPath(); ctx.moveTo(it.ax, it.ay);
      const segs = 8, dx = it.bx - it.ax, dy = it.by - it.ay, len = Math.hypot(dx, dy) || 1;
      for (let i = 1; i <= segs; i++) {
        const q = i / segs, wob = i < segs ? (rand(it.seed, i, Math.floor(it.alpha * 10)) - 0.5) * it.width * 0.5 : 0;
        ctx.lineTo(it.ax + dx * q - dy / len * wob, it.ay + dy * q + dx / len * wob);
      }
      ctx.stroke();
    }
    ctx.restore();
    glowDot(ctx, it.bx, it.by, it.width * 2.5, pal[1], 0.8 * it.alpha);
  }

  function drawWeather(ctx, it) {
    const t = it.p;
    const fadeIn = clamp01((it.s - it.since) / 0.6);
    ctx.save(); ctx.globalAlpha = fadeIn;
    if (it.name === "rain") {
      ctx.strokeStyle = "rgba(170,210,240,0.35)"; ctx.lineWidth = 1.2;
      for (let i = 0; i < 70; i++) {
        const x = (rand("rx", i) * (W + 200) + t * 260) % (W + 200) - 100, y = (rand("ry", i) * H + t * 900) % H;
        ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - 6, y + 18); ctx.stroke();
      }
      ctx.fillStyle = "rgba(40,70,100,0.12)"; ctx.fillRect(0, 0, W, H);
    } else if (it.name === "sun") {
      const g = ctx.createRadialGradient(W * 0.85, -40, 10, W * 0.85, -40, 520);
      g.addColorStop(0, "rgba(255,236,170,0.35)"); g.addColorStop(1, "rgba(255,236,170,0)");
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    } else if (it.name === "sand") {
      ctx.fillStyle = "rgba(200,160,90,0.12)"; ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "rgba(230,200,140,0.5)";
      for (let i = 0; i < 90; i++) { const x = (rand("sx", i) * W + t * 340) % W, y = rand("sy", i) * H + Math.sin(t * 3 + i) * 6; ctx.fillRect(x, y, 3, 1.5); }
    } else if (it.name === "hail") {
      ctx.fillStyle = "rgba(235,245,255,0.8)";
      for (let i = 0; i < 50; i++) { const x = (rand("hx", i) * W + t * 60) % W, y = (rand("hy", i) * H + t * 520) % H; ctx.fillRect(x, y, 3, 3); }
      ctx.fillStyle = "rgba(200,225,255,0.08)"; ctx.fillRect(0, 0, W, H);
    }
    ctx.restore();
    if (it.s - it.since < 1.4 && it.since > 0) {
      const k = (it.s - it.since) / 1.4;
      ctx.save(); ctx.globalAlpha = clamp01((1 - k) / 0.4);
      ctx.fillStyle = "rgba(10,20,24,0.7)"; roundRect(ctx, W / 2 - 70, 40, 140, 30, 15); ctx.fill();
      ctx.fillStyle = "#f3f4da"; ctx.font = "700 15px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.fillText(WEATHER_ZH[it.name] || it.name, W / 2, 61);
      ctx.restore();
    }
  }

  function drawBar(ctx, cam, it) {
    const [x, y] = worldToScreen(cam, it.x, it.y);
    const w = 58, h = 6;
    const left = Math.round(x - w / 2), top = Math.round(y);
    ctx.save(); ctx.globalAlpha = it.alpha;
    ctx.fillStyle = "rgba(8,16,18,0.78)"; roundRect(ctx, left - 2, top - 2, w + 4, h + 7, 3); ctx.fill();
    const hpw = w * clamp01(it.hp / it.max), chipw = w * clamp01(it.chip / it.max);
    ctx.fillStyle = "#f4f0d8"; ctx.fillRect(left, top, chipw, h);
    ctx.fillStyle = it.team ? "#f96f6f" : "#57c1f7"; ctx.fillRect(left, top, hpw, h);
    if (it.hp / it.max < 0.3) { ctx.fillStyle = "rgba(255,90,60,0.35)"; ctx.fillRect(left, top, hpw, h); }
    if (it.shield > 0) {
      const sw = Math.min(w, w * it.shield / it.max);
      ctx.fillStyle = "rgba(220,250,255,0.85)"; ctx.fillRect(left + Math.max(0, Math.min(hpw, w - sw)), top, sw, 3);
    }
    // energy
    const full = it.energy >= 80;
    ctx.fillStyle = full ? "#ffe066" : "#c9a640"; ctx.fillRect(left, top + h + 1, w * clamp01(it.energy / 80), 2);
    // star pips
    for (let i = 0; i < it.star; i++) {
      ctx.fillStyle = it.star === 3 ? "#ffd86b" : "#f2e6b0";
      ctx.beginPath(); ctx.arc(left - 7 - i * 6, top + 3, 2.2, 0, Math.PI * 2); ctx.fill();
    }
    // status chips
    it.statuses.forEach(([ch, color], i) => {
      const cx = left + w + 9 + i * 13, cy = top + 3;
      ctx.fillStyle = color; ctx.beginPath(); ctx.arc(cx, cy, 6, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#14201f"; ctx.font = "700 9px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.fillText(ch, cx, cy + 3);
    });
    if (it.showName) {
      ctx.font = "600 12px 'PingFang SC', system-ui, sans-serif"; ctx.textAlign = "center";
      const tw = ctx.measureText(it.name).width + 12;
      ctx.fillStyle = "rgba(8,16,18,0.85)"; roundRect(ctx, x - tw / 2, top - 22, tw, 17, 8); ctx.fill();
      ctx.fillStyle = "#f3f4da"; ctx.fillText(it.name + " " + "★".repeat(it.star), x, top - 9);
    }
    ctx.restore();
  }
  const NUMBER_COLORS = { damage: ["#ffffff", "#4a1a14"], super: ["#ffb13b", "#4a1400"], weak: ["#c6ccd2", "#22282c"], crit: ["#ffe45c", "#4a2200"],
    heal: ["#8dff9a", "#0c3a18"], shield: ["#a8f0ff", "#0c2a3a"], absorb: ["#a8d8e8", "#0c2030"] };
  function drawNumber(ctx, cam, it) {
    const [x, y] = worldToScreen(cam, it.x, it.y);
    const [fill, stroke] = NUMBER_COLORS[it.kind] || NUMBER_COLORS.damage;
    ctx.save(); ctx.translate(x, y); ctx.scale(it.scale, it.scale); ctx.globalAlpha = it.alpha;
    ctx.font = `900 ${Math.round(it.size)}px system-ui, sans-serif`; ctx.textAlign = "center"; ctx.lineJoin = "round";
    ctx.lineWidth = 5; ctx.strokeStyle = stroke; ctx.strokeText(it.text, 0, 0);
    ctx.fillStyle = fill; ctx.fillText(it.text, 0, 0);
    if (it.kind === "super") { ctx.font = "800 11px system-ui, sans-serif"; ctx.lineWidth = 3; ctx.strokeText("效果拔群", 0, 14); ctx.fillText("效果拔群", 0, 14); }
    if (it.kind === "weak") { ctx.font = "700 10px system-ui, sans-serif"; ctx.lineWidth = 3; ctx.strokeText("效果不佳", 0, 12); ctx.fillText("效果不佳", 0, 12); }
    ctx.restore();
  }
  function drawLabel(ctx, cam, it) {
    const [x, y] = worldToScreen(cam, it.x, it.y);
    ctx.save(); ctx.translate(x, y); ctx.scale(it.scale, it.scale); ctx.globalAlpha = it.alpha;
    ctx.font = `700 ${it.big ? 15 : 13}px 'PingFang SC', system-ui, sans-serif`; ctx.textAlign = "center";
    const text = (it.glyph ? it.glyph + " " : "") + it.text;
    const tw = ctx.measureText(text).width + 14;
    ctx.fillStyle = "rgba(10,18,20,0.82)"; roundRect(ctx, -tw / 2, -14, tw, 20, 10); ctx.fill();
    ctx.strokeStyle = hexA(it.color, 0.9); ctx.lineWidth = 1.5; ctx.stroke();
    ctx.fillStyle = it.color; ctx.fillText(text, 0, 1);
    ctx.restore();
  }
  function drawBanner(ctx, plan, it, images) {
    const unit = plan.units[it.unit];
    const k = it.k;
    const inK = ease("easeOutCubic", clamp01(k / 0.22)), outK = ease("easeInCubic", clamp01((k - 0.78) / 0.22));
    const ally = it.team === 0;
    const y = ally ? H - 190 : 70, h = 92;
    const slide = (1 - inK) * (ally ? -1 : 1) * W + outK * (ally ? 1 : -1) * W;
    ctx.save(); ctx.translate(slide, 0);
    ctx.globalAlpha = 0.92;
    const g = ctx.createLinearGradient(0, y, W, y + h);
    g.addColorStop(0, hexA(it.pal[3], 0.0)); g.addColorStop(0.2, hexA(it.pal[3], 0.92)); g.addColorStop(0.8, hexA(it.pal[2], 0.92)); g.addColorStop(1, hexA(it.pal[2], 0));
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.moveTo(0, y + 14); ctx.lineTo(W, y); ctx.lineTo(W, y + h - 14); ctx.lineTo(0, y + h); ctx.closePath(); ctx.fill();
    ctx.globalAlpha = 1;
    // speed lines
    ctx.strokeStyle = hexA(it.pal[0], 0.35); ctx.lineWidth = 2;
    for (let i = 0; i < 9; i++) { const ly = y + 12 + i * 8, off = (k * 900 + i * 137) % W; ctx.beginPath(); ctx.moveTo(off, ly); ctx.lineTo(off + 120, ly - 4); ctx.stroke(); }
    const img = images[unit.sprite];
    const px = ally ? 210 : W - 210;
    if (img && (img.naturalWidth || img.width)) {
      ctx.save(); ctx.beginPath(); ctx.rect(0, y - 40, W, h + 40); ctx.clip();
      ctx.imageSmoothingEnabled = false;
      const size = 168, pulse = 1 + 0.04 * Math.sin(k * 20);
      ctx.translate(px, y + h + 6); ctx.scale(ally ? -pulse : pulse, pulse);
      ctx.drawImage(img, -size / 2, -size, size, size);
      ctx.restore();
    }
    ctx.textAlign = ally ? "left" : "right";
    const tx = ally ? 320 : W - 320;
    ctx.font = "900 34px 'PingFang SC', system-ui, sans-serif"; ctx.lineWidth = 6; ctx.strokeStyle = "rgba(10,14,18,0.85)";
    ctx.strokeText(it.name, tx, y + 54); ctx.fillStyle = "#fffbe8"; ctx.fillText(it.name, tx, y + 54);
    ctx.font = "700 13px 'PingFang SC', system-ui, sans-serif"; ctx.fillStyle = hexA(it.pal[0], 0.95);
    ctx.fillText((ally ? "我方 · " : "敌方 · ") + unit.name + " · 原生技能", tx, y + 76);
    ctx.restore();
  }

  // ------------------------------------------------------------ metrics
  /** Monotony dashboard numbers for one compiled plan. */
  function monotony(plan) {
    const primary = plan.actions.filter((a) => !a.secondary && !a.terrain);
    const q = (x) => Math.round(x / 0.05) * 0.05;
    const combos = {}, raw = {};
    for (const a of primary) {
      const key = [q(a.anticipation), q(a.travel), q(a.recover)].map((v) => v.toFixed(2)).join("/");
      combos[key] = (combos[key] || 0) + 1;
      const rk = [a.tl.release - a.tl.start, a.impact - a.tl.release, a.tl.end - a.impact].map((v) => q(v).toFixed(2)).join("/");
      raw[rk] = (raw[rk] || 0) + 1;
    }
    const top = (m) => { const rows = Object.entries(m).sort((x, y) => y[1] - x[1]); return { rows, share: rows.length ? rows[0][1] / primary.length : 0, top3: rows.slice(0, 3).reduce((s, r) => s + r[1], 0) / Math.max(1, primary.length) }; };
    let maxSim = 0, clear = 0, frames = 0;
    for (let s = 0; s <= plan.duration; s += 0.05) {
      frames++;
      let active = 0, hot = 0;
      for (const a of primary) {
        if (a.start <= s && s <= a.end) active++;
        if (a.release - 0.1 <= s && s <= a.impact + 0.1) hot++;
      }
      maxSim = Math.max(maxSim, active);
      const cam = plan.cameras.some((c) => c.t0 <= s && s <= c.t1 && c.prio >= 2);
      if (hot <= 1 || cam) clear++;
    }
    const families = {};
    for (const a of primary) families[a.family] = (families[a.family] || 0) + 1;
    const hitstops = (plan.hitstops || []).map((h) => ({ kind: h.kind, at: round3(h.at), frames60: Math.round(h.dwell * 60) }));
    return {
      actions: primary.length,
      combos: top(combos), timeline_combos: top(raw),
      max_simultaneous: maxSim,
      clear_focus_pct: frames ? Math.round(clear / frames * 1000) / 10 : 0,
      hitstops, hitstop_visible: hitstops.filter((h) => h.frames60 >= 2).length,
      families, family_variety: Object.keys(families).length,
      kos: primary.filter((a) => a.ko).length, ults: primary.filter((a) => a.ult).length,
      chains: plan.chains.length,
    };
  }

  // ----------------------------------------------------------- telemetry
  function teamTotals(plan, p) {
    const s = toSim(plan, p);
    const out = { alive: [0, 0], hp: [0, 0], maxHp: [0, 0], count: [0, 0] };
    for (const idx of plan.order) {
      const u = plan.units[idx];
      const st = stateAt(u, s);
      out.count[u.team] += 1;
      out.maxHp[u.team] += u.max_hp;
      out.hp[u.team] += Math.max(0, st.hp);
      if (!u.death || s < u.death.t) out.alive[u.team] += 1;
    }
    return out;
  }
  function logEntries(plan) {
    return (plan.script.log || []).map((row) => ({ t: toPlayback(plan, row.t), text: row.text }));
  }

  // ------------------------------------------------------------ browser
  class BattleRenderer {
    constructor(canvas, script, options = {}) {
      this.canvas = canvas;
      this.options = options;
      this.images = {};
      this.hover = null;
      this.selected = null;
      this.setScript(script, options.pack);
      this._onMove = (ev) => {
        const rect = canvas.getBoundingClientRect();
        const x = (ev.clientX - rect.left) / rect.width * W, y = (ev.clientY - rect.top) / rect.height * H;
        this.hover = this.hitTest(x, y, this.lastT || 0);
        if (this.lastT != null) this.render(this.lastT);
      };
      this._onLeave = () => { this.hover = null; if (this.lastT != null) this.render(this.lastT); };
      canvas.addEventListener?.("mousemove", this._onMove);
      canvas.addEventListener?.("mouseleave", this._onLeave);
    }
    setScript(script, pack) {
      this.script = script;
      this.pack = pack ? (pack.clips ? pack : mergePacks(pack)) : (this.pack || mergePacks(null));
      this.plan = compile(script, this.pack);
      this.plan.boxes = this.boxes ||= {};
      this.ready = this._loadImages();
    }
    setPack(pack) {
      this.pack = pack.clips ? pack : mergePacks(pack);
      this.plan = compile(this.script, this.pack);
      this.plan.boxes = this.boxes ||= {};
      if (this.lastT != null) this.render(this.lastT);
    }
    get duration() { return this.plan.playbackDuration; }
    _loadImages() {
      const urls = [...new Set((this.script.units || []).map((u) => u.sprite))];
      return Promise.all(urls.map((url) => this.images[url] ? Promise.resolve() : new Promise((resolve) => {
        if (typeof Image !== "function") return resolve();
        const img = new Image();
        img.onload = () => {
          this.images[url] = img;
          this.boxes[url] = opaqueBounds(img);
          resolve();
          if (this.lastT != null) this.render(this.lastT);
        };
        img.onerror = () => resolve();
        img.src = url;
      })));
    }
    resize() {
      const dpr = Math.max(1, Math.min(3, (typeof window !== "undefined" && window.devicePixelRatio) || 1));
      if (this.canvas.width !== Math.round(W * dpr) || this.canvas.height !== Math.round(H * dpr)) {
        this.canvas.width = Math.round(W * dpr); this.canvas.height = Math.round(H * dpr);
      }
      this.dpr = dpr;
    }
    render(t) {
      this.resize();
      this.lastT = clamp(t, 0, this.duration);
      const ctx = this.canvas.getContext("2d");
      const list = frame(this.plan, this.lastT, { hover: this.hover, selected: this.selected });
      this.lastList = list;
      ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      paint(ctx, this.plan, list, this.images, { dpr: this.dpr });
      return list;
    }
    hitTest(x, y, t) {
      const s = toSim(this.plan, t);
      let best = null, bestD = 1e9;
      for (const idx of this.plan.order) {
        const u = this.plan.units[idx];
        if (u.death && s > u.death.t) continue;
        const c = bodyCenter(this.plan, u, s, 0.5);
        const d = Math.hypot(c.x - x, c.y - y);
        if (d < c.size * 0.55 && d < bestD) { best = idx; bestD = d; }
      }
      return best;
    }
    teamTotals(t) { return teamTotals(this.plan, t); }
    log() { return logEntries(this.plan); }
    monotony() { return monotony(this.plan); }
    destroy() {
      this.canvas.removeEventListener?.("mousemove", this._onMove);
      this.canvas.removeEventListener?.("mouseleave", this._onLeave);
    }
  }

  function opaqueBounds(img) {
    const w = img.naturalWidth || img.width, h = img.naturalHeight || img.height;
    try {
      const c = makeCanvas(w, h), g = c.getContext("2d");
      g.drawImage(img, 0, 0);
      const data = g.getImageData(0, 0, w, h).data;
      let x0 = w, y0 = h, x1 = -1, y1 = -1;
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        if (data[(y * w + x) * 4 + 3] > 8) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
      }
      return x1 < 0 ? { x: 0, y: 0, w, h } : { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 };
    } catch (error) {
      return { x: 0, y: 0, w, h };
    }
  }

  async function loadPack(fetchImpl = typeof fetch === "function" ? fetch : null) {
    if (!fetchImpl) return mergePacks(null);
    try {
      const response = await fetchImpl("/api/animation/pack", { cache: "no-store" });
      if (!response.ok) throw new Error(String(response.status));
      return mergePacks(await response.json());
    } catch (error) {
      return mergePacks(null);
    }
  }

  return {
    W, H, EASE, ease, hash, rand, samplePortable, sampleTrack, mergePacks, compile, frame, paint, toSim, toPlayback,
    project, monotony, teamTotals, logEntries, unitPose, BattleRenderer, loadPack, TYPE_COLORS, STATUS_LOOK,
  };
});
