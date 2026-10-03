#!/usr/bin/env python3
"""HopeHunter: a local-first opportunity finder and application coach.

Zero dependencies. Your profile/CV and all AI work stay on this machine;
the only network traffic is fetching the public opportunity pages you paste in.
"""
import html
import json
import os
import re
import threading
import time
import uuid
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
PORT = int(os.environ.get("PORT", "8000"))
MAX_SCAN = int(os.environ.get("MAX_SCAN", "10"))  # model calls per scan click
PAGE_CHARS = 7000  # how much of one page the model is asked to read
ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data.json"

# RSS/Atom feeds or JSON APIs (see SOURCES.md). Edit these in the app.
# Every one of these is a platform whose job is announcing things a person can enter. Blogs
# about hackathons are not that, and a dev.to tag feed is full of them: it posts writeups of
# work already finished, which is the opposite of an opening.
DEFAULT_SOURCES = [
    "https://opportunitydesk.org/feed/",
    "https://opportunitiesforyouth.org/feed/",
    "https://devpost.com/api/hackathons?status[]=upcoming&order_by=deadline",
    "https://weworkremotely.com/remote-jobs.rss",
    "https://remoteok.com/api",
    # Each of these was checked live on 3 Oct 2026 and returned posts that name a real opening.
    "https://scholarshipscorner.website/feed/",
    "https://opportunitiesfeed.com/feed/",
]


class LLMError(Exception):
    pass


# ---------- storage ----------
# ThreadingHTTPServer runs each request on its own thread, so two requests can hit
# data.json at once. Without these locks, concurrent saves corrupted the file in 40 out
# of 40 tries - and this file holds the user's CV.
#   _STORE guards the file, so a reader never sees a half-written one.
#   _EDIT guards one read-change-write cycle, so two saves can't clobber each other.
# They are separate because a scan holds _EDIT for as long as the model thinks, while the
# page still needs to load during that time.
_STORE = threading.RLock()
_EDIT = threading.Lock()


def load():
    with _STORE:
        raw = DATA_FILE.read_text(encoding="utf-8") if DATA_FILE.exists() else "{}"
    data = json.loads(raw)
    data.setdefault("profile", "")
    data.setdefault("opportunities", [])
    data.setdefault("sources", list(DEFAULT_SOURCES))
    data.setdefault("feed", [])
    data.setdefault("seen", [])
    data.setdefault("last_scan", None)
    return data


