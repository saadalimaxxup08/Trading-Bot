import os
import sys
import subprocess
import http.server
import socketserver
import requests

class HealthHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # 1. Endpoint to display live console logs of worker.py
        if self.path == "/logs":
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            
            log_content = ""
            if os.path.exists("worker_log.txt"):
                try:
                    with open("worker_log.txt", "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        # Show last 300 lines of logs
                        log_content = "".join(lines[-300:])
                except Exception as e:
                    log_content = f"Error reading log file: {e}"
            else:
                log_content = "Log file worker_log.txt does not exist yet. The worker process has not started or written any logs."
                
            self.wfile.write(log_content.encode())
            return

        # 2. Manual Test Alert Endpoint
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
            
        # 3. Root health check landing page
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body><h1>Binary Pro Scanner V4 is Active and Scanning 24/7!</h1><p>Visit <a href='/logs'>/logs</a> to view live server logs.</p></body></html>")

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

    # 1. Start the main bot scanner as a background subprocess and redirect output/errors to worker_log.txt
    print("[BOT] Launching worker.py scanner process...")
    try:
        # bufsize=1 enables line-buffering so logs are written immediately
        log_file = open("worker_log.txt", "w", encoding="utf-8", buffering=1)
        subprocess.Popen([sys.executable, "worker.py"], stdout=log_file, stderr=log_file)
        print("[BOT] worker.py successfully spawned in background. Output redirected to worker_log.txt.")
    except Exception as e:
        print(f"[BOT Launch Error]: Failed to start worker.py: {e}")

    # 2. Run the HTTP server in the main thread to keep Render alive
    run_web_server()

if __name__ == "__main__":
    main()
