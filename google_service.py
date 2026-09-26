import os
import json
import time
import re
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

KEY_FILE = 'key.json'
TOKEN_FILE = 'google_token.json'

def get_client_config():
    """Đọc thông tin client_id, client_secret từ key.json"""
    if not os.path.exists(KEY_FILE):
        return None
    try:
        with open(KEY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        cfg = data.get('web') or data.get('installed')
        if not cfg:
            return None
        
        client_id = cfg.get('client_id')
        client_secret = cfg.get('client_secret')
        redirect_uris = cfg.get('redirect_uris', [])
        redirect_uri = redirect_uris[0] if redirect_uris else 'http://localhost:8000/api/auth/google/callback'
        
        return {
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'auth_uri': cfg.get('auth_uri', 'https://accounts.google.com/o/oauth2/auth'),
            'token_uri': cfg.get('token_uri', 'https://oauth2.googleapis.com/token')
        }
    except Exception as e:
        print("Lỗi đọc key.json:", e)
        return None

def is_key_configured():
    return os.path.exists(KEY_FILE)

def get_token_info():
    """Lấy thông tin token hiện tại và user profile"""
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return None

def is_logged_in():
    token_info = get_token_info()
    if not token_info:
        return False
    return bool(token_info.get('refresh_token') or token_info.get('access_token'))

def get_auth_url(state=''):
    """Tạo URL xác thực OAuth 2.0 của Google"""
    cfg = get_client_config()
    if not cfg:
        raise Exception("Không tìm thấy file key.json hợp lệ trong thư mục dự án")
    
    scopes = [
        'openid',
        'https://www.googleapis.com/auth/userinfo.email',
        'https://www.googleapis.com/auth/userinfo.profile',
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive.file'
    ]
    
    params = {
        'client_id': cfg['client_id'],
        'redirect_uri': cfg['redirect_uri'],
        'response_type': 'code',
        'scope': ' '.join(scopes),
        'access_type': 'offline',
        'prompt': 'consent',
        'include_granted_scopes': 'true'
    }
    if state:
        params['state'] = state
    
    return 'https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode(params)

def exchange_code_for_token(code):
    """Đổi authorization code lấy access_token & refresh_token"""
    cfg = get_client_config()
    if not cfg:
        raise Exception("Không tìm thấy cấu hình trong key.json")
    
    data = urllib.parse.urlencode({
        'code': code,
        'client_id': cfg['client_id'],
        'client_secret': cfg['client_secret'],
        'redirect_uri': cfg['redirect_uri'],
        'grant_type': 'authorization_code'
    }).encode('utf-8')
    
    req = urllib.request.Request(
        cfg['token_uri'],
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    
    with urllib.request.urlopen(req, timeout=15) as res:
        token_res = json.loads(res.read().decode('utf-8'))
    
    access_token = token_res.get('access_token')
    refresh_token = token_res.get('refresh_token')
    expires_in = token_res.get('expires_in', 3600)
    expires_at = time.time() + expires_in - 60
    
    # Lấy thông tin user profile
    user_info = {}
    try:
        user_req = urllib.request.Request(
            'https://www.googleapis.com/oauth2/v3/userinfo',
            headers={'Authorization': f'Bearer {access_token}'}
        )
        with urllib.request.urlopen(user_req, timeout=10) as ures:
            user_info = json.loads(ures.read().decode('utf-8'))
    except Exception as e:
        print("Không thể lấy userinfo:", e)
    
    # Giữ lại refresh_token cũ nếu Google không trả về refresh_token mới
    old_info = get_token_info() or {}
    if not refresh_token and old_info.get('refresh_token'):
        refresh_token = old_info['refresh_token']
    
    saved_data = {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'expires_at': expires_at,
        'email': user_info.get('email', ''),
        'name': user_info.get('name', ''),
        'picture': user_info.get('picture', ''),
        'updated_at': datetime.now().isoformat()
    }
    
    with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
        json.dump(saved_data, f, ensure_ascii=False, indent=2)
    
    return saved_data

def get_valid_access_token():
    """Lấy access_token còn hiệu lực, tự động làm mới bằng refresh_token nếu cần"""
    token_info = get_token_info()
    if not token_info:
        raise Exception("Chưa đăng nhập tài khoản Google. Vui lòng kết nối tài khoản Google trước.")
    
    access_token = token_info.get('access_token')
    expires_at = token_info.get('expires_at', 0)
    refresh_token = token_info.get('refresh_token')
    
    # Nếu token còn hạn ít nhất 60s
    if access_token and time.time() < expires_at:
        return access_token
    
    if not refresh_token:
        raise Exception("Phiên đăng nhập đã hết hạn. Vui lòng kết nối lại tài khoản Google.")
    
    # Làm mới token
    cfg = get_client_config()
    if not cfg:
        raise Exception("Không tìm thấy cấu hình trong key.json")
    
    data = urllib.parse.urlencode({
        'client_id': cfg['client_id'],
        'client_secret': cfg['client_secret'],
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token'
    }).encode('utf-8')
    
    req = urllib.request.Request(
        cfg['token_uri'],
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    
    with urllib.request.urlopen(req, timeout=15) as res:
        token_res = json.loads(res.read().decode('utf-8'))
    
    new_access_token = token_res.get('access_token')
    expires_in = token_res.get('expires_in', 3600)
    
    token_info['access_token'] = new_access_token
    token_info['expires_at'] = time.time() + expires_in - 60
    if 'refresh_token' in token_res:
        token_info['refresh_token'] = token_res['refresh_token']
    token_info['updated_at'] = datetime.now().isoformat()
    
    with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
        json.dump(token_info, f, ensure_ascii=False, indent=2)
    
    return new_access_token

def logout():
    """Xóa token đã lưu"""
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
    return True

def extract_spreadsheet_id(url_or_id):
    """Trích xuất ID Google Sheet từ URL hoặc ID thô"""
    if not url_or_id:
        return ''
    url_or_id = url_or_id.strip()
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url_or_id)
    if match:
        return match.group(1)
    if '/' not in url_or_id and len(url_or_id) > 15:
        return url_or_id
    return url_or_id

def create_google_spreadsheet(title):
    """Tự động tạo một file Google Sheet mới trong Google Drive của người dùng"""
    token = get_valid_access_token()
    
    payload = {
        'properties': {
            'title': title
        },
        'sheets': [
            {
                'properties': {
                    'title': 'Tổng hợp điểm danh',
                    'gridProperties': {
                        'frozenRowCount': 4
                    }
                }
            }
        ]
    }
    
    req = urllib.request.Request(
        'https://sheets.googleapis.com/v4/spreadsheets',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
    )
    
    with urllib.request.urlopen(req, timeout=20) as res:
        sheet_data = json.loads(res.read().decode('utf-8'))
    
    spreadsheet_id = sheet_data.get('spreadsheetId')
    spreadsheet_url = sheet_data.get('spreadsheetUrl') or f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
    
    return {
        'spreadsheet_id': spreadsheet_id,
        'spreadsheet_url': spreadsheet_url,
        'title': title
    }

def get_spreadsheet_tabs(spreadsheet_url_or_id):
    """
    Lấy danh sách các sheet tabs trong Spreadsheet.
    Trả về dict: { title: sheet_id } và spreadsheet_title.
    """
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_url_or_id)
    if not spreadsheet_id:
        raise Exception("URL hoặc ID Google Sheet không hợp lệ")
    
    token = get_valid_access_token()
    req = urllib.request.Request(
        f'https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}?fields=properties.title,sheets.properties(sheetId,title)',
        headers={'Authorization': f'Bearer {token}'}
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        data = json.loads(res.read().decode('utf-8'))
    
    title = data.get('properties', {}).get('title', '')
    tabs = {s['properties']['title']: s['properties']['sheetId'] for s in data.get('sheets', [])}
    return {
        'spreadsheet_id': spreadsheet_id,
        'title': title,
        'tabs': tabs
    }

def check_sheet_class_compatibility(spreadsheet_url_or_id, class_id, class_name):
    """
    Kiểm tra xem file Google Sheet này có đúng là của lớp cần đồng bộ hay không.
    Nếu phát hiện file đã chứa dữ liệu của lớp khác, chặn lại để tránh ghi đè làm mất dữ liệu.
    """
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_url_or_id)
    if not spreadsheet_id:
        return {'ok': False, 'error': 'URL hoặc ID Google Sheet không hợp lệ'}
    
    token = get_valid_access_token()
    sheet_info = get_spreadsheet_tabs(spreadsheet_id)
    existing_tabs = sheet_info.get('tabs', {})
    sheet_title = sheet_info.get('title', '')
    
    def clean(s):
        return re.sub(r'[\s\-_]+', '', str(s).lower())
    
    lower_cls_id = clean(class_id)
    lower_cls_name = clean(class_name)
    
    # Kiểm tra ô A1 của tab Buổi 1 (nếu đã có tab Buổi 1)
    if 'Buổi 1' in existing_tabs:
        try:
            req = urllib.request.Request(
                f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/Bu%E1%BB%95i%201!A1:A2",
                headers={'Authorization': f'Bearer {token}'}
            )
            with urllib.request.urlopen(req, timeout=15) as res:
                val_data = json.loads(res.read().decode('utf-8'))
                rows = val_data.get('values', [])
                if rows and len(rows) > 0 and len(rows[0]) > 0:
                    a1_text = str(rows[0][0]).strip()
                    if a1_text.startswith('DANH SÁCH ĐIỂM DANH - '):
                        sheet_class_name = a1_text.replace('DANH SÁCH ĐIỂM DANH - ', '').strip()
                        clean_sheet_class = clean(sheet_class_name)
                        if clean_sheet_class != lower_cls_name and clean_sheet_class != lower_cls_id:
                            return {
                                'ok': False,
                                'conflict': True,
                                'found_class': sheet_class_name,
                                'sheet_title': sheet_title,
                                'message': f"CẢNH BÁO AN TOÀN: File Google Sheet này ('{sheet_title}') đang chứa dữ liệu của lớp '{sheet_class_name}' (phát hiện trong tab 'Buổi 1'). Hệ thống từ chối đổ dữ liệu của lớp '{class_name}' vào đây để tránh ghi đè làm mất dữ liệu! Vui lòng tạo hoặc liên kết file Google Sheet riêng cho lớp này."
                            }
        except Exception:
            pass
            
    return {'ok': True, 'sheet_title': sheet_title}

def build_session_sheet_rows(session_info, students_data):
    """Xây dựng ma trận 2D dữ liệu ghi vào tab của một buổi học"""
    class_title = session_info.get('class_name') or session_info.get('class_id') or ''
    session_num = session_info.get('session_number', 1)
    session_date = session_info.get('session_date') or datetime.now().strftime('%d/%m/%Y')
    start_period = session_info.get('start_period', 1)
    end_period = session_info.get('end_period', 3)
    synced_at = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    
    is_conf = bool(session_info.get('is_conference'))
    id_header = "Mã GV/SV" if is_conf else "MSSV"
    
    values = [
        [f"DANH SÁCH ĐIỂM DANH - {str(class_title).upper()}"],
        [f"Buổi {session_num} | Ngày: {session_date} | Tiết: {start_period}-{end_period} | Cập nhật lúc: {synced_at}"],
        [],
        ["STT", id_header, "Họ và Tên", "Vào lớp", "Ra về", "Điểm cộng", "Ghi chú", "Lý do vắng", "Trạng thái"]
    ]
    
    for s in students_data:
        values.append([
            s.get('stt', ''),
            s.get('student_id', ''),
            s.get('full_name', ''),
            s.get('check_in', ''),
            s.get('check_out', ''),
            s.get('bonus_points', 0),
            s.get('bonus_reason', ''),
            s.get('absence_reason', ''),
            s.get('status', 'Vắng')
        ])
    return values

def build_session_format_requests(sheet_id):
    """Tạo danh sách request định dạng đẹp cho một tab buổi học"""
    return [
        # Format tiêu đề lớn hàng 1
        {
            'repeatCell': {
                'range': {
                    'sheetId': sheet_id,
                    'startRowIndex': 0,
                    'endRowIndex': 1,
                    'startColumnIndex': 0,
                    'endColumnIndex': 1
                },
                'cell': {
                    'userEnteredFormat': {
                        'textFormat': {
                            'bold': True,
                            'fontSize': 14,
                            'foregroundColor': {'red': 0.12, 'green': 0.23, 'blue': 0.54}
                        }
                    }
                },
                'fields': 'userEnteredFormat(textFormat)'
            }
        },
        # Format tiêu đề phụ hàng 2
        {
            'repeatCell': {
                'range': {
                    'sheetId': sheet_id,
                    'startRowIndex': 1,
                    'endRowIndex': 2,
                    'startColumnIndex': 0,
                    'endColumnIndex': 1
                },
                'cell': {
                    'userEnteredFormat': {
                        'textFormat': {
                            'italic': True,
                            'fontSize': 10,
                            'foregroundColor': {'red': 0.39, 'green': 0.45, 'blue': 0.55}
                        }
                    }
                },
                'fields': 'userEnteredFormat(textFormat)'
            }
        },
        # Format hàng Header bảng (hàng 4 - index 3)
        {
            'repeatCell': {
                'range': {
                    'sheetId': sheet_id,
                    'startRowIndex': 3,
                    'endRowIndex': 4,
                    'startColumnIndex': 0,
                    'endColumnIndex': 9
                },
                'cell': {
                    'userEnteredFormat': {
                        'backgroundColor': {'red': 0.12, 'green': 0.25, 'blue': 0.69},
                        'textFormat': {
                            'bold': True,
                            'fontSize': 11,
                            'foregroundColor': {'red': 1.0, 'green': 1.0, 'blue': 1.0}
                        },
                        'horizontalAlignment': 'CENTER',
                        'verticalAlignment': 'MIDDLE'
                    }
                },
                'fields': 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)'
            }
        },
        # Đặt chiều cao hàng Header
        {
            'updateDimensionProperties': {
                'range': {
                    'sheetId': sheet_id,
                    'dimension': 'ROWS',
                    'startIndex': 3,
                    'endIndex': 4
                },
                'properties': {
                    'pixelSize': 35
                },
                'fields': 'pixelSize'
            }
        },
        # Auto resize độ rộng cột A -> I
        {
            'autoResizeDimensions': {
                'dimensions': {
                    'sheetId': sheet_id,
                    'dimension': 'COLUMNS',
                    'startIndex': 0,
                    'endIndex': 9
                }
            }
        }
    ]

