from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

from pdf_parser import PDFParser
from zotero_db import ZoteroDB

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except Exception:  # pragma: no cover
    FileSystemEventHandler = object
    Observer = None


COLOR_MAP = {
    "#a28ae5": "purple",
    "#ffd400": "yellow",
    "#5fb236": "green",
    "#ff6666": "red",
    "#2ea8e5": "blue",
}


def slugify(value: str) -> str:
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE).strip().lower()
    return re.sub(r"[-\s]+", "-", value) or "note"


def extract_year(date_value: str | None) -> str:
    if not date_value:
        return ""
    m = re.search(r"\b(19|20)\d{2}\b", date_value)
    return m.group(0) if m else ""


def page_ref(page: str | None) -> str:
    return f"*(p. {page})*" if page else ""


def normalize_color(color: str | None) -> str:
    if not color:
        return "yellow"
    return COLOR_MAP.get(color.lower(), "yellow")


def first_line(text: str | None) -> str:
    if not text:
        return ""
    return text.strip().splitlines()[0].strip()


@dataclass
class Annotation:
    text: str
    comment: str | None
    color: str
    page: str | None
    position: dict[str, Any] | None
    section: str = "General Notes"


class NoteRenderer:
    def render_annotation(self, ann: Annotation) -> str:
        kind = normalize_color(ann.color)
        body = (ann.text or "").strip()
        comment = (ann.comment or "").strip()
        ref = page_ref(ann.page)

        if kind == "purple":
            heading = comment or "Definition"
            parts = [f"#### [[{heading}]]", ""]
            if body:
                parts.append(body)
            return "\n".join(parts).strip()
        if kind == "green":
            parts = [f"> {body}".rstrip(), ">"]
            if ref:
                parts.append(f"> {ref}")
            return "\n".join(parts).strip()
        if kind == "red":
            parts = ["> [!danger]"]
            if comment:
                parts.append(f"> {comment}")
                parts.append(">")
            if body:
                parts.append(f"> {body}")
                parts.append(">")
            if ref:
                parts.append(f"> {ref}")
            return "\n".join(parts).strip()
        if kind == "blue":
            return "\n".join([f"$$\n{body}\n$$", "", ref]).strip()
        parts = [body]
        if ref:
            parts.extend(["", ref])
        return "\n".join(parts).strip()

    def render_paper(self, paper: dict[str, Any], annotations: list[Annotation], outline: list[str] | None = None) -> str:
        authors = paper.get("authors") or []
        frontmatter = {
            "title": paper.get("title", ""),
            "authors": authors,
            "year": extract_year(paper.get("date")),
            "doi": paper.get("DOI", ""),
            "citekey": paper.get("citekey", ""),
            "paper_type": paper.get("itemType", ""),
            "tags": paper.get("tags", []),
        }
        parts = ["---"]
        parts.extend(f"{k}: {json.dumps(v) if isinstance(v, list) else v}" for k, v in frontmatter.items())
        parts.append("---")
        parts.append("")
        parts.append(f"# {paper.get('title', 'Untitled')}")
        parts.append("")
        if paper.get("abstractNote"):
            parts.extend(["## Abstract", "", paper["abstractNote"], ""])
        parts.append("## Thesis Notes")
        grouped: dict[str, list[Annotation]] = {}
        for ann in annotations:
            grouped.setdefault(ann.section, []).append(ann)
        ordered_sections = outline or sorted(grouped)
        seen = set()
        for section in ordered_sections:
            if section in seen:
                continue
            seen.add(section)
            parts.extend([f"### {section}", ""])
            for ann in grouped.get(section, []):
                rendered = self.render_annotation(ann)
                if rendered:
                    parts.append(rendered)
                    parts.append("")
        for section in sorted(set(grouped) - seen):
            parts.extend([f"### {section}", ""])
            for ann in grouped.get(section, []):
                rendered = self.render_annotation(ann)
                if rendered:
                    parts.append(rendered)
                    parts.append("")
        parts.extend(["---", "", "## Open Questions", "", "## Connections To Other Papers", "", "## Thesis Relevance"])
        return "\n".join(parts).rstrip() + "\n"

    def render_concept(self, title: str, cites: list[str], snippets: list[str]) -> str:
        body = [f"# {title}", ""]
        if snippets:
            body.append("\n\n".join(snippets))
            body.append("")
        if cites:
            body.extend(["## Sources", ""] + [f"- [[{c}]]" for c in cites])
        return "\n".join(body).rstrip() + "\n"


class SyncState:
    def __init__(self, path: Path):
        self.path = path
        self.data = {"papers": {}}
        if path.exists():
            self.data = json.loads(path.read_text())

    def get_hash(self, key: str) -> str | None:
        return self.data.get("papers", {}).get(key, {}).get("hash")

    def update(self, key: str, digest: str):
        self.data.setdefault("papers", {})[key] = {"hash": digest, "ts": time.time()}

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True))


