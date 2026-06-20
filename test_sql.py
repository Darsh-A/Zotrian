import sqlite3

db_path = "/home/ardo/Zotero/zotero.sqlite"
uri = f"file:{db_path}?mode=ro&nolock=1"
conn = sqlite3.connect(uri, uri=True)
cursor = conn.cursor()

try:
    print(cursor.execute("SELECT itemID FROM itemAttachments WHERE parentItemID=2").fetchall())
except Exception as e:
    print("Error:", e)
