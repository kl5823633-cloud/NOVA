"""
Nova AI - Local proxy server với đăng nhập, đăng ký qua email OTP, và upload ảnh.

Yêu cầu:
    pip install pillow

Cách dùng:
    python server.py
Sau đó mở http://localhost:8000 trên trình duyệt.
"""
import http.server
import socketserver
import urllib.request
import urllib.error
import os
import json
import hashlib
import secrets
import smtplib
import base64
import time
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "0.0.0.0")
UPSTREAM = "https://api.freemodel.dev"
ROOT = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(ROOT, "users.json")

# Connection string PostgreSQL (Render cấp qua biến môi trường DATABASE_URL).
# Nếu KHÔNG có -> tự động dùng file users.json (chạy local không cần Postgres).
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# ===== CẤU HÌNH EMAIL (Gmail) =====
# Cấu hình được đọc từ file email_config.json (cùng thư mục) hoặc biến môi trường.
# KHÔNG sửa trực tiếp ở đây - hãy điền vào email_config.json
EMAIL_CONFIG_FILE = os.path.join(ROOT, "email_config.json")


def load_email_config():
    """Đọc cấu hình email từ email_config.json hoặc biến môi trường."""
    cfg = {
        "email": os.environ.get("GMAIL_USER", ""),
        "app_password": os.environ.get("GMAIL_APP_PASSWORD", ""),
        "host": "smtp.gmail.com",
        "port": 587,
    }
    if os.path.exists(EMAIL_CONFIG_FILE):
        try:
            with open(EMAIL_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("email"):
                cfg["email"] = data["email"].strip()
            if data.get("app_password"):
                cfg["app_password"] = data["app_password"].strip()
            if data.get("host"):
                cfg["host"] = data["host"].strip()
            if data.get("port"):
                cfg["port"] = int(data["port"])
        except Exception as e:
            print(f"[EMAIL CONFIG] Lỗi đọc {EMAIL_CONFIG_FILE}: {e}")
    return cfg


# Brevo (Sendinblue) HTTP API - dùng cho host chặn SMTP như Render.
# Lấy API key free tại https://app.brevo.com (Settings -> SMTP & API -> API Keys).
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "").strip()
# Email người gửi (phải là email đã verify trong Brevo). Mặc định lấy GMAIL_USER.
BREVO_SENDER = os.environ.get("BREVO_SENDER", "").strip() or os.environ.get("GMAIL_USER", "").strip()


def email_is_configured():
    """True nếu có thể gửi email (qua Brevo HTTP API hoặc SMTP Gmail)."""
    # Ưu tiên Brevo (hoạt động trên Render)
    if BREVO_API_KEY and BREVO_SENDER and "@" in BREVO_SENDER:
        return True
    # SMTP Gmail (chạy local)
    c = load_email_config()
    email = c["email"]
    pw = c["app_password"]
    if not email or not pw:
        return False
    if "your_" in email.lower() or "your_" in pw.lower():
        return False
    return "@" in email


# ===== DATABASE =====
# Có DATABASE_URL  -> dùng PostgreSQL (dữ liệu KHÔNG mất khi host restart).
# Không có          -> dùng file users.json (tiện chạy local).
# Cả hai cùng giao diện load_db()/save_db() trả về dict:
#   {"users": {email: {...}}, "otps": {email: {"code":..., "expires":...}}}

_pg = None
if DATABASE_URL:
    try:
        import psycopg2
        import psycopg2.extras
        _pg = psycopg2
    except ImportError:
        print("[DB] Thiếu thư viện psycopg2-binary. Chạy: pip install psycopg2-binary")
        raise


def _pg_connect():
    # Render cấp URL dạng postgres://; psycopg2 chấp nhận cả postgresql://
    return _pg.connect(DATABASE_URL, sslmode=os.environ.get("PGSSLMODE", "require"))


