import sqlite3

db_path = "/home/ardo/Zotero/zotero.sqlite"
uri = f"file:{db_path}?mode=ro&nolock=1"

conn = sqlite3.connect(uri, uri=True)
cursor = conn.cursor()

# Check extra field in items for a BBT citekey
query = """
SELECT items.itemID, fields.fieldName, itemDataValues.value
FROM items
JOIN itemData ON items.itemID = itemData.itemID
JOIN fields ON itemData.fieldID = fields.fieldID
JOIN itemDataValues ON itemData.valueID = itemDataValues.valueID
WHERE fields.fieldName IN ('extra', 'title', 'date', 'DOI')
LIMIT 10;
"""

for row in cursor.execute(query).fetchall():
    print(row)
