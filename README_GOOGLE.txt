========================================
  HƯỚNG DẪN BẬT ĐĂNG NHẬP BẰNG GOOGLE
========================================

Bạn cần một "OAuth Client ID" của Google (miễn phí). Client ID KHÔNG phải
mật khẩu bí mật — nó vốn lộ ra trong trình duyệt — nên cứ yên tâm dán vào file.

------------------------------------------------------------
BƯỚC 1 — Tạo Client ID trên Google Cloud Console
------------------------------------------------------------
1. Mở: https://console.cloud.google.com/
2. Tạo một Project mới (hoặc dùng project sẵn có).
3. Vào menu "APIs & Services" -> "OAuth consent screen":
   - Chọn "External" -> Create.
   - Điền: App name (vd Nova AI), User support email, Developer email.
   - Lưu lại. Nếu app đang ở chế độ "Testing", thêm email Gmail của bạn
     vào mục "Test users" (hoặc bấm "Publish app" để ai cũng đăng nhập được).
4. Vào "APIs & Services" -> "Credentials":
   - Bấm "Create Credentials" -> "OAuth client ID".
   - Application type: chọn "Web application".
   - Mục "Authorized JavaScript origins", thêm CHÍNH XÁC (kèm cổng):
        http://localhost:8000
        (và nếu deploy Render thì thêm:  https://TEN-APP.onrender.com)
   - KHÔNG cần điền "Authorized redirect URIs".
   - Bấm "Create".
5. Copy chuỗi "Client ID" (dạng: 1234567890-abcdxxxx.apps.googleusercontent.com)

------------------------------------------------------------
BƯỚC 2 — Dán Client ID vào app
------------------------------------------------------------
CÁCH A (chạy local): mở file google_config.json và điền:
    {
      "client_id": "1234567890-abcdxxxx.apps.googleusercontent.com"
    }

CÁCH B (deploy Render): đặt biến môi trường
    GOOGLE_CLIENT_ID = 1234567890-abcdxxxx.apps.googleusercontent.com

------------------------------------------------------------
BƯỚC 3 — Khởi động lại server
------------------------------------------------------------
    python server.py
Mở lại http://localhost:8000 -> sẽ thấy nút "Tiếp tục với Google" dưới form.

LƯU Ý:
- Phải mở qua http://localhost:8000 (không mở trực tiếp file .html), vì Google
  yêu cầu trang chạy trên origin đã đăng ký.
- Origin phải khớp tuyệt đối: đúng giao thức (http/https), đúng tên miền, đúng cổng.
- Tên hiển thị của tài khoản Google vẫn theo quy tắc 2 chữ cái đầu của email
  (vd uliueke@gmail.com -> "ul"), đồng bộ với đăng ký thường.
