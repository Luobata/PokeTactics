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
    equipItem = null;
  let busy = false,
    deploying = false,
    needsResume = false,
    sound = false,
    audio = null;
  let toastTimer;
  let systemTab = "augments",
    roleFilter = "all",
    scoutSeat = 1;
  const roleNames = { attack: "攻击型", defense: "防守型", support: "辅助型" };
  const roleSymbols = { attack: "⚔", defense: "⬟", support: "✚" };
  const roleOf = (p) =>
    Object.hasOwn(roleNames, p?.role_key) ? p.role_key : "attack";
  const starsOf = (p) => Math.max(1, Math.min(3, Number(p?.star) || 1));
  const attackStyle = (p) => p?.ranged ? "远程" : "近战";
  const spriteOf = (p) =>
    `/demo/sprite/${Number(p.sid)}.png${p.shiny ? "?shiny=1" : ""}`;
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
        state = result.state;
        if (!["state", "resume", "new"].includes(cmd))
          upgrades = ownedSnapshot(state).filter((p) =>
            before.some((old) => old.uid === p.uid && old.star < p.star));
        sid = result.sid || state.sid;
        selected = null;
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

  function cell(piece, loc, enemy = false, bench = false) {
    const cls = bench ? "bench-slot" : "tile";
    const chosen = Boolean(loc) && selected === loc;
    const description = piece
      ? `${piece.name}，${starsOf(piece)}星${piece.shiny ? "闪光" : ""}，${roleNames[roleOf(piece)]}，${attackStyle(piece)}，${piece.types.join("、")}${piece.item_name ? "，装备" + piece.item_name : ""}`
      : "空位";
    return `<button type="button" class="${cls}${piece ? "" : " empty"}${chosen ? " selected" : ""}${piece?.shiny ? " shiny" : ""}" ${loc ? `data-loc="${loc}"` : ""} ${piece ? `data-owned="1"${piece.uid ? ` data-uid="${esc(piece.uid)}"` : ""}` : ""} ${enemy || !canPrep() ? "disabled" : ""} ${piece && !enemy && canPrep() ? 'draggable="true"' : ""} aria-label="${esc((enemy ? "敌方" : bench ? "备战席" : "我方") + " " + description)}" ${chosen ? 'aria-pressed="true"' : ""}>${piece ? `<img src="${spriteOf(piece)}" alt="" draggable="false"><span class="unit-label">${esc(piece.name)}</span><span class="unit-stars">${"★".repeat(starsOf(piece))}</span>${piece.item ? '<span class="unit-item" title="已装备">◆</span>' : `<span class="unit-role role-${roleOf(piece)}" title="${roleNames[roleOf(piece)]}">${roleSymbols[roleOf(piece)]}</span>`}${piece.shiny ? '<span class="shiny-mark">✦</span>' : ""}` : ""}</button>`;
  }
  function render() {
    const locked = busy || deploying;
    for (const id of ["new-button", "resume-button", "backup-button"])
      $(id).disabled = locked || (id === "backup-button" && !sid);
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
      cell(enemies[Math.floor(i / 6)]?.[i % 6], null, true),
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
          ? `<button type="button" class="shop-card" data-shop="${i}" style="--card-tint:${/^#[0-9a-f]{6}$/i.test(p.colors?.[0]) ? p.colors[0] + "20" : "#e9efda"}" ${!prep || y.gold < p.price ? "disabled" : ""} aria-label="招募${esc(p.name)}，${roleNames[roleOf(p)]}，${p.price}金币"><div class="shop-art"><span class="shop-tier">${p.tier} 费 · ★</span><span class="shop-role role-${roleOf(p)}">${roleNames[roleOf(p)]}</span><img src="${spriteOf(p)}" alt="" draggable="false"><span class="shop-buy-hint">+</span></div><div class="shop-info"><div class="shop-name">${esc(p.name)}<span class="shop-price">${p.price}${icon("coin")}</span></div><div class="shop-types">${p.types.map((t) => `<span class="type-tag">${esc(t)}</span>`).join("")}</div><div class="shop-move"><span>${esc(p.skill_name)}</span><span>${attackStyle(p)} ${p.range}格</span></div></div></button>`
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
                    : "冒险从一次相遇开始。点击商店中的精灵，把它招募到备战席。"
                  : "准备阶段不限时。调整阵容、点亮羁绊，准备好了就开始战斗。";
    $("synergy-list").innerHTML = state.synergies.length
      ? state.synergies
          .map(
            (s) =>
              `<details class="synergy-row${s.tier ? " on" : ""}"><summary><span class="type-dot" style="background:${/^#[0-9a-f]{6}$/i.test(s.color) ? s.color + "30" : "#dde6c9"}">${esc(s.zh.slice(0, 1))}</span><strong>${esc(s.zh)}</strong><small>${s.n}${s.next ? " / " + s.next : ""}</small></summary><p>${esc(s.effect || `还需 ${s.need} 种不同的${s.zh}属性精灵触发加成。`)}</p></details>`,
          )
          .join("")
      : '<p class="empty-copy">上场精灵，点亮你的第一组羁绊。</p>';
    renderDetail();
    renderInventory();
    renderSystems();
    renderRoundLoot();
    renderStandings();
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
    $("battle-next").disabled = locked;
  }
  function renderDetail() {
    const p = pieceAt(selected);
    if (!p) {
      $("unit-detail").innerHTML =
        `<div class="empty-detail">${icon("ball")}<p>点击一只精灵<br>了解它的战斗风格</p></div>`;
      return;
    }
    $("unit-detail").innerHTML =
      `<div class="unit-detail-card"><img src="${spriteOf(p)}" alt="${esc(p.name)}"><h3>${esc(p.name)}</h3><p class="detail-star">${"★".repeat(starsOf(p))}${p.shiny ? " · 闪光" : ""}</p><p class="role-${roleOf(p)}">${roleNames[roleOf(p)]} · ${attackStyle(p)} · ${esc(p.types.join(" / "))}</p><div style="clear:both"></div><p>${esc(p.role_description || "")}</p><p><b>${esc(p.skill_name)}</b> · ${esc(p.skill_type)}属性：${esc(p.skill_description)}</p><div class="detail-stat"><span>攻击方式</span><b>${attackStyle(p)} · ${p.range} 格</b></div>${p.item ? `<p>装备：${esc(p.item_name)}</p><p>${esc(p.item_effect)}</p>` : ""}${p.technique ? `<p>已学习：${esc(p.technique.name)}</p><p>${esc(p.technique.description)}</p>` : ""}<div class="detail-actions"><button data-open-system="techniques">为它学习技能</button><button data-action="sell" class="sell-button" ${!canPrep() ? "disabled" : ""}>出售 +${p.sell} 金币</button>${p.item ? `<button data-action="unequip" ${!canPrep() ? "disabled" : ""}>卸下装备</button>` : ""}<button data-action="cancel-select">取消选择</button></div></div>`;
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
    if (!["augments", "techniques", "items"].includes(value)) return;
    systemTab = value;
    for (const name of ["augments", "techniques", "items"]) {
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
            `<p class="system-note">第 ${Number(reward.round)} 轮 · 选择一项，本局持续生效</p><div class="augment-options">${reward.options.map((option) => `<button class="augment-card" data-augment="${esc(option.id)}" data-reward="${esc(reward.id)}" ${!canPrep() ? "disabled" : ""}><span class="augment-sigil">✦</span><strong>${esc(option.name)}</strong><p>${esc(option.description)}</p><span class="augment-pick">选择强化 ↗</span></button>`).join("")}</div>`,
        )
        .join("") +
      (picked.length
        ? `<div class="selected-augments">${picked.map((option) => `<div><strong>✦ ${esc(option.name)}</strong><p>${esc(option.description)}</p></div>`).join("")}</div>`
        : "") +
      (!pending.length && !picked.length
        ? '<p class="empty-copy">海克斯在第 1、7、13 轮提供三选一强化。</p>'
        : "");
    const techniques = Array.isArray(state.techniques)
      ? state.techniques
      : state.techniques?.inventory || [];
    $("techniques-count").textContent = `${techniques.reduce((n, t) => n + (Number(t.count) || 0), 0)} 台`;
    $("techniques").innerHTML =
      '<p class="system-note">每只精灵可学习一项。优先消耗技能机免费学习，没有机器可花 2 金币学习；替换不返还旧技能。</p>' +
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
    setSystemTab(systemTab);
  }
  function rewardCards(row) {
    return `<div class="loot-cards">${(row?.grants || []).map((g) => `<div class="loot-card ${esc(g.kind)}"><span class="loot-icon" aria-hidden="true">${g.kind === "technique" ? "◎" : g.kind === "item" ? "◆" : "✧"}</span><div><strong>${esc(g.name)}</strong><small>${g.kind === "technique" ? "技能机 · 免费学习一次" : g.kind === "item" ? "成品装备 · 可直接装备" : "装备组件 · 可用于合成"}</small></div></div>`).join("")}</div>`;
  }
  function renderRoundLoot() {
    const rows = state.round_rewards || [];
    const latest = rows[rows.length - 1];
    $("round-loot").hidden = !latest;
    $("round-loot").innerHTML = latest ? `<div class="loot-heading"><strong>第 ${latest.round} 轮战利品</strong><span>${latest.result === "win" ? "胜利 · 2 份" : latest.result === "loss" ? "失利 · 1 份" : "平局 · 1 份"}已入仓</span></div>${rewardCards(latest)}` : "";
  }
  function scoutPieces(pieces, label) {
    const flat = (pieces || []).flat().filter(Boolean);
    return `<h3>${label} · ${flat.length} 只</h3><div class="scout-unit-grid">${flat.map((p) => `<div class="scout-unit${p.shiny ? " shiny" : ""}"><img src="${spriteOf(p)}" alt="${esc(p.name)}"><div><strong>${esc(p.name)} <span class="detail-star">${"★".repeat(starsOf(p))}${p.shiny ? " ✦" : ""}</span></strong><p class="role-${roleOf(p)}">${roleNames[roleOf(p)]} · ${attackStyle(p)} · ${esc(p.types.join(" / "))}</p><small>${p.item_name ? "装备 " + esc(p.item_name) : "未装备"}${p.technique ? " · " + esc(p.technique.name) : ""}</small></div></div>`).join("") || '<p class="empty-copy">暂无精灵。</p>'}</div>`;
  }
  function renderScout() {
    const seats = state.scouting || [];
    $("scout-tabs").innerHTML = seats
      .map(
        (p) =>
          `<button data-scout="${Number(p.seat)}" aria-pressed="${p.seat === scoutSeat}">${p.seat === 0 ? "我方" : esc(trainerName(p.name))}</button>`,
      )
      .join("");
    const p = seats.find((p) => p.seat === scoutSeat);
    $("scout-content").innerHTML = p
      ? `<div class="scout-heading"><h3>${p.seat === 0 ? "新叶训练家 · 我方" : esc(trainerName(p.name)) + " · 对手"}</h3><p>${Number(p.hp)} HP · Lv.${Number(p.level)} · ${Number(p.gold)} 金币</p></div>${scoutPieces(p.board, "上场阵容")}${scoutPieces(p.bench, "备战席")}<h3>海克斯强化</h3><p>${(p.augments || []).map((a) => esc(a.name || a)).join(" · ") || "尚未选择"}</p>`
      : '<p class="empty-copy">当前存档未提供侦察信息。新的竞技规则支持全部训练家侦察。</p>';
  }
  function renderCatalog() {
    const catalog = state.arena?.catalog || [];
    $("catalog-description").textContent =
      `${catalog.length} 种进化精灵，攻击、防守、辅助各 6 种。八位训练家共享卡池，同种同星三合一；三星需要九张并使用闪光配色。`;
    $("catalog-grid").innerHTML = catalog
      .filter((p) => roleFilter === "all" || roleOf(p) === roleFilter)
      .map(
        (p) =>
          `<article class="catalog-card"><img src="${spriteOf(p)}" alt="${esc(p.name)}"><div><h3>${esc(p.name)} <small>${Number(p.cost || p.tier)} 费</small></h3><p class="role-${roleOf(p)}">${roleNames[roleOf(p)]} · ${attackStyle(p)} · ${esc(p.types.join(" / "))}</p><p>${esc(p.role_description || "")}</p><p><b>${esc(p.skill_name)}</b> · ${esc(p.skill_type)}属性<br>${esc(p.skill_description)}</p><small>共享池剩余 ${Number(p.pool_remaining)} / ${Number(p.pool_total)} 张</small></div></article>`,
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
    render();
  }
  async function autoDeploy() {
    if (!canPrep()) return;
    deploying = true;
    selected = null;
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
  async function newGame() {
    closeBattle();
    $("result-dialog").close();
    systemTab = "augments";
    roleFilter = "all";
    scoutSeat = 1;
    const result = await api("new", { mode: "arena" });
    if (result?.ok) {
      $("new-dialog").close();
      toast("新的冒险开始了。先从商店招募一位伙伴吧。");
    }
  }
  async function resume() {
    const slot = sid || savedSlot();
    if (!slot) {
      toast("还没有可继续的存档。点击「新的冒险」开始。", true);
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

  function stopPlayback() {
    clearInterval(playback.timer);
    playback.timer = null;
    playback.playing = false;
    $("battle-pause").textContent = "播放";
  }
  function closeBattle() {
    playback.token++;
    stopPlayback();
    if ($("battle-dialog").open) $("battle-dialog").close();
  }
  function showVerdict() {
    if (playback.verdictShown) return;
    playback.verdictShown = true;
    const meta = playback.meta;
    const kind =
      meta?.winner === 0 ? "win" : meta?.winner === 1 ? "loss" : "draw";
    const overlay = $("battle-verdict");
    overlay.className = `battle-verdict ${kind}`;
    overlay.querySelector(".verdict-symbol").textContent =
      kind === "win" ? "✦" : kind === "loss" ? "◇" : "＝";
    overlay.querySelector("strong").textContent =
      kind === "win" ? "回合胜利" : kind === "loss" ? "回合失利" : "势均力敌";
    overlay.querySelector("p").textContent = String(
      meta?.headline || "本轮战果已保存",
    ).replace(/<[^>]*>/g, "");
    overlay.hidden = false;
    $("battle-result").textContent = meta?.headline || "本轮战果已保存";
    $("battle-result").className = `battle-result ${kind}`;
    const row = (state.round_rewards || []).find((r) => r.round === (meta?.round || state.round));
    $("battle-rewards").hidden = !row;
    $("battle-rewards").innerHTML = row ? `<h3>回合奖励 · 已入仓</h3><p>${row.result === "win" ? "胜利获得 2 份" : "失败或平局获得 1 份"}，下轮可装备或学习。</p>${rewardCards(row)}` : "";
    if (sound) tone(kind === "win");
  }
  function showFrame(index) {
    const p = playback;
    p.current = Math.max(0, Math.min(p.n - 1, index));
    if (p.current < p.n - 1) {
      $("battle-verdict").hidden = true;
      $("battle-rewards").hidden = true;
      p.verdictShown = false;
    }
    const image = p.frames[p.current];
    if (image?.naturalWidth) {
      const context = $("battle-canvas").getContext("2d");
      const canvas = $("battle-canvas");
      if (canvas.width !== image.naturalWidth || canvas.height !== image.naturalHeight) {
        canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
      }
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.imageSmoothingEnabled = false;
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
    }
    $("battle-status").textContent =
      `${(p.current * p.dt).toFixed(1)} 秒 / ${(Math.max(0, p.n - 1) * p.dt).toFixed(1)} 秒 · ${p.speed}×`;
    let last = -1;
    (p.meta?.events || []).forEach((event, i) => {
      const row = $(`play-event-${i}`);
      if (row) {
        const past = event.t <= p.current * p.dt;
        row.className = `event${past ? " past" : ""}`;
        if (past) last = i;
      }
    });
    if (last >= 0) {
      const row = $(`play-event-${last}`);
      row.className = "event now";
      const box = $("battle-events");
      box.scrollTop = Math.max(
        0,
        row.offsetTop - box.offsetTop - box.clientHeight + row.offsetHeight,
      );
    }
    if (p.n > 0 && p.current >= p.n - 1) showVerdict();
  }
  function play() {
    if (
      !playback.complete ||
      !playback.n ||
      document.hidden ||
      !$("battle-dialog").open
    )
      return;
    stopPlayback();
    if (playback.current >= playback.n - 1) showFrame(0);
    playback.playing = true;
    $("battle-pause").textContent = "暂停";
    playback.timer = setInterval(
      () => {
        showFrame(playback.current + 1);
        if (playback.current >= playback.n - 1) stopPlayback();
      },
      (playback.dt * 1000) / playback.speed,
    );
  }
  function emptyBattle(message) {
    const canvas = $("battle-canvas");
    canvas.width = 240; canvas.height = 320;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#314737";
    ctx.fillRect(0, 0, 240, 320);
    ctx.textAlign = "center";
    ctx.fillStyle = "#e8efd2";
    ctx.font = "bold 17px sans-serif";
    ctx.fillText("本轮战果已保存", 120, 142);
    ctx.fillStyle = "#a5b991";
    ctx.font = "11px sans-serif";
    ctx.fillText("点击下一轮，继续冒险", 120, 168);
    $("battle-status").textContent = message;
  }
  async function openBattle() {
    closeBattle();
    const token = playback.token;
    const meta = state.last_battle;
    Object.assign(playback, {
      meta,
      frames: [],
      current: 0,
      n: meta?.n || 0,
      dt: meta?.dt || 0.05,
      complete: false,
      verdictShown: false,
    });
    $("battle-verdict").hidden = true;
    $("battle-rewards").hidden = true;
    $("battle-title").textContent =
      `第 ${meta?.round || state.round} 轮 · 战斗时刻`;
    $("battle-subtitle").textContent = meta?.opp_name
      ? `你的伙伴 vs ${trainerName(meta.opp_name)}`
      : "本轮对战结算";
    $("battle-result").textContent = "回放结束后显示战果";
    $("battle-result").className = "battle-result";
    $("battle-events").innerHTML =
      (meta?.events || [])
        .map(
          (event, i) =>
            `<div class="event" id="play-event-${i}">${Number(event.t).toFixed(1)}s · ${esc(String(event.text).replace(/<[^>]*>/g, ""))}</div>`,
        )
        .join("") || "<p>这轮没有可回放的战斗事件。</p>";
    $("battle-next").textContent =
      state.phase === "over" ? "查看最终排名 →" : "下一轮 →";
    $("battle-pause").disabled = $("battle-skip").disabled = true;
    $("battle-dialog").showModal();
    if (!meta?.n) {
      emptyBattle(
        meta?.restored
          ? "历史画面未包含在存档中，战果和奖励已恢复。"
          : !state.you.alive
            ? "你的冒险已结束，仍可继续观战。"
            : "本轮没有战斗画面。",
      );
      showVerdict();
      return;
    }
    $("battle-status").textContent = `正在准备战斗画面 · ${meta.n} 帧`;
    emptyBattle("正在准备战斗画面…");
    let nextIndex = 0,
      failed = 0;
    const worker = async () => {
      while (nextIndex < meta.n && token === playback.token) {
        const i = nextIndex++;
        await new Promise((resolve) => {
          const im = new Image();
          let done = false;
          const timeout = setTimeout(() => finish(false), 15000);
          const finish = (ok) => {
            if (done) return;
            done = true;
            clearTimeout(timeout);
            if (ok && token === playback.token) playback.frames[i] = im;
            else failed++;
            if (i === 0 && ok && token === playback.token) showFrame(0);
            resolve();
          };
          im.onload = () => finish(true);
          im.onerror = () => finish(false);
          im.src = `/demo/frame/${sid}/r${meta.round}/${i}.png`;
        });
      }
    };
    await Promise.all(Array.from({ length: 6 }, worker));
    if (token !== playback.token) return;
    if (failed) {
      stopPlayback();
      emptyBattle(
        `有 ${failed} 帧未能载入。收起后可重试回放，或直接进入下一轮。`,
      );
      showVerdict();
      return;
    }
    playback.complete = true;
    $("battle-pause").disabled = $("battle-skip").disabled = false;
    showFrame(0);
    play();
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
    if (target.dataset.shop != null && canPrep())
      await api("buy", { i: target.dataset.shop });
    else if (target.dataset.loc) await chooseCell(target.dataset.loc);
    else if (target.dataset.equip && canPrep()) {
      equipItem =
        equipItem === target.dataset.equip ? null : target.dataset.equip;
      selected = null;
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
    else if (target.dataset.learn && canPrep()) {
      const loc = $("learn-" + target.dataset.learn).value;
      if (loc) await api("learn", { loc, technique: target.dataset.learn });
    } else if (target.dataset.scout != null) {
      scoutSeat = Number(target.dataset.scout);
      renderScout();
      if (!$("scout-dialog").open) $("scout-dialog").showModal();
    } else if (target.dataset.roleFilter) {
      roleFilter = target.dataset.roleFilter;
      renderCatalog();
    } else if (target.dataset.action === "cancel-select") {
      selected = null;
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
  document.addEventListener("dragstart", (event) => {
    const cell = event.target.closest("[data-loc][data-owned]");
    if (!cell || !canPrep()) {
      event.preventDefault();
      return;
    }
    selected = cell.dataset.loc;
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
  $("new-button").onclick = () => {
    if (state) $("new-dialog").showModal();
    else newGame();
  };
  $("new-cancel").onclick = () => $("new-dialog").close();
  $("new-confirm").onclick = newGame;
  $("result-new").onclick = newGame;
  $("result-close").onclick = () => $("result-dialog").close();
  $("resume-button").onclick = resume;
  const help = () => $("help-dialog").showModal();
  $("help-button").onclick = help;
  $("mobile-help-button").onclick = help;
  $("help-close").onclick = () => $("help-dialog").close();
  $("scout-close").onclick = () => $("scout-dialog").close();
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
      const tabs = ["augments", "techniques", "items"];
      const index = tabs.indexOf(systemTab);
      setSystemTab(
        event.key === "Home"
          ? tabs[0]
          : event.key === "End"
            ? tabs[2]
            : tabs[(index + (event.key === "ArrowRight" ? 1 : 2)) % 3],
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
  $("battle-close").onclick = closeBattle;
  $("battle-dialog").addEventListener("cancel", () => {
    playback.token++;
    stopPlayback();
  });
  $("battle-pause").onclick = () =>
    playback.playing ? stopPlayback() : play();
  $("battle-skip").onclick = () => {
    stopPlayback();
    showFrame(playback.n - 1);
  };
  $("battle-speed").onchange = () => {
    playback.speed = Number($("battle-speed").value);
    if (playback.playing) play();
    else if (playback.complete) showFrame(playback.current);
  };
  $("battle-next").onclick = nextRound;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopPlayback();
  });
  document.addEventListener("keydown", (event) => {
    if (
      event.repeat ||
      event.altKey ||
      event.ctrlKey ||
      event.metaKey ||
      /INPUT|SELECT|TEXTAREA|BUTTON/.test(event.target.tagName) ||
      document.querySelector("dialog[open]")
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
