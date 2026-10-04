"""Storage integrity, migration and fault tests without any Pokemon dependency."""

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from esp32_runtime import (
    CorruptSaveError, FileBackend, GameMismatchError, InvalidStateError,
    NoSaveError, SaveStore, StorageIOError, TooLargeError, UnsupportedVersionError,
)


class CounterCodec:
    game_id = "counter"
    schema_version = 2

    def encode(self, state):
        return copy.deepcopy(state)

    def decode(self, payload, schema_version):
        # A real older shape, rather than a current payload with its version lowered.
        if schema_version == 1:
            if type(payload) is not dict or set(payload) != {"coins"}:
                raise ValueError("invalid V1 shape")
            payload = {"score": payload["coins"], "unlocked": []}
        if (type(payload) is not dict or set(payload) != {"score", "unlocked"}
                or type(payload["score"]) is not int or payload["score"] < 0
                or type(payload["unlocked"]) is not list
                or any(type(x) is not str for x in payload["unlocked"])):
            raise ValueError("invalid counter state")
        return copy.deepcopy(payload)


class MemoryBackend:
    def __init__(self):
        self.data = {}
        self.writes = []
        self.fail_key = None
        self.failure = None
        self.fail_read = False
        self.fail_delete = False

    def read(self, namespace, key):
        if self.fail_read:
            raise OSError("injected read failure")
        return self.data.get((namespace, key))

    def write_atomic(self, namespace, key, data):
        self.writes.append((namespace, key))
        if key == self.fail_key:
            if self.failure == "before":
                raise OSError("injected write failure")
            if self.failure == "torn":
                self.data[(namespace, key)] = data[:len(data) // 2]
                return
            if self.failure == "after":
                self.data[(namespace, key)] = data
                raise OSError("injected ambiguous write")
        self.data[(namespace, key)] = data

    def delete(self, namespace, key):
        if self.fail_delete:
            raise OSError("injected cleanup failure")
        self.data.pop((namespace, key), None)


def envelope(payload, *, game_id="counter", schema_version=2, sequence=1,
             storage_version=1):
    """Independent fixture writer following the documented portable wire format."""
    body = dict(game_id=game_id, storage_version=storage_version,
                schema_version=schema_version, sequence=sequence, payload=payload)
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":")).encode("utf-8")
    body["checksum"] = hashlib.sha256(canonical).hexdigest()
    return json.dumps(body, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def state(score):
    return {"score": score, "unlocked": ["chapter_one"]}


class RuntimeStorageContracts(unittest.TestCase):
    def setUp(self):
        self.backend = MemoryBackend()
        self.store = SaveStore(self.backend, CounterCodec())

    def put(self, index, data):
        self.backend.data[("counter", f"autosave.{index}")] = data

    def test_empty_is_distinct_from_corrupt_and_error_does_not_authorize_save(self):
        with self.assertRaises(NoSaveError):
            self.store.load()
        self.put(0, b"truncated")
        before = dict(self.backend.data)
        for action in (self.store.load, lambda: self.store.save(state(1)),
                       lambda: self.store.import_backup(envelope(state(2)))):
            with self.assertRaises(CorruptSaveError):
                action()
        self.assertEqual(self.backend.data, before)

    def test_slots_alternate_and_newest_sequence_wins(self):
        self.assertEqual(self.store.save(state(1)).slot_index, 0)
        self.assertEqual(self.store.save(state(2)).slot_index, 1)
        info = self.store.save(state(3))
        self.assertEqual((info.slot_index, info.sequence), (0, 3))
        self.assertEqual(self.store.load().state, state(3))
        self.assertFalse(self.store.load().recovered)

    def test_corrupt_or_truncated_new_slot_falls_back_to_old(self):
        self.store.save(state(1))
        for bad in (b"{", envelope(state(2))[:-12], b"\xff"):
            with self.subTest(bad=bad):
                self.put(1, bad)
                loaded = self.store.load()
                self.assertEqual(loaded.state, state(1))
                self.assertTrue(loaded.recovered)
                self.assertTrue(loaded.warnings)
        self.store.save(state(3))
        self.assertEqual(self.store.load().state, state(3))

    def test_bad_checksum_does_not_trust_poisoned_version_or_sequence(self):
        self.store.save(state(1))
        body = json.loads(envelope(state(2)))
        body.update(schema_version=999, sequence=999)
        self.put(1, json.dumps(body).encode())
        self.assertEqual(self.store.load().state, state(1))

    def test_valid_newer_schema_or_storage_version_blocks_load_and_mutation(self):
        self.store.save(state(1))
        for kwargs in ({"schema_version": 3}, {"storage_version": 2}):
            with self.subTest(kwargs=kwargs):
                self.put(1, envelope(state(2), sequence=2, **kwargs))
                before = dict(self.backend.data)
                for action in (self.store.load, lambda: self.store.save(state(4)),
                               lambda: self.store.import_backup(envelope(state(5)))):
                    with self.assertRaises(UnsupportedVersionError):
                        action()
                self.assertEqual(self.backend.data, before)

    def test_both_corrupt_slots_are_not_empty(self):
        self.put(0, b"{")
        self.put(1, b"{}")
        with self.assertRaises(CorruptSaveError):
            self.store.load()

    def test_sequence_does_not_override_schema_compatibility(self):
        self.put(0, envelope(state(1), sequence=9))
        self.put(1, envelope(state(2), schema_version=3, sequence=1))
        with self.assertRaises(UnsupportedVersionError):
            self.store.save(state(3))

    def test_read_failure_does_not_fall_back_or_create_new_save(self):
        self.store.save(state(1))
        writes = len(self.backend.writes)
        self.backend.fail_read = True
        for action in (self.store.load, lambda: self.store.save(state(2))):
            with self.assertRaises(StorageIOError):
                action()
        self.assertEqual(len(self.backend.writes), writes)

    def test_game_namespaces_are_isolated_and_cross_game_import_is_refused(self):
        self.store.save(state(1))
        other_codec = CounterCodec()
        other_codec.game_id = "other_game"
        other = SaveStore(self.backend, other_codec)
        other.save(state(9))
        before = dict(self.backend.data)
        with self.assertRaises(GameMismatchError):
            self.store.import_backup(other.export_backup())
        self.assertEqual(self.backend.data, before)
        self.assertEqual(self.store.load().state, state(1))
        self.assertEqual(other.load().state, state(9))
        wrong_namespace = SaveStore(self.backend, other_codec, namespace="counter")
        with self.assertRaises(GameMismatchError):
            wrong_namespace.save(state(10))

    def test_legacy_migration_is_read_only_until_explicit_save(self):
        legacy = envelope({"coins": 17}, schema_version=1)
        self.put(0, legacy)
        loaded = self.store.load()
        self.assertEqual(loaded.state, {"score": 17, "unlocked": []})
        self.assertTrue(loaded.migrated)
        self.assertEqual(self.store.export_backup(), legacy)
        self.assertEqual(self.backend.writes, [])
        self.store.save(loaded.state)
        self.assertEqual(self.store.load().schema_version, 2)

    def test_backup_roundtrip_and_local_sequence_do_not_inherit_foreign_counter(self):
        self.store.save(state(1))
        self.store.import_backup(envelope(state(77), sequence=900))
        loaded = self.store.load()
        self.assertEqual((loaded.state, loaded.sequence), (state(77), 2))
        target = SaveStore(MemoryBackend(), CounterCodec())
        target.import_backup(self.store.export_backup())
        self.assertEqual(target.load().state, state(77))
        self.assertEqual(target.load().sequence, 1)

    def test_import_preserves_persisted_checkpoint(self):
        self.store.save(state(1))
        previous = self.store.export_backup()
        self.store.import_backup(envelope(state(2)))
        self.assertEqual(self.store.export_checkpoint(), previous)
        self.assertEqual(self.store.inspect_backup(self.store.export_checkpoint()).state, state(1))

    def test_import_checkpoints_unsaved_current_state_before_data_write(self):
        self.store.save(state(1))
        self.backend.writes.clear()
        self.store.import_backup(envelope(state(2)), checkpoint_state=state(99))
        self.assertEqual(self.backend.writes, [("counter", "autosave.checkpoint"),
                                               ("counter", "autosave.1")])
        self.assertEqual(self.store.inspect_backup(self.store.export_checkpoint()).state, state(99))

    def test_invalid_import_and_invalid_checkpoint_do_not_write(self):
        self.store.save(state(1))
        before = dict(self.backend.data)
        for blob in (b"{", envelope(state(2), schema_version=999),
                     envelope({"score": -1, "unlocked": []})):
            with self.subTest(blob=blob):
                with self.assertRaises((CorruptSaveError, UnsupportedVersionError, InvalidStateError)):
                    self.store.import_backup(blob, checkpoint_state=state(1))
                self.assertEqual(self.backend.data, before)
        with self.assertRaises(InvalidStateError):
            self.store.import_backup(envelope(state(2)), checkpoint_state={"score": -1})
        self.assertEqual(self.backend.data, before)

    def test_checkpoint_failure_aborts_import_before_data_slots_change(self):
        self.store.save(state(1))
        before = dict(self.backend.data)
        self.backend.fail_key, self.backend.failure = "autosave.checkpoint", "before"
        with self.assertRaises(StorageIOError):
            self.store.import_backup(envelope(state(2)))
        self.assertEqual(self.backend.data, before)
        self.assertEqual(self.store.load().state, state(1))

    def test_write_failure_torn_write_and_ambiguous_write_preserve_current(self):
        for failure in ("before", "torn", "after"):
            with self.subTest(failure=failure):
                self.setUp()
                self.store.save(state(1))
                self.backend.fail_key, self.backend.failure = "autosave.1", failure
                with self.assertRaises(StorageIOError):
                    self.store.import_backup(envelope(state(2)), checkpoint_state=state(99))
                self.assertEqual(self.store.load().state, state(1))
                self.assertEqual(self.store.inspect_backup(self.store.export_checkpoint()).state, state(99))

    def test_unconfirmed_cleanup_reports_commit_uncertainty_and_keeps_checkpoint(self):
        self.store.save(state(1))
        previous = self.store.export_backup()
        self.backend.fail_key, self.backend.failure = "autosave.1", "after"
        self.backend.fail_delete = True
        with self.assertRaises(StorageIOError) as caught:
            self.store.import_backup(envelope(state(2)))
        self.assertTrue(caught.exception.commit_uncertain)
        self.assertEqual(self.backend.data[("counter", "autosave.0")], previous)
        self.assertEqual(self.store.export_checkpoint(), previous)

    def test_decode_validation_rejects_checksum_valid_invalid_game_state(self):
        self.store.save(state(1))
        self.put(1, envelope({"score": -5, "unlocked": []}, sequence=2))
        self.assertEqual(self.store.load().state, state(1))
        self.assertTrue(self.store.load().recovered)

    def test_duplicate_keys_bad_types_and_nonfinite_json_are_rejected(self):
        good = envelope(state(1))
        samples = [good.replace(b'"sequence":1', b'"sequence":1,"sequence":1'),
                   good.replace(b'"sequence":1', b'"sequence":true'),
                   good.replace(b'"score":1', b'"score":NaN')]
        for sample in samples:
            with self.subTest(sample=sample):
                with self.assertRaises(CorruptSaveError):
                    self.store.inspect_backup(sample)
        with self.assertRaises(InvalidStateError):
            self.store.save({"score": 1, "unlocked": {"not": "a list"}})
        with self.assertRaises(InvalidStateError):
            self.store.save({"score": 1, "unlocked": [object()]})

    def test_equal_sequence_with_different_verified_payloads_is_ambiguous(self):
        self.put(0, envelope(state(1), sequence=5))
        self.put(1, envelope(state(2), sequence=5))
        with self.assertRaises(CorruptSaveError):
            self.store.load()

    def test_capacity_applies_to_whole_envelope_and_preserves_previous(self):
        small = SaveStore(self.backend, CounterCodec(), max_bytes=256)
        small.save(state(1))
        previous = small.export_backup()
        with self.assertRaises(TooLargeError):
            small.save({"score": 2, "unlocked": ["x" * 300]})
        self.assertEqual(small.export_backup(), previous)
        with self.assertRaises(TooLargeError):
            small.inspect_backup(b"x" * 257)

    def test_namespace_and_slot_reject_paths_and_unicode(self):
        for value in ("../escape", "/tmp", ".", "a/b", "a\\b", "游戏", "", "x" * 33):
            for key in ("namespace", "slot"):
                with self.subTest(value=value, key=key):
                    with self.assertRaises(ValueError):
                        SaveStore(self.backend, CounterCodec(), **{key: value})


class FileBackendContracts(unittest.TestCase):
    def test_disk_roundtrip_and_replace_failure_leave_old_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            backend = FileBackend(root)
            store = SaveStore(backend, CounterCodec())
            store.save(state(1))
            previous = store.export_backup()
            with patch("esp32_runtime.storage.os.replace", side_effect=OSError("injected rename failure")):
                with self.assertRaises(StorageIOError):
                    store.save(state(2))
            reopened = SaveStore(FileBackend(root), CounterCodec())
            self.assertEqual(reopened.export_backup(), previous)
            self.assertEqual(list((Path(root) / "counter").glob(".save-*")), [])

    def test_file_fsync_failure_occurs_before_replace(self):
        with tempfile.TemporaryDirectory() as root:
            backend = FileBackend(root)
            backend.write_atomic("counter", "record", b"old")
            with patch("esp32_runtime.storage.os.fsync", side_effect=OSError("injected fsync")), \
                    patch("esp32_runtime.storage.os.replace") as replace:
                with self.assertRaises(StorageIOError) as caught:
                    backend.write_atomic("counter", "record", b"new")
            replace.assert_not_called()
            self.assertFalse(caught.exception.commit_uncertain)
            self.assertEqual(backend.read("counter", "record"), b"old")

    def test_directory_fsync_failure_is_explicitly_uncertain(self):
        with tempfile.TemporaryDirectory() as root:
            backend = FileBackend(root)
            backend.write_atomic("counter", "record", b"old")
            with patch.object(backend, "_sync_directory", side_effect=OSError("injected dir fsync")):
                with self.assertRaises(StorageIOError) as caught:
                    backend.write_atomic("counter", "record", b"new")
            self.assertTrue(caught.exception.commit_uncertain)
            self.assertEqual(backend.read("counter", "record"), b"new")

    def test_backend_capacity_delete_and_path_restrictions(self):
        with tempfile.TemporaryDirectory() as root:
            backend = FileBackend(root, max_bytes=256)
            with self.assertRaises(TooLargeError):
                backend.write_atomic("counter", "record", b"x" * 257)
            (Path(root) / "counter").mkdir()
            (Path(root) / "counter" / "oversized").write_bytes(b"x" * 257)
            with self.assertRaises(TooLargeError):
                backend.read("counter", "oversized")
            backend.write_atomic("counter", "record", b"ok")
            backend.delete("counter", "record")
            self.assertIsNone(backend.read("counter", "record"))
            for namespace, key in (("../outside", "record"), ("counter", "../outside")):
                with self.assertRaises(ValueError):
                    backend.read(namespace, key)

    def test_namespace_and_key_symlinks_are_not_followed(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            backend = FileBackend(root)
            (Path(root) / "counter").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(StorageIOError):
                backend.write_atomic("counter", "record", b"data")
            (Path(root) / "counter").unlink()
            (Path(root) / "counter").mkdir()
            private = Path(outside) / "private"
            private.write_bytes(b"private")
            (Path(root) / "counter" / "record").symlink_to(private)
            with self.assertRaises(StorageIOError):
                backend.read("counter", "record")
            self.assertEqual(private.read_bytes(), b"private")


if __name__ == "__main__":
    unittest.main()