def init_db():
    """Tạo bảng nếu chưa có (chỉ với Postgres)."""
    if not _pg:
        return
    with _pg_connect() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                email    TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                created  DOUBLE PRECISION
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS otps (
                email   TEXT PRIMARY KEY,
                code    TEXT NOT NULL,
                expires DOUBLE PRECISION
            )
        """)
        conn.commit()


def load_db():
    if not _pg:
        if not os.path.exists(DB_FILE):
            return {"users": {}, "otps": {}}
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"users": {}, "otps": {}}

    db = {"users": {}, "otps": {}}
    with _pg_connect() as conn, conn.cursor(cursor_factory=_pg.extras.RealDictCursor) as cur:
        cur.execute("SELECT email, username, password, created FROM users")
        for row in cur.fetchall():
            db["users"][row["email"]] = {
                "username": row["username"],
                "password": row["password"],
                "email": row["email"],
                "created": row["created"],
            }
        cur.execute("SELECT email, code, expires FROM otps")
        for row in cur.fetchall():
            db["otps"][row["email"]] = {"code": row["code"], "expires": row["expires"]}
    return db


def save_db(db):
    if not _pg:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        return

    users = db.get("users", {})
    otps = db.get("otps", {})
    with _pg_connect() as conn, conn.cursor() as cur:
        # Đồng bộ bảng users theo dict hiện tại
        cur.execute("SELECT email FROM users")
        existing_users = {r[0] for r in cur.fetchall()}
        for email in existing_users - set(users.keys()):
            cur.execute("DELETE FROM users WHERE email = %s", (email,))
        for email, u in users.items():
            cur.execute("""
                INSERT INTO users (email, username, password, created)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE
                SET username = EXCLUDED.username,
                    password = EXCLUDED.password,
                    created  = EXCLUDED.created
            """, (email, u.get("username"), u.get("password"), u.get("created")))

        # Đồng bộ bảng otps
        cur.execute("SELECT email FROM otps")
        existing_otps = {r[0] for r in cur.fetchall()}
        for email in existing_otps - set(otps.keys()):
            cur.execute("DELETE FROM otps WHERE email = %s", (email,))
        for email, o in otps.items():
            cur.execute("""
                INSERT INTO otps (email, code, expires)
                VALUES (%s, %s, %s)
                ON CONFLICT (email) DO UPDATE
                SET code = EXCLUDED.code, expires = EXCLUDED.expires
            """, (email, o.get("code"), o.get("expires")))
        conn.commit()


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def generate_otp():
    return str(secrets.randbelow(900000) + 100000)  # 6 chữ số


def _otp_email_html(otp_code):
    return f"""
        <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;background:#12121a;color:#e8e8f0;border-radius:16px;padding:32px">
          <div style="text-align:center;margin-bottom:24px">
            <div style="width:60px;height:60px;background:linear-gradient(135deg,#7c5cff,#00d4ff);border-radius:14px;display:inline-flex;align-items:center;justify-content:center;font-size:28px;font-weight:800;color:#fff">N</div>
            <h2 style="background:linear-gradient(135deg,#7c5cff,#00d4ff);-webkit-background-clip:text;color:transparent;margin-top:12px">Nova AI</h2>
          </div>
          <p style="color:#9999a8;text-align:center">Mã xác thực đăng ký tài khoản của bạn:</p>
          <div style="background:#1a1a25;border:2px solid #7c5cff;border-radius:12px;padding:20px;text-align:center;margin:20px 0">
            <span style="font-size:36px;font-weight:800;letter-spacing:8px;color:#9277ff">{otp_code}</span>
          </div>
          <p style="color:#66667a;font-size:13px;text-align:center">Mã có hiệu lực trong <strong>10 phút</strong>. Không chia sẻ mã này với ai.</p>
        </div>
        """


def _send_otp_via_brevo(to_email, otp_code):
    """Gửi OTP qua Brevo HTTP API (port 443 - không bị Render chặn). Trả về (ok, msg)."""
    payload = json.dumps({
        "sender": {"name": "Nova AI", "email": BREVO_SENDER},
        "to": [{"email": to_email}],
        "subject": "Nova AI - Mã xác thực đăng ký",
        "htmlContent": _otp_email_html(otp_code),
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        method="POST",
        headers={
            "api-key": BREVO_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if 200 <= resp.status < 300:
                return True, "OK"
            return False, f"Brevo trả về mã {resp.status}"
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "ignore")
        except Exception:
            detail = str(e)
        return False, f"Brevo lỗi {e.code}: {detail}"
    except Exception as e:
        return False, str(e)


def _send_otp_via_smtp(to_email, otp_code):
    """Gửi OTP qua SMTP Gmail (dùng khi chạy local). Trả về (ok, msg)."""
    c = load_email_config()
    smtp_email = c["email"]
    smtp_pass = c["app_password"]
    smtp_host = c["host"]
    smtp_port = c["port"]
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Nova AI - Mã xác thực đăng ký"
        msg["From"] = f"Nova AI <{smtp_email}>"
        msg["To"] = to_email
        msg.attach(MIMEText(_otp_email_html(otp_code), "html"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.starttls()
            server.login(smtp_email, smtp_pass)
            server.sendmail(smtp_email, to_email, msg.as_string())
        return True, "OK"
    except smtplib.SMTPAuthenticationError:
        return False, "Sai email hoặc App Password. Kiểm tra lại email_config.json."
    except Exception as e:
        return False, str(e)


def send_otp_email(to_email, otp_code):
    """Gửi mã OTP. Ưu tiên Brevo (chạy trên host), fallback SMTP Gmail (local)."""
    if BREVO_API_KEY and BREVO_SENDER:
        return _send_otp_via_brevo(to_email, otp_code)
    return _send_otp_via_smtp(to_email, otp_code)


# ===== SESSION (đơn giản bằng token) =====
SESSIONS = {}  # token -> username


def create_session(username):
    token = secrets.token_hex(32)
    SESSIONS[token] = {"username": username, "created": time.time()}
    return token


def get_session(token):
    if not token:
        return None
    s = SESSIONS.get(token)
    if s and time.time() - s["created"] < 86400 * 7:  # 7 ngày
        return s["username"]
    return None


# ===== HTTP HANDLER =====
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def get_token(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return None

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        if self.path == "/":
            self.path = "/ai-chatbot.html"
        if self.path.startswith("/v1/"):
            return self._proxy("GET")
        return super().do_GET()

    def do_POST(self):
        if self.path == "/auth/send-otp":
            return self._handle_send_otp()
        if self.path == "/auth/register":
            return self._handle_register()
        if self.path == "/auth/login":
            return self._handle_login()
        if self.path == "/auth/check":
            return self._handle_check()
        if self.path == "/upload/image":
            return self._handle_upload_image()
        if self.path.startswith("/v1/"):
            return self._proxy("POST")
        self.send_error(404)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _read_json(self):
        body = self._read_body()
        try:
            return json.loads(body)
        except Exception:
            return {}

    # --- Auth endpoints ---
    def _handle_send_otp(self):
        data = self._read_json()
        email = (data.get("email") or "").strip().lower()
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return self.send_json(400, {"error": "Email không hợp lệ"})

        # Bắt buộc đã cấu hình email server, không có chế độ dev
        if not email_is_configured():
            return self.send_json(503, {
                "error": "Server chưa cấu hình email gửi OTP. Vui lòng điền email_config.json (xem README)."
            })

        db = load_db()
        if email in db["users"]:
            return self.send_json(409, {"error": "Email này đã được đăng ký"})

        otp = generate_otp()
        db["otps"][email] = {"code": otp, "expires": time.time() + 600}
        save_db(db)

        ok, msg = send_otp_email(email, otp)
        if ok:
            print(f"[OTP] Đã gửi mã tới {email}")
            self.send_json(200, {"message": "Đã gửi mã OTP đến email của bạn. Vui lòng kiểm tra hòm thư."})
        else:
            # Gửi thất bại -> xóa OTP vừa tạo, báo lỗi thật
            db = load_db()
            db["otps"].pop(email, None)
            save_db(db)
            print(f"[OTP] Gửi thất bại tới {email}: {msg}")
            self.send_json(502, {"error": f"Không gửi được email: {msg}"})

    def _handle_register(self):
        data = self._read_json()
        email = (data.get("email") or "").strip().lower()
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        otp = (data.get("otp") or "").strip()

        if not email or not username or not password or not otp:
            return self.send_json(400, {"error": "Thiếu thông tin"})
        if len(username) < 3:
            return self.send_json(400, {"error": "Tên tài khoản phải có ít nhất 3 ký tự"})
        if len(password) < 6:
            return self.send_json(400, {"error": "Mật khẩu phải có ít nhất 6 ký tự"})

        db = load_db()
        otp_data = db["otps"].get(email)
        if not otp_data:
            return self.send_json(400, {"error": "Chưa gửi OTP hoặc OTP đã hết hạn"})
        if time.time() > otp_data["expires"]:
            return self.send_json(400, {"error": "Mã OTP đã hết hạn, vui lòng gửi lại"})
        if otp_data["code"] != otp:
            return self.send_json(400, {"error": "Mã OTP không đúng"})

        if email in db["users"]:
            return self.send_json(409, {"error": "Email đã được đăng ký"})
        # Kiểm tra username trùng
        for u in db["users"].values():
            if u["username"].lower() == username.lower():
                return self.send_json(409, {"error": "Tên tài khoản đã tồn tại"})

        db["users"][email] = {
            "username": username,
            "password": hash_password(password),
            "email": email,
            "created": time.time()
        }
        del db["otps"][email]
        save_db(db)

        token = create_session(username)
        self.send_json(200, {"message": "Đăng ký thành công!", "token": token, "username": username})

    def _handle_login(self):
        data = self._read_json()
        login = (data.get("login") or "").strip().lower()  # email hoặc username
        password = data.get("password") or ""

        db = load_db()
        found = None
        for email, u in db["users"].items():
            if email == login or u["username"].lower() == login:
                found = u
                break

        if not found or found["password"] != hash_password(password):
            return self.send_json(401, {"error": "Tài khoản hoặc mật khẩu không đúng"})

        token = create_session(found["username"])
        self.send_json(200, {"message": "Đăng nhập thành công!", "token": token, "username": found["username"]})

    def _handle_check(self):
        token = self.get_token()
        username = get_session(token)
        if username:
            self.send_json(200, {"authenticated": True, "username": username})
        else:
            self.send_json(401, {"authenticated": False})

    # --- Upload ảnh ---
    def _handle_upload_image(self):
        token = self.get_token()
        if not get_session(token):
            return self.send_json(401, {"error": "Chưa đăng nhập"})

        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0))
        if length > 10 * 1024 * 1024:  # 10MB limit
            return self.send_json(400, {"error": "Ảnh quá lớn (tối đa 10MB)"})

        body = self.rfile.read(length)

        # Tìm boundary trong multipart
        if "multipart/form-data" in content_type:
            boundary = content_type.split("boundary=")[-1].strip().encode()
            parts = body.split(b"--" + boundary)
            for part in parts:
                if b"Content-Disposition" in part and b'name="image"' in part:
                    # Tìm data sau header
                    header_end = part.find(b"\r\n\r\n")
                    if header_end == -1:
                        continue
                    img_data = part[header_end + 4:]
                    if img_data.endswith(b"\r\n"):
                        img_data = img_data[:-2]

                    # Detect mime type
                    mime = "image/jpeg"
                    if img_data[:8] == b"\x89PNG\r\n\x1a\n":
                        mime = "image/png"
                    elif img_data[:4] == b"GIF8":
                        mime = "image/gif"
                    elif img_data[:4] == b"RIFF":
                        mime = "image/webp"

                    b64 = base64.b64encode(img_data).decode()
                    return self.send_json(200, {
                        "base64": b64,
                        "mime": mime,
                        "data_url": f"data:{mime};base64,{b64}"
                    })
            return self.send_json(400, {"error": "Không tìm thấy ảnh trong request"})

        # Raw binary
        mime = "image/jpeg"
        if body[:8] == b"\x89PNG\r\n\x1a\n":
            mime = "image/png"
        b64 = base64.b64encode(body).decode()
        self.send_json(200, {
            "base64": b64,
            "mime": mime,
            "data_url": f"data:{mime};base64,{b64}"
        })

    # --- Proxy đến freemodel.dev ---
    def _proxy(self, method):
        target = UPSTREAM + self.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else None

        req = urllib.request.Request(target, data=body, method=method)
        for h in ("Authorization", "Content-Type", "Accept"):
            v = self.headers.get(h)
            if v:
                req.add_header(h, v)

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                self.send_response(resp.status)
                ctype = resp.headers.get("Content-Type", "application/octet-stream")
                self.send_header("Content-Type", ctype)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                while True:
                    chunk = resp.read(1024)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(f'{{"error":"proxy error: {e}"}}'.encode())


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    init_db()
    print(f"Nova AI server đang chạy tại cổng {PORT} (host {HOST})")
    if HOST in ("0.0.0.0", ""):
        print(f"Local: mở http://localhost:{PORT}")
    print(f"Lưu trữ user: {'PostgreSQL (DATABASE_URL)' if DATABASE_URL else DB_FILE}")
    print()
    if email_is_configured():
        if BREVO_API_KEY and BREVO_SENDER:
            print(f"✅ Email gửi OTP qua Brevo API. Người gửi: {BREVO_SENDER}")
        else:
            c = load_email_config()
            print(f"✅ Email gửi OTP qua SMTP Gmail: {c['email']}")
    else:
        print("⚠️  CHƯA cấu hình email gửi OTP!")
        print("   Cách 1 (khuyên dùng trên host): đặt BREVO_API_KEY + BREVO_SENDER.")
        print("   Cách 2 (local): điền email_config.json hoặc GMAIL_USER/GMAIL_APP_PASSWORD.")
    print()
    print("Nhấn Ctrl+C để dừng.\n")
    with ThreadedServer((HOST, PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nĐã dừng server.")
