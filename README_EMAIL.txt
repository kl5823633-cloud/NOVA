================================================================
  HƯỚNG DẪN CẤU HÌNH EMAIL ĐỂ NOVA AI GỬI MÃ OTP
================================================================

Để Nova gửi mã xác thực (OTP) thẳng về Gmail người dùng, bạn cần
khai báo 1 tài khoản Gmail làm "người gửi" trong file:

    email_config.json

--------------------------------------------------------------
BƯỚC 1 — Bật xác minh 2 bước cho tài khoản Google
--------------------------------------------------------------
1. Vào: https://myaccount.google.com/security
2. Tìm mục "Xác minh 2 bước" (2-Step Verification) -> Bật.
   (Bắt buộc, vì App Password chỉ xuất hiện khi đã bật 2 bước.)

--------------------------------------------------------------
BƯỚC 2 — Tạo App Password (mật khẩu ứng dụng)
--------------------------------------------------------------
1. Vào: https://myaccount.google.com/apppasswords
2. Đặt tên bất kỳ (ví dụ: "Nova AI") -> bấm Tạo (Create).
3. Google hiện 1 chuỗi 16 ký tự, ví dụ:  abcd efgh ijkl mnop
   -> Copy chuỗi này (có thể bỏ dấu cách: abcdefghijklmnop).

   LƯU Ý: App Password KHÁC mật khẩu đăng nhập Gmail thường.
   Không dùng mật khẩu Gmail thường ở đây — sẽ báo lỗi đăng nhập.

--------------------------------------------------------------
BƯỚC 3 — Điền vào file email_config.json
--------------------------------------------------------------
Mở file email_config.json (cùng thư mục server.py) và sửa:

    {
      "email": "tencuaban@gmail.com",
      "app_password": "abcdefghijklmnop",
      "host": "smtp.gmail.com",
      "port": 587
    }

- "email"        : Gmail bạn dùng để gửi mã
- "app_password" : chuỗi 16 ký tự ở Bước 2 (bỏ dấu cách)
- host/port      : giữ nguyên cho Gmail

--------------------------------------------------------------
BƯỚC 4 — Chạy server
--------------------------------------------------------------
    python server.py

Nếu cấu hình đúng, console sẽ hiện:
    ✅ Email gửi OTP đã cấu hình: tencuaban@gmail.com

Nếu sai/chưa cấu hình, console sẽ hiện cảnh báo và nút "Gửi mã"
trên web sẽ báo lỗi rõ ràng (không có chế độ dev tự điền mã nữa).

--------------------------------------------------------------
CÁCH HOẠT ĐỘNG
--------------------------------------------------------------
- Người dùng nhập email khi đăng ký -> bấm "Gửi mã".
- Nova gửi mã 6 số tới Gmail đó (hết hạn sau 10 phút).
- Người dùng PHẢI mở hòm thư (kể cả mục Spam/Quảng cáo) để lấy mã,
  rồi nhập vào ô "Mã xác nhận (OTP)" để hoàn tất đăng ký.

--------------------------------------------------------------
CÁCH KHÁC: dùng biến môi trường (không cần file)
--------------------------------------------------------------
PowerShell:
    $env:GMAIL_USER = "tencuaban@gmail.com"
    $env:GMAIL_APP_PASSWORD = "abcdefghijklmnop"
    python server.py

================================================================
