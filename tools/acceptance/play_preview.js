/* Previews and glossary for newcomers (docs/70).
 *
 *  - PlayGlossary: one shared dictionary of plain-language keyword
 *    explanations (灼伤, 麻痹, 护盾, 共鸣, 觉醒, 本命技能 …). mark(text) escapes a
 *    string and wraps the first occurrence of each known term in a
 *    <span class="gl-term">; decorate(root) does the same to text already in
 *    the DOM (detail panel, sheets, bonds, scout, action bar).
 *  - PlayPreview: one reusable floating card (#pv-card). Desktop shows it on
 *    hover after HOVER_MS, keyboard users on focus; touch users get it on a
 *    long press for things without a context menu (bonds, augments, weather,
 *    terrain, glossary terms). It never re-renders a section and never calls
 *    the server: everything comes from the state play.js already holds.
 *
 * play.js calls PlayPreview.render(ctx) after every render (ctx as in
 * play_layout.js). PlayContext reuses PlayPreview.describe() for the header of
 * its phone action sheet. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
  const HOVER_MS = 300;
  // Board tiles are hovered constantly while arranging: wait longer, never cover the board,
  // and stay quiet while a unit is selected (the info strip already describes it).
  const BOARD_HOVER_MS = 650;
  const onBoard = (el) => Boolean(el?.closest?.("#battlefield"));
  const TERM_MS = 150;
  const LONG_PRESS_MS = 450;

  // ------------------------------------------------------------ glossary
  // Plain-language definitions; numbers checked against sim/status.py, economy.py,
  // arena_depth.py and arena_item_synergy.py on 2026-11-21.
  const TERMS = {
    "本命技能": "每只精灵自带的专属技能，不能被替换。能量攒满后自动释放；升到 2★/3★ 时可以再选一项永久强化。",
    "学习位": "每只精灵额外的一个技能栏，用技能机学会一招。替换会覆盖旧招且不返还，本命技能始终保留。",
    "技能机": "让精灵学会一招额外技能的道具（仓库里没有时也可以花 2 金学习）。只能学给属性相容的精灵。",
    "能量": "普攻和受到攻击都会积攒能量，攒满 80 后自动释放本命技能。",
    "特性": "被动能力：满足触发条件时自动生效，通常有冷却时间和每场次数上限。",
    "灼伤": "6 秒内持续掉血（共约 4.8% 最大生命），物理攻击 -10%。火系招式常会附带，火系免疫。",
    "中毒": "8 秒内持续掉血，每秒 0.5% 起逐秒加深（共约 9.6% 最大生命）。毒、钢属性免疫。",
    "麻痹": "持续 8 秒：攻击速度 -30%，每 3 秒僵住 0.4 秒。电系免疫。",
    "冰冻": "1.2 秒内完全无法行动。冰系免疫。",
    "睡眠": "最多 2 秒无法行动，受到攻击就会醒来。",
    "畏缩": "被打断，行动停顿 0.3 秒。",
    "定身": "不能移动位置，但仍然可以攻击；不占用主要异常状态。",
    "易伤": "受到的伤害提高。",
    "湿润": "水系招式留下的标记，可以和其他异常共存，供后续联动利用。",
    "护盾": "一层临时生命，受到伤害时先扣护盾，通常持续 3 秒。同时只有一层，只有更强的护盾才能替换。",
    "击退": "把目标推开一格，打乱对方站位。",
    "嘲讽": "迫使附近的敌人优先攻击自己一段时间。",
    "净化": "解除友军身上的主要异常状态（灼伤、中毒、麻痹等）。",
    "封疗": "让目标受到的治疗量降低。",
    "吸血": "把造成伤害的一部分转化为自己的生命。",
    "闪避": "有一定概率让敌人的攻击落空。",
    "溅射": "命中主目标时，附近的敌人也受到一部分伤害。",
    "羁绊": "场上不同的精灵凑齐同一属性或战术的数量门槛后激活的加成。备战席上的不计入，同种精灵只算一次。",
    "共鸣": "场上精灵携带同一标签的装备 2 件 / 4 件时，激活装备共鸣的额外效果。",
    "觉醒": "第 12 轮起，装备 + 它配方里的一个组件 → 觉醒版：保留原效果，再多一条机制。每局最多 2 件，可在合成树里查看。",
    "双持": "同一只精灵同时携带两件特定装备时触发的组合效果，需要第二装备位。",
    "核心": "每队可以指定 1 名上场精灵为核心：获得第二装备位、生命和攻击 +15%、它的属性羁绊多计一次，但敌方突进单位会优先扑向它。",
    "海克斯": "每隔几轮三选一的全局强化，本局一直生效。",
    "技能强化": "精灵升到 2★/3★ 时，从两项本命技能强化中选一项，永久生效。",
    "升星": "集齐 3 只同名同星的精灵会自动合成为更高一星，属性大幅提升。",
    "三合一": "3 只同名同星的精灵自动合成为更高一星。",
    "共享池": "八位训练家共用同一个卡池：别人买走的精灵，你就更难刷到。",
    "人口": "可以同时上场的精灵数量，随训练家等级提高。",
    "利息": "每轮结算时，留存金币每 10 金额外 +1，最多 +5（存到 50 金吃满）。",
    "连胜": "连胜 2 场起每轮额外 +1 金，4 场 +2，6 场 +3。",
    "连败": "连败 2 场起每轮额外 +1 金，4 场 +2，6 场 +3，作为补偿。",
    "天气": "本轮战场天气，双方共享：强化对应属性的宝可梦，并带来落雷、风沙、光合等效果。点顶部天气标签看三轮预报。",
    "地形": "当前阶段的战场地形，带来额外规则，几轮后会切换。",
    "射程": "能攻击到的距离（格数）。近战为 1 格。",
    "近战": "需要贴近敌人才能攻击，射程 1 格。",
    "远程": "可以隔着几格攻击，适合放在后排。",
    "攻击型": "攻击和特攻提高，专注输出，需要队友保护。",
    "防守型": "更耐打，适合放在前排吸收伤害。",
    "辅助型": "以治疗、护盾、控制等方式帮助队友，适合放在后排。",
  };
  const ALIASES = {"原生技能": "本命技能", "本命": "本命技能", "海克斯强化": "海克斯", "装备共鸣": "共鸣",
    "第二装备位": "双持", "剧毒": "中毒", "治疗降低": "封疗"};
  const keys = [...Object.keys(TERMS), ...Object.keys(ALIASES)].sort((a, b) => b.length - a.length);
  const TERM_RE = new RegExp(keys.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "g");
  const canonical = (word) => ALIASES[word] || word;
  const define = (word) => TERMS[canonical(word)] || "";
  /** Terms that appear in a text, in order, without duplicates. */
  function find(text) {
    const seen = new Set();
    for (const match of String(text || "").matchAll(TERM_RE)) seen.add(canonical(match[0]));
    return [...seen];
  }
  /** Escape text and wrap the first occurrence of each term (pass `seen` to share it across calls). */
  function mark(text, seen = new Set()) {
    let out = "";
    let last = 0;
    const source = String(text ?? "");
    for (const match of source.matchAll(TERM_RE)) {
      const key = canonical(match[0]);
      if (seen.has(key)) continue;
      seen.add(key);
      out += esc(source.slice(last, match.index))
        + `<span class="gl-term" tabindex="0" data-gl="${esc(key)}">${esc(match[0])}</span>`;
      last = match.index + match[0].length;
    }
    return out + esc(source.slice(last));
  }
  // Decorate text already in the DOM. Skips controls so a term never steals a click.
  const SKIP = new Set(["BUTTON", "A", "SELECT", "OPTION", "TEXTAREA", "INPUT", "SUMMARY", "SCRIPT", "STYLE", "LABEL"]);
  function decorate(root) {
    if (!root || typeof document.createTreeWalker !== "function" || root.__glSrc === root.innerHTML) return;
    const walker = document.createTreeWalker(root, 4 /* NodeFilter.SHOW_TEXT */);
    const hits = [];
    // One link per term per panel; the everyday words stay plain there.
    const seen = new Set(["近战", "远程", "射程", ...[...root.querySelectorAll(".gl-term")].map((el) => el.getAttribute("data-gl"))]);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      TERM_RE.lastIndex = 0;
      if (!TERM_RE.test(node.nodeValue)) continue;
      let skip = false;
      for (let el = node.parentElement; el && el !== root; el = el.parentElement)
        if (SKIP.has(el.tagName) || el.classList?.contains("gl-term") || el.getAttribute?.("role") === "button") { skip = true; break; }
      if (!skip) hits.push(node);
    }
    for (const node of hits) {
      const html = mark(node.nodeValue, seen);
      if (!html.includes("gl-term")) continue;
      const holder = document.createElement("span");
      holder.innerHTML = html;
      node.replaceWith(...holder.childNodes);
    }
    root.__glSrc = root.innerHTML;
  }
  window.PlayGlossary = {terms: TERMS, define, find, mark, decorate};

  // ------------------------------------------------------------ state lookups
  let ctx = null;
  const S = () => ctx?.state || null;
  const IX = () => S()?.interactions || null;
  const stars = (p) => "★".repeat(Math.max(1, Math.min(3, Number(p?.star) || 1)));
  const roleNames = {attack: "攻击型", defense: "防守型", support: "辅助型"};
  const sprite = (p) => window.pokeSpriteUrl ? window.pokeSpriteUrl(p.sid, p.shiny) : `/demo/sprite/${Number(p.sid)}.png`;
  const isPhone = () => Boolean(window.PlayLayout?.isPhone?.());
  function pieceAt(loc) {
    const s = S();
    if (!s || !loc) return null;
    if (loc[0] === "b") return s.bench?.[Number(loc.slice(1))] || null;
    const m = /^g(\d),(\d)$/.exec(loc);
    return m ? s.board?.[Number(m[1])]?.[Number(m[2])] || null : null;
  }
  function enemyAt(loc) {
    const m = /^g(\d),(\d)$/.exec(loc || "");
    return m ? S()?.opponent?.rows?.[Number(m[1])]?.[Number(m[2])] || null : null;
  }
  const short = (text, n = 90) => {
    const value = String(text || "");
    return value.length > n ? `${value.slice(0, n - 1)}…` : value;
  };
  function bondNames(p) {
    const s = S();
    const rows = [...(s?.bonds?.entries || []), ...(s?.arena?.bond_catalog || [])];
    return (p.bonds || []).map((id) => rows.find((row) => row.id === id)?.name || null).filter(Boolean);
  }

  // ------------------------------------------------------------ targets
  /** What a node stands for: {kind, key, el} or null. Single selectors only (old DOMs / tests). */
  function targetOf(node) {
    if (!node?.closest) return null;
    let el;
    if ((el = node.closest(".gl-term"))) return {kind: "term", key: el.getAttribute("data-gl"), el};
    if ((el = node.closest("[data-enemy-loc]"))) return enemyAt(el.getAttribute("data-enemy-loc")) ? {kind: "enemy", key: el.getAttribute("data-enemy-loc"), el} : null;
    if ((el = node.closest("[data-loc]"))) return pieceAt(el.getAttribute("data-loc")) ? {kind: "unit", key: el.getAttribute("data-loc"), el} : null;
    if ((el = node.closest("[data-shop]"))) return S()?.shop?.[Number(el.getAttribute("data-shop"))] ? {kind: "shop", key: Number(el.getAttribute("data-shop")), el} : null;
    if ((el = node.closest(".ix-item-card"))) {
      const key = el.querySelector("[data-ix-equip]")?.getAttribute("data-ix-equip") || (el.getAttribute("data-ix-drag") || "").split(":")[1];
      return key ? {kind: "item", key, el} : null;
    }
    if ((el = node.closest("[data-equip]"))) return {kind: "item", key: el.getAttribute("data-equip"), el};
    if ((el = node.closest("[data-ix-tm]"))) return {kind: "tm", key: el.getAttribute("data-ix-tm"), el};
    if ((el = node.closest("[data-ix-augment-info]"))) return {kind: "augment", key: el.getAttribute("data-ix-augment-info"), el};
    if ((el = node.closest(".bond-row")) || (el = node.closest(".synergy-row"))) {
      const name = el.querySelector("strong")?.textContent || "";
      return name ? {kind: "bond", key: name, el} : null;
    }
    if ((el = node.closest(".weather-pill"))) return {kind: "weather", key: "now", el};
    if ((el = node.closest("#hud-terrain"))) return {kind: "terrain", key: "now", el};
    if ((el = node.closest("#hud-order"))) return {kind: "order", key: "now", el};
    return null;
  }

  // ------------------------------------------------------------ content
  const typeTags = (types) => (types || []).map((t) => {
    const color = S()?.type_colors?.[t];
    return `<span class="pv-type"${/^#[0-9a-f]{6}$/i.test(color || "") ? ` style="--type:${color}"` : ""}>${esc(t)}</span>`;
  }).join("");
  function termsFooter(texts, limit = 3) {
    const found = find(texts.join(" ")).slice(0, limit);
    return found.length ? `<dl class="pv-terms">${found.map((k) => `<div><dt>${esc(k)}</dt><dd>${esc(TERMS[k])}</dd></div>`).join("")}</dl>` : "";
  }
  function unitCard(p, {owner = "own", loc = null, shop = null} = {}) {
    const skill = p.native_skill || {name: p.skill_name, description: p.skill_description};
    const role = roleNames[p.role_key] || "攻击型";
    const items = [[p.item_name, p.item_effect], [p.extra_item_name, p.extra_item_effect]].filter(([name]) => name);
    const bonds = bondNames(p);
    const texts = [skill?.description, p.trait?.description, ...items.map(([, e]) => e), role];
    const price = shop != null ? `<span class="pv-price">${Number(p.price)} 金</span>` : "";
    const merge = shop != null ? (p.merge_note || (p.star_progress?.merges_now ? `买下即升 ${Number(p.star_progress.next_star) || 2}★` : "")) : "";
    const hint = owner === "enemy" ? "点击侦察完整情报"
      : shop != null ? "点击选中 · 双击招募 · 右键更多"
        : `点击选中 · 双击${loc?.[0] === "b" ? "上场" : "下场"} · 右键/长按更多`;
    return `<header class="pv-head"><img src="${esc(sprite(p))}" alt=""><span><b>${esc(p.name)} <em>${stars(p)}</em></b><small>${owner === "enemy" ? "敌方 · " : shop != null ? `${Number(p.tier || p.price)} 费 · ` : loc?.[0] === "b" ? "备战席 · " : ""}${role} · ${p.ranged ? "远程" : "近战"} ${Number(p.range) || 1} 格</small></span>${price}</header>
      <div class="pv-types">${typeTags(p.types)}${merge ? `<span class="pv-merge">⇪ ${esc(merge)}</span>` : ""}${p.pool_remaining != null ? `<span class="pv-pool">池剩 ${Number(p.pool_remaining)}</span>` : ""}</div>
      ${skill?.name ? `<p class="pv-line"><i>本命</i><b>${esc(skill.name)}</b>${esc(short(skill.description, 110))}</p>` : ""}
      ${p.technique?.name ? `<p class="pv-line"><i>学习</i><b>${esc(p.technique.name)}</b>${esc(short(p.technique.description, 80))}</p>` : ""}
      ${p.trait?.name ? `<p class="pv-line"><i>特性</i><b>${esc(p.trait.name)}</b>${esc(short(p.trait.description, 100))}</p>` : ""}
      ${items.map(([name, effect]) => `<p class="pv-line"><i>装备</i><b>◆ ${esc(name)}</b>${esc(short(effect, 80))}</p>`).join("")}
      ${bonds.length ? `<p class="pv-line pv-bonds"><i>羁绊</i>${bonds.map(esc).join(" · ")}</p>` : ""}
      ${termsFooter(texts)}
      <p class="pv-hint">${hint}</p>`;
  }
  function itemCard(key) {
    const s = S();
    const ix = IX();
    const row = ix?.equip?.items?.[key] || {};
    const raw = (s?.items?.finished || []).find((x) => x.key === key) || {};
    const guide = ix?.item_advice?.guides?.[key] || null;
    const lines = [...(row.lines || []), ...(row.stats || []).map((x) => `组件 ${x}`)];
    const effect = row.effect || raw.effect || "";
    const carriers = (row.carriers || []).slice(0, 2).map((c) => esc(c.name)).join(" › ");
    return `<header class="pv-head"><span class="pv-glyph" aria-hidden="true">◆</span><span><b>${esc(row.name || raw.name || key)}</b><small>${guide?.archetype ? `${esc(guide.archetype)} · ` : ""}${guide?.treasure ? "宝物" : guide?.mechanic ? "机制装备" : "数值装备"}${row.recipe ? ` · ${esc(row.recipe)}` : ""}</small></span></header>
      ${guide?.playstyle ? `<p class="pv-line"><i>用法</i>${esc(guide.playstyle)}</p>` : ""}
      ${lines.length ? `<div class="pv-types">${lines.map((x) => `<span class="pv-stat">${esc(x)}</span>`).join("")}</div>` : ""}
      ${effect ? `<p class="pv-line">${esc(short(effect, 140))}</p>` : ""}
      ${guide?.awaken ? `<p class="pv-line"><i>觉醒</i>${esc(short(guide.awaken, 90))}</p>` : ""}
      ${carriers ? `<p class="pv-line"><i>推荐</i>${carriers}</p>` : ""}
      ${termsFooter([effect, guide?.awaken || "", ...lines, guide?.playstyle || ""])}
      <p class="pv-hint">右键 / 长按：装给推荐携带者、拆解、出售</p>`;
  }
  function tmCard(key) {
    const s = S();
    const list = Array.isArray(s?.techniques) ? s.techniques : s?.techniques?.inventory || [];
    const t = list.find((x) => x.id === key);
    if (!t) return "";
    const row = IX()?.techniques?.[key] || {};
    return `<header class="pv-head"><span class="pv-glyph" aria-hidden="true">💿</span><span><b>${esc(t.name)}</b><small>${esc(row.category_name || "技能机")} · ${Number(t.count) ? `仓库 ×${Number(t.count)}` : `${Number(t.cost) || 2} 金学习`}</small></span></header>
      <p class="pv-line">${esc(short(t.description, 150))}</p>
      ${t.compatibility ? `<p class="pv-line"><i>可学</i>${esc(t.compatibility)}</p>` : ""}
      ${row.best ? `<p class="pv-line"><i>推荐</i><b>${esc(row.best.name)}</b>${esc(row.best.reasons?.[0] || "")}</p>` : ""}
      ${termsFooter([t.description, "学习位"])}`;
  }
  function augmentCard(id) {
    const a = (S()?.augments?.selected || []).find((row) => row.id === id);
    if (!a) return "";
    const text = a.description || a.brief || "";
    return `<header class="pv-head"><span class="pv-glyph" aria-hidden="true">✦</span><span><b>${esc(a.name)}</b><small>海克斯 · 本局持续生效</small></span></header>
      <p class="pv-line">${esc(short(text, 160))}</p>${a.current ? `<p class="pv-line"><i>当前</i>${esc(a.current)}</p>` : ""}
      ${termsFooter([text, "海克斯"])}<p class="pv-hint">点击查看上一战收益</p>`;
  }
  function bondCard(name) {
    const s = S();
    const row = (s?.bonds?.entries || []).find((r) => r.name === name) || (s?.synergies || []).find((r) => (r.zh || r.name) === name);
    if (!row) return "";
    const tiers = (row.thresholds || []).map((t) => `<li class="${Number(row.n) >= Number(t.count) ? "on" : ""}"><b>${Number(t.count)}</b>${esc(short(t.effect, 70))}</li>`).join("");
    const effect = row.effect || "";
    return `<header class="pv-head"><span class="pv-glyph" aria-hidden="true">⛓</span><span><b>${esc(row.name || row.zh)}</b><small>${row.category === "tactic" ? "战术羁绊" : "属性羁绊"} · 已上场 ${Number(row.n) || 0}${row.next ? ` / 下一档 ${Number(row.next)}` : ""}</small></span></header>
      ${tiers ? `<ul class="pv-tiers">${tiers}</ul>` : effect ? `<p class="pv-line">${esc(short(effect, 140))}</p>` : ""}
      ${termsFooter(["羁绊", effect])}`;
  }
  function weatherCard() {
    const s = S();
    const cur = s?.depth?.climate?.forecast?.[0];
    if (cur) return `<header class="pv-head"><span class="pv-glyph" aria-hidden="true">${esc(cur.glyph || "☀")}</span><span><b>${esc(cur.name)}</b><small>本轮天气 · 双方共享</small></span></header>
      ${(cur.lines || []).map((line) => `<p class="pv-line">${esc(line)}</p>`).join("")}${cur.shift ? `<p class="pv-line"><i>变化</i>战斗中转为 ${esc(cur.shift.name)}</p>` : ""}
      ${termsFooter(["天气"])}<p class="pv-hint">点击查看后几轮天气预报</p>`;
    if (!s?.weather) return "";
    return `<header class="pv-head"><span class="pv-glyph" aria-hidden="true">☀</span><span><b>${esc(s.weather.zh === "无" ? "平静" : s.weather.zh)}</b><small>本轮天气</small></span></header><p class="pv-line">${esc(s.weather.note || "")}</p>${termsFooter(["天气"])}`;
  }
  function terrainCard() {
    const t = S()?.depth?.terrain;
    if (!t) return "";
    return `<header class="pv-head"><span class="pv-glyph" aria-hidden="true">⛰</span><span><b>${esc(t.name)}</b><small>地形${t.stage_end ? ` · 持续到第 ${Number(t.stage_end)} 轮` : ""}</small></span></header>
      <p class="pv-line">${esc(t.description)}</p>${t.next && t.next.id !== t.id ? `<p class="pv-line"><i>之后</i>${esc(t.next.name)}</p>` : ""}${termsFooter([t.description, "地形"])}`;
  }
  function orderCard() {
    const d = S()?.depth;
    const o = d ? (d.orders || []).find((x) => x.id === (d.order || "none")) : null;
    if (!o) return "";
    return `<header class="pv-head"><span class="pv-glyph" aria-hidden="true">⚑</span><span><b>${esc(o.name)}</b><small>战术指令</small></span></header><p class="pv-line">${esc(o.description || o.brief || "")}</p><p class="pv-hint">点击更换指令</p>`;
  }
  function termCard(key) {
    const text = define(key);
    return text ? `<p class="pv-term"><b>${esc(canonical(key))}</b>${esc(text)}</p>` : "";
  }
  /** Markup for a target, or "" when there is nothing to say. */
  function describe(target) {
    if (!target || !S()) return "";
    switch (target.kind) {
      case "unit": { const p = pieceAt(target.key); return p ? unitCard(p, {loc: target.key}) : ""; }
      case "enemy": { const p = enemyAt(target.key); return p ? unitCard(p, {owner: "enemy"}) : ""; }
      case "shop": { const p = S().shop?.[target.key]; return p ? unitCard(p, {shop: target.key}) : ""; }
      case "item": return itemCard(target.key);
      case "tm": return tmCard(target.key);
      case "augment": return augmentCard(target.key);
      case "bond": return bondCard(target.key);
      case "weather": return weatherCard();
      case "terrain": return terrainCard();
      case "order": return orderCard();
      case "term": return termCard(target.key);
      default: return "";
    }
  }

  // ------------------------------------------------------------ floating card
  let card = null;
  let shown = null;      // target currently shown
  let timer = 0;
  let pinned = false;    // opened by a long press / tap: stays until the next tap
  function ensureCard() {
    if (card) return card;
    card = document.createElement("div");
    card.id = "pv-card";
    card.className = "pv-card";
    card.setAttribute("role", "tooltip");
    card.hidden = true;
    document.body.append(card);
    return card;
  }
  function place(el, anchor) {
    if (typeof el.getBoundingClientRect !== "function" || !anchor?.getBoundingClientRect) return;
    let a = anchor.getBoundingClientRect();
    if (onBoard(anchor)) {
      // Anchor to the whole board at the tile's height, so the card sits beside the board.
      const b = document.getElementById("battlefield").getBoundingClientRect();
      a = {left: b.left, right: b.right, top: a.top, bottom: a.bottom, width: b.width, height: a.height};
    }
    const w = el.offsetWidth || 280, h = el.offsetHeight || 160;
    const vw = window.innerWidth || 1280, vh = window.innerHeight || 800, gap = 8;
    const fits = (x, y) => x >= 4 && y >= 4 && x + w <= vw - 4 && y + h <= vh - 4;
    const options = [
      [a.right + gap, a.top], [a.left - w - gap, a.top],
      [a.left + a.width / 2 - w / 2, a.top - h - gap], [a.left + a.width / 2 - w / 2, a.bottom + gap],
    ];
    const sideways = onBoard(anchor) ? options.slice(0, 2) : options;
    let [x, y] = sideways.find(([ox, oy]) => fits(ox, Math.min(oy, vh - h - 4)))
      || options.find(([ox, oy]) => fits(ox, Math.min(oy, vh - h - 4))) || options[0];
    x = Math.max(4, Math.min(x, vw - w - 4));
    y = Math.max(4, Math.min(y, vh - h - 4));
    el.style.left = `${Math.round(x)}px`;
    el.style.top = `${Math.round(y)}px`;
  }
  function show(target, {pin = false} = {}) {
    const html = describe(target);
    if (!html) return hide();
    const el = ensureCard();
    if (el.__src !== html) { el.innerHTML = html; el.__src = html; }
    el.className = `pv-card pv-${target.kind}${pin ? " pinned" : ""}`;
    el.hidden = false;
    shown = target;
    pinned = pin;
    target.el?.setAttribute?.("aria-describedby", "pv-card");
    place(el, target.el);
  }
  function hide() {
    clearTimeout(timer);
    timer = 0;
    if (shown?.el?.getAttribute?.("aria-describedby") === "pv-card") shown.el.removeAttribute("aria-describedby");
    shown = null;
    pinned = false;
    if (card && !card.hidden) card.hidden = true;
  }
  const same = (a, b) => a && b && a.kind === b.kind && a.key === b.key && a.el === b.el;
  function schedule(target, delay) {
    if (same(target, shown)) return;
    clearTimeout(timer);
    if (!target) { if (!pinned) hide(); return; }
    timer = setTimeout(() => {
      timer = 0;
      if (window.PlayContext?.isOpen?.() || document.body.classList.contains("is-dragging")) return;
      show(target);
    }, delay);
  }
  const blocked = () => window.PlayContext?.isOpen?.() || document.body.classList.contains("is-dragging")
    || document.body.classList.contains("guide-open-modal");

  // Mouse hover (pointerType mouse only: emulated mouse events after a tap must not open it).
  document.addEventListener("pointerover", (event) => {
    if (event.pointerType && event.pointerType !== "mouse") return;
    if (blocked()) return;
    let target = targetOf(event.target);
    const board = target && onBoard(target.el);
    if (board && (ctx?.selected?.() != null || ctx?.equipItem?.() != null)) target = null;
    schedule(target, target?.kind === "term" ? TERM_MS : board ? BOARD_HOVER_MS : HOVER_MS);
  });
  document.addEventListener("pointerout", (event) => {
    if (event.pointerType && event.pointerType !== "mouse") return;
    const next = targetOf(event.relatedTarget);
    if (same(next, shown) || (next && shown && next.el === shown.el)) return;
    if (!next) { clearTimeout(timer); timer = 0; if (!pinned) hide(); }
  });
  // Keyboard focus shows the same card (only for keyboard-visible focus).
  document.addEventListener("focusin", (event) => {
    let visible = true;
    try { visible = event.target?.matches?.(":focus-visible") ?? true; } catch (_) { /* old engines */ }
    if (!visible || blocked()) return;
    const target = targetOf(event.target);
    if (target) schedule(target, target.kind === "term" ? TERM_MS : HOVER_MS);
  });
  document.addEventListener("focusout", () => { if (!pinned) hide(); });
  document.addEventListener("pointerdown", (event) => {
    if (pinned && event.target?.closest?.("#pv-card")) return;
    hide();
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && shown) { hide(); event.stopPropagation?.(); }
  }, true);
  // Tap / click on a glossary term toggles its definition (touch has no hover).
  document.addEventListener("click", (event) => {
    const term = event.target?.closest?.(".gl-term");
    if (!term) return;
    const target = {kind: "term", key: term.getAttribute("data-gl"), el: term};
    if (same(target, shown) && pinned) hide();
    else show(target, {pin: true});
  });
  document.addEventListener("keydown", (event) => {
    if ((event.key === "Enter" || event.key === " ") && event.target?.classList?.contains?.("gl-term")) {
      event.preventDefault?.();
      show({kind: "term", key: event.target.getAttribute("data-gl"), el: event.target}, {pin: true});
    }
  });
  if (typeof window.addEventListener === "function") {
    window.addEventListener("scroll", () => hide(), true);
    window.addEventListener("resize", () => hide());
  }

  // Touch long press for things without a context menu (bonds, augments, chips, terms).
  let press = null;
  document.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" || event.button > 0) return;
    const target = targetOf(event.target);
    if (!target || ["unit", "enemy", "shop", "item", "tm"].includes(target.kind)) return;
    press = {target, x: event.clientX, y: event.clientY, timer: setTimeout(() => {
      if (!press) return;
      show(press.target, {pin: true});
      eatClick = true;  // the release must not also toggle a bond row / open a sheet
      press = null;
    }, LONG_PRESS_MS)};
  });
  document.addEventListener("pointerup", () => {
    if (eatClick) suppressClickUntil = Date.now() + 400;
    eatClick = false;
  }, true);
  const cancelPress = (event) => {
    if (!press) return;
    if (event?.type === "pointermove" && Math.hypot(event.clientX - press.x, event.clientY - press.y) < 10) return;
    clearTimeout(press.timer);
    press = null;
  };
  for (const type of ["pointerup", "pointercancel", "pointermove"]) document.addEventListener(type, cancelPress);
  let suppressClickUntil = 0;
  let eatClick = false;
  document.addEventListener("click", (event) => {
    if (Date.now() < suppressClickUntil) {
      suppressClickUntil = 0;
      event.preventDefault?.();
      event.stopImmediatePropagation?.();
    }
  }, true);

  // ------------------------------------------------------------ render
  const DECORATE = ["unit-detail", "ix-sheet-body", "synergy-list", "scout-content", "ix-augment-cards", "augments", "boost-mods"];
  let decorateFrame = 0;
  function render(context) {
    ctx = context;
    if (shown && !describe(shown)) hide();
    else if (shown && card && !card.hidden) {
      const html = describe(shown);
      if (card.__src !== html) { card.innerHTML = html; card.__src = html; }
    }
    // Glossary decoration after paint: never on the click → visible path.
    if (typeof requestAnimationFrame !== "function" || decorateFrame) return;
    decorateFrame = requestAnimationFrame(() => {
      decorateFrame = 0;
      for (const id of DECORATE) decorate($(id));
    });
  }

  window.PlayPreview = {render, show, hide, describe, targetOf, isOpen: () => Boolean(shown), current: () => shown,
    HOVER_MS, LONG_PRESS_MS};
})();
