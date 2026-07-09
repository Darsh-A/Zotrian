# Zotrian — Structure & Architecture

> Local-first tool that converts Zotero papers and annotations into structured Obsidian Markdown notes.

## Directory Layout

```
Zotrian/
├── zotrian.json           # User configuration (paths, watch settings)
├── .zotrian-state.json    # Incremental sync cache (hashes, timestamps, note paths)
├── pyproject.toml         # Python project metadata & dependencies
├── DIRECTION.md           # Design specification / roadmap
├── STRUCTURE.md           # This file
└── zotrian/
    ├── __init__.py        # Package entry; re-exports cli.main
    ├── __main__.py        # `python -m zotrian` entry
    ├── cli.py             # CLI argument parsing: `convert` and `watch` subcommands
    ├── config.py          # AppConfig dataclass & config loading (~ expansion, discovery)
    ├── exporter.py        # Core engine: annotation processing, section assignment, note rendering
    ├── latex_cleaner.py   # Unicode→LaTeX math symbol normalization
    ├── note_merger.py     # Preserve user-editable note sections across re-exports
    ├── pdf_parser.py      # PDF TOC extraction & fallback heading detection (PyMuPDF/fitz)
    └── zotero_db.py       # Read-only SQLite access to Zotero database
```

## Data Flow

```
Zotero DB (read-only SQLite)
       │
       ▼
zotero_db.py         ──  fetches papers, metadata, PDF paths, annotations
       │
       ▼
pdf_parser.py        ──  opens PDF with fitz, extracts TOC / fallback headings
       │
       ▼
exporter.py          ──  assigns annotations to sections, renders Markdown
       │                    ├── latex_cleaner.py  (Unicode→LaTeX normalization)
       │                    └── note_merger.py    (preserve user edits)
       ▼
Obsidian vault       ──  writes `.md` notes
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `zotrian convert --paper "<title>"` | One-shot export of a paper's annotations |
| `zotrian watch --paper "<title>"` | Live watcher: continuously syncs annotations as they change |

Common flags: `--config`, `--vault`, `--db`, `--storage`

## Annotation Color System

Colors map Zotero highlight colors to semantic meaning. The COLOR_MAP in `exporter.py`:

| Hex | Name | Role | Rendered As |
|-----|------|------|-------------|
| `#a28ae5` | Purple | Definition/reusable concept | `#### [[Concept Name]]` wikilink heading |
| `#ffd400` | Yellow | General note | Plain text |
| `#5fb236` | Green | Quote | `> quoted text` blockquote |
| `#ff6666` | Red | Warning/caveat | `> [!danger]` Obsidian callout |
| `#2ea8e5` | Blue | Equation/binding box | `![Blue annotation](image.png)` or `$$...$$` |
| `#e56eee` | Magenta | **H2 section heading** | `<h2 style="color: magenta;">Heading</h2>` |
| `#f19837` | Orange | **H3 sub-section heading** | `<h3 style="color: orange;">Heading</h3>` |
| `#aaaaaa` | Gray | **H4 sub-sub-section heading** | `<h4 style="color: gray;">Heading</h4>` |

### Heading Annotation Workflow (for PDFs without TOCs)

When a PDF lacks a proper table of contents (< 2 TOC entries):
1. The user manually highlights section headings with Magenta (H1-level), Orange (H2-level), or Gray (H3-level)
2. These heading annotations are separated from content annotations
3. Heading annotations define section boundaries; content is assigned to the nearest preceding heading
4. Heading annotations render as colored HTML headings in the output
5. When a PDF DOES have a usable TOC, TOC is used for section assignment and heading annotations only add color

## Note Output Template

```markdown
---
title: "..."
authors: [...]
year: "..."
doi: "..."
citekey: "..."
paper_type: "..."
tags: [...]
---

# Paper Title

---
## Open Questions
(user content — preserved across re-exports)

## Connections To Other Papers
(user content — preserved across re-exports)

## Thesis Relevance
(user content — preserved across re-exports)
---

## Thesis Notes

<h2 style="color: magenta;">Section Heading</h2>

<!-- zt:325 -->
Some yellow annotation text

<!-- zt:328 -->
> [!danger]
> The much weaker Fe lines...

<h3 style="color: orange;">Sub-section Heading</h3>

<!-- zt:333 -->
More annotations...
```

## Key Classes

### `Exporter` (exporter.py)
Orchestrates the entire export pipeline. Key methods:
- `run()` / `refresh()` — iterate papers and export
- `export_one()` — process a single paper: split annotations, assign sections, re-extract text, render note, handle change detection
- `_assign_sections_from_headings()` — sequential section assignment from colored heading annotations
- `annotation_section()` — delegates to PDFParser for TOC-based section assignment
- `digest_for_paper()` — SHA-256 content fingerprinting for incremental sync
- `load_parser()` — lazy-load PDFParser with graceful error handling

