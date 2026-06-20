# Project: Zotero → Obsidian Thesis Knowledge Management Pipeline

A local-first tool that converts Zotero papers and annotations into structured Obsidian notes for my MSc thesis workflow. This should fully replace my use of Better Notes.

## Goal

1. Read papers, metadata, PDFs, and annotations directly from Zotero.
2. Determine which section/subsection of the paper each annotation belongs to, using the actual PDF structure (not just page number).
3. Generate well-structured Markdown notes for Obsidian, organized by section.
4. Generate concept/reference notes from definition annotations.
5. Support incremental runs — only changed papers/annotations get re-exported, not the whole vault.

## Environment

- OS: Linux (EndeavourOS)
- Zotero + Better BibTeX + Obsidian
- Python 3.12+

Research current best-practice approaches and libraries for reading the Zotero SQLite database safely (it's locked while Zotero is running), reading Better BibTeX citation keys, parsing annotation data (including position/coordinate info), and extracting PDF structure/outline. Prefer minimal dependencies, but use whatever's actually well-suited and well-maintained for each part — don't assume any specific library is the right choice without checking current docs/state of the ecosystem.

## Zotero Source Data

Extract per paper:
- title, authors, year, abstract, DOI, tags, collections
- Better BibTeX citation key
- attached PDF path
- annotations (highlighted text, comment, color, page, position data)

## Annotation Processing by Highlight Color

| Color | Meaning | Output |
|---|---|---|
| Purple | Definition / reusable concept | Heading = comment (or "Definition" if empty), body = highlighted text. Also creates/updates a linked concept note in `Concepts/`. |
| Yellow | Normal note | Plain text + page reference |
| Green | Quote | Blockquote + page reference |
| Red | Warning / caveat | `[!danger]` callout, includes comment if present, + page reference |
| Blue | Equation | LaTeX block (`$$...$$`) + page reference |

(See examples of each output format below.)

### Purple example
```markdown
#### [[Signal-to-Noise Ratio]]

Ratio between useful signal and background noise.
```

### Yellow example
```markdown
Some important observation from the paper.

*(p. 5)*
```

### Green example
```markdown
> Quoted text
>
> *(p. 5)*
```

### Red example
```markdown
> [!danger]
> Important caveat
>
> Note: selection effects may dominate
>
> *(p. 5)*
```

### Blue example
```markdown
$$
E = mc^2
$$

*(p. 5)*
```

## Section Assignment

The core hard problem: given an annotation's location in the PDF, determine which logical section/subsection (per the paper's actual structure — Introduction, Methods, 2.1 Data Collection, etc.) it belongs to, even when a page contains multiple section boundaries.

This needs to work from the PDF's real structure (table of contents if present, heading text/font detection as fallback) and the annotation's actual position — not just "annotation is on page 12 so it belongs to whatever section starts that page." Research the best current approach for this rather than assuming one method; this is the part most worth getting right.

## Markdown Output

One note per paper:

```markdown
---
title:
authors:
year:
doi:
citekey:
paper_type:
tags:
---

# Paper Title

## Abstract

...

## Thesis Notes

### Introduction
annotations...

### Methods
annotations...

### Results
annotations...

### Discussion
annotations...

---

## Open Questions

## Connections To Other Papers

## Thesis Relevance
```

Concept notes (from purple highlights) live separately:

```text
Concepts/Signal-to-Noise Ratio.md
```

Support Obsidian conventions: wikilinks, callouts, backlinks, Dataview-compatible frontmatter.


## Incremental Updates

Re-running the tool should only touch papers/annotations that changed since the last run — not rewrite the whole vault. Figure out a reasonable way to track state/detect changes (e.g. some form of caching) — doesn't need to match any particular implementation, just needs to be reliable and not require Zotero-side plugins.

## CLI

```bash
python export.py
python export.py --paper "Gaia DR3"
python export.py --watch
```

## Deliverables

1. Architecture design (with reasoning for key technical choices, especially section-assignment approach)
2. Database/data access layer
3. PDF structure parser + section assignment logic
4. Annotation parser
5. Markdown renderer
6. Incremental sync system
7. CLI

Production-ready code, but flag any assumptions or edge cases (e.g. PDFs with no embedded TOC, annotations spanning page breaks) you had to make a judgment call on.