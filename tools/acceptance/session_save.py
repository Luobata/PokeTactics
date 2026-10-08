"""PokeTactics snapshot codec. Storage/backup policy lives in esp32_runtime.

Schema 1 records owned accounting explicitly: the same species can be bought,
merged or stone-evolved with different sources and investment. Loading never
calls begin_round, decide, roll or combat: income/rewards cannot be replayed.
"""
import base64
import binascii
import copy
import hashlib
import json
import math
import re
import zlib
from collections import Counter
from pathlib import Path
from esp32_runtime import UnsupportedVersionError

ROOT = Path(__file__).resolve().parents[2]
COMMON = ("gold", "hp", "level", "xp", "streak", "alive", "rank", "last_damage",
          "combines", "stone_used", "item_drops")
BOT_STATS = ("gold_curve", "pop_curve", "synergy_curve", "synergy_formed_round",
             "synergy_formed_type", "refreshes", "item_crafts", "item_equips",
             "stone_triggers", "craft_stats")
LEGACY_BASE_FINGERPRINT = '2f9426505cad1addbab7b5db1e9f5a673a72ec0937a1ed4cf916926c04d015ad'
LEGACY_TACTICS_FINGERPRINT = 'f05ad20bf84e27917c269487469914f042cc03bde53176a2c4b845b092bb343c'
LEGACY_ABILITIES_FINGERPRINT = 'b39cb3c1756b71d4a26a1f79b613683ee6852bdad66709fc1cd1138d66cde23f'
LEGACY_COUNTER_PACING_FINGERPRINT = '2a469a66cce17970c78393f495305f55cb52c6a92e2264a164e6861095ac5fbb'
PRE_ARENA_FINGERPRINT = '6e763935b92f008c231a81a7b5742c0db2062d7ef42bc43f34cbf8f479d994da'
TWO_ROW_ARENA_FINGERPRINT = '3ec245248bf2a189a298cc195136acf8916fc98c73bbc932e9c486dd683fb68c'
PRE_NATIVE_SKILLS_FINGERPRINT = '42b5fca83d6fc77617522abe1eae8b85f4e0b88d7d9f45d925db0c8c7ad273a0'
# Exact first native build, before the lethal Shadow Siphon transfer fix.
# The schema and inventory/loot records are identical to the current build.
NATIVE_SKILLS_INITIAL_FINGERPRINT = '5e47e4575d043cc72be0560b77992171b44c8f53aed2ad496f6e1f01879c0c30'
# Last native-skill build before arena combination equipment and augments.
# Existing choices, rewards and resources remain committed on upgrade.
PRE_COMBINATIONS_FINGERPRINT = '2215e899fa6f75dbd3a3b7254fb648bc4de3913052bbdf23d6d370c7bb3e6243'
# Verified eighteen-species predecessor, including native combinations.
PRE_EXPANSION_FINGERPRINT = 'f55e36be0c93114a15df5975fa6dcd74cc1a401cbfab76c2bddb29cc1c818c03'
# Verified thirty-species predecessor, before supplemental Gen2 data/skills.
PRE_GEN2_FINGERPRINT = '49f76d703092c70ff309f04d33da3017ec9121cf19468684434b73a757321522'
# Verified 48-species build before per-unit combat statistics/history.
PRE_STATISTICS_FINGERPRINT = 'a17c3d6c9e66901a6e6f421873b1150e3b859dc9295f1b1609b4673216a83af7'
# Verified 48-species build with statistics, before native skill identities.
# It has the complete pool/TM ledger and must not use roster-expansion fallback.
PRE_SKILL_IDENTITIES_FINGERPRINT = '14536e0d3642dda0ac35f764c565d580e117cd8c5931732c198c8e68056b7214'
# Verified identity build before shield/cleanse/displacement combo branches.
# Full 48-species inventory, learning ledger and history must remain strict.
PRE_COMBO_BRANCHES_FINGERPRINT = 'ad411eac1e8f64580bdd147f928a69205d6ca7d99327cb46ad0e6d3291aac9a4'
# Verified shield/cleanse/displacement build before attack branch equipment.
# Preserve its complete ledgers and both historical summary shapes verbatim.
PRE_ATTACK_BRANCHES_FINGERPRINT = 'dda7aa66a9a16de3f6901fd484199cbac5f4dedee0a54be638b1e4d382fc134d'
# Verified attack build before arena bonds and milestone component choices.
# New supplies start after loading; committed loot/history must not be replayed.
PRE_ARENA_BONDS_FINGERPRINT = '24e6144376ae728d20e4bb3adecc4e25b25aac6ff0d49b2462243fe30411d8cf'
# Verified bond/supply build before fixed species passives and new equipment.
# Its complete component, pool, teaching and historical ledgers stay strict.
PRE_TRAITS_GEAR_FINGERPRINT = '6fc72304a52e7df57665c33931933063ebd6ca66cc54d983ec97d67112d8122c'
# Verified fixed-trait build before selectable alternatives and arena weather.
# Only live piece snapshots gain an implicit None choice; history stays verbatim.
PRE_ARENA_SYNERGY_FINGERPRINT = '52058d2c7f7a83950ecca4a734e4263481ba62cf0027ec4245abf22a1b4ff2f2'
PRE_SYNERGY_TECHNIQUES = frozenset({'cut', 'surf', 'rest', 'thunderbolt', 'ice_beam',
                                     'toxic', 'earthquake', 'roar', 'rapid_spin'})
# Exact arena catalog from the frozen fixed-trait predecessor. Its fingerprint
# cannot authenticate new items/teaching in live snapshots or committed loot.
PRE_SYNERGY_ITEMS = frozenset({
    'bright_powder', 'choice_band', 'clarity_charm', 'contagion_orb', 'dew_charm',
    'drain_fang', 'focus_lens', 'grounding_cloak', 'healing_needle', 'heart_bell',
    'heavy_boots', 'leftovers', 'lucky_egg', 'metronome', 'pulse_band', 'relay_coil',
    'sash', 'scarf_electric', 'scarf_fire', 'scarf_water', 'storm_chime', 'swift_feather',
    'tide_shell', 'torrent_orb', 'trap_lens', 'ward_bracer', 'weather_stone'})
BATTLE_STAT_FIELDS = ('damage_dealt', 'healing_done', 'self_healing', 'damage_taken', 'shield_absorbed')
REPORT_EFFECT_KEYS = ('effect_version', 'combinations', 'enemy_combinations', 'fields', 'enemy_fields')
COMBINATION_COUNTERS = ('triggers', 'energy', 'shield', 'absorbed', 'charges', 'damage',
                        'damage_absorbed', 'vulnerable', 'spreads', 'tempo_stacks', 'offense_buffs',
                        'healing', 'cleanses', 'statuses', 'mitigated', 'accuracy_saves', 'weakens')
FIELD_COUNTERS = ('triggers', 'damage', 'absorbed', 'avoided', 'cleared')


class UnknownRulesError(UnsupportedVersionError, ValueError):
    """A verified incompatible rule version must not trigger old-bank recovery."""


def rules_fingerprint():
    digest = hashlib.sha256()
    for path in sorted((ROOT / "sim").glob("*.py")) + sorted((ROOT / "data").glob("*.json")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"存档字段 {label} 超出范围")
    return value


def sequence(value, maximum, label):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"存档字段 {label} 列表无效")
    return value


def owned_record(owned, evolution_choices=False, arena=False):
    record = {"species": owned.piece.species_id, "item": owned.item,
            "uid": owned.uid, "technique": owned.technique,
            "sources": list(owned.sources), "invested": owned.invested}
    if evolution_choices:
        record['evolution_locked'] = owned.evolution_locked
    trait_key = getattr(owned, 'arena_trait', None)
    if arena:
        import arena_traits
        trait_key = arena_traits.validate_choice(owned.piece.species_id, trait_key)
        record['star'] = owned.piece.star
        record['arena_trait'] = trait_key
    elif trait_key is not None:
        raise ValueError('非竞技棋子不能包含竞技特性选择')
    return record


def comp_record(comp, arena=False):
    records = []
    for value in comp:
        p, item = value if isinstance(value, tuple) else (value, None)
        row = {"species": p.species_id, "item": item}
        trait_key = getattr(p, 'arena_trait_key', None)
        if arena:
            import arena_traits
            trait_key = arena_traits.validate_choice(p.species_id, trait_key)
            row['star'] = getattr(p, 'star', 1)
            row['arena_trait'] = trait_key
        elif trait_key is not None:
            raise ValueError('非竞技阵容不能包含竞技特性选择')
        records.append(row)
    return records


