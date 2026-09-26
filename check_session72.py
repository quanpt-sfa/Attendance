import sqlite3

conn = sqlite3.connect('attendance.db')
c = conn.cursor()

# Get session info
c.execute('SELECT class_id FROM sessions WHERE session_id = 72')
session = c.fetchone()
class_id = session[0]
print(f'Session 72 belongs to class: {class_id}')

# Count students in class
c.execute('SELECT COUNT(*) FROM students WHERE class_id = ?', (class_id,))
print(f'Total students in class: {c.fetchone()[0]}')

# Count checkins
c.execute("SELECT COUNT(*) FROM checkins WHERE session_id = 72 AND check_type = 'in'")
print(f'Total checkins: {c.fetchone()[0]}')

# Find students who checked in but not in student list
c.execute("""
    SELECT DISTINCT c.student_id 
    FROM checkins c 
    WHERE c.session_id = 72 AND c.check_type = 'in'
    AND c.student_id NOT IN (SELECT student_id FROM students WHERE class_id = ?)
""", (class_id,))
orphan_checkins = c.fetchall()
print(f'Students checked in but NOT in class roster: {orphan_checkins}')

# Check for duplicate checkins
c.execute("""
    SELECT student_id, COUNT(*) as cnt 
    FROM checkins 
    WHERE session_id = 72 AND check_type = 'in'
    GROUP BY student_id 
    HAVING cnt > 1
""")
duplicates = c.fetchall()
print(f'Duplicate checkins: {duplicates}')

conn.close()
