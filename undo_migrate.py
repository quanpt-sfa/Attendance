import openpyxl
import sqlite3
import sys

# Fix encoding
sys.stdout.reconfigure(encoding='utf-8')

DB_FILE = 'attendance.db'
EXCEL_FILE = 'backup_diemdanh.xlsx'

def undo():
    print(f"Reading {EXCEL_FILE} to undo import...")
    try:
        wb = openpyxl.load_workbook(EXCEL_FILE)
        sheet = wb.active
    except Exception as e:
        print(f"Cannot read file: {e}")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    rows = list(sheet.iter_rows(min_row=2, values_only=True))
    deleted_count = 0
    
    # We will delete all checkins for the student_id + class_id pairs found in the file
    # unique pairs to avoid redundant deletes
    targets = set()

    for row in rows:
        class_id = row[0]
        student_id = str(row[1]).strip() if row[1] else None
        
        if class_id and student_id:
            targets.add((class_id, student_id))
            
    print(f"Found {len(targets)} unique student/class pairs to clean up.")
    
    for class_id, student_id in targets:
        try:
            cursor.execute('''
                DELETE FROM checkins 
                WHERE class_id = ? AND student_id = ?
            ''', (class_id, student_id))
            deleted_count += cursor.rowcount
        except Exception as e:
            print(f"Error deleting checking for {student_id} in {class_id}: {e}")
            
    conn.commit()
    conn.close()
    
    print("-" * 30)
    print(f"Undo Completed.")
    print(f"Deleted {deleted_count} checkin records.")

if __name__ == '__main__':
    undo()
