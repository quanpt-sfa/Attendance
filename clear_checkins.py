import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

DB_FILE = 'attendance.db'

def clear_checkins():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Count before delete
    cursor.execute('SELECT COUNT(*) FROM checkins')
    count = cursor.fetchone()[0]
    print(f"Found {count} checkin records to delete.")
    
    # Delete all checkins
    cursor.execute('DELETE FROM checkins')
    
    conn.commit()
    conn.close()
    
    print(f"Deleted {count} checkin records successfully.")
    print("Done!")

if __name__ == '__main__':
    clear_checkins()