class Exporter:
    render_version = "2"

    def __init__(self, vault: Path, db_path: Path | None = None):
        self.vault = vault
        self.out_dir = vault / "Papers"
        self.concept_dir = vault / "Concepts"
        self.state = SyncState(vault / ".zotrian-state.json")
        self.db = ZoteroDB(str(db_path) if db_path else "/home/ardo/Zotero/zotero.sqlite")
        self.renderer = NoteRenderer()
        self.out_dir.mkdir(exist_ok=True)
        self.concept_dir.mkdir(exist_ok=True)

    def annotation_section(self, parser: PDFParser | None, ann: dict[str, Any]) -> str:
        if not parser:
            return "General Notes"
        pos = ann.get("position") or {}
        page_index = pos.get("pageIndex")
        if page_index is None:
            try:
                page_index = max(int(ann.get("page", "1")) - 1, 0)
            except Exception:
                return "General Notes"
        return parser.get_section_for_annotation(page_index, pos)

    def digest_for_paper(self, paper: dict[str, Any], anns: list[Annotation], outline: list[str]) -> str:
        payload = {
            "render_version": self.render_version,
            "title": paper.get("title"),
            "dateModified": paper.get("dateModified"),
            "citekey": paper.get("citekey"),
            "pdf_path": paper.get("pdf_path"),
            "outline": outline,
            "annotations": [asdict(a) for a in anns],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def load_parser(self, pdf_path: str | None) -> PDFParser | None:
        if not pdf_path:
            return None
        try:
            return PDFParser(pdf_path)
        except Exception:
            return None

    def export_one(self, paper: dict[str, Any]) -> tuple[bool, str]:
        paper = dict(paper)
        key = paper.get("citekey") or slugify(paper.get("title", "untitled"))
        paper["citekey"] = key
        parser = self.load_parser(paper.get("pdf_path"))
        anns: list[Annotation] = []
        for raw in paper.get("annotations", []):
            ann = Annotation(
                text=raw.get("text") or "",
                comment=raw.get("comment"),
                color=raw.get("color") or "",
                page=raw.get("page"),
                position=raw.get("position"),
            )
            ann.section = self.annotation_section(parser, raw)
            anns.append(ann)
        outline = []
        if parser:
            for _, items in sorted(parser.sections.items()):
                outline.extend([title for _, title in items])
        digest = self.digest_for_paper(paper, anns, outline)
        if self.state.get_hash(key) == digest:
            return False, key
        note = self.renderer.render_paper(paper, anns, outline=outline)
        (self.out_dir / f"{key}.md").write_text(note)
        concepts: dict[str, dict[str, list[str]]] = {}
        for ann in anns:
            if normalize_color(ann.color) != "purple":
                continue
            title = first_line(ann.comment) or "Definition"
            concepts.setdefault(title, {"cites": [], "snippets": []})
            concepts[title]["cites"].append(key)
            concepts[title]["snippets"].append(ann.text.strip())
        for title, data in concepts.items():
            (self.concept_dir / f"{slugify(title)}.md").write_text(
                self.renderer.render_concept(title, sorted(set(data["cites"])), data["snippets"])
            )
        self.state.update(key, digest)
        return True, key

    def run(self, paper_filter: str | None = None) -> list[str]:
        changed: list[str] = []
        for paper in self.db.get_papers():
            if paper_filter and paper_filter.lower() not in (paper.get("title", "") + " " + paper.get("citekey", "")).lower():
                continue
            exported, key = self.export_one(paper)
            if exported:
                changed.append(key)
        self.state.save()
        return changed

    def refresh(self, paper_filter: str | None = None) -> list[str]:
        return self.run(paper_filter)


class ZoteroChangeHandler(FileSystemEventHandler):
    def __init__(self, exporter: Exporter, paper_filter: str | None = None):
        self.exporter = exporter
        self.paper_filter = paper_filter
        self.last_run = 0.0

    def on_modified(self, event):  # pragma: no cover
        if getattr(event, "is_directory", False):
            return
        self._maybe_refresh()

    def on_created(self, event):  # pragma: no cover
        if getattr(event, "is_directory", False):
            return
        self._maybe_refresh()

    def _maybe_refresh(self):  # pragma: no cover
        now = time.time()
        if now - self.last_run < 2:
            return
        self.last_run = now
        changed = self.exporter.refresh(self.paper_filter)
        if changed:
            print("Updated:")
            for key in changed:
                print(f"  - {key}")
        else:
            print("No note changes detected")


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--paper")
    p.add_argument("--vault")
    p.add_argument("--config", default="zotrian.json")
    p.add_argument("--watch", action="store_true")
    return p


def main():
    args = build_parser().parse_args()
    config = load_config(Path(args.config))
    vault = Path(args.vault or config.get("vault_path") or Path.cwd())
    db_path = Path(config.get("zotero_db_path") or "/home/ardo/Zotero/zotero.sqlite")
    exporter = Exporter(vault, db_path=db_path)
    changed = exporter.run(args.paper)
    print(f"Exported {len(changed)} papers")
    if args.watch:
        if Observer is None:
            raise RuntimeError("watchdog is not available in this environment")
        interval = int(config.get("watch_interval_seconds", 5))
        handler = ZoteroChangeHandler(exporter, args.paper)
        observer = Observer()
        observer.schedule(handler, str(db_path.parent), recursive=False)
        observer.start()
        print(f"Watching {db_path} for changes...")
        try:
            while True:
                time.sleep(interval)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
