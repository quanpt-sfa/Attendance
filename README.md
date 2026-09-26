# 📟 Điểm danh Offline với Zebra Scanner

Ứng dụng PWA (Progressive Web App) điểm danh hoàn toàn offline sử dụng máy quét mã vạch Zebra.

## Tính năng

✅ **Hoàn toàn offline** - Chạy không cần internet  
✅ **Import Excel** - Nạp danh sách sinh viên từ file .xlsx  
✅ **Quét mã vạch Zebra** - Hỗ trợ chế độ HID Keyboard  
✅ **Lưu trữ IndexedDB** - Dữ liệu được lưu offline trên thiết bị  
✅ **Xuất Excel** - Export điểm danh và log ra file .xlsx  
✅ **PWA** - Cài đặt như app desktop  

## Cài đặt

### 1. Tải thư viện offline

Để app chạy **hoàn toàn offline**, bạn cần tải 2 file thư viện và đặt vào thư mục `libs/`:

#### Dexie.js (IndexedDB wrapper)
- Truy cập: https://unpkg.com/dexie@latest/dist/dexie.min.js
- Lưu file vào: `C:\Projects\Attendance\libs\dexie.min.js`

#### SheetJS (xlsx library)
- Truy cập: https://cdn.sheetjs.com/xlsx-latest/package/dist/xlsx.full.min.js
- Lưu file vào: `C:\Projects\Attendance\libs\xlsx.full.min.js`

**Cách tải nhanh bằng PowerShell:**

```powershell
# Tải Dexie
Invoke-WebRequest -Uri "https://unpkg.com/dexie@latest/dist/dexie.min.js" -OutFile "C:\Projects\Attendance\libs\dexie.min.js"

# Tải SheetJS
Invoke-WebRequest -Uri "https://cdn.sheetjs.com/xlsx-latest/package/dist/xlsx.full.min.js" -OutFile "C:\Projects\Attendance\libs\xlsx.full.min.js"
```

### 2. Chạy local server

Mở PowerShell trong thư mục `C:\Projects\Attendance` và chạy:

```powershell
python -m http.server 8000
```

### 3. Mở trình duyệt

Truy cập: **http://localhost:8000**

Dùng Chrome hoặc Edge để có trải nghiệm PWA tốt nhất.

## Cách sử dụng

### Bước 1: Chuẩn bị file Excel danh sách sinh viên

Tạo file Excel (.xlsx) với các cột:
- **MSSV** hoặc **MaSV** hoặc **StudentID** - Mã số sinh viên
- **HoTen** hoặc **Họ tên** hoặc **Name** - Tên sinh viên

Ví dụ:

| MSSV | HoTen |
|------|-------|
| 21520001 | Nguyễn Văn A |
| 21520002 | Trần Thị B |
| 21520003 | Lê Văn C |

### Bước 2: Nạp danh sách

1. Click **"Nạp danh sách từ Excel"**
2. Chọn file Excel của bạn
3. Hệ thống sẽ tự động nhận diện cột MSSV và Họ tên

### Bước 3: Quét mã vạch

1. Đảm bảo **Zebra scanner** ở chế độ **USB HID Keyboard** hoặc **Bluetooth HID Keyboard**
2. Con trỏ sẽ tự động ở ô "Sẵn sàng quét"
3. Quét mã vạch MSSV
4. Hệ thống sẽ hiển thị thông báo:
   - ✅ **Xanh**: Check in thành công - "Cảm ơn bạn [Tên] đã check in"
   - ⚠️ **Vàng**: Đã check in trước đó - "Bạn [Tên] đã check in lúc [Thời gian]"
   - ❌ **Đỏ**: Không tìm thấy MSSV - "Không tìm thấy MSSV [mã]"

### Bước 4: Xuất Excel điểm danh

1. Click **"Xuất Excel điểm danh"**
2. File sẽ được tải về với 2 sheet:
   - **DiemDanh**: MSSV, Họ tên, Thời gian check in, Trạng thái
   - **Log**: Tất cả lượt quét (thành công, trùng, không tìm thấy)

### Xóa dữ liệu

Click **"Xóa dữ liệu"** để xóa toàn bộ danh sách, điểm danh và log.

## Cấu hình Zebra Scanner

### Chế độ HID Keyboard (Khuyên dùng)

