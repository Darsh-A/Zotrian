import json
import sqlite3
import time
from pathlib import Path


class ZoteroDB:
    def __init__(self, db_path: str, storage_path: str | Path | None = None):
        self.db_path = db_path
        self.uri = f"file:{self.db_path}?mode=ro&immutable=1"
        if storage_path is None:
            self.storage_path = Path(db_path).parent / "storage"
        else:
            self.storage_path = Path(storage_path)
        self.cache_path = Path(db_path).parent / "cache" / "library"

    def get_connection(self):
        conn = sqlite3.connect(self.uri, uri=True, timeout=30)
        conn.execute("PRAGMA query_only = ON")
        return conn

    def get_papers(self, since_timestamp=None, paper_filter=None):
        """Fetch all top-level items (papers)."""
        last_error = None
        for attempt in range(5):
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                query = """
                    SELECT items.itemID, items.key, items.dateModified, itemTypes.typeName
                    FROM items
                    JOIN itemTypes ON items.itemTypeID = itemTypes.itemTypeID
                    WHERE itemTypes.typeName NOT IN ('note', 'attachment', 'annotation')
                """

                params = []
                if paper_filter:
                    query += """
                        AND (
                            EXISTS (
                                SELECT 1
                                FROM itemData
                                JOIN fields ON itemData.fieldID = fields.fieldID
                                JOIN itemDataValues ON itemData.valueID = itemDataValues.valueID
                                WHERE itemData.itemID = items.itemID
                                  AND fields.fieldName = 'title'
                                  AND lower(itemDataValues.value) LIKE ?
                            )
                            OR EXISTS (
                                SELECT 1
                                FROM itemData
                                JOIN fields ON itemData.fieldID = fields.fieldID
                                JOIN itemDataValues ON itemData.valueID = itemDataValues.valueID
                                WHERE itemData.itemID = items.itemID
                                  AND fields.fieldName = 'extra'
                                  AND lower(itemDataValues.value) LIKE ?
                            )
                            OR lower(items.key) LIKE ?
                        )
                    """
                    filter_value = f"%{paper_filter.lower()}%"
                    params.extend([filter_value, filter_value, filter_value])
                if since_timestamp:
                    query += " AND items.dateModified > ?"
                    params.append(since_timestamp)

                papers = []
                for row in cursor.execute(query, params).fetchall():
                    item_id, key, date_modified, item_type = row
                    metadata = self.get_item_metadata(conn, item_id)
                    metadata["itemID"] = item_id
                    metadata["key"] = key
                    metadata["dateModified"] = date_modified
                    metadata["itemType"] = item_type
                    metadata["tags"] = self.get_item_tags(conn, item_id)
                    metadata["pdf_path"] = self.get_pdf_attachment(conn, item_id)
                    metadata["annotations"] = self.get_annotations(conn, item_id)
                    papers.append(metadata)

                conn.close()
                return papers
            except sqlite3.OperationalError as exc:
                last_error = exc
                if "database is locked" not in str(exc).lower():
                    raise
                time.sleep(0.5 * (attempt + 1))
        raise last_error

    def get_item_metadata(self, conn, item_id):
        cursor = conn.cursor()
        query = """
            SELECT fields.fieldName, itemDataValues.value
            FROM itemData
            JOIN fields ON itemData.fieldID = fields.fieldID
            JOIN itemDataValues ON itemData.valueID = itemDataValues.valueID
            WHERE itemData.itemID = ?
        """
        metadata = {}
        for row in cursor.execute(query, (item_id,)).fetchall():
            field_name, value = row
            metadata[field_name] = value

        metadata["citekey"] = ""
        if "extra" in metadata:
            for line in metadata["extra"].splitlines():
                line = line.strip()
                if line.lower().startswith(("citation key:", "citekey:")):
                    metadata["citekey"] = line.split(":", 1)[1].strip()
                    break

        author_query = """
            SELECT creators.firstName, creators.lastName
            FROM itemCreators
            JOIN creators ON itemCreators.creatorID = creators.creatorID
            WHERE itemCreators.itemID = ?
            ORDER BY itemCreators.orderIndex
        """
        authors = []
        for row in cursor.execute(author_query, (item_id,)).fetchall():
            first, last = row
            if first and last:
                authors.append(f"{first} {last}")
            elif last:
                authors.append(last)
            elif first:
                authors.append(first)
        metadata["authors"] = authors
        return metadata

    def get_item_tags(self, conn, item_id):
        cursor = conn.cursor()
        query = """
            SELECT tags.name
            FROM itemTags
            JOIN tags ON itemTags.tagID = tags.tagID
            WHERE itemTags.itemID = ?
        """
        return [row[0] for row in cursor.execute(query, (item_id,)).fetchall()]

    def get_pdf_attachment(self, conn, item_id):
        cursor = conn.cursor()
        query = """
            SELECT items.key, itemAttachments.path
            FROM itemAttachments
            JOIN items ON itemAttachments.itemID = items.itemID
            WHERE itemAttachments.parentItemID = ? AND itemAttachments.contentType = 'application/pdf'
        """
        row = cursor.execute(query, (item_id,)).fetchone()
        if row:
            key, path = row
            if path and path.startswith("storage:"):
                filename = path.replace("storage:", "")
                full_path = self.storage_path / key / filename
                if full_path.exists():
                    return str(full_path)
        return None

    def get_annotations(self, conn, item_id):
        cursor = conn.cursor()
        attach_query = "SELECT itemID FROM itemAttachments WHERE parentItemID = ? AND contentType='application/pdf'"
        attach_rows = cursor.execute(attach_query, (item_id,)).fetchall()

        annotations = []
        for attach_row in attach_rows:
            attach_id = attach_row[0]
            ann_query = """
                SELECT ia.itemID, ia.text, ia.comment, ia.color, ia.pageLabel, ia.position, it.key
                FROM itemAnnotations ia
                JOIN items it ON ia.itemID = it.itemID
                WHERE ia.parentItemID = ?
                ORDER BY ia.sortIndex
            """
            for row in cursor.execute(ann_query, (attach_id,)).fetchall():
                annotation_id, text, comment, color, page_label, position, zotero_key = row
                annotation_key = str(annotation_id) if annotation_id is not None else None
                image_key = zotero_key if zotero_key else annotation_key
                image_path = self.get_annotation_image_path(image_key)
                annotations.append(
                    {
                        "key": annotation_key,
                        "text": text,
                        "comment": comment,
                        "color": color,
                        "page": page_label,
                        "position": json.loads(position) if position else None,
                        "image_path": str(image_path) if image_path else None,
                    }
                )

        return annotations

    def get_annotation_image_path(self, annotation_key):
        if not annotation_key:
            return None
        image_path = self.cache_path / f"{annotation_key}.png"
        return image_path if image_path.exists() else None