### `NoteRenderer` (exporter.py)
Generates the Markdown note. Key methods:
- `render_paper()` — assembles full note with frontmatter, user sections, and annotation groups
- `render_annotation()` — color-specific annotation rendering
- `render_colored_heading()` — HTML heading with color style for heading annotations
- `render_frontmatter()` — Dataview-compatible YAML frontmatter

### `PDFParser` (pdf_parser.py)
Two-tier section detection:
1. **Primary**: PDF's built-in Table of Contents via `fitz.Document.get_toc()`
2. **Fallback**: Font-size-based heuristic heading detection (samples 5 pages, finds text with font size > median × 1.1 or bold + matching heading patterns)
- `get_section_for_annotation()` — finds the section containing a given annotation position
- Raises `NoHeadingsDetectedError` when neither strategy finds headings

### `ZoteroDB` (zotero_db.py)
Read-only SQLite access with retry logic (5 attempts for database lock). Key methods:
- `get_papers()` — fetches all papers with metadata, tags, PDF paths, and annotations
- `get_annotations()` — queries `itemAnnotations` table, also checks cache for equation images
- `get_pdf_attachment()` — resolves `storage:` URIs to filesystem paths

### `SyncState` (exporter.py)
Manages `.zotrian-state.json`. Tracks per-paper: `hash` (content fingerprint), `note_path`, `note_title`, `updated_at`, `concepts`.

## Incremental Sync

Change detection via SHA-256 hash of a canonical JSON payload containing:
- `render_version` (version bump forces full re-export)
- Paper key, title, dateModified, citekey, PDF path, outline, all annotations

If the hash matches the previous run's stored hash, the paper is skipped entirely.

## Note Preservation

Three template sections are preserved across re-exports:
- `## Open Questions`
- `## Connections To Other Papers`
- `## Thesis Relevance`

The `note_merger.py` module reads the existing note before overwriting, extracts content from these sections, and injects it into the new output.

### Annotation-Level Preservation

Each annotation is wrapped with an invisible marker (`<!-- zt:ITEMID -->`) that ties it to its Zotero item ID. On re-export:

1. The existing note is parsed to extract preserved annotation content keyed by Zotero item ID
2. For each Zotero annotation: if its ID exists in the existing note, the preserved content (with user edits) is used instead of a fresh render
3. New annotations (IDs not in the existing note) get freshly rendered with new markers
4. The entire note is regenerated, but user edits to existing annotations survive

The marker format:
```
<!-- zt:259 -->

<rendered annotation content>
```

This means the note is always structurally complete (correct section ordering), but annotation text that the user has manually edited is never overwritten.

## LaTeX Normalization

Unicode math symbols from PDF text extraction are converted to LaTeX equivalents via a static mapping in `latex_cleaner.py`. Examples:
- `¼` → `=`, `½` → `[`, `¾` → `]`
- Greek letters: `α` → `\alpha`, `Γ` → `\Gamma`, etc.
- Subscripts/superscripts: `₁` → `_{1}`, `²` → `^{2}`, etc.
- Math operators: `×` → `*`, `−` → `-`, `≤` → `\leq`, `∞` → `\infty`

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pymupdf` (provides `fitz`) | >= 1.27.2.3 | PDF structure analysis & TOC extraction |
| `watchdog` | >= 6.0.0 | Filesystem watching for live sync (optional; polling fallback) |

## Zotero Database Schema (relevant tables)

- `items` — all items (papers, notes, attachments, annotations)
- `itemTypes` — type names (journalArticle, note, attachment, annotation)
- `itemData` — field-value pairs per item
- `itemDataValues` — actual field values
- `fields` — field name definitions (title, date, DOI, abstract, extra, etc.)
- `creators` — author first/last names
- `itemCreators` — mapping of creators to items with order
- `itemAnnotations` — annotations (text, comment, color, pageLabel, sortIndex, position)
- `itemAttachments` — attachment metadata including PDF path
- `itemTags` / `tags` — user-applied tags

## Known Issues & Gotchas

1. **Some PDFs have no TOC entries** (e.g., older scanned PDFs). The fallback is manual heading annotations (Magenta/Orange/Gray).
2. **PDF text extraction can garble math symbols** (glyph→Unicode mapping errors in the PDF font). The `latex_cleaner` mapping handles common cases but cannot recover all original math.
3. **Full note regeneration**: annotation sections are rebuilt from scratch each export. User content in the three template sections is preserved; anything else (including annotation-section edits) will be lost.
4. **Interactive prompt**: `confirm_no_toc()` uses `input()` which hangs in non-interactive environments — pipe `yes` or use `echo y |` when scripting.
5. **Coordinate systems**: Zotero annotation positions use PDF coordinates (bottom-left origin) while fitz uses top-left origin. The section assignment in `get_section_for_annotation()` handles this by matching y-coordinates with a 20-unit tolerance.