class SessionCodec:
    game_id = "poketactics"
    schema_version = 5

    def encode(self, state):
        import tactics
        choices = tactics.evolution_choices_enabled(state.ruleset)
        is_arena = state.ruleset == 'arena_v1'
        state.ensure_unit_ids()
        seats = []
        for seat in state.seats:
            data = {key: getattr(seat, key) for key in COMMON}
            data.update({"seat": seat.seat, "shop": list(seat.shop.slots),
                         "board": [owned_record(o, choices, is_arena) for o in seat.board],
                         "bench": [owned_record(o, choices, is_arena) for o in seat.bench],
                         "components": dict(seat.inventory.components),
                         "finished": list(seat.inventory.finished),
                         "techniques": dict(seat.inventory.techniques),
                         "last_opponent": getattr(getattr(seat, "_last_opp", None), "seat", None)})
            if seat.seat == 0:
                data.update({"grid": [[r, c, owned_record(seat.grid[(r, c)], choices, is_arena)]
                                      for r, c in sorted(seat.grid)],
                             "refresh_j": seat.refresh_j, "shop_locked": seat.shop_locked})
            else:
                data.update({"ability": seat.ability, "personality": seat.pers_key,
                             "target_types": list(seat.target_types),
                             "stats": {key: copy.deepcopy(getattr(seat, key)) for key in BOT_STATS}})
            seats.append(data)
        meta = state.last_battle
        summary = ({key: copy.deepcopy(meta[key]) for key in
                    ("winner", "survivors", "duration", "round", "pve", "ghost", "opp_name", "statistics", *REPORT_EFFECT_KEYS) if key in meta}
                   if meta else None)
        if summary is not None:
            summary.setdefault('opp_name', (state.opp_view or {}).get('name', '对手'))
            summary.setdefault('statistics', None)
        history = copy.deepcopy(state.battle_history)
        if summary is not None and not history:
            history.append({
                'round': summary.get('round', state.round_no), 'winner': summary['winner'],
                'duration': summary.get('duration', 0), 'pve': summary.get('pve', False),
                'ghost': summary.get('ghost', False), 'opp_name': summary['opp_name'],
                'statistics': copy.deepcopy(summary['statistics']),
                **({key: copy.deepcopy(summary[key]) for key in REPORT_EFFECT_KEYS}
                   if summary.get('effect_version') == 1 else {}),
            })
        summary = self._pack_report(summary) if summary is not None else None
        history = [self._pack_report(row) for row in history]
        payload = {"rules": rules_fingerprint(), "seed": state.seed, "round": state.round_no,
                "ruleset": state.ruleset, "tactical": copy.deepcopy(state.tactical),
                "rewards": copy.deepcopy(state.rewards),
                "next_unit_id": state.next_unit_id,
                "expedition_state": {"run_id": state.run_id, "loadout": state.expedition,
                                     "discoveries": state.discoveries},
                "phase": state.phase, "seats": seats,
                "pool": {str(k): v for k, v in state.pool.remaining.items()},
                "pairs": [[a.seat, b.seat] for a, b in state.pairs] if state.pairs is not None else None,
                "ghost_seat": getattr(state.ghost_seat, "seat", None),
                "ghost_source": getattr(state.ghost_src, "seat", None),
                "opponent_comp": comp_record(state.opponent_comp, is_arena) if state.opponent_comp is not None else None,
                "opponent_learned": state.opponent_learned,
                "opponent_tactics": copy.deepcopy(state.opponent_tactics),
                "log": list(state.log), "last_battle": summary,
                "battle_history": history,
                "player_battles": state.player_battles, "player_frames_total": state.player_frames_total,
                "eliminated_round": state.eliminated_round,
                "final_team": [{"species": o["sid"], "item": o.get("item"),
                                **({'star': o['star']} if is_arena else {}),
                                "technique": (o.get('technique') or {}).get('id')}
                               for o in state.final_team] if state.final_team is not None else None}
        if is_arena:
            payload['arena'] = {
                'pending': [{"id": row['id'], "round": row['round'],
                             "options": [o['id'] for o in row['options']]}
                            for row in state.arena_augments_pending],
                'selected': [[a['id'] if isinstance(a, dict) else a
                              for a in seat.arena_augments_selected] for seat in state.seats],
                'loot': copy.deepcopy(state.arena_loot),
                'loot_start': state.arena_loot_start,
                'component_choices': copy.deepcopy(state.arena_component_choices),
                'component_choice_start': state.arena_component_choice_start,
            }
        if is_arena and state.scouting_history is not None:
            scout = copy.deepcopy(state.scouting_history)
            scout['seats'] = [[self._pack_report(row, compact_statistics=True) for row in rows]
                              for rows in scout['seats']]
            payload['scouting_history'] = scout
        # Normalize tuple-based metric curves and integer-keyed survivor maps;
        # the shared runtime deliberately accepts strict, portable JSON only.
        return json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))

    def decode(self, payload, schema_version):
        if type(schema_version) is not int or schema_version not in (1, 2, 3, 4, 5):
            raise ValueError("不支持的 PokeTactics 存档版本")
        if schema_version >= 2 and "expedition_state" not in payload:
            raise ValueError("远征存档缺少永久对局编号")
        try:
            return self._decode(payload, schema_version)
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise ValueError("存档结构不完整或字段类型错误") from exc

    def _decode(self, data, schema_version):
        import demo
        import techniques
        import tactics
        from bots import PERSONALITIES
        try:
            ruleset = tactics.validate_ruleset(data['ruleset']) if schema_version >= 4 else tactics.BASE_RULESET
        except ValueError as exc:
            raise UnknownRulesError('无法识别此存档的规则版本；需要对应版本继续，原存档未修改') from exc
        if schema_version < 4 and data.get('ruleset', tactics.BASE_RULESET) != tactics.BASE_RULESET:
            raise UnknownRulesError('旧存档版本不能包含新战术规则')
        fingerprint = data.get('rules')
        current_fingerprint = rules_fingerprint()
        supported = {current_fingerprint, TWO_ROW_ARENA_FINGERPRINT,
                     PRE_NATIVE_SKILLS_FINGERPRINT, NATIVE_SKILLS_INITIAL_FINGERPRINT,
                     PRE_COMBINATIONS_FINGERPRINT, PRE_EXPANSION_FINGERPRINT,
                     PRE_GEN2_FINGERPRINT, PRE_STATISTICS_FINGERPRINT,
                     PRE_SKILL_IDENTITIES_FINGERPRINT, PRE_COMBO_BRANCHES_FINGERPRINT,
                     PRE_ATTACK_BRANCHES_FINGERPRINT, PRE_ARENA_BONDS_FINGERPRINT,
                     PRE_TRAITS_GEAR_FINGERPRINT, PRE_ARENA_SYNERGY_FINGERPRINT}
        if ruleset == tactics.BASE_RULESET:
            supported.add(LEGACY_BASE_FINGERPRINT)
        if ruleset in (tactics.BASE_RULESET, tactics.TACTICS_RULESET):
            supported.add(LEGACY_TACTICS_FINGERPRINT)
        if ruleset in (tactics.BASE_RULESET, tactics.TACTICS_RULESET, tactics.ABILITIES_RULESET):
            supported.add(LEGACY_ABILITIES_FINGERPRINT)
        choices = tactics.evolution_choices_enabled(ruleset)
        is_arena = ruleset == 'arena_v1'
        pre_synergy_arena = is_arena and fingerprint == PRE_ARENA_SYNERGY_FINGERPRINT
        migrating_arena = is_arena and fingerprint == TWO_ROW_ARENA_FINGERPRINT
        migrating_expansion = (is_arena and fingerprint in supported
                               and fingerprint not in (current_fingerprint, PRE_STATISTICS_FINGERPRINT,
                                                       PRE_SKILL_IDENTITIES_FINGERPRINT, PRE_COMBO_BRANCHES_FINGERPRINT,
                                                       PRE_ATTACK_BRANCHES_FINGERPRINT, PRE_ARENA_BONDS_FINGERPRINT,
                                                       PRE_TRAITS_GEAR_FINGERPRINT, PRE_ARENA_SYNERGY_FINGERPRINT))
        if not is_arena:
            supported.add(PRE_ARENA_FINGERPRINT)
        if not choices and not is_arena:
            supported.add(LEGACY_COUNTER_PACING_FINGERPRINT)
        if fingerprint not in supported:
            raise UnknownRulesError('无法识别此存档的规则指纹；需要对应版本继续，原存档未修改')
        state = demo.Session(integer(data["seed"], -(2 ** 63), 2 ** 63 - 1, "seed"), ruleset=ruleset)
        state.round_no = integer(data["round"], 1, demo.MAX_ROUNDS, "round")
        if data["phase"] not in ("prep", "battle", "over"):
            raise ValueError("无效的对局阶段")
        state.phase = data["phase"]
        held = Counter()
        unit_ids = set()

        def trait_choice(record, sid, live=True):
            if not is_arena or not live:
                if 'arena_trait' in record:
                    raise ValueError('非竞技或历史展示记录不能包含竞技特性选择')
                return None
            if fingerprint != current_fingerprint:
                if 'arena_trait' in record:
                    raise ValueError('旧版存档不能伪造竞技特性选择')
                return None
            if 'arena_trait' not in record:
                raise ValueError('当前竞技棋子缺少特性选择记录')
            key = record['arena_trait']
            if key is not None and not isinstance(key, str):
                raise ValueError('竞技特性选择类型无效')
            import arena_traits
            return arena_traits.validate_choice(sid, key)

        def learning(sid, key):
            if pre_synergy_arena and key is not None:
                if key not in PRE_SYNERGY_TECHNIQUES:
                    raise ValueError('旧版竞技教学包含新增技能机')
                # This exact predecessor used the type policy, before the
                # mixed attacker's explicit original-move coverage was added.
                if sid == 34 and key in ('thunderbolt', 'ice_beam'):
                    raise ValueError('旧版尼多王不能包含新增相容教学')
            return techniques.validate_learning(sid, key, ruleset=ruleset)

        def piece(record, owned=True, live_choice=True):
            sid = integer(record["species"], 1, 65535, "species")
            if sid not in state.templates:
                raise ValueError("存档包含当前版本不支持的棋子")
            item = record["item"]
            if item is not None and (item not in demo.items_mod.catalog(ruleset)
                                         or pre_synergy_arena and item not in PRE_SYNERGY_ITEMS):
                raise ValueError("未知装备")
            template = state.templates[sid]
            selected_trait = trait_choice(record, sid, live_choice)
            if is_arena:
                star = integer(record.get('star'), 1, 3, 'star')
                template = copy.copy(template)
                template.star = star
                template.shiny = star == 3
                template.arena_trait_key = selected_trait
            elif 'star' in record:
                raise ValueError('旧规则不能包含竞技升星记录')
            if not owned:
                return (template, item) if item else template
            sources = sequence(record["sources"], 128, "sources")
            if not sources or sid not in sources:
                raise ValueError("棋子来源账本缺失")
            for source in sources:
                if type(source) is not int or source not in state.templates:
                    raise ValueError("棋子来源账本无效")
            if is_arena and (len(sources) != 3 ** (star - 1) or any(source != sid for source in sources)):
                raise ValueError('竞技星级与卡池来源不一致')
            investment = integer(record["invested"], 1, sum(state.templates[s].tier for s in sources), "invested")
            result = demo.shop_mod.OwnedPiece(template, investment)
            result.sources, result.item = list(sources), item
            result.arena_trait = selected_trait
            uid = record.get('uid')
            if uid is not None or schema_version >= 3:
                if not isinstance(uid, str) or not re.fullmatch(r'u[0-9]{8}', uid) or uid == 'u00000000' or uid in unit_ids:
                    raise ValueError('棋子编号无效或重复')
                unit_ids.add(uid)
                result.uid = uid
            if schema_version >= 3 and 'technique' not in record:
                raise ValueError('棋子缺少教学记录')
            result.technique = learning(sid, record.get('technique'))
            if choices:
                locked = record.get('evolution_locked')
                if type(locked) is not bool:
                    raise ValueError('棋子缺少有效的暂缓进化记录')
                if locked and (demo.pokedex().next_evolution(sid) is None or sid in demo.shop_mod.TRADE_EVOLUTIONS):
                    raise ValueError('该形态不能暂缓普通进化')
                result.evolution_locked = locked
            elif 'evolution_locked' in record:
                raise ValueError('旧规则不能包含暂缓进化记录')
            held.update(sources)
            return result

        records = sequence(data["seats"], 8, "seats")
        if len(records) != 8 or [s["seat"] for s in records] != list(range(8)):
            raise ValueError("存档必须包含完整且唯一的八个席位")
        ranks = []
        for record, seat in zip(records, state.seats):
            for key in COMMON:
                value = record[key]
                if key in ("alive", "stone_used"):
                    if type(value) is not bool:
                        raise ValueError(f"{key} 必须为布尔值")
                elif key == "rank":
                    if value is not None:
                        integer(value, 1, 8, key)
                        ranks.append(value)
                else:
                    low, high = {"hp": (-1000, 100), "level": (1, 7), "streak": (-31, 31)}.get(key, (0, 1000000))
                    integer(value, low, high, key)
                setattr(seat, key, value)
            if seat.alive != (seat.hp > 0):
                raise ValueError("生命值与淘汰状态矛盾")
            if not seat.alive and seat.rank is None:
                raise ValueError("被淘汰的席位缺少名次")
            xp_limit = demo.economy.xp_to_next(seat.level)
            if xp_limit and seat.xp >= xp_limit:
                raise ValueError("等级与经验不一致")
            seat.bench = [piece(o) for o in sequence(record["bench"], 8 if is_arena else demo.BENCH_CAP, "bench")]
            if seat.seat == 0:
                seat.grid = {}
                for row, col, owned in sequence(record["grid"], seat.pop(), "grid"):
                    row = integer(row, 0, 1 if migrating_arena else state.grid_rows - 1, 'row')
                    if migrating_arena and row == 1:
                        row = 2
                    pos = (row, integer(col, 0, 5, "col"))
                    if pos in seat.grid:
                        raise ValueError("重复的棋盘格位")
                    seat.grid[pos] = piece(owned)
                normalized_board = []
                for saved in record['board']:
                    selected_trait = trait_choice(saved, saved['species'])
                    normalized = {**saved, 'uid': saved.get('uid'), 'technique': saved.get('technique')}
                    if is_arena:
                        normalized['arena_trait'] = selected_trait
                    normalized_board.append(normalized)
                if [owned_record(o, choices, is_arena) for o in seat.board] != normalized_board:
                    raise ValueError("棋盘格位与棋子顺序不一致")
                seat.refresh_j = integer(record["refresh_j"], 0, 1000000, "refresh_j")
                if type(record["shop_locked"]) is not bool:
                    raise ValueError("无效锁店状态")
                seat.shop_locked = record["shop_locked"]
            else:
                seat.board = [piece(o) for o in sequence(record["board"], seat.pop(), "board")]
                seat.ability = integer(record["ability"], 0, 3, "ability")
                if record["personality"] not in PERSONALITIES:
                    raise ValueError("无效机器人策略")
                seat.pers_key = record["personality"]
                seat.pers = PERSONALITIES[seat.pers_key]
                seat.name = f"{seat.seat}·{seat.pers['label'][:3]}L{seat.ability}"
                target_types = sequence(record["target_types"], 2, "target_types")
                if any(t not in demo.TYPE_ZH for t in target_types):
                    raise ValueError("未知目标属性")
                seat.target_types = tuple(target_types)
                stats = record["stats"]
                for key, upper in (("gold_curve", 1000000), ("pop_curve", 9)):
                    for value in sequence(stats[key], demo.MAX_ROUNDS, key):
                        integer(value, 0, upper, key)
                for name, count in sequence(stats["synergy_curve"], demo.MAX_ROUNDS, "synergy_curve"):
                    if name not in demo.TYPE_ZH and name != "-":
                        raise ValueError("统计包含未知属性")
                    integer(count, 0, 9, "synergy_count")
                for key in ("refreshes", "item_crafts", "item_equips", "stone_triggers"):
                    integer(stats[key], 0, 1000000, key)
                if stats["synergy_formed_round"] is not None:
                    integer(stats["synergy_formed_round"], 1, state.round_no, "synergy_formed_round")
                if stats["synergy_formed_type"] is not None and stats["synergy_formed_type"] not in demo.TYPE_ZH:
                    raise ValueError("统计包含未知成型属性")
                craft = stats["craft_stats"]
                if set(craft) != {"calls", "made", "no_pair", "gated", "shadow"}:
                    raise ValueError("合成统计字段不完整")
                integer(craft["calls"], 0, 1000000, "craft_calls")
                for key in ("made", "no_pair", "gated", "shadow"):
                    if not isinstance(craft[key], dict) or set(craft[key]) - set(demo.items_mod.catalog(ruleset)):
                        raise ValueError("合成统计含未知装备")
                    for value in craft[key].values():
                        integer(value, 0, 1000000, "craft_count")
                for key in BOT_STATS:
                    setattr(seat, key, copy.deepcopy(stats[key]))
            shop_slots = 5 if is_arena else demo.SHOP_SLOTS_UI
            slots = sequence(record["shop"], shop_slots, "shop")
            if len(slots) != shop_slots:
                raise ValueError("商店格数不一致")
            for sid in slots:
                if sid is not None:
                    if type(sid) is not int or sid not in state.templates:
                        raise ValueError("商店未知棋子")
                    held[sid] += 1
            seat.shop.slots = list(slots)
            if not seat.alive and (seat.board or seat.bench or any(s is not None for s in slots)):
                raise ValueError("已淘汰席位仍占用卡池")
            components = record["components"]
            if set(components) != set(demo.items_mod.COMPONENT_ORDER):
                raise ValueError("组件字段不一致")
            seat.inventory.components = {k: integer(v, 0, 1000, k) for k, v in components.items()}
            finished = sequence(record["finished"], 1000, "finished")
            if any(key not in demo.items_mod.catalog(ruleset)
                   or pre_synergy_arena and key not in PRE_SYNERGY_ITEMS for key in finished):
                raise ValueError("仓库含未知装备")
            seat.inventory.finished = list(finished)
            machines = record.get('techniques', dict.fromkeys(techniques.ids_for(ruleset), 0))
            if pre_synergy_arena and (not isinstance(machines, dict) or set(machines) != PRE_SYNERGY_TECHNIQUES):
                raise ValueError('旧版竞技技能机仓库字段无效')
            if migrating_arena and isinstance(machines, dict) and set(machines) == {'cut', 'surf', 'rest'}:
                machines = {**dict.fromkeys(techniques.ids_for(ruleset), 0), **machines}
            if (migrating_expansion and isinstance(machines, dict)
                    and set(machines) == {'cut', 'surf', 'rest', 'thunderbolt', 'ice_beam', 'toxic', 'earthquake'}):
                machines = {**dict.fromkeys(techniques.ids_for(ruleset), 0), **machines}
            if (is_arena and fingerprint != current_fingerprint and isinstance(machines, dict)
                    and set(machines) == PRE_SYNERGY_TECHNIQUES):
                machines = {**dict.fromkeys(techniques.ids_for(ruleset), 0), **machines}
            if schema_version >= 3 and 'techniques' not in record:
                raise ValueError('缺少技能机仓库')
            if not isinstance(machines, dict) or set(machines) != set(techniques.ids_for(ruleset)):
                raise ValueError('技能机仓库字段无效')
            seat.inventory.techniques = {k: integer(v, 0, 1000, 'techniques') for k, v in machines.items()}
        if len(ranks) != len(set(ranks)) or (state.phase == "over" and len(ranks) != 8):
            raise ValueError("名次重复或终局名次不完整")
        saved_pool = data['pool']
        if migrating_expansion:
            predecessor = set(demo.arena_mod.ORIGINAL_ROSTER)
            if fingerprint == PRE_GEN2_FINGERPRINT:
                predecessor.update(demo.arena_mod.EXPANSION_ROSTER)
            missing = set(state.templates) - predecessor
            if set(saved_pool) == {str(s) for s in predecessor} and not any(held[s] for s in missing):
                saved_pool = {**saved_pool, **{str(s): demo.arena_mod.pool_cap(s) for s in missing}}
        if set(saved_pool) != {str(s) for s in state.templates}:
            raise ValueError("卡池种类与当前版本不一致")
        for sid, template in state.templates.items():
            cap = demo.arena_mod.pool_cap(sid) if is_arena else demo.shop_mod.POOL_COPIES[template.tier]
            count = integer(saved_pool[str(sid)], 0, cap, "pool")
            if count + held[sid] != cap:
                raise ValueError("卡池守恒校验失败")
            state.pool.remaining[sid] = count

        def seat_ref(value):
            return None if value is None else state.seats[integer(value, 0, 7, "seat reference")]

        for record, seat in zip(records, state.seats):
            seat._last_opp = seat_ref(record["last_opponent"])
            if seat._last_opp is seat:
                raise ValueError("上轮对手不能是自己")
        pair_data = data["pairs"]
        state.pairs = ([(seat_ref(a), seat_ref(b)) for a, b in sequence(pair_data, 4, "pairs")]
                       if pair_data is not None else None)
        participants = [s.seat for pair in state.pairs or [] for s in pair]
        if len(set(participants)) != len(participants):
            raise ValueError("重复配对")
        state.ghost_seat, state.ghost_src = seat_ref(data["ghost_seat"]), seat_ref(data["ghost_source"])
        if bool(state.ghost_seat) != bool(state.ghost_src) or state.ghost_seat is not None and (
                state.ghost_seat is state.ghost_src or state.ghost_seat.seat in participants):
            raise ValueError("幽灵配对不一致")
        if state.phase == "prep" and state.round_no % 5:
            paired = set(participants + ([state.ghost_seat.seat] if state.ghost_seat else []))
            if paired != {seat.seat for seat in state._alive()}:
                raise ValueError("准备阶段配对缺少存活席位")
        state.opponent_comp = ([piece(o, owned=False) for o in sequence(data["opponent_comp"], 12, "opponent_comp")]
                               if data["opponent_comp"] is not None else None)
        opponent_learned = data.get('opponent_learned')
        if schema_version >= 3 and 'opponent_learned' not in data:
            raise ValueError('缺少对手教学快照')
        if opponent_learned is not None:
            sequence(opponent_learned, 12, 'opponent_learned')
            if state.opponent_comp is None or len(opponent_learned) != len(state.opponent_comp):
                raise ValueError('对手教学快照长度无效')
            state.opponent_learned = [learning(
                (p[0] if isinstance(p, tuple) else p).species_id, t)
                for p, t in zip(state.opponent_comp, opponent_learned)]
        if state.round_no % 5 == 0:
            state.opp_view = state._pve_view(state.round_no)
        else:
            src = state.ghost_src if state.ghost_seat is state.player else next(
                (b if a is state.player else a for a, b in state.pairs or [] if state.player in (a, b)), None)
            if src is not None and state.opponent_comp is not None:
                comp = state.opponent_comp
                views = [demo._piece_view(o[0], o[1], ruleset) if isinstance(o, tuple)
                         else demo._piece_view(o, ruleset=ruleset) for o in comp]
                if is_arena:
                    for view, learned in zip(views, state.opponent_learned or [None] * len(views)):
                        view['technique'] = techniques.view(learned, ruleset=ruleset)
                state.opp_view = {"name": (f"幽灵（{src.name} 镜像）" if state.ghost_seat is state.player else src.name),
                                  "hp": src.hp, "level": src.level, "rows": state._enemy_rows(views),
                                  "bench": [demo._piece_view(o.piece, o.item, ruleset) for o in src.bench]}
        log = sequence(data["log"], 240, "log")
        if any(not isinstance(line, str) or len(line) > 1000 for line in log):
            raise ValueError("战报文本无效")
        state.log = list(log)
        for key in ("player_battles", "player_frames_total"):
            setattr(state, key, integer(data[key], 0, 1000000, key))
        state.eliminated_round = (integer(data["eliminated_round"], 1, state.round_no, "eliminated_round")
                                  if data["eliminated_round"] is not None else None)
        state.final_team = ([demo._piece_view(p[0], p[1], ruleset) if isinstance(p, tuple) else demo._piece_view(p, ruleset=ruleset)
                             for p in [piece(o, owned=False, live_choice=False) for o in sequence(data["final_team"], 9, "final_team")]]
                            if data["final_team"] is not None else None)
        for record, view in zip(data['final_team'] or [], state.final_team or []):
            view['technique'] = techniques.view(learning(
                record['species'], record.get('technique')), ruleset=ruleset)
        summary = copy.deepcopy(data["last_battle"])
        if summary is not None:
            if not isinstance(summary, dict) or set(summary) - {
                    "winner", "survivors", "duration", "round", "pve", "ghost", "opp_name", "statistics", *REPORT_EFFECT_KEYS}:
                raise ValueError("战斗结算摘要字段无效")
            winner = summary["winner"]
            if winner is not None:
                integer(winner, 0, 1, "winner")
            if "survivors" in summary:
                survivors = summary["survivors"]
                if not isinstance(survivors, dict) or set(survivors) != {"0", "1"}:
                    raise ValueError("战斗存活数量无效")
                for value in survivors.values():
                    integer(value, 0, 12, "survivors")
            if "duration" in summary:
                duration = summary["duration"]
                if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= 10000:
                    raise ValueError("战斗时长无效")
            if "round" in summary:
                integer(summary["round"], 1, state.round_no, "battle round")
            for key in ("pve", "ghost"):
                if key in summary and type(summary[key]) is not bool:
                    raise ValueError("战斗类别无效")
            if 'opp_name' in summary:
                self._validate_opponent_name(summary['opp_name'])
            if 'statistics' in summary:
                self._validate_battle_statistics(summary['statistics'], state)
            self._decode_report_effects(summary, state, allow_new=fingerprint == current_fingerprint)
            state.last_battle = {**copy.deepcopy(summary), "n": 0, "winner": winner, "round": summary.get('round', state.round_no), "restored": True,
                                 "headline": "已恢复战后结算，结果不会重复发放",
                                 "opp_name": summary.get('opp_name', (state.opp_view or {}).get("name", "对手")), "events": []}
        if 'battle_history' in data:
            self._decode_battle_history(state, data['battle_history'], allow_new=fingerprint == current_fingerprint)
        elif fingerprint in (current_fingerprint, PRE_SKILL_IDENTITIES_FINGERPRINT,
                             PRE_COMBO_BRANCHES_FINGERPRINT, PRE_ATTACK_BRANCHES_FINGERPRINT,
                             PRE_ARENA_BONDS_FINGERPRINT, PRE_TRAITS_GEAR_FINGERPRINT,
                             PRE_ARENA_SYNERGY_FINGERPRINT):
            raise ValueError('当前存档缺少本局战报记录')
        elif summary:
            # Old builds only kept the latest result, without unit counters.
            # Never reconstruct damage from requested event values or replay.
            state.battle_history = [{
                'round': state.last_battle['round'], 'winner': summary['winner'],
                'duration': summary.get('duration', 0), 'pve': summary.get('pve', False),
                'ghost': summary.get('ghost', False), 'opp_name': state.last_battle['opp_name'],
                'statistics': None,
            }]
        state.scouting_history = None
        if 'scouting_history' in data:
            if not is_arena or fingerprint != current_fingerprint or schema_version != 5:
                raise ValueError('旧版或非竞技存档不能包含侦察战报扩展')
            self._decode_scouting_history(state, data['scouting_history'])
        elif any(row.get('effect_version') == 1 for row in state.battle_history):
            raise ValueError('新战报存档缺少侦察记录扩展')
        state.save_warning = ('已识别旧版存档，继续使用 base_v1 规则'
                              if fingerprint == LEGACY_BASE_FINGERPRINT else None)
        from expedition import decode_extension
        decode_extension(state, data)
        # Schema 1/2 attached teaching to the partner loadout. Migrate it once to
        # a concrete unit (or inventory when that family is no longer owned).
        if state.expedition and state.expedition['technique']:
            if schema_version >= 3:
                raise ValueError('教学必须绑定棋子或存放仓库')
            import partners
            family = next(p['family_ids'] for p in partners.catalog()
                          if p['id'] == state.expedition['partner'])
            machine = state.expedition['technique']
            target = next((o for o in state.player.all_pieces()
                           if o.piece.species_id in family and o.technique is None), None)
            if target is not None:
                target.technique = techniques.validate_learning(target.piece.species_id, machine)
            else:
                state.player.inventory.techniques[machine] += 1
            state.expedition['technique'] = None
        minimum = max((int(uid[1:]) for uid in unit_ids), default=0) + 1
        if schema_version >= 3 and 'next_unit_id' not in data:
            raise ValueError('缺少棋子编号计数器')
        state.next_unit_id = integer(data.get('next_unit_id', minimum), minimum, 99999999, 'next_unit_id')
        state.ensure_unit_ids()
        if is_arena:
            self._decode_arena(state, data, migrating_arena,
                               fingerprint not in (current_fingerprint, PRE_TRAITS_GEAR_FINGERPRINT,
                                                   PRE_ARENA_SYNERGY_FINGERPRINT), pre_synergy_arena)
        elif 'arena' in data:
            raise ValueError('旧规则不能包含竞技强化记录')
        if schema_version >= 4:
            self._decode_tactics(state, data)
        if is_arena and fingerprint == PRE_NATIVE_SKILLS_FINGERPRINT:
            state.save_warning = '已加入18种专属原生技能；学习技能、装备和回合奖励进度已保留。'
        if is_arena and fingerprint == PRE_COMBINATIONS_FINGERPRINT:
            state.save_warning = '已加入联动玩法；原阵容、装备、学习技能与已选海克斯保留，新选择从后续回合进入。'
        if is_arena and fingerprint == PRE_SKILL_IDENTITIES_FINGERPRINT:
            state.save_warning = '已更新原生技能定位；阵容、装备、学习技能、海克斯与奖励账本已保留，历史战斗结果不会重算。'
        if is_arena and fingerprint == PRE_COMBO_BRANCHES_FINGERPRINT:
            state.save_warning = '已更新护盾、净化与击退联动；阵容、装备、学习技能、海克斯与奖励账本已保留，历史战斗结果不会重算。'
        if is_arena and fingerprint == PRE_ATTACK_BRANCHES_FINGERPRINT:
            state.save_warning = '已更新攻击构筑联动；阵容、装备、学习技能、海克斯与奖励账本已保留，历史战斗结果不会重算。'
        if is_arena and fingerprint == PRE_ARENA_BONDS_FINGERPRINT:
            state.save_warning = ('已更新竞技羁绊与阶段组件补给；阵容、装备、学习技能、海克斯与奖励账本已保留，'
                                  '历史战斗结果不会重算，组件补给只从后续结算轮次开始。')
        if is_arena and fingerprint == PRE_TRAITS_GEAR_FINGERPRINT:
            state.save_warning = ('已加入固定物种特性与装备联动；阵容、装备、学习技能、海克斯和补给账本已保留，'
                                  '历史战斗结果不会重算，新效果只在后续战斗生效。')
        if is_arena and fingerprint == PRE_ARENA_SYNERGY_FINGERPRINT:
            state.save_warning = ('已加入可选特性与竞技天气联动；原精灵保持默认特性，阵容、装备、教学和补给账本已保留，'
                                  '历史战斗结果不会重算，新效果只在后续战斗生效。')
        if migrating_expansion:
            previous = getattr(state, 'save_warning', '')
            state.save_warning = (previous + ' ' if previous else '') + '竞技池已扩为48种，新增第二世代精灵；原阵容、商店、资源与海克斯选择保留，新精灵从后续刷新进入。'
        return state

    @staticmethod
    def _validate_opponent_name(name):
        if not isinstance(name, str) or not name or len(name) > 120:
            raise ValueError('战报对手名称无效')

    @staticmethod
    def _validate_battle_statistics(statistics, state):
        import items
        from data import pokedex
        if statistics is None:
            return  # Explicitly unrecorded legacy/test-render report.
        fields = set(BATTLE_STAT_FIELDS)
        if (not isinstance(statistics, dict) or set(statistics) != {'version', 'units', 'totals'}
                or type(statistics['version']) is not int or statistics['version'] != 1):
            raise ValueError('战斗统计版本或字段无效')
        rows = sequence(statistics['units'], 24, 'battle units')
        identities = {'idx', 'team', 'sid', 'name', 'star', 'role', 'item'}
        for expected_idx, row in enumerate(rows):
            if not isinstance(row, dict) or set(row) != fields | identities:
                raise ValueError('单位战斗统计字段无效')
            if integer(row['idx'], 0, 23, 'battle idx') != expected_idx:
                raise ValueError('单位战斗统计编号重复或顺序无效')
            integer(row['team'], 0, 1, 'battle team')
            sid = integer(row['sid'], 1, 65535, 'battle species')
            # Classic PVE deploys unevolved wild species outside the shop pool.
            supported_species = state.templates if state.is_arena else pokedex().species
            if sid not in supported_species or row['name'] != pokedex().species_record(sid)['name_zh']:
                raise ValueError('单位战斗统计精灵无效')
            integer(row['star'], 1, 3 if state.is_arena else 1, 'battle star')
            expected_role = state.templates[sid].role_key if state.is_arena else None
            if row['role'] != expected_role:
                raise ValueError('单位战斗统计定位无效')
            if row['item'] is not None and row['item'] not in items.catalog(state.ruleset):
                raise ValueError('单位战斗统计装备无效')
            for field in BATTLE_STAT_FIELDS:
                integer(row[field], 0, 2 ** 31 - 1, 'battle ' + field)
            if row['self_healing'] > row['healing_done']:
                raise ValueError('自我治疗不能超过有效治疗总量')
        if any(sum(row['team'] == team for row in rows) > 12 for team in (0, 1)):
            raise ValueError('单位战斗统计超过阵容人数')
        totals = sequence(statistics['totals'], 2, 'battle totals')
        if len(totals) != 2:
            raise ValueError('战斗统计需要完整双方汇总')
        for team, total in enumerate(totals):
            if not isinstance(total, dict) or set(total) != fields | {'team'}:
                raise ValueError('战斗统计汇总字段无效')
            if integer(total['team'], 0, 1, 'battle total team') != team:
                raise ValueError('战斗统计汇总阵营重复或顺序无效')
            for field in BATTLE_STAT_FIELDS:
                value = integer(total[field], 0, 2 ** 31 - 1, 'battle total ' + field)
                if value != sum(row[field] for row in rows if row['team'] == team):
                    raise ValueError('战斗统计汇总与单位数值不一致')

    def _decode_battle_history(self, state, raw, allow_new=True):
        rows = copy.deepcopy(sequence(raw, 31, 'battle history'))
        previous = 0
        for row in rows:
            required = {'round', 'winner', 'duration', 'pve', 'ghost', 'opp_name', 'statistics'}
            if not isinstance(row, dict) or set(row) not in (required, required | set(REPORT_EFFECT_KEYS)):
                raise ValueError('本局战报字段无效')
            round_no = integer(row['round'], 1, state.round_no, 'history round')
            if round_no <= previous or (state.phase == 'prep' and round_no == state.round_no):
                raise ValueError('本局战报轮次重复、未结算或顺序无效')
            previous = round_no
            if row['winner'] is not None:
                integer(row['winner'], 0, 1, 'history winner')
            duration = row['duration']
            if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= 10000:
                raise ValueError('本局战报时长无效')
            if any(type(row[key]) is not bool for key in ('pve', 'ghost')) or row['pve'] and row['ghost']:
                raise ValueError('本局战报类别无效')
            self._validate_opponent_name(row['opp_name'])
            self._validate_battle_statistics(row['statistics'], state)
            self._decode_report_effects(row, state, allow_new=allow_new)
        if state.last_battle:
            if not rows or rows[-1]['round'] != state.last_battle['round']:
                raise ValueError('本局战报缺少最近已结算回合')
            latest = rows[-1]
            defaults = {'duration': 0, 'pve': False, 'ghost': False, 'statistics': None}
            compared = ('winner', 'duration', 'pve', 'ghost', 'opp_name', 'statistics')
            if latest.get('effect_version') == 1 or state.last_battle.get('effect_version') == 1:
                compared += REPORT_EFFECT_KEYS
            if any(latest.get(key) != state.last_battle.get(key, defaults.get(key)) for key in compared):
                raise ValueError('最近战报与战斗结算不一致')
        state.battle_history = copy.deepcopy(rows)

    @staticmethod
    def _pack_report(report, compact_statistics=False):
        """Portable optional presentation extension; legacy fields stay verbatim."""
        packed = copy.deepcopy(report)
        if packed.get('effect_version') == 1:
            for key in ('combinations', 'enemy_combinations'):
                rows = [[row['id'], *[row[counter] for counter in COMBINATION_COUNTERS]]
                        for row in packed[key]['by_key']]
                compact = json.dumps(rows, separators=(',', ':'), allow_nan=False).encode('utf-8')
                packed[key] = {'version': 1, 'encoding': 'zlib-json-v1',
                               'data': base64.b64encode(zlib.compress(compact)).decode('ascii')}
        if compact_statistics and packed['statistics'] is not None:
            packed['statistics'] = {'version': 1, 'units': [
                [row['team'], row['sid'], row['star'], row['item'],
                 *[row[field] for field in BATTLE_STAT_FIELDS]]
                for row in packed['statistics']['units']]}
        return packed

    def _decode_report_effects(self, report, state, allow_new=True):
        extended = 'effect_version' in report
        if extended:
            if not allow_new or not state.is_arena:
                raise ValueError('旧版或非竞技战报不能包含双方联动扩展')
            if type(report['effect_version']) is not int or report['effect_version'] != 1:
                raise ValueError('双方联动扩展版本无效')
            if not set(REPORT_EFFECT_KEYS) <= set(report):
                raise ValueError('双方联动扩展缺少字段')
        elif 'enemy_combinations' in report or 'enemy_fields' in report:
            raise ValueError('敌方联动缺少版本记录')
        for key in ('combinations', 'enemy_combinations'):
            if key not in report:
                continue
            if not state.is_arena:
                raise ValueError('非竞技存档不能包含联动统计')
            value = report[key]
            if isinstance(value, dict) and 'version' in value:
                if (not extended or set(value) != {'version', 'encoding', 'data'}
                        or type(value['version']) is not int or value['version'] != 1
                        or value['encoding'] != 'zlib-json-v1' or not isinstance(value['data'], str)
                        or len(value['data']) > 128 * 1024):
                    raise ValueError('紧凑联动版本或字段无效')
                try:
                    compressed = base64.b64decode(value['data'], validate=True)
                    decoder = zlib.decompressobj()
                    decoded = decoder.decompress(compressed, 64 * 1024 + 1)
                    if len(decoded) > 64 * 1024 or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
                        raise ValueError('紧凑联动数据超过上限或流不完整')
                    decoded_rows = json.loads(decoded)
                except (binascii.Error, zlib.error, UnicodeError, json.JSONDecodeError) as exc:
                    raise ValueError('紧凑联动压缩数据无效') from exc
                from combination_view import NAMES, battle_summary
                summary = battle_summary([], {})
                rows = sequence(decoded_rows, len(NAMES), 'compact combinations')
                for row in rows:
                    if not isinstance(row, list) or len(row) != len(COMBINATION_COUNTERS) + 1:
                        raise ValueError('紧凑联动行长度无效')
                    combo = row[0]
                    if not isinstance(combo, str) or combo not in NAMES:
                        raise ValueError('紧凑联动类别无效')
                    summary['by_key'].append({'id': combo, 'name': NAMES[combo],
                                              **dict(zip(COMBINATION_COUNTERS, row[1:]))})
                total_fields = {'triggers': 'triggers', 'total_energy': 'energy', 'total_shield': 'shield',
                                'absorbed': 'absorbed', 'total_charges': 'charges', 'total_damage': 'damage',
                                'damage_absorbed': 'damage_absorbed', 'total_vulnerable': 'vulnerable',
                                'total_spreads': 'spreads', 'total_tempo_stacks': 'tempo_stacks',
                                'total_offense_buffs': 'offense_buffs', 'total_healing': 'healing',
                                'total_cleanses': 'cleanses', 'total_statuses': 'statuses',
                                'total_mitigated': 'mitigated', 'total_accuracy_saves': 'accuracy_saves',
                                'total_weakens': 'weakens'}
                for row in summary['by_key']:
                    for counter in COMBINATION_COUNTERS:
                        integer(row[counter], 0, 2 ** 31 - 1, 'compact combination counter')
                summary.update({key: sum(row[field] for row in summary['by_key'])
                                for key, field in total_fields.items()})
                report[key] = summary
            self._validate_combination_summary(report[key])
        for key in ('fields', 'enemy_fields'):
            if key not in report:
                continue
            if not state.is_arena or not isinstance(report[key], dict) or set(report[key]) != set(FIELD_COUNTERS):
                raise ValueError('地形统计字段无效')
            for value in report[key].values():
                integer(value, 0, 1000000, 'field summary')

    def _decode_scouting_history(self, state, raw):
        if not isinstance(raw, dict) or set(raw) != {'version', 'from_round', 'seats'}:
            raise ValueError('侦察记录扩展字段无效')
        if type(raw['version']) is not int or raw['version'] != 1:
            raise ValueError('侦察记录扩展版本无效')
        first = integer(raw['from_round'], 1, state.round_no, 'scouting first round')
        ledgers = copy.deepcopy(sequence(raw['seats'], 8, 'scouting seats'))
        if len(ledgers) != 8:
            raise ValueError('侦察记录需要完整8席位')
        required = {'round', 'winner', 'duration', 'pve', 'ghost', 'opp_name', 'opp_seat', 'source', 'statistics'}
        for seat, rows in enumerate(ledgers):
            sequence(rows, 3, 'scouting recent reports')
            previous = 0
            for row in rows:
                if not isinstance(row, dict) or set(row) != required | set(REPORT_EFFECT_KEYS):
                    raise ValueError('侦察战报字段无效')
                round_no = integer(row['round'], first, state.round_no, 'scouting round')
                if round_no <= previous or state.phase == 'prep' and round_no == state.round_no:
                    raise ValueError('侦察战报重复、未结算或顺序无效')
                previous = round_no
                if row['winner'] is not None:
                    integer(row['winner'], 0, 1, 'scouting winner')
                duration = row['duration']
                if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= 10000:
                    raise ValueError('侦察战报时长无效')
                if any(type(row[key]) is not bool for key in ('pve', 'ghost')) or row['pve'] and row['ghost'] or row['pve'] != (round_no % 5 == 0):
                    raise ValueError('侦察战报类别或轮次无效')
                if row['source'] not in ('battle', 'uncontested'):
                    raise ValueError('侦察战报来源无效')
                if row['pve']:
                    if row['opp_seat'] is not None:
                        raise ValueError('野怪战报不能归属训练家席位')
                elif integer(row['opp_seat'], 0, 7, 'scouting opponent') == seat:
                    raise ValueError('侦察对手不能是自己')
                self._validate_opponent_name(row['opp_name'])
                if not row['pve'] and row['opp_name'] != state.seats[row['opp_seat']].name:
                    raise ValueError('侦察对手名称与席位不一致')
                statistics = row['statistics']
                if statistics is None:
                    raise ValueError('新侦察战报必须包含已记录统计')
                if statistics is not None:
                    if not isinstance(statistics, dict) or set(statistics) != {'version', 'units'} or type(statistics['version']) is not int or statistics['version'] != 1:
                        raise ValueError('紧凑侦察统计字段或版本无效')
                    units = sequence(statistics['units'], 24, 'scouting unit counts')
                    converted = []
                    for idx, unit in enumerate(units):
                        if not isinstance(unit, list) or len(unit) != 4 + len(BATTLE_STAT_FIELDS):
                            raise ValueError('紧凑侦察统计行长度无效')
                        team = integer(unit[0], 0, 1, 'scouting unit team')
                        sid = integer(unit[1], 1, 65535, 'scouting unit species')
                        if sid not in state.templates:
                            raise ValueError('紧凑侦察精灵无效')
                        template = state.templates[sid]
                        converted.append({'idx': idx, 'team': team, 'sid': sid, 'name': template.name,
                                          'star': unit[2], 'item': unit[3], 'role': template.role_key,
                                          **dict(zip(BATTLE_STAT_FIELDS, unit[4:]))})
                    statistics = {'version': 1, 'units': converted, 'totals': [
                        {'team': team, **{field: sum(integer(unit[field], 0, 2 ** 31 - 1, 'scouting counter')
                                                    for unit in converted if unit['team'] == team)
                                          for field in BATTLE_STAT_FIELDS}} for team in (0, 1)]}
                    self._validate_battle_statistics(statistics, state)
                    if row['source'] == 'uncontested' and (duration != 0 or
                            all(any(unit['team'] == team for unit in converted) for team in (0, 1)) or
                            any(unit[field] for unit in converted for field in BATTLE_STAT_FIELDS)):
                        raise ValueError('不战而胜不能包含实战数值或完整双方')
                    row['statistics'] = statistics
                elif row['source'] == 'uncontested' and duration != 0:
                    raise ValueError('未交战报告时长必须为零')
                self._decode_report_effects(row, state)
                if row['source'] == 'uncontested' and any(
                        value for key in ('combinations', 'enemy_combinations', 'fields', 'enemy_fields')
                        for field, value in row[key].items() if field != 'by_key'):
                    raise ValueError('未交战报告不能包含已触发联动')
                if seat == 0:
                    global_row = next((report for report in state.battle_history if report['round'] == round_no), None)
                    if global_row is None or any(row.get(key) != global_row.get(key) for key in
                            ('winner', 'duration', 'pve', 'ghost', 'statistics', *REPORT_EFFECT_KEYS)):
                        raise ValueError('玩家侦察战报与本局记录不一致')
                    if row['opp_name'] != global_row['opp_name']:
                        raise ValueError('玩家侦察战报与本局对手不一致')
        # A PVP result is one combat with two read-only perspectives. Where
        # both retained windows cover that round, their identities/counters and
        # effects must agree; older opposite records may legitimately be pruned.
        def unit_signature(statistics, flip=False):
            return sorted((row['team'] ^ int(flip), row['sid'], row['star'], row['item'] or '',
                           *[row[field] for field in BATTLE_STAT_FIELDS])
                          for row in statistics['units'])

        for seat, rows in enumerate(ledgers):
            for row in rows:
                if row['pve']:
                    continue
                opposite = ledgers[row['opp_seat']]
                counterpart = next((record for record in opposite if record['round'] == row['round']
                                    and not record['pve'] and record['opp_seat'] == seat), None)
                if row['ghost']:
                    if counterpart is not None:
                        raise ValueError('幽灵来源不能同时记录这场真实交战')
                    continue
                if counterpart is None:
                    if not opposite or opposite[-1]['round'] < row['round'] or opposite[0]['round'] <= row['round']:
                        raise ValueError('侦察真实交战缺少对手记录')
                    continue
                expected_winner = None if row['winner'] is None else row['winner'] ^ 1
                if (counterpart['ghost'] or counterpart['winner'] != expected_winner
                        or counterpart['duration'] != row['duration'] or counterpart['source'] != row['source']
                        or unit_signature(counterpart['statistics'], flip=True) != unit_signature(row['statistics'])
                        or any(row[ours] != counterpart[theirs] or row[theirs] != counterpart[ours]
                               for ours, theirs in (('combinations', 'enemy_combinations'), ('fields', 'enemy_fields')))):
                    raise ValueError('侦察双方战报不一致')
        state.scouting_history = {'version': 1, 'from_round': first, 'seats': ledgers}

    @staticmethod
    def _validate_combination_summary(summary):
        from combination_view import NAMES
        totals = {'triggers', 'total_energy', 'total_shield', 'absorbed'}
        extra_totals = {'total_charges', 'total_damage', 'damage_absorbed', 'total_vulnerable'}
        old_shape = totals | {'by_key'}
        new_shape = old_shape | extra_totals
        attack_totals = {'total_spreads', 'total_tempo_stacks', 'total_offense_buffs'}
        attack_shape = new_shape | attack_totals
        trait_fields = {'total_healing': 'healing', 'total_cleanses': 'cleanses',
                        'total_statuses': 'statuses', 'total_mitigated': 'mitigated',
                        'total_accuracy_saves': 'accuracy_saves', 'total_weakens': 'weakens'}
        trait_shape = attack_shape | set(trait_fields)
        if not isinstance(summary, dict) or set(summary) not in (old_shape, new_shape, attack_shape, trait_shape):
            raise ValueError('联动统计字段无效')
        extended = set(summary) != old_shape
        attack_extended = set(summary) in (attack_shape, trait_shape)
        traits_extended = set(summary) == trait_shape
        numeric_totals = (totals | (extra_totals if extended else set())
                          | (attack_totals if attack_extended else set())
                          | (set(trait_fields) if traits_extended else set()))
        for key in numeric_totals:
            integer(summary[key], 0, 2 ** 31 - 1, 'combination ' + key)
        seen = set()
        allowed = {'poison_catalyst', 'watch_echo', 'barrier_feedback', 'breach_momentum',
                   'native_inspiration', 'heart_bell', 'ward_bracer', 'clarity_charm',
                   'contagion_orb', 'metronome', 'bond_erosion', 'bond_combo',
                   'bond_guard', 'bond_inspiration'}
        if traits_extended:
            import arena_traits
            allowed.update({'drain_fang', 'tide_shell', 'dew_charm', 'torrent_orb',
                            'pulse_band', 'relay_coil', 'grounding_cloak', 'storm_chime',
                            'life_orb', 'element_wet', 'element_conduct', 'element_bloom',
                            'arena_weather'})
            allowed.update(spec['id'] for spec in arena_traits.catalog())
        expected = {key: NAMES[key] for key in allowed}
        rows = sequence(summary['by_key'], len(expected), 'combination entries')
        row_fields = {'id', 'name', 'triggers', 'energy', 'shield', 'absorbed'}
        if extended:
            row_fields |= {'charges', 'damage', 'damage_absorbed', 'vulnerable'}
        if attack_extended:
            row_fields |= {'spreads', 'tempo_stacks', 'offense_buffs'}
        if traits_extended:
            row_fields |= set(trait_fields.values())
        numeric_fields = row_fields - {'id', 'name'}
        for row in rows:
            if not isinstance(row, dict) or set(row) != row_fields:
                raise ValueError('联动条目字段无效')
            key = row['id']
            if not isinstance(key, str) or key not in expected or key in seen or row['name'] != expected[key]:
                raise ValueError('联动条目未知或重复')
            seen.add(key)
            for count in numeric_fields:
                integer(row[count], 0, 2 ** 31 - 1, 'combination ' + count)
        fields = {'triggers': 'triggers', 'total_energy': 'energy',
                  'total_shield': 'shield', 'absorbed': 'absorbed'}
        if extended:
            fields.update({'total_charges': 'charges', 'total_damage': 'damage',
                           'damage_absorbed': 'damage_absorbed', 'total_vulnerable': 'vulnerable'})
        if attack_extended:
            fields.update({'total_spreads': 'spreads', 'total_tempo_stacks': 'tempo_stacks',
                           'total_offense_buffs': 'offense_buffs'})
        if traits_extended:
            fields.update(trait_fields)
        if any(summary[key] != sum(row[field] for row in rows) for key, field in fields.items()):
            raise ValueError('联动统计总量不一致')

    def _decode_arena(self, state, data, migrating=False, migrating_components=False,
                      pre_synergy=False):
        import arena
        raw = data.get('arena')
        fields = {'pending', 'selected'} if migrating else {'pending', 'selected', 'loot', 'loot_start'}
        component_fields = {'component_choices', 'component_choice_start'}
        if not isinstance(raw, dict):
            raise ValueError('竞技强化存档结构无效')
        if set(raw) == fields and migrating_components:
            # Only a known predecessor may omit both new fields. Partial fields
            # and a current-rules snapshot are never treated as an old save.
            legacy_components = True
        elif set(raw) == fields | component_fields:
            legacy_components = False
        else:
            raise ValueError('竞技强化存档结构无效')
        milestones = (1, 7, 13)
        available = sum(r <= state.round_no for r in milestones)
        rows = sequence(raw['selected'], 8, 'selected augments')
        if len(rows) != 8:
            raise ValueError('竞技强化需要完整八个席位')
        for seat, selected in zip(state.seats, rows):
            keys = sequence(selected, available, 'selected augment ids')
            if any(not isinstance(key, str) or key not in arena.AUGMENTS for key in keys) or len(keys) != len(set(keys)):
                raise ValueError('竞技强化未知或重复')
            seat.arena_augments_selected = [arena.augment_view(key) for key in keys]
        pending = sequence(raw['pending'], 1, 'pending augments')
        rebuilt = []
        for row in pending:
            if not isinstance(row, dict) or set(row) != {'id', 'round', 'options'}:
                raise ValueError('待选竞技强化字段无效')
            round_no = integer(row['round'], 1, state.round_no, 'augment round')
            if (round_no not in milestones or round_no != state.round_no or row['id'] != f'augment-r{round_no}'
                    or state.phase != 'prep' or not state.player.alive):
                raise ValueError('待选竞技强化生命周期无效')
            keys = sequence(row['options'], 3, 'augment options')
            used = {a['id'] for a in state.player.arena_augments_selected}
            if (len(keys) != 3 or any(not isinstance(key, str) or key not in arena.AUGMENTS or key in used for key in keys)
                    or len(keys) != len(set(keys))):
                raise ValueError('竞技强化候选无效')
            rebuilt.append({'id': row['id'], 'round': round_no,
                            'options': [arena.augment_view(key) for key in keys]})
        if state.player.alive and len(state.player.arena_augments_selected) + len(pending) != available:
            raise ValueError('竞技强化领取进度无效')
        for seat in state.bots:
            if seat.alive and len(seat.arena_augments_selected) != available:
                raise ValueError('机器人竞技强化领取进度无效')
        state.arena_augments_pending = rebuilt
        if migrating:
            state.arena_loot_start = state.round_no + (state.phase != 'prep')
            state.save_warning = '已升级为三排战场，原后排保留在第三排；新回合开始发放战利品。'
        else:
            self._decode_arena_loot(state, raw, pre_synergy)
        if legacy_components:
            # Never manufacture a supply for an already settled milestone.
            state.arena_component_choices = []
            state.arena_component_choice_start = state.round_no + (state.phase != 'prep')
        else:
            self._decode_arena_component_choices(state, raw)

    def _decode_arena_component_choices(self, state, raw):
        import items
        from arena_rewards import COMPONENT_CHOICE_ROUNDS
        start = integer(raw['component_choice_start'], state.arena_loot_start,
                        state.round_no + 1, 'component choice start')
        ledger = sequence(raw['component_choices'], 8 * len(COMPONENT_CHOICE_ROUNDS),
                          'component choices')
        settled_round = state.round_no - (state.phase == 'prep')
        eligible = {(row['round'], row['seat']) for row in state.arena_loot
                    if start <= row['round'] <= settled_round
                    and row['round'] in COMPONENT_CHOICE_ROUNDS}
        seen = set()
        previous_round = 0
        fields = {'id', 'round', 'seat', 'options', 'status', 'choice', 'closed_reason'}
        for row in ledger:
            if not isinstance(row, dict) or set(row) != fields:
                raise ValueError('阶段组件补给字段无效')
            round_no = integer(row['round'], start, settled_round, 'component choice round')
            seat_id = integer(row['seat'], 0, 7, 'component choice seat')
            key = (round_no, seat_id)
            if (round_no not in COMPONENT_CHOICE_ROUNDS or key not in eligible or key in seen
                    or round_no < previous_round
                    or row['id'] != f'{state.run_id}:r{round_no}:s{seat_id}:component'):
                raise ValueError('阶段组件补给编号、轮次或参赛记录无效')
            seen.add(key)
            previous_round = round_no
            if not isinstance(row['options'], list) or row['options'] != list(items.COMPONENT_ORDER):
                raise ValueError('阶段组件补给必须包含完整且顺序固定的八种组件')
            status, choice, reason = row['status'], row['choice'], row['closed_reason']
            if status == 'pending':
                if (seat_id != 0 or choice is not None or reason is not None
                        or not state.player.alive or state.phase == 'over'):
                    raise ValueError('待选阶段组件补给生命周期无效')
            elif status == 'claimed':
                if not isinstance(choice, str) or choice not in row['options'] or reason is not None:
                    raise ValueError('阶段组件补给领取记录无效')
            elif status == 'closed':
                if (seat_id != 0 or choice is not None
                        or not (reason == 'eliminated' and not state.player.alive
                                or reason == 'run_finished' and state.phase == 'over')):
                    raise ValueError('阶段组件补给关闭记录无效')
            else:
                raise ValueError('阶段组件补给状态无效')
        if seen != eligible:
            raise ValueError('阶段组件补给缺少已结算参赛席位的记录')
        state.arena_component_choice_start = start
        state.arena_component_choices = copy.deepcopy(ledger)

    def _decode_arena_loot(self, state, raw, pre_synergy=False):
        from arena_rewards import reward_view
        state.arena_loot_start = integer(raw['loot_start'], 1, state.round_no + 1, 'loot start')
        ledger = sequence(raw['loot'], 8 * state.round_no, 'round loot')
        ids = set()
        for row in ledger:
            if not isinstance(row, dict) or set(row) != {'id', 'round', 'seat', 'result', 'grants'}:
                raise ValueError('回合奖励记录字段无效')
            round_no = integer(row['round'], state.arena_loot_start, state.round_no, 'loot round')
            seat_id = integer(row['seat'], 0, 7, 'loot seat')
            if row['id'] != f'{state.run_id}:r{round_no}:s{seat_id}:loot' or row['id'] in ids:
                raise ValueError('回合奖励编号无效或重复')
            if round_no == state.round_no and state.phase == 'prep':
                raise ValueError('准备阶段不能提前发放本轮奖励')
            ids.add(row['id'])
            if row['result'] not in ('win', 'loss', 'draw'):
                raise ValueError('回合奖励胜负无效')
            grants = sequence(row['grants'], 2, 'loot grants')
            if len(grants) != (2 if row['result'] == 'win' else 1):
                raise ValueError('回合奖励数量与胜负不一致')
            for grant in grants:
                if not isinstance(grant, dict) or set(grant) != {'kind', 'key'}:
                    raise ValueError('奖励物品字段无效')
                reward_view(grant)
                if pre_synergy and ((grant['kind'] == 'item' and grant['key'] not in PRE_SYNERGY_ITEMS)
                                    or (grant['kind'] == 'technique'
                                        and grant['key'] not in PRE_SYNERGY_TECHNIQUES)):
                    raise ValueError('旧版竞技奖励包含新增道具或技能机')
        state.arena_loot = copy.deepcopy(ledger)

    def _decode_tactics(self, state, data):
        import demo
        import techniques
        import tactics
        if tactics.enabled(state.ruleset) and state.expedition is None:
            raise ValueError('战术远征缺少主搭档配置')
        configurations = sequence(data['tactical'], 8, 'tactical')
        if len(configurations) != 8:
            raise ValueError('战术配置需要完整八个席位')
        for seat, config in zip(state.seats, configurations):
            try:
                state.validate_tactical(seat, config)
            except demo.DemoError as exc:
                raise ValueError(str(exc)) from exc
        state.tactical = copy.deepcopy(configurations)
        rewards = sequence(data['rewards'], 48, 'rewards')
        if not tactics.enabled(state.ruleset) and rewards:
            raise ValueError('旧规则不能包含战术待领奖励')
        reward_ids = set()
        for row in rewards:
            if not isinstance(row, dict) or set(row) != {
                    'id', 'seat', 'round', 'kind', 'status', 'options', 'choice', 'closed_reason'}:
                raise ValueError('待领奖励字段无效')
            seat_id = integer(row['seat'], 0, 7, 'reward seat')
            round_no = integer(row['round'], 5, state.round_no, 'reward round')
            expected_id = f'{state.run_id}:r{round_no}:s{seat_id}:technique'
            if round_no % 5 or row['id'] != expected_id or row['id'] in reward_ids or row['kind'] != 'technique':
                raise ValueError('待领奖励编号无效或重复')
            reward_ids.add(row['id'])
            options = sequence(row['options'], 3, 'reward options')
            if (len(options) != 3 or any(type(option) is not str for option in options)
                    or len(set(options)) != 3 or set(options) - set(techniques.ids_for(state.ruleset))):
                raise ValueError('奖励候选无效')
            status, choice, reason = row['status'], row['choice'], row['closed_reason']
            if status == 'pending':
                if (choice is not None or reason is not None or not state.seats[seat_id].alive
                        or state.phase == 'over' or round_no < state.round_no - 1
                        or round_no < state.round_no and state.phase != 'prep'):
                    raise ValueError('待领奖励生命周期无效')
            elif status == 'claimed':
                if choice not in options or reason is not None:
                    raise ValueError('奖励领取记录无效')
            elif status == 'closed':
                if not (choice == 'skip' and reason == 'skipped' or choice is None and reason in ('terminal', 'eliminated')):
                    raise ValueError('奖励关闭记录无效')
            else:
                raise ValueError('奖励状态无效')
        state.rewards = copy.deepcopy(rewards)
        config = data['opponent_tactics']
        if config is None:
            if tactics.enabled(state.ruleset) and state.opponent_comp is not None:
                raise ValueError('缺少对手战术快照')
            return
        if not tactics.enabled(state.ruleset) or state.opponent_comp is None:
            raise ValueError('对手战术快照不适用')
        if not isinstance(config, dict) or set(config) != {'guard', 'weather'}:
            raise ValueError('对手战术快照字段无效')
        count = len(state.opponent_comp)
        learned = state.opponent_learned or [None] * count
        for kind, fields in (('guard', {'source', 'target'}), ('weather', {'source'})):
            entry = config[kind]
            if entry is None:
                continue
            if not isinstance(entry, dict) or set(entry) != fields:
                raise ValueError('对手战术快照内容无效')
            for index in entry.values():
                integer(index, 0, count - 1, 'opponent tactic index')
            technique = learned[entry['source']]
            if kind == 'weather' and technique not in ('sunny_day', 'rain_dance'):
                raise ValueError('对手天气手教学不符')
            if kind == 'guard':
                a, b = entry['source'], entry['target']
                if technique != 'guard' or abs(a % 6 - b % 6) + abs(a // 6 - b // 6) != 1:
                    raise ValueError('对手护卫教学或相邻关系无效')
        state.opponent_tactics = copy.deepcopy(config)
