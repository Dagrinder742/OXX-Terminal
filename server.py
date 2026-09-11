import http.server
import json
import os

PORT = 8080

class OXXHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            # Read agent memory
            if os.path.exists("agent_memory.json"):
                with open("agent_memory.json", "r", encoding="utf-8") as f:
                    data = f.read()
            else:
                data = json.dumps({"error": "agent_memory.json not found"})

            self.wfile.write(data.encode("utf-8"))
        elif self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OXX Terminal Python Backend Active. Hit /api/status for telemetry.")
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    server = http.server.HTTPServer(("localhost", PORT), OXXHandler)
    print(f"[*] OXX Local Backend running at http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Server stopped.")