def save(data):
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    with _STORE:
        tmp = DATA_FILE.with_name(DATA_FILE.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        # Windows refuses to rename over a file another thread has open, which is why the
        # reader above holds the same lock.
        os.replace(tmp, DATA_FILE)


# ---------- local model ----------
def llm(system, user, schema=None):
    body = {
        "model": MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        # keep_alive: loading a 3.8 GB model costs more than a whole answer, and Ollama
        # drops it after five idle minutes, so two jobs in a row would pay that twice.
        "options": {"temperature": 0.2, "num_ctx": 8192, "keep_alive": "30m"},
    }
    if schema:
        # Handing Ollama the schema makes the shape impossible to get wrong, which asking
        # for it in prose does not.
        body["format"] = schema
    req = urllib.request.Request(
        OLLAMA_URL + "/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            out = json.loads(r.read())["message"]["content"]
    except urllib.error.HTTPError as e:
        # Keep HTTPError ahead of URLError below - it is a subclass, so the generic branch
        # would otherwise swallow the server's own words.
        raise LLMError(server_said(e) or model_hint())
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        # Covers a refused port, a dropped connection, and Ollama answering without a
        # message field. All of them mean the same thing to the user: check Ollama.
        raise LLMError(model_hint())
    if not isinstance(out, str):
        raise LLMError("The model gave no readable answer. Try again.")
    if not schema:
        return out.strip()
    parsed = None
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", out, re.S)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    if parsed is None:
        raise LLMError("The model returned malformed JSON. Try again.")
    # Every JSON job here asks for one object. A small model sometimes answers with an
    # array or a bare string, which would crash the caller with a useless error message.
    if not isinstance(parsed, dict):
        raise LLMError("The model did not answer with the fields I asked for. Try again.")
    return parsed


def server_said(e):
    """Ollama's own words from an error response, or "" when the body isn't readable.

    A missing model and a GPU that refused to run it both answer 500, and only one of
    them is fixed by "ollama pull". The cause sits at the end of these messages, so the
    tail is what gets kept.
    """
    try:
        detail = json.loads(e.read().decode("utf-8", "replace")).get("error", "")
    except Exception:
        return ""
    detail = " ".join(str(detail).split())
    return detail if len(detail) <= 220 else "... " + detail[-220:]


# ---------- what we ask the model to answer with ----------
def field(what=""):
    return {"type": "string", **({"description": what} if what else {})}


def fields_list(what=""):
    return {"type": "array", "items": {"type": "string"},
            **({"description": what} if what else {})}


TYPES = ("job", "internship", "fellowship", "scholarship", "hackathon", "grant", "contest")


def known_type(value):
    # The enum below asks for one of these seven words. A live scan still came back with
    # "Accelerator", "programme" and "essay award", because Ollama treats a schema as
    # best effort. A tag is a claim about the post, so an answer off the list shows no tag.
    word = str(value or "").strip().lower()
    return word if word in TYPES else ""


def oneof(choices):
    return {"type": "string", "enum": list(choices)}


# The container words a small model reaches for when it should be describing the opening. Only
# words that can never name the thing itself belong here: a "programme" or a "program" can be the
# opening, so "Program covers tuition" must survive, while "The feed announces" never can.
_FRAMING = re.compile(
    r"^(?:this\s+|the\s+|a\s+)?(?:blog\s+)?(?:post|page|article|listing|announcement|"
    r"update|entry|item|ad|feed|newsletter|website|site|write[-\s]?up|round[-\s]?up|thread)\s+"
    # "is listing", "has been sharing", "announces" - a copula first, then the reporting verb.
    r"(?:is|are|was|were|has|have|had)?\s*(?:been)?\s*"
    r"(?:announc\w*|share\w*|list\w*|advertis\w*|promot\w*|talk\w* about|is\s+for|covers?|"
    r"points?\s+to|mentions?|describ\w*|highligh\w*|reports?|shows?|contains?|includes?|"
    r"invit\w*)\b"
    r":?\s+",
    re.I)


def unframe_reason(text):
    """A kept line with its leading clause about the feed removed.

    The prompt says not to write "The post announces", and gemma3:4b writes it anyway - four of
    nine keeps in one live scan. Asking a 4B model harder is not a fix; the framing is a fixed,
    recognisable shape at the start of the line, so the app cuts it and capitalises what is left.
    A line that is only framing is returned as it came, because an empty reason is worse than a
    padded one.
    """
    s = str(text or "").strip()
    rest = _FRAMING.sub("", s, count=1)
    if rest == s or not rest:
        return s
    return rest[0].upper() + rest[1:]


def obj(**shape):
    # additionalProperties stays False and every key stays required so a reply can't come
    # back with only the interesting half. "not stated" is an empty string, which the page
    # already treats as nothing to show.
    return {"type": "object", "properties": shape, "required": list(shape),
            "additionalProperties": False}


_HEALTH = {"at": 0.0, "ok": False}
HEALTH_TTL = 10  # seconds


def model_available():
    """Cached model health.

    A refused localhost port costs ~2s per attempt on Windows and urllib tries both
    address families, so an uncached check would add ~4s to every request while Ollama
    is down - which is exactly when the UI is otherwise most responsive.
    """
    now = time.monotonic()
    if now - _HEALTH["at"] < HEALTH_TTL:
        return _HEALTH["ok"]
    _HEALTH.update(at=now, ok=_probe_model())
    return _HEALTH["ok"]


def _probe_model():
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=5) as r:
            payload = json.loads(r.read())
    except Exception:
        return False
    if "models" not in payload:
        return True  # unexpected reply shape; let llm() report the real problem
    names = [str(m.get("name", "")) for m in payload.get("models") or []]
    # Exact name, or a longer tag for the same model (gemma3:4b-it-q4 satisfies a request
    # for gemma3:4b). Matching only the part before the colon would call gemma3:12b a
    # healthy answer for gemma3:4b, and then every request would fail with "model not found".
    return any(n == MODEL or n.startswith(MODEL + "-") for n in names)


def model_hint():
    return (f"Can't reach Ollama at {OLLAMA_URL} or model '{MODEL}' isn't pulled. "
            f"Start Ollama and run: ollama pull {MODEL}")


# ---------- deadline grounding ----------
MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july",
               "august", "september", "october", "november", "december"]

