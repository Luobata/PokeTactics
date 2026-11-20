/* Original vector icons for components and items (docs/71). No external art:
 * every icon is composed from a few SVG primitives in a 24×24 box.
 *   ItemIcons.html(key, {size, kind}) → <span class="item-icon …"><svg …/></span>
 * Awakened keys (<base>_plus) get a gold halo + spark; treasures a gold frame. */
(() => {
  "use strict";
  const INK = "#2a2a22";
  const o = (fill, extra = "") => `fill="${fill}" stroke="${INK}" stroke-width="1.1" stroke-linejoin="round" stroke-linecap="round" ${extra}`;
  const line = (d, color = INK, w = 1.2) => `<path d="${d}" fill="none" stroke="${color}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"/>`;
  const shine = (x, y, r = 2.2) => `<circle cx="${x}" cy="${y}" r="${r}" fill="#fff" opacity=".6"/>`;

  // ---- primitives
  const orb = (c, mark = "") => `<circle cx="12" cy="12.5" r="8.3" ${o(c)}/>${mark}${shine(9, 9.4)}`;
  const bell = (c, mark = "") => `<path d="M12 3.6c-3.6 0-5.5 3-5.5 6.8v4.2l-1.9 2.4h14.8l-1.9-2.4v-4.2c0-3.8-1.9-6.8-5.5-6.8z" ${o(c)}/><circle cx="12" cy="19.2" r="1.7" ${o("#e8c25a")}/>${mark}${shine(9.6, 8)}`;
  const rock = (c, mark = "") => `<path d="M3.8 16.5 6.6 8 12.4 4.8 18.6 8.4 20.3 15.8 14.6 19.6 7.4 19.6z" ${o(c)}/>${line("M6.6 8 11 11.5 12.4 4.8M11 11.5 14.6 19.6M11 11.5 18.6 8.4", "#00000040", .9)}${mark}`;
  const gem = (c, mark = "") => `<path d="M12 3 19 9.5 12 21 5 9.5z" ${o(c)}/>${line("M5 9.5h14M12 3 9 9.5 12 21 15 9.5z", "#ffffff70", .8)}${mark}`;
  const charm = (c, inner) => `${line("M12 2.5v4", INK, 1.2)}<circle cx="12" cy="5.5" r="1.4" ${o("#e8c25a")}/>${inner}`;

  const ICONS = {
    // ---- components
    band: `<path d="M3 11c3-2.6 15-2.6 18 0l-.6 3.6c-3.4-2-13.4-2-16.8 0z" ${o("#d94b3d")}/><path d="M17 12.6l3.6 5.4-2.8.2-2.2-4.4z" ${o("#d94b3d")}/>${line("M6 11.8c3-1 9-1 12 0", "#ffffff80", 1)}`,
    hardstone: rock("#9b8f7a"),
    magnet: `<path d="M5 4h4.4v8a2.6 2.6 0 0 0 5.2 0V4H19v8a7 7 0 0 1-14 0z" ${o("#c8473f")}/><path d="M5 4h4.4v3H5zM14.6 4H19v3h-4.4z" ${o("#d9dde2")}/>`,
    shoes: `<path d="M4 15.5V9.2l4-.6 1.4 3 6.2 1.2c2.6.6 4.4 1.6 4.4 3.6v1.6H4z" ${o("#4f8fd6")}/>${line("M4 15.6h16", "#ffffff90", 1)}${line("M8.5 10.2l1.6-.6M9.6 12l1.6-.6", "#ffffffb0", 1)}`,
    bell: `<path d="M12 4C7 4 3.6 8 4 13.2c.2 2.4 2 4.8 8 4.8s7.8-2.4 8-4.8C20.4 8 17 4 12 4z" ${o("#f2c7c0")}/>${line("M12 4v14M8 5.4l1.4 12.2M16 5.4l-1.4 12.2", "#c58a80", 1)}<path d="M9.4 18h5.2l-1 2.6h-3.2z" ${o("#f2c7c0")}/>`,
    charcoal: `<path d="M4.4 14.6 7 8.4l5.4-2.2 6 2.6 1.4 6.2-4.6 3.8H9z" ${o("#3b3b3f")}/><path d="M9 13.2c.6-2 2.2-2.4 2.6-4.2 1.4 1.6 2.6 3 1.8 5-.8 1.6-3.8 1.4-4.4-.8z" fill="#ff8a3d" opacity=".9"/>`,
    mysticwater: `<path d="M12 3.2c3.4 4.6 6 7.8 6 11a6 6 0 0 1-12 0c0-3.2 2.6-6.4 6-11z" ${o("#5aa8e6")}/>${shine(9.6, 13.4, 2)}`,
    spark: `<path d="M13.6 2.8 6 13.4h5.2l-1.4 7.8 8.2-11.4h-5.4z" ${o("#f4d23c")}/>`,

    // ---- strike / damage
    metronome: `<path d="M7 20.4h10L13.4 4h-2.8z" ${o("#c2884e")}/>${line("M12 18.2 15.6 6.6", INK, 1.3)}<circle cx="14.6" cy="9.6" r="1.6" ${o("#e8c25a")}/>`,
    boomerang: `<path d="M4 6.4c5.6-1.4 11 .6 15.4 6.2-2.6-1.4-6.2-2-9.2-1.2l-1.6 8.8C6.4 15.4 4 11 4 6.4z" ${o("#d98a2b")}/>${line("M6 8.4c3-.4 6 .4 8.6 2.2", "#ffffff90", 1)}`,
    drain_fang: `<path d="M5 4.4c4.6 0 9.8.4 14 0-1.6 6-3.8 11.2-7 15.6C8.8 15.6 6.6 10.4 5 4.4z" ${o("#f4f1e4")}/><path d="M10.2 13.6c.8 1.2 1.2 2.2 1.8 3.4.6-1.2 1-2.2 1.8-3.4z" fill="#c8323f"/>`,
    life_orb: orb("#8b3fb8", `<path d="M12 8.4c2.4 1.6 2.8 4.4 0 7.8-2.8-3.4-2.4-6.2 0-7.8z" fill="#f17ad1" opacity=".85"/>`),
    pulse_band: `<rect x="4" y="8.4" width="16" height="7.4" rx="3.2" ${o("#3b74c4")}/><path d="M12.6 9.4 9.8 13h2.4l-.8 2.4 3-3.8h-2.4z" fill="#f4d23c"/>`,
    weakness_policy: `<path d="M6 3.4h9l3 3v14.2H6z" ${o("#f4f1e4")}/>${line("M8.4 9h7.2M8.4 12h7.2M8.4 15h4.4", "#8a8573", 1)}<circle cx="16" cy="16.6" r="3" ${o("#d94b3d")}/>`,
    reaper_scale: `<path d="M12 3.4c4.8 2 7.4 6.2 6.6 10.6-.8 4-3.4 6.4-6.6 6.6-3.2-.2-5.8-2.6-6.6-6.6C4.6 9.6 7.2 5.4 12 3.4z" ${o("#5d6fa8")}/>${line("M8.4 10.6c2.4 1.4 4.8 1.4 7.2 0M8.8 14.6c2.2 1.2 4.2 1.2 6.4 0", "#c7d2f2", 1)}`,
    expert_belt: `<rect x="2.8" y="9" width="18.4" height="6" rx="1.4" ${o("#3b3b3f")}/><rect x="9.2" y="7.4" width="5.6" height="9.2" rx="1" ${o("#e8c25a")}/>${line("M3 12h6M15 12h6", "#d94b3d", 1.4)}`,
    kings_rock: `<path d="M4.4 17.6 5.4 7.4l4 4L12 5l2.6 6.4 4-4 1 10.2z" ${o("#e8c25a")}/><path d="M4.4 17.6h15.2v2.4H4.4z" ${o("#c79a1a")}/><circle cx="12" cy="13.6" r="1.4" fill="#d94b3d"/>`,
    lightning_rod: `${line("M12 3.4v16.4", INK, 2.4)}${line("M12 3.4v16.4", "#b8c0c8", 1.2)}<path d="M8 20h8v1.6H8z" ${o("#8a8f96")}/><path d="M16.4 4.4 13.8 9h2l-1 3.4 3-4.6h-2z" fill="#f4d23c" stroke="${INK}" stroke-width=".7"/>`,

    // ---- status
    flame_orb: orb("#e8742b", `<path d="M12 7.6c2.6 2 3.6 4.2 2.6 6.8-.6 1.4-1.6 2-2.6 2s-2-.6-2.6-2c-.6-1.6 0-3 1.2-4 .2 1 .6 1.6 1.4 1.8-.6-1.6-.4-3 0-4.6z" fill="#ffd25a"/>`),
    toxic_orb: orb("#8a4fc0", `<circle cx="10.4" cy="13.6" r="1.8" fill="#c9f07a"/><circle cx="14" cy="11.4" r="1.3" fill="#c9f07a"/><circle cx="13.8" cy="15.4" r="1" fill="#c9f07a"/>`),
    contagion_orb: orb("#5aa06a", `<circle cx="12" cy="12.6" r="2" fill="#f2e86a"/>${line("M12 8v2.4M12 15v2.4M7.6 12.6H10M14 12.6h2.4", "#f2e86a", 1.2)}`),
    static_glove: `<path d="M6.4 20V11l-1.6-3.6 2-.8 1.6 3V5.2h2v4.6V4.4h2v5.4V5.2h2v5.6V7h2v8.4c0 3-1.8 4.6-4.4 4.6z" ${o("#f2d04a")}/><path d="M18.4 3.6 16.6 6.6h1.4l-.8 2.2 2.2-3h-1.4z" fill="#3b74c4"/>`,
    healing_needle: `${line("M5 19 14.6 9.4", INK, 2.6)}${line("M5 19 14.6 9.4", "#d9dde2", 1.4)}<path d="M13.4 8.2 17 4.6l2.4 2.4-3.6 3.6z" ${o("#c8473f")}/>${line("M17.2 6.8l2.6-2.6", INK, 1.2)}`,
    kings_rock_alt: "",

    // ---- impact
    impact_gauntlet: `<path d="M5 11.4c0-3 2-5.2 5-5.2h4.4c3 0 4.6 2 4.6 5v4.6c0 2.4-1.6 4-4 4H9.6C7 19.8 5 18 5 15.4z" ${o("#c96a3a")}/>${line("M9 6.4v4M12.4 6.2v4M15.6 6.6v4", "#00000050", 1)}${line("M2.4 8.4h2M1.8 12h2.4M2.4 15.6h2", "#e8742b", 1.3)}`,
    red_card: `<rect x="6" y="3.4" width="12" height="17.2" rx="1.6" ${o("#d93a3a")}/>${line("M8.6 7h6.8", "#ffffffa0", 1.2)}`,
    trap_lens: `<circle cx="10.4" cy="10.4" r="6" ${o("#bfe3f2")}/>${line("M14.8 14.8 20 20", INK, 2.4)}<path d="M8 12.6 10.4 7.6l2.4 5z" fill="#8a7a5a"/>`,
    heavy_boots: `<path d="M6.4 3.6h6v8.6l6.2 2.4c1.4.6 1.8 1.4 1.8 2.8v1.6H5V12z" ${o("#6b5844")}/><path d="M4.6 18.8h16v2H4.6z" ${o("#3b3b3f")}/>`,
    tide_shell: `<path d="M12 4.4c5 0 8.6 3.4 8.6 7.8 0 3.6-2.6 6.6-8.6 7.8-6-1.2-8.6-4.2-8.6-7.8 0-4.4 3.6-7.8 8.6-7.8z" ${o("#7cc4d8")}/>${line("M12 20V5M8 19 7 6.6M16 19l1-12.4", "#2f7d94", 1)}`,
    escape_pack: `<path d="M6.4 8.4c0-2.6 2.4-4.6 5.6-4.6s5.6 2 5.6 4.6v10.4c0 1-.8 1.6-1.6 1.6H8c-.8 0-1.6-.6-1.6-1.6z" ${o("#4f8f5a")}/><rect x="8.6" y="12" width="6.8" height="4.6" rx="1" ${o("#e8c25a")}/>`,
    storm_chime: `${line("M5 4.4h14", INK, 1.4)}${line("M8 4.4v8M12 4.4v11M16 4.4v6.4", "#8a8f96", 1.2)}<rect x="6.8" y="12" width="2.4" height="4.4" rx=".8" ${o("#7cc4d8")}/><rect x="10.8" y="15" width="2.4" height="4.4" rx=".8" ${o("#7cc4d8")}/><rect x="14.8" y="10.4" width="2.4" height="4.4" rx=".8" ${o("#7cc4d8")}/>`,

    // ---- arcane
    mind_crystal: gem("#b07ae0"),
    quick_claw: `<path d="M5 19.6c1-6 3.4-11 7.6-15.4-1.2 4.6-1.2 8.4 0 12.4-2.6 1-5 2-7.6 3z" ${o("#f4f1e4")}/><path d="M11 19.6c1.4-5 3.8-9.2 7.6-12.6-.8 4.2-.6 7.6.6 10.6-2.6.6-5.4 1.2-8.2 2z" ${o("#f4f1e4")}/><circle cx="18" cy="5" r="2" fill="#4f8fd6"/>`,
    echo_bell: bell("#e8c25a", `${line("M20.6 7.6c1.2 1.6 1.2 4 0 5.6M3.4 7.6c-1.2 1.6-1.2 4 0 5.6", "#4f8fd6", 1.2)}`),
    torrent_orb: orb("#3b74c4", `${line("M8 13.6c1.4-1.4 2.6-1.4 4 0s2.6 1.4 4 0", "#bfe3f2", 1.4)}`),
    relay_coil: `${line("M5 12c0-3 2-3 2 0s2 3 2 0 2-3 2 0 2 3 2 0 2-3 2 0 2 3 2 0", "#c79a1a", 2.4)}${line("M5 12c0-3 2-3 2 0s2 3 2 0 2-3 2 0 2 3 2 0 2-3 2 0 2 3 2 0", "#f4d23c", 1.1)}<circle cx="4" cy="12" r="1.6" ${o("#d94b3d")}/><circle cx="20" cy="12" r="1.6" ${o("#3b74c4")}/>`,
    damp_rock: rock("#5d8fb8", `<path d="M12 8.6c1.4 1.8 2.4 3 2.4 4.2a2.4 2.4 0 0 1-4.8 0c0-1.2 1-2.4 2.4-4.2z" fill="#bfe3f2"/>`),
    heat_rock: rock("#c4573a", `<circle cx="12" cy="12.6" r="2.6" fill="#ffd25a"/>`),
    mirror_coat: `<path d="M12 3 19.2 7.2v9.6L12 21l-7.2-4.2V7.2z" ${o("#c9d6e6")}/>${line("M8.4 9.6 12 7.6M8.4 13l6-3.4", "#ffffffd0", 1.2)}`,
    rally_whistle: `<path d="M3.6 10.4h9.6a4.6 4.6 0 1 1-4.6 4.6V14H3.6z" ${o("#e8c25a")}/><circle cx="13.2" cy="15" r="1.6" fill="${INK}"/>${line("M16 6.4l1.6-2M18.6 8.6l2.2-1M14 5.6V3.4", "#d94b3d", 1.2)}`,

    // ---- guard / support
    sash: `<path d="M7 3.4h3.6l6.4 13.2-1.8 4H12l1-3.6z" ${o("#d94b3d")}/><path d="M13.6 3.4h3.6L11 16.6l-2.4 1.4z" ${o("#f2a03a")}/>`,
    ward_bracer: `<path d="M6 7.4c4-1.6 8-1.6 12 0v9.2c-4 1.6-8 1.6-12 0z" ${o("#5d7f9e")}/><path d="M12 8.6c1.6.4 2.6 1 3 1.4 0 3-1.2 5-3 6-1.8-1-3-3-3-6 .4-.4 1.4-1 3-1.4z" fill="#e8c25a"/>`,
    lucky_egg: `<path d="M12 3.4c3.6 0 6.4 5 6.4 9.4 0 4.2-2.8 7.6-6.4 7.6s-6.4-3.4-6.4-7.6c0-4.4 2.8-9.4 6.4-9.4z" ${o("#f6efd6")}/><circle cx="10" cy="11" r="1.6" fill="#e8c25a"/><circle cx="14" cy="15.2" r="1.3" fill="#e8c25a"/>`,
    taunt_bell: bell("#c96a3a", `<path d="M10 9.6l2 1.4 2-1.4" fill="none" stroke="#ffd25a" stroke-width="1.2"/>`),
    leftovers: `<path d="M12 6.6c3.6-1.6 7.2.6 7.2 5 0 4.6-3.2 8.6-7.2 8.6s-7.2-4-7.2-8.6c0-4.4 3.6-6.6 7.2-5z" ${o("#d94b3d")}/><path d="M14.6 7.4c1.6 2.4 1.6 6.6 0 10.6" ${o("#f6efd6")}/>${line("M12 6.6c0-1.6.6-2.6 1.6-3.2", "#6b5844", 1.3)}`,
    grounding_cloak: `<path d="M8 4h8l3.6 15.6c-2.4 1-5 1.4-7.6 1.4s-5.2-.4-7.6-1.4z" ${o("#6b5fa8")}/>${line("M12 4v17", "#ffffff50", 1)}<circle cx="12" cy="6" r="1.4" fill="#e8c25a"/>`,
    heart_bell: bell("#f2a0b4", `<path d="M12 12.6c-1.6-1.2-2.6-2-2.6-3 0-.8.6-1.4 1.4-1.4.6 0 1 .4 1.2.8.2-.4.6-.8 1.2-.8.8 0 1.4.6 1.4 1.4 0 1-1 1.8-2.6 3z" fill="#d93a5a"/>`),
    clarity_charm: charm("#7cc4d8", gem("#bfe3f2")),
    dew_charm: charm("#5aa8e6", `<path d="M12 8c2.6 3.4 4.4 5.6 4.4 8a4.4 4.4 0 0 1-8.8 0c0-2.4 1.8-4.6 4.4-8z" ${o("#bfe3f2")}/>`),
    blast_core: `<circle cx="11" cy="13.4" r="7" ${o("#3b3b3f")}/>${line("M15.6 8.4 18 6", INK, 1.4)}<path d="M18 6l1.2-2.2.6 1.4 1.6-.4-1 1.4 1 1.2-1.6.2" fill="#ff8a3d"/>${shine(8.6, 11, 1.8)}`,
    revival_seed: `<path d="M12 20.6c-3.6 0-6-2-6-4.6 0-2 2-3.4 6-3.4s6 1.4 6 3.4c0 2.6-2.4 4.6-6 4.6z" ${o("#a8763e")}/>${line("M12 13V7", "#3f8a3c", 1.6)}<path d="M12 8.6C10 5 7 5 5.6 6.4 7.6 9 10 9.4 12 8.6zM12 7.4c1.6-3 4.4-3.4 6-2.2-1.6 2.6-4 3.2-6 2.2z" ${o("#6fc25a")}/>`,
    safety_goggles: `<path d="M3 10.4c0-1.4 1-2.4 2.4-2.4h13.2c1.4 0 2.4 1 2.4 2.4v3.4c0 1.6-1.2 2.6-2.6 2.6h-2.6c-1 0-1.6-.6-2-1.4L12.6 13h-1.2l-1.2 2c-.4.8-1 1.4-2 1.4H5.6C4.2 16.4 3 15.4 3 13.8z" ${o("#3b3b3f")}/><rect x="4.8" y="9.6" width="5.4" height="4.8" rx="1.6" fill="#7cc4d8"/><rect x="13.8" y="9.6" width="5.4" height="4.8" rx="1.6" fill="#7cc4d8"/>`,
    light_clay: `<path d="M5 15.6c-.6-3.6 2-7 6.6-7.6 4.6-.4 7.8 2 7.6 5.6-.2 3.2-3.4 5.4-7.4 5.4S5.4 18 5 15.6z" ${o("#e6dcc0")}/><circle cx="12" cy="13" r="2.4" fill="#fff8c8"/>${line("M12 3.6v2.4M18 5.4l-1.4 1.6M6 5.4l1.4 1.6", "#e8c25a", 1.3)}`,
  };
  delete ICONS.kings_rock_alt;
  const FALLBACK = gem("#a9b3a0");

  const TREASURES = new Set(["weakness_policy", "reaper_scale", "revival_seed", "rally_whistle", "safety_goggles", "light_clay", "expert_belt", "kings_rock"]);
  const AWAKEN_HALO = `<circle cx="12" cy="12" r="11.2" fill="none" stroke="#f0b62a" stroke-width="1.4" stroke-dasharray="2.4 1.6"/><path d="M19.6 1.6l.8 1.8 1.8.8-1.8.8-.8 1.8-.8-1.8-1.8-.8 1.8-.8z" fill="#f0b62a" stroke="${INK}" stroke-width=".5"/>`;

  function svg(key) {
    const plus = /_plus$/.test(key || "");
    const base = plus ? key.slice(0, -5) : key;
    const body = ICONS[base] || FALLBACK;
    return `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${body}${plus ? AWAKEN_HALO : ""}</svg>`;
  }
  function html(key, {size = 24, cls = ""} = {}) {
    const base = String(key || "").replace(/_plus$/, "");
    const kind = /_plus$/.test(key || "") ? " awakened" : TREASURES.has(base) ? " treasure" : "";
    return `<span class="item-icon${kind}${cls ? " " + cls : ""}" style="--icon:${Number(size)}px">${svg(key)}</span>`;
  }
  window.ItemIcons = {html, svg, has: (key) => Boolean(ICONS[String(key || "").replace(/_plus$/, "")])};
})();
