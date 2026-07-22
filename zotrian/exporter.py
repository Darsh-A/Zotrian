from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import AISettings, AppConfig
from .gemini_cleaner import AICleaningError, AICleaner, CleaningCandidate
from .note_merger import (
    extract_user_sections,
    inject_user_sections,
    parse_annotation_markers,
)
from .zotero_db import ZoteroDB


COLOR_MAP = {
    "#a28ae5": "purple",
    "#ffd400": "yellow",
    "#5fb236": "green",
    "#ff6666": "red",
    "#2ea8e5": "blue",
    "#e56eee": "magenta",
    "#f19837": "orange",
    "#aaaaaa": "gray",
}

HEADING_COLORS = frozenset({"magenta", "orange", "gray"})

HEADING_LEVELS = {
    "magenta": 2,
    "orange": 3,
    "gray": 4,
}


def normalize_color(color: str | None) -> str:
    if not color:
        return "yellow"
    return COLOR_MAP.get(color.lower(), "yellow")


def extract_year(date_value: str | None) -> str:
    if not date_value:
        return ""
    match = re.search(r"\b(19|20)\d{2}\b", date_value)
    return match.group(0) if match else ""


def sanitize_filename(value: str, fallback: str = "Untitled") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(". ")
    return cleaned or fallback


def yaml_scalar(value: Any) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


@dataclass
class Annotation:
    text: str
    comment: str | None
    color: str
    page: str | None
    position: dict[str, Any] | None
    image_path: str | None = None
    section: str = "Abstract"
    annot_key: str = ""