# Whatever a page puts between the parts of a date: "17 Nov 2026", "17-Nov-2026",
# "17th of November, 2026".
_DATE_SEP = r"[\s\-,./]*"

# The words that make a printed date a closing date rather than some other date the page
# happens to print. A page writes "Apply by 5 March", so they sit in the same sentence.
_DEADLINE_WORDS = re.compile(
    r"\b(deadlines?|clos\w*|last date|final date|apply\w*|application\w*|applicants?\w*"
    r"|submi\w*|entries|entry|due|register\w*|registration|ends?|closing)\b", re.I)
_SENTENCE_BREAK = re.compile(r"[.!?;\n]")
_MAX_BEFORE = 120


def sentence_around(text, start, end):
    """The clause a date sits in: bounded by punctuation on both sides."""
    before = 0
    for m in _SENTENCE_BREAK.finditer(text[:start]):
        before = m.end()
    after = len(text)
    for m in _SENTENCE_BREAK.finditer(text, end):
        after = m.start()
        break
    return text[max(before, start - _MAX_BEFORE):after]


def printed_as_deadline(text, iso):
    """True if the page prints this date inside a sentence about applying or closing."""
    for hit in date_pattern(iso).finditer(text):
        if _DEADLINE_WORDS.search(sentence_around(text, hit.start(), hit.end())):
            return True
    return False


def date_pattern(iso, want_year=True):
    """Regex for every unambiguous way a page could print this date.

    Bare numeric forms like 03/11/2026 are left out on purpose: day and month order is
    ambiguous, so matching one could confirm a date the page never meant. The day is
    matched with a digit lookbehind and lookaround so "15 May" can never confirm 5 May.
    """
    d = date.fromisoformat(iso)
    month = f"(?:{MONTH_NAMES[d.month - 1]}|{MONTH_NAMES[d.month - 1][:3]})"
    day = rf"{d.day}(?:st|nd|rd|th)?"
    padded = rf"{d.day:02d}(?:st|nd|rd|th)?"
    forms = [rf"{day}{_DATE_SEP}(?:of{_DATE_SEP})?{month}",
             rf"{padded}{_DATE_SEP}(?:of{_DATE_SEP})?{month}",
             rf"{month}{_DATE_SEP}{day}",
             rf"{month}{_DATE_SEP}{padded}"]
    if want_year:
        forms = [f"{f}{_DATE_SEP},?{_DATE_SEP}{d.year}" for f in forms] + [d.isoformat()]
    return re.compile(r"(?<!\d)(?:%s)(?!\d)" % "|".join(forms), re.I)


def printed_at_all(text, iso):
    return date_pattern(iso).search(text) is not None


# "January 5, 2027", "5 Jan 2027", "17th of November, 2026" - and nothing without a year,
# on purpose. "End of November" is a claim about a month, not a date, and turning it into
# 2026-11-30 would be the app inventing the very thing it is supposed to check.
_WORD_DATE = re.compile(
    r"(?:(?P<day_a>\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<month_a>[a-z]+)"
    r"|(?P<month_b>[a-z]+)\s+(?P<day_b>\d{1,2})(?:st|nd|rd|th)?),?\s+(?P<year>\d{4})(?!\d)",
    re.I)


def date_from_words(text):
    """The ISO date inside a phrase written with month names, or None."""
    m = _WORD_DATE.search(str(text or ""))
    if not m:
        return None
    month = (m.group("month_a") or m.group("month_b")).lower()
    for i, name in enumerate(MONTH_NAMES):
        if month in (name, name[:3]):
            try:
                return date(int(m.group("year")), i + 1,
                            int(m.group("day_a") or m.group("day_b"))).isoformat()
            except ValueError:
                return None  # 31 February is not a date the app should pretend to check
    return None


