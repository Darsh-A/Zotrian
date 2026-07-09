from __future__ import annotations

import re

USER_SECTIONS = ("Open Questions", "Connections To Other Papers", "Thesis Relevance")

ANNOT_MARKER_RE = re.compile(r"^<!-- zt:(\d+) -->\s*$")
HEADING_RE = re.compile(r"^#{2,4}\s")


def _clean_annotation_content(lines: list[str]) -> str | None:
    start = 0
    while start < len(lines) and lines[start].strip() == "":
        start += 1
    end = len(lines) - 1
    while end >= start and lines[end].strip() == "":
        end -= 1
    cleaned = []
    for i in range(start, end + 1):
        stripped = lines[i].strip()
        if HEADING_RE.match(stripped) or stripped in ("## Thesis Notes", "## Abstract", "---"):
            continue
        cleaned.append(lines[i])
    result = "\n".join(cleaned).strip()
    return result if result else None


def parse_annotation_markers(note_text: str) -> dict[str, str]:
    extracted: dict[str, str] = {}
    lines = note_text.split("\n")
    current_key: str | None = None
    current_lines: list[str] = []

    for line in lines:
        m = ANNOT_MARKER_RE.match(line)
        if m:
            if current_key is not None:
                content = _clean_annotation_content(current_lines)
                if content:
                    extracted[current_key] = content
            current_key = m.group(1)
            current_lines = []
            continue
        if current_key is not None:
            current_lines.append(line)

    if current_key is not None:
        content = _clean_annotation_content(current_lines)
        if content:
            extracted[current_key] = content

    return extracted


def _find_section_bounds(content: str, heading: str) -> tuple[int, int] | None:
    pattern = rf"^## {re.escape(heading)}\s*$"
    start = None
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if re.match(pattern, line):
            start = i
            continue
        if start is not None and re.match(r"^(## |---)", line):
            return (start, i)
        if start is not None and i == len(lines) - 1:
            return (start, len(lines))
    return None


def extract_user_sections(existing_note: str) -> dict[str, str]:
    extracted: dict[str, str] = {}
    for section_name in USER_SECTIONS:
        bounds = _find_section_bounds(existing_note, section_name)
        if bounds is None:
            continue
        start_idx, end_idx = bounds
        lines = existing_note.split("\n")
        body = lines[start_idx + 1 : end_idx]
        stripped = "\n".join(body).strip()
        if stripped:
            extracted[section_name] = stripped
    return extracted


def inject_user_sections(rendered_parts: list[str], extracted: dict[str, str]) -> list[str]:
    result: list[str] = []
    heading_pattern = re.compile(r"^## (.+)$")

    i = 0
    while i < len(rendered_parts):
        line = rendered_parts[i]
        m = heading_pattern.match(line)
        if m and m.group(1) in extracted:
            result.append(line)
            result.append("")
            saved = extracted[m.group(1)]
            result.append(saved)
            result.append("")
            i += 1
            while i < len(rendered_parts):
                next_line = rendered_parts[i]
                if heading_pattern.match(next_line) or next_line.startswith("---"):
                    break
                i += 1
            continue
        result.append(line)
        i += 1

    return result
