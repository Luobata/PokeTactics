#!/usr/bin/env python3
"""Build the Generation I-III historical species reference.

The output is reference data only. It intentionally does not register any species in
the arena shop or combat runtime. PokeAPI move IDs remain namespaced in
``level_up_pokeapi`` because they are not PokeTactics runtime move IDs.

Data source:
    PokeAPI repository CSV at the pinned commit in ``POKEAPI_COMMIT``.
    Past generations in PokeAPI record the last generation to which an old value
    applied. To reconstruct a Generation III snapshot we choose the earliest past
    snapshot whose generation_id is >= 3; if none exists, current values applied
    before the Fairy-type change and later stat changes.

Sprite source:
    PokeAPI sprites repository at ``SPRITES_COMMIT``. Generation II uses Crystal
    indexed-PNG conversion already used by assets/gen2. Generation III uses Emerald
    RGBA directly without applying the Crystal enclosed-white transform.

Usage:
    python3 tools/build_gen123_reference.py
    python3 tools/build_gen123_reference.py --pokeapi-dir /path/to/pokeapi
    python3 tools/build_gen123_reference.py --download-assets
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import sys
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import tempfile
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
POKEAPI_COMMIT = "5ee47a9a9c1229632ec4b473a9c1c53026e005dd"
SPRITES_COMMIT = "289e842364648ec0495ae4ba12f48d5cbfbf670b"
POKEAPI_REPO = "https://github.com/PokeAPI/pokeapi"
SPRITES_REPO = "https://github.com/PokeAPI/sprites"
POKEEMERALD_REPO = "https://github.com/pret/pokeemerald"
POKEEMERALD_COMMIT = "731ad5bfd6e6f265508d0efcca0ba42f9dcf5881"
POKEEMERALD_SPECIES_INFO_URL = (f"{POKEEMERALD_REPO}/raw/{POKEEMERALD_COMMIT}/src/data/pokemon/species_info.h")
POKEEMERALD_SPECIES_CONSTANTS_URL = (f"{POKEEMERALD_REPO}/raw/{POKEEMERALD_COMMIT}/include/constants/species.h")
TARGET_GENERATION = 3
FIRST_ID = 1
LAST_ID = 386
EMERALD_VERSION_GROUP_ID = 6
LEVEL_UP_METHOD_ID = 1
CHINESE_LANGUAGE_ID = 12
WHITE = (255, 255, 255)

CSV_FILES = (
    "languages.csv",
    "moves.csv",
    "pokemon.csv",
    "pokemon_move_methods.csv",
    "pokemon_moves.csv",
    "pokemon_species.csv",
    "pokemon_species_names.csv",
    "pokemon_stats.csv",
    "pokemon_stats_past.csv",
    "pokemon_types.csv",
    "pokemon_types_past.csv",
    "stats.csv",
    "types.csv",
    "version_groups.csv",
    "versions.csv",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def download_pokeapi(destination: Path) -> None:
    url = f"{POKEAPI_REPO}/archive/{POKEAPI_COMMIT}.tar.gz"
    archive = destination / "pokeapi.tar.gz"
    print(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=30) as response, archive.open("wb") as output:
        shutil.copyfileobj(response, output)
    with tarfile.open(archive, "r:gz") as bundle:
        csv_member = next(member for member in bundle.getmembers()
                          if member.name.endswith("/data/v2/csv"))
        prefix = csv_member.name[: -len("data/v2/csv")]
        wanted = {prefix + "data/v2/csv/" + name for name in CSV_FILES}
        bundle.extractall(destination, members=[m for m in bundle.getmembers() if m.name in wanted])
        extracted_csv = destination / csv_member.name
    shutil.move(str(extracted_csv), destination / "csv")
    archive.unlink()


def read_csvs(csv_root: Path) -> dict[str, list[dict[str, str]]]:
    tables: dict[str, list[dict[str, str]]] = {}
    for name in CSV_FILES:
        path = csv_root / name
        if not path.exists():
            raise FileNotFoundError(f"missing PokeAPI CSV: {path}")
        with path.open(newline="", encoding="utf-8") as handle:
            tables[name] = list(csv.DictReader(handle))
    return tables


def snapshot_past(values: dict[tuple[int, int], int], key: int, current: int) -> int:
    """Pick the oldest PokeAPI past stat snapshot that still applies at generation 3."""
    candidates = [generation for (generation, candidate_key), value in values.items()
                  if candidate_key == key and generation >= TARGET_GENERATION]
    if not candidates:
        return current
    generation = min(candidates)
    return values[(generation, key)]


def snapshot_types(current: dict[int, int], past: dict[tuple[int, int], int]) -> dict[int, int]:
    """Replace a complete type snapshot, not individual current slots.

    A later Fairy addition often changes only one slot in the current table. PokeAPI's
    historical rows contain the complete type set for the old generation, so selecting
    slots independently would leave current Fairy in unchanged slot 2. Here the oldest
    snapshot ending at generation >= 3 replaces the entire current type set.
    """
    generations = sorted({generation for generation, _slot in past if generation >= TARGET_GENERATION})
    if not generations:
        return current
    generation = generations[0]
    return {slot: type_id for (snapshot_generation, slot), type_id in past.items()
            if snapshot_generation == generation}


def crystal_png(data: bytes) -> Image.Image:
    """Convert Crystal RGBA to the existing indexed-P local format."""
    src = Image.open(io.BytesIO(data)).convert("RGBA")
    ref = Image.open(io.BytesIO(data))
    ref_palette = ref.getpalette()
    index = {WHITE: 0}
    palette = list(WHITE)
    out = Image.new("P", src.size)
    source, target = src.load(), out.load()
    for y in range(src.height):
        for x in range(src.width):
            r, g, b, alpha = source[x, y]
            color = WHITE if alpha == 0 else (r, g, b)
            if color not in index:
                index[color] = len(palette) // 3
                palette.extend(color)
            target[x, y] = index[color]
    ordered = list(WHITE)
    remap = {0: 0}
    for source_index in sorted(set(ref.get_flattened_data() if hasattr(ref, "get_flattened_data") else ref.getdata())):
        color = tuple(ref_palette[source_index * 3:source_index * 3 + 3])
        if color != WHITE and color in index:
            remap[index[color]] = len(ordered) // 3
            ordered.extend(color)
    for y in range(src.height):
        for x in range(src.width):
            target[x, y] = remap[target[x, y]]
    out.putpalette(ordered + [0] * (768 - len(ordered)))
    return out


def emerald_rgba(data: bytes) -> Image.Image:
    """Keep true alpha and internal white; do not apply Crystal palette folding."""
    with Image.open(io.BytesIO(data)) as source:
        if source.mode != "RGBA":
            return source.convert("RGBA").copy()
        return source.copy()


def validate_sprite(image: Image.Image, expected_mode: str) -> None:
    if image.mode != expected_mode:
        raise ValueError(f"sprite must decode as {expected_mode}, got {image.mode}")
    if image.width != image.height:
        raise ValueError(f"sprite is not square: {image.size}")
    if image.mode == "P":
        visible = image.convert("RGBA").getchannel("A").getbbox() is not None
    else:
        visible = image.getchannel("A").getbbox() is not None
    if not visible:
        raise ValueError("sprite has no visible pixels")


def fetch(url: str, attempts: int = 3, timeout: int = 15) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "PokeTactics-data-import/1.0"})
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504):
                raise
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(0.4 * attempt)
    raise RuntimeError(f"failed after {attempts} attempts: {url}") from last_error


def build_reference(csv_root: Path, output: Path, run_emerald_cross_check: bool = False) -> None:
    tables = read_csvs(csv_root)

    species = {
        int(row["id"]): row
        for row in tables["pokemon_species.csv"]
        if FIRST_ID <= int(row["id"]) <= LAST_ID
    }
    default_pokemon = {
        int(row["species_id"]): row
        for row in tables["pokemon.csv"]
        if FIRST_ID <= int(row["species_id"]) <= LAST_ID and row["is_default"] == "1"
    }
    if set(species) != set(range(FIRST_ID, LAST_ID + 1)):
        raise ValueError("PokeAPI species table does not contain ids 1..386")
    if set(default_pokemon) != set(species):
        raise ValueError("PokeAPI default pokemon table does not cover ids 1..386")

    names = {
        int(row["pokemon_species_id"]): row["name"]
        for row in tables["pokemon_species_names.csv"]
        if row["local_language_id"] == str(CHINESE_LANGUAGE_ID)
    }
    type_names = {int(row["id"]): row["identifier"].upper() for row in tables["types.csv"]}
    stat_names = {int(row["id"]): row["identifier"] for row in tables["stats.csv"]}
    move_names = {int(row["id"]): row["identifier"] for row in tables["moves.csv"]}
    move_generations = {int(row["id"]): int(row["generation_id"]) for row in tables["moves.csv"]}

    current_stats: dict[int, dict[int, int]] = defaultdict(dict)
    for row in tables["pokemon_stats.csv"]:
        pokemon_id = int(row["pokemon_id"])
        if pokemon_id in species:
            current_stats[pokemon_id][int(row["stat_id"])] = int(row["base_stat"])

    past_stats: dict[int, dict[tuple[int, int], int]] = defaultdict(dict)
    for row in tables["pokemon_stats_past.csv"]:
        pokemon_id = int(row["pokemon_id"])
        if pokemon_id in species:
            past_stats[pokemon_id][(int(row["generation_id"]), int(row["stat_id"]))] = int(row["base_stat"])

    current_types: dict[int, dict[int, int]] = defaultdict(dict)
    for row in tables["pokemon_types.csv"]:
        pokemon_id = int(row["pokemon_id"])
        if pokemon_id in species:
            current_types[pokemon_id][int(row["slot"])] = int(row["type_id"])

    past_types: dict[int, dict[tuple[int, int], int]] = defaultdict(dict)
    for row in tables["pokemon_types_past.csv"]:
        pokemon_id = int(row["pokemon_id"])
        if pokemon_id in species:
            past_types[pokemon_id][(int(row["generation_id"]), int(row["slot"]))] = int(row["type_id"])

    children: dict[int, list[int]] = defaultdict(list)
    for pokemon_id, row in species.items():
        parent = int(row["evolves_from_species_id"]) if row["evolves_from_species_id"] else 0
        if parent in species:
            children[parent].append(pokemon_id)

    level_moves: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    for row in tables["pokemon_moves.csv"]:
        pokemon_id = int(row["pokemon_id"])
        move_id = int(row["move_id"])
        if (pokemon_id not in species
                or row["version_group_id"] != str(EMERALD_VERSION_GROUP_ID)
                or row["pokemon_move_method_id"] != str(LEVEL_UP_METHOD_ID)
                or move_generations.get(move_id, 99) > TARGET_GENERATION):
            continue
        level_moves[pokemon_id].append(
            (int(row["level"]), move_id, int(row["order"] or 0))
        )

    entries = []
    stat_key_map = {
        "hp": "hp",
        "attack": "attack",
        "defense": "defense",
        "special-attack": "special_attack",
        "special-defense": "special_defense",
        "speed": "speed",
    }
    for pokemon_id in range(FIRST_ID, LAST_ID + 1):
        row = species[pokemon_id]
        base = {
            stat_key_map[stat_names[stat_id]]:
                snapshot_past(past_stats[pokemon_id], stat_id, value)
            for stat_id, value in current_stats[pokemon_id].items()
        }
        if len(base) != 6 or sorted(base) != sorted(stat_key_map.values()):
            raise ValueError(f"species {pokemon_id}: incomplete base stats {base}")

        types_by_slot = snapshot_types(current_types[pokemon_id], past_types[pokemon_id])
        types = [type_names[types_by_slot[slot]] for slot in sorted(types_by_slot)]
        if not 1 <= len(types) <= 2:
            raise ValueError(f"species {pokemon_id}: invalid type count {types}")

        lineage = [pokemon_id]
        cursor = pokemon_id
        while True:
            parent = int(species[cursor]["evolves_from_species_id"]) if species[cursor]["evolves_from_species_id"] else 0
            if parent not in species:
                break
            lineage.append(parent)
            cursor = parent

        seen_moves: set[tuple[int, int]] = set()
        learnset = []
        for level, move_id, order in sorted(level_moves[pokemon_id], key=lambda item: (item[0], item[2], item[1])):
            if (level, move_id) in seen_moves:
                continue
            seen_moves.add((level, move_id))
            learnset.append({"level": level, "move_id": move_id, "move": move_names[move_id]})

        entries.append({
            "id": pokemon_id,
            "name": row["identifier"],
            "name_zh": names[pokemon_id],
            "generation": int(row["generation_id"]),
            "types": types,
            "base": {
                "hp": base["hp"],
                "attack": base["attack"],
                "defense": base["defense"],
                "speed": base["speed"],
                "special_attack": base["special_attack"],
                "special_defense": base["special_defense"],
            },
            "lineage": lineage,
            "evolves_to": sorted(children[pokemon_id]),
            "level_up_pokeapi": learnset,
        })

    generations = {generation: sum(entry["generation"] == generation for entry in entries)
                   for generation in (1, 2, 3)}
    if generations != {1: 151, 2: 100, 3: 135}:
        raise ValueError(f"unexpected generation counts: {generations}")

    cross_check = cross_check_emerald(entries) if run_emerald_cross_check else None
    payload = {
        "schema_version": 1,
        "scope": "Pokemon species 1-386; Generation III historical reference only; never auto-add shop or combat cards.",
        "sources": {
            "data_repository": POKEAPI_REPO,
            "data_commit": POKEAPI_COMMIT,
            "source_file_sha256": {name: sha256_file(csv_root / name) for name in CSV_FILES},
            "historical_policy": (
                "PokeAPI past generation_id is the final generation for an old snapshot. "
                "For target generation 3 choose the earliest past snapshot with generation_id >= 3; "
                "if absent use current values. This restores pre-Fairy types and Generation III stat values."
            ),
            "name_zh": "PokeAPI Simplified Chinese official names (local_language_id 12)",
            "evolution": "Direct evolves_from_species_id relationships, filtered to species 1-386",
            "learnset": (
                "PokeAPI Emerald version_group_id 6 level-up moves, generation <= 3. "
                "level_up_pokeapi uses PokeAPI move IDs and identifiers; do not interpret them "
                "as PokeTactics runtime move IDs."
            ),
            **({"emerald_cross_check": cross_check} if cross_check is not None else {}),
        },
        "entries": entries,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output} ({len(entries)} entries, generations={generations})")


PRIORITY_GEN3_IDS = (252, 253, 254, 255, 256, 257, 258, 259, 260, 270, 271,
                     272, 280, 281, 282, 285, 286, 304, 305, 306, 333, 334,
                     349, 350, 359, 371, 372, 373, 374, 375, 376)


def cross_check_emerald(entries: list[dict]) -> dict:
    """Compare all 386 PokeAPI historical stats/types with pret pokeemerald."""
    species_info_blob = fetch(POKEEMERALD_SPECIES_INFO_URL)
    species_constants_blob = fetch(POKEEMERALD_SPECIES_CONSTANTS_URL)
    species_info = species_info_blob.decode("utf-8")
    constants_text = species_constants_blob.decode("utf-8")
    special_names = {
        "nidoran_f": "nidoran-f",
        "nidoran_m": "nidoran-m",
        "mr_mime": "mr-mime",
        "ho_oh": "ho-oh",
    }
    reference = {entry["name"]: entry for entry in entries}
    parsed = {}
    for block in species_info.split("\n    [SPECIES_")[1:]:
        constant = "SPECIES_" + block.split("]", 1)[0]
        stem = constant[len("SPECIES_"):].lower()
        identifier = special_names.get(stem, stem.replace("_", "-"))
        if identifier not in reference:
            continue
        body = block.split("\n    },", 1)[0]
        base = {}
        for source_key, result_key in (
            ("baseHP", "hp"), ("baseAttack", "attack"), ("baseDefense", "defense"),
            ("baseSpeed", "speed"), ("baseSpAttack", "special_attack"),
            ("baseSpDefense", "special_defense"),
        ):
            match = re.search(r"\." + source_key + r"\s*=\s*(\d+)", body)
            if not match:
                raise ValueError(f"pokeemerald {identifier}: missing {source_key}")
            base[result_key] = int(match.group(1))
        match = re.search(r"\.types\s*=\s*\{\s*TYPE_([A-Z]+)(?:,\s*TYPE_([A-Z]+))?\s*\}", body)
        if not match:
            raise ValueError(f"pokeemerald {identifier}: missing types")
        types = [match.group(1)] + ([match.group(2)] if match.group(2) else [])
        if len(types) == 2 and types[0] == types[1]:
            types = types[:1]
        parsed[identifier] = (base, types)

    if set(parsed) != set(reference):
        missing = sorted(set(reference) - set(parsed))
        extra = sorted(set(parsed) - set(reference))
        raise ValueError(f"pokeemerald species mismatch; missing={missing[:5]}, extra={extra[:5]}")
    mismatches = []
    for identifier, (base, types) in parsed.items():
        if base != reference[identifier]["base"]:
            mismatches.append((identifier, "base", base, reference[identifier]["base"]))
        if types != reference[identifier]["types"]:
            mismatches.append((identifier, "types", types, reference[identifier]["types"]))
    if mismatches:
        raise ValueError(f"pokeemerald cross-check mismatches: {mismatches[:10]}")
    return {
        "repository": POKEEMERALD_REPO,
        "commit": POKEEMERALD_COMMIT,
        "species_info_sha256": sha256_bytes(species_info_blob),
        "species_constants_sha256": sha256_bytes(species_constants_blob),
        "result": "386/386 base stats and types matched",
    }


def import_sprites(priority_only: bool = False) -> None:
    gen2_root = ROOT / "assets" / "gen2"
    gen3_root = ROOT / "assets" / "gen3"
    for directory in (gen2_root / "normal", gen2_root / "shiny", gen3_root / "normal", gen3_root / "shiny"):
        directory.mkdir(parents=True, exist_ok=True)

    manifests = {
        "gen2": {"repository": SPRITES_REPO, "commit": SPRITES_COMMIT, "style": "Crystal front sprites",
                 "format": "indexed P; background/enclosed white folded to palette index 0",
                 "decode_policy": "Use the existing assets/gen2 Crystal decoder policy", "files": {}},
        "gen3": {"repository": SPRITES_REPO, "commit": SPRITES_COMMIT, "style": "Emerald front sprites",
                 "format": "RGBA with true transparency and internal white preserved",
                 "decode_policy": "Do not apply the Crystal enclosed-white transform", "files": {}},
    }

    def save(sprite_id: int, shiny: bool, generation: int) -> tuple[str, dict]:
        kind = "shiny" if shiny else "normal"
        if generation == 2:
            root = gen2_root
            style = "versions/generation-ii/crystal"
            transform, expected_mode = crystal_png, "P"
        else:
            root = gen3_root
            style = "versions/generation-iii/emerald"
            transform, expected_mode = emerald_rgba, "RGBA"
        path = root / kind / f"{sprite_id}.png"
        relative = str(path.relative_to(ROOT))
        relative_url = f"sprites/pokemon/{style}/{'shiny/' if shiny else ''}{sprite_id}.png"
        url = f"https://raw.githubusercontent.com/PokeAPI/sprites/{SPRITES_COMMIT}/{relative_url}"
        data = fetch(url)
        image = transform(data)
        validate_sprite(image, expected_mode)
        if path.exists():
            with Image.open(path) as existing:
                if (existing.mode != image.mode or existing.size != image.size
                        or existing.tobytes() != image.tobytes()):
                    raise ValueError(f"source sprite differs from protected existing file: {path}")
        else:
            image.save(path)
            print(f"wrote {path} {image.size} {image.mode}", flush=True)
        return relative, {"url": url, "sha256": sha256_bytes(data), "bytes": len(data), "kind": kind}

    jobs = [(sprite_id, shiny, 3) for sprite_id in PRIORITY_GEN3_IDS for shiny in (False, True)]
    if not priority_only:
        jobs.extend((sprite_id, shiny, 3) for sprite_id in range(252, 387) for shiny in (False, True))
        jobs.extend((sprite_id, shiny, 2) for sprite_id in range(152, 252) for shiny in (False, True))
    unique_jobs = list(dict.fromkeys(jobs))

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="sprite-import") as executor:
        futures = {executor.submit(save, *job): job for job in unique_jobs}
        for future in as_completed(futures):
            sprite_id, shiny, generation = futures[future]
            relative, record = future.result()
            manifests[f"gen{generation}"]["files"][relative] = record

    gen2_manifest_path = gen2_root / "gen123_import_sources.json"
    gen3_manifest_path = gen3_root / "sources.json"
    for generation, path in ((2, gen2_manifest_path), (3, gen3_manifest_path)):
        key = f"gen{generation}"
        if path.exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
            merged_files = previous.get("files", {})
            merged_files.update(manifests[key]["files"])
            manifests[key]["files"] = merged_files
        manifests[key]["files"] = dict(sorted(manifests[key]["files"].items()))
        path.write_text(json.dumps(manifests[key], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path} ({len(manifests[key]['files'])} files)", flush=True)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pokeapi-dir", type=Path,
                        help="Directory containing PokeAPI CSV files (data/v2/csv or csv)")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "pokemon_gen123_reference.json")
    parser.add_argument("--download-assets", action="store_true",
                        help="Import missing sprites and verify protected files against the pinned source")
    parser.add_argument("--assets-only", action="store_true")
    parser.add_argument("--priority-only", action="store_true", help="Only import the first 31 playable Gen III forms")
    parser.add_argument("--self-test", action="store_true", help="Run synthetic historical snapshot assertions")
    parser.add_argument("--emerald-cross-check", action="store_true", help="Cross-check all stats/types with pinned pret pokeemerald")
    args = parser.parse_args(argv)

    if args.self_test:
        assert snapshot_types({1: 18, 2: 18}, {(5, 1): 14}) == {1: 14}
        assert snapshot_past({(3, 4): 100, (5, 4): 125}, 4, 90) == 100
        print("historical snapshot self-test passed")
        return 0

    if args.assets_only:
        import_sprites(priority_only=args.priority_only)
        return 0

    pokeapi_dir = args.pokeapi_dir
    temp_dir: tempfile.TemporaryDirectory | None = None
    if pokeapi_dir is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="pokeapi-gen123-")
        pokeapi_dir = Path(temp_dir.name)
        download_pokeapi(pokeapi_dir)
    csv_root = pokeapi_dir / "csv"
    if not csv_root.exists():
        csv_root = pokeapi_dir / "data" / "v2" / "csv"
    if not csv_root.exists():
        raise FileNotFoundError(f"cannot find CSV directory under {pokeapi_dir}")

    try:
        build_reference(csv_root, args.output, run_emerald_cross_check=args.emerald_cross_check)
        if args.download_assets:
            import_sprites(priority_only=args.priority_only)
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir.name, ignore_errors=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, tarfile.TarError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
