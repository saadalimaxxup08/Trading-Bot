import os
import sys
import subprocess
import http.server
import socketserver

class HealthHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
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
