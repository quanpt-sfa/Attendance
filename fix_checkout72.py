# -*- coding: utf-8 -*-
import sqlite3
from datetime import datetime

conn = sqlite3.connect('attendance.db')
c = conn.cursor()

# Get class_id for session 72
c.execute('SELECT class_id FROM sessions WHERE session_id = 72')
class_id = c.fetchone()[0]

# Find students who checked in but not checked out
c.execute("""
    SELECT student_id FROM checkins 
    WHERE session_id = 72 AND check_type = 'in' 
    AND student_id NOT IN (
        SELECT student_id FROM checkins 
        WHERE session_id = 72 AND check_type = 'out'
    )
""")
students = c.fetchall()
print(f'Students to checkout: {len(students)}')

# Add checkout for each
now = datetime.now().strftime('%H:%M:%S %d/%m/%Y')
for s in students:
    c.execute('''
        INSERT INTO checkins (session_id, student_id, class_id, check_type, check_time) 
        VALUES (?, ?, ?, ?, ?)
    ''', (72, s[0], class_id, 'out', now))
    print(f'  Checked out: {s[0]}')

conn.commit()
conn.close()
print('Done!')
