from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import AppConfig
from .zotero_db import ZoteroDB


COLOR_MAP = {
    "#a28ae5": "purple",
    "#ffd400": "yellow",
    "#5fb236": "green",
    "#ff6666": "red",
    "#2ea8e5": "blue",
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
    section: str = "General Notes"


class NoteRenderer:
    def section_heading_level(self, section: str) -> int:
        match = re.match(r"^(\d+(?:\.\d+)*)\.", section.strip())
        if not match:
            return 3
        return min(3 + match.group(1).count("."), 6)

    def render_section_heading(self, section: str) -> str:
        return f"{'#' * self.section_heading_level(section)} {section}"

    def render_annotation(self, ann: Annotation) -> str:
        kind = normalize_color(ann.color)
        body = (ann.text or "").strip()
        comment = (ann.comment or "").strip()

        if kind == "purple":
            heading = comment or "Definition"
            parts = [f"#### [[{heading}]]", ""]
            if body:
                parts.append(body)
            return "\n".join(parts).strip()

        if kind == "green":
            return f"> {body or comment}".rstrip()

        if kind == "red":
            parts = ["> [!danger]"]
            if comment:
                parts.append(f"> {comment}")
            if body:
                parts.append(f"> {body}")
            return "\n".join(parts).strip()

        if kind == "blue":
            image_path = Path(ann.image_path).expanduser() if ann.image_path else None
            if image_path and image_path.exists():
                parts = [f"![Blue annotation]({image_path.resolve().as_uri()})"]
            else:
                parts = ["$$", body or comment, "$$"]
            return "\n".join(parts).strip()

        return body or comment

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

    def render_paper(self, paper: dict[str, Any], annotations: list[Annotation], outline: list[str] | None = None) -> str:
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
                "## Thesis Notes",
                "",
            ]
        )

        grouped: dict[str, list[Annotation]] = {}
        for annotation in annotations:
            rendered = self.render_annotation(annotation)
            if not rendered:
                continue
            grouped.setdefault(annotation.section or "General Notes", []).append(annotation)

        ordered_sections: list[str] = []
        if outline:
            for section in outline:
                if section in grouped and section not in ordered_sections:
                    ordered_sections.append(section)
        for section in grouped:
            if section not in ordered_sections:
                ordered_sections.append(section)

        if not ordered_sections:
            ordered_sections = ["General Notes"]

        for section in ordered_sections:
            parts.extend([self.render_section_heading(section), ""])
            for annotation in grouped.get(section, []):
                parts.append(self.render_annotation(annotation))
                parts.append("")

        return "\n".join(parts).rstrip() + "\n"

class SyncState:
    def __init__(self, path: Path):
        self.path = path
        self.data = {"papers": {}}
        if path.exists():
            self.data = json.loads(path.read_text())

    def get_paper(self, key: str) -> dict[str, Any]:
        return self.data.get("papers", {}).get(key, {})

    def update_paper(self, key: str, payload: dict[str, Any]) -> None:
        self.data.setdefault("papers", {})[key] = payload

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True, ensure_ascii=False))


class Exporter:
    render_version = "5"

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

    def annotation_section(self, parser: Any | None, ann: dict[str, Any]) -> str:
        if not parser:
            return "General Notes"

        position = ann.get("position") or {}
        page_index = position.get("pageIndex")
        if page_index is None:
            try:
                page_index = max(int(ann.get("page", "1")) - 1, 0)
            except Exception:
                return "General Notes"
        return parser.get_section_for_annotation(page_index, position)

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
        annotations: list[Annotation] = []
        for raw in paper.get("annotations", []):
            annotation = Annotation(
                text=raw.get("text") or "",
                comment=raw.get("comment"),
                color=raw.get("color") or "",
                page=raw.get("page"),
                position=raw.get("position"),
                image_path=raw.get("image_path"),
            )
            annotation.section = self.annotation_section(parser, raw)
            annotations.append(annotation)

        outline: list[str] = []
        if parser:
            for _, items in sorted(parser.sections.items()):
                outline.extend([title for _, title in items])

        digest = self.digest_for_paper(paper, note_title, annotations, outline)
        previous_state = self.state.get_paper(stable_key)
        if previous_state.get("hash") == digest:
            return False, note_title

        note_path = self.paper_dir / note_filename
        note_path.write_text(self.renderer.render_paper(paper, annotations, outline))

        previous_note_path = previous_state.get("note_path")
        if previous_note_path and previous_note_path != str(note_path):
            old_path = Path(previous_note_path)
            if old_path.exists():
                old_path.unlink()

        self.state.update_paper(
            stable_key,
            {
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
