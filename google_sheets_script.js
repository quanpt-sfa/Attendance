/**
 * =========================================================================
 * GOOGLE APPS SCRIPT: ĐỒNG BỘ ĐIỂM DANH TỰ ĐỘNG CHO GOOGLE SHEETS
 * =========================================================================
 * 
 * HƯỚNG DẪN THIẾT LẬP (Chỉ cần làm 1 lần cho mỗi Google Sheet của lớp):
 * 
 * BƯỚC 1: Mở Google Sheet bạn muốn lưu điểm danh cho lớp (hoặc tạo sheet mới).
 * BƯỚC 2: Trên thanh menu, chọn: Tiện ích mở rộng (Extensions) > Apps Script.
 * BƯỚC 3: Xóa toàn bộ nội dung trong trình soạn thảo, dán toàn bộ đoạn mã này vào.
 * BƯỚC 4: Nhấn nút "Triển khai" (Deploy) ở góc trên bên phải > chọn "Tùy chọn triển khai mới" (New deployment).
 * BƯỚC 5: 
 *    - Chọn loại: "Ứng dụng web" (Web app - biểu tượng bánh răng).
 *    - Mô tả: "Điểm danh tự động".
 *    - Thực thi dưới dạng (Execute as): "Tôi" (Me / email của bạn).
 *    - Ai có quyền truy cập (Who has access): CHỌN "Bất kỳ ai" (Anyone). 
 *      (Lưu ý: Bắt buộc chọn "Anyone" để phần mềm điểm danh có thể gửi dữ liệu vào).
 * BƯỚC 6: Nhấn nút "Triển khai" (Deploy) > Cấp quyền truy cập (Authorize access) nếu Google hỏi.
 * BƯỚC 7: Sao chép "URL ứng dụng web" (có đuôi /exec) và dán vào ô "Google Sheet URL" khi khai báo lớp học!
 * 
 * =========================================================================
 */

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return ContentService.createTextOutput(JSON.stringify({
        status: "error",
        message: "Không nhận được dữ liệu (Empty payload)"
      })).setMimeType(ContentService.MimeType.JSON);
    }

    var data = JSON.parse(e.postData.contents);
    var ss = SpreadsheetApp.getActiveSpreadsheet();

    // 1. Kiểm tra kết nối thử nghiệm (Test connection)
    if (data.action === "test") {
      return ContentService.createTextOutput(JSON.stringify({
        status: "success",
        message: "Kết nối Google Sheet thành công!",
        spreadsheet_name: ss.getName(),
        spreadsheet_url: ss.getUrl()
      })).setMimeType(ContentService.MimeType.JSON);
    }

    // 2. Xử lý đồng bộ buổi học
    var sessionNumber = data.session_number || 1;
    var sessionDate = data.session_date || Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "dd/MM/yyyy");
    var tabName = "Buổi " + sessionNumber;

    // Tạo hoặc ghi đè tab buổi học chi tiết
    var sheet = ss.getSheetByName(tabName);
    if (!sheet) {
      sheet = ss.insertSheet(tabName);
    } else {
      sheet.clear();
    }

    // Tiêu đề đầu bảng
    var title = "DANH SÁCH ĐIỂM DANH - " + (data.class_name || data.class_id || "").toUpperCase();
    sheet.getRange(1, 1).setValue(title);
    sheet.getRange(1, 1).setFontSize(14).setFontWeight("bold").setFontColor("#1e3a8a");

    var subTitle = "Buổi " + sessionNumber + " | Ngày: " + sessionDate + " | Tiết: " + (data.start_period || 1) + "-" + (data.end_period || 3) + " | Cập nhật lúc: " + (data.synced_at || Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "HH:mm:ss dd/MM/yyyy"));
    sheet.getRange(2, 1).setValue(subTitle);
    sheet.getRange(2, 1).setFontSize(10).setFontStyle("italic").setFontColor("#64748b");

    // Header cột
    var isConference = !!data.is_conference;
    var idHeader = isConference ? "Mã GV/SV" : "MSSV";
    var headers = ["STT", idHeader, "Họ và Tên", "Vào lớp", "Ra về", "Điểm cộng", "Ghi chú", "Lý do vắng", "Trạng thái"];

    sheet.getRange(4, 1, 1, headers.length).setValues([headers]);
    sheet.getRange(4, 1, 1, headers.length)
      .setBackground("#1e40af")
      .setFontColor("#ffffff")
      .setFontWeight("bold")
      .setHorizontalAlignment("center")
      .setVerticalAlignment("middle");
    sheet.setRowHeight(4, 32);

    // Điền danh sách sinh viên
    var students = data.students || [];
    var rows = [];

    for (var i = 0; i < students.length; i++) {
      var s = students[i];
      rows.push([
        s.stt || (i + 1),
        s.student_id || "",
        s.full_name || "",
        s.check_in || "",
        s.check_out || "",
        s.bonus_points || 0,
        s.bonus_reason || "",
        s.absence_reason || "",
        s.status || "Vắng"
      ]);
    }

    if (rows.length > 0) {
      var dataRange = sheet.getRange(5, 1, rows.length, headers.length);
      dataRange.setValues(rows);
      dataRange.setFontSize(10);
      dataRange.setVerticalAlignment("middle");
      dataRange.setBorder(true, true, true, true, true, true, "#e2e8f0", SpreadsheetApp.BorderStyle.SOLID);

      // Căn giữa STT, MSSV, Giờ vào, Giờ ra, Điểm cộng, Trạng thái
      sheet.getRange(5, 1, rows.length, 2).setHorizontalAlignment("center");
      sheet.getRange(5, 4, rows.length, 3).setHorizontalAlignment("center");
      sheet.getRange(5, 9, rows.length, 1).setHorizontalAlignment("center");

      // Tô màu trạng thái
      for (var r = 0; r < rows.length; r++) {
        var statusCell = sheet.getRange(5 + r, 9);
        var val = rows[r][8];
        if (val === "Có mặt") {
          statusCell.setBackground("#dcfce7").setFontColor("#15803d").setFontWeight("bold");
        } else if (val === "Vắng có phép") {
          statusCell.setBackground("#f3e8ff").setFontColor("#7e22ce").setFontWeight("bold");
        } else {
          statusCell.setBackground("#fee2e2").setFontColor("#b91c1c");
        }

        // Tô màu điểm cộng nếu có
        var bonus = rows[r][5];
        if (bonus > 0) {
          sheet.getRange(5 + r, 6).setFontColor("#16a34a").setFontWeight("bold");
        } else if (bonus < 0) {
          sheet.getRange(5 + r, 6).setFontColor("#dc2626").setFontWeight("bold");
        }
      }
    }

    // Auto-fit các cột
    for (var col = 1; col <= headers.length; col++) {
      sheet.autoResizeColumn(col);
    }

    // 3. Tự động cập nhật Tab "Tổng hợp điểm danh"
    updateMasterSummary(ss, data);

    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      message: "Đã cập nhật " + rows.length + " sinh viên vào sheet '" + tabName + "'!",
      spreadsheet_url: ss.getUrl()
    })).setMimeType(ContentService.MimeType.JSON);

  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: error.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

