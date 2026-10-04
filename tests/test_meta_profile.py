"""Challenge progression is retry-safe and never replaces a damaged profile."""

import copy
import hashlib
import itertools
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "sim", ROOT / "tools" / "acceptance"):
    sys.path.insert(0, str(directory))

from esp32_runtime import (CorruptSaveError, InvalidStateError, StorageIOError,
                           UnsupportedVersionError)
from meta_profile import MAX_PROFILE_BYTES, ProfileCodec, ProfileStore
from sim import metagame
import items
from shop import build_templates


def snapshot(run=1, *, seen=(3,), fielded=(3,), won=(), round_no=1, finished=False, rank=None):
    return {"run_id": f"{run:032x}", "seen": list(seen), "fielded": list(fielded),
            "won": list(won), "round": round_no, "finished": finished, "rank": rank}


def progress(**kwargs):
    return metagame.apply_progress(metagame.initial_profile(), snapshot(**kwargs))


def changed_envelope(raw, **fields):
    body = json.loads(raw)
    body.update(fields)
    del body["checksum"]
    canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode()
    body["checksum"] = hashlib.sha256(canonical(body)).hexdigest()
    return canonical(body)


class MetaProgressContracts(unittest.TestCase):
    def test_default_options_and_unlocks_do_not_change_shop(self):
        templates = build_templates()
        original = copy.deepcopy(templates)
        display = metagame.view(metagame.initial_profile())
        self.assertEqual(display["partner_ids"], [3, 6, 9])
        self.assertEqual(display["technique_ids"], ["none"])
        self.assertEqual(display["item_ids"], ["none"])
        self.assertEqual(display["stats"], dict(runs=0, finished=0, wins=0, top4=0,
                                               rounds=0, seen=0, fielded=0, won=0))
        self.assertFalse(any(challenge["unlocked"] for challenge in display["challenges"]))
        self.assertEqual(len(templates), 84)
        self.assertEqual(set(templates), set(original))
        self.assertEqual({row["id"] for row in metagame.STARTER_ITEMS} - {"none"},
                         {"sash", "leftovers"})
        self.assertTrue(all(row["id"] in items.FINISHED for row in metagame.STARTER_ITEMS
                            if row["id"] != "none"))

    def test_seen_species_alone_do_not_unlock_fielding_challenges(self):
        display = metagame.view(progress(seen=(3, 6, 9, 26, 143, 25), fielded=()))
        self.assertEqual(display["stats"]["seen"], 6)
        self.assertEqual(display["partner_ids"], [3, 6, 9])
        self.assertEqual(display["technique_ids"], ["none"])

    def test_failure_and_cross_run_fielding_unlock_horizontal_choices(self):
        first = progress(finished=True, rank=8, round_no=4)
        display = metagame.view(first)
        self.assertEqual(display["technique_ids"], ["none", "cut", "rest"])
        self.assertEqual(display["item_ids"], ["none", "leftovers"])
        self.assertEqual(display["stats"]["finished"], 1)
        self.assertEqual(display["stats"]["wins"], 0)
        second = metagame.apply_progress(first, snapshot(2, seen=(6, 9), fielded=(6, 9)))
        display = metagame.view(second)
        self.assertEqual(display["partner_ids"], [3, 6, 9, 26])
        self.assertIn("surf", display["technique_ids"])
        third = metagame.apply_progress(second, snapshot(3, seen=(25, 26, 143), fielded=(25, 26, 143)))
        display = metagame.view(third)
        self.assertEqual(display["partner_ids"], [3, 6, 9, 26, 143])
        self.assertEqual(display["item_ids"], ["none", "leftovers", "sash"])
        self.assertEqual(display["stats"]["fielded"], 6)
        self.assertTrue(all(challenge["unlocked"] for challenge in display["challenges"]))

    def test_duplicate_settlement_and_all_snapshot_orders_are_idempotent(self):
        snapshots = [snapshot(seen=(3, 6), fielded=(3,), round_no=1),
                     snapshot(seen=(3, 6, 9), fielded=(3, 6), won=(3,), round_no=3),
                     snapshot(seen=(3, 6, 9), fielded=(3, 6, 9), won=(3, 6),
                              round_no=8, finished=True, rank=1)]
        expected = None
        for ordered in itertools.permutations(snapshots):
            profile = metagame.initial_profile()
            for entry in (*ordered, *ordered):
                profile = metagame.apply_progress(profile, entry)
            if expected is None:
                expected = profile
            self.assertEqual(profile, expected)
        stats = metagame.view(expected)["stats"]
        self.assertEqual((stats["runs"], stats["finished"], stats["wins"], stats["rounds"]), (1, 1, 1, 8))
        self.assertEqual((stats["seen"], stats["fielded"], stats["won"]), (3, 3, 2))

    def test_union_uses_run_id_and_does_not_mutate_inputs(self):
        old = progress(round_no=5, finished=True, rank=1)
        incoming = snapshot(seen=(9, 6), fielded=(6,), round_no=2)
        untouched_profile, untouched_snapshot = copy.deepcopy(old), copy.deepcopy(incoming)
        merged = metagame.apply_progress(old, incoming)
        self.assertEqual(old, untouched_profile)
        self.assertEqual(incoming, untouched_snapshot)
        self.assertEqual(metagame.view(merged)["dex"]["seen"], [3, 6, 9])
        self.assertEqual(metagame.view(merged)["stats"]["wins"], 1)
        merged = metagame.apply_progress(merged, snapshot(2, round_no=5, finished=True, rank=1))
        self.assertEqual(metagame.view(merged)["stats"]["wins"], 2)

    def test_conflicting_terminal_rank_fails_without_rewriting_a_win(self):
        profile = progress(finished=True, rank=1)
        with self.assertRaises(ValueError):
            metagame.apply_progress(profile, snapshot(finished=True, rank=8))
        self.assertEqual(metagame.view(profile)["stats"]["wins"], 1)

    def test_strict_snapshot_types_and_bounds(self):
        invalid = [dict(run_id="A" * 32), dict(run_id="a" * 31), dict(run_id=1),
                   dict(seen=[True]), dict(seen=[0]), dict(seen=[65536]), dict(seen=[3, 3]),
                   dict(seen=list(range(1, metagame.MAX_OBSERVATIONS_PER_RUN + 2))),
                   dict(seen=(3,)), dict(fielded=[6]), dict(won=[6]), dict(round=True),
                   dict(round=-1), dict(round=32), dict(finished=1), dict(rank=1),
                   dict(finished=True), dict(finished=True, rank=True),
                   dict(finished=True, rank=9), dict(finished=True, rank=1, round=0),
                   dict(unlocked=["cut"])]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                metagame.apply_progress(metagame.initial_profile(), {**snapshot(), **changes})
        for invalid_profile in (None, [], {}, {"runs": []}, {"runs": {}, "wins": 100},
                                {"runs": {"bad": snapshot()}},
                                {"runs": {"a" * 32: {"round": 1}}}):
            with self.subTest(profile=invalid_profile), self.assertRaises(ValueError):
                metagame.validate_profile(invalid_profile)

    def test_view_and_codec_are_detached_from_profile_and_catalogs(self):
        profile = progress()
        display = metagame.view(profile)
        display["partners"][0]["name"] = "changed"
        display["challenges"][0]["rewards"][0]["name"] = "changed"
        encoded = ProfileCodec().encode(profile)
        encoded["runs"][snapshot()["run_id"]]["seen"].append(9)
        self.assertEqual(profile, progress())
        self.assertEqual(metagame.view(profile)["partners"][0]["name"], "妙蛙花")
        self.assertEqual(metagame.view(profile)["challenges"][0]["rewards"][0]["name"], "居合斩")

    def test_run_capacity_preserves_every_deduplication_record(self):
        record = {key: value for key, value in snapshot().items() if key != "run_id"}
        profile = {"runs": {f"{run:032x}": copy.deepcopy(record) for run in range(metagame.MAX_RUNS)}}
        before = copy.deepcopy(profile)
        with self.assertRaises(metagame.ProfileCapacityError):
            metagame.apply_progress(profile, snapshot(metagame.MAX_RUNS))
        self.assertEqual(profile, before)
        self.assertEqual(metagame.apply_progress(profile, snapshot(1)), profile)
        profile["runs"][f"{metagame.MAX_RUNS:032x}"] = record
        with self.assertRaises(metagame.ProfileCapacityError):
            metagame.validate_profile(profile)

    def test_snapshot_union_overflow_is_rejected_without_mutating_inputs(self):
        species = list(range(1, metagame.MAX_OBSERVATIONS_PER_RUN + 1))
        profile = progress(seen=species, fielded=())
        incoming = snapshot(seen=(252,), fielded=(), round_no=2)
        old_profile, old_snapshot = copy.deepcopy(profile), copy.deepcopy(incoming)
        # Each input fits on its own; their disjoint union would contain 152 ids.
        self.assertEqual(metagame.validate_profile(profile), profile)
        self.assertEqual(metagame.validate_snapshot(incoming), incoming)
        with self.assertRaises(ValueError):
            metagame.apply_progress(profile, incoming)
        self.assertEqual(profile, old_profile)
        self.assertEqual(incoming, old_snapshot)
        # A retry with overlapping observations at capacity is still accepted.
        updated = metagame.apply_progress(profile, snapshot(seen=(3,), fielded=(), round_no=2))
        self.assertEqual(metagame.validate_profile(updated), updated)
        self.assertEqual(updated["runs"][incoming["run_id"]]["seen"], species)


