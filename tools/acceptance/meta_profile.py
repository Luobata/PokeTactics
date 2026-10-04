"""Trainer profile codec and storage adapter using the shared save runtime."""

from esp32_runtime import FileBackend, NoSaveError, SaveStore, UnsupportedVersionError
from sim.metagame import initial_profile, validate_profile

# 2048 fully populated run ledgers with uint16 species ids require over 5 MiB.
# Both the backend and envelope enforce the bound so every valid ledger fits.
MAX_PROFILE_BYTES = 8 * 1024 * 1024


class ProfileCodec:
    game_id = "poketactics-meta"
    schema_version = 1

    def encode(self, profile):
        return validate_profile(profile)

    def decode(self, payload, schema_version):
        if type(schema_version) is not int or schema_version != self.schema_version:
            raise UnsupportedVersionError("不支持的 PokeTactics 局外档案版本")
        return validate_profile(payload)


class ProfileStore:
    """Persist an independent trainer slot; only a missing slot creates a profile.

    Corruption, unknown versions and I/O failures are intentionally propagated.
    The shared runtime supplies checksum checks, atomic A/B writes, fallback to
    a verified older slot and a checkpoint before replacing an imported profile.
    Callers must serialize all writers to a shared root, just as for game saves.
    """

    def __init__(self, root):
        self.store = SaveStore(FileBackend(root, max_bytes=MAX_PROFILE_BYTES), ProfileCodec(),
                               namespace="poketactics-meta", slot="trainer",
                               max_bytes=MAX_PROFILE_BYTES)
        self.last_loaded = None

    def load(self):
        try:
            self.last_loaded = self.store.load()
        except NoSaveError:
            self.store.save(initial_profile())
            self.last_loaded = self.store.load()
        return self.last_loaded.state

    def save(self, profile):
        return self.store.save(profile)

    def export_backup(self):
        self.load()
        return self.store.export_backup()

    def inspect_backup(self, raw):
        return self.store.inspect_backup(raw).state

    def import_backup(self, raw):
        self.last_loaded = self.store.import_backup(raw)
        return self.last_loaded.state