def check_deadline(fields, source):
    """A model's deadline is only verified when the page prints that date AS a closing date.

    Two things get checked, because a date merely appearing on the page is not enough:
    the words around it have to be about applying or closing (a page that prints its own
    posting date would otherwise confirm the wrong day), and the exact words the model
    says it read have to contain that date. Anything that fails is shown as unconfirmed
    rather than as fact, because a confident wrong date is worse than an absent one.
    """
    shown = str(fields.get("deadline") or "").strip()
    quote = str(fields.get("deadline_quote") or "").strip()
    out = {"iso": None, "shown": shown or None, "quote": quote or None,
           "status": "none", "note": ""}
    raw_iso = str(fields.get("deadline_iso") or "").strip()
    if raw_iso[:4].isdigit() and int(raw_iso[:4]) >= 9000:
        # A model that finds no closing date reaches for a far-future sentinel like
        # 9999-12-31 instead of leaving the field empty. That is a "no", not a date, and
        # echoing the words beside it put "Deadline None" on a card about a real page.
        return {"iso": None, "shown": None, "quote": None, "status": "none", "note": ""}
    try:
        d = date.fromisoformat(raw_iso)
    except ValueError:
        # No usable ISO field, so try the words the model actually wrote. A page that prints
        # "January 5, 2027" under Application Deadlines is checkable whatever field carries it;
        # giving up here reported a verified date as an unchecked one.
        words = date_from_words(shown)
        if not words:
            if shown:
                out["status"] = "unconfirmed"
                out["note"] = "The model gave no clean date to check."
            return out
        d = date.fromisoformat(words)
    iso = d.isoformat()
    out["iso"] = iso
    page = str(source or "")
    if not printed_at_all(page, iso):
        out["status"] = "unconfirmed"
        out["note"] = "That date isn't printed on the page we read."
        return out
    if quote and not date_pattern(iso, want_year=False).search(quote):
        out["status"] = "unconfirmed"
        out["note"] = "The words the model quoted don't actually name that date."
        return out
    if not printed_as_deadline(page, iso):
        out["status"] = "unconfirmed"
        out["note"] = "The page prints that date, but not as a closing date - check it."
        return out
    if d < date.today():
        out["status"] = "past"
        out["note"] = "The page shows it, but it has already passed."
        return out
    out["status"] = "verified"
    return out


# ---------- fetching ----------
def web_url(url):
    """The URL only if it is a web page, otherwise None.

    urllib happily opens file:, ftp: and data:, and this app fetches URLs pasted by a
    person and links found inside feeds. Without this check a link in some feed could make
    the app read a file off the laptop and summarize it. Feeds also carry javascript:
    links that the page puts straight into an href.
    """
    u = str(url or "").strip()
    return u if u.lower().startswith(("http://", "https://")) else None


def _safe(url):
    u = web_url(url)
    if u is None:
        raise ValueError("Only http and https links can be opened.")
    return u


def sample(text):
    """The start and the end of a long page, instead of only its start.

    A deadline or a 'how to apply' line often prints near the bottom, where a head-only
    cut never showed it to the model. The total stays capped, so this costs the same tokens
    and reads one more part of the page.
    """
    text = (text or "").strip()
    if len(text) <= PAGE_CHARS:
        return text
    tail, marker = 2000, "\n... the page continues ...\n"
    return text[:PAGE_CHARS - tail - len(marker)].rstrip() + marker + text[-tail:].strip()


