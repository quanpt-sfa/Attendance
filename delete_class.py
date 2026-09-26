"""
Script xoa lop hoc truc tiep tu database
Chay khi server da dung
"""
import sqlite3
import sys

DB_FILE = 'attendance.db'

def delete_class(class_id):
    print(f"Deleting class: {class_id}")
    
    conn = sqlite3.connect(DB_FILE, timeout=30)
    cursor = conn.cursor()
    
    # Check if class exists
    cursor.execute('SELECT class_id FROM classes WHERE class_id = ?', (class_id,))
    if not cursor.fetchone():
        print(f"Class '{class_id}' not found!")
        conn.close()
        return False
    
    # Delete related data
    cursor.execute('''
        DELETE FROM checkins WHERE session_id IN 
        (SELECT session_id FROM sessions WHERE class_id = ?)
    ''', (class_id,))
    print(f"  - Deleted {cursor.rowcount} checkins")
    
    cursor.execute('DELETE FROM logs WHERE class_name = ?', (class_id,))
    print(f"  - Deleted {cursor.rowcount} logs")
    
    cursor.execute('DELETE FROM sessions WHERE class_id = ?', (class_id,))
    print(f"  - Deleted {cursor.rowcount} sessions")
    
    cursor.execute('DELETE FROM students WHERE class_id = ?', (class_id,))
    print(f"  - Deleted {cursor.rowcount} students")
    
    cursor.execute('DELETE FROM classes WHERE class_id = ?', (class_id,))
    print(f"  - Deleted class")
    
    conn.commit()
    conn.close()
    
    print("Done!")
    return True

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python delete_class.py <class_id>")
        print("Example: python delete_class.py Thu7_T13-15")
        sys.exit(1)
    
    class_id = sys.argv[1]
    delete_class(class_id)
