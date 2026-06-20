import json
import sqlite3
from pathlib import Path

class ZoteroDB:
    def __init__(self, db_path="/home/ardo/Zotero/zotero.sqlite"):
        self.db_path = db_path
        self.uri = f"file:{self.db_path}?mode=ro&nolock=1"
        self.storage_path = Path(db_path).parent / "storage"
        
    def get_connection(self):
        return sqlite3.connect(self.uri, uri=True)

    def get_papers(self, since_timestamp=None):
        """Fetch all top-level items (papers)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # We look for itemTypes that are typical papers (e.g., journalArticle, preprint, conferencePaper, etc.)
        # 1: artwork, 2: audioRecording, 3: bill, 4: blogPost, 5: book, 6: bookSection, 7: case, 8: computerProgram...
        # We can just fetch all top level items that are not notes or attachments.
        
        query = """
            SELECT items.itemID, items.key, items.dateModified, itemTypes.typeName
            FROM items
            JOIN itemTypes ON items.itemTypeID = itemTypes.itemTypeID
            WHERE itemTypes.typeName NOT IN ('note', 'attachment', 'annotation')
        """
        
        params = []
        if since_timestamp:
            query += " AND items.dateModified > ?"
            params.append(since_timestamp)
            
        papers = []
        for row in cursor.execute(query, params).fetchall():
            item_id, key, date_modified, item_type = row
            metadata = self.get_item_metadata(conn, item_id)
            metadata['itemID'] = item_id
            metadata['key'] = key
            metadata['dateModified'] = date_modified
            metadata['itemType'] = item_type
            
            # Fetch tags
            metadata['tags'] = self.get_item_tags(conn, item_id)
            
            # Fetch PDF attachment
            metadata['pdf_path'] = self.get_pdf_attachment(conn, item_id)
            
            # Fetch annotations
            metadata['annotations'] = self.get_annotations(conn, item_id)
            
            papers.append(metadata)
            
        conn.close()
        return papers

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
            
        # Extract citekey from extra if present
        metadata['citekey'] = ""
        if 'extra' in metadata:
            for line in metadata['extra'].splitlines():
                line = line.strip()
                if line.lower().startswith(('citation key:', 'citekey:')):
                    metadata['citekey'] = line.split(':', 1)[1].strip()
                    break
                    
        # Fetch authors
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
        metadata['authors'] = authors
        
        return metadata
        
    def get_item_tags(self, conn, item_id):
        cursor = conn.cursor()
        query = """
            SELECT tags.name
            FROM itemTags
            JOIN tags ON itemTags.tagID = tags.tagID
            WHERE itemTags.itemID = ?
        """
        return [r[0] for r in cursor.execute(query, (item_id,)).fetchall()]

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
            if path and path.startswith('storage:'):
                filename = path.replace('storage:', '')
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
                SELECT text, comment, color, pageLabel, position
                FROM itemAnnotations
                WHERE parentItemID = ?
                ORDER BY sortIndex
            """
            for row in cursor.execute(ann_query, (attach_id,)).fetchall():
                text, comment, color, pageLabel, position = row
                ann = {
                    "text": text,
                    "comment": comment,
                    "color": color,
                    "page": pageLabel,
                    "position": json.loads(position) if position else None
                }
                annotations.append(ann)
                
        return annotations

if __name__ == "__main__":
    db = ZoteroDB()
    papers = db.get_papers()
    print(f"Found {len(papers)} papers.")
    for p in papers:
        if p.get('annotations'):
            print(f"Paper: {p.get('title')} has {len(p['annotations'])} annotations.")
            print(f"Sample annotation: {p['annotations'][0]}")
