import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import subprocess

# 1. Простой сервер, чтобы Koyeb видел, что мы живы
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# 2. Запускаем сервер в фоне
threading.Thread(target=run_server, daemon=True).start()

# 3. Запускаем твоего бота (замени 3.py, если файл называется иначе)
subprocess.run(["python", "3.py"])