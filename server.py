#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Server điểm danh với SQLite backend - Phiên bản 2.0
Hỗ trợ quản lý lớp học, sinh viên, buổi học và điểm danh
"""

import json
import sqlite3
import os
import base64
import uuid
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs, unquote
import urllib.request
import urllib.error
from datetime import datetime, timedelta
import unicodedata
import google_service

# Cấu hình
PORT = 8000
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'attendance.db')
PHOTOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'photos')

# Đảm bảo thư mục photos tồn tại
os.makedirs(PHOTOS_DIR, exist_ok=True)

# ===== Tiện ích sắp xếp tiếng Việt chuẩn (Tên -> Họ & tên đệm -> Lớp -> MSSV) =====
VIETNAMESE_ALPHABET = [
    'a', 'à', 'á', 'ả', 'ã', 'ạ',
    'ă', 'ằ', 'ắ', 'ẳ', 'ẵ', 'ặ',
    'â', 'ầ', 'ấ', 'ẩ', 'ẫ', 'ậ',
    'b', 'c', 'd', 'đ',
    'e', 'è', 'é', 'ẻ', 'ẽ', 'ẹ',
    'ê', 'ề', 'ế', 'ể', 'ễ', 'ệ',
    'f', 'g', 'h',
    'i', 'ì', 'í', 'ỉ', 'ĩ', 'ị',
    'j', 'k', 'l', 'm', 'n',
    'o', 'ò', 'ó', 'ỏ', 'õ', 'ọ',
    'ô', 'ồ', 'ố', 'ổ', 'ỗ', 'ộ',
    'ơ', 'ờ', 'ớ', 'ở', 'ỡ', 'ợ',
    'p', 'q', 'r', 's', 't',
    'u', 'ù', 'ú', 'ủ', 'ũ', 'ụ',
    'ư', 'ừ', 'ứ', 'ử', 'ữ', 'ự',
    'v', 'w', 'x',
    'y', 'ỳ', 'ý', 'ỷ', 'ỹ', 'ỵ',
    'z'
]
VI_CHAR_ORDER = {ch: i for i, ch in enumerate(VIETNAMESE_ALPHABET)}

def vi_char_sort_key(text):
    text = unicodedata.normalize('NFC', str(text or '').lower().strip())
    return [VI_CHAR_ORDER.get(ch, ord(ch) + 1000) for ch in text]

def vietnamese_student_sort_key(s):
    """
    Sắp xếp chuẩn danh sách sinh viên theo thứ tự giáo dục Việt Nam:
    1. Tên (first_name)
    2. Họ & tên đệm (last_name)
    3. Tên lớp / Lớp (class_name hoặc class_id)
    4. MSSV (student_id)
    """
    first_name = (s.get('first_name') or '').strip()
    last_name = (s.get('last_name') or '').strip()
    full_name = (s.get('full_name') or s.get('name') or '').strip()

    if not first_name and full_name:
        parts = full_name.split()
        first_name = parts[-1] if parts else ''
        last_name = ' '.join(parts[:-1]) if len(parts) > 1 else ''
    elif not last_name and full_name and first_name:
        if full_name.endswith(first_name):
            last_name = full_name[:-len(first_name)].strip()

    class_key = str(s.get('class_name') or s.get('class_id') or s.get('className') or '').strip().lower()
    student_id = str(s.get('student_id') or s.get('id') or '').strip().lower()

    return (
        vi_char_sort_key(first_name),
        vi_char_sort_key(last_name),
        class_key,
        student_id
    )

def sort_vietnamese_students(students_list):
    """Sắp xếp danh sách sinh viên theo thứ tự chuẩn Việt Nam: Tên -> Họ -> Lớp -> MSSV"""
    return sorted(students_list, key=vietnamese_student_sort_key)


def init_database():
    """Khởi tạo database và tạo bảng nếu chưa có"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Bảng lớp học
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS classes (
            class_id TEXT PRIMARY KEY,
            credit_class_id TEXT,
            class_name TEXT NOT NULL,
            start_date TEXT,
            num_sessions INTEGER DEFAULT 10,
            session_interval INTEGER DEFAULT 7,
            default_start_period INTEGER DEFAULT 1,
            default_end_period INTEGER DEFAULT 3,
            room TEXT,
            google_sheet_url TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Bảng buổi học (tự động phát sinh)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id TEXT NOT NULL,
            session_number INTEGER NOT NULL,
            session_date TEXT NOT NULL,
            start_period INTEGER DEFAULT 1,
            end_period INTEGER DEFAULT 3,
            is_open INTEGER DEFAULT 0,
            opened_at TEXT,
            closed_at TEXT,
            FOREIGN KEY (class_id) REFERENCES classes(class_id),
            UNIQUE(class_id, session_number)
        )
    ''')
    
    # Bảng sinh viên
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT NOT NULL,
            class_id TEXT NOT NULL,
            last_name TEXT,
            first_name TEXT,
            full_name TEXT,
            birth_date TEXT,
            gender TEXT,
            photo_path TEXT,
            created_at TEXT,
            PRIMARY KEY (student_id, class_id),
            FOREIGN KEY (class_id) REFERENCES classes(class_id)
        )
    ''')
    
    # Bảng điểm danh
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            class_id TEXT NOT NULL,
            check_type TEXT NOT NULL,
            check_time TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id),
            UNIQUE(session_id, student_id, check_type)
        )
    ''')
    
    # Bảng logs
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT,
            session_id INTEGER,
            class_id TEXT,
            student_id TEXT,
            check_type TEXT,
            result TEXT,
            note TEXT
        )
    ''')
    
    # Bảng lý do vắng
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS absences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            class_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id),
            UNIQUE(session_id, student_id)
        )
    ''')
    
    # Migration: Thêm các cột mới nếu chưa có
    migrate_database(conn, cursor)
    
    conn.commit()
    conn.close()
    print(f"[OK] Database: {DB_FILE}")


def migrate_database(conn, cursor):
    """Thêm các cột mới vào database cũ nếu cần"""
    
    # Lấy danh sách cột hiện có của bảng classes
    cursor.execute("PRAGMA table_info(classes)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    
    # Các cột cần thêm vào classes
    new_cols = {
        'start_date': 'TEXT',
        'num_sessions': 'INTEGER DEFAULT 10',
        'session_interval': 'INTEGER DEFAULT 7',
        'default_start_period': 'INTEGER DEFAULT 1',
        'default_end_period': 'INTEGER DEFAULT 3',
        'default_end_period': 'INTEGER DEFAULT 3',
        'room': 'TEXT',
        'credit_class_id': 'TEXT',
        'is_conference': 'INTEGER DEFAULT 0',
        'google_sheet_url': 'TEXT',
        'created_at': 'TEXT',
        'updated_at': 'TEXT'
    }
    
    for col, col_type in new_cols.items():
        if col not in existing_cols:
            try:
                cursor.execute(f'ALTER TABLE classes ADD COLUMN {col} {col_type}')
                print(f"  ✓ Added column classes.{col}")
            except:
                pass
    
    # Lấy danh sách cột hiện có của bảng students
    cursor.execute("PRAGMA table_info(students)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    
    student_new_cols = {
        'last_name': 'TEXT',
        'first_name': 'TEXT',
        'full_name': 'TEXT',
        'email': 'TEXT',
        'birth_date': 'TEXT',
        'gender': 'TEXT',
        'photo_path': 'TEXT',
        'card_uid': 'TEXT',
        'card_registered_at': 'TEXT',
        'is_lecturer': 'INTEGER DEFAULT 0',
        'created_at': 'TEXT'
    }
    
    for col, col_type in student_new_cols.items():
        if col not in existing_cols:
            try:
                cursor.execute(f'ALTER TABLE students ADD COLUMN {col} {col_type}')
                print(f"  ✓ Added column students.{col}")
            except:
                pass

    # Lấy danh sách cột hiện có của bảng checkins
    cursor.execute("PRAGMA table_info(checkins)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    
    checkin_new_cols = {
        'bonus_points': 'INTEGER DEFAULT 0',
        'bonus_reason': 'TEXT'
    }
    
    for col, col_type in checkin_new_cols.items():
        if col not in existing_cols:
            try:
                cursor.execute(f'ALTER TABLE checkins ADD COLUMN {col} {col_type}')
                print(f"  ✓ Added column checkins.{col}")
            except:
                pass
    
    conn.commit()


def auto_close_past_sessions():
    """Tự động đóng các buổi đã qua ngày"""
    today = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE sessions 
        SET is_open = 0, closed_at = ?
        WHERE is_open = 1 AND session_date < ?
    ''', (datetime.now().isoformat(), today))
    
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    
    if affected > 0:
        print(f"[OK] Da tu dong dong {affected} buoi hoc da qua ngay")
    
    return affected


