from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _resolve_path(raw_value: str | None, base_dir: Path) -> Path | None:
    if not raw_value:
        return None
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _discover_zotero_database() -> Path | None:
    candidates = [
        Path("~/Zotero/zotero.sqlite").expanduser(),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _discover_zotero_storage(db_path: Path | None) -> Path | None:
    if db_path:
        storage_path = db_path.parent / "storage"
        if storage_path.exists():
            return storage_path

    profile_root = Path("~/.zotero/zotero").expanduser()
    if not profile_root.exists():
        return None

    for candidate in sorted(profile_root.glob("*.default*/storage")):
        if candidate.exists():
            return candidate
    return None


@dataclass(slots=True)
class ZoteroSettings:
    database_path: Path
    storage_path: Path


@dataclass(slots=True)
class ObsidianSettings:
    vault_path: Path
    paper_notes_dir: str

    @property
    def paper_notes_path(self) -> Path:
        return self.vault_path / self.paper_notes_dir


@dataclass(slots=True)
class WatchSettings:
    interval_seconds: int = 5
    debounce_seconds: int = 2


@dataclass(slots=True)
class AppConfig:
    zotero: ZoteroSettings
    obsidian: ObsidianSettings
    watch: WatchSettings
    state_path: Path
    config_path: Path

    @property
    def watch_root(self) -> Path:
        return self.zotero.database_path.parent


def _normalize_legacy_config(raw: dict[str, Any]) -> dict[str, Any]:
    if "zotero" in raw or "obsidian" in raw:
        return raw

    return {
        "zotero": {
            "database_path": raw.get("zotero_db_path"),
            "storage_path": raw.get("zotero_storage_path"),
        },
        "obsidian": {
            "vault_path": raw.get("vault_path"),
            "paper_notes_dir": raw.get("paper_notes_dir", "Summaries"),
        },
        "watch": {
            "interval_seconds": raw.get("watch_interval_seconds", 5),
            "debounce_seconds": raw.get("watch_debounce_seconds", 2),
        },
        "state_path": raw.get("state_path", ".zotrian-state.json"),
    }


def load_config(config_path: Path) -> AppConfig:
    base_dir = config_path.expanduser().resolve().parent
    raw: dict[str, Any] = {}
    if config_path.exists():
        raw = json.loads(config_path.read_text())

    normalized = _normalize_legacy_config(raw)
    zotero_raw = normalized.get("zotero", {})
    obsidian_raw = normalized.get("obsidian", {})
    watch_raw = normalized.get("watch", {})

    database_path = _resolve_path(zotero_raw.get("database_path"), base_dir) or _discover_zotero_database()
    if database_path is None:
        raise FileNotFoundError(
            "Could not determine the Zotero database path. Set zotero.database_path in the config file or pass --db."
        )

    storage_path = _resolve_path(zotero_raw.get("storage_path"), base_dir) or _discover_zotero_storage(database_path)
    if storage_path is None:
        raise FileNotFoundError(
            "Could not determine the Zotero storage path. Set zotero.storage_path in the config file or pass --storage."
        )

    vault_path = _resolve_path(obsidian_raw.get("vault_path"), base_dir)
    if vault_path is None:
        raise FileNotFoundError(
            "Could not determine the Obsidian vault path. Set obsidian.vault_path in the config file or pass --vault."
        )

    state_path = _resolve_path(normalized.get("state_path", ".zotrian-state.json"), base_dir)
    if state_path is None:
        state_path = vault_path / ".zotrian-state.json"

    return AppConfig(
        zotero=ZoteroSettings(
            database_path=database_path,
            storage_path=storage_path,
        ),
        obsidian=ObsidianSettings(
            vault_path=vault_path,
            paper_notes_dir=obsidian_raw.get("paper_notes_dir", "Summaries"),
        ),
        watch=WatchSettings(
            interval_seconds=int(watch_raw.get("interval_seconds", 5)),
            debounce_seconds=int(watch_raw.get("debounce_seconds", 2)),
        ),
        state_path=state_path,
        config_path=config_path.expanduser().resolve(),
    )