class NoteRenderer:
    def section_heading_level(self, section: str) -> int:
        match = re.match(r"^(\d+(?:\.\d+)*)\.", section.strip())
        if not match:
            return 3
        return min(3 + match.group(1).count("."), 6)

    def render_section_heading(self, section: str) -> str:
        return f"{'#' * self.section_heading_level(section)} {section}"

    def render_annotation(self, ann: Annotation, preserved: str | None = None) -> str:
        if preserved is not None:
            marker = f"<!-- zt:{ann.annot_key} -->"
            if preserved.startswith(marker):
                return preserved
            return f"{marker}\n\n{preserved}"

        kind = normalize_color(ann.color)
        if kind in HEADING_COLORS:
            return ""

        # Blue annotations are image-only (no body/comment required)
        if kind == "blue":
            image_path = Path(ann.image_path).expanduser() if ann.image_path else None
            if image_path and image_path.exists():
                content = f"![Blue annotation]({image_path.resolve().as_uri()})"
                marker = f"<!-- zt:{ann.annot_key} -->"
                return f"{marker}\n\n{content}"
            return ""

        body = (ann.text or "").strip()
        comment = (ann.comment or "").strip()

        if not body and not comment:
            return ""

        if kind == "purple":
            heading = comment or "Definition"
            parts = [f"#### [[{heading}]]", ""]
            if body:
                parts.append(body)
            content = "\n".join(parts).strip()
        elif kind == "green":
            content = f"> {body or comment}".rstrip()
        elif kind == "red":
            parts = ["> [!danger]"]
            if comment:
                parts.append(f"> {comment}")
            if body:
                parts.append(f"> {body}")
            content = "\n".join(parts).strip()
        else:
            content = body or comment

        if not content.strip():
            return ""

        marker = f"<!-- zt:{ann.annot_key} -->"
        return f"{marker}\n\n{content}"

    def render_frontmatter(self, paper: dict[str, Any]) -> list[str]:
        authors = paper.get("authors") or []
        tags = paper.get("tags") or []
        lines = [
            "---",
            f"title: {yaml_scalar(paper.get('title', ''))}",
            "authors:",
        ]
        if authors:
            lines.extend([f"  - {yaml_scalar(author)}" for author in authors])
        else:
            lines.append("  - \"\"")
        lines.extend(
            [
                f"year: {yaml_scalar(extract_year(paper.get('date')))}",
                f"doi: {yaml_scalar(paper.get('DOI', ''))}",
                f"citekey: {yaml_scalar(paper.get('citekey', ''))}",
                f"paper_type: {yaml_scalar(paper.get('itemType', ''))}",
                "tags:",
            ]
        )
        if tags:
            lines.extend([f"  - {yaml_scalar(tag)}" for tag in tags])
        else:
            lines.append("  - \"\"")
        lines.append("---")
        return lines

    def render_paper(
        self,
        paper: dict[str, Any],
        annotations: list[Annotation],
        outline: list[str] | None = None,
        heading_color_map: dict[str, str] | None = None,
        existing_note_content: str | None = None,
        existing_annotations: dict[str, str] | None = None,
    ) -> str:
        color_map = heading_color_map or {}
        preserved = existing_annotations or {}
        parts = self.render_frontmatter(paper)
        parts.extend(
            [
                "",
                f"# {paper.get('title', 'Untitled')}",
                "",
                "---",
                "## Open Questions",
                "",
                "## Connections To Other Papers",
                "",
                "## Thesis Relevance",
                "---",
                "",
            ]
        )

        if existing_note_content:
            extracted = extract_user_sections(existing_note_content)
            if extracted:
                parts = inject_user_sections(parts, extracted)

        grouped: dict[str, list[Annotation]] = {}
        for annotation in annotations:
            rendered = self.render_annotation(annotation)
            if not rendered:
                continue
            grouped.setdefault(annotation.section or "Abstract", []).append(annotation)

        ordered_sections: list[str] = []
        if "Abstract" in grouped and grouped["Abstract"]:
            ordered_sections.append("Abstract")
        if outline:
            for section in outline:
                if section not in ordered_sections:
                    ordered_sections.append(section)
        for section in grouped:
            if section not in ordered_sections:
                ordered_sections.append(section)

        if ordered_sections:
            parts.extend(["", "## Thesis Notes", ""])

        for section in ordered_sections:
            anns = grouped.get(section, [])
            heading_color = color_map.get(section)
            if heading_color:
                level = HEADING_LEVELS.get(heading_color, self.section_heading_level(section))
                parts.extend([f"{'#' * level} {section}", ""])
            else:
                parts.extend([self.render_section_heading(section), ""])
            for annotation in anns:
                content = self.render_annotation(annotation, preserved=preserved.get(annotation.annot_key))
                parts.append(content)
                parts.append("")

        return "\n".join(parts).rstrip() + "\n"


class SyncState:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {"papers": {}}
        if path.exists():
            try:
                self.data = json.loads(path.read_text())
            except json.JSONDecodeError:
                self.data = {"papers": {}}

    def get_paper(self, key: str) -> dict[str, Any]:
        return self.data.get("papers", {}).get(key, {})

    def update_paper(self, key: str, payload: dict[str, Any]) -> None:
        self.data.setdefault("papers", {})[key] = payload

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True, ensure_ascii=False))