class AttendanceHandler(SimpleHTTPRequestHandler):
    """Handler xử lý cả file tĩnh và API"""
    
    def send_json(self, data, status=200):
        """Gửi response JSON"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def send_error_json(self, message, status=400):
        """Gửi lỗi dạng JSON"""
        self.send_json({'error': message}, status)
    
    def get_post_data(self):
        """Đọc và parse JSON từ request body"""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return {}
        body = self.rfile.read(content_length).decode('utf-8')
        return json.loads(body)
    
    def do_OPTIONS(self):
        """Xử lý CORS preflight"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def do_GET(self):
        """Xử lý GET request"""
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        
        # API endpoints
        if path == '/api/classes':
            self.get_classes()
        elif path.startswith('/api/classes/') and path.endswith('/google_sheet_status'):
            class_id = path.split('/')[3]
            self.get_class_google_sheet_status(class_id)
        elif path.startswith('/api/classes/') and '/sessions' not in path:
            class_id = path.split('/')[3]
            self.get_class(class_id)
        elif path == '/api/sessions':
            class_id = params.get('class_id', [''])[0]
            self.get_sessions(class_id)
        elif path == '/api/sessions/current':
            self.get_current_session()
        elif path == '/api/students':
            class_id = params.get('class_id', [''])[0]
            self.get_students(class_id)
        elif path.startswith('/api/students/') and '/photo' in path:
            student_id = path.split('/')[3]
            class_id = params.get('class_id', [''])[0]
            self.get_student_photo(student_id, class_id)
        elif path == '/api/checkins':
            session_id = params.get('session_id', [''])[0]
            self.get_checkins(session_id)
        elif path == '/api/absences':
            session_id = params.get('session_id', [''])[0]
            self.get_absences(session_id)
        elif path == '/api/logs':
            session_id = params.get('session_id', [''])[0]
            self.get_logs(session_id)
        elif path == '/api/roster':
            # Backward compatibility
            class_name = params.get('class', [''])[0]
            self.get_roster_legacy(class_name)
        elif path == '/api/email_template':
            self.get_email_template()
        elif path == '/api/auth/google/status':
            self.get_google_auth_status()
        elif path == '/api/auth/google/login':
            self.handle_google_login(params)
        elif path == '/api/auth/google/callback':
            self.handle_google_callback(params)
        else:
            # Serve static files
            super().do_GET()
    
    def do_POST(self):
        """Xử lý POST request"""
        path = urlparse(self.path).path
        
        if path == '/api/classes':
            self.create_class()
        elif path.startswith('/api/sessions/') and path.endswith('/open'):
            session_id = path.split('/')[3]
            self.open_session(session_id)
        elif path.startswith('/api/sessions/') and path.endswith('/close'):
            session_id = path.split('/')[3]
            self.close_session(session_id)
        elif path == '/api/students':
            self.create_student()
        elif path == '/api/students/import':
            self.import_students()
        elif path.startswith('/api/students/') and path.endswith('/photo'):
            student_id = path.split('/')[3]
            self.upload_photo(student_id)
        elif path.startswith('/api/students/') and path.endswith('/transfer'):
            student_id = path.split('/')[3]
            self.transfer_student(student_id)
        elif path.startswith('/api/students/') and path.endswith('/card/sync'):
            student_id = path.split('/')[3]
            self.sync_card_uid(student_id)
        elif path == '/api/students/card/sync-all':
            self.sync_all_cards()
        elif path == '/api/checkins':
            self.save_checkin()
        elif path == '/api/checkins/bonus':
            self.update_checkin_bonus()
        elif path == '/api/absences':
            self.save_absence()
        elif path == '/api/logs':
            self.save_log()
        elif path == '/api/send_email_report':
            self.send_email_report()
        elif path == '/api/email_template':
            self.save_email_template()
        elif path.startswith('/api/sessions/') and path.endswith('/sync_google_sheet'):
            session_id = path.split('/')[3]
            self.sync_session_google_sheet(session_id)
        elif path.startswith('/api/classes/') and path.endswith('/sync_google_sheet'):
            class_id = path.split('/')[3]
            self.sync_class_google_sheet(class_id)
        elif path == '/api/google_sheet/test':
            self.test_google_sheet()
        elif path == '/api/auth/google/logout':
            self.handle_google_logout()
        elif path == '/api/google/create_sheet':
            self.handle_google_create_sheet()
        else:
            self.send_error_json('Unknown endpoint', 404)
    
    def do_PUT(self):
        """Xử lý PUT request"""
        path = urlparse(self.path).path
        
        if path.startswith('/api/classes/'):
            class_id = path.split('/')[3]
            self.update_class(class_id)
        elif path.startswith('/api/students/') and path.endswith('/card'):
            student_id = path.split('/')[3]
            self.update_card_uid(student_id)
        elif path.startswith('/api/students/'):
            student_id = path.split('/')[3]
            self.update_student(student_id)
        elif path.startswith('/api/sessions/'):
            session_id = path.split('/')[3]
            self.update_session(session_id)
        else:
            self.send_error_json('Unknown endpoint', 404)
    
    def do_DELETE(self):
        """Xử lý DELETE request"""
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        
        if path == '/api/classes':
            # Delete all - backward compatibility
            self.delete_all_data()
        elif path.startswith('/api/classes/'):
            parts = path.split('/')
            class_id = parts[3]
            if len(parts) > 4 and parts[4] == 'students':
                self.delete_students_in_class(class_id)
            else:
                self.delete_class(class_id)
        elif path.startswith('/api/students/') and path.endswith('/card'):
            student_id = unquote(path.split('/')[3])
            class_id = params.get('class_id', [''])[0]
            self.delete_card_uid(student_id, class_id)
        elif path.startswith('/api/students/'):
            student_id = unquote(path.split('/')[3])
            class_id = params.get('class_id', [''])[0]
            self.delete_student(student_id, class_id)
        elif path == '/api/checkins':
            session_id = params.get('session_id', [''])[0]
            student_id = params.get('student_id', [''])[0]
            check_type = params.get('type', [''])[0]
            self.delete_checkin(session_id, student_id, check_type)
        elif path == '/api/absences':
            session_id = params.get('session_id', [''])[0]
            student_id = params.get('student_id', [''])[0]
            self.delete_absence(session_id, student_id)
        else:
            self.send_error_json('Unknown endpoint', 404)
    
    # ===== Classes API =====
    
    def get_classes(self):
        """Lấy danh sách lớp"""
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM classes ORDER BY created_at DESC')
        rows = cursor.fetchall()
        conn.close()
        
        classes = [dict(row) for row in rows]
        self.send_json(classes)
    
    def get_class(self, class_id):
        """Lấy thông tin lớp"""
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM classes WHERE class_id = ?', (class_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            self.send_json(dict(row))
        else:
            self.send_error_json('Class not found', 404)
    
    def create_class(self):
        """Tạo lớp mới và phát sinh các buổi học"""
        try:
            data = self.get_post_data()
            
            # Backward compatibility với API cũ
            if 'className' in data and 'students' in data:
                return self.save_class_legacy(data)
            
            class_id = data.get('class_id', '').strip()
            class_name = data.get('class_name', '').strip()
            start_date = data.get('start_date', '')
            num_sessions = int(data.get('num_sessions', 10))
            session_interval = int(data.get('session_interval', 7))
            default_start_period = int(data.get('default_start_period', 1))
            default_end_period = int(data.get('default_end_period', 3))
            room = data.get('room', '').strip()
            credit_class_id = data.get('credit_class_id', '').strip()
            is_conference = int(data.get('is_conference', 0))
            google_sheet_url = data.get('google_sheet_url', '').strip()
            
            if not class_id or not class_name:
                self.send_error_json('Thiếu mã lớp hoặc tên lớp')
                return
            
            now = datetime.now().isoformat()
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            # Kiểm tra nếu link Sheet bị trùng với lớp khác
            if google_sheet_url:
                target_sheet_id = google_service.extract_spreadsheet_id(google_sheet_url)
                if target_sheet_id:
                    cursor.execute('SELECT class_id, class_name, google_sheet_url FROM classes')
                    for other in cursor.fetchall():
                        other_url = other['google_sheet_url'] or ''
                        if other_url and google_service.extract_spreadsheet_id(other_url) == target_sheet_id:
                            conn.close()
                            self.send_error_json(
                                f"Link Google Sheet này đã được liên kết với lớp '{other['class_name']}' ({other['class_id']}). "
                                f"Mỗi lớp học bắt buộc phải có 1 file Google Sheet riêng biệt để tránh ghi đè dữ liệu. Vui lòng bấm 'Tự tạo Sheet' hoặc nhập link riêng.",
                                400
                            )
                            return
            
            # Tạo lớp
            cursor.execute('''
                INSERT INTO classes (class_id, class_name, start_date, num_sessions, 
                    session_interval, default_start_period, default_end_period, room, credit_class_id, is_conference, google_sheet_url, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (class_id, class_name, start_date, num_sessions, session_interval,
                  default_start_period, default_end_period, room, credit_class_id, is_conference, google_sheet_url, now, now))
            
            # Phát sinh các buổi học
            if is_conference and not start_date:
                # Với hội thảo, tạo 1 buổi duy nhất với ngày hôm nay
                today = datetime.now().strftime('%Y-%m-%d')
                cursor.execute('''
                    INSERT INTO sessions (class_id, session_number, session_date, 
                        start_period, end_period, is_open)
                    VALUES (?, ?, ?, ?, ?, 0)
                ''', (class_id, 1, today, default_start_period, default_end_period))
                num_sessions = 1
            elif start_date:
                base_date = datetime.strptime(start_date, '%Y-%m-%d')
                for i in range(num_sessions):
                    session_date = base_date + timedelta(days=i * session_interval)
                    cursor.execute('''
                        INSERT INTO sessions (class_id, session_number, session_date, 
                            start_period, end_period, is_open)
                        VALUES (?, ?, ?, ?, ?, 0)
                    ''', (class_id, i + 1, session_date.strftime('%Y-%m-%d'),
                          default_start_period, default_end_period))
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True, 'class_id': class_id, 'sessions_created': num_sessions})
        except sqlite3.IntegrityError:
            self.send_error_json('Mã lớp đã tồn tại')
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    def update_class(self, class_id):
        """Cập nhật lớp"""
        try:
            class_id = unquote(class_id)
            data = self.get_post_data()
            now = datetime.now().isoformat()
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            # Fetch existing class first
            cursor.execute('SELECT * FROM classes WHERE class_id = ?', (class_id,))
            if not cursor.fetchone():
                conn.close()
                self.send_error_json('Không tìm thấy lớp học', 404)
                return
            
            fields = []
            values = []
            
            if 'class_name' in data:
                fields.append('class_name = ?')
                values.append(data['class_name'])
            if 'room' in data:
                fields.append('room = ?')
                values.append(data['room'])
            if 'credit_class_id' in data:
                fields.append('credit_class_id = ?')
                values.append(data['credit_class_id'])
            if 'is_conference' in data:
                fields.append('is_conference = ?')
                values.append(int(data['is_conference']))
            if 'google_sheet_url' in data:
                sheet_url = data['google_sheet_url'].strip()
                if sheet_url:
                    target_id = google_service.extract_spreadsheet_id(sheet_url)
                    if target_id:
                        cursor.execute('SELECT class_id, class_name, google_sheet_url FROM classes WHERE class_id != ?', (class_id,))
                        for other in cursor.fetchall():
                            other_url = other['google_sheet_url'] or ''
                            if other_url and google_service.extract_spreadsheet_id(other_url) == target_id:
                                conn.close()
                                self.send_error_json(
                                    f"Link Google Sheet này đã được liên kết với lớp '{other['class_name']}' ({other['class_id']}). "
                                    f"Mỗi lớp học bắt buộc phải có 1 file Sheet riêng biệt để tránh đổ chung và đè dữ liệu. Vui lòng bấm 'Tự tạo Sheet mới' hoặc dùng link riêng cho lớp này.",
                                    400
                                )
                                return
                fields.append('google_sheet_url = ?')
                values.append(sheet_url)
                
            fields.append('updated_at = ?')
            values.append(now)
            values.append(class_id)
            
            sql = f"UPDATE classes SET {', '.join(fields)} WHERE class_id = ?"
            cursor.execute(sql, values)
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    def delete_class(self, class_id):
        """Xóa lớp và tất cả dữ liệu liên quan"""
        conn = None
        try:
            # Decode URL encoding
            class_id = unquote(class_id)
            
            # Add timeout to avoid lock issues
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            
            # Xóa checkins của các buổi học
            cursor.execute('''
                DELETE FROM checkins WHERE session_id IN 
                (SELECT session_id FROM sessions WHERE class_id = ?)
            ''', (class_id,))
            
            # Xóa logs (logs table uses class_name, not class_id)
            cursor.execute('DELETE FROM logs WHERE class_name = ?', (class_id,))
            
            # Xóa sessions
            cursor.execute('DELETE FROM sessions WHERE class_id = ?', (class_id,))
            
            # Xóa students
            cursor.execute('DELETE FROM students WHERE class_id = ?', (class_id,))
            
            # Xóa class
            cursor.execute('DELETE FROM classes WHERE class_id = ?', (class_id,))
            
            conn.commit()
            
            self.send_json({'success': True})
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_error_json(str(e), 500)
        finally:
            if conn:
                conn.close()
    
    # ===== Sessions API =====
    
    def get_sessions(self, class_id):
        """Lấy danh sách buổi học của lớp"""
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT s.*, 
                (SELECT COUNT(*) FROM checkins c WHERE c.session_id = s.session_id AND c.check_type = 'in') as checkin_count,
                (SELECT COUNT(*) FROM students st WHERE st.class_id = s.class_id) as total_students
            FROM sessions s
            WHERE s.class_id = ?
            ORDER BY s.session_number
        ''', (class_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
        sessions = [dict(row) for row in rows]
        self.send_json(sessions)
    
    def get_current_session(self):
        """Lấy buổi học đang mở"""
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT s.*, c.class_name, c.is_conference, c.google_sheet_url
            FROM sessions s
            LEFT JOIN classes c ON s.class_id = c.class_id
            WHERE s.is_open = 1
            LIMIT 1
        ''')
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            self.send_json(dict(row))
        else:
            self.send_json(None)
    
    def open_session(self, session_id):
        """Mở buổi điểm danh"""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            # Đóng tất cả các buổi khác
            cursor.execute('''
                UPDATE sessions SET is_open = 0, closed_at = ?
                WHERE is_open = 1
            ''', (datetime.now().isoformat(),))
            
            # Mở buổi được chọn
            cursor.execute('''
                UPDATE sessions SET is_open = 1, opened_at = ?, closed_at = NULL
                WHERE session_id = ?
            ''', (datetime.now().isoformat(), session_id))
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True, 'session_id': session_id})
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    def close_session(self, session_id):
        """Đóng buổi điểm danh"""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE sessions SET is_open = 0, closed_at = ?
                WHERE session_id = ?
            ''', (datetime.now().isoformat(), session_id))
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    def update_session(self, session_id):
        """Cập nhật buổi học"""
        try:
            data = self.get_post_data()
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE sessions 
                SET session_date = ?, start_period = ?, end_period = ?
                WHERE session_id = ?
            ''', (data.get('session_date'), data.get('start_period'), 
                  data.get('end_period'), session_id))
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    # ===== Google Auth & Google Sheet API =====

    def get_google_auth_status(self):
        """Lấy trạng thái kết nối Google OAuth"""
        try:
            configured = google_service.is_key_configured()
            logged_in = google_service.is_logged_in()
            user = None
            if logged_in:
                token_info = google_service.get_token_info() or {}
                user = {
                    'email': token_info.get('email', ''),
                    'name': token_info.get('name', ''),
                    'picture': token_info.get('picture', '')
                }
            self.send_json({
                'success': True,
                'configured': configured,
                'logged_in': logged_in,
                'user': user
            })
        except Exception as e:
            self.send_error_json(str(e), 500)

    def handle_google_login(self, params):
        """Khởi tạo luồng đăng nhập Google OAuth"""
        try:
            if not google_service.is_key_configured():
                self.send_error_json('Không tìm thấy file key.json trong thư mục dự án', 400)
                return
            
            fmt = params.get('format', [''])[0]
            auth_url = google_service.get_auth_url()
            
            if fmt == 'json':
                self.send_json({'success': True, 'auth_url': auth_url})
            else:
                self.send_response(302)
                self.send_header('Location', auth_url)
                self.end_headers()
        except Exception as e:
            self.send_error_json(str(e), 500)

    def handle_google_callback(self, params):
        """Xử lý redirect callback từ Google sau khi người dùng cho phép"""
        try:
            code = params.get('code', [''])[0]
            error = params.get('error', [''])[0]
            
            if error:
                html = f"""<!DOCTYPE html><html><body style="font-family:sans-serif;background:#0b1220;color:#ef4444;text-align:center;padding:50px;">
                <h2>❌ Đăng nhập không thành công: {error}</h2>
                <button onclick="window.close()" style="padding:10px 20px;margin-top:20px;cursor:pointer;">Đóng cửa sổ</button></body></html>"""
                self.send_response(400)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
                return
            
            if not code:
                self.send_error_json('Missing code parameter', 400)
                return
            
            user_data = google_service.exchange_code_for_token(code)
            
            html = f"""<!DOCTYPE html>
            <html lang="vi">
            <head>
              <meta charset="utf-8">
              <title>Kết nối Google thành công</title>
              <style>
                body {{ font-family: system-ui, sans-serif; background: #0b1220; color: #e5e7eb; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
                .card {{ background: #1e293b; border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 32px; text-align: center; max-width: 420px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
                .icon {{ font-size: 50px; margin-bottom: 16px; }}
                h2 {{ color: #22c55e; margin: 0 0 12px; }}
                p {{ color: #94a3b8; font-size: 14px; margin-bottom: 20px; line-height: 1.5; }}
                .user-badge {{ display: inline-flex; align-items: center; gap: 8px; background: rgba(34,197,94,0.1); border: 1px solid #22c55e; padding: 8px 18px; border-radius: 20px; font-weight: 600; color: #4ade80; font-size: 15px; }}
              </style>
            </head>
            <body>
              <div class="card">
                <div class="icon">🎉</div>
                <h2>Kết nối thành công!</h2>
                <div class="user-badge">👤 {user_data.get('email', 'Tài khoản Google')}</div>
                <p style="margin-top:16px;">Tài khoản Google của bạn đã được kết nối với phần mềm điểm danh. Cửa sổ này sẽ tự đóng lại trong giây lát...</p>
              </div>
              <script>
                if (window.opener) {{
                  window.opener.postMessage({{ type: 'GOOGLE_AUTH_SUCCESS', email: '{user_data.get('email', '')}' }}, '*');
                  setTimeout(() => window.close(), 1800);
                }} else {{
                  setTimeout(() => {{ window.location.href = '/index.html?auth=success'; }}, 1800);
                }}
              </script>
            </body>
            </html>"""
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        except Exception as e:
            html = f"""<!DOCTYPE html><html><body style="font-family:sans-serif;background:#0b1220;color:#ef4444;text-align:center;padding:50px;">
            <h2>❌ Lỗi xác thực token: {str(e)}</h2>
            <button onclick="window.close()" style="padding:10px 20px;margin-top:20px;cursor:pointer;">Đóng cửa sổ</button></body></html>"""
            self.send_response(500)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))

    def handle_google_logout(self):
        """Đăng xuất tài khoản Google"""
        try:
            google_service.logout()
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e), 500)

    def handle_google_create_sheet(self):
        """Tự động tạo mới Google Sheet trên Google Drive của người dùng"""
        try:
            if not google_service.is_logged_in():
                self.send_error_json('Chưa kết nối tài khoản Google. Vui lòng bấm "Kết nối Google" trước.', 401)
                return
            
            data = self.get_post_data()
            title = data.get('title', 'Điểm danh lớp học').strip()
            res = google_service.create_google_spreadsheet(title)
            self.send_json({'success': True, 'data': res})
        except Exception as e:
            self.send_error_json(str(e), 500)

    def test_google_sheet(self):
        """Kiểm tra kết nối đến Google Sheet (hỗ trợ cả link Google Sheet trực tiếp và Apps Script Webhook)"""
        try:
            data = self.get_post_data()
            url = data.get('url', '').strip()
            class_id = data.get('class_id', '').strip()
            if not url:
                self.send_error_json('Chưa nhập URL Google Sheet', 400)
                return

            # Nếu là link Google Sheet thông thường (không phải webhook Apps Script)
            if not url.startswith('https://script.google.com/'):
                if not google_service.is_logged_in():
                    self.send_error_json('Chưa kết nối tài khoản Google. Vui lòng bấm "Kết nối Google" trên góc trên màn hình trước.', 401)
                    return
                
                sheet_id = google_service.extract_spreadsheet_id(url)
                if not sheet_id:
                    self.send_error_json('Đường link Google Sheet không hợp lệ', 400)
                    return

                # Kiểm tra trùng lặp trong database
                conn = sqlite3.connect(DB_FILE)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('SELECT class_id, class_name, google_sheet_url FROM classes WHERE class_id != ?', (class_id,))
                duplicate_class = None
                for other in cursor.fetchall():
                    other_url = other['google_sheet_url'] or ''
                    if other_url and google_service.extract_spreadsheet_id(other_url) == sheet_id:
                        duplicate_class = dict(other)
                        break

                current_class = None
                if class_id:
                    cursor.execute('SELECT class_id, class_name FROM classes WHERE class_id = ?', (class_id,))
                    c_row = cursor.fetchone()
                    if c_row:
                        current_class = dict(c_row)
                conn.close()

                token = google_service.get_valid_access_token()
                req = urllib.request.Request(
                    f'https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}?fields=properties.title',
                    headers={'Authorization': f'Bearer {token}'}
                )
                with urllib.request.urlopen(req, timeout=15) as response:
                    res_data = json.loads(response.read().decode('utf-8'))
                    title = res_data.get('properties', {}).get('title', 'Google Sheet')

                if duplicate_class:
                    self.send_json({
                        'success': False,
                        'has_conflict': True,
                        'message': f"CẢNH BÁO TRÙNG LẶP: File '{title}' hiện đang được sử dụng bởi lớp '{duplicate_class['class_name']}' ({duplicate_class['class_id']}). Mỗi lớp học bắt buộc phải có 1 file Google Sheet riêng biệt!",
                        'sheet_title': title
                    })
                    return

                if current_class:
                    compat = google_service.check_sheet_class_compatibility(url, current_class['class_id'], current_class['class_name'])
                    if not compat.get('ok'):
                        self.send_json({
                            'success': False,
                            'has_conflict': True,
                            'message': compat.get('message'),
                            'sheet_title': title
                        })
                        return

                self.send_json({
                    'success': True,
                    'message': f'Kết nối thành công tới file: "{title}"',
                    'sheet_title': title
                })
                return

            # Nếu là URL Webhook Apps Script
            req = urllib.request.Request(
                url,
                data=json.dumps({'action': 'test'}).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                body = response.read().decode('utf-8')
                try:
                    res_json = json.loads(body)
                except:
                    res_json = {'status': 'success', 'message': body}
                self.send_json({'success': True, 'data': res_json, 'message': 'Kết nối Apps Script thành công!'})
        except urllib.error.HTTPError as http_err:
            if http_err.code == 404:
                self.send_error_json('Không tìm thấy file Google Sheet. Hãy kiểm tra lại đường link.', 404)
            elif http_err.code == 403:
                self.send_error_json('Không có quyền truy cập file Google Sheet này với tài khoản Google đang đăng nhập.', 403)
            else:
                self.send_error_json(f'Lỗi HTTP {http_err.code}: {http_err.reason}', 500)
        except Exception as e:
            self.send_error_json(f'Không thể kết nối đến Google Sheet: {str(e)}', 500)

    def _extract_session_students_payload(self, cursor, session_id, class_students):
        """Trích xuất dữ liệu điểm danh của một buổi học theo danh sách sinh viên lớp, sắp xếp chuẩn Việt Nam"""
        class_students = sort_vietnamese_students(class_students)

        cursor.execute('SELECT * FROM checkins WHERE session_id = ?', (session_id,))
        checkins = [dict(r) for r in cursor.fetchall()]

        cursor.execute('SELECT * FROM absences WHERE session_id = ?', (session_id,))
        absences = {r['student_id']: r['reason'] for r in cursor.fetchall()}

        check_map = {}
        for c in checkins:
            sid = c['student_id']
            if sid not in check_map:
                check_map[sid] = {'in': '', 'out': '', 'bonus_points': 0, 'bonus_reason': ''}
            if c['check_type'] == 'in':
                check_map[sid]['in'] = c['check_time']
                check_map[sid]['bonus_points'] = c.get('bonus_points') or 0
                check_map[sid]['bonus_reason'] = c.get('bonus_reason') or ''
            elif c['check_type'] == 'out':
                check_map[sid]['out'] = c['check_time']

        payload = []
        for idx, s in enumerate(class_students):
            sid = s['student_id']
            chk = check_map.get(sid, {})
            has_in = bool(chk.get('in'))
            abs_reason = absences.get(sid, '')

            if has_in:
                status = 'Có mặt'
            elif abs_reason:
                status = 'Vắng có phép'
            else:
                status = 'Vắng'

            full_name = s.get('full_name') or f"{s.get('last_name', '')} {s.get('first_name', '')}".strip()

            payload.append({
                'stt': idx + 1,
                'student_id': sid,
                'last_name': s.get('last_name', ''),
                'first_name': s.get('first_name', ''),
                'full_name': full_name,
                'class_id': s.get('class_id', ''),
                'class_name': s.get('class_name', ''),
                'role': 'Giảng viên' if s.get('is_lecturer') else 'Sinh viên',
                'check_in': chk.get('in', ''),
                'check_out': chk.get('out', ''),
                'bonus_points': chk.get('bonus_points', 0),
                'bonus_reason': chk.get('bonus_reason', ''),
                'absence_reason': abs_reason,
                'status': status
            })
        return payload

    def sync_session_google_sheet(self, session_id):
        """Đồng bộ kết quả điểm danh của buổi học lên Google Sheet tương ứng"""
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT s.*, c.class_name, c.is_conference, c.google_sheet_url
                FROM sessions s
                JOIN classes c ON s.class_id = c.class_id
                WHERE s.session_id = ?
            ''', (session_id,))
            session = cursor.fetchone()

            if not session:
                conn.close()
                self.send_error_json('Không tìm thấy buổi học', 404)
                return

            google_sheet_url = (session['google_sheet_url'] or '').strip()
            if not google_sheet_url:
                conn.close()
                self.send_error_json('Lớp học này chưa khai báo URL Google Sheet.', 400)
                return

            class_id = session['class_id']
            cursor.execute('''
                SELECT s.*, c.class_name, c.credit_class_id
                FROM students s
                LEFT JOIN classes c ON s.class_id = c.class_id
                WHERE s.class_id = ?
            ''', (class_id,))
            students = sort_vietnamese_students([dict(r) for r in cursor.fetchall()])

            # 1. Kiểm tra xem link này có đang bị trùng với lớp khác trong database không
            target_sheet_id = google_service.extract_spreadsheet_id(google_sheet_url)
            cursor.execute('SELECT class_id, class_name, google_sheet_url FROM classes WHERE class_id != ?', (class_id,))
            for other in cursor.fetchall():
                other_url = other['google_sheet_url'] or ''
                if other_url and google_service.extract_spreadsheet_id(other_url) == target_sheet_id:
                    conn.close()
                    self.send_error_json(
                        f"XUNG ĐỘT LINK GOOGLE SHEET: Link này đang bị trùng với lớp '{other['class_name']}' ({other['class_id']}). "
                        f"Mỗi lớp học bắt buộc phải có 1 file Google Sheet riêng biệt để tránh ghi đè làm mất dữ liệu. "
                        f"Vui lòng vào 'Quản lý lớp học' bấm 'Tạo Sheet' mới cho lớp này!",
                        400
                    )
                    return

            # 2. Kiểm tra nội dung trên Google Sheet trước khi đổ dữ liệu
            if not google_sheet_url.startswith('https://script.google.com/'):
                if not google_service.is_logged_in():
                    conn.close()
                    self.send_error_json('Chưa kết nối tài khoản Google. Vui lòng bấm "Kết nối Google" trên thanh công cụ.', 401)
                    return
                compat = google_service.check_sheet_class_compatibility(google_sheet_url, class_id, session['class_name'])
                if not compat.get('ok'):
                    conn.close()
                    self.send_error_json(compat.get('message', 'File Google Sheet này thuộc về lớp khác.'), 409)
                    return

            students_payload = self._extract_session_students_payload(cursor, session_id, students)
            conn.close()

            # 1. Nếu là link Google Sheet trực tiếp (dùng OAuth API v4 từ key.json)
            if not google_sheet_url.startswith('https://script.google.com/'):
                res = google_service.sync_session_to_google_sheet(
                    google_sheet_url,
                    dict(session),
                    students_payload
                )
                self.send_json(res)
                return

            # 2. Nếu là URL Webhook Google Apps Script
            payload = {
                'action': 'sync_session',
                'class_id': class_id,
                'class_name': session['class_name'],
                'is_conference': bool(session['is_conference']),
                'session_id': session_id,
                'session_number': session['session_number'],
                'session_date': session['session_date'],
                'start_period': session['start_period'],
                'end_period': session['end_period'],
                'synced_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
                'students': students_payload
            }

            req = urllib.request.Request(
                google_sheet_url,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )

            with urllib.request.urlopen(req, timeout=25) as response:
                body = response.read().decode('utf-8')
                try:
                    res_json = json.loads(body)
                except:
                    res_json = {'status': 'success', 'raw': body}

                self.send_json({
                    'success': True,
                    'message': res_json.get('message', f"Đã đồng bộ {len(students_payload)} sinh viên lên Google Sheet!"),
                    'spreadsheet_url': res_json.get('spreadsheet_url') or (google_sheet_url if 'spreadsheets/d/' in google_sheet_url else None),
                    'count': len(students_payload)
                })

        except urllib.error.HTTPError as http_err:
            self.send_error_json(f"Lỗi HTTP từ Google Sheet: {http_err.code} - {http_err.reason}", 502)
        except urllib.error.URLError as url_err:
            self.send_error_json(f"Không thể kết nối đến URL Google Sheet: {url_err.reason}", 502)
        except Exception as e:
            self.send_error_json(f"Lỗi khi đồng bộ Google Sheet: {str(e)}", 500)

    def sync_class_google_sheet(self, class_id):
        """
        Kiểm tra và đồng bộ tất cả các buổi học của lớp lên Google Sheet.
        Tự động kiểm tra buổi nào chưa có tab thì tạo mới và đồng bộ,
        buổi nào đã có thì cập nhật dữ liệu điểm danh mới nhất.
        """
        try:
            class_id = unquote(class_id)
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM classes WHERE class_id = ?', (class_id,))
            cls = cursor.fetchone()
            if not cls:
                conn.close()
                self.send_error_json('Không tìm thấy lớp học', 404)
                return

            google_sheet_url = (cls['google_sheet_url'] or '').strip()
            if not google_sheet_url:
                conn.close()
                self.send_error_json('Lớp học này chưa có link Google Sheet. Vui lòng dán link hoặc bấm Tự tạo Sheet.', 400)
                return

            cursor.execute('''
                SELECT s.*,
                       (SELECT COUNT(*) FROM checkins c WHERE c.session_id = s.session_id AND c.check_type = 'in') as checkin_count
                FROM sessions s
                WHERE s.class_id = ?
                ORDER BY s.session_number ASC
            ''', (class_id,))
            sessions = [dict(r) for r in cursor.fetchall()]
            if not sessions:
                conn.close()
                self.send_error_json('Không tìm thấy buổi học nào trong lớp này', 404)
                return

            cursor.execute('''
                SELECT s.*, c.class_name, c.credit_class_id
                FROM students s
                LEFT JOIN classes c ON s.class_id = c.class_id
                WHERE s.class_id = ?
            ''', (class_id,))
            students = sort_vietnamese_students([dict(r) for r in cursor.fetchall()])

            # 1. Kiểm tra xem link này có đang bị trùng với lớp khác trong database không
            target_sheet_id = google_service.extract_spreadsheet_id(google_sheet_url)
            cursor.execute('SELECT class_id, class_name, google_sheet_url FROM classes WHERE class_id != ?', (class_id,))
            for other in cursor.fetchall():
                other_url = other['google_sheet_url'] or ''
                if other_url and google_service.extract_spreadsheet_id(other_url) == target_sheet_id:
                    conn.close()
                    self.send_error_json(
                        f"XUNG ĐỘT LINK GOOGLE SHEET: Link này đang bị trùng với lớp '{other['class_name']}' ({other['class_id']}). "
                        f"Mỗi lớp học bắt buộc phải có 1 file Google Sheet riêng biệt để tránh ghi đè làm mất dữ liệu. "
                        f"Vui lòng vào 'Quản lý lớp học' bấm 'Tạo Sheet' mới cho lớp này!",
                        400
                    )
                    return

            # 2. Kiểm tra nội dung trên Google Sheet trước khi đổ dữ liệu
            if not google_sheet_url.startswith('https://script.google.com/'):
                if not google_service.is_logged_in():
                    conn.close()
                    self.send_error_json('Chưa kết nối tài khoản Google. Vui lòng bấm "Kết nối Google" trước.', 401)
                    return
                compat = google_service.check_sheet_class_compatibility(google_sheet_url, class_id, cls['class_name'])
                if not compat.get('ok'):
                    conn.close()
                    self.send_error_json(compat.get('message', 'File Google Sheet này thuộc về lớp khác.'), 409)
                    return

                sheet_tabs_info = google_service.get_spreadsheet_tabs(google_sheet_url)
                existing_tabs = sheet_tabs_info.get('tabs', {})

                missing_sessions = []
                existing_sessions = []
                sessions_payload_list = []

                for s in sessions:
                    s_num = s['session_number']
                    tab_name = f"Buổi {s_num}"
                    if tab_name in existing_tabs:
                        existing_sessions.append(s_num)
                    else:
                        missing_sessions.append(s_num)

                    s_info = dict(s)
                    s_info['class_name'] = cls['class_name']
                    s_info['is_conference'] = cls['is_conference']
                    st_payload = self._extract_session_students_payload(cursor, s['session_id'], students)
                    sessions_payload_list.append({
                        'session_info': s_info,
                        'students_data': st_payload
                    })

                conn.close()

                res = google_service.sync_multiple_sessions_to_google_sheet(
                    google_sheet_url,
                    sessions_payload_list
                )

                new_count = len(missing_sessions)
                exist_count = len(existing_sessions)
                total_count = len(sessions)

                if new_count > 0 and exist_count > 0:
                    summary_msg = f"Đã kiểm tra Google Sheet: Phát hiện {total_count} buổi học ({new_count} buổi chưa có đã được tạo mới: Buổi {', '.join(map(str, missing_sessions))}; {exist_count} buổi đã có được cập nhật). Cả {total_count} buổi đã đồng bộ thành công!"
                elif new_count > 0:
                    summary_msg = f"Đã tạo mới và đồng bộ thành công {new_count} buổi học lên Google Sheet (Buổi {', '.join(map(str, missing_sessions))})!"
                else:
                    summary_msg = f"Tất cả {total_count} buổi học đã có trên Google Sheet và vừa được cập nhật dữ liệu điểm danh mới nhất!"

                self.send_json({
                    'success': True,
                    'message': summary_msg,
                    'total_sessions': total_count,
                    'synced_count': total_count,
                    'missing_sessions_created': missing_sessions,
                    'existing_sessions_updated': existing_sessions,
                    'spreadsheet_url': res.get('spreadsheet_url') or google_sheet_url
                })
                return

            # 2. Trường hợp URL Webhook Apps Script
            all_sessions_payload = []
            for s in sessions:
                st_payload = self._extract_session_students_payload(cursor, s['session_id'], students)
                all_sessions_payload.append({
                    'session_id': s['session_id'],
                    'session_number': s['session_number'],
                    'session_date': s['session_date'],
                    'start_period': s['start_period'],
                    'end_period': s['end_period'],
                    'students': st_payload
                })
            conn.close()

            payload = {
                'action': 'sync_all_sessions',
                'class_id': class_id,
                'class_name': cls['class_name'],
                'is_conference': bool(cls['is_conference']),
                'synced_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
                'sessions': all_sessions_payload
            }

            req = urllib.request.Request(
                google_sheet_url,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read().decode('utf-8')
                try:
                    res_json = json.loads(body)
                except:
                    res_json = {'status': 'success', 'raw': body}

                self.send_json({
                    'success': True,
                    'message': res_json.get('message', f"Đã đồng bộ toàn bộ {len(sessions)} buổi lên Google Sheet!"),
                    'spreadsheet_url': google_sheet_url,
                    'total_sessions': len(sessions)
                })

        except urllib.error.HTTPError as http_err:
            self.send_error_json(f"Lỗi HTTP từ Google Sheet: {http_err.code} - {http_err.reason}", 502)
        except urllib.error.URLError as url_err:
            self.send_error_json(f"Không thể kết nối đến URL Google Sheet: {url_err.reason}", 502)
        except Exception as e:
            self.send_error_json(f"Lỗi khi đồng bộ Google Sheet: {str(e)}", 500)

    def get_class_google_sheet_status(self, class_id):
        """Kiểm tra trạng thái các buổi học của lớp trên Google Sheet (đã có hay chưa có)"""
        try:
            class_id = unquote(class_id)
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('SELECT class_id, class_name, is_conference, google_sheet_url FROM classes WHERE class_id = ?', (class_id,))
            cls = cursor.fetchone()
            if not cls:
                conn.close()
                self.send_error_json('Không tìm thấy lớp học', 404)
                return

            google_sheet_url = (cls['google_sheet_url'] or '').strip()
            cursor.execute('''
                SELECT s.*,
                       (SELECT COUNT(*) FROM checkins c WHERE c.session_id = s.session_id AND c.check_type = 'in') as checkin_count,
                       (SELECT COUNT(*) FROM students st WHERE st.class_id = s.class_id) as total_students
                FROM sessions s
                WHERE s.class_id = ?
                ORDER BY s.session_number ASC
            ''', (class_id,))
            sessions = [dict(r) for r in cursor.fetchall()]
            conn.close()

            if not google_sheet_url:
                self.send_json({
                    'has_sheet': False,
                    'total_sessions': len(sessions),
                    'sessions': sessions,
                    'message': 'Lớp học chưa liên kết Google Sheet'
                })
                return

            is_direct = not google_sheet_url.startswith('https://script.google.com/')
            logged_in = google_service.is_logged_in()
            tabs = {}
            sheet_title = ''

            if is_direct and logged_in:
                try:
                    sheet_info = google_service.get_spreadsheet_tabs(google_sheet_url)
                    tabs = sheet_info.get('tabs', {})
                    sheet_title = sheet_info.get('title', '')
                except Exception as e:
                    tabs = {}

            on_sheet_sessions = []
            missing_sessions = []

            for s in sessions:
                tab_name = f"Buổi {s['session_number']}"
                is_on = tab_name in tabs if tabs else False
                s['is_on_sheet'] = is_on
                if is_on:
                    on_sheet_sessions.append(s['session_number'])
                else:
                    missing_sessions.append(s['session_number'])

            # Kiểm tra xem link này có đang bị trùng lặp với lớp khác không
            duplicate_class = None
            target_sheet_id = google_service.extract_spreadsheet_id(google_sheet_url)
            if target_sheet_id:
                conn_chk = sqlite3.connect(DB_FILE)
                conn_chk.row_factory = sqlite3.Row
                cur_chk = conn_chk.cursor()
                cur_chk.execute('SELECT class_id, class_name, google_sheet_url FROM classes WHERE class_id != ?', (class_id,))
                for other in cur_chk.fetchall():
                    other_url = other['google_sheet_url'] or ''
                    if other_url and google_service.extract_spreadsheet_id(other_url) == target_sheet_id:
                        duplicate_class = dict(other)
                        break
                conn_chk.close()

            # Kiểm tra nội dung tính tương thích với tên lớp
            compat = None
            if is_direct and logged_in:
                compat = google_service.check_sheet_class_compatibility(google_sheet_url, class_id, cls['class_name'])

            has_conflict = bool(duplicate_class or (compat and not compat.get('ok')))
            conflict_message = ""
            if duplicate_class:
                conflict_message = f"CẢNH BÁO TRÙNG LẶP: Link Google Sheet này đang bị dùng chung với lớp '{duplicate_class['class_name']}' ({duplicate_class['class_id']}). Mỗi lớp học bắt buộc phải có 1 file Sheet riêng biệt!"
            elif compat and not compat.get('ok'):
                conflict_message = compat.get('message')

            self.send_json({
                'has_sheet': True,
                'is_direct': is_direct,
                'google_logged_in': logged_in,
                'sheet_title': sheet_title,
                'spreadsheet_url': google_sheet_url,
                'has_conflict': has_conflict,
                'conflict_message': conflict_message,
                'total_sessions': len(sessions),
                'on_sheet_count': len(on_sheet_sessions),
                'on_sheet_sessions': on_sheet_sessions,
                'missing_count': len(missing_sessions),
                'missing_sessions': missing_sessions,
                'sessions': sessions
            })
        except Exception as e:
            self.send_error_json(str(e), 500)

    # ===== Students API =====
    
    def get_students(self, class_id):
        """Lấy danh sách sinh viên của lớp, sắp xếp chuẩn Việt Nam: Tên -> Họ -> Lớp -> MSSV"""
        if not class_id:
            self.send_json([])
            return
        
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT s.*, c.class_name, c.credit_class_id
            FROM students s
            LEFT JOIN classes c ON s.class_id = c.class_id
            WHERE s.class_id = ?
        ''', (class_id,))
        rows = cursor.fetchall()
        conn.close()
        
        students = [dict(row) for row in rows]
        students = sort_vietnamese_students(students)
        self.send_json(students)
    
    def create_student(self):
        """Thêm sinh viên"""
        try:
            data = self.get_post_data()
            
            student_id = data.get('student_id', '').strip()
            class_id = data.get('class_id', '').strip()
            last_name = data.get('last_name', '').strip()
            first_name = data.get('first_name', '').strip()
            full_name = f"{last_name} {first_name}".strip() or data.get('full_name', '').strip()
            email = data.get('email', '').strip()
            birth_date = data.get('birth_date', '')
            gender = data.get('gender', '')
            is_lecturer = int(data.get('is_lecturer', 0))
            
            if not student_id or not class_id:
                self.send_error_json('Thiếu MSSV hoặc mã lớp')
                return
            
            now = datetime.now().isoformat()
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO students 
                (student_id, class_id, last_name, first_name, full_name, email, birth_date, gender, is_lecturer, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (student_id, class_id, last_name, first_name, full_name, email, birth_date, gender, is_lecturer, now))
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    def import_students(self):
        """Import sinh viên từ danh sách"""
        conn = None
        try:
            data = self.get_post_data()
            class_id = data.get('class_id', '')
            students = data.get('students', [])
            
            if not class_id or not students:
                self.send_error_json('Thieu du lieu')
                return
            
            now = datetime.now().isoformat()
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            
            count = 0
            for s in students:
                student_id = str(s.get('id', s.get('student_id', ''))).strip()
                if not student_id:
                    continue
                
                last_name = s.get('last_name', '').strip()
                first_name = s.get('first_name', '').strip()
                full_name = s.get('name', s.get('full_name', '')).strip()
                if not full_name and (last_name or first_name):
                    full_name = f"{last_name} {first_name}".strip()
                
                cursor.execute('''
                    INSERT OR REPLACE INTO students 
                    (student_id, class_id, last_name, first_name, full_name, email,
                     birth_date, gender, is_lecturer, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (student_id, class_id, last_name, first_name, full_name, s.get('email', '').strip(),
                      s.get('birth_date', ''), s.get('gender', ''), int(s.get('is_lecturer', 0)), now))
                count += 1
            
            conn.commit()
            
            self.send_json({'success': True, 'count': count})
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_error_json(str(e), 500)
        finally:
            if conn:
                conn.close()
    
    def update_student(self, student_id):
        """Cập nhật sinh viên"""
        try:
            data = self.get_post_data()
            class_id = data.get('class_id', '')
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            last_name = data.get('last_name', '')
            first_name = data.get('first_name', '')
            full_name = f"{last_name} {first_name}".strip() or data.get('full_name', '')
            
            cursor.execute('''
                UPDATE students 
                SET last_name = ?, first_name = ?, full_name = ?, email = ?, birth_date = ?, gender = ?, is_lecturer = ?
                WHERE student_id = ? AND class_id = ?
            ''', (last_name, first_name, full_name, data.get('email', '').strip(), data.get('birth_date', ''),
                  data.get('gender', ''), int(data.get('is_lecturer', 0)), student_id, class_id))
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    
    def delete_students_in_class(self, class_id):
        """Xóa toàn bộ sinh viên trong một lớp"""
        conn = None
        try:
            class_id = unquote(class_id)
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            
            # 1. Xóa checkins của tất cả sinh viên trong lớp này
            cursor.execute('''
                DELETE FROM checkins 
                WHERE session_id IN (SELECT session_id FROM sessions WHERE class_id = ?)
            ''', (class_id,))
            
            # 2. Xóa logs liên quan đến sinh viên trong lớp này
            # Lưu ý: logs dùng cột class_name, nên ta phải map từ class_id sang class_name trước
            # Nhưng để an toàn và đơn giản, ta chỉ xóa logs trong context của session thuộc lớp
            # Hiện tại bảng logs cấu trúc hơi lỏng lẻo, nhưng ta có thể xóa dựa vào session_id
            cursor.execute('''
                DELETE FROM logs 
                WHERE session_id IN (SELECT session_id FROM sessions WHERE class_id = ?)
            ''', (class_id,))
            
            # 3. Xóa sinh viên thuộc lớp
            cursor.execute('DELETE FROM students WHERE class_id = ?', (class_id,))
            
            rows_deleted = cursor.rowcount
            conn.commit()
            
            self.send_json({'success': True, 'count': rows_deleted})
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_error_json(str(e), 500)
        finally:
            if conn:
                conn.close()

    def delete_student(self, student_id, class_id):
        """Xóa sinh viên"""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            # Xóa checkins của sinh viên trong lớp này
            cursor.execute('''
                DELETE FROM checkins 
                WHERE student_id = ? 
                AND session_id IN (SELECT session_id FROM sessions WHERE class_id = ?)
            ''', (student_id, class_id))
            
            # Xóa sinh viên
            cursor.execute('DELETE FROM students WHERE student_id = ? AND class_id = ?', 
                          (student_id, class_id))
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    def transfer_student(self, student_id):
        """Chuyển sinh viên sang lớp khác"""
        conn = None
        try:
            data = self.get_post_data()
            from_class_id = data.get('from_class_id', '').strip()
            to_class_id = data.get('to_class_id', '').strip()
            
            if not from_class_id or not to_class_id:
                self.send_error_json('Thiếu thông tin lớp nguồn hoặc lớp đích')
                return
            
            if from_class_id == to_class_id:
                self.send_error_json('Lớp nguồn và lớp đích không được giống nhau')
                return
            
            conn = sqlite3.connect(DB_FILE, timeout=30)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Check if student exists in source class
            cursor.execute('SELECT * FROM students WHERE student_id = ? AND class_id = ?', 
                          (student_id, from_class_id))
            student = cursor.fetchone()
            
            if not student:
                self.send_error_json(f'Không tìm thấy sinh viên {student_id} trong lớp {from_class_id}')
                return
            
            # Check if target class exists
            cursor.execute('SELECT class_id FROM classes WHERE class_id = ?', (to_class_id,))
            if not cursor.fetchone():
                self.send_error_json(f'Lớp đích {to_class_id} không tồn tại')
                return
            
            # Check if student already exists in target class
            cursor.execute('SELECT student_id FROM students WHERE student_id = ? AND class_id = ?',
                          (student_id, to_class_id))
            if cursor.fetchone():
                self.send_error_json(f'Sinh viên {student_id} đã tồn tại trong lớp {to_class_id}')
                return
            
            # Insert student into target class with same info
            now = datetime.now().isoformat()
            cursor.execute('''
                INSERT INTO students 
                (student_id, class_id, last_name, first_name, full_name, birth_date, gender, photo_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (student_id, to_class_id, student['last_name'], student['first_name'],
                  student['full_name'], student['birth_date'], student['gender'],
                  student['photo_path'], now))
            
            # Delete student from source class
            cursor.execute('DELETE FROM students WHERE student_id = ? AND class_id = ?',
                          (student_id, from_class_id))
            
            conn.commit()
            
            self.send_json({
                'success': True,
                'student_id': student_id,
                'from_class': from_class_id,
                'to_class': to_class_id
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_error_json(str(e), 500)
        finally:
            if conn:
                conn.close()
    
    def upload_photo(self, student_id):
        """Upload ảnh sinh viên"""
        try:
            data = self.get_post_data()
            class_id = data.get('class_id', '')
            photo_data = data.get('photo', '')  # Base64 encoded
            
            if not photo_data:
                self.send_error_json('Thiếu dữ liệu ảnh')
                return
            
            # Tạo tên file
            filename = f"{class_id}_{student_id}_{uuid.uuid4().hex[:8]}.jpg"
            filepath = os.path.join(PHOTOS_DIR, filename)
            
            # Decode và lưu ảnh
            if ',' in photo_data:
                photo_data = photo_data.split(',')[1]
            
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(photo_data))
            
            # Cập nhật database
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE students SET photo_path = ? WHERE student_id = ? AND class_id = ?
            ''', (filename, student_id, class_id))
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True, 'photo_path': filename})
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    def get_student_photo(self, student_id, class_id):
        """Lấy ảnh sinh viên - hỗ trợ tự động tìm file mssv.jpg"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT photo_path FROM students WHERE student_id = ? AND class_id = ?',
                      (student_id, class_id))
        row = cursor.fetchone()
        conn.close()
        
        # Check photo_path from database first
        if row and row[0]:
            filepath = os.path.join(PHOTOS_DIR, row[0])
            if os.path.exists(filepath):
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.end_headers()
                with open(filepath, 'rb') as f:
                    self.wfile.write(f.read())
                return
        
        # Fallback: try to find file by student_id.jpg naming convention
        for ext in ['.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG']:
            auto_path = os.path.join(PHOTOS_DIR, f"{student_id}{ext}")
            if os.path.exists(auto_path):
                content_type = 'image/png' if ext.lower() == '.png' else 'image/jpeg'
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.end_headers()
                with open(auto_path, 'rb') as f:
                    self.wfile.write(f.read())
                return
        
        self.send_error_json('Photo not found', 404)
    
    # ===== Card UID API =====
    
    def update_card_uid(self, student_id):
        """Cập nhật card_uid cho sinh viên"""
        conn = None
        try:
            data = self.get_post_data()
            class_id = data.get('class_id', '').strip()
            card_uid = data.get('card_uid', '').strip()
            session_id = data.get('session_id')
            registered_at = data.get('card_registered_at') # Optional: preserve timestamp on transfer
            
            if not class_id:
                self.send_error_json('Thiếu class_id')
                return
            
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            
            # Kiểm tra xem UID đã được đăng ký cho sinh viên khác chưa
            if card_uid:
                cursor.execute('''
                    SELECT student_id, class_id, full_name, card_registered_at FROM students 
                    WHERE card_uid = ? AND NOT (student_id = ? AND class_id = ?)
                ''', (card_uid, student_id, class_id))
                existing = cursor.fetchone()
                
                if existing:
                    self.send_json({
                        'success': False,
                        'error': 'uid_exists',
                        'existing_student_id': existing[0],
                        'existing_class_id': existing[1],
                        'existing_name': existing[2],
                        'existing_registered_at': existing[3]
                    })
                    return
            
            # Use provided timestamp or current time
            if not registered_at:
                registered_at = datetime.now().isoformat()

            # Cập nhật card_uid
            cursor.execute('''
                UPDATE students 
                SET card_uid = ?, card_registered_at = ?
                WHERE student_id = ? AND class_id = ?
            ''', (card_uid, registered_at, student_id, class_id))
            
            # Nếu có session_id, thực hiện điểm danh
            if session_id:
                 cursor.execute('''
                    INSERT OR REPLACE INTO checkins (session_id, student_id, class_id, check_type, check_time)
                    VALUES (?, ?, ?, ?, ?)
                ''', (session_id, student_id, class_id, 'in', datetime.now().strftime('%H:%M:%S %d/%m/%Y')))
            
            conn.commit()
            self.send_json({
                'success': True, 
                'card_uid': card_uid,
                'card_registered_at': registered_at
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_error_json(str(e), 500)
        finally:
            if conn:
                conn.close()
    
    def delete_card_uid(self, student_id, class_id):
        """Xóa card_uid của sinh viên"""
        conn = None
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE students SET card_uid = NULL WHERE student_id = ? AND class_id = ?
            ''', (student_id, class_id))
            
            conn.commit()
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e), 500)
        finally:
            if conn:
                conn.close()
    
    def sync_card_uid(self, student_id):
        """Đồng bộ card_uid cho cùng MSSV ở tất cả các lớp"""
        conn = None
        try:
            data = self.get_post_data()
            class_id = data.get('class_id', '').strip()
            
            if not class_id:
                self.send_error_json('Thiếu class_id')
                return
            
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            
            # Lấy card_uid hiện tại của sinh viên trong lớp này
            cursor.execute('''
                SELECT card_uid FROM students WHERE student_id = ? AND class_id = ?
            ''', (student_id, class_id))
            row = cursor.fetchone()
            
            if not row or not row[0]:
                self.send_error_json('Sinh viên chưa có card_uid để đồng bộ')
                return
            
            card_uid = row[0]
            
            # Cập nhật card_uid cho tất cả các lớp khác có cùng MSSV
            cursor.execute('''
                UPDATE students SET card_uid = ? WHERE student_id = ? AND class_id != ?
            ''', (card_uid, student_id, class_id))
            
            updated_count = cursor.rowcount
            conn.commit()
            
            self.send_json({
                'success': True,
                'card_uid': card_uid,
                'synced_count': updated_count
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_error_json(str(e), 500)
        finally:
            if conn:
                conn.close()
    
    def sync_all_cards(self):
        """Đồng bộ toàn bộ card_uid cho tất cả sinh viên"""
        conn = None
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 1. Lấy danh sách uid mới nhất cho từng mssv
            # Sắp xếp theo register time giảm dần để lấy cái mới nhất
            cursor.execute('''
                SELECT student_id, card_uid, card_registered_at 
                FROM students 
                WHERE card_uid IS NOT NULL AND card_uid != ''
                ORDER BY card_registered_at DESC
            ''')
            rows = cursor.fetchall()
            
            # Map student_id -> latest_card_uid
            latest_map = {}
            for row in rows:
                sid = row['student_id']
                if sid not in latest_map:
                    latest_map[sid] = row['card_uid']
            
            # 2. Cập nhật vào database
            count = 0
            for student_id, card_uid in latest_map.items():
                cursor.execute('''
                    UPDATE students 
                    SET card_uid = ? 
                    WHERE student_id = ? AND (card_uid IS NULL OR card_uid != ?)
                ''', (card_uid, student_id, card_uid))
                count += cursor.rowcount
            
            conn.commit()
            
            self.send_json({
                'success': True,
                'synced_students': len(latest_map),
                'updated_records': count
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_error_json(str(e), 500)
        finally:
            if conn:
                conn.close()

    # ===== Checkins API =====
    
    def get_checkins(self, session_id):
        """Lấy điểm danh của buổi"""
        if not session_id:
            self.send_json([])
            return
        
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT c.*, s.full_name as name, s.photo_path, s.first_name, s.last_name, s.class_id, cl.class_name
            FROM checkins c
            LEFT JOIN students s ON c.student_id = s.student_id AND c.class_id = s.class_id
            LEFT JOIN classes cl ON s.class_id = cl.class_id
            WHERE c.session_id = ?
            ORDER BY c.check_time DESC
        ''', (session_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
        checkins = [dict(row) for row in rows]
        self.send_json(checkins)
    
    def save_checkin(self):
        """Lưu check-in/check-out"""
        try:
            data = self.get_post_data()
            
            session_id = data.get('session_id')
            student_id = data.get('student_id', data.get('id', '')).strip()
            class_id = data.get('class_id', '')
            check_type = data.get('check_type', data.get('type', 'in'))
            check_time = data.get('check_time', data.get('time', datetime.now().strftime('%H:%M:%S %d/%m/%Y')))
            
            # Optional bonus fields
            bonus_points = data.get('bonus_points')
            bonus_reason = data.get('bonus_reason')

            # Backward compatibility
            if not session_id and data.get('className'):
                return self.save_checkin_legacy(data)
            
            if not session_id or not student_id:
                self.send_error_json('Thiếu session_id hoặc student_id')
                return
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            # Lấy class_id từ session nếu chưa có
            if not class_id:
                cursor.execute('SELECT class_id FROM sessions WHERE session_id = ?', (session_id,))
                row = cursor.fetchone()
                if row:
                    class_id = row[0]
            
            # Kiểm tra xem đã có record chưa
            cursor.execute('''
                SELECT checkin_id FROM checkins 
                WHERE session_id = ? AND student_id = ? AND check_type = ?
            ''', (session_id, student_id, check_type))
            existing = cursor.fetchone()
            
            if existing:
                # Update existing record
                # Only update bonus if provided
                if bonus_points is not None or bonus_reason is not None:
                    cursor.execute('''
                        UPDATE checkins SET check_time = ?, class_id = ?, bonus_points = ?, bonus_reason = ?
                        WHERE checkin_id = ?
                    ''', (check_time, class_id, bonus_points or 0, bonus_reason or '', existing[0]))
                else:
                    cursor.execute('''
                        UPDATE checkins SET check_time = ?, class_id = ?
                        WHERE checkin_id = ?
                    ''', (check_time, class_id, existing[0]))
            else:
                # Insert new record
                cursor.execute('''
                    INSERT INTO checkins (session_id, student_id, class_id, check_type, check_time, bonus_points, bonus_reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (session_id, student_id, class_id, check_type, check_time, bonus_points or 0, bonus_reason or ''))
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e), 500)

    def update_checkin_bonus(self):
        """Cập nhật điểm cộng và lý do"""
        try:
            data = self.get_post_data()
            session_id = data.get('session_id')
            student_id = data.get('student_id')
            check_type = data.get('check_type', 'in')
            bonus_points = data.get('bonus_points', 0)
            bonus_reason = data.get('bonus_reason', '')
            
            if not session_id or not student_id:
                self.send_error_json('Thiếu thông tin')
                return

            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE checkins 
                SET bonus_points = ?, bonus_reason = ?
                WHERE session_id = ? AND student_id = ? AND check_type = ?
            ''', (bonus_points, bonus_reason, session_id, student_id, check_type))
            
            rows = cursor.rowcount
            conn.commit()
            conn.close()
            
            if rows > 0:
                self.send_json({'success': True})
            else:
                self.send_error_json('Không tìm thấy bản ghi checkin', 404)
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    def delete_checkin(self, session_id, student_id, check_type):
        """Xóa checkin"""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM checkins 
                WHERE session_id = ? AND student_id = ? AND check_type = ?
            ''', (session_id, student_id, check_type))
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    # ===== Absences API =====
    
    def get_absences(self, session_id):
        """Lấy danh sách lý do vắng của buổi"""
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if session_id:
            cursor.execute('SELECT * FROM absences WHERE session_id = ?', (session_id,))
        else:
            cursor.execute('SELECT * FROM absences')
        
        rows = cursor.fetchall()
        conn.close()
        
        absences = [dict(row) for row in rows]
        self.send_json(absences)
    
    def save_absence(self):
        """Lưu lý do vắng"""
        try:
            data = self.get_post_data()
            
            session_id = data.get('session_id')
            student_id = data.get('student_id', '')
            class_id = data.get('class_id', '')
            reason = data.get('reason', '').strip()
            
            if not session_id or not student_id or not reason:
                self.send_error_json('Thiếu dữ liệu')
                return
            
            now = datetime.now().isoformat()
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO absences 
                (session_id, student_id, class_id, reason, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (session_id, student_id, class_id, reason, now))
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    def delete_absence(self, session_id, student_id):
        """Xóa lý do vắng"""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM absences 
                WHERE session_id = ? AND student_id = ?
            ''', (session_id, student_id))
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    # ===== Logs API =====
    
    def get_logs(self, session_id):
        """Lấy logs"""
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if session_id:
            cursor.execute('SELECT * FROM logs WHERE session_id = ? ORDER BY id DESC', (session_id,))
        else:
            cursor.execute('SELECT * FROM logs ORDER BY id DESC LIMIT 1000')
        
        rows = cursor.fetchall()
        conn.close()
        
        logs = [dict(row) for row in rows]
        self.send_json(logs)
    
    def save_log(self):
        """Lưu log"""
        try:
            data = self.get_post_data()
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO logs (time, session_id, class_id, student_id, check_type, result, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                data.get('time', datetime.now().isoformat()),
                data.get('session_id'),
                data.get('class_id', data.get('className', '')),
                data.get('student_id', data.get('id', '')),
                data.get('check_type', data.get('type', '')),
                data.get('result', ''),
                data.get('note', '')
            ))
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    # ===== Legacy API (Backward Compatibility) =====
    
    def get_roster_legacy(self, class_name):
        """Lấy roster theo tên lớp (backward compatibility)"""
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Tìm class_id từ class_name
        cursor.execute('SELECT class_id FROM classes WHERE class_name = ? OR class_id = ?', 
                      (class_name, class_name))
        row = cursor.fetchone()
        
        if row:
            class_id = row[0]
            cursor.execute('''
                SELECT s.student_id as id, s.full_name as name, s.class_id as className,
                       s.first_name, s.last_name, c.class_name
                FROM students s
                LEFT JOIN classes c ON s.class_id = c.class_id
                WHERE s.class_id = ?
            ''', (class_id,))
            rows = cursor.fetchall()
            roster = sort_vietnamese_students([dict(row) for row in rows])
        else:
            roster = []
        
        conn.close()
        self.send_json(roster)
    
    def save_class_legacy(self, data):
        """Lưu lớp theo format cũ"""
        try:
            class_name = data.get('className', '')
            students = data.get('students', [])
            
            now = datetime.now().isoformat()
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            # Tạo hoặc cập nhật class
            cursor.execute('''
                INSERT OR REPLACE INTO classes (class_id, class_name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
            ''', (class_name, class_name, now, now))
            
            # Xóa students cũ
            cursor.execute('DELETE FROM students WHERE class_id = ?', (class_name,))
            
            # Thêm students mới
            for s in students:
                cursor.execute('''
                    INSERT INTO students (student_id, class_id, full_name, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (s.get('id', ''), class_name, s.get('name', ''), now))
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True, 'count': len(students)})
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    def save_checkin_legacy(self, data):
        """Lưu checkin theo format cũ"""
        try:
            class_name = data.get('className', '')
            session_date = data.get('sessionDate', '')
            session_period = data.get('sessionPeriod', '')
            student_id = data.get('id', '')
            check_type = data.get('type', 'in')
            check_time = data.get('time', '')
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            # Tìm hoặc tạo session
            cursor.execute('''
                SELECT session_id FROM sessions 
                WHERE class_id = ? AND session_date = ?
            ''', (class_name, session_date))
            row = cursor.fetchone()
            
            if row:
                session_id = row[0]
            else:
                # Tạo session mới
                start_p, end_p = session_period.split('-') if '-' in session_period else (1, 3)
                cursor.execute('''
                    INSERT INTO sessions (class_id, session_number, session_date, start_period, end_period, is_open)
                    VALUES (?, 1, ?, ?, ?, 1)
                ''', (class_name, session_date, int(start_p), int(end_p)))
                session_id = cursor.lastrowid
            
            # Lưu checkin
            cursor.execute('''
                INSERT OR REPLACE INTO checkins (session_id, student_id, class_id, check_type, check_time)
                VALUES (?, ?, ?, ?, ?)
            ''', (session_id, student_id, class_name, check_type, check_time))
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    def delete_all_data(self):
        """Xóa toàn bộ dữ liệu"""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM checkins')
            cursor.execute('DELETE FROM logs')
            cursor.execute('DELETE FROM sessions')
            cursor.execute('DELETE FROM students')
            cursor.execute('DELETE FROM classes')
            
            conn.commit()
            conn.close()
            
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e), 500)
    
    def get_email_template(self):
        """Lấy mẫu nội dung email"""
        try:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'email_template.json')
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.send_json(data)
            else:
                self.send_json({"subject": "", "body": ""})
        except Exception as e:
            self.send_error_json(str(e))

    def save_email_template(self):
        """Lưu mẫu nội dung email"""
        try:
            data = self.get_post_data()
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'email_template.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.send_json({'success': True})
        except Exception as e:
            self.send_error_json(str(e))

    def send_email_report(self):
        """Gửi email báo cáo điểm danh"""
        try:
            data = self.get_post_data()
            session_id = data.get('session_id')
            
            if not session_id:
                self.send_error_json('Thiếu session_id')
                return

            # Read config
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
            if not os.path.exists(config_path):
                self.send_error_json('Chưa cấu hình email (config.json)')
                return
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            smtp_server = config.get('smtp_server')
            smtp_port = config.get('smtp_port')
            sender_email = config.get('sender_email')
            sender_password = config.get('sender_password')
            
            if not all([smtp_server, smtp_port, sender_email, sender_password]):
                self.send_error_json('Cấu hình email không đầy đủ')
                return

            # Read template
            template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'email_template.json')
            if os.path.exists(template_path):
                with open(template_path, 'r', encoding='utf-8') as f:
                    template_data = json.load(f)
            else:
                # Default fallback if file missing
                template_data = {
                    "subject": "[{{class_id}}] Báo cáo điểm danh - Buổi {{session_number}}",
                    "body": "<html><body><h2>Báo cáo điểm danh</h2><p>Chào {{full_name}},</p><p>Trạng thái: {{status}}</p></body></html>"
                }

            subject_tmpl = template_data.get('subject', '')
            body_tmpl = template_data.get('body', '')

            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get session info
            cursor.execute('''
                SELECT s.*, c.class_name, c.room 
                FROM sessions s 
                JOIN classes c ON s.class_id = c.class_id 
                WHERE s.session_id = ?
            ''', (session_id,))
            session = cursor.fetchone()
            
            if not session:
                self.send_error_json('Không tìm thấy buổi học')
                conn.close()
                return

            # Get students
            cursor.execute('SELECT * FROM students WHERE class_id = ?', (session['class_id'],))
            students = cursor.fetchall()
            
            # Get checkins
            cursor.execute('SELECT * FROM checkins WHERE session_id = ?', (session_id,))
            checkins_data = cursor.fetchall()
            check_map = {}
            for c in checkins_data:
                if c['check_type'] == 'in':
                    check_map[c['student_id']] = {
                        'time': c['check_time'],
                        'bonus': c['bonus_points'] or 0,
                        'reason': c['bonus_reason'] or ''
                    }
            
            # Get absences
            cursor.execute('SELECT * FROM absences WHERE session_id = ?', (session_id,))
            absences = {a['student_id']: a['reason'] for a in cursor.fetchall()}
            
            conn.close()
            
            # Send emails
            context = ssl.create_default_context()
            sent_count = 0
            fail_count = 0
            
            try:
                server = smtplib.SMTP(smtp_server, smtp_port)
                server.starttls(context=context)
                server.login(sender_email, sender_password)
                
                for s in students:
                    email = s['email']
                    if not email:
                        continue
                        
                    student_id = s['student_id']
                    full_name = s['full_name']
                    
                    # Determine status
                    check_in = check_map.get(student_id)
                    is_present = check_in is not None
                    
                    status_str = "CÓ MẶT" if is_present else "VẮNG MẶT"
                    color = "green" if is_present else "red"
                    
                    details = ""
                    if is_present:
                        details += f"<p>Thời gian vào lớp: {check_in['time']}</p>"
                        if check_in['bonus']:
                            details += f"<p>Điểm cộng/trừ: <b>{check_in['bonus']}</b></p>"
                        if check_in['reason']:
                            details += f"<p>Ghi chú: {check_in['reason']}</p>"
                    else:
                        reason = absences.get(student_id, "Không có lý do")
                        details += f"<p>Lý do vắng: {reason}</p>"

                    # Replacements
                    replacements = {
                        '{{full_name}}': full_name,
                        '{{student_id}}': student_id,
                        '{{class_name}}': session['class_name'],
                        '{{class_id}}': session['class_id'],
                        '{{session_date}}': session['session_date'],
                        '{{session_number}}': str(session['session_number']),
                        '{{status}}': status_str,
                        '{{status_color}}': color,
                        '{{details}}': details,
                        '{{check_time}}': check_in['time'] if is_present else '',
                        '{{bonus}}': str(check_in['bonus']) if is_present and check_in['bonus'] else '',
                        '{{note}}': check_in['reason'] if is_present else (reason if not is_present else '')
                    }
                    
                    subj = subject_tmpl
                    body = body_tmpl
                    for k, v in replacements.items():
                        subj = subj.replace(k, str(v))
                        body = body.replace(k, str(v))
                    
                    msg = MIMEMultipart("alternative")
                    msg["Subject"] = subj
                    msg["From"] = sender_email
                    msg["To"] = email
                    msg.attach(MIMEText(body, "html"))
                    
                    try:
                        server.sendmail(sender_email, email, msg.as_string())
                        sent_count += 1
                        print(f"Sent email to {email}")
                    except Exception as e:
                        print(f"Failed to send to {email}: {e}")
                        fail_count += 1
                        
                server.quit()
                self.send_json({'success': True, 'sent': sent_count, 'failed': fail_count})
                
            except Exception as e:
                self.send_error_json(f"Lỗi SMTP: {str(e)}", 500)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_error_json(str(e), 500)
    
    def log_message(self, format, *args):
        """Ghi log request"""
        if args and isinstance(args[0], str) and '/api/' in args[0]:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")


def check_port_available(port):
    """Kiểm tra port có đang được sử dụng không"""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('127.0.0.1', port))
        sock.close()
        return True
    except OSError:
        sock.close()
        return False


def run_server():
    """Khởi động server"""
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    if not check_port_available(PORT):
        print(f"\n[LOI] Port {PORT} dang bi chiem boi tien trinh khac!")
        print(f"  Hay dong tien trinh do truoc hoac doi port.")
        print(f"  Kiem tra: netstat -aon | findstr :{PORT}")
        return
    
    init_database()
    auto_close_past_sessions()
    
    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
    
    server = ThreadedHTTPServer(('', PORT), AttendanceHandler)
    server.allow_reuse_address = False
    print(f"\n{'='*50}")
    print(f"  [*] Server dang chay tai: http://localhost:{PORT}")
    print(f"  [*] Database: {DB_FILE}")
    print(f"  [*] Photos: {PHOTOS_DIR}")
    print(f"  [*] Bam Ctrl+C de dung")
    print(f"{'='*50}\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n[OK] Server da dung.")
        server.shutdown()


if __name__ == '__main__':
    run_server()