Zebra scanner cần được cấu hình ở chế độ **USB HID Keyboard** hoặc **Bluetooth HID Keyboard**:

1. Quét mã cấu hình trong sách hướng dẫn Zebra
2. Chọn chế độ: **USB HID / Keyboard Emulation**
3. Cấu hình Suffix: **Enter** (để tự động submit sau khi quét)

Khi quét, scanner sẽ "gõ" MSSV + Enter vào ô input, web app sẽ tự động xử lý.

### Nếu scanner không phải HID Keyboard

Nếu scanner của bạn dùng **Web Serial** hoặc **WebUSB**, bạn cần code thêm phần tích hợp. Liên hệ để được hỗ trợ thêm.

## Cài đặt PWA

Để cài đặt app như ứng dụng desktop:

1. Click biểu tượng **⊕** trên thanh địa chỉ trình duyệt
2. Chọn **"Install"** hoặc **"Cài đặt"**
3. App sẽ mở trong cửa sổ riêng, hoạt động ngay cả khi offline

## Công nghệ sử dụng

- **HTML/CSS/JS** - Không cần backend
- **IndexedDB** - Lưu trữ offline (qua Dexie.js)
- **SheetJS** - Đọc/ghi file Excel
- **Service Worker** - Cache để chạy offline
- **PWA** - Cài đặt như app native

## Khắc phục sự cố

### Scanner quét không ra gì?

✅ Kiểm tra Zebra đang ở chế độ **HID Keyboard**  
✅ Kiểm tra con trỏ có ở ô "Sẵn sàng quét" không  
✅ Test bằng cách gõ tay MSSV + Enter để kiểm tra logic  

### Service Worker không hoạt động?

✅ Phải chạy qua **http://localhost** hoặc **https://**  
✅ Không chạy qua `file://` protocol  
✅ Dùng Chrome DevTools > Application > Service Workers để debug  

### Không đọc được Excel?

✅ Đảm bảo file là .xlsx (không phải .xls cũ)  
✅ Sheet đầu tiên phải có dữ liệu  
✅ Phải có cột MSSV và Họ tên (tên cột linh hoạt)  

## Offline Vietnamese TTS cho Random Picker

Phiên bản server Python hiện tại có thể đọc tên sinh viên bằng Piper chạy hoàn toàn local. Random Picker ưu tiên WAV đã cache; nếu Piper chưa được cài hoặc phát audio local lỗi, hệ thống tự quay về giọng `speechSynthesis` của trình duyệt.

### Cài TTS một lần

Cần Internet cho đúng bước này. Trong thư mục Attendance trên Windows chạy:

```powershell
.\Setup-TTS.bat
```

Script tạo `.venv-tts` riêng, cài `piper-tts==1.8.0`, tải voice `vi_VN-vais1000-medium`, kiểm tra SHA-256 của model và chạy một smoke test. Piper không được cài vào Python chính của Attendance.

Kiểm tra trạng thái bất kỳ lúc nào:

```powershell
.\Check-TTS.bat
```

Trạng thái sẵn sàng có dạng:

```text
Piper: READY
Voice: vi_VN-vais1000-medium
Runtime: OK
Model: OK
Cache: 42 WAV file(s)
```

### Chạy Attendance

Dùng launcher Python canonical, có thể chọn port:

```powershell
.\Start-Server.bat 8080
```

Sau khi `Setup-TTS.bat` đã hoàn tất một lần, việc tạo và phát giọng tên sinh viên không cần Internet. Khi thêm, import hoặc cập nhật sinh viên thành công, server sẽ precache tên trong background. Lúc Random Picker gọi một sinh viên từ database, server trả WAV local; cache hit không chạy Piper lần nữa.

Các dữ liệu local sau không được commit lên Git:

```text
.venv-tts/
tts/voices/
tts_cache/
```

Nếu TTS chưa sẵn sàng, Attendance vẫn khởi động và hoạt động; Random Picker dùng giọng trình duyệt làm fallback. Danh sách Excel nạp trực tiếp vào Random Picker cũng tiếp tục dùng fallback này vì không có định danh lớp/database.

## Liên hệ & Hỗ trợ

Nếu có vấn đề hoặc cần tùy chỉnh thêm, hãy mở issue hoặc liên hệ trực tiếp.

---

**Made with ❤️ for offline attendance tracking**
