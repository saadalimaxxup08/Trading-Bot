import os
import sys
import subprocess
import http.server
import socketserver
import requests

class HealthHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/test_alert":
            try:
                token = os.environ.get("TELEGRAM_BOT_TOKEN")
                chat_id = os.environ.get("TELEGRAM_CHAT_ID")
                
                if token:
                    token = token.strip().strip('"').strip("'")
                if chat_id:
                    chat_id = chat_id.strip().strip('"').strip("'")
                    
                if token and chat_id:
                    url = f"https://api.telegram.org/bot{token}/sendMessage"
                    payload = {
                        "chat_id": chat_id,
                        "text": "🧪 <b>Render Server Test:</b> Hello! This message was sent directly from the Render Cloud hosting bot. Everything is working perfectly!",
                        "parse_mode": "HTML"
                    }
                    res = requests.post(url, json=payload, timeout=10)
                    if res.status_code == 200:
                        msg = "Test alert sent successfully to Telegram!"
                    else:
                        msg = f"Telegram API Error: {res.text}"
                else:
                    msg = "Credentials missing (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured on Render)."
            except Exception as e:
                msg = f"Error sending test: {e}"
                
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(f"<html><body><h1>{msg}</h1></body></html>".encode())
            return
            
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body><h1>Binary Pro Scanner V4 is Active and Scanning 24/7!</h1></body></html>")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    handler = HealthHandler
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"[WEB] Hosting health check page on port {port}")
        httpd.serve_forever()

def main():
    print("=========================================")
    print("[RENDER START] INITIALIZING SERVICE")
    print("=========================================")

    # 1. Start the main bot scanner as a background subprocess
    print("[BOT] Launching worker.py scanner process...")
    subprocess.Popen([sys.executable, "worker.py"])
    print("[BOT] worker.py successfully spawned in background.")

    # 2. Run the HTTP server in the main thread to keep Render alive
    run_web_server()

if __name__ == "__main__":
    main()