class MetaStorageContracts(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.store = ProfileStore(self.root)

    def files(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def slot(self, index):
        return self.root / "poketactics-meta" / f"trainer.{index}"

    def test_missing_creates_profile_and_restart_preserves_progress(self):
        self.assertEqual(self.store.load(), metagame.initial_profile())
        self.assertTrue(self.slot(0).exists())
        self.store.save(progress(finished=True, rank=8))
        restarted = ProfileStore(self.root)
        self.assertEqual(restarted.load(), progress(finished=True, rank=8))
        exported = restarted.export_backup()
        self.assertEqual(exported, restarted.export_backup())
        self.assertEqual(restarted.inspect_backup(exported), restarted.load())

    def test_corrupt_existing_profile_never_becomes_a_new_profile(self):
        self.store.load()
        self.slot(0).write_bytes(b"truncated")
        before = self.files()
        for action in (self.store.load, self.store.export_backup,
                       lambda: self.store.save(metagame.initial_profile())):
            with self.assertRaises(CorruptSaveError):
                action()
            self.assertEqual(self.files(), before)

    def test_bad_newer_slot_recovers_old_data_without_overwriting_bytes(self):
        self.store.save(progress())
        self.store.save(progress(finished=True, rank=1))
        self.slot(1).write_bytes(b"corrupt latest")
        before = self.files()
        self.assertEqual(self.store.load(), progress())
        self.assertTrue(self.store.last_loaded.recovered)
        self.assertEqual(before, self.files())

    def test_verified_future_profile_version_blocks_load_save_and_import(self):
        self.store.save(progress())
        original = self.store.export_backup()
        self.slot(1).write_bytes(changed_envelope(original, schema_version=2, sequence=2))
        before = self.files()
        for action in (self.store.load, lambda: self.store.save(progress()),
                       lambda: self.store.import_backup(original)):
            with self.assertRaises(UnsupportedVersionError):
                action()
            self.assertEqual(self.files(), before)

    def test_bad_backups_cannot_change_profile_or_checkpoint(self):
        self.store.save(progress(finished=True, rank=8))
        original = self.store.export_backup()
        invalid_payload = copy.deepcopy(progress())
        invalid_payload["runs"][snapshot()["run_id"]]["seen"] = [True]
        bad_backups = [(b"broken", CorruptSaveError),
                       (changed_envelope(original, payload=invalid_payload), InvalidStateError),
                       (changed_envelope(original, schema_version=2), UnsupportedVersionError)]
        before = self.files()
        for raw, error_type in bad_backups:
            with self.subTest(error=error_type), self.assertRaises(error_type):
                self.store.import_backup(raw)
            self.assertEqual(self.files(), before)

    def test_import_is_checked_and_retains_previous_profile_as_checkpoint(self):
        self.store.save(progress(finished=True, rank=8))
        previous = self.store.export_backup()
        incoming = changed_envelope(previous, payload=progress(finished=True, rank=1))
        self.assertEqual(self.store.import_backup(incoming), progress(finished=True, rank=1))
        self.assertEqual(self.store.load(), progress(finished=True, rank=1))
        self.assertEqual(self.store.store.export_checkpoint(), previous)
        before = self.files()
        self.assertEqual(self.store.inspect_backup(incoming), progress(finished=True, rank=1))
        self.assertEqual(self.files(), before)

    def test_io_failure_is_not_treated_as_a_new_profile(self):
        self.store.save(progress())
        before = self.files()
        with patch.object(self.store.store.backend, "read", side_effect=StorageIOError("offline")):
            with self.assertRaises(StorageIOError):
                self.store.load()
        self.assertEqual(self.files(), before)

    def test_maximum_valid_ledger_fits_the_backup_capacity(self):
        species = list(range(metagame.MAX_SPECIES_ID - metagame.MAX_OBSERVATIONS_PER_RUN + 1,
                             metagame.MAX_SPECIES_ID + 1))
        record = {"seen": species, "fielded": species, "won": species,
                  "round": metagame.MAX_ROUNDS, "finished": True, "rank": 1}
        profile = {"runs": {f"{run:032x}": record for run in range(metagame.MAX_RUNS)}}
        self.store.save(profile)
        raw = self.store.export_backup()
        self.assertGreater(len(raw), 4 * 1024 * 1024)
        self.assertLess(len(raw), MAX_PROFILE_BYTES)
        stats = metagame.view(self.store.inspect_backup(raw))["stats"]
        self.assertEqual(stats["wins"], metagame.MAX_RUNS)
        self.assertEqual(stats["rounds"], metagame.MAX_RUNS * metagame.MAX_ROUNDS)

    def test_future_species_ids_roundtrip_without_requiring_a_roster_entry(self):
        profile = progress(seen=(252, 65535), fielded=(252, 65535), won=(65535,))
        self.store.save(profile)
        raw = self.store.export_backup()
        restored = ProfileStore(self.root).inspect_backup(raw)
        self.assertEqual(restored, profile)
        self.assertEqual(metagame.view(restored)["dex"]["seen"], [252, 65535])
        self.assertEqual(self.store.import_backup(raw), profile)


if __name__ == "__main__":
    unittest.main()