class Exporter:
    render_version = "7"

    def __init__(self, config: AppConfig):
        self.config = config
        self.state = SyncState(config.state_path)
        self.db = ZoteroDB(
            db_path=str(config.zotero.database_path),
            storage_path=config.zotero.storage_path,
        )
        self.renderer = NoteRenderer()
        self.paper_dir = config.obsidian.paper_notes_path
        self.paper_dir.mkdir(parents=True, exist_ok=True)
        self.ai_cleaner = self._build_ai_cleaner(config.ai)

    def _build_ai_cleaner(self, settings: AISettings) -> AICleaner | None:
        if not settings.enabled:
            return None
        return AICleaner(settings)

    def _annotation_page_index(self, ann: dict[str, Any]) -> int:
        position = ann.get("position") or {}
        page_index = position.get("pageIndex")
        if page_index is not None:
            return int(page_index)
        try:
            return max(int(ann.get("page", "1")) - 1, 0)
        except Exception:
            return 0

    def _assign_sections_from_headings(
        self,
        all_annotations: list[Annotation],
        heading_color_map: dict[str, str],
    ) -> None:
        current_section = "Abstract"
        for ann in all_annotations:
            kind = normalize_color(ann.color)
            title = (ann.text or ann.comment or "").strip()
            if kind in HEADING_COLORS and title:
                current_section = title
                heading_color_map[title] = kind
            else:
                ann.section = current_section

    def _assign_sections_by_reading_order(
        self,
        content_annotations: list[Annotation],
        heading_positions: list[tuple],
        parser: Any | None = None,
    ) -> None:
        """Assign sections using a virtual-page reading-order sweep.

        Each physical page is split at its width midpoint into two virtual
        pages: left half = page*2, right half = page*2+1.  Headings and
        annotations are then sorted by (virtual_page, y), which naturally
        respects two-column reading order without fragile column detection.

        heading_positions elements can be either:
          - 5-tuple: (page, x_left, y_top, title, toc_index) — from font detection
          - 4-tuple: (page, y_top, title, toc_index) — from text search fallback
        """
        # --- Virtual page helpers ---
        def _page_width(page_index: int) -> float:
            if parser is None or page_index < 0 or page_index >= len(parser.doc):
                return 0.0
            return float(parser.doc[page_index].rect.width)

        def heading_virtual(h: tuple) -> tuple[int, float]:
            page = h[0]
            pw = _page_width(page)
            if len(h) == 5:
                x = h[1]
                y = h[2]
            else:
                x = 0.0  # no x info → assume left column
                y = h[1]
            vp = page * 2 if pw <= 0 or x < pw / 2 else page * 2 + 1
            return (vp, y)

        # --- Build annotation events: (virtual_page, fitz_y_top, annotation) ---
        ann_events: list[tuple[int, float, Annotation]] = []
        for ann in content_annotations:
            position = ann.position or {}
            page_index = position.get("pageIndex")
            if page_index is None:
                try:
                    page_index = max(int(ann.page or "1") - 1, 0)
                except (ValueError, TypeError):
                    page_index = 0

            y_coord = 0.0
            x_coord = 0.0
            rects = position.get("rects") or []
            if rects:
                y_coord = min(rect[1] for rect in rects if len(rect) >= 2)
                x_coord = min(rect[0] for rect in rects if len(rect) >= 1)

            # Convert Zotero PDF bottom-left coords to fitz top-left coords
            if parser is not None:
                page_h = parser._page_height(page_index)
                if page_h > 0:
                    y_coord = page_h - y_coord

            pw = _page_width(page_index)
            vp = page_index * 2 if pw <= 0 or x_coord < pw / 2 else page_index * 2 + 1
            ann_events.append((vp, y_coord, ann))

        # Sort by (virtual_page, y) — top-to-bottom within each virtual page
        ann_events.sort(key=lambda x: (x[0], x[1]))

        # Sort headings by (virtual_page, y)
        sorted_headings = sorted(heading_positions, key=lambda h: heading_virtual(h))

        # Sweep: walk annotations in reading order, advancing heading pointer
        current_section = "Abstract"
        h_idx = 0

        for vp_ann, y_ann, ann in ann_events:
            while h_idx < len(sorted_headings):
                h = sorted_headings[h_idx]
                vp_h, y_h = heading_virtual(h)

                # Heading precedes annotation if earlier virtual page,
                # or same virtual page with y <= annotation y (with tolerance)
                precedes = vp_h < vp_ann or (vp_h == vp_ann and y_h <= y_ann + 5)
                if precedes:
                    current_section = h[3] if len(h) == 5 else h[2]  # title
                    h_idx += 1
                else:
                    break
            ann.section = current_section

    def annotation_section(self, parser: Any | None, ann: dict[str, Any]) -> str:
        if not parser:
            return "Abstract"
        position = ann.get("position") or {}
        page_index = position.get("pageIndex")
        if page_index is None:
            try:
                page_index = max(int(ann.get("page", "1")) - 1, 0)
            except Exception:
                return "Abstract"
        return parser.get_section_for_annotation(page_index, position)

    def _content_ai_candidates(self, annotations: list[Annotation]) -> list[CleaningCandidate]:
        candidates: list[CleaningCandidate] = []
        for annotation in annotations:
            kind = normalize_color(annotation.color)
            if kind in HEADING_COLORS or kind == "blue":
                continue
            text = (annotation.text or "").strip()
            comment = (annotation.comment or "").strip() or None
            if not text and not comment:
                continue
            candidates.append(
                CleaningCandidate(
                    annot_key=annotation.annot_key,
                    section=annotation.section or "Abstract",
                    page=annotation.page,
                    color=kind,
                    text=text,
                    comment=comment,
                )
            )
        return candidates

    def _apply_ai_cleaning(
        self,
        paper: dict[str, Any],
        stable_key: str,
        annotations: list[Annotation],
    ) -> None:
        if not self.ai_cleaner:
            return

        previous_state = self.state.get_paper(stable_key)
        cache = dict(previous_state.get("ai_cache") or {})
        candidates = self._content_ai_candidates(annotations)
        if not candidates:
            return

        cleaned_by_key: dict[str, str] = {}
        pending: list[CleaningCandidate] = []
        for candidate in candidates:
            signature = self.ai_cleaner.input_signature(candidate)
            cached = cache.get(candidate.annot_key)
            if (
                isinstance(cached, dict)
                and cached.get("signature") == signature
                and isinstance(cached.get("cleaned_text"), str)
                and cached.get("cleaned_text")
            ):
                cleaned_by_key[candidate.annot_key] = cached["cleaned_text"]
            else:
                pending.append(candidate)

        batch_size = max(self.config.ai.batch_size, 1)
        merged_secondary: set[str] = set()
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            cleaned_batch = self.ai_cleaner.clean_batch(paper, batch)

            individual_map: dict[str, str] = {}
            for composite_key, cleaned_text in cleaned_batch.items():
                keys = [k.strip() for k in composite_key.split(",") if k.strip()]
                if not keys or not cleaned_text:
                    continue
                for k in keys:
                    individual_map[k] = cleaned_text
                if len(keys) > 1:
                    merged_secondary.update(keys[1:])

            for candidate in batch:
                cleaned_text = individual_map.get(candidate.annot_key)
                if not cleaned_text:
                    continue
                cleaned_by_key[candidate.annot_key] = cleaned_text
                cache[candidate.annot_key] = {
                    "signature": self.ai_cleaner.input_signature(candidate),
                    "cleaned_text": cleaned_text,
                }

        for annotation in annotations:
            key = annotation.annot_key
            if key in merged_secondary:
                annotation.text = ""
                annotation.comment = None
            elif key in cleaned_by_key:
                annotation.text = cleaned_by_key[key]

        paper_cache = dict(previous_state)
        paper_cache["ai_cache"] = cache
        self.state.update_paper(stable_key, paper_cache)

    def digest_for_paper(
        self,
        paper: dict[str, Any],
        note_title: str,
        annotations: list[Annotation],
        outline: list[str],
    ) -> str:
        payload = {
            "render_version": self.render_version,
            "paper_key": paper.get("key"),
            "note_title": note_title,
            "title": paper.get("title"),
            "dateModified": paper.get("dateModified"),
            "citekey": paper.get("citekey"),
            "pdf_path": paper.get("pdf_path"),
            "outline": outline,
            "annotations": [asdict(annotation) for annotation in annotations],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def load_parser(self, pdf_path: str | None):
        if not pdf_path:
            return None
        try:
            from .pdf_parser import PDFParser

            return PDFParser(pdf_path)
        except Exception:
            return None

    def export_one(self, paper: dict[str, Any]) -> tuple[bool, str]:
        paper = dict(paper)
        stable_key = paper.get("key") or paper.get("citekey") or sanitize_filename(paper.get("title", "Untitled"))
        note_title = paper.get("title") or paper.get("citekey") or stable_key
        note_filename = f"{sanitize_filename(note_title)}.md"
        paper["citekey"] = paper.get("citekey") or stable_key

        parser = self.load_parser(paper.get("pdf_path"))

        all_annotations: list[Annotation] = []
        heading_color_map: dict[str, str] = {}

        for raw in paper.get("annotations", []):
            color = raw.get("color") or ""
            kind = normalize_color(color)
            ann = Annotation(
                text=raw.get("text") or "",
                comment=raw.get("comment"),
                color=color,
                page=raw.get("page"),
                position=raw.get("position"),
                image_path=raw.get("image_path"),
                annot_key=str(raw.get("key", "")),
            )
            if kind in HEADING_COLORS:
                title = (ann.text or ann.comment or "").strip()
                if title:
                    heading_color_map[title] = kind
            all_annotations.append(ann)

        content_annotations = [a for a in all_annotations if normalize_color(a.color) not in HEADING_COLORS]
        heading_annotations = [a for a in all_annotations if normalize_color(a.color) in HEADING_COLORS]

        has_toc = parser is not None and parser.toc and len(parser.toc) >= 2

        heading_positions: list[tuple] | None = None
        if has_toc and parser:
            # Try font-based detection first (returns 5-tuples with x-coord)
            heading_positions = parser._detect_headings_by_font()
            if not heading_positions:
                # Fallback to text search (returns 4-tuples without x-coord)
                heading_positions = parser.get_heading_positions()
            self._assign_sections_by_reading_order(content_annotations, heading_positions, parser)
        else:
            self._assign_sections_from_headings(all_annotations, heading_color_map)

        outline: list[str] = []
        if heading_positions is not None:
            for h in heading_positions:
                title = h[3] if len(h) == 5 else h[2]
                if title not in outline:
                    outline.append(title)
        for ann in heading_annotations:
            title = (ann.text or ann.comment or "").strip()
            if title and title not in outline:
                outline.append(title)

        for ann in content_annotations:
            ann.text = (ann.text or "").strip()

        self._apply_ai_cleaning(paper, stable_key, content_annotations)

        all_annotations = content_annotations + heading_annotations
        note_path = self.paper_dir / note_filename
        digest = self.digest_for_paper(paper, note_title, all_annotations, outline)
        previous_state = self.state.get_paper(stable_key)
        if previous_state.get("hash") == digest and note_path.exists():
            return False, note_title

        existing_content = None
        existing_annotations: dict[str, str] = {}
        if note_path.exists():
            existing_content = note_path.read_text()
            if not self.ai_cleaner:
                existing_annotations = parse_annotation_markers(existing_content)

        content = self.renderer.render_paper(
            paper,
            content_annotations,
            outline,
            heading_color_map=heading_color_map,
            existing_note_content=existing_content,
            existing_annotations=existing_annotations,
        )
        note_path.write_text(content)

        previous_note_path = previous_state.get("note_path")
        if previous_note_path and previous_note_path != str(note_path):
            old_path = Path(previous_note_path)
            if old_path.exists():
                old_path.unlink()

        self.state.update_paper(
            stable_key,
            {
                **(self.state.get_paper(stable_key) or {}),
                "hash": digest,
                "updated_at": time.time(),
                "note_path": str(note_path),
                "note_title": note_title,
            },
        )

        return True, note_title

    def run(self, paper_filter: str | None = None) -> list[str]:
        changed: list[str] = []
        for paper in self.db.get_papers(paper_filter=paper_filter):
            exported, note_title = self.export_one(paper)
            if exported:
                changed.append(note_title)
        self.state.save()
        return changed

    def refresh(self, paper_filter: str | None = None) -> list[str]:
        return self.run(paper_filter=paper_filter)
