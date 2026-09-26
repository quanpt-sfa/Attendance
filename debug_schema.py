import sqlite3
import os

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'attendance.db')

def check_schema():
    if not os.path.exists(DB_FILE):
        print(f"Database not found at {DB_FILE}")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    print(f"Checking database: {DB_FILE}")
    
    # List all tables and their columns
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    
    for t in tables:
        table_name = t[0]
        print(f"\nColumns in '{table_name}':")
        try:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            for col in columns:
                # cid, name, type, notnull, dflt_value, pk
                print(f"  {col[1]} ({col[2]}) PK={col[5]}")
        except Exception as e:
            print(f"Error checking {table_name}: {e}")
        
    conn.close()

if __name__ == "__main__":
    check_schema()
