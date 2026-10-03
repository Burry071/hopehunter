"""Scripted stand-in for Ollama that answers with the app's own saved output.

Throwaway tooling for the demo recording, not part of the app. It replies to each job with
the words a real gemma3:4b run already produced for the same card (kept in
dev/demo_fixtures.json), so the walkthrough shows genuine model output without waiting on
the GPU. A short pause is added so the button's own waiting state lands in the frames.

    python dev/demo_ollama.py                      # terminal one, on STUB_PORT
    cd _demo && OLLAMA_URL=http://127.0.0.1:11439 python app.py   # terminal two
    node dev/record.mjs <cdpPort> http://127.0.0.1:8010/ <card.html> _demo/frames
    python dev/make_gif.py                         # -> shots/demo.gif
"""
import json
import os
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = Path(__file__).parent.parent
FIX = json.loads((ROOT / "dev" / "demo_fixtures.json").read_text(encoding="utf-8"))
MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
PORT = int(os.environ.get("STUB_PORT", "11439"))
DELAY = float(os.environ.get("DEMO_DELAY", "1.4"))


def reply_for(system):
    if "screen web posts" in system:
        return json.dumps({"is_opportunity": True, "type": "hackathon",
                           "reason": FIX["feed"][0]["reason"]})
    if "career coach" in system:
        return json.dumps(FIX["match"])
    if "application message" in system:
        return FIX["draft"]
    return json.dumps(FIX["fields"])


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._json({"models": [{"name": MODEL}]})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        system = json.loads(self.rfile.read(length))["messages"][0]["content"]
        time.sleep(DELAY)
        self._json({"message": {"content": reply_for(system)}})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"demo model on http://127.0.0.1:{PORT}, answering in {DELAY}s")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
