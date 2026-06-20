# Zotrian

Export Zotero papers and annotations into Obsidian notes.

## Run

Use `uv` so the project runs in the pinned environment:

```bash
UV_CACHE_DIR=/tmp/uvcache uv run python export.py
```

Useful variants:

```bash
UV_CACHE_DIR=/tmp/uvcache uv run python export.py --paper "How Many Elements Matter?"
```

Notes are written into:

- `Papers/` for paper notes
- `Concepts/` for purple-highlight concept notes

## Config

The default config file is `zotrian.json`:

```json
{
  "vault_path": "/home/ardo/mlem/Vaults/Thesis/thesis_vault/Summaries",
  "zotero_db_path": "/home/ardo/Zotero/zotero.sqlite",
  "watch_interval_seconds": 5
}
```

## Watch

Run in watch mode to keep the Obsidian notes updated when Zotero changes:

```bash
UV_CACHE_DIR=/tmp/uvcache uv run python export.py --watch
```

You can override the config file with `--config` or the vault path with `--vault`.
