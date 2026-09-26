import sqlite3
import os

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'attendance.db')

def fix_checkins_schema():
    if not os.path.exists(DB_FILE):
        print(f"Database not found at {DB_FILE}")
        return

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print(f"Fixing checkins schema for: {DB_FILE}")
    
    try:
        # 1. Check if session_id is missing in checkins
        cursor.execute("PRAGMA table_info(checkins)")
        columns = {col[1] for col in cursor.fetchall()}
        
        if 'session_id' in columns:
            print("session_id column already exists in checkins. No fix needed.")
            conn.close()
            return

        print("session_id column MISSING in checkins. Proceeding with migration...")
        
        # 2. Rename existing table
        cursor.execute("ALTER TABLE checkins RENAME TO checkins_old")
        print("Renamed 'checkins' to 'checkins_old'")
        
        # 3. Create new table with correct schema
        # Schema based on common sense usage in server.py (which selects count(*) where session_id matches)
        cursor.execute('''
            CREATE TABLE checkins (
                checkin_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                student_id TEXT,
                check_type TEXT DEFAULT 'in', -- 'in' or 'out'
                check_time TEXT,
                created_at TEXT,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            )
        ''')
        print("Created new 'checkins' table")
        
        # 4. Migrate data?
        # Old schema: class_name, session_date, session_period, student_id, student_name, check_type, check_time
        # New link needs session_id.
        # We can try to find session_id from sessions table matching session_date and maybe class_id?
        # But old checkins only have class_name.
        # And classes table was just reset.
        # So it's very hard to link old checkins.
        # We will skip migration of old checkins for now to ensure system stability for new data.
        # Old data is preserved in checkins_old if needed later.
        
        print("Skipping data migration for checkins due to missing linkage (classes/sessions reset).")
        print("Old checkins preserved in 'checkins_old'.")
        
        conn.commit()
        print("Checkins schema fix completed successfully.")
        
    except Exception as e:
        print(f"Error fixing checkins schema: {e}")
        conn.rollback()
        
    conn.close()

if __name__ == "__main__":
    fix_checkins_schema()
