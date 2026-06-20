import sqlite3

db_path = "/home/ardo/Zotero/zotero.sqlite"
uri = f"file:{db_path}?mode=ro&nolock=1"
try:
    conn = sqlite3.connect(uri, uri=True)
    cursor = conn.cursor()
    
    tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    print(f"Total tables: {len(tables)}")
    
    if "itemAnnotations" in tables:
        cursor.execute("SELECT * FROM itemAnnotations LIMIT 1;")
        row = cursor.fetchone()
        columns = [description[0] for description in cursor.description]
        print("\nitemAnnotations columns:", columns)
        print("Sample row:", row)
    else:
        print("No itemAnnotations table.")
        
    print("\nTables with 'item':")
    for t in tables:
        if 'item' in t.lower():
            print(t)
            
except Exception as e:
    print(f"Error: {e}")