def fetch_text(url):
    req = urllib.request.Request(_safe(url), headers={"User-Agent": "Mozilla/5.0 HopeHunter"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read(600_000).decode("utf-8", "ignore")
    raw = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return sample(re.sub(r"\s+", " ", raw).strip())


def page_text(url):
    """The readable text of one linked page, or a message naming what actually stopped it.

    "Couldn't open that page (login wall?)" used to answer a 404, a typo, a timeout and a
    real login wall alike, which sent a reader to fix the wrong thing. The server's own words
    are the only part of the failure they can act on.
    """
    try:
        return fetch_text(url)
    except Exception as e:
        reason = str(e).strip() or type(e).__name__
        raise ValueError(f"Couldn't open that page ({reason}). "
                         "If it needs a login, paste its text in below instead.")


def fetch_raw(url):
    req = urllib.request.Request(_safe(url), headers={"User-Agent": "Mozilla/5.0 HopeHunter"})
    with urllib.request.urlopen(req, timeout=20) as r:
        # A feed cut off mid-file is not a smaller feed, it is a feed that fails to parse:
        # We Work Remotely's RSS is 2.2 MB, and at 1.5 MB it produced zero jobs forever.
        return r.read(8_000_000).decode("utf-8", "ignore")


def clean(s):
    s = re.sub(r"(?s)<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def json_items(j):
    """Handles bare lists and objects like {"hackathons": [...]} / {"jobs": [...]}."""
    if isinstance(j, dict):
        for k in ("hackathons", "jobs", "hits", "data", "results", "items"):
            if isinstance(j.get(k), list):
                j = j[k]
                break
    if not isinstance(j, list):
        return []
    out = []
    for a in j:
        if not isinstance(a, dict):
            continue
        url = web_url(a.get("url") or a.get("link") or a.get("apply_url"))
        title = a.get("title") or a.get("position") or a.get("name")
        if not (url and title):  # e.g. RemoteOK's leading legal-notice object
            continue
        bits = []
        for k in ("company", "description", "tagline", "prize_amount",
                  "submission_period_dates", "displayed_location", "location",
                  "themes", "tags"):
            v = a.get(k)
            if isinstance(v, list):
                v = ", ".join(str(x.get("name", x)) if isinstance(x, dict) else str(x) for x in v)
            if v:
                bits.append(f"{k}: {v}")
        out.append({"title": clean(str(title)), "url": str(url),
                    "snippet": clean(" | ".join(bits))[:700]})
    return out


def parse_feed(raw):
    """Understands RSS, Atom, and common JSON job/hackathon APIs."""
    try:
        return json_items(json.loads(raw))
    except ValueError:
        pass
    items = []
    root = ET.fromstring(raw)
    for el in root.iter():
        if el.tag.split("}")[-1] not in ("item", "entry"):
            continue
        d = {"title": "", "url": "", "snippet": ""}
        for ch in el:
            t = ch.tag.split("}")[-1]
            if t == "title":
                d["title"] = clean(ch.text)
            elif t == "link":
                d["url"] = (ch.text or "").strip() or ch.get("href", "")
            elif t in ("description", "summary", "content") and not d["snippet"]:
                d["snippet"] = clean(ch.text)[:700]
        d["url"] = web_url(d["url"]) or ""
        if d["url"]:
            items.append(d)
    return items


# ---------- discovery: scan sources, keep real opportunities ----------
SYS_TRIAGE = (
    "You screen one web post at a time. Decide first whether it ANNOUNCES something a reader "
    "can apply to or enter - a job, internship, fellowship, scholarship, hackathon, grant or "
    "contest with prizes - as opposed to a blog post, a tutorial, a writeup of work already "
    "finished, an opinion, or an advertisement for a course. Then use `reason` for one short "
    "plain sentence naming the opening itself and who it is for. Do not write about the post "
    "or the announcement: \"The Loeb Fellowship is fully funded for practitioners in urban "
    "design\", not \"The post announces the Loeb Fellowship\". Use only the words of the "
    "post: never add a date, a prize, a country or a "
    "requirement the post does not print. Reply with JSON only."
)

TRIAGE_SCHEMA = obj(
    is_opportunity={"type": "boolean", "description": "does this announce something to apply to"},
    type=oneof(TYPES),
    reason=field("one sentence under 20 words: the opening and who it is for - name the "
                 "programme, never the words 'this post' or 'the post'"),
)


def triage(item):
    return llm(
        SYS_TRIAGE,
        f"POST TITLE: {item['title']}\nPOST TEXT: {item['snippet']}",
        schema=TRIAGE_SCHEMA,
    )


def decided(value):
    """Turn a model's yes/no answer into True or False, or None when it isn't one.

    Small models often send "true" as text. Comparing with `is True` rejected that and
    quietly skipped every opportunity, which reads as an app that finds nothing. An answer
    we can't read comes back as None so the caller counts it and asks again later.
    """
    if isinstance(value, bool):
        return value
    try:
        parsed = json.loads(str(value).strip().lower())
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, bool) else None


def _items_or_none(raw):
    try:
        return parse_feed(raw)
    except Exception:
        return None  # an HTML page is not XML, and a half-download is not a feed


def _feed_in_page(raw):
    """The feed address a web page advertises in its own <head>, or None."""
    for tag in re.findall(r"<link\b[^>]*>", raw[:80000], re.I):
        t = tag.lower().replace("'", '"')
        if 'rel="alternate"' not in t:
            continue
        if "application/rss+xml" not in t and "application/atom+xml" not in t:
            continue
        href = re.search(r'href="([^"]+)"', t)
        if href:
            return href.group(1)
    return None


# Two conventional paths, not a list of sites: nearly every blogging engine answers one of
# them, and each extra guess costs a fetch on every scan for the pages that answer neither.
FEED_PATHS = ("/feed/", "/rss.xml")


def read_source(src):
    """One line of the feeds box: items, what to tell the reader, and a better address.

    People paste a site's homepage because that is what their browser shows them. A homepage
    is not a feed, so the app follows the feed the page points at, or tries the paths the
    common blogging engines answer, and keeps the one that worked for the next scan.
    """
    try:
        raw = fetch_raw(src)
    except Exception as e:
        # The server's own words, because "down" and "403 Forbidden" are different problems
        # and the reader can only fix one of them.
        return {"items": None, "use": "",
                "note": f"{src} did not answer ({str(e).strip() or type(e).__name__})."}
    items = _items_or_none(raw)
    if items:
        return {"items": items, "use": "", "note": ""}
    base = src.rstrip("/")
    for guess in [_feed_in_page(raw)] + [base + p for p in FEED_PATHS]:
        feed = web_url(urljoin(src, guess) if guess else "")
        if not feed or feed == src:
            continue
        try:
            found = _items_or_none(fetch_raw(feed))
        except Exception:
            found = None
        if found:
            return {"items": found, "use": feed,
                    "note": f"{src} is a web page, not a feed. Now using {feed}."}
    return {"items": None, "use": "",
            "note": (f"{src} is a web page with no feed on it, so there is nothing here to "
                     'scan. Add the site\'s feed or API link, or paste one opening into '
                     '"Add one yourself".')}


def scan(data):
    seen = set(data["seen"])
    queue, queued, errors = [], set(), []
    # Every wait in this part is a network fetch, not thinking, so they run together.
    with ThreadPoolExecutor(max_workers=4) as pool:
        fetched = list(pool.map(read_source, data["sources"]))
    switched = {src: res["use"] for src, res in zip(data["sources"], fetched) if res["use"]}
    if switched:
        data["sources"] = [switched.get(s, s) for s in data["sources"]]
    buckets = []
    for src, res in zip(data["sources"], fetched):
        if res["note"]:
            errors.append(res["note"])
        bucket = []
        for it in res["items"] or []:
            if it["url"] not in seen and it["url"] not in queued:
                queued.add(it["url"])
                # Which feed printed this. A card with no source on it is a claim, and with
                # eleven feeds the reader cannot tell a platform they chose from a site the
                # app wandered into.
                it["source"] = src
                bucket.append(it)
        buckets.append(bucket)
    # One post per feed in turn, not one feed after another. A scan of ten posts across eleven
    # feeds otherwise reads ten from whichever source happens to be first and never asks the
    # others a question, so adding a site changes nothing the reader can see.
    for turn in range(max((len(b) for b in buckets), default=0)):
        for bucket in buckets:
            if turn < len(bucket):
                queue.append(bucket[turn])
    added = skipped = failed = 0
    for it in queue[:MAX_SCAN]:
        try:
            t = triage(it)
        except LLMError as e:
            # Keep the model's own reason: "run ollama pull gemma3:4b" is a fix, "the scan
            # paused" is not.
            errors.append(f"The scan paused partway through: {e} Scan again to resume.")
            break  # leave this item unseen so the next scan retries it
        except Exception:
            failed += 1
            continue
        verdict = decided(t.get("is_opportunity"))
        if verdict is None:
            failed += 1
            continue  # left out of seen, so the next scan asks about it again
        seen.add(it["url"])
        if verdict:
            data["feed"].append({"url": it["url"], "title": it["title"],
                                 "type": known_type(t.get("type")),
                                 "reason": unframe_reason(t.get("reason") or ""),
                                 "source": it.get("source") or ""})
            added += 1
        else:
            skipped += 1
    data["feed"] = data["feed"][:100]
    data["seen"] = list(seen)[-3000:]
    data["last_scan"] = {"added": added, "skipped": skipped, "failed": failed,
                         "waiting": max(0, len(queue) - MAX_SCAN), "errors": errors}


# ---------- the three AI jobs ----------
SYS_EXTRACT = (
    "You extract facts about an opportunity (job, internship, fellowship, scholarship, "
    "hackathon, grant) from web page text. Use ONLY what the text says. If something is "
    "not stated, leave its field empty. Never guess dates. Be terse: a few words per field, "
    "no full sentences, nothing repeated. Reply with JSON only."
)

EXTRACT_SCHEMA = obj(
    title=field("what the opportunity is called"),
    organization=field("who runs it"),
    type=oneof(TYPES),
    deadline=field("the closing date exactly as the page words it"),
    deadline_iso=field("the closing date as YYYY-MM-DD, only if the page states it"),
    deadline_quote=field("the exact words on the page that the closing date came from"),
    location=field("city and country, or Remote"),
    eligibility=fields_list("who may apply, at most 3 short points"),
    benefits=fields_list("what the person gets, at most 3 short points"),
    how_to_apply=field("where and how to apply, a few words"),
    summary=field("what this is, at most 15 words"),
)


def extract(text):
    return llm(SYS_EXTRACT, f"PAGE TEXT:\n{text}", schema=EXTRACT_SCHEMA)


SYS_MATCH = (
    "You are a kind but honest career coach for a person who may feel discouraged. "
    "Compare their background with the opportunity. Do not invent facts about them. "
    "Each point is one short plain sentence with no heading, no bold and no asterisks, "
    "because the page shows these words exactly as you write them. Be specific and "
    "constructive about gaps. Reply with JSON only."
)

MATCH_SCHEMA = obj(
    why=fields_list("what already fits, at most 3 points of under 12 words each, naming "
                    "something in their background"),
    gaps=fields_list("what is missing, at most 3 points of under 12 words each, without "
                     "discouraging them"),
    next_steps=fields_list("what to do next, at most 3 points of under 12 words each"),
)


def match(profile, opportunity):
    m = llm(
        SYS_MATCH,
        f"PERSON:\n{profile}\n\nOPPORTUNITY:\n{json.dumps(opportunity, ensure_ascii=False)}",
        schema=MATCH_SCHEMA,
    )
    # "At most 3" sits in the description, and the description is a request. Asked that way the
    # model answered "why you fit" with nine sentences, which is a wall to scroll, not advice.
    for key in ("why", "gaps", "next_steps"):
        m[key] = m[key][:3]
    return m


SYS_DRAFT = (
    "Write a short, warm, honest application message (150-200 words) in first person "
    "for the person below, tailored to the opportunity. Use ONLY facts from their "
    "profile; never invent achievements, grades, or experience. No clichés, no "
    "flattery. Plain text only."
)


def draft(profile, fields):
    return llm(
        SYS_DRAFT,
        f"PERSON:\n{profile}\n\nOPPORTUNITY:\n{json.dumps(fields, ensure_ascii=False)}",
    )


# ---------- http ----------
def view(data):
    out = {k: v for k, v in data.items() if k != "seen"}
    out["model"] = MODEL
    out["model_ok"] = model_available()
    return out

def find(data, oid):
    for o in data["opportunities"]:
        if o["id"] == oid:
            return o
    raise ValueError("Opportunity not found")


NEEDS_MODEL = {"/api/scan", "/api/add", "/api/track", "/api/match", "/api/draft"}


class Handler(BaseHTTPRequestHandler):
    # The app answers only requests addressed to localhost. Without this, a page the
    # person visits could point its own domain at 127.0.0.1 (DNS rebinding) and read
    # /api/state, which is their whole CV. The browser sends the address it typed in the
    # Host header, so a rebinding request arrives with a foreign one and gets refused.
    LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")

    def _foreign_host(self):
        raw = (self.headers.get("Host") or "").strip().lower()
        name = raw[1:].split("]")[0] if raw.startswith("[") else raw.split(":")[0]
        # Empty is allowed: HTTP/1.0 clients and tests send no Host at all.
        return bool(name) and name not in self.LOCAL_HOSTS

    def _send(self, code, payload, ctype="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self._foreign_host():
            return self._send(403, {"error": "This app only answers localhost."})
        # A query string is not part of the route: "/" and "/?x=1" are the same page.
        path = self.path.split("?", 1)[0]
        try:
            if path in ("/", "/index.html"):
                self._send(200, (ROOT / "index.html").read_bytes(), "text/html")
            elif path == "/api/state":
                self._send(200, view(load()))
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            # An unhandled error here kills the connection, and the page just shows
            # nothing with no reason. Say what broke so it can be fixed.
            self._send(500, {"error": f"Can't read your saved data: {e}"})

    def do_POST(self):
        if self._foreign_host():
            return self._send(403, {"error": "This app only answers localhost."})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            # One request reads the file, changes it, and writes it back. The lock spans
            # that whole cycle so two overlapping requests can't clobber each other's edit.
            with _EDIT:
                self._handle(body)
        except LLMError as e:
            self._send(503, {"error": str(e)})
        except Exception as e:
            self._send(400, {"error": str(e)})

    def _handle(self, body):
        if not isinstance(body, dict):
            raise ValueError("The app sent a request this endpoint can't read.")
        data = load()
        if self.path in NEEDS_MODEL and not model_available():
            raise LLMError(model_hint())
        if self.path == "/api/profile":
            data["profile"] = body.get("profile", "")
        elif self.path in ("/api/add", "/api/track"):
            url = (body.get("url") or "").strip()
            text = (body.get("text") or "").strip()
            if not text:
                if not url:
                    raise ValueError("Paste a link or the page text.")
                text = page_text(url)
            text = sample(text)
            fields = extract(text)
            fields["type"] = known_type(fields.get("type"))
            fields["summary"] = unframe_reason(fields.get("summary") or "")
            fields["deadline_check"] = check_deadline(fields, text)
            data["opportunities"].insert(
                0, {"id": uuid.uuid4().hex[:8], "url": url, "fields": fields,
                    "match": None, "draft": None}
            )
            data["feed"] = [x for x in data["feed"] if x["url"] != url]
        elif self.path == "/api/sources":
            lines = [s.strip() for s in (body.get("sources") or "").splitlines()]
            data["sources"] = [s for s in lines if s.startswith("http")]
        elif self.path == "/api/scan":
            scan(data)
        elif self.path == "/api/dismiss":
            data["feed"] = [x for x in data["feed"] if x["url"] != body.get("url")]
        elif self.path == "/api/match":
            o = find(data, body["id"])
            if not data["profile"].strip():
                raise ValueError("Write your background first.")
            o["match"] = match(data["profile"], o["fields"])
        elif self.path == "/api/draft":
            o = find(data, body["id"])
            if not data["profile"].strip():
                raise ValueError("Write your background first.")
            o["draft"] = draft(data["profile"], o["fields"])
        elif self.path == "/api/delete":
            data["opportunities"] = [x for x in data["opportunities"] if x["id"] != body["id"]]
        else:
            return self._send(404, {"error": "not found"})
        save(data)
        self._send(200, view(data))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    # Bound to localhost only: nothing here is reachable from other machines.
    print(f"HopeHunter on http://127.0.0.1:{PORT}  (model: {MODEL})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
