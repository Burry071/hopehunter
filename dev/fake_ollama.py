"""Throwaway stand-in for Ollama, for exercising HopeHunter without a GPU.

Not part of the app. Run it beside the app to click through every screen, or to record the
demo without waiting on a real model:
    python dev/fake_ollama.py      # in one terminal
    python app.py                  # in another

It answers each of the four jobs the app asks for. The deadline it returns is a real date
in ISO form, so the grounding check verifies it against whatever page text you give it and
shows "unconfirmed" when the page does not actually print that date.

Real Ollama owns port 11434. Either quit Ollama first, or run this elsewhere and point the
app at it:
    STUB_PORT=11435 python dev/fake_ollama.py
    OLLAMA_URL=http://127.0.0.1:11435 python app.py
"""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
PORT = int(os.environ.get("STUB_PORT", "11434"))

EXTRACT = {
    "title": "Summer Research Scholarship", "organization": "Viva Institute",
    "type": "scholarship", "deadline": "5 March 2027", "deadline_iso": "2027-03-05",
    "deadline_quote": "Apply by 5 March 2027", "location": "Remote",
    "eligibility": ["Open to undergraduates"], "benefits": ["Tuition covered"],
    "how_to_apply": "Send one PDF.", "summary": "It covers tuition. Open to undergraduates.",
}
TRIAGE = {"is_opportunity": True, "type": "hackathon",
          "reason": "A build-with-Python hackathon, open to students."}
MATCH = {"why": ["Two Python projects", "Final year CS"],
         "gaps": ["No prior fellowship"], "next_steps": ["Write the one-page CV"]}
DRAFT = ("Dear committee,\n\nI am a final-year computer science student. I have built two "
         "tools in Python and I want to keep building. Thank you for reading this.")


def reply_for(system):
    if "screen web posts" in system:
        return json.dumps(TRIAGE)
    if "career coach" in system:
        return json.dumps(MATCH)
    if "application message" in system:
        return DRAFT
    return json.dumps(EXTRACT)


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
        self._json({"message": {"content": reply_for(system)}})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"fake Ollama on http://127.0.0.1:{PORT}, offering model '{MODEL}'")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
