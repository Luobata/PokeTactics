# Portable runtime reference

This package contains no Pokemon rules or state. Python on the host implements
the reference storage contract; an ESP-IDF NVS backend is **pending**. The
reference JSON files are not PokeWalk NVS blobs or `.pksave` backups.

```python
from esp32_runtime import FileBackend, SaveStore, NoSaveError

store = SaveStore(FileBackend(".build/saves"), game_codec,
                  namespace="my_game", slot="autosave", max_bytes=512 * 1024)
store.save(game_state)
loaded = store.load()                 # loaded.state, sequence, recovered, migrated
backup = store.export_backup()       # bytes of the persisted record
candidate = store.inspect_backup(backup)  # validates without writing
restored = store.import_backup(backup, checkpoint_state=game_state)
previous = store.export_checkpoint() # downloadable, validated pre-import record
```

`GameCodec` supplies `game_id`, the current positive `schema_version`,
`encode(state)` returning a JSON tree, and `decode(payload, schema_version)`.
The decoder must validate the complete game state, explicitly migrate supported
older shapes, and create isolated state without modifying a live game or
granting rewards. A successful import returns state for the caller to publish;
the runtime never publishes a game session. Loading a migrated record does not
write it back. New fields need explicit defaults and migration fixtures.

The exact envelope contains `game_id`, `storage_version` (currently 1),
`schema_version`, positive `sequence`, `payload`, and `checksum`. The checksum
is lowercase SHA-256 of the other five fields serialized as UTF-8 JSON with
sorted keys, no extra whitespace, literal Unicode, and no non-finite numbers.
SHA detects corruption, not a malicious author's forgery. No pickle, executable
type restoration, device-specific pointers, or build-hash compatibility check
is used. A game may carry build provenance inside its validated payload.

Each logical slot has `.0` and `.1` keys. The highest verified sequence wins;
a damaged slot may fall back to its healthy peer, surfaced as `recovered=True`
and warnings. A checksum-valid unsupported schema or storage version in either
slot blocks load and overwrite, regardless of its sequence. Equal sequences
with different contents are errors.
The whole envelope has a configurable byte limit, and JSON nesting is bounded.
Namespace/slot names accept 1–32 ASCII letters/digits/underscores/hyphens, with
an alphanumeric first character. Game IDs use the same rule.

Callers must handle distinct outcomes:

- `NoSaveError`: both data slots are absent; creating the first save is allowed.
- `CorruptSaveError`: bytes exist, but neither slot validates; preserve them.
- `UnsupportedVersionError`: a newer format is present; preserve it.
- `GameMismatchError`: a valid envelope belongs to another game.
- `StorageIOError`: read/write permission, device or readback failure; never
  interpret it as no save.
- `InvalidStateError` / `TooLargeError`: the codec or capacity rejected input.

Import validates the envelope and game payload before any write. It then writes
and reads back `.checkpoint` (the supplied in-memory state, or the currently
persisted save), before writing and reading back the inactive data slot with a
new local sequence. Invalid input and failed checkpoints cannot replace current
data. A failed data write removes the inactive candidate when possible; the
previous current slot and checkpoint remain available. If cleanup cannot be
confirmed, `StorageIOError.commit_uncertain` is true: reload/reconcile or recover
the checkpoint instead of blindly retrying or claiming that no write occurred.
Checkpoint is local storage, not a USB/computer backup acknowledgment protocol.

`StorageBackend` requires bounded `read(namespace, key) -> bytes | None`, atomic
`write_atomic(namespace, key, bytes)`, and `delete(namespace, key)`. Only absence
may return `None`; all I/O failures must raise. `FileBackend` uses a temporary
file in the same directory, file fsync, atomic rename, and directory fsync. A
rename followed by a failed directory fsync is explicitly reported as an
uncertain commit. Use a private directory; namespace/key symlinks are refused.
One `SaveStore` serializes its own operations. Applications must serialize all
writers sharing the same namespace/slot, including multiple store instances or
processes; this reference does not provide a cross-process lock.

The game owns when to save. Persist irreversible player actions or a stable
phase transition before reporting durable completion; do not save a partially
applied transaction or mutate a live session while encoding it. Autosave
scheduling, USB transport, device identity, NVS layout, flash wear/latency,
firmware upgrade preservation, and power-cut tests on physical hardware remain
integration work. Host success does not claim those checks passed.

Run the independent storage contract tests:

```sh
python3 -m unittest discover -s tests -p test_runtime_storage.py -v
```

`animation.py` provides a game-independent 2D track validator and pure integer
pose sampler. It has no Pillow, battle state, species IDs or frame timer. Tracks
contain normalized time, displacement, rotation, scale and discrete visibility;
seek order cannot affect the sampled result. Validate authored data once before
publishing it. Character structure, sprite cuts and skill choreography stay in
the game's content/rendering modules. C sampling and a device drawing backend
remain pending; Python's ties-to-even rounding is part of the reference contract.

```python
from esp32_runtime.animation import validate_track, sample_track

track = [[0, 0, 0, 0, 100, 100, 1], [1, -4, -2, 30, 110, 100, 1]]
validate_track(track)
pose = sample_track(track, .5)
```
