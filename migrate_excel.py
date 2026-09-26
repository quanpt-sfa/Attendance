import openpyxl
import sqlite3
import sys
from datetime import datetime

# Fix encoding for Windows console
sys.stdout.reconfigure(encoding='utf-8')

DB_FILE = 'attendance.db'
EXCEL_FILE = 'backup_diemdanh.xlsx'

def migrate():
    print(f"Reading {EXCEL_FILE}...")
    try:
        wb = openpyxl.load_workbook(EXCEL_FILE)
        sheet = wb.active
    except Exception as e:
        print(f"Cannot read file: {e}")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Ensure checkins table has class_id
    cursor.execute("PRAGMA table_info(checkins)")
    cols = {row[1] for row in cursor.fetchall()}
    if 'class_id' not in cols:
        print("Migrating schema: Adding class_id to checkins table...")
        try:
            cursor.execute("ALTER TABLE checkins ADD COLUMN class_id TEXT")
            # We might want to backfill this from sessions if possible, but for new inserts it's fine.
        except Exception as e:
            print(f"Schema migration error: {e}")

    # Cache for sessions: (class_id, date_str) -> session_id
    session_cache = {}

    rows = list(sheet.iter_rows(min_row=2, values_only=True))
    print(f"Found {len(rows)} rows. Processing...")
    
    count_in = 0
    count_out = 0
    
    first_row_debug = True

    for row in rows:
        # Columns: ClassName(0), MSSV(1), HoTen(2), CheckInTime(3), CheckOutTime(4), Status(5)
        class_id = row[0]
        student_id = str(row[1]).strip() if row[1] else None
        check_in_time = row[3]
        check_out_time = row[4]
        
        if first_row_debug:
             print(f"DEBUG ROW 1: Class={class_id}, Student={student_id}, In={check_in_time}, Out={check_out_time}")
             first_row_debug = False

        if not class_id or not student_id:
            continue
            
        # Helper to process a check time
        def process_check(time_val, check_type):
            if not time_val:
                return 0
            
            # Parse datetime
            dt = None
            if isinstance(time_val, datetime):
                dt = time_val
            elif isinstance(time_val, str):
                try:
                    # Try format "18:16:15 16/1/2026"
                    dt = datetime.strptime(time_val, '%H:%M:%S %d/%m/%Y')
                except:
                    try:
                         # Fallback to standard
                         dt = datetime.strptime(time_val, '%Y-%m-%d %H:%M:%S')
                    except:
                         pass
            
            if not dt:
                return 0
                
            date_str = dt.strftime('%Y-%m-%d')
            full_time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # Ensure Class Exists
            cursor.execute('SELECT 1 FROM classes WHERE class_id = ?', (class_id,))
            if not cursor.fetchone():
                print(f"  + Auto-creating missing class: {class_id}")
                cursor.execute('''
                    INSERT INTO classes (class_id, class_name, num_sessions, created_at, updated_at)
                    VALUES (?, ?, 15, ?, ?)
                ''', (class_id, class_id, datetime.now().isoformat(), datetime.now().isoformat()))

            # Find/Get Session
            sess_key = (class_id, date_str)
            if sess_key in session_cache:
                session_id = session_cache[sess_key]
            else:
                # Check DB
                cursor.execute('SELECT session_id FROM sessions WHERE class_id = ? AND session_date = ?', (class_id, date_str))
                res = cursor.fetchone()
                if res:
                    session_id = res[0]
                else:
                    # Create Session 
                    cursor.execute('SELECT MAX(session_number) FROM sessions WHERE class_id = ?', (class_id,))
                    max_sess = cursor.fetchone()[0]
                    next_sess = (max_sess or 0) + 1
                    
                    cursor.execute('''
                        INSERT INTO sessions (class_id, session_number, session_date, is_open)
                        VALUES (?, ?, ?, 0)
                    ''', (class_id, next_sess, date_str))
                    session_id = cursor.lastrowid
                    # print(f"  + Created session {next_sess} for {class_id} on {date_str}")
                    
                session_cache[sess_key] = session_id

            # Ensure Student Exists (Optional but recommended for consistency)
            # cursor.execute('INSERT OR IGNORE INTO students (student_id, class_id) VALUES (?, ?)', (student_id, class_id))

            # Insert Checkin
            try:
                cursor.execute('''
                    INSERT INTO checkins (session_id, student_id, class_id, check_type, check_time)
                    VALUES (?, ?, ?, ?, ?)
                ''', (session_id, student_id, class_id, check_type, full_time_str))
                return 1
            except sqlite3.IntegrityError:
                # Already exists
                return 0
            except Exception as e:
                print(f"Error inserting checkin: {e}")
                return 0

        count_in += process_check(check_in_time, 'IN')
        count_out += process_check(check_out_time, 'OUT')

    conn.commit()
    conn.close()
    
    print("-" * 30)
    print(f"Migration Completed.")
    print(f"Imported {count_in} Check-IN records.")
    print(f"Imported {count_out} Check-OUT records.")

if __name__ == '__main__':
    migrate()