def sync_multiple_sessions_to_google_sheet(spreadsheet_url_or_id, sessions_payload_list):
    """
    Đồng bộ hàng loạt buổi học vào các tab riêng biệt trên Google Sheet trong 1 lần gọi batch
    sessions_payload_list: danh sách [{'session_info': {...}, 'students_data': [...]}]
    """
    if not sessions_payload_list:
        return {'success': True, 'synced_count': 0, 'message': 'Không có buổi học nào cần đồng bộ'}
        
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_url_or_id)
    if not spreadsheet_id:
        raise Exception("URL hoặc ID Google Sheet không hợp lệ")
        
    token = get_valid_access_token()
    
    # 1. Lấy danh sách các tab hiện có
    sheet_info = get_spreadsheet_tabs(spreadsheet_id)
    existing_sheets = dict(sheet_info.get('tabs', {}))
    
    # 2. Kiểm tra tab nào chưa có thì tạo thêm hàng loạt
    missing_tabs = []
    for item in sessions_payload_list:
        s_num = item['session_info'].get('session_number', 1)
        tab_name = f"Buổi {s_num}"
        if tab_name not in existing_sheets and tab_name not in missing_tabs:
            missing_tabs.append(tab_name)
            
    if missing_tabs:
        add_requests = []
        for tab_name in missing_tabs:
            add_requests.append({
                'addSheet': {
                    'properties': {
                        'title': tab_name,
                        'gridProperties': {
                            'frozenRowCount': 4
                        }
                    }
                }
            })
        add_req = urllib.request.Request(
            f'https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate',
            data=json.dumps({'requests': add_requests}).encode('utf-8'),
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
        )
        with urllib.request.urlopen(add_req, timeout=25) as add_res:
            add_res_data = json.loads(add_res.read().decode('utf-8'))
            for reply in add_res_data.get('replies', []):
                if 'addSheet' in reply:
                    p = reply['addSheet']['properties']
                    existing_sheets[p['title']] = p['sheetId']
                    
    # 3. Chuẩn bị dữ liệu ghi vào từng tab
    clear_ranges = []
    update_data = []
    format_requests = []
    synced_tabs = []
    
    for item in sessions_payload_list:
        s_info = item['session_info']
        st_data = item['students_data']
        s_num = s_info.get('session_number', 1)
        tab_name = f"Buổi {s_num}"
        synced_tabs.append(tab_name)
        
        clear_ranges.append(f"'{tab_name}'!A1:Z1000")
        rows = build_session_sheet_rows(s_info, st_data)
        update_data.append({
            'range': f"'{tab_name}'!A1",
            'values': rows
        })
        
        sheet_id = existing_sheets.get(tab_name)
        if sheet_id is not None:
            format_requests.extend(build_session_format_requests(sheet_id))
            
    # 4. Xóa dữ liệu cũ trong các tab (batchClear)
    if clear_ranges:
        clear_req = urllib.request.Request(
            f'https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchClear',
            data=json.dumps({'ranges': clear_ranges}).encode('utf-8'),
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
        )
        try:
            urllib.request.urlopen(clear_req, timeout=15)
        except Exception:
            pass
            
    # 5. Ghi dữ liệu đồng thời vào tất cả các tab (values:batchUpdate)
    if update_data:
        update_req = urllib.request.Request(
            f'https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchUpdate',
            data=json.dumps({
                'valueInputOption': 'USER_ENTERED',
                'data': update_data
            }).encode('utf-8'),
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
        )
        with urllib.request.urlopen(update_req, timeout=30) as u_res:
            u_res.read()
            
    # 6. Định dạng bảng cho tất cả các tab trong 1 batchUpdate
    if format_requests:
        fmt_req = urllib.request.Request(
            f'https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate',
            data=json.dumps({'requests': format_requests}).encode('utf-8'),
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
        )
        try:
            urllib.request.urlopen(fmt_req, timeout=20)
        except Exception as e:
            print("Lỗi định dạng giao diện Google Sheet:", e)
            
    first_gid = existing_sheets.get(synced_tabs[0]) if synced_tabs else None
    gid_hash = f"#gid={first_gid}" if first_gid is not None else ""
    spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit{gid_hash}"
    
    return {
        'success': True,
        'spreadsheet_id': spreadsheet_id,
        'spreadsheet_url': spreadsheet_url,
        'synced_count': len(sessions_payload_list),
        'synced_tabs': synced_tabs,
        'missing_tabs_created': missing_tabs,
        'message': f"Đã đồng bộ thành công {len(sessions_payload_list)} buổi ({', '.join(synced_tabs)}) lên Google Sheet!"
    }

def sync_session_to_google_sheet(spreadsheet_url_or_id, session_info, students_data):
    """
    Đồng bộ dữ liệu một buổi học trực tiếp vào Google Sheet qua Google Sheets API v4
    """
    res = sync_multiple_sessions_to_google_sheet(
        spreadsheet_url_or_id, 
        [{'session_info': session_info, 'students_data': students_data}]
    )
    s_num = session_info.get('session_number', 1)
    tab_name = f"Buổi {s_num}"
    return {
        'success': True,
        'spreadsheet_id': res.get('spreadsheet_id'),
        'spreadsheet_url': res.get('spreadsheet_url'),
        'sheet_title': tab_name,
        'count': len(students_data),
        'message': f"Đã đồng bộ {len(students_data)} sinh viên vào tab '{tab_name}' trên Google Sheet!"
    }
