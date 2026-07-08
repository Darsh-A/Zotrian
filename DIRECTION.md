# Project: Zotero → Obsidian Thesis Knowledge Management Pipeline

A local-first tool that converts Zotero papers and annotations into structured Obsidian notes for my MSc thesis workflow. This should fully replace my use of Better Notes.

## Goal

1. Read papers, metadata, PDFs, and annotations directly from Zotero.
2. Determine which section/subsection of the paper each annotation belongs to, using the actual PDF structure (not just page number).
3. Generate well-structured Markdown notes for Obsidian, organized by section of the paper.
4. Generate concept/reference notes from definition annotations.
5. Support incremental runs — only changed papers/annotations get re-exported, not the whole vault.

## Zotero Source Data

Extract per paper:
- title, authors, year, abstract, DOI, tags, collections
- Better BibTeX citation key
- attached PDF path
- annotations (highlighted text, comment, color, page, position data)

## Annotation Processing by Highlight Color

| Color | Meaning | Output |
|---|---|---|
| Purple | Definition / reusable concept | Heading = comment (or "Definition" if empty), body = highlighted text. |
| Yellow | Normal note | Plain text|
| Green | Quote | Blockquote + page reference |
| Red | Warning / caveat | `[!danger]` callout, includes comment if present, + page reference |
| Blue | Equation / binding box image | Embedded image reference to Zotero cache + page reference |

(See examples of each output format below.)

### Purple example
```markdown
#### [[Signal-to-Noise Ratio]]

Ratio between useful signal and background noise.
```

### Yellow example
```markdown
Some important observation from the paper.
```

### Green example
```markdown
> Quoted text
```

### Red example
```markdown
> [!danger]
> Important caveat
```

### Blue example
```markdown
![Blue annotation](file:///home/ardo/Zotero/cache/library/6UTPXA9S.png)

*(p. 377)*
```

## Section Assignment

The core hard problem: given an annotation's location in the PDF, determine which logical section/subsection (per the paper's actual structure — Introduction, Methods, 2.1 Data Collection, etc.) it belongs to, even when a page contains multiple section boundaries.

This needs to work from the PDF's real structure (table of contents if present, heading text/font detection as fallback) and the annotation's actual position — not just "annotation is on page 12 so it belongs to whatever section starts that page." Research the best current approach for this rather than assuming one method; this is the part most worth getting right.

If the subsections arent available then you can put the annotations in the parent section.

Also have a fallback for color codes for 3 level of heading
Color 1 - Heading_Level 1
Color 2 - Heading_Level 1.1
Color 3 - Heading_Level 1.1.1

## Markdown Output

One note per paper:

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

---
## Open Questions

## Connections To Other Papers

## Thesis Relevance
---

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

Support Obsidian conventions: wikilinks, callouts, backlinks, Dataview-compatible frontmatter.


## Incremental Updates

Re-running the tool should only touch papers/annotations that changed since the last run — not rewrite the whole vault. Figure out a reasonable way to track state/detect changes (e.g. some form of caching) — doesn't need to match any particular implementation, just needs to be reliable and not require Zotero-side plugins.


## CLI
For the CLI i want two different things

1. A run convert command that converts the annotated pdf to note file
2. A live watch command that watches live annotation changes and keeps adding it to the obsidian note

Also name the obsidian note based on the paper title