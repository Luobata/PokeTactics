"""Game-independent reference storage; ESP32 NVS backend is not implemented."""

from .storage import (
    CorruptSaveError, FileBackend, GameCodec, GameMismatchError, InvalidStateError,
    LoadedSave, NoSaveError, SaveError, SaveInfo, SaveStore, StorageBackend,
    StorageIOError, TooLargeError, UnsupportedVersionError,
)

__all__ = [
    "CorruptSaveError", "FileBackend", "GameCodec", "GameMismatchError",
    "InvalidStateError", "LoadedSave", "NoSaveError", "SaveError", "SaveInfo",
    "SaveStore", "StorageBackend", "StorageIOError", "TooLargeError",
    "UnsupportedVersionError",
]
