"""TCP Server giao tiếp với Dobot MG400. Mọi sự kiện được báo qua log_callback(text, level)."""
import select
import socket

class DobotTCPServer:
    def __init__(self, port=12345, host="0.0.0.0", allowed_ip_prefix="192.168.2.", log_callback=None):
        self.host = host
        self.port = port
        self.allowed_ip_prefix = allowed_ip_prefix
        self.log_callback = log_callback      # hàm (text, level) để hiện lên khung log của giao diện
        self.server_socket = None
        self.client_socket = None
        self.client_address = None
        self.is_connected = False
        self.rx_buffer = ""          # dữ liệu Dobot gửi lên nhưng chưa đủ 1 dòng

        self.start_listening()

    def _log(self, text, level="info"):
        print(text)
        if self.log_callback:
            try:
                self.log_callback(text, level)
            except Exception:
                pass

    def start_listening(self):
        try:
            if self.server_socket is None:
                self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.server_socket.bind((self.host, self.port))
                self.server_socket.listen(1)
                self._log(f"🟢 Dobot Server mở cổng {self.port}, nhận IP dải {self.allowed_ip_prefix}x...")
            return True
        except Exception as e:
            self._log(f"❌ Lỗi khởi tạo Server trên port {self.port}: {e}", "ng")
            return False

    def check_and_accept(self):
        """Gọi định kỳ từ giao diện. Không chặn luồng GUI (dùng select, timeout = 0)."""
        if self.is_connected:
            return True

        if not self.start_listening():
            return False

        try:
            readable, _, _ = select.select([self.server_socket], [], [], 0)
            if not readable:
                return False

            client_soc, client_addr = self.server_socket.accept()
            client_ip = client_addr[0]

            if self.allowed_ip_prefix and not client_ip.startswith(self.allowed_ip_prefix):
                self._log(f"⛔ Từ chối kết nối từ IP: {client_ip}", "warn")
                client_soc.close()
                return False

            self.client_socket = client_soc
            self.client_address = client_addr
            self.client_socket.settimeout(2.0)
            self.is_connected = True
            self._log(f"✅ Đã kết nối Dobot IP: {client_ip}:{client_addr[1]}", "ok")
            return True
        except Exception as e:
            self._log(f"⚠️ Lỗi nhận kết nối: {e}", "warn")
            return False

    def send_signal(self, command_str):
        if not self.is_connected or not self.client_socket:
            self._log(f"⚠️ Dobot chưa kết nối. Bỏ qua lệnh: {command_str}", "warn")
            return False

        try:
            msg = f"{command_str}\n"
            self.client_socket.sendall(msg.encode("utf-8"))
            self._log(f"📤 PC → Dobot: {msg!r}", "tx")
            return True
        except Exception as e:
            self._log(f"⚠️ Lỗi gửi tín hiệu Dobot: {e}", "warn")
            self._mark_disconnected()
            return False

    def _mark_disconnected(self):
        if self.client_socket:
            try:
                self.client_socket.close()
            except Exception:
                pass
        self.client_socket = None
        self.is_connected = False
        self.rx_buffer = ""

    def poll_messages(self):
        """Đọc các tin Dobot gửi lên (không chặn). Mỗi tin kết thúc bằng xuống dòng. Trả về list chuỗi."""
        if not self.is_connected or not self.client_socket:
            return []
        got_data = False
        try:
            while select.select([self.client_socket], [], [], 0)[0]:
                data = self.client_socket.recv(1024)
                if not data:                               # Dobot đã đóng kết nối
                    self._log("⚠️ Dobot ngắt kết nối.", "warn")
                    self._mark_disconnected()
                    return []
                got_data = True
                self.rx_buffer += data.decode("utf-8", errors="ignore")
        except OSError as e:
            self._log(f"⚠️ Lỗi đọc từ Dobot: {e}", "warn")
            self._mark_disconnected()
            return []

        lines = self.rx_buffer.split("\n")
        self.rx_buffer = lines.pop()                       # phần chưa đủ 1 dòng giữ lại
        messages = [ln.strip() for ln in lines if ln.strip()]

        for m in messages:
            self._log(f"📥 Dobot → PC: {m!r}", "rx")
        if got_data and self.rx_buffer.strip():            # lỗi hay gặp: Dobot quên ký tự xuống dòng
            self._log(f"⚠️ Dobot gửi chưa có ký tự xuống dòng, đang chờ: {self.rx_buffer!r}", "warn")
        return messages

    def close(self):
        if self.client_socket:
            try:
                self.client_socket.close()
            except Exception:
                pass
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
        self.client_socket = None
        self.server_socket = None
        self.is_connected = False
        self._log("🔴 Đã đóng Socket Server.")