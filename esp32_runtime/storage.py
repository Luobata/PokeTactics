"""Bounded JSON records, independent game codecs, and recoverable dual-slot writes.

This is a host reference, not an ESP-IDF driver. A backend must preserve the old
value until an atomic replacement commits. SaveStore serializes one instance;
applications must serialize all writers of the same namespace/slot. No game
objects, executable code, Python type names, or pickle are stored.
"""

from __future__ import annotations

import hashlib
import hmac
import copy
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

T = TypeVar("T")
STORAGE_VERSION = 1
MAX_SEQUENCE = (1 << 63) - 1
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}\Z")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_FIELDS = {"game_id", "storage_version", "schema_version", "sequence", "payload", "checksum"}
_UNSET = object()


class SaveError(Exception):
    """A failed operation never authorizes treating a slot as a new game."""


class NoSaveError(SaveError):
    """Both data slots are absent, rather than unreadable or invalid."""


class CorruptSaveError(SaveError):
    """Existing bytes cannot be verified or decoded."""


class UnsupportedVersionError(SaveError):
    """The record requires a storage/schema version this runtime cannot decode."""


class GameMismatchError(SaveError):
    """A verified record belongs to a different game."""


class InvalidStateError(SaveError):
    """The game codec rejected the supplied state or payload."""


class TooLargeError(SaveError):
    """The complete serialized record exceeds the configured capacity."""


class StorageIOError(SaveError):
    """Backend I/O failed; old data must be preserved, not treated as absent.

    commit_uncertain means an atomic rename happened but its directory fsync
    failed, or cleanup after a backend error could not be confirmed. Reload or
    inspect the checkpoint before retrying; do not claim that nothing changed.
    """

    def __init__(self, message, *, commit_uncertain=False):
        super().__init__(message)
        self.commit_uncertain = commit_uncertain


class GameCodec(Protocol[T]):
    game_id: str
    schema_version: int

    def encode(self, state: T) -> Any:
        """Return a bounded JSON tree; do not mutate state."""
        ...

    def decode(self, payload: Any, schema_version: int) -> T:
        """Validate/migrate in isolation; return state without publishing it."""
        ...


class StorageBackend(Protocol):
    def read(self, namespace: str, key: str) -> bytes | None:
        """None means absent only. Permission/I/O errors must raise."""
        ...

    def write_atomic(self, namespace: str, key: str, data: bytes) -> None:
        """Durably replace one key; incomplete writes must not alter old bytes."""
        ...

    def delete(self, namespace: str, key: str) -> None:
        """Delete one key; absent is a no-op, I/O failure must raise."""
        ...


def _name(value, label, pattern=_NAME):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"invalid {label}: use bounded ASCII letters, digits, '_' or '-'")
    return value


def _capacity(value):
    if type(value) is not int or value < 256:
        raise ValueError("max_bytes must be an integer of at least 256")
    return value


class FileBackend:
    """POSIX host backend: same-directory temp, file fsync, rename, dir fsync.

    No dependencies and no implicit installation. Existing symlinks are refused.
    Use a private application directory, not an attacker-writable shared folder.
    """

    def __init__(self, root, *, max_bytes=1024 * 1024):
        self.root = Path(root).expanduser().resolve()
        self.max_bytes = _capacity(max_bytes)
        missing = []
        ancestor = self.root
        while not ancestor.exists():
            missing.append(ancestor)
            ancestor = ancestor.parent
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            for created in reversed(missing):
                self._sync_directory(created.parent)
        except OSError as exc:
            raise StorageIOError(f"storage directory creation failed: {exc}") from exc

    def _path(self, namespace, key, *, create=False):
        _name(namespace, "namespace")
        _name(key, "key", _KEY)
        directory = self.root / namespace
        if directory.is_symlink():
            raise StorageIOError("namespace must not be a symlink")
        if create:
            directory.mkdir(exist_ok=True)
        path = directory / key
        if path.is_symlink():
            raise StorageIOError("storage key must not be a symlink")
        return path

    def read(self, namespace, key):
        try:
            path = self._path(namespace, key)
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise StorageIOError("storage key is not a regular file")
                if info.st_size > self.max_bytes:
                    raise TooLargeError("backend record exceeds capacity")
                data = stream.read(self.max_bytes + 1)
                if len(data) > self.max_bytes:
                    raise TooLargeError("backend record exceeds capacity")
                return data
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StorageIOError(f"read failed: {exc}") from exc

    @staticmethod
    def _sync_directory(directory):
        fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def write_atomic(self, namespace, key, data):
        if not isinstance(data, bytes):
            raise TypeError("backend data must be bytes")
        if len(data) > self.max_bytes:
            raise TooLargeError("backend record exceeds capacity")
        temporary, replaced = None, False
        try:
            path = self._path(namespace, key, create=True)
            fd, temporary = tempfile.mkstemp(prefix=".save-", dir=path.parent)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            replaced, temporary = True, None
            self._sync_directory(path.parent)
            self._sync_directory(self.root)
        except OSError as exc:
            raise StorageIOError(f"atomic write failed: {exc}", commit_uncertain=replaced) from exc
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    # A leftover uncommitted temp file is never a save record.
                    pass

    def delete(self, namespace, key):
        try:
            path = self._path(namespace, key)
            path.unlink(missing_ok=True)
            if path.parent.exists():
                self._sync_directory(path.parent)
        except OSError as exc:
            raise StorageIOError(f"delete failed: {exc}") from exc