// Cho phép kiểm tra URL qua trình duyệt (GET)
function doGet(e) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  return ContentService.createTextOutput(JSON.stringify({
    status: "online",
    message: "Google Apps Script Điểm danh đang hoạt động tốt!",
    spreadsheet_name: ss.getName(),
    spreadsheet_url: ss.getUrl()
  })).setMimeType(ContentService.MimeType.JSON);
}

/**
 * Cập nhật hoặc khởi tạo Tab "Tổng hợp điểm danh"
 */
function updateMasterSummary(ss, data) {
  var masterName = "Tổng hợp điểm danh";
  var master = ss.getSheetByName(masterName);
  var students = data.students || [];
  var sessionNum = data.session_number || 1;
  var maxSessions = 15; // Số buổi hiển thị tối đa

  if (!master) {
    master = ss.insertSheet(masterName, 0);
  }

  // Khởi tạo bảng tổng hợp nếu chưa có
  if (master.getLastRow() < 3) {
    master.clear();
    master.getRange(1, 1).setValue("BẢNG TỔNG HỢP ĐIỂM DANH - " + (data.class_name || data.class_id || "").toUpperCase());
    master.getRange(1, 1).setFontSize(14).setFontWeight("bold").setFontColor("#0f172a");

    var baseHeaders = ["STT", "MSSV", "Họ và Tên"];
    for (var b = 1; b <= maxSessions; b++) {
      baseHeaders.push("Buổi " + b);
    }
    baseHeaders.push("Tổng có mặt", "Tổng điểm cộng");

    master.getRange(3, 1, 1, baseHeaders.length).setValues([baseHeaders]);
    master.getRange(3, 1, 1, baseHeaders.length)
      .setBackground("#0f172a")
      .setFontColor("#ffffff")
      .setFontWeight("bold")
      .setHorizontalAlignment("center");
    master.setRowHeight(3, 30);

    var initRows = [];
    for (var i = 0; i < students.length; i++) {
      var row = [i + 1, students[i].student_id, students[i].full_name];
      for (var j = 0; j < maxSessions + 2; j++) row.push("");
      initRows.push(row);
    }

    if (initRows.length > 0) {
      master.getRange(4, 1, initRows.length, baseHeaders.length).setValues(initRows);
      master.getRange(4, 1, initRows.length, baseHeaders.length)
        .setBorder(true, true, true, true, true, true, "#e2e8f0", SpreadsheetApp.BorderStyle.SOLID);
    }

    for (var c = 1; c <= baseHeaders.length; c++) {
      master.autoResizeColumn(c);
    }
  }

  // Cập nhật điểm danh của buổi hiện tại vào cột tương ứng
  var colSession = 3 + sessionNum; // Cột bắt đầu từ cột 4 (Buổi 1)
  var lastRow = master.getLastRow();
  if (lastRow >= 4 && colSession <= (3 + maxSessions)) {
    var mssvList = master.getRange(4, 2, lastRow - 3, 1).getValues();
    var mssvToRow = {};
    for (var r = 0; r < mssvList.length; r++) {
      mssvToRow[String(mssvList[r][0]).trim()] = 4 + r;
    }

    for (var k = 0; k < students.length; k++) {
      var st = students[k];
      var rowIdx = mssvToRow[String(st.student_id).trim()];
      if (rowIdx) {
        var mark = st.status === "Có mặt" ? "✓" : (st.status === "Vắng có phép" ? "P" : "V");
        if (st.bonus_points > 0) {
          mark += " (+" + st.bonus_points + ")";
        } else if (st.bonus_points < 0) {
          mark += " (" + st.bonus_points + ")";
        }

        var cell = master.getRange(rowIdx, colSession);
        cell.setValue(mark).setHorizontalAlignment("center").setFontWeight("bold");

        if (st.status === "Có mặt") {
          cell.setBackground("#dcfce7").setFontColor("#15803d");
        } else if (st.status === "Vắng có phép") {
          cell.setBackground("#f3e8ff").setFontColor("#7e22ce");
        } else {
          cell.setBackground("#fee2e2").setFontColor("#b91c1c");
        }
      }
    }
  }
}
