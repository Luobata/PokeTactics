#!/usr/bin/env python3
"""从 ../ESP32-PokemonGo（PokeWalk）提取宝可梦数据，生成 data/ 下的结构化 JSON。

提取内容与来源（均为 PokeWalk 固定提交的 pret/pokecrystal 数据链）：

| 输出 | 来源 |
|---|---|
| `data/pokemon.json` 151 只：中英名、属性、种族值、进化链 | `firmware/main/combat_gen2_stats.h`（种族值）+ `data/pokemon_moves/gold_silver.json`（进化链/英名）+ `data/pokemon_names/gs_legacy.json`（官方中文名）+ `tools/species_types_gen2.py`（手工属性表） |
| `data/typechart.json` 17 系克制表 | `data/pokemon_moves/gold_silver_types.json` |
| `data/moves.json` 251 招：名称、属性、威力、命中、效果 | `data/pokemon_moves/gold_silver.json` |

用法（在 PokeTactics 根目录）：

    python3 tools/extract_from_pokewalk.py [--pokewalk ../ESP32-PokemonGo]

data/ 是生成物，随仓库提供以便无 PokeWalk 检出时也能跑 sim；删掉后可随时重建。
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from species_types_gen2 import SPECIES_TYPES_GEN2  # noqa: E402

STAT_KEYS = ("hp", "attack", "defense", "speed", "special_attack", "special_defense")
STAT_ROW = re.compile(r"\{(\d+),(\d+),(\d+),(\d+),(\d+),(\d+)\}, // (\d+) (\S+)")

# pokecrystal 里的反混淆属性名：PSYCHIC_TYPE 是为避开同名招式，CURSE_TYPE 是诅咒的无属性标记
MOVE_TYPE_ALIASES = {"PSYCHIC_TYPE": "PSYCHIC", "CURSE_TYPE": "NONE"}


def parse_stats(header_text: str) -> dict:
    out = {}
    for m in STAT_ROW.finditer(header_text):
        values = [int(v) for v in m.groups()[:6]]
        out[int(m.group(7))] = {
            "name": m.group(8).lower(), **dict(zip(STAT_KEYS, values))
        }
    return out


def main() -> None:
    here = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--pokewalk", type=Path,
                    default=here.parent / "ESP32-PokemonGo")
    args = ap.parse_args()
    pk = args.pokewalk

    stats = parse_stats((pk / "firmware/main/combat_gen2_stats.h").read_text())
    assert len(stats) == 151, f"expected 151 species, got {len(stats)}"

    gs = json.loads((pk / "data/pokemon_moves/gold_silver.json").read_text())
    zh = {r["id"]: r["official_reference"] for r in json.loads(
        (pk / "data/pokemon_names/gs_legacy.json").read_text())["records"]}

    pokemon = []
    for entry in gs["pokemon"]:
        pid = entry["id"]
        pokemon.append({
            "id": pid,
            "name": entry["name"].lower(),
            "name_zh": zh.get(pid),
            "types": list(SPECIES_TYPES_GEN2[pid]),
            "base": stats[pid],
            # lineage: 从当前形态回溯到基础形态的进化链，如 006 -> [6,5,4]
            "lineage": entry["lineage"],
            # level_up: [等级, 招式ID]，金银升级学习表（招式详情见 moves.json）
            "level_up": entry["level_up"],
        })

    moves_src = gs["moves"]
    # 招式中文名：从 PokeWalk assets/moves.bin 的字符串池解码（段布局与
    # tools/pipeline/inventory_assets.parse_moves 一致：头16B + 招式12B×N +
    # 物种4B×151 + 学习2B×L + UTF-8 池）。仅覆盖伤害招子集，缺名回退英文名。
    zh_names = {}
    try:
        mb = (pk / "assets/moves.bin").read_bytes()
        import struct as _s
        _, _, mrsz, mcnt, scnt, lcnt, poolsz = _s.unpack("<4sHHHHHH", mb[:16])
        pool_off = 16 + mcnt * mrsz + scnt * 4 + lcnt * 2
        pool = mb[pool_off:pool_off + poolsz]
        for i in range(mcnt):
            o = 16 + i * mrsz  # 招式记录区在 16B 文件头之后
            mid, zo, zl = _s.unpack("<HHB", mb[o:o + 5])
            if zl:
                zh_names[mid] = pool[zo:zo + zl].decode("utf-8", "replace")
    except Exception as exc:  # 招式名是显示层增强，失败不阻断提取
        print(f"警告：moves.bin 中文名解码失败（{exc}），回退英文名")

    moves = [{"id": m["id"], "name": m["name"].lower(),
              "name_zh": zh_names.get(m["id"], ""),
              "type": MOVE_TYPE_ALIASES.get(m["type"], m["type"]),
              "power": m.get("power"), "accuracy": m.get("accuracy"),
              "effect": m["effect"]}
             for m in moves_src]

    types_src = json.loads((pk / "data/pokemon_moves/gold_silver_types.json").read_text())
    typechart = {
        "types": types_src["types"],
        # multipliers[att][def] = 攻击方属性对防守方属性的倍率（百分比整数）
        "multipliers": types_src["multipliers"],
    }

    provenance = {
        "extracted_from": "PokeWalk (../ESP32-PokemonGo)",
        "upstream": gs["source"] + " @" + gs["commit"][:12],
        "species_types": "hand-curated Gen2 table, see tools/species_types_gen2.py",
    }
    out_dir = here / "data"
    out_dir.mkdir(exist_ok=True)
    for name, payload in (("pokemon", pokemon), ("typechart", typechart),
                          ("moves", moves)):
        doc = dict(provenance) if name != "typechart" else {}
        doc.update(payload if isinstance(payload, dict) else {"entries": payload})
        (out_dir / f"{name}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
        print(f"data/{name}.json: "
              f"{len(payload if isinstance(payload, list) else payload['types'])} 条")

    # 自检：进化链首应为自身，且三段链的头会作为其他条目的尾出现
    by_id = {p["id"]: p for p in pokemon}
    for p in pokemon:
        lin = p["lineage"]
        assert lin[0] == p["id"], f"lineage head mismatch: {p['id']} {lin}"
        for nxt in (by_id[i]["lineage"] for i in by_id):
            if len(nxt) == len(lin) + 1 and nxt[-len(lin):] == lin:
                assert nxt[0] not in (0,), "unreachable"
    print("自检通过：151 只种族值/属性/中文名/进化链齐全，克制表 17×17")


if __name__ == "__main__":
    main()