def _json_tree(value, depth=0):
    if depth > 64:
        raise InvalidStateError("JSON payload nesting exceeds 64")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _json_tree(item, depth + 1)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _json_tree(item, depth + 1)
        return
    raise InvalidStateError("payload must contain only finite JSON values and string keys")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


@dataclass(frozen=True)
class SaveInfo:
    sequence: int
    schema_version: int
    slot_index: int


@dataclass(frozen=True)
class LoadedSave(Generic[T]):
    state: T
    sequence: int
    schema_version: int
    recovered: bool = False
    migrated: bool = False
    warnings: tuple[str, ...] = ()


@dataclass
class _Record(Generic[T]):
    body: dict
    raw: bytes
    state: T
    index: int = -1


class SaveStore(Generic[T]):
    """A/B records selected by verified sequence; bad newer slot falls back.

    Unknown newer schemas and I/O errors block writes. Game migrations are
    read-only until an explicit save. A persisted checkpoint precedes import.
    """

    def __init__(self, backend: StorageBackend, codec: GameCodec[T], *,
                 namespace=None, slot="autosave", max_bytes=512 * 1024):
        self.backend, self.codec = backend, codec
        self.game_id = _name(codec.game_id, "game_id")
        self.namespace = _name(namespace if namespace is not None else self.game_id, "namespace")
        self.slot = _name(slot, "slot")
        if type(codec.schema_version) is not int or codec.schema_version < 1:
            raise ValueError("schema_version must be a positive integer")
        self.max_bytes = _capacity(max_bytes)
        self._lock = threading.RLock()

    def _key(self, index):
        return f"{self.slot}.{index}"

    def _read(self, key):
        try:
            return self.backend.read(self.namespace, key)
        except OSError as exc:
            raise StorageIOError(f"read failed: {exc}") from exc

    def _decode_state(self, payload, version):
        try:
            return self.codec.decode(copy.deepcopy(payload), version)
        except SaveError:
            raise
        except Exception as exc:
            raise InvalidStateError(f"game codec rejected payload: {exc}") from exc

    def _parse(self, raw):
        if not isinstance(raw, bytes):
            raise CorruptSaveError("record must be bytes")
        if len(raw) > self.max_bytes:
            raise TooLargeError("record exceeds capacity")
        try:
            body = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            if type(body) is not dict or set(body) != _FIELDS:
                raise ValueError("invalid envelope fields")
            for name in ("storage_version", "schema_version", "sequence"):
                if type(body[name]) is not int or not 1 <= body[name] <= MAX_SEQUENCE:
                    raise ValueError(f"invalid {name}")
            if not isinstance(body["game_id"], str):
                raise ValueError("invalid game_id")
            checksum = body["checksum"]
            if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
                raise ValueError("invalid checksum")
            _json_tree(body["payload"])
            expected = hashlib.sha256(_canonical({k: v for k, v in body.items() if k != "checksum"})).hexdigest()
            if not hmac.compare_digest(checksum, expected):
                raise ValueError("checksum mismatch")
        except (ValueError, TypeError, UnicodeError, RecursionError, InvalidStateError) as exc:
            raise CorruptSaveError(f"invalid save record: {exc}") from exc
        return body

    def _record(self, raw, index=-1):
        body = self._parse(raw)
        if body["game_id"] != self.game_id:
            raise GameMismatchError(f"expected game {self.game_id}, got {body['game_id']}")
        if body["storage_version"] != STORAGE_VERSION or body["schema_version"] > self.codec.schema_version:
            raise UnsupportedVersionError("save uses an unsupported storage or game schema version")
        state = self._decode_state(body["payload"], body["schema_version"])
        return _Record(body, raw, state, index)

    def _scan(self):
        records, errors, unsupported, present = [], [], [], False
        for index in (0, 1):
            try:
                raw = self._read(self._key(index))
                if raw is None:
                    continue
                present = True
                records.append(self._record(raw, index))
            except UnsupportedVersionError as exc:
                unsupported.append((self._parse(raw)["sequence"], exc))
            except (CorruptSaveError, InvalidStateError, TooLargeError) as exc:
                present = True
                errors.append(f"slot {index}: {exc}")
        best = max(records, key=lambda r: r.body["sequence"], default=None)
        # A verified unknown schema may carry semantics this runtime cannot
        # interpret. Do not overwrite it even if another slot has a higher
        # sequence; sequence is not a compatibility override.
        if unsupported:
            raise max(unsupported, key=lambda x: x[0])[1]
        if best is None:
            if present:
                raise CorruptSaveError("no valid save slot; " + "; ".join(errors))
            raise NoSaveError("no save exists")
        if len(records) == 2 and records[0].body["sequence"] == records[1].body["sequence"] and records[0].body != records[1].body:
            raise CorruptSaveError("conflicting records have the same sequence")
        return best, tuple(errors)

    def _loaded(self, record, warnings=()):
        return LoadedSave(record.state, record.body["sequence"], record.body["schema_version"],
                          bool(warnings), record.body["schema_version"] < self.codec.schema_version,
                          tuple(warnings))

    def load(self):
        with self._lock:
            record, warnings = self._scan()
            return self._loaded(record, warnings)

    def _encode(self, state, sequence):
        if sequence > MAX_SEQUENCE:
            raise SaveError("save sequence exhausted")
        try:
            payload = self.codec.encode(state)
            _json_tree(payload)
            body = {"game_id": self.game_id, "storage_version": STORAGE_VERSION,
                    "schema_version": self.codec.schema_version, "sequence": sequence, "payload": payload}
            body["checksum"] = hashlib.sha256(_canonical(body)).hexdigest()
            raw = _canonical(body)
        except SaveError:
            raise
        except Exception as exc:
            raise InvalidStateError(f"game codec could not encode state: {exc}") from exc
        return self._record(raw)

    def _write_verified(self, key, record, *, rollback_key=False):
        try:
            self.backend.write_atomic(self.namespace, key, record.raw)
            if self._read(key) != record.raw:
                raise StorageIOError("written record failed readback verification")
        except (OSError, SaveError) as exc:
            # Only the inactive data slot may be removed. The prior current slot
            # and import checkpoint remain untouched even after a torn write.
            uncertain = getattr(exc, "commit_uncertain", False)
            if rollback_key:
                try:
                    self.backend.delete(self.namespace, key)
                except (OSError, SaveError):
                    uncertain = True
            if isinstance(exc, TooLargeError):
                raise
            raise StorageIOError(f"save write failed: {exc}", commit_uncertain=uncertain) from exc

    def save(self, state):
        with self._lock:
            try:
                current, _ = self._scan()
            except NoSaveError:
                current = None
            sequence = current.body["sequence"] + 1 if current else 1
            index = 1 - current.index if current else 0
            record = self._encode(state, sequence)
            self._write_verified(self._key(index), record, rollback_key=True)
            return SaveInfo(sequence, self.codec.schema_version, index)

    def export_backup(self):
        with self._lock:
            return self._scan()[0].raw

    def inspect_backup(self, data):
        """The exact startup integrity/schema/codec validation, without writes."""
        with self._lock:
            return self._loaded(self._record(data))

    def import_backup(self, data, *, checkpoint_state=_UNSET):
        with self._lock:
            incoming = self._record(data)  # Validate before any mutation.
            try:
                current, _ = self._scan()
            except NoSaveError:
                current = None
            sequence = current.body["sequence"] + 1 if current else 1
            # Re-encode migrations at the current schema, with a local sequence.
            imported = self._encode(incoming.state, sequence)
            checkpoint = (self._encode(checkpoint_state, max(1, sequence - 1))
                          if checkpoint_state is not _UNSET else current)
            if checkpoint is not None:
                self._write_verified(self._key("checkpoint"), checkpoint)
            index = 1 - current.index if current else 0
            self._write_verified(self._key(index), imported, rollback_key=True)
            return self._loaded(imported)

    def export_checkpoint(self):
        with self._lock:
            raw = self._read(self._key("checkpoint"))
            if raw is None:
                raise NoSaveError("no import checkpoint exists")
            return self._record(raw).raw
