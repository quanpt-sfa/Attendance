# -*- coding: utf-8 -*-
import sqlite3
import sys
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('attendance.db')
c = conn.cursor()

# Check session 72
c.execute('SELECT class_id FROM sessions WHERE session_id = 72')
class_id = c.fetchone()[0]
print(f'Session 72 class: {class_id}')

# Check student 23644361
c.execute('SELECT * FROM students WHERE student_id = ?', ('23644361',))
students = c.fetchall()
print(f'Student 23644361 in all classes: {students}')

c.execute('SELECT * FROM students WHERE student_id = ? AND class_id = ?', ('23644361', class_id))
s = c.fetchone()
print(f'Student in this class: {s}')

# Check checkins for this student
c.execute('SELECT * FROM checkins WHERE session_id = 72 AND student_id = ?', ('23644361',))
checkins = c.fetchall()
print(f'Checkins for 23644361: {checkins}')

# Total checkout count
c.execute("SELECT COUNT(*) FROM checkins WHERE session_id = 72 AND check_type = 'out'")
print(f'Total checkouts in session 72: {c.fetchone()[0]}')

# Latest 5 checkouts
c.execute("SELECT * FROM checkins WHERE session_id = 72 AND check_type = 'out' ORDER BY rowid DESC LIMIT 5")
print(f'Latest checkouts: {c.fetchall()}')

conn.close()
