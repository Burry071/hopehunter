"""Times the three real jobs HopeHunter asks the model to do.

Not part of the app. Run it with a model loaded to decide whether your machine
handles that model, or to compare two of them:
    OLLAMA_MODEL=gemma3:4b python dev/bench.py
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402

PAGE = """Global Hack Week 2027

A fully online hackathon for people who have never contributed to open source.
Mentors from ten companies review every project. Prizes total $5,000.

Posted 12 January 2027 by the organising team.

Who can join
Open to any student currently enrolled, anywhere in the world. Teams of two to four.

How to take part
Register on the site, then submit a project repository. Apply by 5 March 2027
to be considered for a prize.
"""

PROFILE = "Final year CS student, Pakistan. Python, some JavaScript. Two side projects. Never to a hackathon."

SAMPLE = {"title": "Global Hack Week 2027", "organization": "Global Hack Week", "type": "hackathon",
          "deadline": "5 March 2027", "deadline_iso": "2027-03-05",
          "deadline_quote": "Apply by 5 March 2027 to be considered for a prize.",
          "location": "Remote", "eligibility": ["Open to any student currently enrolled"],
          "benefits": ["$5,000 in prizes"], "how_to_apply": "Register, then submit a repository",
          "summary": "An online hackathon for first-time contributors."}

JOBS = [
    ("read a page", app.SYS_EXTRACT, "PAGE TEXT:\n" + PAGE, app.EXTRACT_SCHEMA),
    ("screen a post", app.SYS_TRIAGE,
     "PERSON:\n%s\n\nPOST TITLE: Global Hack Week 2027\nPOST TEXT: A hackathon for people who "
     "have never contributed to open source. Prizes total $5,000. Apply by 5 March 2027." % PROFILE,
     app.TRIAGE_SCHEMA),
    ("coach", app.SYS_MATCH,
     "PERSON:\n%s\n\nOPPORTUNITY:\n%s" % (PROFILE, json.dumps(SAMPLE, ensure_ascii=False)),
     app.MATCH_SCHEMA),
]


def ask(model, system, user, schema):
    opts = {"temperature": 0.2, "num_ctx": int(os.environ.get("BENCH_CTX", "8192"))}
    if os.environ.get("NUM_GPU"):
        opts["num_gpu"] = int(os.environ["NUM_GPU"])
    body = {"model": model, "stream": False, "options": opts}
    if schema:
        body["format"] = schema
    body["messages"] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    req = urllib.request.Request(app.OLLAMA_URL + "/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    started = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        out = json.loads(r.read())
    return out, time.time() - started


def gpu_split(model):
    try:
        with urllib.request.urlopen(app.OLLAMA_URL + "/api/ps", timeout=10) as r:
            running = json.loads(r.read()).get("models") or []
    except Exception:
        return "unknown"
    for m in running:
        if m.get("name", "").startswith(model.split(":")[0]):
            vram = (m.get("size_vram") or 0) / 1e9
            return "%s  (%.1f of %.1f GB on device)" % (
                m.get("processor", "?"), vram, (m.get("size") or 0) / 1e9)
    return "not loaded"


if __name__ == "__main__":
    model = os.environ.get("OLLAMA_MODEL", app.MODEL)
    print("model: %s   num_ctx: %s   num_gpu: %s\n" % (
        model, os.environ.get("BENCH_CTX", "8192"), os.environ.get("NUM_GPU", "auto")))
    for name, system, user, schema in JOBS:
        try:
            out, secs = ask(model, system, user, schema)
        except Exception as e:
            print("%-12s FAILED  %s" % (name, e))
            continue
        m = {k: out.get(k) for k in ("eval_count", "eval_duration", "load_duration",
                                     "prompt_eval_count", "prompt_eval_duration")}
        n = m.get("eval_count") or 0
        rate = n / (m.get("eval_duration") / 1e9) if m.get("eval_duration") else 0
        prate = (m.get("prompt_eval_count") or 0) / (m["prompt_eval_duration"] / 1e9) \
            if m.get("prompt_eval_duration") else 0
        print("%-12s %5.1fs  gen %4d tok @ %5.1f/s   read %5d tok @ %5.1f/s" % (
            name, secs, n, rate, m.get("prompt_eval_count") or 0, prate))
        if name == "read a page":
            try:
                fields = json.loads(out["message"]["content"])
                check = app.check_deadline(fields, PAGE)
                print("             deadline %s -> %s (%s)" % (
                    fields.get("deadline_iso"), check["status"], check["note"]))
            except Exception as e:
                print("             unreadable reply: %s" % e)
    print("\non device: %s" % gpu_split(model))
