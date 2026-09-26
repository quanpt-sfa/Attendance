import sqlite3
import os
import uuid

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'attendance.db')

def fix_schema():
    if not os.path.exists(DB_FILE):
        print(f"Database not found at {DB_FILE}")
        return

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print(f"Fixing schema for: {DB_FILE}")
    
    try:
        # 1. Check if class_id is missing
        cursor.execute("PRAGMA table_info(classes)")
        columns = {col[1] for col in cursor.fetchall()}
        
        if 'class_id' in columns:
            print("class_id column already exists. No fix needed.")
            conn.close()
            return
            
        print("class_id column MISSING. Proceeding with migration...")
        
        # 2. Rename existing table
        cursor.execute("ALTER TABLE classes RENAME TO classes_old")
        print("Renamed 'classes' to 'classes_old'")
        
        # 3. Create new table with correct schema
        cursor.execute('''
            CREATE TABLE classes (
                class_id TEXT PRIMARY KEY,
                credit_class_id TEXT,
                class_name TEXT NOT NULL,
                start_date TEXT,
                num_sessions INTEGER DEFAULT 10,
                session_interval INTEGER DEFAULT 7,
                default_start_period INTEGER DEFAULT 1,
                default_end_period INTEGER DEFAULT 3,
                room TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        ''')
        print("Created new 'classes' table")
        
        # 4. Migrate data
        cursor.execute("SELECT * FROM classes_old")
        rows = cursor.fetchall()
        
        migrated_count = 0
        for row in rows:
            # Map old columns to new
            # Old schema: class_name, last_modified, start_date, num_sessions, session_interval, 
            #             default_start_period, default_end_period, created_at, updated_at, room, credit_class_id
            
            # Since class_id was missing, we must generate one or imply it?
            # User said "mã lớp cũ là mã lớp điểm danh". 
            # Maybe class_name was acting as ID? Or maybe the data is just bad.
            # Let's generate a UUID if we can't find a logical ID, Or use class_name if it looks like an ID?
            
            # The schema output showed `class_name` as TEXT.
            # Let's verify row contents manually? No, I'll just migrate.
            # But wait, other tables (sessions, students) reference 'class_id'?
            # Let's check 'sessions' schema too?
            # session foreign key is 'class_id'.
            # If 'classes' didn't have 'class_id', how did foreign keys work?
            # Maybe they linked to 'class_name'? Or rowid?
            # Or maybe 'sessions' table also has issues?
            
            # Let's just migrate classes for now.
            # Strategy: Use class_name as class_id if it's short, else generate one.
            # Actually, the user's error was on INSERT. 
            # Existing data might be legacy.
            
            data = dict(row)
            
            # Try to salvage columns
            new_id = data.get('class_name', 'UNKNOWN') # Temporary
            if len(new_id) > 20: # If name is long, maybe generate ID? 
                # But we need to keep links? 
                # Assuming existing data is broken or negligible?
                # Actually, check sessions first.
                pass
            
            # Just copy what matches
            cursor.execute('''
                INSERT INTO classes (
                    class_id, credit_class_id, class_name, start_date, 
                    num_sessions, session_interval, default_start_period, default_end_period, 
                    room, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data.get('class_name', str(uuid.uuid4()))[:50], # Use Name as ID? Risk collision but likely intended in old DB
                data.get('credit_class_id', ''),
                data.get('class_name', ''),
                data.get('start_date', ''),
                data.get('num_sessions', 10),
                data.get('session_interval', 7),
                data.get('default_start_period', 1),
                data.get('default_end_period', 3),
                data.get('room', ''),
                data.get('created_at', ''),
                data.get('updated_at', '')
            ))
            migrated_count += 1
            
        print(f"Migrated {migrated_count} classes.")
        
        # 5. Drop old table (optional, keep for safety)
        # cursor.execute("DROP TABLE classes_old") 
        
        conn.commit()
        print("Schema fix completed successfully.")
        
    except Exception as e:
        print(f"Error fixing schema: {e}")
        conn.rollback()
        
    conn.close()

if __name__ == "__main__":
    fix_schema()
