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
uv run zotrian convert-ai --paper "How Many Elements Matter?"
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
  "ai": {
    "enabled": false,
    "provider": "gemini",
    "model": "gemini-2.5-flash-lite",
    "api_key_env": "GEMINI_API_KEY",
    "batch_size": 20,
    "max_output_tokens": 2048,
    "temperature": 0.2,
    "request_timeout_seconds": 45
  },
  "state_path": ".zotrian-state.json"
}
```

Path overrides are also available at the CLI:

- `--config`
- `--vault`
- `--db`
- `--storage`
- `--ai`
- `--no-ai`

## AI Cleaning

Zotrian can optionally rewrite extracted annotations into cleaner notes using Gemini.

- The deterministic PDF parsing and section placement stay the same.
- Only note content is rewritten.
- Results are cached per annotation key and prompt signature, so repeated syncs only re-send changed annotations.
- When AI mode is enabled, annotation blocks are regenerated from AI output instead of preserving previous per-annotation note edits.

Set an API key before using AI mode:

```bash
export GEMINI_API_KEY=your_key_here
```

Enable AI mode in either place:

- Config: set `"ai.enabled": true`
- CLI: pass `--ai`
- Convenience commands: `convert-ai` and `watch-ai`

## Commands

Convert notes once:

```bash
uv run zotrian convert --paper "The most metal poor stars"
```

Convert only one matching paper:

```bash
uv run zotrian convert --paper "The most metal poor stars"
uv run zotrian convert --paper "The most metal poor stars" --ai
uv run zotrian convert-ai --paper "The most metal poor stars"
```

Watch Zotero for annotation/database changes:

```bash
uv run zotrian watch --paper "The most metal poor stars"
uv run zotrian watch --paper "The most metal poor stars" --ai
uv run zotrian watch-ai --paper "The most metal poor stars"
```

If `--paper` is omitted, Zotrian exits without converting the full library.

If `watchdog` is unavailable, Zotrian falls back to polling the Zotero database files.

## Output

Each paper note is named from the paper title and includes:

- YAML frontmatter for title, authors, year, DOI, citekey, type, and tags
- `Abstract`, `Open Questions`, `Connections To Other Papers`, `Thesis Relevance`, and `Thesis Notes` sections
- color-aware rendering for quotes, warnings, equations, and definitions, with blue annotations embedded from Zotero's cache library
