from __future__ import annotations


def clean_annotation_text(zotero_text: str | None) -> str:
    return (zotero_text or "").strip()
