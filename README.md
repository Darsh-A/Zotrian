# Zotrian

Export Zotero papers and annotations into Obsidian notes from a proper terminal CLI.

## What It Does

- Reads paper metadata, PDF attachments, and annotations directly from Zotero.
- Converts annotations into Obsidian markdown notes using the structure described in `DIRECTION.md`.
- Writes paper notes by paper title into your Obsidian summaries folder.
- Supports incremental syncs and a live watch mode.

## Zotero Layout

The current Zotero installation stores:

- the library database at `~/Zotero/zotero.sqlite`
- attached PDFs at `~/Zotero/storage/`
- profile/app data at `~/.zotero/zotero/npal5o2e.default/`

The exporter uses the Zotero database, storage directory, and cache library for papers and annotations.

## Install / Run

Use `uv` so the project runs in the pinned environment:

```bash
uv run zotrian convert --paper "How Many Elements Matter?"
```

Useful variants:

```bash
uv run zotrian convert --paper "How Many Elements Matter?"
uv run zotrian convert --config zotrian.json
uv run zotrian convert --vault /path/to/vault
```

You can also run it as a module:

```bash
python -m zotrian convert --paper "How Many Elements Matter?"
```

Notes are written into the configured Obsidian vault:

- paper notes into `Summaries/`


## Config

The default config file is `zotrian.json`:

```json
{
  "zotero": {
    "database_path": "~/Zotero/zotero.sqlite",
    "storage_path": "~/Zotero/storage"
  },
  "obsidian": {
    "vault_path": "~/mlem/Vaults/Thesis/thesis_vault",
    "paper_notes_dir": "Summaries"
  },
  "watch": {
    "interval_seconds": 5,
    "debounce_seconds": 2
  },
  "state_path": ".zotrian-state.json"
}
```

Path overrides are also available at the CLI:

- `--config`
- `--vault`
- `--db`
- `--storage`

## Commands

Convert notes once:

```bash
uv run zotrian convert --paper "The most metal poor stars"
```

Convert only one matching paper:

```bash
uv run zotrian convert --paper "The most metal poor stars"
```

Watch Zotero for annotation/database changes:

```bash
uv run zotrian watch --paper "The most metal poor stars"
```

If `--paper` is omitted, Zotrian exits without converting the full library.

If `watchdog` is unavailable, Zotrian falls back to polling the Zotero database files.

## Output

Each paper note is named from the paper title and includes:

- YAML frontmatter for title, authors, year, DOI, citekey, type, and tags
- `Abstract`, `Open Questions`, `Connections To Other Papers`, `Thesis Relevance`, and `Thesis Notes` sections
- color-aware rendering for quotes, warnings, equations, and definitions, with blue annotations embedded from Zotero's cache library
