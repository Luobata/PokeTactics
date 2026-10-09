/* The trial UI is a client of the authoritative arena session API. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const icon = (name) =>
    `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const trainerName = (value) => String(value ?? "").replace(/L[123]\b/g, "");
  const SLOT_KEY = "poketactics.play.arena.slot";
  let state = null,
    sid = "",
    selected = null,
    shopSelected = null,
    equipItem = null;
  let busy = false,
    deploying = false,
    needsResume = false,
    sound = false,
    audio = null;
  let toastTimer;
  let systemTab = "augments",
    roleFilter = "all",
    scoutSeat = null;
  let resumeAfterScout = false, scoutUnit = null, scoutReportIndex = null, scoutReturnFocus = null;
  let historyReport = null;
  const statViews = {
    battle: {team: 0, metric: "damage_dealt"},
    history: {team: 0, metric: "damage_dealt"},
    scout: {team: 0, metric: "damage_dealt"},
  };
  const statMetrics = [
    {key: "damage_dealt", label: "输出", note: "实际造成的生命损失"},
    {key: "healing_done", label: "治疗", note: "有效回血，包含自疗"},
    {key: "damage_taken", label: "承伤", note: "实际承受的生命损失"},
    {key: "shield_absorbed", label: "护盾吸收", note: "被护盾吸收的伤害"},
    {key: "kills", label: "击杀", note: "造成对手最后一段实际生命损失的次数"},
  ];
  const recordedStats = (stats) => stats?.version === 1 && Array.isArray(stats.units);
  const statValue = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
  const statNumber = (value) => statValue(value) == null ? "—" : value.toLocaleString("zh-CN", {maximumFractionDigits: 1});
  const reportVerdict = (winner) => winner === 0 ? {kind: "win", label: "胜利"}
    : winner === 1 ? {kind: "loss", label: "失利"}
    : winner === null || winner === -1 ? {kind: "draw", label: "平局"}
    : {kind: "unknown", label: "已结算"};
  const battleDuration = (value) => statValue(value) == null ? "时长未记录" : `${value.toFixed(1)} 秒`;
  const roleNames = { attack: "攻击型", defense: "防守型", support: "辅助型" };
  const roleSymbols = { attack: "⚔", defense: "⬟", support: "✚" };
  const roleOf = (p) =>
    Object.hasOwn(roleNames, p?.role_key) ? p.role_key : "attack";
  const starsOf = (p) => Math.max(1, Math.min(3, Number(p?.star) || 1));
  const attackStyle = (p) => p?.ranged ? "远程" : "近战";
  const spriteOf = (p) =>
    `/demo/sprite/${Number(p.sid)}.png${p.shiny ? "?shiny=1" : ""}`;
  const nativeOf = (p) => p.native_skill || {
    name: p.skill_name, type: p.skill_type, description: p.skill_description, tags: [],
  };
  const skillTags = (p) => (nativeOf(p).tags || [])
    .map((tag) => `<span>${esc(tag)}</span>`).join("");
  function traitSlot(p, compact = false, readonly = false) {
    if (!Object.hasOwn(p, "trait")) return "";
    const trait = p.trait;
    const options = Array.isArray(p.trait_options) ? p.trait_options : [];
    const selectable = options.length > 1;
    const choice = !readonly && !compact && p.uid && selectable
      ? `<div class="trait-choice"><label for="trait-choice">本局特性</label><select id="trait-choice" data-trait-choice aria-label="选择${esc(p.name)}的互斥特性" ${!canPrep() ? "disabled" : ""}>${options.map(option => `<option value="${esc(option.id)}"${option.id === trait?.id ? " selected" : ""}${option.locked ? " disabled" : ""}>${esc(option.name)}${option.locked ? "（挑战解锁）" : ""}</option>`).join("")}</select><small>${canPrep() ? "准备期免费切换 · 同时只能启用一项" : "下个准备期可切换 · 当前选择已锁定"}</small><details class="trait-choice-notes"><summary>比较特性与取舍</summary>${options.map(option => `<p><strong>${esc(option.name)}</strong>${option.locked ? "（完成竞技挑战后解锁）" : ""} ${esc(option.description)}</p>`).join("")}</details></div>` : "";
    return `<section class="skill-slot trait-slot${trait ? "" : " pending-trait"}" aria-label="竞技特性"><div class="skill-slot-heading"><span>◎ ${readonly && selectable ? "已选特性" : selectable ? "可选特性" : "固定特性"}</span><small>自动触发 · 不占技能槽</small></div><strong>${trait ? esc(trait.name) : "尚未配置"}</strong>${compact ? "" : `<p>${trait ? esc(trait.description) : "该精灵本版尚未配置特性，不会随机获得特性。"}</p>`}${choice}</section>`;
  }
  function selectedTraitSkillNote(p, move, native = false) {
    if (p.trait?.id !== "trait_sheer_force") return "";
    const applicable = native && Number(p.sid) === 34 || ["thunderbolt", "ice_beam", "sludge_bomb", "thunder"].includes(move?.id);
    if (!applicable) return "";
    return `<p class="skill-trait-override"><strong>已选强行 · 覆盖基础效果</strong>此动作直接伤害提高30%，移除追加异常与畏缩。${native ? "也不再对预先中毒目标追加40%追击。" : ""}${p.item === "life_orb" ? "该动作免除生命之玉反噬，普攻仍反噬。" : ""}</p>`;
  }
  function skillSlots(p, { learned = true, compact = false, readonly = false } = {}) {
    const native = nativeOf(p);
    const nativeSlot = `<section class="skill-slot native-skill-slot" aria-label="原生技能"><div class="skill-slot-heading"><span>原生技能</span><small>固定 · 80能量，按条件施放</small></div><strong>${esc(native.name)} <small>${esc(native.type)}属性${native.behavior ? " · " + esc(native.behavior) : ""}</small></strong><div class="skill-tags">${skillTags(p)}</div>${compact ? "" : `<p>${esc(native.description)}</p>${selectedTraitSkillNote(p, native, true)}`}</section>`;
    if (!learned) return traitSlot(p, compact, readonly) + nativeSlot;
    const technique = p.technique;
    return traitSlot(p, compact, readonly) + nativeSlot + `<section class="skill-slot learned-skill-slot" aria-label="学习技能"><div class="skill-slot-heading"><span>学习技能</span><small>可替换 · 每场最多一次</small></div><strong>${technique ? esc(technique.name) : "尚未学习"}</strong>${compact ? "" : `<p>${technique ? esc(technique.description) : "学习一项招式，补充队伍需要的能力。替换只改变学习位，保留原生技能。"}</p>${selectedTraitSkillNote(p, technique)}`}</section>`;
  }
  const playback = {
    token: 0,
    timer: null,
    frames: [],
    current: 0,
    n: 0,
    dt: 0.05,
    playing: false,
    speed: 1,
    meta: null,
    complete: false,
    verdictShown: false,
    intentPlaying: false,
    buffering: false,
    requested: null,
    cached: new Set(),
    loaded: new Set(),
    failed: new Set(),
    pending: new Map(),
    cacheLimit: 72,
    reportTab: "events",
    reportTabTouched: false,
  };

  function toast(message, error = false) {
    $("toast").textContent = message;
    $("toast").className = `toast show${error ? " error" : ""}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      $("toast").className = "toast";
    }, 3600);
  }
  function tone(success = true) {
    if (!sound) return;
    try {
      audio ||= new (window.AudioContext || window.webkitAudioContext)();
      audio.resume().catch(() => {});
      const osc = audio.createOscillator(),
        gain = audio.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(success ? 660 : 240, audio.currentTime);
      osc.frequency.exponentialRampToValueAtTime(
        success ? 880 : 170,
        audio.currentTime + 0.09,
      );
      gain.gain.setValueAtTime(0.055, audio.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + 0.14);
      osc.connect(gain);
      gain.connect(audio.destination);
      osc.start();
      osc.stop(audio.currentTime + 0.15);
    } catch {
      sound = false;
      $("sound-button").setAttribute("aria-pressed", "false");
    }
  }
  function savedSlot() {
    try {
      const value = localStorage.getItem(SLOT_KEY);
      return /^[a-f0-9]{12}$/.test(value || "") ? value : "";
    } catch {
      return "";
    }
  }
  function rememberSlot() {
    try {
      localStorage.setItem(SLOT_KEY, sid);
      return true;
    } catch {
      return false;
    }
  }
  const playable = () =>
    state?.phase === "prep" && state.you.alive && !needsResume;
  const canPrep = () => playable() && !busy && !deploying;
  function pieceAt(loc) {
    if (!state || !loc) return null;
    if (loc[0] === "b") return state.bench[Number(loc.slice(1))] || null;
    const match = /^g([0-2]),([0-5])$/.exec(loc);
    return match ? state.board[Number(match[1])][Number(match[2])] : null;
  }
  async function api(cmd, params = {}, quiet = false) {
    if (busy) return null;
    const before = ownedSnapshot(state);
    let upgrades = [];
    busy = true;
    render();
    const query = new URLSearchParams({ cmd, sid, ...params });
    if (
      state?.save?.sequence != null &&
      !["new", "state", "resume"].includes(cmd)
    )
      query.set("expected_sequence", String(state.save.sequence));
    try {
      const response = await fetch(`/api/demo/action?${query}`, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`连接失败（${response.status}）`);
      const result = await response.json();
      if (!result.ok) {
        if (result.recovery_sid) {
          sid = result.recovery_sid;
          rememberSlot();
        }
        if (
          result.recovery_sid ||
          /保存.*确认|其他页面更新|先点继续存档/.test(result.error || "")
        )
          needsResume = true;
        toast(result.error || "操作未完成，请重试", true);
        tone(false);
        if (needsResume)
          $("save-status").textContent = "请点击「继续存档」重新核对进度。";
        return result;
      }
      if (result.state) {
        if (["new", "resume"].includes(cmd) || state && (state.sid !== result.state.sid || state.round !== result.state.round || state.phase !== result.state.phase)) resetScout();
        state = result.state;
        if (!["state", "resume", "new"].includes(cmd))
          upgrades = ownedSnapshot(state).filter((p) =>
            before.some((old) => old.uid === p.uid && old.star < p.star));
        sid = result.sid || state.sid;
        selected = null;
        shopSelected = null;
        equipItem = null;
        needsResume = false;
        if (!rememberSlot())
          toast("浏览器无法记住进度，请下载存档保留这场冒险。", true);
      }
      if (result.msg && !quiet) toast(result.msg);
      if (!quiet && !["state", "resume", "new"].includes(cmd)) tone();
      return result;
    } catch (error) {
      // A lost mutation response is uncertain: reload disk before another purchase.
      if (!["state", "resume", "new"].includes(cmd)) needsResume = true;
      toast(
        `${error.message}。${needsResume ? "请点击继续存档核对进度。" : "请检查本地服务后重试。"}`,
        true,
      );
      $("save-status").textContent = "连接中断，可点击「继续存档」重试。";
      return null;
    } finally {
      busy = false;
      render();
      for (const piece of upgrades) animateUpgrade(piece, before);
    }
  }

  function ownedSnapshot(value) {
    return [...(value?.board || []).flat(), ...(value?.bench || [])]
      .filter(Boolean).map((p) => {
        const element = document.querySelector(`[data-uid="${p.uid}"]`);
        const box = element?.getBoundingClientRect();
        return {...p, star: starsOf(p), point: box ? {x: box.left + box.width / 2,
          y: box.top + box.height / 2} : null};
      });
  }
  function animateUpgrade(piece, before) {
    const target = document.querySelector(`[data-uid="${piece.uid}"]`);
    if (!target) return;
    const box = target.getBoundingClientRect();
    // Bring a bench merge into view before placing its presentation layer.
    if (box.top > innerHeight - 50 || box.bottom < 0) {
      target.scrollIntoView({block: "center", behavior: "instant"});
    }
    const end = target.getBoundingClientRect();
    const point = {x: end.left + end.width / 2, y: end.top + end.height / 2};
    const layer = document.createElement("div");
    layer.className = `merge-stage${piece.shiny ? " merge-shiny" : ""}`;
    layer.setAttribute("aria-hidden", "true");
    const remaining = new Set(ownedSnapshot(state).map((p) => p.uid));
    const sources = before.filter((old) => old.sid === piece.sid && old.star < piece.star &&
      (old.uid === piece.uid || !remaining.has(old.uid))).slice(0, 3);
    // The newly purchased copy does not exist in the pre-action snapshot.
    // Show all three contributing cards, including that incoming copy.
    while (sources.length < 3) sources.push({...piece, star: piece.star - 1,
      shiny: false, point: {x: point.x + 72, y: point.y - 64}});
    layer.innerHTML = sources.map((old, i) => {
      const start = old.point || {x: point.x + (i - 1) * 72, y: point.y - 64};
      const dx = Math.max(-180, Math.min(180, start.x - point.x));
      const dy = Math.max(-160, Math.min(160, start.y - point.y));
      return `<img class="merge-source" src="${spriteOf(old)}" alt="" style="--dx:${dx}px;--dy:${dy}px;--delay:${i * 45}ms">`;
    }).join("") + `<span class="merge-ring"></span><span class="merge-ring second"></span><span class="merge-flash">✦</span><span class="merge-label">${"★".repeat(piece.star)}${piece.shiny ? " 闪光！" : " 升星！"}</span>`;
    layer.style.left = `${point.x}px`;
    layer.style.top = `${point.y}px`;
    document.body.append(layer);
    target.classList.add("unit-upgrade");
    const announce = $("merge-status");
    announce.textContent = `${piece.name}升为${piece.star}星${piece.shiny ? "，成为闪光精灵" : ""}`;
    setTimeout(() => {layer.remove(); target.classList.remove("unit-upgrade");}, 1500);
  }

  function cell(piece, loc, enemy = false, bench = false, enemyLoc = null) {
    const cls = bench ? "bench-slot" : "tile";
    const chosen = Boolean(loc) && selected === loc;
    const description = piece
      ? `${piece.name}，${starsOf(piece)}星${piece.shiny ? "闪光" : ""}，${roleNames[roleOf(piece)]}，${attackStyle(piece)}，${piece.types.join("、")}${piece.item_name ? "，装备" + piece.item_name : ""}`
      : "空位";
    return `<button type="button" class="${cls}${piece ? "" : " empty"}${chosen ? " selected" : ""}${piece?.shiny ? " shiny" : ""}${equipItem && piece && !enemy && canPrep() ? " equip-target" : ""}" ${loc ? `data-loc="${loc}"` : ""} ${enemy && piece && enemyLoc ? `data-enemy-loc="${enemyLoc}" aria-haspopup="dialog"` : ""} ${piece && !enemy ? `data-owned="1"${piece.uid ? ` data-uid="${esc(piece.uid)}"` : ""}` : ""} ${enemy ? !piece ? "disabled" : "" : !canPrep() ? "disabled" : ""} ${piece && !enemy && canPrep() ? 'draggable="true"' : ""} aria-label="${esc((enemy ? "敌方" : bench ? "备战席" : "我方") + " " + description)}" ${chosen ? 'aria-pressed="true"' : ""}>${piece ? `<img src="${spriteOf(piece)}" alt="" draggable="false"><span class="unit-label">${esc(piece.name)}</span><span class="unit-stars">${"★".repeat(starsOf(piece))}</span>${piece.item ? `<span class="unit-item unit-item-badge" title="已装备：${esc(piece.item_name || piece.item)}">◆ ${esc(piece.item_name || piece.item)}</span>` : `<span class="unit-role role-${roleOf(piece)}" title="${roleNames[roleOf(piece)]}">${roleSymbols[roleOf(piece)]}</span>`}${piece.shiny ? '<span class="shiny-mark">✦</span>' : ""}` : ""}</button>`;
  }
  function render() {
    const locked = busy || deploying;
    for (const id of ["new-confirm", "result-new", "resume-button", "backup-button"])
      $(id).disabled = locked || (id === "backup-button" && !sid);
    for (const button of document.querySelectorAll("[data-restart]"))
      button.disabled = locked;
    if (!state) {
      $("fight-button").disabled =
        $("refresh-button").disabled =
        $("levelup-button").disabled =
        $("lock-button").disabled =
        $("deploy-button").disabled =
          true;
      if (busy) $("save-status").textContent = "正在连接冒险…";
      return;
    }
    if (shopSelected != null && !state.shop[shopSelected]) shopSelected = null;
    const y = state.you,
      prep = canPrep();
    $("hp").textContent = y.hp;
    $("hp-fill").style.width = `${Math.max(0, Math.min(100, y.hp))}%`;
    $("gold").textContent = y.gold;
    $("level").textContent = `Lv.${y.level}`;
    $("pop").textContent = `${y.on_board}/${y.pop}`;
    $("xp-text").textContent =
      y.xp_next == null ? "满级" : `${y.xp} / ${y.xp_next} XP`;
    $("xp-fill").style.width =
      y.xp_next == null
        ? "100%"
        : `${Math.min(100, (100 * y.xp) / y.xp_next)}%`;
    $("round-number").textContent = String(state.round).padStart(2, "0");
    $("phase-label").textContent =
      state.phase === "over"
        ? "冒险结束"
        : !y.alive
          ? "观战阶段"
          : state.phase === "battle"
            ? "战斗结算"
            : "准备阶段";
    $("weather-label").textContent =
      state.weather.zh === "无" ? "平静" : state.weather.zh;
    $("weather-label").parentElement.title = state.weather.note;
    const opp = state.opponent;
    $("opponent-name").textContent = trainerName(opp?.name) || "等待下一轮";
    $("enemy-team-name").textContent = trainerName(opp?.name) || "当轮对手";
    $("opponent-kind").textContent = opp?.pve ? "野生遭遇" : "训练家对战";
    const enemies = opp?.rows || Array.from({length: 3}, () => []);
    $("enemy-board").innerHTML = Array.from({ length: (state.arena?.deployment_rows || state.board.length) * 6 }, (_, i) =>
      cell(enemies[Math.floor(i / 6)]?.[i % 6], null, true, false, `g${Math.floor(i / 6)},${i % 6}`),
    ).join("");
    $("ally-board").innerHTML = state.board
      .flatMap((row, r) => row.map((p, c) => cell(p, `g${r},${c}`)))
      .join("");
    $("bench").style.setProperty("--bench-slots", state.you.bench_cap || 8);
    $("bench").innerHTML = Array.from(
      { length: state.you.bench_cap || 8 },
      (_, i) => cell(state.bench[i], `b${i}`, false, true),
    ).join("");
    let welcome = $("empty-board-message");
    if (!welcome) {
      welcome = document.createElement("div");
      welcome.id = "empty-board-message";
      welcome.className = "empty-board-message";
      document.querySelector(".board-scene").append(welcome);
    }
    welcome.hidden = !playable() || y.on_board > 0;
    welcome.textContent = state.bench.length
      ? "点击备战席精灵，再点棋盘上场"
      : "从下方商店，招募你的第一位伙伴";
    $("shop").innerHTML = state.shop
      .map((p, i) =>
        p
          ? `<button type="button" class="shop-card${shopSelected === i ? " selected" : ""}${y.gold < p.price ? " unaffordable" : ""}" data-shop="${i}" style="--card-tint:${/^#[0-9a-f]{6}$/i.test(p.colors?.[0]) ? p.colors[0] + "20" : "#e9efda"}"${shopSelected === i ? ' aria-pressed="true"' : ""} aria-label="查看${esc(p.name)}详情，${roleNames[roleOf(p)]}，${p.price}金币"><div class="shop-art"><span class="shop-tier">${p.tier} 费 · ★</span><span class="shop-role role-${roleOf(p)}">${roleNames[roleOf(p)]}</span><img src="${spriteOf(p)}" alt="" draggable="false"><span class="shop-buy-hint">+</span></div><div class="shop-info"><div class="shop-name">${esc(p.name)}<span class="shop-price">${p.price}${icon("coin")}</span></div><div class="shop-types">${p.types.map((t) => `<span class="type-tag">${esc(t)}</span>`).join("")}</div><div class="shop-move"><span>${esc(nativeOf(p).name)}</span><span>${attackStyle(p)} ${p.range}格</span></div><div class="shop-skill-tags">${skillTags(p)}${p.trait ? `<span class="trait-shop-tag">◎ ${esc(p.trait.name)}</span>` : ""}</div></div></button>`
          : `<div class="shop-card sold"><div class="sold-content">${icon("ball")}<p>伙伴已加入</p></div></div>`,
      )
      .join("");
    $("shop-count").textContent = state.shop.length;
    $("shop").style.setProperty("--shop-slots", state.shop.length);
    $("refresh-button").disabled = !prep || y.gold < y.refresh_cost;
    $("refresh-button").innerHTML =
      `${icon("refresh")} 刷新 <span>${y.refresh_cost} ${icon("coin")}</span>`;
    $("levelup-button").disabled =
      !prep || y.gold < y.xp_cost || y.xp_next == null;
    $("levelup-button").innerHTML =
      `${icon("plus")} 购买经验 <span>${y.xp_cost} 金币</span>`;
    $("lock-button").disabled = !prep;
    $("lock-button").classList.toggle("locked", y.shop_locked);
    $("lock-button").setAttribute("aria-pressed", String(y.shop_locked));
    $("lock-button").setAttribute(
      "aria-label",
      y.shop_locked ? "解除商店锁定" : "锁定商店",
    );
    $("lock-button").title = y.shop_locked
      ? "已锁定：下一轮保留，手动刷新会解锁"
      : "锁定商店：下一轮保留伙伴";
    $("deploy-button").disabled =
      !prep || !state.bench.length || y.on_board >= y.pop;
    $("fight-button").disabled = locked || needsResume;
    const fightLabel = busy
      ? "正在处理…"
      : state.phase === "over"
        ? "查看最终排名"
        : state.phase === "battle"
          ? "查看战斗回放"
          : !y.alive
            ? "继续观战"
            : "开始战斗";
    $("fight-button").innerHTML =
      `${icon("swords")}<span>${fightLabel}</span>${icon("arrow")}`;
    $("fight-button").classList.toggle("busy", locked);
    $("tutorial-hint").textContent = needsResume
      ? "进度需要核对。请点击页脚的「继续存档」，再继续操作。"
      : equipItem
        ? "已选择装备：点击棋盘或备战席中的精灵，为它装备。"
        : shopSelected != null
          ? "已选中商店伙伴。在详情里点「招募」加入备战席，再点一次卡片也可以直接招募。"
          : selected
            ? "伙伴已选中。点击目标格移动或交换，在左侧可出售、卸下装备。"
          : state.phase === "over"
            ? "每一场冒险，都会让下一次相遇更有把握。再来一场吧。"
            : !y.alive
              ? "你已结束这场冒险。可以继续观战，看看最终的冠军是谁。"
              : state.phase === "battle"
                ? "本轮战果已经保存。查看回放后，点击下一轮继续冒险。"
                : !y.on_board
                  ? state.bench.length
                    ? "伙伴已来到备战席。点击它，再点击棋盘格，或者选择「一键上场」。"
                    : "冒险从一次相遇开始。点击商店中的精灵看看详情，再把它招募到备战席。"
                  : "准备阶段不限时。调整阵容、点亮羁绊，准备好了就开始战斗。";
    renderBonds();
    renderDetail();
    renderInventory();
    renderSystems();
    renderCombinations();
    renderRoundLoot();
    renderComponentChoices();
    renderStandings();
    renderBattleHistory();
    if ($("scout-dialog").open) renderScout();
    if ($("catalog-dialog").open) renderCatalog();
    $("battle-log").innerHTML =
      state.log
        .slice(-5)
        .reverse()
        .map((row) => `<p>${esc(trainerName(row))}</p>`)
        .join("") || '<p class="empty-copy">新的故事，等你写下。</p>';
    $("save-status").textContent = needsResume
      ? "请点击「继续存档」重新核对进度。"
      : state.save?.warning ||
        (state.save?.sequence
          ? `进度已自动保存 · 第 ${state.round} 轮`
          : "每次操作自动保存");
    $("battle-next").disabled = locked || ($("battle-dialog").open && playback.n > 0 && !playback.verdictShown);
  }
  function renderCombatStats(scope, stats) {
    const container = $(`${scope}-statistics`);
    if (!recordedStats(stats)) {
      container.innerHTML = '<div class="stat-heading"><h3>战斗统计</h3><span>未记录</span></div><p class="stats-unavailable">这份旧战果未记录单位统计，无法还原输出、治疗与承伤。</p>';
      return;
    }
    const view = statViews[scope];
    const metric = statMetrics.find((entry) => entry.key === view.metric);
    const units = stats.units.filter((unit) => Number(unit.team) === view.team)
      .sort((a, b) => (statValue(b[view.metric]) ?? -1) - (statValue(a[view.metric]) ?? -1)
        || Number(a.idx) - Number(b.idx));
    const total = (stats.totals || []).find((row) => Number(row.team) === view.team);
    const maximum = Math.max(0, ...units.map((unit) => statValue(unit[view.metric]) ?? 0));
    const teams = scope === "scout" ? [scoutName(scoutSubject()), trainerName(scoutReport()?.opp_name) || "当场对手"] : ["我方", "敌方"];
    const teamName = esc(teams[view.team]);
    container.innerHTML = `<div class="stat-heading"><h3>战斗统计</h3><span>全场结算 · 含阵亡精灵</span></div>
      <div class="stat-teams" role="group" aria-label="选择统计阵营">${[0, 1].map((team) => `<button type="button" data-stat-scope="${scope}" data-stat-team="${team}" aria-pressed="${team === view.team}">${team === 0 ? "● " : "▲ "}${esc(teams[team])}</button>`).join("")}</div>
      <div class="stat-metrics" role="group" aria-label="选择统计指标并按数值排序">${statMetrics.map((entry) => `<button type="button" data-stat-scope="${scope}" data-stat-metric="${entry.key}" aria-pressed="${entry.key === view.metric}" title="${entry.note}"><span>${entry.label}</span><strong>${statNumber(entry.key === "kills" ? units.reduce((sum, unit) => sum + (statValue(unit.kills) ?? 0), 0) : total?.[entry.key])}</strong></button>`).join("")}</div>
      <div class="stat-ranking-heading"><span>${teamName} · ${metric.label}排行</span><small>由高到低 · ${units.length} 位伙伴</small></div>
      <ol class="stat-unit-list" data-stat-ranking="${view.metric}" aria-label="${teamName}${metric.label}排行">${units.map((unit, rank) => {
        const value = statValue(unit[view.metric]);
        const width = maximum > 0 && value != null ? Math.max(0, Math.min(100, value / maximum * 100)) : 0;
        const role = Object.hasOwn(roleNames, unit.role) ? roleNames[unit.role] : "";
        const selfHeal = view.metric === "healing_done" && statValue(unit.self_healing) != null
          ? `<small class="stat-self-heal">其中自疗 ${statNumber(unit.self_healing)}</small>` : "";
        const unitSprite = spriteOf({...unit, shiny: unit.shiny ?? starsOf(unit) === 3});
        return `<li class="stat-unit-row" data-stat-unit="${Number(unit.idx)}"><span class="stat-rank" aria-hidden="true">${rank + 1}</span><img src="${unitSprite}" alt="" loading="lazy"><div class="stat-unit-main"><div class="stat-unit-heading"><strong>${esc(unit.name)}</strong>${unit.mvp ? '<span class="stat-mvp" title="本场 MVP：输出+治疗加权最高">★ MVP</span>' : ""}<span class="stat-unit-stars" aria-label="${starsOf(unit)}星">${"★".repeat(starsOf(unit))}</span></div><small class="stat-unit-role">${esc(role)}${unit.item ? `${role ? " · " : ""}携带装备` : ""}</small><div class="stat-bar" aria-hidden="true"><span style="width:${width.toFixed(2)}%"></span></div></div><div class="stat-unit-value"><strong>${statNumber(value)}</strong>${selfHeal}</div></li>`;
      }).join("") || `<li class="stats-empty-team">${teamName}没有上阵精灵。</li>`}</ol>
      <p class="stat-accounting">输出与承伤只计实际掉血。治疗只计有效回血，包含自疗。护盾吸收单列，所有上阵精灵均计入。击杀归属造成最后一段实际生命损失的伤害来源（持续伤害/岩钉归施加者，反噬与自伤不算）。★ MVP 为全队输出+治疗加权最高者。</p>`;
    container.dataset.team = String(view.team);
  }
  function selectStatView(target) {
    const scope = target.dataset.statScope;
    if (!Object.hasOwn(statViews, scope) || (scope === "battle" && !playback.verdictShown)) return;
    const view = statViews[scope];
    let selector;
    if (["0", "1"].includes(target.dataset.statTeam)) {
      view.team = Number(target.dataset.statTeam);
      selector = `[data-stat-team="${view.team}"]`;
    } else if (statMetrics.some((metric) => metric.key === target.dataset.statMetric)) {
      view.metric = target.dataset.statMetric;
      selector = `[data-stat-metric="${view.metric}"]`;
    } else return;
    renderCombatStats(scope, (scope === "scout" ? scoutReport() : scope === "history" ? historyReport : playback.meta)?.statistics);
    $(`${scope}-statistics`).querySelector(selector)?.focus();
  }
  function renderBattleHistory() {
    const rows = Array.isArray(state?.battle_history) ? state.battle_history : [];
    const emptyMessage = Number(state?.round) > 1 || Number(state?.stats?.battles) > 0
      ? "旧回合未记录统计，从下一场战斗开始保留每轮战报。"
      : "完成第一场战斗后，这里会留下每轮战报。";
    $("battle-history-count").textContent = `${rows.length} 场`;
    const lastRow = rows.at(-1);
    $("last-result-button").hidden = !lastRow;
    $("last-result-round").textContent = lastRow ? `· 第 ${Number(lastRow.round)} 轮` : "";
    // 跨轮生涯：同名棋子跨轮伤害/击杀小计（旧轮次未记录统计的自动跳过）。
    const career = new Map();
    for (const row of rows) {
      if (!recordedStats(row.statistics)) continue;
      for (const unit of row.statistics.units) {
        if (Number(unit.team) !== 0) continue;
        const key = `${Number(unit.sid)}:${String(unit.name)}`;
        const entry = career.get(key) || { name: String(unit.name), damage: 0, kills: 0, rounds: 0 };
        entry.damage += statValue(unit.damage_dealt) ?? 0;
        entry.kills += statValue(unit.kills) ?? 0;
        entry.rounds += 1;
        career.set(key, entry);
      }
    }
    const careerRows = [...career.values()].sort((a, b) => b.damage - a.damage || b.kills - a.kills || a.name.localeCompare(b.name, "zh-CN"));
    $("battle-career").innerHTML = careerRows.length
      ? `<div class="battle-career-heading"><span>生涯小计</span><small>同名伙伴跨轮累计 · 仅含已记录统计的轮次</small></div>${careerRows.map((entry) => `<p class="battle-career-row"><strong>${esc(entry.name)}</strong><span>累计输出 ${statNumber(entry.damage)} · 击杀 ${statNumber(entry.kills)}</span><small>上阵 ${entry.rounds} 轮</small></p>`).join("")}`
      : "";
    $("battle-history").innerHTML = rows.slice().reverse().map((row) => {
      const verdict = reportVerdict(row.winner);
      return `<button type="button" class="history-entry ${verdict.kind}" data-battle-report="${Number(row.round)}" aria-haspopup="dialog" aria-label="查看第${Number(row.round)}轮战报"><span class="history-round">${String(row.round).padStart(2, "0")}</span><span class="history-entry-main"><strong>第 ${Number(row.round)} 轮 <em>${verdict.label}</em></strong><small>${esc(trainerName(row.opp_name) || (row.pve ? "野生遭遇" : "当轮对手"))}${row.ghost ? " · 镜像对手" : ""}</small></span><span class="history-entry-end"><small>${battleDuration(row.duration)}</small><span>${recordedStats(row.statistics) ? "查看统计 →" : "统计未记录 →"}</span></span></button>`;
    }).join("") || `<p class="empty-copy history-empty">${emptyMessage}</p>`;
  }
  function openHistoryReport(round) {
    const row = (state?.battle_history || []).find((entry) => Number(entry.round) === Number(round));
    if (!row) return;
    historyReport = row;
    Object.assign(statViews.history, {team: 0, metric: "damage_dealt"});
    const verdict = reportVerdict(row.winner);
    $("history-report-title").textContent = `第 ${row.round} 轮 · 战报`;
    $("history-report-subtitle").textContent = `${row.pve ? "野生遭遇" : "训练家对战"} · ${trainerName(row.opp_name) || "当轮对手"}${row.ghost ? "（镜像）" : ""} · ${battleDuration(row.duration)}`;
    $("history-report-result").textContent = verdict.label;
    $("history-report-result").className = `history-result ${verdict.kind}`;
    $("history-report-round").innerHTML = (state.battle_history || []).map((entry) => `<option value="${Number(entry.round)}"${Number(entry.round) === Number(row.round) ? " selected" : ""}>第 ${Number(entry.round)} 轮 · ${reportVerdict(entry.winner).label}</option>`).join("");
    $("history-report-round").value = String(row.round);
    renderCombatStats("history", row.statistics);
    renderBondSpark("history", row.statistics?.units);
    showCombinationSummary(row, "history");
    if (!$("history-report-dialog").open) $("history-report-dialog").showModal();
  }
  function renderBonds() {
    const entries = Array.isArray(state.bonds?.entries) ? state.bonds.entries : null;
    if (!entries) {
      $("synergy-list").innerHTML = (state.synergies || []).map((s) => `<details class="synergy-row${s.tier ? " on" : ""}"><summary><span class="type-dot">${esc((s.zh || s.name || "").slice(0, 1))}</span><strong>${esc(s.zh || s.name)}</strong><small>${Number(s.n)}${s.next ? " / " + Number(s.next) : ""}</small></summary><p>${esc(s.effect || `还需 ${Number(s.need)} 位伙伴。`)}</p></details>`).join("") || '<p class="empty-copy">上场精灵，点亮你的第一组羁绊。</p>';
      $("bond-note").textContent = "旧存档按其原有规则显示属性计数；新竞技按不同物种计数。";
      return;
    }
    const catalog = state.arena?.catalog || [];
    const bench = new Set((state.bench || []).filter(Boolean).map(p => p.sid));
    const shop = new Set((state.shop || []).filter(Boolean).map(p => p.sid));
    const priority = sid => bench.has(sid) ? 0 : shop.has(sid) ? 1 : 2;
    $("bond-note").textContent = state.bonds.note || "只计上场的不同物种，同种不同星级不重复，备战席不计入。";
    const ordered = [...entries].sort((a, b) => Number(b.category === "tactic") - Number(a.category === "tactic"));
    let previousCategory = null;
    $("synergy-list").innerHTML = ordered.map(row => {
      const heading = row.category !== previousCategory ? `<p class="bond-group-title">${row.category === "tactic" ? "战术羁绊 · 玩法配合" : "属性羁绊 · 成员加成"}</p>` : "";
      previousCategory = row.category;
      const candidates = [...(row.candidates || [])].sort((a, b) => priority(a) - priority(b) || a - b).slice(0, 4);
      const nextTier = (row.thresholds || []).find(tier => Number(tier.count) === Number(row.next));
      const effect = row.effect || (nextTier ? `${row.next}种档：${nextTier.effect}` : "部署不同伙伴，达到门槛后激活。");
      const available = candidates.map(sid => { const p = catalog.find(p => p.sid === sid); return p ? `<a href="/pokedex?q=${encodeURIComponent(p.name)}"><span>${esc(p.name)}</span><small>${bench.has(sid) ? "备战席" : shop.has(sid) ? "商店" : "图鉴"}</small></a>` : ""; }).join("");
      return `${heading}<details class="synergy-row bond-row${row.tier ? " on" : ""}"><summary><span class="type-dot${row.category === "tactic" ? " tactic" : ""}">${esc((row.name || "").slice(0, 1))}</span><strong>${esc(row.name)}</strong><small>${Number(row.n)}${row.next ? " / " + Number(row.next) : " · 满档"}</small></summary><p class="bond-tier">${row.tier ? `已激活 ${Number(row.tier)} 种档` : "尚未激活"}${row.next ? ` · 再补 ${Number(row.need)} 位不同伙伴` : ""}</p><p>${esc(effect)}</p>${available ? `<div class="bond-candidates"><span>可补伙伴</span>${available}</div>` : ""}<a class="bond-directory-link" href="/pokedex?tab=bonds&q=${encodeURIComponent(row.name)}">完整成员与门槛 ↗</a></details>`;
    }).join("") || '<p class="empty-copy">上场精灵，点亮你的第一组羁绊。</p>';
  }
  function pieceBonds(p) {
    const entries = [...(state.bonds?.entries || []), ...(state.arena?.bond_catalog || [])];
    return (p.bonds || []).map(id => { const row = entries.find(row => row.id === id); const name = row?.name || id; return `<a href="/pokedex?tab=bonds&q=${encodeURIComponent(id)}">${esc(name)}</a>`; }).join("");
  }
  function renderDetail() {
    if (shopSelected != null) {
      renderShopDetail();
      return;
    }
    const p = pieceAt(selected);
    if (!p) {
      $("unit-detail").innerHTML =
        `<div class="empty-detail">${icon("ball")}<p>点击一只精灵<br>了解它的战斗风格</p></div>`;
      return;
    }
    $("unit-detail").innerHTML =
      `<div class="unit-detail-card"><img src="${spriteOf(p)}" alt="${esc(p.name)}"><h3>${esc(p.name)}</h3><p class="detail-star">${"★".repeat(starsOf(p))}${p.shiny ? " · 闪光" : ""}</p><p class="role-${roleOf(p)}">${roleNames[roleOf(p)]} · ${attackStyle(p)} · ${esc(p.types.join(" / "))}</p><div style="clear:both"></div><p>${esc(p.role_description || "")}</p>${skillSlots(p)}${p.bonds?.length ? `<div class="unit-bonds"><span>所属羁绊</span>${pieceBonds(p)}</div>` : ""}<div class="detail-stat"><span>攻击方式</span><b>${attackStyle(p)} · ${p.range} 格</b></div>${p.item ? `<div class="detail-item"><p class="detail-item-heading"><span class="detail-item-badge" aria-hidden="true">◆</span><strong>装备：${esc(p.item_name)}</strong></p><p>${esc(p.item_effect)}</p></div>` : ""}<div class="detail-actions"><button data-open-system="techniques">为它学习技能</button><button data-action="sell" class="sell-button" ${!canPrep() ? "disabled" : ""}>出售 +${p.sell} 金币</button>${p.item ? `<button data-action="unequip" ${!canPrep() ? "disabled" : ""}>卸下装备</button>` : ""}<button data-action="cancel-select">取消选择</button></div></div>`;
  }
  function renderShopDetail() {
    const p = state?.shop?.[shopSelected];
    if (!p) {
      shopSelected = null;
      renderDetail();
      return;
    }
    const y = state.you;
    const reason = !playable()
      ? "准备阶段才能招募"
      : y.gold < p.price
        ? `金币不足，还差 ${p.price - y.gold} 金币`
        : "";
    $("unit-detail").innerHTML =
      `<div class="unit-detail-card shop-detail"><img src="${spriteOf(p)}" alt="${esc(p.name)}"><h3>${esc(p.name)}</h3><p class="detail-star">${"★".repeat(starsOf(p))} · ${p.tier} 费${p.shiny ? " · 闪光" : ""}</p><p class="role-${roleOf(p)}">${roleNames[roleOf(p)]} · ${attackStyle(p)} · ${esc(p.types.join(" / "))}</p><div style="clear:both"></div><p>${esc(p.role_description || "")}</p>${skillSlots(p, { learned: false })}${p.bonds?.length ? `<div class="unit-bonds"><span>所属羁绊</span>${pieceBonds(p)}</div>` : ""}<div class="detail-stat"><span>攻击方式</span><b>${attackStyle(p)} · ${p.range} 格</b></div><div class="detail-actions"><button class="recruit-button" data-shop-buy="${shopSelected}" ${reason || !canPrep() ? "disabled" : ""} aria-label="招募${esc(p.name)}，${p.price}金币${reason ? "，" + reason : ""}">招募 · ${p.price} ${icon("coin")}</button><button data-action="cancel-select">取消选择</button>${reason ? `<p class="recruit-note">${reason}</p>` : ""}</div></div>`;
  }
  function renderInventory() {
    const items = state.items;
    let html = items.components
      .map(
        (c) =>
          `<div class="inventory-item"><span>${esc(c.name)}</span><small>× ${c.n}</small></div>`,
      )
      .join("");
    html += items.finished
      .map(
        (item) =>
          `<button class="equip-button${equipItem === item.key ? " active" : ""}" data-equip="${esc(item.key)}" ${!canPrep() ? "disabled" : ""}><span><b>${esc(item.name)}</b><span class="item-description">${esc(item.effect)}</span></span><small>${equipItem === item.key ? "选择精灵…" : "装备 ↗"}</small></button>`,
      )
      .join("");
    const equipped = ownedLocations().filter(({ piece }) => piece.item);
    if (equipped.length)
      html +=
        '<p class="inventory-heading">已装备</p>' +
        equipped
          .map(
            ({ piece, loc }) =>
              `<div class="inventory-item equipped-row"><span>◆ ${esc(piece.item_name || piece.item)}</span><small>已装备给 ${esc(piece.name)}${loc[0] === "b" ? " · 备战席" : ""}</small></div>`,
          )
          .join("");
    if (items.craftable.length)
      html +=
        '<p class="inventory-heading">可合成装备</p>' +
        items.craftable
          .map(
            (item) =>
              `<button class="craft-button" data-craft="${esc(item.key)}" ${!canPrep() ? "disabled" : ""}><span><b>${esc(item.name)}</b><span class="item-description">${esc(item.recipe)} · ${esc(item.effect)}</span></span><small>合成 +</small></button>`,
          )
          .join("");
    $("inventory").innerHTML =
      html || '<p class="empty-copy">每轮结算获得随机装备、材料或技能机。</p>';
  }
  function setSystemTab(value) {
    if (!["augments", "techniques", "items", "growth"].includes(value)) return;
    systemTab = value;
    for (const name of ["augments", "techniques", "items", "growth"]) {
      $(name + "-panel").hidden = name !== value;
      $(name + "-tab").setAttribute("aria-selected", String(name === value));
      $(name + "-tab").tabIndex = name === value ? 0 : -1;
    }
  }
  function ownedLocations() {
    const rows = [];
    state.board.forEach((row, r) =>
      row.forEach((piece, c) => {
        if (piece) rows.push({ piece, loc: `g${r},${c}` });
      }),
    );
    state.bench.forEach((piece, i) => {
      if (piece) rows.push({ piece, loc: `b${i}` });
    });
    return rows;
  }
  function renderSystems() {
    const pending = state.augments?.pending || [];
    const picked = state.augments?.selected || [];
    $("augments-count").textContent = pending.length
      ? `${pending.length} 待选`
      : picked.length;
    $("augments-count").classList.toggle("pending", pending.length > 0);
    $("augments").innerHTML =
      pending
        .map(
          (reward) =>
            `<p class="system-note">第 ${Number(reward.round)} 轮 · 选择一项，本局持续生效</p><div class="augment-options">${reward.options.map((option) => `<button class="augment-card" data-augment="${esc(option.id)}" data-reward="${esc(reward.id)}" ${!canPrep() ? "disabled" : ""}><span class="augment-sigil">✦</span><strong>${esc(option.name)}</strong><p>${esc(option.description)}</p><span class="augment-pick">选择强化 ↗</span></button>`).join("")}</div><button class="augment-reroll" data-augment-reroll="${esc(reward.id)}" ${!canPrep() || reward.rerolled ? "disabled" : ""}>${reward.rerolled ? "已换过一批 · 每轮限一次" : "换一批 ↻"}</button>`,
        )
        .join("") +
      (picked.length
        ? `<div class="selected-augments">${picked.map((option) => `<div><strong>✦ ${esc(option.name)}</strong>${option.current ? `<span class="augment-current">${esc(option.current)}</span>` : ""}<p>${esc(option.description)}</p></div>`).join("")}</div>`
        : "") +
      (!pending.length && !picked.length
        ? '<p class="empty-copy">海克斯在第 1、7、13 轮提供三选一强化。</p>'
        : "");
    const techniques = Array.isArray(state.techniques)
      ? state.techniques
      : state.techniques?.inventory || [];
    $("techniques-count").textContent = `${techniques.reduce((n, t) => n + (Number(t.count) || 0), 0)} 台`;
    $("techniques").innerHTML =
      '<p class="system-note">每只精灵有一个固定原生位和一个学习位，两者可同时生效。学习技能每场最多触发一次；替换只改变学习位，不覆盖原生技能。优先消耗一台技能机免费学习，没有机器可花 2 金币；替换不返还旧技能。</p>' +
      techniques
        .map((t) => {
        const eligible = ownedLocations().filter(({ piece }) => piece.technique?.id !== t.id && (Array.isArray(piece.learnable)
            ? piece.learnable.includes(t.id)
            : piece.learnable !== false));
          const choices = eligible
            .map(
              ({ piece, loc }) =>
                `<option value="${loc}" ${selected === loc ? "selected" : ""}>${esc(piece.name)} ${"★".repeat(starsOf(piece))}${piece.technique ? " · 已学" + esc(piece.technique.name) : ""}</option>`,
            )
            .join("");
          const hasMachine = Number(t.count) > 0;
          return `<div class="technique-card${hasMachine ? " stocked" : ""}"><div><strong>${esc(t.name)} <small>${hasMachine ? `技能机 ×${Number(t.count)}` : `${Number(t.cost) || 2} 金币`}</small></strong><p>${esc(t.description)}</p>${t.compatibility ? `<p>${esc(t.compatibility)}</p>` : ""}</div><div class="learn-controls"><select id="learn-${esc(t.id)}" aria-label="${esc(t.name)}学习目标" ${!canPrep() || !eligible.length ? "disabled" : ""}>${choices || '<option value="">先招募兼容的精灵</option>'}</select><button data-learn="${esc(t.id)}" ${!canPrep() || !eligible.length || (!hasMachine && state.you.gold < (t.cost || 2)) ? "disabled" : ""}>${hasMachine ? "使用技能机" : `学习 · ${Number(t.cost) || 2} 金`}</button></div></div>`;
        })
        .join("") +
      (!techniques.length
        ? '<p class="empty-copy">技能机将在野怪轮提供。你可以先完成阵容部署。</p>'
        : "");
    $("items-count").textContent =
      state.items.finished.length + state.items.craftable.length;
    renderGrowth();
    setSystemTab(systemTab);
  }
  function renderGrowth() {
    const data = state.growth,
      tab = $("growth-tab");
    if (!state.arena || !data) {
      tab.hidden = true;
      $("growth-count").textContent = "0";
      return;
    }
    tab.hidden = false;
    if (data.error) {
      $("growth-count").textContent = "!";
      $("growth").innerHTML = `<p class="empty-copy">${esc(data.error)}</p>`;
      return;
    }
    const challenges = Array.isArray(data.challenges) ? data.challenges : [],
      done = challenges.filter((c) => c.unlocked).length,
      stats = data.stats || {};
    $("growth-count").textContent = `${done}/${challenges.length}`;
    const cards = challenges
      .map(
        (c) =>
          `<div class="growth-challenge${c.unlocked ? " done" : ""}"><div class="growth-challenge-head"><strong>${esc(c.name)}</strong><span>${Math.min(Number(c.current) || 0, Number(c.target) || 1)} / ${Number(c.target) || 1}</span></div><p>${esc(c.description)}</p><div class="growth-progress"><i style="width:${Math.min(100, ((Number(c.current) || 0) / (Number(c.target) || 1)) * 100)}%"></i></div><small class="growth-reward">${c.unlocked ? "已解锁" : "解锁"} · ${c.rewards?.length ? esc(c.rewards.join(" / ")) : "纪念进度 · 无数值奖励"}</small></div>`,
      )
      .join("");
    const unlocks = [
      ...(data.augments || []).map(
        (a) =>
          `<div class="growth-unlock${a.unlocked ? " done" : ""}"><strong>✦ ${esc(a.name)}</strong><p>${esc(a.description)}</p><small>${a.unlocked ? "已进入本局海克斯候选池" : "海克斯候选 · 完成挑战解锁"}</small></div>`,
      ),
      ...(data.traits || []).map(
        (t) =>
          `<div class="growth-unlock${t.unlocked ? " done" : ""}"><strong>◎ ${esc(t.name)}（${esc(t.species_name || "")}）</strong><p>${esc(t.description)}</p><small>${t.unlocked ? "已可在准备期选择" : "互斥特性 · 完成挑战解锁"}</small></div>`,
      ),
    ].join("");
    $("growth").innerHTML =
      '<p class="system-note">跨局挑战只解锁选项与收藏，不提供永久数值加成；解锁从下一局开始生效，机器人始终使用基础候选池。</p>' +
      `<p class="growth-stats">竞技 ${Number(stats.runs) || 0} 局 · 夺冠 ${Number(stats.wins) || 0} 次 · 累计击杀 ${Number(stats.kills) || 0} · 单局最高连胜 ${Number(stats.streak) || 0} · 点亮羁绊 ${Number(stats.bonds) || 0} 组 · 上场 ${Number(stats.species) || 0}/48 种</p>` +
      (data.new_this_run?.length
        ? `<p class="growth-new">本次新完成挑战：${esc(data.new_this_run.join("、"))}</p>`
        : "") +
      `<div class="growth-grid">${cards}</div>` +
      '<h3 class="growth-subhead">可解锁内容</h3>' +
      `<div class="growth-grid">${unlocks}</div>`;
  }
  function rewardCards(row) {
    return `<div class="loot-cards">${(row?.grants || []).map((g) => `<div class="loot-card ${esc(g.kind)}"><span class="loot-icon" aria-hidden="true">${g.kind === "technique" ? "◎" : g.kind === "item" ? "◆" : "✧"}</span><div><strong>${esc(g.name)}</strong><small>${g.kind === "technique" ? "技能机 · 免费学习一次" : g.kind === "item" ? "成品装备 · 可直接装备" : "装备组件 · 可用于合成"}</small></div></div>`).join("")}</div>`;
  }
  function renderCombinations() {
    const data = state.combinations;
    const rows = Array.isArray(data?.entries) ? data.entries : [];
    const traits = rows.filter(row => row.source_kind === "trait");
    const base = rows.filter(row => row.stage === "base" && row.source_kind !== "trait");
    const upgrade = rows.filter(row => row.stage !== "base" && row.source_kind !== "trait");
    $("combination-check").hidden = !rows.length;
    $("combination-count").textContent = `${base.filter(row => row.status === "ready").length} 条基础配合已具备 · ${upgrade.filter(row => row.status === "ready").length} 项补强已具备`;
    function facts(label, values, kind) {
      if (!values?.length) return "";
      return `<div class="combination-facts ${kind}"><strong>${label}</strong><ul>${values.map(value => `<li>${esc(value)}</li>`).join("")}</ul></div>`;
    }
    function group(title, entries, stage) {
      if (!entries.length) return "";
      return `<section class="combination-stage ${stage}"><h3>${title}</h3>${entries.map(row => {
        const ready = row.status === "ready";
        return `<article class="combination-row${ready ? " ready" : ""}"><div class="combination-heading"><strong>${esc(row.name)}</strong><span>${stage === "trait" ? "已选择 · 条件触发" : ready ? "配置已具备" : "尚缺配置"}</span></div><p>${esc(row.detail)}</p>${facts("已具备", row.present || row.units?.map(unit => "已上场：" + unit.name), "present")}${facts("缺组件 / 配置", row.missing, "missing")}${facts("需战斗时机 / 对手条件", row.battle_conditions, "conditions")}${facts("互斥 / 取舍", row.conflicts, "conflicts")}</article>`;
      }).join("")}</section>`;
    }
    $("combinations").innerHTML = group("基础配合 · 本命与属性先配合", base, "base") + group("按战局补强 · 装备、天气与海克斯", upgrade, "upgrade") + group("个体特性 · 查看触发与取舍", traits, "trait") + `<p class="combination-note">${esc(data?.note || "配置齐全仍需战斗中的有效命中、治疗和站位条件。")}</p>`;
  }
  function renderComponentChoices() {
    const container = $("component-choices");
    const rewards = Array.isArray(state.component_choices) ? state.component_choices : [];
    container.hidden = !rewards.length;
    if (!rewards.length) { container.innerHTML = ""; return; }
    const pending = rewards.filter(reward => reward.status === "pending");
    const stock = new Map((state.items?.components || []).map(part => [part.key || part.id, Number(part.n) || 0]));
    function craftAfter(option, item) {
      return (item.recipes || []).some(pair => {
        const counts = new Map(stock);
        counts.set(option.id, (counts.get(option.id) || 0) + 1);
        for (const part of pair) { const key = typeof part === "string" ? part : part.id; const n = counts.get(key) || 0; if (!n) return false; counts.set(key, n - 1); }
        return pair.length === 2;
      });
    }
    container.innerHTML = `<div class="component-choice-heading"><div><span class="eyebrow">COMPONENT SUPPLY</span><h3>定向组件补给</h3></div><span>${pending.length ? pending.length + " 次待领" : "已处理"}</span></div><p class="component-choice-note">第3、6轮实际结算后各一次八选一，独立于胜2份 / 败1份的随机战利品。${canPrep() ? "选择所缺材料，领取后加入仓库。" : "下一准备期可领取；当前暂不能选择。"}</p>${rewards.map(reward => {
      if (reward.status !== "pending") { const chosen = (reward.options || []).find(option => option.id === reward.choice); return `<p class="component-choice-receipt">第 ${Number(reward.round)} 轮 · ${reward.status === "claimed" ? "已领取 " + esc(chosen?.name || reward.choice) : reward.closed_reason === "eliminated" ? "已淘汰，补给关闭" : "对局已结束，补给关闭"}</p>`; }
      return `<div class="component-choice-round"><strong>第 ${Number(reward.round)} 轮 · 选择一件组件</strong><div class="component-choice-options">${(reward.options || []).map(option => {
        const recipes = option.recipe_details || [];
        const ready = recipes.filter(item => !(state.items?.crafting_blocked || []).includes(item.id) && craftAfter(option, item));
        return `<button class="component-choice-option${ready.length ? " craft-ready" : ""}" data-component-choice="${esc(option.id)}" data-component-reward="${esc(reward.id)}" ${!canPrep() ? "disabled" : ""}><strong>${esc(option.name)}</strong><span>可合成：${recipes.map(item => esc(item.name)).join("、") || "查看合成图"}</span>${ready.length ? `<small>领取后可合成：${ready.map(item => esc(item.name)).join("、")}</small>` : '<small>补一块材料 · 再按配方合成</small>'}</button>`;
      }).join("")}</div></div>`;
    }).join("")}<a href="/pokedex?tab=items&view=recipes">查看完整装备合成图 ↗</a>`;
  }
  function combinationSide(data, fields, teamName, guidance = "") {
    let content;
    if (!data) content = '<p class="combination-note">这份战果未记录该方联动统计，不能用零值代替。</p>';
    else {
    const rows = Array.isArray(data.by_key) ? data.by_key : [];
    const totals = [["total_energy", "实际回能"], ["total_shield", "新增护盾"], ["absorbed", "护盾实吸"]];
    if (Object.hasOwn(data, "total_damage")) totals.push(["total_damage", "已结算的强化额外生命损失"], ["damage_absorbed", "强化部分被盾吸收"], ["total_charges", "反击蓄力"], ["total_vulnerable", "成功施加易伤"]);
    if (Object.hasOwn(data, "total_spreads")) totals.push(["total_spreads", "成功异常传播"], ["total_tempo_stacks", "有效普攻增层"], ["total_offense_buffs", "直接攻击鼓舞次数"]);
    if (Object.hasOwn(data, "total_healing")) totals.push(["total_healing", "特性 / 装备实际治疗"], ["total_mitigated", "实际避免生命损失"], ["total_cleanses", "实际净化"], ["total_statuses", "成功施加异常"], ["total_accuracy_saves", "修正闪避"], ["total_weakens", "物理压制目标"]);
    const visible = rows.filter((row) => row.triggers || row.absorbed || row.charges);
    function benefit(row) {
      const metrics = [];
      if (row.energy) metrics.push(`回能 ${Number(row.energy)}`);
      if (row.shield) metrics.push(`新增盾 ${Number(row.shield)}`);
      if (row.absorbed) metrics.push(`护盾实吸 ${Number(row.absorbed)}`);
      if (row.id === "ward_bracer") metrics.push(`蓄力 ${Number(row.charges) || 0} 次`, `强化普攻 ${Number(row.triggers) || 0} 次`, `额外生命损失 ${Number(row.damage) || 0}`, `强化部分被盾吸收 ${Number(row.damage_absorbed) || 0}`);
      if (row.vulnerable) metrics.push(`成功易伤 ${Number(row.vulnerable)} 次`);
      if (row.spreads) metrics.push(`成功传播 ${Number(row.spreads)} 次`);
      if (row.tempo_stacks) metrics.push(`有效普攻增层 ${Number(row.tempo_stacks)} 次（清层后可重新累计）`);
      if (row.offense_buffs) metrics.push(row.id === "trait_guts" ? `毅力 ${Number(row.offense_buffs)} 次 · 3秒物理直接伤害+20%` : row.id === "bond_inspiration" ? `鼓舞 ${Number(row.offense_buffs)} 次 · 3秒直接攻击增益` : `鼓舞 ${Number(row.offense_buffs)} 次 · 每次3秒直接攻击+25%`);
      if (row.healing) metrics.push(`实际治疗 ${Number(row.healing)}`);
      if (row.cleanses) metrics.push(`实际净化 ${Number(row.cleanses)} 次`);
      if (row.statuses) metrics.push(`成功异常 ${Number(row.statuses)} 次`);
      if (row.mitigated || ["trait_sturdy", "trait_magic_guard"].includes(row.id)) metrics.push(`实际避免生命损失 ${Number(row.mitigated)}`);
      if (row.accuracy_saves) metrics.push(`修正闪避 ${Number(row.accuracy_saves)} 次`);
      if (row.weakens) metrics.push(`物理压制 ${Number(row.weakens)} 名目标`);
      if (row.id.startsWith("trait_") && row.damage) metrics.push(`本次命中的强化额外生命损失 ${Number(row.damage)}`);
      if (row.id.startsWith("trait_") && row.damage_absorbed) metrics.push(`强化部分被盾吸收 ${Number(row.damage_absorbed)}`);
      return `<p class="combination-benefit"><strong>${row.id.startsWith("trait_") ? "特性 · " : ""}${esc(row.name)} · ${Number(row.triggers) || 0} 条生效记录</strong><span>${metrics.join(" · ")}</span></p>`;
    }
    const brief = totals.filter(([key]) => Number(data[key]) > 0).slice(0, 4);
    content = `${brief.length ? `<div class="combination-brief">${brief.map(([key, label]) => `<span><b>${Number(data[key])}</b> ${label}</span>`).join("")}</div>` : ""}${visible.map(benefit).join("") || '<p class="combination-note">本轮未触发联动。检查真实吸盾、异常、有效治疗、击退落点与临战站位，再调整构筑。</p>' + guidance}<details class="combination-metrics"><summary>完整指标 · 含零值</summary><div class="combination-totals">${totals.map(([key, label]) => `<div><b>${Number(data[key]) || 0}</b><span>${label}</span></div>`).join("")}</div></details><details class="combination-accounting"><summary>统计口径与边界</summary><p class="combination-note">只统计实际到账。一项特性可同时产生治疗与回能等多条生效记录，记录数不等于触发机会数。强化伤害只列单次已结算命中的额外部分，不重复计入整次普攻或命中，也不生成第二次攻击；特性与装备治疗只统计真实回复，防伤单列实际避免生命损失，不算护盾或治疗；易伤、异常传播、节拍增层和鼓舞只记录真实生效次数，不推算额外伤害；连击与节拍器共享同目标层数；这里计累计增层，非当前层数，不重复计装备与羁绊。鼓舞不强化毒/灼伤或岩钉；毅力只强化物理直接伤害。盾到期与过量部分不算收益。</p></details>`;
    }
    if (fields) {
      const facts = [["triggers", "岩钉触发"], ["damage", "实际生命损失"], ["absorbed", "护盾吸收"], ["avoided", "厚底靴免疫"], ["cleared", "清除格数"]];
      content += `<details class="combination-fields"><summary>地形联动 · 入格 ${Number(fields.triggers) || 0} 次 · 实际生命损失 ${Number(fields.damage) || 0}</summary><div class="combination-totals">${facts.map(([key, label]) => `<div><b>${Number(fields[key]) || 0}</b><span>${label}</span></div>`).join("")}</div><p class="combination-note">岩钉伤害统计${esc(teamName)}铺场；免疫和清场统计${esc(teamName)}队员。只有真实入格触发，站立不反复扣血。</p></details>`;
    } else content += '<p class="combination-note">地形联动未记录。</p>';
    return content;
  }
  function combinationGuidance() {
    const bondRows = Array.isArray(state?.bonds?.entries) ? state.bonds.entries : null;
    const rows = bondRows || (Array.isArray(state?.synergies) ? state.synergies : [])
      .map(s => ({name: s.zh || s.name, n: Number(s.n) || 0, tier: Number(s.tier) || 0,
        next: s.next == null ? null : Number(s.next), need: Number(s.need) || 0,
        thresholds: [], candidates: []}));
    const near = rows.filter(row => row.next != null && row.need > 0)
      .sort((a, b) => a.need - b.need || b.n - a.n).slice(0, 2);
    if (!near.length)
      return '<p class="combination-guide">羁绊已点亮到当前可达档位。打开准备区「联动检查」，核对基础配合还缺哪些组件与战斗时机。</p>';
    const bench = new Set((state?.bench || []).filter(Boolean).map(p => Number(p.sid)));
    const shop = new Set((state?.shop || []).filter(Boolean).map(p => Number(p.sid)));
    const catalog = state?.arena?.catalog || [];
    const nameOf = sid => catalog.find(p => Number(p.sid) === Number(sid))?.name || "";
    return `<ul class="combination-guide">${near.map(row => {
      const nextTier = (row.thresholds || []).find(t => Number(t.count) === Number(row.next));
      const effect = nextTier?.effect ? `：${esc(nextTier.effect)}` : "";
      const sources = (row.candidates || []).map(Number)
        .filter(sid => bench.has(sid) || shop.has(sid)).slice(0, 2);
      const hint = sources.length
        ? `（${sources.map(sid => `${esc(nameOf(sid))}在${bench.has(sid) ? "备战席" : "商店"}`).filter(text => !text.startsWith("在")).join("、")}）`
        : "";
      return `<li>${row.tier
        ? `当前阵容「${esc(row.name)}」已激活 ${Number(row.tier)} 种档，再补 ${Number(row.need)} 位不同伙伴点亮 ${Number(row.next)} 种档`
        : `当前阵容再上场 ${Number(row.need)} 位不同伙伴即可点亮「${esc(row.name)}」`}${effect}${hint}</li>`;
    }).join("")}</ul>`;
  }
  function bondSparkRows(units) {
    const catalog = Array.isArray(state?.arena?.bond_catalog) ? state.arena.bond_catalog : [];
    if (!catalog.length || !Array.isArray(units)) return null;
    const deployed = new Set(units.filter(unit => Number(unit.team) === 0).map(unit => Number(unit.sid)));
    return catalog.map(bond => {
      const members = new Set((bond.members || []).map(Number));
      const n = [...deployed].filter(sid => members.has(sid)).length;
      if (!n) return null;
      const thresholds = [...(bond.thresholds || [])].sort((a, b) => Number(a.count) - Number(b.count));
      const reached = thresholds.filter(t => n >= Number(t.count));
      const next = thresholds.find(t => Number(t.count) > n) || null;
      return {name: bond.name, category: bond.category, n,
        tier: reached.length ? Number(reached.at(-1).count) : 0,
        effect: reached.at(-1)?.effect || "",
        next: next ? Number(next.count) : null,
        need: next ? Number(next.count) - n : 0,
        nextEffect: next?.effect || ""};
    }).filter(Boolean).sort((a, b) => Number(b.tier > 0) - Number(a.tier > 0)
      || a.need - b.need || b.n - a.n || String(a.name).localeCompare(String(b.name), "zh-CN"));
  }
  function renderBondSpark(scope, units) {
    const container = $(`${scope}-bonds`);
    if (!container) return;
    const rows = bondSparkRows(units);
    if (!rows) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }
    const active = rows.filter(row => row.tier > 0);
    const pending = rows.filter(row => !row.tier && row.need > 0).slice(0, 3);
    container.hidden = false;
    container.innerHTML = `<div class="bond-spark-heading"><h3>羁绊点亮 · 上场阵容</h3><span>按上场不同物种计数，与准备区口径一致</span></div>${
      active.map(row => `<p class="bond-spark-row on"><strong>${esc(row.name)} <small>${Number(row.n)} 种${row.category === "tactic" ? " · 战术" : ""}</small></strong><span>已激活 ${Number(row.tier)} 种档 · ${esc(row.effect)}${row.next ? ` · 再补 ${Number(row.need)} 位升 ${Number(row.next)} 档` : " · 已封顶"}</span></p>`).join("") ||
      '<p class="bond-spark-row"><span>本场没有点亮任何羁绊档位。</span></p>'}${
      pending.map(row => `<p class="bond-spark-row"><strong>${esc(row.name)} <small>${Number(row.n)} / ${Number(row.next)} 种</small></strong><span>还差 ${Number(row.need)} 位不同伙伴点亮：${esc(row.nextEffect)}</span></p>`).join("")}`;
  }
  // 下局建议：全部由 state / 战报里的真实记录推导，数据缺一项就少一条，不凑数。
  function adviceTeamTotal(stats, team, metric) {
    const row = (stats?.totals || []).find(entry => Number(entry.team) === team);
    return statValue(row?.[metric]) ?? 0;
  }
  function adviceStreakBonus(streak) {
    const length = Math.abs(Number(streak) || 0);
    for (const [threshold, gold] of [[6, 3], [4, 2], [2, 1]])
      if (length >= threshold) return gold;
    return 0;
  }
  function adviceDefeatTips(defeat) {
    const tips = [];
    const by = defeat?.defeated_by;
    if (by) {
      const synergy = by.synergy ? `（${esc(by.synergy)}主羁绊）` : "";
      tips.push(`败于 ${esc(trainerName(by.name).trim())}${synergy}，第 ${Number(by.round)} 轮被扣 ${Number(by.damage)} 血：下局优先补克制其主羁绊的伙伴，或给前排配护盾、防守型装备。`);
    }
    const threat = defeat?.top_threat;
    if (threat) {
      const key = trainerName(threat.name).trim();
      let theirs = 0, total = 0;
      for (const row of Array.isArray(state?.battle_history) ? state.battle_history : []) {
        if (!recordedStats(row.statistics)) continue;
        const damage = adviceTeamTotal(row.statistics, 1, "damage_dealt");
        total += damage;
        if (trainerName(row.opp_name).trim() === key) theirs += damage;
      }
      const share = total > 0 && theirs > 0 ? Math.round(theirs / total * 100) : null;
      tips.push(share == null
        ? `最大威胁 ${esc(key)} 累计打掉你 ${Number(threat.damage)} 血：下次对位优先集火其输出核心。`
        : `最大威胁 ${esc(key)} 累计打掉你 ${Number(threat.damage)} 血，已记录战报中其队伍输出占我方总承伤 ${share}%：下次对位优先集火其输出核心。`);
    }
    return tips;
  }
  function adviceMvpTip(stats, won) {
    if (!recordedStats(stats)) return null;
    const units = stats.units.filter(unit => Number(unit.team) === 0);
    if (units.length < 2) return null;
    const total = units.reduce((sum, unit) => sum + (statValue(unit.damage_dealt) ?? 0), 0);
    if (total <= 0) return null;
    const top = units.reduce((best, unit) =>
      (statValue(unit.damage_dealt) ?? 0) > (statValue(best.damage_dealt) ?? 0) ? unit : best);
    const pct = Math.round((statValue(top.damage_dealt) ?? 0) / total * 100);
    if (pct <= 50) return null;
    return won
      ? `${pct}% 的输出来自 ${esc(top.name)}，是这支队伍的核心：优先给它升星、配齐装备，把优势滚到终局。`
      : `输出过度集中在 ${esc(top.name)} 身上（占全队 ${pct}%）：给它配保护型装备，或补一个第二输出点分担压力。`;
  }
  function adviceHealingTip(lost, stats, round) {
    if (!lost) return null;
    const rows = (Array.isArray(state?.battle_history) ? state.battle_history : [])
      .filter(row => row.winner === 1 && recordedStats(row.statistics) && Number(row.round) !== Number(round));
    if (recordedStats(stats)) rows.push({statistics: stats});
    const recent = rows.slice(-3);
    if (!recent.length) return null;
    if (recent.some(row => adviceTeamTotal(row.statistics, 0, "healing_done") > 0)) return null;
    return `近 ${recent.length} 场失利我方有效治疗为 0：队伍没有回复手段，考虑辅助型伙伴或吸血、回复装备。`;
  }
  function adviceBondTip() {
    const entries = Array.isArray(state?.bonds?.entries) ? state.bonds.entries
      : (Array.isArray(state?.synergies) ? state.synergies : []).map(s => ({name: s.zh || s.name,
          n: Number(s.n) || 0, tier: Number(s.tier) || 0, next: s.next == null ? null : Number(s.next),
          need: Number(s.need) || 0, thresholds: [], candidates: []}));
    const near = entries.filter(row => row.next != null && Number(row.need) > 0)
      .sort((a, b) => Number(a.need) - Number(b.need) || Number(b.n) - Number(a.n))[0];
    if (!near) return null;
    const bench = new Set((state?.bench || []).filter(Boolean).map(p => Number(p.sid)));
    const shop = new Set((state?.shop || []).filter(Boolean).map(p => Number(p.sid)));
    const catalog = state?.arena?.catalog || [];
    const nameOf = sid => catalog.find(p => Number(p.sid) === Number(sid))?.name || "";
    const sources = (near.candidates || []).map(Number)
      .filter(sid => bench.has(sid) || shop.has(sid)).slice(0, 2);
    const hint = sources.length
      ? `；${sources.map(sid => `${esc(nameOf(sid))}就在${bench.has(sid) ? "备战席" : "商店"}`).join("、")}`
      : "";
    const effect = (near.thresholds || []).find(t => Number(t.count) === Number(near.next))?.effect;
    return `「${esc(near.name)}」还差 ${Number(near.need)} 位不同伙伴点亮 ${Number(near.next)} 种档${effect ? `（${esc(effect)}）` : ""}${hint}：下局见到优先拿下。`;
  }
  function adviceConsolidateTip(stats) {
    const active = (bondSparkRows(stats?.units) || []).find(row => row.tier > 0);
    if (!active) return null;
    return `「${esc(active.name)}」已点亮 ${Number(active.tier)} 种档（${esc(active.effect)}）：下局继续围绕它补强${active.next ? `，再补 ${Number(active.need)} 位升 ${Number(active.next)} 档` : "，已封顶保持人口质量"}。`;
  }
  function adviceEconomyTip(won) {
    const streak = Number(state?.you?.streak) || 0;
    const gold = Number(state?.you?.gold) || 0;
    if (!won && streak <= -2) {
      const interest = gold >= 50 ? "利息已吃满" : `再攒 ${10 - gold % 10} 金利息再 +1`;
      return `已连败 ${-streak} 场，连败补贴每轮 +${adviceStreakBonus(streak)} 金；现有 ${gold} 金，${interest}：稳住经济，别急着刷新商店。`;
    }
    if (won && streak >= 2)
      return `已连胜 ${streak} 场，连胜奖励每轮 +${adviceStreakBonus(streak)} 金：保持人口与强度，把经济优势滚下去。`;
    return null;
  }
  function nextRoundAdvice({won = false, lost = false, defeat = null, stats = null, round = null} = {}) {
    return [
      ...adviceDefeatTips(defeat),
      adviceMvpTip(stats, won),
      adviceHealingTip(lost || !!defeat?.defeated_by, stats, round),
      won ? adviceConsolidateTip(stats) : null,
      adviceBondTip(),
      adviceEconomyTip(won),
    ].filter(Boolean).slice(0, 3);
  }
  function renderAdvice(scope, tips, won) {
    const container = $(`${scope}-advice`);
    if (!container) return;
    if (!tips.length) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }
    container.hidden = false;
    container.innerHTML = `<div class="bond-spark-heading"><h3>下局建议</h3><span>${won ? "巩固方向" : "短板归因"} · 由本局真实记录推导</span></div><ul class="advice-list">${tips.map(tip => `<li>${tip}</li>`).join("")}</ul>`;
  }
  function showCombinationSummary(meta, scope = "battle", teams = ["我方", "敌方"]) {
    const container = $(`${scope}-combinations`);
    if (!container) return;
    container.hidden = false;
    const guidance = ["battle", "history"].includes(scope) ? combinationGuidance() : "";
    container.innerHTML = `<h3>双方联动收益</h3><p class="combination-note">当场实际结算，按来源区分；阵容效果不能代替实战触发。</p>${teams.map((name, team) => `<details class="combination-team ${team ? "enemy" : "friendly"}"${team === 0 ? " open" : ""}><summary>${team === 0 ? "●" : "▲"} ${esc(name)}联动收益 <span>${(team === 0 ? meta?.combinations : meta?.enemy_combinations) ? "实际记录" : "未记录"}</span></summary>${combinationSide(team === 0 ? meta?.combinations : meta?.enemy_combinations, team === 0 ? meta?.fields : meta?.enemy_fields, name, team === 0 ? guidance : "")}</details>`).join("")}`;
  }
  function renderRoundLoot() {
    const rows = state.round_rewards || [];
    const latest = rows[rows.length - 1];
    $("round-loot").hidden = !latest;
    $("round-loot").innerHTML = latest ? `<div class="loot-heading"><strong>第 ${latest.round} 轮战利品</strong><span>${latest.result === "win" ? "胜利 · 2 份" : latest.result === "loss" ? "失利 · 1 份" : "平局 · 1 份"}已入仓</span></div>${rewardCards(latest)}` : "";
  }
  function scoutPieces(pieces, label, owner) {
    const flat = (pieces || []).flat().filter(Boolean);
    const prefix = label === "备战席" ? "b" : "u";
    return `<h3>${label} · ${flat.length} 只</h3><div class="scout-unit-grid">${flat.map((p, index) => `<button type="button" class="scout-unit${p.shiny ? " shiny" : ""}" data-scout-unit="${prefix}${index}" data-scout-owner="${Number(owner.seat)}" aria-controls="scout-unit-detail" aria-label="查看${esc(p.name)}的完整情报"><img src="${spriteOf(p)}" alt=""><span class="scout-unit-main"><strong>${esc(p.name)} <span class="detail-star">${"★".repeat(starsOf(p))}${p.shiny ? " ✦" : ""}</span></strong><span class="scout-unit-role role-${roleOf(p)}">${roleNames[roleOf(p)]} · ${attackStyle(p)} ${Number(p.range) || "—"}格 · ${esc((p.types || []).join(" / "))}</span><span class="scout-unit-loadout">${p.item_name ? "◆ " + esc(p.item_name) : "未装备"}${p.trait ? " · ◎ " + esc(p.trait.name) : ""}</span><span class="scout-unit-skills">${esc(nativeOf(p).name)}${p.technique ? " / " + esc(p.technique.name) : ""}</span><small>完整效果 →</small></span></button>`).join("") || '<p class="empty-copy">暂无精灵。</p>'}</div>`;
  }
  const scoutName = (p) => p?.human ? "新叶训练家" : trainerName(p?.name) || "当轮对手";
  const scoutAlive = (p) => p.alive ?? p.hp > 0;
  function scoutSubject() {
    if (scoutSeat === -1) return {...state.opponent, seat: -1, current_opponent: true, board: (state.opponent?.rows || []).flat().filter(Boolean), bench: [], recent_reports: []};
    const subject = (state?.scouting || []).find(p => p.seat === scoutSeat);
    if (subject?.battle_snapshot?.rows) return {...subject, rows: subject.battle_snapshot.rows, board: subject.battle_snapshot.rows.flat().filter(Boolean)};
    return subject;
  }
  function scoutReport() {
    return (scoutSubject()?.recent_reports || [])[scoutReportIndex] || null;
  }
  function scoutBadges(p) {
    return `${p.human ? '<span class="scout-badge own">我方</span>' : ""}${p.current_opponent ? `<span class="scout-badge rival">${p.ghost_opponent ? "本轮幽灵镜像" : "本轮对手"}</span>` : ""}${p.hp != null && !scoutAlive(p) ? `<span class="scout-badge out">已淘汰${p.rank ? " · 第" + Number(p.rank) + "名" : ""}</span>` : ""}`;
  }
  function scoutSynergies(p, detailed = false) {
    const rows = p.bonds?.entries || p.synergies || [];
    const active = rows.filter(s => s.tier);
    if (!detailed) return active.map(s => `<span title="${esc(s.effect)}">${esc(s.name || s.zh)} ${Number(s.n)}</span>`).join("") || '<span class="inactive">暂无激活羁绊</span>';
    return `<section class="scout-effects" aria-label="羁绊完整效果"><h3>队伍羁绊 · 当前公开配置</h3><p class="scout-section-note">${esc(p.bonds?.note || "当前公开阵容的成员计数与已激活效果。")}</p>${rows.map(row => `<details class="scout-effect${row.tier ? " active" : ""}"><summary><span>${esc(row.name || row.zh)}</span><small>${row.tier ? "已激活 " + Number(row.tier) + " 种档" : "未激活"} · ${Number(row.n)}${row.next ? " / " + Number(row.next) : ""}</small></summary><p>${esc(row.effect || "尚未达到激活门槛。")}</p>${(row.thresholds || []).map(tier => `<p class="scout-effect-tier"><strong>${Number(tier.count)}种档</strong> ${esc(tier.effect)}</p>`).join("")}</details>`).join("") || '<p class="empty-copy">暂无羁绊记录。</p>'}</section>`;
  }
  function scoutBoard(p, mini = false) {
    if (!p.rows) return '<p class="empty-copy">当前数据未提供站位。</p>';
    const direction = `<span class="scout-front">${p.human ? "▲" : "▼"} 接敌方向 · 前排在${p.human ? "上" : "下"}方</span>`;
    return `<span class="scout-formation ${p.human ? "own" : "enemy"}${mini ? " miniature" : ""}">${p.human ? direction : ""}<span class="scout-board-rows">${p.rows.map((row, r) => `<span class="scout-board-row">${mini ? "" : `<span class="scout-row-label">${r === (p.human ? 0 : p.rows.length - 1) ? "前排" : r === (p.human ? p.rows.length - 1 : 0) ? "后排" : "中排"}</span>`}<span class="scout-board-cells">${row.map((unit, c) => {
      const info = unit ? `${unit.name} · ${starsOf(unit)}星 · ${roleNames[roleOf(unit)]} · ${attackStyle(unit)}${unit.item_name ? " · 装备" + unit.item_name : ""}${unit.technique ? " · 学习" + unit.technique.name : ""}` : "空位";
      const interactive = unit && !mini;
      const tag = interactive ? "button" : "span";
      return `<${tag} class="scout-cell${unit ? " occupied role-" + roleOf(unit) : ""}${unit?.shiny ? " shiny" : ""}" ${interactive ? `type="button" data-scout-unit="g${r},${c}" data-scout-owner="${Number(p.seat)}" aria-controls="scout-unit-detail"` : 'role="img"'} aria-label="第${r + 1}行第${c + 1}列：${esc(info)}${interactive ? "，查看完整情报" : ""}" title="${esc(info)}">${unit ? `<img src="${spriteOf(unit)}" alt=""><small>${"★".repeat(starsOf(unit))}${unit.shiny ? " ✦" : ""}</small>${unit.item_name ? `<i class="scout-equipped" title="已装备：${esc(unit.item_name)}">◆</i>` : ""}${unit.technique ? `<i class="scout-technique" title="已学习：${esc(unit.technique.name)}">◎</i>` : ""}` : ""}</${tag}>`;
    }).join("")}</span></span>`).join("")}</span>${!p.human ? direction : ""}</span>`;
  }
  function scoutOverview(seats) {
    const sorted = [...seats].sort((a, b) => Number(b.current_opponent || false) - Number(a.current_opponent || false) || Number(b.human) - Number(a.human) || Number(scoutAlive(b)) - Number(scoutAlive(a)) || b.hp - a.hp || a.seat - b.seat);
    return `<div class="scout-overview-heading"><strong>${seats.filter(p => !p.human).length} 位对手 · ${seats.filter(scoutAlive).length} 位仍在场</strong><span>点开阵容，查看完整效果与最近实战</span></div><div class="scout-overview">${sorted.map(p => {
      const units = p.board || [];
      const counts = Object.keys(roleNames).map(role => `${roleNames[role].replace("型", "")} ${units.filter(unit => roleOf(unit) === role).length}`).join(" · ");
      return `<button type="button" class="scout-card${p.human ? " own" : ""}${p.current_opponent ? " current" : ""}${!scoutAlive(p) ? " eliminated" : ""}" data-scout="${Number(p.seat)}" aria-label="侦察${esc(scoutName(p))}阵容"><span class="scout-card-heading"><strong>${esc(scoutName(p))}</strong><span>${Number(p.hp)} <small>HP</small></span></span><span class="scout-badges">${scoutBadges(p)}</span><span class="scout-card-stats">Lv.${Number(p.level)} · 上场 ${units.length} 只 · 备战 ${(p.bench || []).length} 只</span>${scoutBoard(p, true)}<span class="scout-lineup">${units.map(unit => `<span>${esc(unit.name)} <small>${"★".repeat(starsOf(unit))}</small></span>`).join("") || "暂无上场精灵"}</span><span class="scout-role-counts">${counts}</span><span class="scout-synergies">${scoutSynergies(p)}</span><span class="scout-card-more">详细侦察 <span>→</span></span></button>`;
    }).join("")}</div><p class="scout-tip">八位训练家共享卡池。阵容是当前配置，最近实战来自已经结算的回合。</p>`;
  }
  function selectedScoutPiece() {
    if (!scoutUnit) return null;
    const owner = scoutUnit.source === "opponent" ? state?.opponent : scoutSubject();
    if (!owner) return null;
    const match = /^g([0-2]),([0-5])$/.exec(scoutUnit.loc);
    if (match) return owner.rows?.[Number(match[1])]?.[Number(match[2])] || null;
    const list = scoutUnit.loc[0] === "b" ? owner.bench : owner.board;
    return (list || []).flat().filter(Boolean)[Number(scoutUnit.loc.slice(1))] || null;
  }
  function scoutUnitDetail() {
    const p = selectedScoutPiece();
    if (!p) return '<p class="scout-inspect-hint">点选站位格或下方精灵，查看特性、技能与装备的完整效果。</p>';
    const stats = p.stat_scope === "deployment_base" ? p.stats : null;
    const facts = [["max_hp", "生命"], ["atk", "物攻"], ["sp_atk", "特攻"], ["defense", "物防"], ["sp_defense", "特防"], ["speed", "速度"]];
    return `<section id="scout-unit-detail" class="scout-unit-detail ${scoutSubject()?.human ? "own" : "enemy"}" aria-labelledby="scout-unit-title" tabindex="-1"><div class="scout-detail-heading"><img src="${spriteOf(p)}" alt=""><div><span class="scout-readonly">${scoutSubject()?.human ? "我方公开情报" : "敌方情报"} · 只读</span><h3 id="scout-unit-title">${esc(p.name)} <span class="detail-star">${"★".repeat(starsOf(p))}${p.shiny ? " ✦ 闪光" : ""}</span></h3><p class="role-${roleOf(p)}">${roleNames[roleOf(p)]} · ${attackStyle(p)} · 射程 ${Number(p.range) || "—"} 格</p><p>${esc((p.types || []).join(" / "))}</p></div></div><p>${esc(p.role_description || "")}</p>${stats ? `<dl class="scout-base-stats">${facts.map(([key, name]) => `<div><dt>${name}</dt><dd>${statNumber(stats[key])}</dd></div>`).join("")}</dl><p class="scout-section-note">部署基础值 · 已计星级与角色；装备、羁绊、海克斯与战中增益另计，生命不是战中剩余值。</p>` : ""}${skillSlots(p, {readonly: true})}<section class="skill-slot scout-item-slot" aria-label="装备完整效果"><div class="skill-slot-heading"><span>携带装备</span><small>当前配置</small></div><strong>${p.item ? esc(p.item_name || p.item) : "未装备"}</strong><p>${p.item ? esc(p.item_effect || "这份快照未记录装备效果。") : "该精灵没有携带装备。"}</p></section></section>`;
  }
  function scoutAugments(p) {
    return `<section class="scout-effects" aria-label="海克斯完整效果"><h3>海克斯强化 · 当前公开配置</h3>${(p.augments || []).map(a => `<details class="scout-effect"><summary><span>${esc(a.name || a)}</span><small>展开效果</small></summary>${a.current ? `<p class="augment-current">${esc(a.current)}</p>` : ""}<p>${esc(a.description || "这份快照未记录强化说明。")}</p></details>`).join("") || '<p class="empty-copy">尚未选择海克斯。</p>'}</section>`;
  }
  function scoutRecentReports(p) {
    const rows = p.recent_reports || [];
    if (!rows.length) return `<section class="scout-recent-reports"><h3>最近实战</h3><p class="scout-section-note">${p.reports_recorded_from ? `从第 ${Number(p.reports_recorded_from)} 轮开始记录，目前还没有已结算实战。` : "旧回合尚未记录该训练家的实战，从后续结算开始显示。"}</p></section>`;
    return `<section class="scout-recent-reports"><div class="scout-position-heading"><h3>最近实战</h3><span>最多 3 场 · 已结算</span></div><p class="scout-section-note">历史数据属于当场配置，用来核对实际输出、治疗、承伤和联动。</p><div class="scout-report-list">${rows.map((row, index) => { const verdict = reportVerdict(row.winner); return `<button type="button" data-scout-report="${index}" aria-pressed="${index === scoutReportIndex}" class="scout-report-entry ${verdict.kind}"><strong>第 ${Number(row.round)} 轮 · ${verdict.label}${row.source === "uncontested" ? " · 空场结算" : ""}</strong><span>${esc(trainerName(row.opp_name) || (row.pve ? "野生遭遇" : "当场对手"))}${row.ghost ? " · 镜像" : ""} · ${battleDuration(row.duration)}</span><small>${recordedStats(row.statistics) ? "查看实战统计 →" : "统计未记录 →"}</small></button>`; }).join("")}</div>${scoutReport() ? '<section id="scout-statistics" class="combat-statistics" aria-label="所侦察训练家的当场统计"></section><div id="scout-combinations" class="battle-combinations"></div>' : ""}</section>`;
  }
  function clearScoutLayout() {
    document.querySelector(".game-layout").classList.remove("scouting-open");
    $("scout-dialog").classList.remove("docked");
    $("scout-dialog").removeAttribute("aria-modal");
  }
  function closeScout() {
    const narrow = $("scout-dialog").classList.contains("docked") && window.matchMedia("(max-width: 1199px)").matches;
    if ($("scout-dialog").open) $("scout-dialog").close();
    clearScoutLayout();
    if (narrow) document.querySelector(".center-column").scrollIntoView({block: "start", behavior: "instant"});
  }
  function resetScout() {
    resumeAfterScout = false;
    scoutReturnFocus = null;
    closeScout();
    scoutUnit = null;
    scoutReportIndex = null;
    scoutSeat = null;
    $("scout-resume").hidden = true;
  }
  function openScout(seat = null, {unit = null, returnFocus = null, retain = false} = {}) {
    if (!state) return;
    if (!retain && seat !== scoutSeat) { scoutUnit = null; scoutReportIndex = null; }
    scoutSeat = seat;
    if (unit) scoutUnit = unit;
    const panel = $("scout-dialog");
    if (!panel.open) {
      scoutReturnFocus = returnFocus || document.activeElement;
      resumeAfterScout = $("battle-dialog").open && playback.intentPlaying;
      if (resumeAfterScout) stopPlayback();
      const modal = Boolean($("battle-dialog").open || $("history-report-dialog").open || $("result-dialog").open);
      panel.classList.toggle("docked", !modal);
      document.querySelector(".game-layout").classList.toggle("scouting-open", !modal);
      panel.setAttribute("aria-modal", String(modal));
      renderScout();
      if (modal) panel.showModal();
      else if (typeof panel.show === "function") panel.show();
      else panel.setAttribute("open", "");
      $("scout-close").focus();
      if (!modal && window.matchMedia("(max-width: 1199px)").matches) panel.scrollIntoView({block: "start", behavior: "instant"});
    } else renderScout();
    $("scout-resume").hidden = false;
    if (unit) {
      const detail = $("scout-unit-detail");
      detail?.focus({preventScroll: true});
      if (detail && panel.classList.contains("docked") && !window.matchMedia("(max-width: 1199px)").matches) panel.scrollTop = Math.max(0, detail.offsetTop - 92);
      else detail?.scrollIntoView({block: panel.classList.contains("docked") ? "start" : "nearest", behavior: "instant"});
    }
    else panel.scrollTop = 0;
  }
  function openEnemyPiece(loc, returnFocus) {
    if (!state?.opponent) return;
    const owner = (state.scouting || []).find(p => p.current_opponent);
    openScout(owner?.seat ?? -1, {unit: {source: "opponent", loc}, returnFocus});
  }
  function renderScout() {
    const seats = state.scouting || [];
    const p = scoutSubject();
    $("scout-title").textContent = scoutSeat == null ? "全场阵容" : `${scoutName(p)} · 侦察`;
    $("scout-timing").textContent = `第 ${state.round} 轮 · ${state.phase === "prep" ? "当前公开配置。准备期可边侦察边调整我方阵容。" : state.phase === "over" ? "最终公开阵容。" : "当前公开配置；回放期间无法调整部署。"} 实际触发效果请查看最近实战。`;
    $("scout-workspace-note").textContent = $("battle-dialog").open ? "关闭侦察后返回战斗回放" : "宽屏并排布阵 · 窄屏可返回我方阵容";
    $("scout-tabs").innerHTML = `<button type="button" data-scout-overview aria-pressed="${scoutSeat == null}">全场概览</button>` + seats.map(p => `<button type="button" data-scout="${Number(p.seat)}" aria-pressed="${p.seat === scoutSeat}">${p.human ? "我方" : esc(trainerName(p.name))}${p.current_opponent ? " · 本轮" : ""}</button>`).join("");
    $("scout-content").innerHTML = scoutSeat == null && seats.length ? scoutOverview(seats) : p ? `<div class="scout-heading${p.human ? " own" : ""}"><h3>${esc(scoutName(p))} <span class="scout-badges">${scoutBadges(p)}</span></h3><p>${p.hp != null ? Number(p.hp) + " HP · " : ""}${p.level != null ? "Lv." + Number(p.level) + " · " : ""}${p.gold != null ? Number(p.gold) + " 金币 · " : ""}上场 ${(p.board || []).length} 只</p></div><div class="scout-position-heading"><h3>${p.battle_snapshot ? "本轮已锁定站位" : "当前实际站位"}</h3><span>点选精灵查看完整效果</span></div>${p.battle_snapshot ? `<p class="scout-section-note">第 ${Number(p.battle_snapshot.round)} 轮对手快照 · 上场装备、技能与特性按开战时记录；备战席为当前公开信息。</p>` : ""}${scoutBoard(p)}${scoutUnitDetail()}${scoutPieces(p.board, "上场精灵", p)}${scoutPieces(p.bench, "备战席", p)}${scoutSynergies(p, true)}${scoutAugments(p)}${scoutRecentReports(p)}` : '<p class="empty-copy">当前存档未提供侦察信息。新的竞技规则支持全部训练家侦察。</p>';
    const report = scoutReport();
    if (report) { const teams = [scoutName(p), trainerName(report.opp_name) || "当场对手"]; renderCombatStats("scout", report.statistics); showCombinationSummary(report, "scout", teams); }
    document.querySelectorAll("[data-scout-unit]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.scoutUnit === scoutUnit?.loc)));
  }
  function renderCatalog() {
    const catalog = state.arena?.catalog || [];
    $("catalog-description").textContent =
      `${catalog.length} 种竞技精灵：${Object.keys(roleNames).map(role => roleNames[role] + " " + catalog.filter(p => roleOf(p) === role).length + " 种").join("、")}。八位训练家共享卡池，同种同星三合一；三星需要九张并使用闪光配色。`;
    $("catalog-grid").innerHTML = catalog
      .filter((p) => roleFilter === "all" || roleOf(p) === roleFilter)
      .map(
        (p) =>
          `<article class="catalog-card"><img src="${spriteOf(p)}" alt="${esc(p.name)}"><div><h3>${esc(p.name)} <small>${Number(p.cost || p.tier)} 费</small></h3><p class="role-${roleOf(p)}">${roleNames[roleOf(p)]} · ${attackStyle(p)} · ${esc(p.types.join(" / "))}</p><p>${esc(p.role_description || "")}</p>${skillSlots(p, {learned: false})}<p class="catalog-learning-note">另有独立学习位，学习不会覆盖原生技能。</p><small>共享池剩余 ${Number(p.pool_remaining)} / ${Number(p.pool_total)} 张</small></div></article>`,
      )
      .join("");
    document
      .querySelectorAll("[data-role-filter]")
      .forEach((b) =>
        b.setAttribute(
          "aria-pressed",
          String(b.dataset.roleFilter === roleFilter),
        ),
      );
  }
  function renderStandings() {
    const portraits = [25, 4, 7, 39, 133, 52, 54, 1];
    $("standings").innerHTML = state.standings
      .map((p, i) => ({ ...p, seat: p.seat ?? i, portrait: portraits[i] }))
      .sort((a, b) => b.hp - a.hp || (a.rank ?? 0) - (b.rank ?? 0))
      .map(
        (p, i) =>
          `<button class="trainer-row${p.is_you ? " you" : ""}${!p.alive ? " eliminated" : ""}" data-scout="${p.seat}" aria-label="侦察${p.is_you ? "我方" : esc(trainerName(p.name))}阵容"><span class="trainer-rank">${p.rank || i + 1}</span><span class="trainer-avatar"><img src="/demo/sprite/${p.portrait}.png" alt=""></span><span class="trainer-info"><span class="trainer-name">${p.is_you ? "新叶训练家" : esc(trainerName(p.name))}</span><small>${p.is_you ? "就是你" : "Lv." + p.level}${!p.alive ? " · 已淘汰" : ""} · 侦察 ↗</small><span class="mini-health"><i style="width:${Math.max(0, Math.min(100, p.hp))}%"></i></span></span><span class="trainer-hp">${p.hp}<span class="mini-heart">♡</span></span></button>`,
      )
      .join("");
  }
  async function chooseCell(loc) {
    if (!canPrep()) return;
    const p = pieceAt(loc);
    if (equipItem) {
      if (p) await api("equip", { item: equipItem, loc });
      else toast("请选择一只精灵来装备。");
      return;
    }
    if (selected && selected !== loc) {
      await api("move", { from: selected, to: loc });
      return;
    }
    selected = selected === loc ? null : p ? loc : null;
    shopSelected = null;
    render();
  }
  async function autoDeploy() {
    if (!canPrep()) return;
    deploying = true;
    selected = null;
    shopSelected = null;
    render();
    try {
      while (
        state.bench.length &&
        state.you.on_board < state.you.pop &&
        playable()
      ) {
        const p = state.bench[0],
          rows = roleOf(p) === 'support' ? [2, 1, 0] : roleOf(p) === 'attack' && p.ranged ? [1, 2, 0] : [0, 1, 2];
        let target = null;
        for (const r of rows)
          for (const c of [2, 3, 1, 4, 0, 5])
            if (!state.board[r][c] && !target) target = `g${r},${c}`;
        if (!target) break;
        const result = await api("move", { from: "b0", to: target }, true);
        if (!result?.ok) return;
      }
      toast("伙伴已经就位。调整阵容后，就可以开始战斗。");
    } finally {
      deploying = false;
      render();
    }
  }
  function requestRestart() {
    if (busy || deploying) return;
    if (state) $("new-dialog").showModal();
    else newGame();
  }
  async function newGame() {
    if (busy || deploying) return;
    closeBattle();
    $("result-dialog").close();
    systemTab = "augments";
    roleFilter = "all";
    resetScout();
    const result = await api("new", { mode: "arena" });
    if (result?.ok) {
      $("new-dialog").close();
      toast("新的冒险开始了。先从商店招募一位伙伴吧。");
    }
  }
  async function resume() {
    const slot = sid || savedSlot();
    if (!slot) {
      toast("还没有可继续的存档。点击「重开一局」开始。", true);
      return;
    }
    closeBattle();
    const result = await api("resume", { sid: slot });
    if (result?.ok) {
      toast("欢迎回来，冒险还在继续。");
      if (state.phase === "over") showResults();
    }
  }
  async function fight() {
    if (busy || deploying || !state || needsResume) return;
    if (state.phase === "over") return showResults();
    if (state.phase === "battle") return openBattle();
    if (!state.you.alive) {
      const result = await api("next");
      if (result?.ok) state.phase === "over" ? showResults() : openBattle();
      return;
    }
    if (state.augments?.pending?.length) {
      setSystemTab("augments");
      document.querySelector(".preparation-section").scrollIntoView({behavior: "smooth", block: "center"});
      toast("先选择本轮海克斯强化，再开始战斗。");
      return;
    }
    if (!state.you.on_board) {
      toast(
        state.bench.length
          ? "先把备战席的伙伴放到棋盘，或点击「一键上场」。"
          : "先从商店招募一位伙伴，再放到棋盘上。",
        true,
      );
      return;
    }
    const result = await api("end_prep");
    if (result?.ok) openBattle();
  }
  function showResults() {
    const result = state.player_result,
      rows =
        state.over?.ranking ||
        state.standings.filter((p) => p.rank).sort((a, b) => a.rank - b.rank);
    $("result-title").textContent =
      result?.rank === 1
        ? "森林的冠军，就是你。"
        : `冒险完成 · 第 ${result?.rank || "—"} 名`;
    $("result-description").textContent =
      `走过 ${result?.round || state.round} 轮冒险，${state.you.combines} 次升星。每一次相遇，都是新的可能。`;
    const defeat = result?.defeat,
      defeatedBy = defeat?.defeated_by,
      topThreat = defeat?.top_threat;
    $("result-defeat").innerHTML = [
      defeatedBy
        ? `<p class="defeat-line">败于 ${esc(trainerName(defeatedBy.name))}${defeatedBy.synergy ? `（${esc(defeatedBy.synergy)}）` : ""} R${Number(defeatedBy.round)} -${Number(defeatedBy.damage)}</p>`
        : "",
      topThreat
        ? `<p class="defeat-line">最大威胁 ${esc(trainerName(topThreat.name))} 累计-${Number(topThreat.damage)}</p>`
        : "",
      ...(Array.isArray(result?.new_challenges) && result.new_challenges.length
        ? [`<p class="defeat-line growth-result-line">本次新完成挑战：${esc(result.new_challenges.join("、"))}</p>`]
        : []),
    ].join("");
    const lastRecorded = (Array.isArray(state.battle_history) ? state.battle_history : [])
      .findLast(row => recordedStats(row.statistics));
    const champion = result?.rank === 1;
    renderAdvice("result",
      nextRoundAdvice({won: champion, lost: !champion && !state.you.alive,
        defeat: result?.defeat, stats: lastRecorded?.statistics, round: lastRecorded?.round}),
      champion);
    $("result-ranking").innerHTML =
      rows
        .map(
          (p) =>
            `<div class="result-ranking-row${p.is_you ? " you" : ""}"><span>${p.rank}. ${p.is_you ? "新叶训练家（你）" : esc(trainerName(p.name))}</span><span>${p.hp} HP</span></div>`,
        )
        .join("") +
      (!state.over
        ? '<p class="empty-copy">其余训练家仍在对战，继续观战可查看完整排名。</p><button id="finish-spectating" class="secondary-button">快进到最终排名</button>'
        : "");
    if (!$("result-dialog").open) $("result-dialog").showModal();
  }

  // A replay keeps a small moving window of decoded images. A long battle can
  // have hundreds of frames; retaining them all would consume gigabytes.
  const replayClock = (seconds, tenths = false) => {
    const safe = Math.max(0, Number(seconds) || 0);
    const minutes = Math.floor(safe / 60);
    const remainder = tenths ? (safe % 60).toFixed(1).padStart(4, "0") : String(Math.floor(safe % 60)).padStart(2, "0");
    return `${String(minutes).padStart(2, "0")}:${remainder}`;
  };
  function setBattleTab(tab, touched = true) {
    if (!["events", "statistics", "rewards"].includes(tab)) return;
    playback.reportTab = tab;
    if (touched) playback.reportTabTouched = true;
    for (const button of document.querySelectorAll("[data-battle-tab]")) {
      const active = button.dataset.battleTab === tab;
      button.setAttribute("aria-selected", String(active));
      button.setAttribute("tabindex", active ? "0" : "-1");
      $(`battle-${button.dataset.battleTab}-panel`).hidden = !active;
    }
  }
  function updatePlaybackState() {
    const p = playback;
    $("battle-pause").textContent = p.intentPlaying ? "暂停" : "播放";
    $("battle-pause").setAttribute("aria-label", p.intentPlaying ? "暂停战斗回放" : "播放战斗回放");
    $("battle-playback-state").textContent = p.verdictShown ? "回合结束"
      : p.buffering && p.intentPlaying ? "载入画面"
      : p.playing ? "回放中" : p.complete ? "已暂停" : "准备开战";
  }
  function stopPlayback() {
    clearInterval(playback.timer);
    playback.timer = null;
    playback.playing = false;
    playback.intentPlaying = false;
    updatePlaybackState();
  }
  function closeBattle() {
    playback.token++;
    stopPlayback();
    for (const request of playback.pending.values()) request.cancel();
    playback.pending.clear();
    playback.frames = [];
    playback.cached.clear();
    if ($("battle-dialog").open) $("battle-dialog").close();
  }
  function pendingBattleReport() {
    $("battle-statistics").innerHTML = '<div class="battle-report-pending"><span class="report-pending-symbol" aria-hidden="true">◷</span><strong>等伙伴们完成这一战</strong><p>回放结束后，查看双方输出、治疗、承伤与护盾吸收。</p></div>';
    $("battle-rewards-pending").hidden = false;
    $("battle-rewards").hidden = true;
    $("battle-combinations").hidden = true;
    $("battle-rewards").innerHTML = "";
    $("battle-combinations").innerHTML = "";
    $("battle-bonds").hidden = true;
    $("battle-bonds").innerHTML = "";
    $("battle-advice").hidden = true;
    $("battle-advice").innerHTML = "";
  }
  function hideBattleDisclosure() {
    const p = playback;
    $("battle-verdict").hidden = true;
    $("battle-result").textContent = "回放结束后显示战果";
    $("battle-result").className = "battle-result";
    $("battle-next").disabled = true;
    if (p.verdictShown) pendingBattleReport();
    p.verdictShown = false;
  }
  function showVerdict() {
    if (playback.verdictShown) return;
    stopPlayback();
    playback.verdictShown = true;
    const meta = playback.meta;
    const kind = meta?.winner === 0 ? "win" : meta?.winner === 1 ? "loss" : "draw";
    const overlay = $("battle-verdict");
    overlay.className = `battle-verdict ${kind}`;
    overlay.querySelector(".verdict-symbol").textContent = kind === "win" ? "✦" : kind === "loss" ? "◇" : "＝";
    overlay.querySelector("strong").textContent = kind === "win" ? "回合胜利" : kind === "loss" ? "回合失利" : "势均力敌";
    overlay.querySelector("p").textContent = String(meta?.headline || "本轮战果已保存").replace(/<[^>]*>/g, "");
    overlay.hidden = false;
    $("battle-result").textContent = meta?.headline || "本轮战果已保存";
    $("battle-result").className = `battle-result ${kind}`;
    $("battle-rewards-pending").hidden = true;
    const row = (state.round_rewards || []).find((r) => r.round === (meta?.round || state.round));
    $("battle-rewards").hidden = !row;
    $("battle-rewards").innerHTML = row ? `<h3>回合奖励 · 已入仓</h3><p>${row.result === "win" ? "胜利获得 2 份" : "失败或平局获得 1 份"}，下轮可装备或学习。</p>${rewardCards(row)}` : '<p class="combination-note">这轮未记录额外奖励。</p>';
    renderCombatStats("battle", meta?.statistics);
    renderBondSpark("battle", meta?.statistics?.units);
    renderAdvice("battle",
      nextRoundAdvice({won: meta?.winner === 0, lost: meta?.winner === 1,
        stats: meta?.statistics, round: meta?.round || state.round}),
      meta?.winner === 0);
    showCombinationSummary(meta);
    $("battle-next").disabled = busy || needsResume;
    if (!playback.reportTabTouched) setBattleTab("statistics", false);
    updatePlaybackState();
    if (sound) tone(kind === "win");
  }
  function updateTeamTelemetry() {
    const p = playback;
    const frame = p.meta?.team_frames?.[p.current];
    const combatants = p.meta?.combatants || [];
    for (const [team, side] of [[0, "friendly"], [1, "enemy"]]) {
      const initial = combatants.filter((unit) => Number(unit.team) === team);
      const alive = statValue(frame?.alive?.[team]);
      const health = statValue(frame?.hp?.[team]);
      const maxHp = initial.reduce((sum, unit) => sum + (statValue(unit.max_hp) || 0), 0);
      $(`battle-${side}-alive`).textContent = alive == null ? "— / —" : `${alive} / ${initial.length}`;
      const bar = $(`battle-${side}-hp-bar`);
      bar.style.width = maxHp > 0 && health != null ? `${Math.max(0, Math.min(100, health / maxHp * 100))}%` : "0%";
      bar.parentElement.title = health == null ? "这份回放未记录队伍生命" : `剩余总生命 ${statNumber(health)} / ${statNumber(maxHp)}`;
    }
    $("battle-clock").textContent = replayClock(p.current * p.dt, true);
  }
  function updateBattleTimeline() {
    const p = playback;
    const total = Math.max(0, p.n - 1);
    const seek = $("battle-seek");
    seek.value = String(p.requested ?? p.current);
    seek.setAttribute("aria-valuetext", `${(p.current * p.dt).toFixed(1)} 秒，共 ${(total * p.dt).toFixed(1)} 秒`);
    seek.style.setProperty("--progress", `${total ? p.current / total * 100 : 0}%`);
    let buffered = p.current;
    while (buffered + 1 < p.n && p.frames[buffered + 1]?.naturalWidth) buffered++;
    seek.style.setProperty("--buffer", `${total ? buffered / total * 100 : 0}%`);
    $("battle-current-time").textContent = replayClock(p.current * p.dt);
    $("battle-total-time").textContent = replayClock(total * p.dt);
    $("battle-status").textContent = `${(p.current * p.dt).toFixed(1)} / ${(total * p.dt).toFixed(1)} 秒 · ${p.speed}×`;
    $("battle-status").dataset.loadedFrames = String(p.loaded.size);
    $("battle-status").dataset.cachedFrames = String(p.cached.size);
    $("battle-status").dataset.bufferedFrames = String(buffered - p.current);
  }
  function updateBattleEvents() {
    const p = playback;
    const occurred = (p.meta?.events || []).map((event, index) => ({event, index}))
      .filter(({event}) => Number(event.t) <= p.current * p.dt + 0.000001);
    const last = occurred.length ? occurred[occurred.length - 1].index : -1;
    if (last === p.lastEvent) return;
    p.lastEvent = last;
    const box = $("battle-events");
    box.innerHTML = occurred.map(({event, index}, position) => `<div class="event ${position === occurred.length - 1 ? "now" : "past"}" id="play-event-${index}"><time>${Number(event.t).toFixed(1)}s</time><span>${esc(String(event.text).replace(/<[^>]*>/g, ""))}</span></div>`).join("") || '<p class="battle-events-empty">技能、命中与联动会随战斗逐条出现。</p>';
    box.scrollTop = box.scrollHeight;
    $("battle-current-event").textContent = occurred.length ? String(occurred[occurred.length - 1].event.text).replace(/<[^>]*>/g, "") : "双方伙伴，即将登场。";
  }
  function showFrame(index) {
    const p = playback;
    const next = Math.max(0, Math.min(p.n - 1, Number(index) || 0));
    const image = p.frames[next];
    if (!image?.naturalWidth) return false;
    p.current = next;
    if (p.requested === next) p.requested = null;
    p.complete = true;
    p.buffering = false;
    p.retryIndex = null;
    if (next < p.n - 1 && p.verdictShown) hideBattleDisclosure();
    const canvas = $("battle-canvas");
    if (canvas.width !== image.naturalWidth || canvas.height !== image.naturalHeight) {
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
    }
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.imageSmoothingEnabled = String(p.meta?.presentation || "").startsWith("web-arena-");
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    $("battle-loading").hidden = true;
    document.querySelector(".battle-screen").setAttribute("aria-busy", "false");
    updateTeamTelemetry();
    updateBattleTimeline();
    updateBattleEvents();
    updatePlaybackState();
    if (p.n > 0 && next >= p.n - 1) showVerdict();
    return true;
  }
  function setBattleLoading(message, retry = false) {
    playback.buffering = true;
    $("battle-loading").hidden = false;
    $("battle-loading-copy").textContent = message;
    $("battle-loading").className = `battle-loading${retry ? " load-error" : ""}`;
    $("battle-retry").hidden = !retry;
    document.querySelector(".battle-screen").setAttribute("aria-busy", String(!retry));
    updatePlaybackState();
  }
  function trimReplayCache() {
    const p = playback;
    if (p.cached.size <= p.cacheLimit) return;
    const center = p.requested ?? p.current;
    const start = Math.max(0, center - 4);
    const end = Math.min(p.n - 1, center + p.cacheLimit - 9);
    for (const index of [...p.cached]) {
      if (p.cached.size <= p.cacheLimit) break;
      if ((index < start || index > end) && index !== p.current && index !== p.requested) {
        p.cached.delete(index);
        delete p.frames[index];
      }
    }
    const farthest = [...p.cached].sort((a, b) => Math.abs(b - center) - Math.abs(a - center));
    while (p.cached.size > p.cacheLimit && farthest.length) {
      const index = farthest.shift();
      if (index === p.current || index === p.requested) continue;
      p.cached.delete(index);
      delete p.frames[index];
    }
  }
  function startPlaybackTimer() {
    const p = playback;
    if (!p.intentPlaying || p.timer || !p.complete || p.requested != null || document.hidden || $("scout-dialog").open || !$("battle-dialog").open) return;
    const end = Math.min(p.n - 1, p.current + 3);
    for (let index = p.current + 1; index <= end; index++) {
      if (!p.frames[index]?.naturalWidth) {
        if (p.failed.has(index)) {
          p.retryIndex = index;
          setBattleLoading("一段画面暂时无法载入，可重试或查看战果。", true);
        } else setBattleLoading("正在准备接下来的战斗画面…");
        return;
      }
    }
    p.buffering = false;
    $("battle-loading").hidden = true;
    document.querySelector(".battle-screen").setAttribute("aria-busy", "false");
    p.playing = true;
    updatePlaybackState();
    const token = p.token;
    p.timer = setInterval(() => {
      if (token !== p.token || !p.intentPlaying) return;
      const next = p.current + 1;
      if (!showFrame(next)) {
        clearInterval(p.timer);
        p.timer = null;
        p.playing = false;
        p.requested = Math.min(p.n - 1, next);
        if (p.failed.has(p.requested)) {
          p.retryIndex = p.requested;
          setBattleLoading("这一帧暂时无法载入，可重试或查看战果。", true);
        } else setBattleLoading("正在准备接下来的战斗画面…");
      }
      pumpReplayFrames();
    }, (p.dt * 1000) / p.speed);
  }
  function pumpReplayFrames() {
    const p = playback;
    if (!p.n || !$("battle-dialog").open) return;
    const token = p.token;
    trimReplayCache();
    const center = p.requested ?? p.current;
    const forward = p.cacheLimit - 9;
    const start = Math.max(0, center - 4);
    const end = Math.min(p.n - 1, center + forward);
    const candidates = [center];
    for (let index = center + 1; index <= end; index++) candidates.push(index);
    for (let index = center - 1; index >= start; index--) candidates.push(index);
    const wanted = new Set(candidates);
    for (const [index, request] of [...p.pending]) {
      if (!wanted.has(index)) request.cancel();
    }
    while (p.pending.size < 4) {
      const index = candidates.find((candidate) => !p.frames[candidate]?.naturalWidth && !p.pending.has(candidate) && !p.failed.has(candidate));
      if (index == null) break;
      const image = new Image();
      let done = false;
      let timeout;
      const request = {cancel: () => {
        if (done) return;
        done = true;
        clearTimeout(timeout);
        image.onload = null;
        image.onerror = null;
        image.removeAttribute?.("src");
        if (p.pending.get(index) === request) p.pending.delete(index);
      }};
      const finish = (ok) => {
        if (done) return;
        done = true;
        clearTimeout(timeout);
        image.onload = null;
        image.onerror = null;
        if (token !== p.token || p.pending.get(index) !== request) return;
        p.pending.delete(index);
        if (ok && image.naturalWidth) {
          p.frames[index] = image;
          p.cached.add(index);
          p.loaded.add(index);
          if (p.requested === index) showFrame(index);
        } else {
          p.failed.add(index);
          if (p.requested === index) {
            p.retryIndex = index;
            setBattleLoading("这一帧暂时无法载入，可重试或查看战果。", true);
            if (p.revealOnFailure && index === p.n - 1) {
              $("battle-status").textContent = "画面暂时无法载入，本轮战果已保存。";
              showVerdict();
            }
          }
        }
        updateBattleTimeline();
        startPlaybackTimer();
        pumpReplayFrames();
      };
      p.pending.set(index, request);
      timeout = setTimeout(() => finish(false), 15000);
      image.onload = () => finish(true);
      image.onerror = () => finish(false);
      const revision = p.meta?.render_revision;
      image.src = `/demo/frame/${sid}/r${p.meta.round}/${index}.png${revision ? `?v=${encodeURIComponent(revision)}` : ""}`;
    }
    updateBattleTimeline();
  }
  function requestBattleFrame(index, {resume = false, revealOnFailure = false} = {}) {
    const p = playback;
    if (!p.n) return;
    stopPlayback();
    const target = Math.max(0, Math.min(p.n - 1, Math.round(Number(index) || 0)));
    if (target < p.n - 1) hideBattleDisclosure();
    p.requested = target;
    p.revealOnFailure = revealOnFailure;
    p.intentPlaying = resume;
    if (!showFrame(target)) {
      if (p.failed.has(target)) {
        p.retryIndex = target;
        setBattleLoading("这一帧暂时无法载入，可重试或查看战果。", true);
        if (revealOnFailure && target === p.n - 1) showVerdict();
      } else setBattleLoading(`正在载入 ${replayClock(target * p.dt)} 的画面…`);
    }
    pumpReplayFrames();
    startPlaybackTimer();
  }
  function play() {
    const p = playback;
    if (!p.n || document.hidden || $("scout-dialog").open || !$("battle-dialog").open) return;
    if (p.current >= p.n - 1 && p.requested == null) return requestBattleFrame(0, {resume: true});
    p.intentPlaying = true;
    startPlaybackTimer();
    pumpReplayFrames();
    updatePlaybackState();
  }
  function emptyBattle(message) {
    const canvas = $("battle-canvas");
    canvas.width = playback.meta?.width || 960;
    canvas.height = playback.meta?.height || 640;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#192c2b";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.textAlign = "center";
    ctx.fillStyle = "#d9e5ce";
    ctx.font = "600 26px sans-serif";
    ctx.fillText(playback.n ? "森林竞技场" : "本轮战果已保存", canvas.width / 2, canvas.height / 2 - 12);
    ctx.fillStyle = "#82978f";
    ctx.font = "15px sans-serif";
    ctx.fillText(playback.n ? "伙伴们即将登场" : "下一轮，继续冒险", canvas.width / 2, canvas.height / 2 + 23);
    $("battle-status").textContent = message;
  }
  async function openBattle() {
    closeBattle();
    const meta = state.last_battle;
    Object.assign(playback, {
      meta, frames: [], cached: new Set(), loaded: new Set(), failed: new Set(), pending: new Map(),
      current: 0, requested: meta?.n ? 0 : null, n: meta?.n || 0, dt: meta?.dt || 0.05,
      complete: false, verdictShown: false, buffering: true, intentPlaying: !!meta?.n,
      reportTab: "events", reportTabTouched: false, lastEvent: null, retryIndex: null,
      revealOnFailure: false, seekResume: false,
      cacheLimit: window.matchMedia?.("(max-width: 720px)")?.matches ? 36 : 72,
    });
    $("battle-speed").value = String(playback.speed);
    $("battle-verdict").hidden = true;
    $("battle-result").textContent = "回放结束后显示战果";
    $("battle-result").className = "battle-result";
    pendingBattleReport();
    Object.assign(statViews.battle, {team: 0, metric: "damage_dealt"});
    $("battle-title").textContent = `第 ${meta?.round || state.round} 轮 · 战斗时刻`;
    $("battle-subtitle").textContent = `${meta?.pve ? "野生遭遇" : "训练家对战"}${meta?.ghost ? " · 镜像对手" : ""} · 3 排战场`;
    $("battle-round-label").textContent = `第 ${meta?.round || state.round} 轮`;
    $("battle-friendly-name").textContent = "新叶训练家";
    $("battle-enemy-name").textContent = trainerName(meta?.opp_name) || "当轮对手";
    for (const [team, side] of [[0, "friendly"], [1, "enemy"]]) {
      $(`battle-${side}-roster`).innerHTML = (meta?.combatants || []).filter((unit) => Number(unit.team) === team).map((unit) => `<img src="${spriteOf({...unit, shiny: starsOf(unit) === 3})}" alt="${esc(unit.name)}" title="${esc(unit.name)} · ${starsOf(unit)}星 · ${esc(roleNames[unit.role] || "")}${Number(unit.range) ? ` · ${Number(unit.range) > 1 ? "远程" : "近战"}` : ""}">`).join("");
    }
    $("battle-events").innerHTML = '<p class="battle-events-empty">技能、命中与联动会随战斗逐条出现。</p>';
    $("battle-current-event").textContent = "双方伙伴，即将登场。";
    $("battle-next").textContent = state.phase === "over" ? "查看最终排名 →" : "下一轮 →";
    $("battle-next").disabled = !!meta?.n;
    $("battle-pause").disabled = $("battle-skip").disabled = $("battle-replay").disabled = !meta?.n;
    $("battle-seek").disabled = !meta?.n;
    $("battle-seek").max = String(Math.max(0, (meta?.n || 0) - 1));
    $("battle-report-body").hidden = false;
    $("battle-report-toggle").setAttribute("aria-expanded", "true");
    $("battle-report-toggle").innerHTML = '收起战报 <span aria-hidden="true">−</span>';
    setBattleTab("events", false);
    $("battle-dialog").showModal();
    emptyBattle("正在准备战斗画面…");
    updateTeamTelemetry();
    updateBattleTimeline();
    updatePlaybackState();
    if (!meta?.n) {
      $("battle-loading").hidden = true;
      document.querySelector(".battle-screen").setAttribute("aria-busy", "false");
      $("battle-status").textContent = meta?.restored ? "历史画面未包含在存档中，战果和奖励已恢复。"
        : !state.you.alive ? "你的冒险已结束，仍可继续观战。" : "本轮没有战斗画面。";
      showVerdict();
      return;
    }
    setBattleLoading("正在准备战场，画面就绪后开始回放…");
    pumpReplayFrames();
  }
  async function nextRound() {
    if (busy) return;
    if (state.phase === "over") {
      closeBattle();
      showResults();
      return;
    }
    const result = await api("next");
    if (result?.ok) {
      closeBattle();
      if (state.phase === "over" || !state.you.alive) showResults();
    }
  }

  document.addEventListener("click", async (event) => {
    const target = event.target.closest("button");
    if (!target || target.disabled) return;
    if (target.dataset.shop != null) {
      const i = Number(target.dataset.shop);
      if (shopSelected === i) {
        // 再次点击已选中的卡片等同于点「招募」，沿用旧的一步买入习惯。
        if (canPrep() && state.you.gold >= (state.shop[i]?.price ?? Infinity))
          await api("buy", { i });
      } else {
        shopSelected = i;
        selected = null;
        equipItem = null;
        render();
      }
    } else if (target.dataset.shopBuy != null && canPrep()) {
      await api("buy", { i: target.dataset.shopBuy });
    } else if (target.dataset.enemyLoc) openEnemyPiece(target.dataset.enemyLoc, target);
    else if (target.dataset.loc) await chooseCell(target.dataset.loc);
    else if (target.dataset.equip && canPrep()) {
      equipItem =
        equipItem === target.dataset.equip ? null : target.dataset.equip;
      selected = null;
      shopSelected = null;
      render();
    } else if (target.dataset.craft && canPrep())
      await api("craft", { item: target.dataset.craft });
    else if (target.dataset.system) setSystemTab(target.dataset.system);
    else if (target.dataset.openSystem) {
      setSystemTab(target.dataset.openSystem);
      document
        .querySelector(".preparation-section")
        .scrollIntoView({ behavior: "smooth", block: "nearest" });
    } else if (target.dataset.augment && canPrep())
      await api("claim_augment", {
        id: target.dataset.reward,
        choice: target.dataset.augment,
      });
    else if (target.dataset.augmentReroll && canPrep())
      await api("reroll_augment", { id: target.dataset.augmentReroll });
    else if (target.dataset.componentChoice && canPrep())
      await api("claim_component", {
        reward_id: target.dataset.componentReward,
        choice: target.dataset.componentChoice,
      });
    else if (target.dataset.learn && canPrep()) {
      const loc = $("learn-" + target.dataset.learn).value;
      if (loc) await api("learn", { loc, technique: target.dataset.learn });
    } else if (target.hasAttribute("data-scout-return")) {
      closeScout();
    } else if (target.hasAttribute("data-scout-resume")) {
      openScout(scoutSeat, {retain: true, returnFocus: target});
    } else if (target.hasAttribute("data-scout-overview")) {
      openScout(null, {returnFocus: target});
    } else if (target.dataset.scout != null) {
      openScout(Number(target.dataset.scout), {returnFocus: target});
    } else if (target.dataset.scoutUnit) {
      const seat = Number(target.dataset.scoutOwner);
      openScout(seat, {unit: {source: "scouting", loc: target.dataset.scoutUnit}});
    } else if (target.dataset.scoutReport != null) {
      scoutReportIndex = Number(target.dataset.scoutReport);
      Object.assign(statViews.scout, {team: 0, metric: "damage_dealt"});
      renderScout();
      $("scout-statistics")?.scrollIntoView({block: "nearest", behavior: "instant"});
    } else if (target.dataset.battleReport != null) {
      openHistoryReport(target.dataset.battleReport);
    } else if (target.dataset.statScope) {
      selectStatView(target);
    } else if (target.dataset.roleFilter) {
      roleFilter = target.dataset.roleFilter;
      renderCatalog();
    } else if (target.dataset.action === "cancel-select") {
      selected = null;
      shopSelected = null;
      equipItem = null;
      render();
    } else if (
      ["sell", "unequip"].includes(target.dataset.action) &&
      selected &&
      canPrep()
    )
      await api(target.dataset.action, { loc: selected });
    else if (target.id === "finish-spectating" && !busy) {
      const result = await api("finish");
      if (result?.ok) showResults();
    }
  });
  document.addEventListener("change", async (event) => {
    const target = event.target;
    if (!target.matches?.("select[data-trait-choice]") || !selected || !canPrep()) return;
    const p = pieceAt(selected);
    if (!p?.trait_options?.some(option => option.id === target.value)) return;
    await api("trait", { loc: selected, trait: target.value });
  });
  document.addEventListener("dragstart", (event) => {
    const cell = event.target.closest("[data-loc][data-owned]");
    if (!cell || !canPrep()) {
      event.preventDefault();
      return;
    }
    selected = cell.dataset.loc;
    shopSelected = null;
    equipItem = null;
    event.dataTransfer.setData("text/plain", selected);
    event.dataTransfer.effectAllowed = "move";
    cell.classList.add("selected");
    renderDetail();
  });
  document.addEventListener("dragover", (event) => {
    const cell = event.target.closest("[data-loc]");
    if (cell && canPrep() && selected) {
      event.preventDefault();
      cell.classList.add("drop-target");
      event.dataTransfer.dropEffect = "move";
    }
  });
  document.addEventListener("dragleave", (event) => {
    event.target.closest("[data-loc]")?.classList.remove("drop-target");
  });
  document.addEventListener("drop", async (event) => {
    const cell = event.target.closest("[data-loc]");
    if (!cell || !canPrep()) return;
    event.preventDefault();
    const from = event.dataTransfer.getData("text/plain");
    if (from && from === selected && pieceAt(from) && from !== cell.dataset.loc)
      await api("move", { from, to: cell.dataset.loc });
    render();
  });
  document.addEventListener("dragend", () => {
    if (!busy) render();
  });
  $("refresh-button").onclick = () => {
    if (canPrep()) api("refresh");
  };
  $("lock-button").onclick = () => {
    if (canPrep()) api("lock");
  };
  $("levelup-button").onclick = () => {
    if (canPrep()) api("levelup");
  };
  $("deploy-button").onclick = autoDeploy;
  $("fight-button").onclick = fight;
  for (const button of document.querySelectorAll("[data-restart]"))
    button.onclick = requestRestart;
  $("new-cancel").onclick = () => $("new-dialog").close();
  $("new-confirm").onclick = newGame;
  $("result-new").onclick = newGame;
  $("result-close").onclick = () => $("result-dialog").close();
  $("resume-button").onclick = resume;
  const help = () => $("help-dialog").showModal();
  $("help-button").onclick = help;
  $("mobile-help-button").onclick = help;
  $("help-close").onclick = () => $("help-dialog").close();
  $("scout-close").onclick = closeScout;
  $("lobby-toggle").onclick = () => {
    const open = document.querySelector(".game-layout").classList.toggle("lobby-open");
    $("lobby-toggle").setAttribute("aria-expanded", String(open));
  };
  $("scout-dialog").addEventListener("cancel", event => { event.preventDefault(); closeScout(); });
  $("scout-dialog").addEventListener("close", () => {
    clearScoutLayout();
    let returnTarget = scoutReturnFocus;
    if (returnTarget?.isConnected === false) {
      returnTarget = returnTarget.id ? $(returnTarget.id)
        : returnTarget.dataset.enemyLoc ? document.querySelector(`[data-enemy-loc="${returnTarget.dataset.enemyLoc}"]`)
        : returnTarget.dataset.scout != null ? document.querySelector(`[data-scout="${returnTarget.dataset.scout}"]`)
        : $("scout-resume");
    }
    returnTarget?.focus?.();
    if (resumeAfterScout && $("battle-dialog").open && playback.current < playback.n - 1) play();
    resumeAfterScout = false;
  });
  $("catalog-button").onclick = () => {
    if (!state) return;
    renderCatalog();
    $("catalog-dialog").showModal();
  };
  $("catalog-close").onclick = () => $("catalog-dialog").close();
  document
    .querySelector(".system-tabs")
    .addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
        return;
      event.preventDefault();
      const tabs = ["augments", "techniques", "items", "growth"];
      const index = tabs.indexOf(systemTab);
      setSystemTab(
        event.key === "Home"
          ? tabs[0]
          : event.key === "End"
            ? tabs[3]
            : tabs[(index + (event.key === "ArrowRight" ? 1 : 3)) % 4],
      );
      $(systemTab + "-tab").focus();
    });
  $("sound-button").onclick = () => {
    sound = !sound;
    $("sound-button").setAttribute("aria-pressed", String(sound));
    $("sound-button").title = sound ? "音效已开启" : "音效已关闭";
    tone();
    toast(sound ? "已开启操作音效" : "已关闭操作音效");
  };
  $("backup-button").onclick = () => {
    if (!sid || busy) return;
    const link = document.createElement("a");
    link.href = `/api/demo/backup?sid=${encodeURIComponent(sid)}`;
    link.download = `PokeTactics-${sid}.ptsave`;
    link.click();
  };
  $("history-report-close").onclick = () => $("history-report-dialog").close();
  $("history-report-round").onchange = () => openHistoryReport($("history-report-round").value);
  $("last-result-button").onclick = () => {
    const rows = state?.battle_history || [];
    if (rows.length) openHistoryReport(rows.at(-1).round);
  };
  $("battle-close").onclick = closeBattle;
  $("battle-dialog").addEventListener("cancel", closeBattle);
  $("battle-pause").onclick = () => playback.intentPlaying ? stopPlayback() : play();
  $("battle-skip").onclick = () => requestBattleFrame(playback.n - 1, {revealOnFailure: true});
  $("battle-replay").onclick = () => requestBattleFrame(0, {resume: true});
  $("battle-speed").onchange = () => {
    const running = playback.intentPlaying;
    stopPlayback();
    playback.speed = Number($("battle-speed").value);
    updateBattleTimeline();
    if (running) play();
  };
  $("battle-seek").onpointerdown = () => {
    playback.seekResume = playback.intentPlaying;
    stopPlayback();
  };
  $("battle-seek").oninput = () => requestBattleFrame($("battle-seek").value);
  $("battle-seek").onchange = () => {
    if (playback.seekResume) play();
    playback.seekResume = false;
  };
  $("battle-retry").onclick = () => {
    const target = playback.retryIndex ?? playback.requested ?? playback.current;
    const running = playback.intentPlaying;
    playback.failed.delete(target);
    playback.retryIndex = null;
    requestBattleFrame(playback.requested ?? playback.current, {resume: running});
  };
  $("battle-report-toggle").onclick = () => {
    const hidden = !$("battle-report-body").hidden;
    $("battle-report-body").hidden = hidden;
    $("battle-report-toggle").setAttribute("aria-expanded", String(!hidden));
    $("battle-report-toggle").innerHTML = `${hidden ? "展开" : "收起"}战报 <span aria-hidden="true">${hidden ? "+" : "−"}</span>`;
  };
  for (const button of document.querySelectorAll("[data-battle-tab]")) button.onclick = () => setBattleTab(button.dataset.battleTab);
  document.querySelector(".battle-report-tabs").addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const tabs = ["events", "statistics", "rewards"];
    const index = tabs.indexOf(playback.reportTab);
    const tab = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs[2]
      : tabs[(index + (event.key === "ArrowRight" ? 1 : 2)) % tabs.length];
    setBattleTab(tab);
    $(`battle-${tab}-tab`).focus();
  });
  $("battle-next").onclick = nextRound;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopPlayback();
  });
  document.addEventListener("keydown", (event) => {
    if (event.code === "Escape" && $("scout-dialog").open && $("scout-dialog").classList.contains("docked")) { event.preventDefault(); closeScout(); return; }
    if (
      event.repeat ||
      event.altKey ||
      event.ctrlKey ||
      event.metaKey ||
      /INPUT|SELECT|TEXTAREA|BUTTON/.test(event.target.tagName) ||
      [...document.querySelectorAll("dialog[open]")].some(dialog => dialog !== $("scout-dialog") || !dialog.classList.contains("docked"))
    )
      return;
    if (event.code === "Space") {
      event.preventDefault();
      fight();
    }
    if (event.code === "KeyE") autoDeploy();
    if (event.code === "KeyR" && canPrep()) api("refresh");
    if (event.code === "Escape") {
      selected = null;
      shopSelected = null;
      equipItem = null;
      render();
    }
  });
  render();
  (async () => {
    sid = savedSlot();
    if (sid) {
      const result = await api("resume", { sid }, true);
      if (result?.ok && state.phase === "over") showResults();
    } else await newGame();
  })();
})();
