import io
import json
import urllib.error
from datetime import date, timedelta

import pytest

import app


def _d(days):
    return date.today() + timedelta(days=days)


# ---------- deadline grounding ----------

def test_deadline_verified_when_page_prints_iso():
    iso = _d(90).isoformat()
    out = app.check_deadline({"deadline": "Close " + iso, "deadline_iso": iso},
                             f"Apply now. Deadline {iso}.")
    assert out["status"] == "verified"
    assert out["iso"] == iso


@pytest.mark.parametrize("rendering", [
    lambda d: f"{d.day} {d:%B} {d.year}",
    lambda d: f"{d:%B} {d.day}, {d.year}",
    lambda d: f"{d:%b} {d.day}, {d.year}",
    lambda d: f"{d.day:02d} {d:%b} {d.year}",
])
def test_deadline_verified_for_spelled_out_dates(rendering):
    d = _d(45)
    out = app.check_deadline({"deadline_iso": d.isoformat()}, "Closes " + rendering(d) + ".")
    assert out["status"] == "verified"


def test_invented_date_is_not_verified():
    out = app.check_deadline({"deadline_iso": _d(90).isoformat()},
                             "Applications are open. No closing date given.")
    assert out["status"] == "unconfirmed"
    assert "isn't printed" in out["note"]


def test_ambiguous_numeric_date_is_never_trusted():
    d = _d(45)
    out = app.check_deadline({"deadline_iso": d.isoformat()}, f"Apply by {d.day}/{d.month}/{d.year}.")
    assert out["status"] == "unconfirmed"


def test_day_prefixed_by_another_digit_does_not_verify():
    # "15 May 2026" contains "5 May 2026" as a substring; it must not confirm the 5th.
    out = app.check_deadline({"deadline_iso": "2026-05-05"}, "Applications closed 15 May 2026.")
    assert out["status"] == "unconfirmed"


def test_padded_day_does_not_verify_a_bare_one():
    out = app.check_deadline({"deadline_iso": "2026-03-05"}, "Closes 25 March 2026.")
    assert out["status"] == "unconfirmed"


def test_a_printed_past_date_is_reported_as_closed():
    assert app.check_deadline({"deadline_iso": "2026-05-15"},
                              "Closed 15 May 2026.")["status"] == "past"


def test_past_date_is_flagged_even_when_the_page_shows_it():
    out = app.check_deadline({"deadline_iso": "2020-01-15"}, "Closed on 15 January 2020.")
    assert out["status"] == "past"


def test_free_text_date_without_iso_is_reported_unconfirmed():
    out = app.check_deadline({"deadline": "End of November"}, "Deadline: End of November")
    assert out["status"] == "unconfirmed"
    assert out["shown"] == "End of November"


def test_missing_deadline_stays_missing():
    out = app.check_deadline({}, "Just a description, no dates.")
    assert out == {"iso": None, "shown": None, "quote": None,
                   "status": "none", "note": ""}


def test_impossible_iso_does_not_crash():
    out = app.check_deadline({"deadline": "sometime in 2027", "deadline_iso": "2027-13-45"}, "x")
    assert out["status"] == "unconfirmed"


def test_a_deadline_that_is_not_a_date_is_not_echoed():
    # The AI Studio page has no closing date, so the model wrote the word "None" in the
    # deadline field and 9999-12-31 in the one meant for a date. The card read "Deadline
    # None - The model gave no clean date to check": the model shrugging, dressed up as a
    # deadline a reader might miss. A far-future sentinel is a "no", so it shows no date.
    out = app.check_deadline({"deadline": "None", "deadline_iso": "9999-12-31T23:59:59Z",
                              "deadline_quote": "There's no deadline!"}, "x")
    assert out == {"iso": None, "shown": None, "quote": None, "status": "none", "note": ""}
    # Wording that really does claim a date still belongs on the card, flagged as unchecked.
    kept = app.check_deadline({"deadline": "End of November"}, "Deadline: End of November")
    assert kept["status"] == "unconfirmed" and kept["shown"] == "End of November"


def test_a_date_the_page_prints_in_words_is_still_checked():
    # I pasted a real fellowship link and the model answered "January 5, 2027" with the ISO
    # field left empty. The check gave up with "the model gave no clean date to check" - about
    # a date the page prints in those exact words, under a heading that says Application
    # Deadlines. A date in words is checkable, so the missing ISO stopped an excuse, not a lie.
    page = "Application Deadlines   January 5, 2027   5:00 p.m ET   MArch, MLA, MUP, MAU"
    out = app.check_deadline({"deadline": "January 5, 2027", "deadline_iso": "",
                              "deadline_quote": "January 5, 2027 5:00 p.m ET"}, page)
    assert out["status"] == "verified" and out["iso"] == "2027-01-05"
    # And the same words with no year, or a year the page never prints, stay unconfirmed:
    # without a year there is nothing to compare, and a date only the model knows about is
    # exactly the invention this check exists to catch.
    vague = app.check_deadline({"deadline": "Early January"}, page)
    assert vague["status"] == "unconfirmed"
    absent = app.check_deadline({"deadline": "March 3, 2027", "deadline_iso": ""}, page)
    assert absent["status"] == "unconfirmed" and "isn't printed" in absent["note"]


# ---------- feed parsing ----------

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>F</title>
<item><title>  Scholarship &amp; Grant drive </title><link>https://e.com/a</link>
<description>Apply by 5 March 2027. &lt;b&gt;bold&lt;/b&gt;</description></item>
<item><title>No link here</title></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Remote internship</title><link href="https://e.com/b"/><summary>One line</summary></entry>
</feed>"""


def test_rss_decodes_entities_and_drops_linkless_items():
    items = app.parse_feed(RSS)
    assert len(items) == 1
    assert items[0]["title"] == "Scholarship & Grant drive"
    assert items[0]["url"] == "https://e.com/a"
    assert "<b>" not in items[0]["snippet"]


def test_atom_uses_href_and_summary():
    assert app.parse_feed(ATOM) == [
        {"title": "Remote internship", "url": "https://e.com/b", "snippet": "One line"}]


def test_devpost_json_envelope():
    raw = json.dumps({"hackathons": [{"title": "Global Sprint", "url": "https://devpost.com/h",
                                     "prize_amount": "$5000", "themes": [{"name": "AI"}]}]})
    items = app.parse_feed(raw)
    assert items[0]["title"] == "Global Sprint"
    assert "prize_amount: $5000" in items[0]["snippet"]
    assert "AI" in items[0]["snippet"]


def test_remoteok_skips_its_leading_legal_object():
    raw = json.dumps([{"company": "RemoteOK", "name": "terms"},
                      {"position": "Junior Dev", "url": "https://r.co/j1", "company": "Acme"}])
    items = app.parse_feed(raw)
    assert len(items) == 1
    assert items[0]["title"] == "Junior Dev"
    assert "company: Acme" in items[0]["snippet"]


def test_json_items_need_both_url_and_title():
    out = app.json_items([{"title": "no url"}, {"url": "https://x"},
                          {"title": "t", "url": "https://u"}])
    assert len(out) == 1


def test_feed_links_that_are_not_web_pages_are_dropped():
    # An item's url goes straight into an href, so javascript: and file: must not survive
    # parsing at all.
    out = app.json_items([
        {"title": "ok", "url": "https://real.example/job"},
        {"title": "bad", "url": "javascript:fetch('/api/state')"},
        {"title": "bad", "url": "file:///C:/Users/you/secret.txt"},
        {"title": "bad", "url": "data:text/html,<script>alert(1)</script>"},
    ])
    assert [x["url"] for x in out] == ["https://real.example/job"]


def test_atom_links_are_filtered_the_same_way():
    raw = ("<feed><entry><title>t</title>"
           "<link href='javascript:alert(1)'/>"
           "<summary>s</summary></entry>"
           "<entry><title>ok</title><link href='https://e.example/p'/>"
           "<summary>s</summary></entry></feed>")
    assert [i["url"] for i in app.parse_feed(raw)] == ["https://e.example/p"]


@pytest.mark.parametrize("url", [
    "file:///C:/Windows/win.ini", "ftp://example/x", "javascript:alert(1)",
    "data:text/plain,hi", "C:/Users/you/cv.txt", "", None,
])
def test_only_http_can_be_fetched(url):
    with pytest.raises(ValueError, match="http and https"):
        app.fetch_text(url)
    with pytest.raises(ValueError, match="http and https"):
        app.fetch_raw(url)


def test_web_url_passes_real_pages_and_refuses_the_rest():
    assert app.web_url("HTTPS://Example.com/a") == "HTTPS://Example.com/a"
    assert app.web_url("  https://a ") == "https://a"
    assert app.web_url("file:///a") is None
    assert app.web_url("httpx://a") is None


# ---------- scan resilience ----------

def _data(**kw):
    d = {"profile": "p", "sources": ["https://f1"], "feed": [], "seen": [],
         "opportunities": [], "last_scan": None}
    d.update(kw)
    return d


def _items(*urls):
    return [{"title": "t", "url": u, "snippet": "s"} for u in urls]


def test_scan_survives_one_unusable_reply(monkeypatch):
    monkeypatch.setattr(app, "fetch_raw", lambda url: "raw")
    monkeypatch.setattr(app, "parse_feed", lambda raw: _items("u1", "u2", "u3"))

    def triage(item):
        if item["url"] == "u2":
            raise ValueError("bad json")
        return {"is_opportunity": True, "type": "job", "score": 80, "reason": "fits"}

    monkeypatch.setattr(app, "triage", triage)
    d = _data()
    app.scan(d)
    assert d["last_scan"]["failed"] == 1
    assert d["last_scan"]["added"] == 2
    assert [x["url"] for x in d["feed"]] == ["u1", "u3"]
    assert "u2" not in d["seen"], "u2 must be retried on the next scan"


def test_scan_pauses_on_dead_model_without_losing_the_run(monkeypatch):
    monkeypatch.setattr(app, "fetch_raw", lambda url: "raw")
    monkeypatch.setattr(app, "parse_feed", lambda raw: _items("u1", "u2"))
    called = []

    def triage(item):
        called.append(item["url"])
        raise app.LLMError("no ollama")

    monkeypatch.setattr(app, "triage", triage)
    d = _data()
    app.scan(d)
    assert called == ["u1"], "should stop rather than retry every item"
    assert d["seen"] == []
    assert any("paused" in e for e in d["last_scan"]["errors"])


def test_scan_reports_unreadable_sources(monkeypatch):
    def boom(url):
        raise OSError("down")
    monkeypatch.setattr(app, "fetch_raw", boom)
    d = _data()
    app.scan(d)
    e = d["last_scan"]["errors"][0]
    assert "https://f1" in e and "did not answer" in e


PAGE_WITH_FEED = """<!doctype html><html><head><title>Blog</title>
<link rel="alternate" type="application/rss+xml" title="Feed" href="/feed/" />
</head><body><h1>Latest openings</h1></body></html>"""

PAGE_WITHOUT_FEED = "<!doctype html><html><body><h1>Just a homepage</h1></body></html>"


def test_a_web_page_is_read_through_the_feed_it_advertises(monkeypatch):
    # Homepages were pasted into the sources box - github.com, devfolio.co, unstop.com - and
    # the app answered "Couldn't read" about pages that answered perfectly. A page that links
    # to its own feed has one, so follow the link instead of blaming the network.
    def fetch(url):
        return PAGE_WITH_FEED if url == "https://blog.example" else ATOM
    monkeypatch.setattr(app, "fetch_raw", fetch)
    monkeypatch.setattr(app, "triage", lambda it: {"is_opportunity": True, "type": "job",
                                                   "reason": "r"})
    d = _data()
    d["sources"] = ["https://blog.example"]
    app.scan(d)
    assert [x["url"] for x in d["feed"]] == ["https://e.com/b"]
    # The next scan should not have to discover it again.
    assert d["sources"] == ["https://blog.example/feed/"]
    assert any("feed" in e.lower() for e in d["last_scan"]["errors"])


def test_the_usual_feed_path_is_tried_when_a_page_links_to_none(monkeypatch):
    # Most opportunity blogs run on WordPress, which puts its feed at /feed/ without always
    # advertising the link tag. Two conventional paths cover that without naming any site.
    def fetch(url):
        return ATOM if url == "https://blog.example/feed/" else PAGE_WITHOUT_FEED
    monkeypatch.setattr(app, "fetch_raw", fetch)
    monkeypatch.setattr(app, "triage", lambda it: {"is_opportunity": True, "type": "job",
                                                   "reason": "r"})
    d = _data()
    d["sources"] = ["https://blog.example"]
    app.scan(d)
    assert [x["url"] for x in d["feed"]] == ["https://e.com/b"]
    assert d["sources"] == ["https://blog.example/feed/"]


def test_a_page_with_no_feed_says_what_to_do_about_it(monkeypatch):
    # "Couldn't read https://github.com" sent a reader to check their internet. The truth is
    # that the page has no feed at all, and the fix is a different link or the other card.
    monkeypatch.setattr(app, "fetch_raw", lambda url: PAGE_WITHOUT_FEED)
    d = _data()
    d["sources"] = ["https://github.com"]
    app.scan(d)
    e = d["last_scan"]["errors"][0]
    assert "https://github.com" in e and "no feed" in e
    assert "Add one yourself" in e
    assert "did not answer" not in e


def test_scan_defers_the_overflow_and_says_so(monkeypatch):
    monkeypatch.setattr(app, "fetch_raw", lambda url: "raw")
    monkeypatch.setattr(app, "parse_feed", lambda raw: _items(*[f"u{i}" for i in range(5)]))
    monkeypatch.setattr(app, "MAX_SCAN", 2)
    monkeypatch.setattr(app, "triage", lambda it: {"is_opportunity": False})
    d = _data()
    app.scan(d)
    assert d["last_scan"]["waiting"] == 3


def test_one_scan_reaches_every_feed_not_just_the_first(monkeypatch):
    # Eleven feeds and a ten-post scan: built in source order the scan read ten posts from
    # whichever feed happened to be first and never asked the other ten anything. So a reader
    # who adds a site sees no difference from before they added it. The scan now spends itself
    # one post per feed, which is what "check my feeds" is supposed to mean.
    feeds = {
        "https://f1": _items(*[f"a{i}" for i in range(6)]),
        "https://f2": _items(*[f"b{i}" for i in range(6)]),
        "https://f3": _items(*[f"c{i}" for i in range(6)]),
    }
    monkeypatch.setattr(app, "fetch_raw", lambda url: url)
    monkeypatch.setattr(app, "parse_feed", lambda raw: feeds[raw])
    monkeypatch.setattr(app, "MAX_SCAN", 6)
    asked = []

    def triage(item):
        asked.append(item["url"])
        return {"is_opportunity": False}

    monkeypatch.setattr(app, "triage", triage)
    d = _data(sources=list(feeds))
    app.scan(d)
    assert asked == ["a0", "b0", "c0", "a1", "b1", "c1"]


def test_a_link_that_will_not_open_says_why(monkeypatch):
    # https://www.who.int/internships answers 404 - the page moved - and the app answered
    # "Couldn't open that page (login wall?)". One guess for every failure sends a reader to
    # fix the wrong thing, so the server's own words go into the message and login becomes
    # what the reader can try next rather than a claim about what happened.
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    monkeypatch.setattr(app, "fetch_text", boom)
    try:
        app.page_text("https://www.who.int/internships")
        raise AssertionError("should refuse the page")
    except ValueError as e:
        msg = str(e)
    assert "404" in msg and "login" in msg.lower() and "paste" in msg.lower()


def test_a_found_opening_says_which_feed_it_came_from(monkeypatch):
    # With eleven feeds on the page a card that shows only a title and one line is a claim
    # with no source behind it, and the reader cannot tell a platform they picked from a site
    # the app wandered into. Every kept item carries the feed that printed it.
    feeds = {"https://desk.example/feed/": _items("u1"),
             "https://blog.example/feed/": _items("u2")}
    monkeypatch.setattr(app, "fetch_raw", lambda url: url)
    monkeypatch.setattr(app, "parse_feed", lambda raw: feeds[raw])
    monkeypatch.setattr(app, "triage", lambda it: {"is_opportunity": True,
                                                   "type": "job", "reason": "r"})
    d = _data(sources=list(feeds))
    app.scan(d)
    assert [x["source"] for x in d["feed"]] == ["https://desk.example/feed/",
                                                "https://blog.example/feed/"]


def test_scan_skips_urls_it_has_already_judged(monkeypatch):
    monkeypatch.setattr(app, "fetch_raw", lambda url: "raw")
    monkeypatch.setattr(app, "parse_feed", lambda raw: _items("u1", "u2"))
    judged = []

    def triage(item):
        judged.append(item["url"])
        return {"is_opportunity": False}

    monkeypatch.setattr(app, "triage", triage)
    app.scan(_data(seen=["u1"]))
    assert judged == ["u2"]


def test_no_job_is_asked_for_a_fit_number(monkeypatch):
    # Asked the same hackathon post twice, with a background that fits it perfectly and one
    # that fits not at all, gemma3:4b answered 1/100 both times and the coach answered 0/100
    # both times. A number that does not move ranks nothing and only discourages, so no job
    # is asked for one anywhere.
    holder = _sent(monkeypatch)
    app.triage({"title": "t", "url": "u", "snippet": "s"})
    assert "score" not in holder["req"].body["format"]["properties"]
    assert "score" not in app.MATCH_SCHEMA["properties"]


def test_scan_keeps_the_reason_and_stores_no_number(monkeypatch):
    monkeypatch.setattr(app, "fetch_raw", lambda url: "raw")
    monkeypatch.setattr(app, "parse_feed", lambda raw: _items("u1"))
    monkeypatch.setattr(app, "triage", lambda it: {"is_opportunity": True, "type": "job",
                                                     "reason": "remote, and for students"})
    d = _data()
    app.scan(d)
    assert d["feed"][0]["reason"] == "remote, and for students"
    assert "score" not in d["feed"][0]


# ---------- replies we can't use ----------

class _Resp:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _reply(monkeypatch, payload):
    monkeypatch.setattr(app.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))


PAGE_FIELDS = {"title", "organization", "type", "deadline", "deadline_iso", "deadline_quote",
               "location", "eligibility", "benefits", "how_to_apply", "summary"}


class _Captured:
    """The request body llm() builds, so a test can read what the model was told."""

    def __init__(self, req, reply):
        self.body = json.loads(req.data)
        self._raw = json.dumps({"message": {"content": json.dumps(reply)}}).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _sent(monkeypatch, reply=None):
    out = {}

    def open_(req, *a, **k):
        out["req"] = _Captured(req, reply if reply is not None else {"ok": True})
        return out["req"]

    monkeypatch.setattr(app.urllib.request, "urlopen", open_)
    return out


def test_the_model_is_held_to_a_schema_not_asked_politely(monkeypatch):
    # gemma3:4b was asked, in prose, for "title" and answered with "name" and a nested
    # "deadline" object. The card then rendered with no title and no date, and nothing
    # looked wrong. Ollama can enforce a schema, so the shape stops being a request.
    holder = _sent(monkeypatch)
    app.extract("PAGE TEXT: whatever")
    fmt = holder["req"].body.get("format")
    assert isinstance(fmt, dict), "format must be a JSON schema, not the word 'json'"
    assert set(fmt.get("properties") or {}) == PAGE_FIELDS
    assert set(fmt.get("required") or {}) == PAGE_FIELDS
    assert fmt.get("additionalProperties") is False


def test_the_two_date_fields_ask_for_the_pages_own_words(monkeypatch):
    holder = _sent(monkeypatch)
    app.extract("PAGE TEXT: whatever")
    props = holder["req"].body["format"]["properties"]
    assert "YYYY-MM-DD" in props["deadline_iso"]["description"]
    assert "exact" in props["deadline_quote"]["description"].lower()


def test_plain_text_jobs_send_no_schema(monkeypatch):
    holder = _sent(monkeypatch, reply={"unused": 1})
    app.draft("profile text", {"title": "x"})
    assert "format" not in holder["req"].body


def test_model_reply_without_a_message_becomes_a_model_error(monkeypatch):
    # Ollama answers this way when the model isn't pulled. A raw KeyError would reach the
    # user as "message", which tells them nothing about what to fix.
    _reply(monkeypatch, {"error": "model not found"})
    with pytest.raises(app.LLMError):
        app.llm("sys", "user", schema=app.EXTRACT_SCHEMA)


def test_the_servers_own_words_reach_the_user(monkeypatch):
    # Real machine, real failure: the model was pulled and Ollama answered, but its GPU
    # run died on a driver mismatch. "run ollama pull gemma3:4b" sends a person in circles.
    def boom(*a, **k):
        body = io.BytesIO(json.dumps({"error": "CUDA error: unsupported toolchain"}).encode())
        raise urllib.error.HTTPError("http://x/api/chat", 500, "Internal Server Error", {}, body)

    monkeypatch.setattr(app.urllib.request, "urlopen", boom)
    with pytest.raises(app.LLMError) as e:
        app.llm("sys", "user")
    assert "unsupported toolchain" in str(e.value)


def test_a_server_error_with_no_readable_body_still_gets_the_hint(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.HTTPError("http://x/api/chat", 502, "Bad Gateway", {}, None)

    monkeypatch.setattr(app.urllib.request, "urlopen", boom)
    with pytest.raises(app.LLMError) as e:
        app.llm("sys", "user")
    assert "Ollama" in str(e.value)


def test_model_answer_of_the_wrong_shape_becomes_a_model_error(monkeypatch):
    _reply(monkeypatch, {"message": {"content": '["not", "an", "object"]'}})
    with pytest.raises(app.LLMError):
        app.extract("PAGE TEXT: whatever")


def test_check_deadline_never_sees_a_non_dict(monkeypatch):
    # The crash used to happen here, after extract() had already returned a list.
    _reply(monkeypatch, {"message": {"content": '"just a string"'}})
    with pytest.raises(app.LLMError):
        app.llm("sys", "user", schema=app.EXTRACT_SCHEMA)


def test_plain_text_reply_is_still_returned_as_text(monkeypatch):
    _reply(monkeypatch, {"message": {"content": "  a draft  "}})
    assert app.llm("sys", "user") == "a draft"


# ---------- storage ----------

@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "data.json"
    monkeypatch.setattr(app, "DATA_FILE", path)
    return path


def test_concurrent_saves_always_leave_a_readable_file(store):
    import threading

    payloads = [{"profile": f"person {i}", "opportunities": [], "sources": [],
                 "feed": [], "seen": [], "last_scan": None} for i in range(60)]
    read_ok = []

    def reader():
        for _ in range(40):
            try:
                read_ok.append(app.load()["profile"])
            except json.JSONDecodeError:
                read_ok.append("TORN")

    threads = [threading.Thread(target=app.save, args=(p,)) for p in payloads]
    threads += [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert "TORN" not in read_ok, "a read landed mid-write and got a partial file"
    assert set(read_ok) <= {p["profile"] for p in payloads} | {""}, "a read saw two saves mixed"
    final = json.loads(store.read_text(encoding="utf-8"))
    assert final in payloads, "the file is a mixture of two saves"


def test_save_leaves_no_temp_file(store):
    app.save({"profile": "p"})
    assert list(store.parent.iterdir()) == [store]


def test_load_gives_defaults_when_no_file_exists(store):
    d = app.load()
    assert d["profile"] == ""
    assert d["sources"] == app.DEFAULT_SOURCES


# ---------- health probe ----------
# Ollama running with nothing pulled is the most common first-run state, and it reads as
# "model not found" everywhere unless the app names the fix.

def _tags(monkeypatch, payload):
    monkeypatch.setattr(app.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))


def test_probe_fails_when_the_model_is_not_pulled(monkeypatch):
    _tags(monkeypatch, {"models": [{"name": "llama3:latest"}, {"name": "nomic-embed-text"}]})
    assert app._probe_model() is False


def test_probe_passes_on_the_exact_model(monkeypatch):
    _tags(monkeypatch, {"models": [{"name": "gemma3:4b"}]})
    assert app._probe_model() is True


def test_probe_accepts_a_tagged_variant_of_the_same_model(monkeypatch):
    # Asking for gemma3:4b and finding gemma3:4b-it-q4 is the same model to the user.
    monkeypatch.setattr(app, "MODEL", "gemma3:4b")
    _tags(monkeypatch, {"models": [{"name": "gemma3:4b-it-q4"}]})
    assert app._probe_model() is True


def test_probe_fails_when_ollama_is_down(monkeypatch):
    def boom(*a, **k):
        raise app.urllib.error.URLError("refused")
    monkeypatch.setattr(app.urllib.request, "urlopen", boom)
    assert app._probe_model() is False


def test_unexpected_reply_shape_is_not_called_healthy(monkeypatch):
    _tags(monkeypatch, {"whoops": True})
    assert app._probe_model() is True  # let llm() report the real problem, don't guess


def test_hint_names_the_command_that_fixes_it(monkeypatch):
    monkeypatch.setattr(app, "MODEL", "gemma3:4b")
    monkeypatch.setattr(app, "OLLAMA_URL", "http://localhost:11434")
    hint = app.model_hint()
    assert "ollama pull gemma3:4b" in hint
    assert "localhost:11434" in hint


def test_health_cache_expires_and_rechecks(monkeypatch):
    calls = []

    def fake_probe():
        calls.append(1)
        return len(calls) > 1  # first answer is unhealthy, then it recovers
    monkeypatch.setattr(app, "_probe_model", fake_probe)
    monkeypatch.setattr(app, "_HEALTH", {"at": 0.0, "ok": False})
    assert app.model_available() is False
    assert app.model_available() is False  # served from cache, no new probe
    assert len(calls) == 1
    monkeypatch.setattr(app, "_HEALTH", {"at": 0.0, "ok": False})  # pretend TTL elapsed
    assert app.model_available() is True
    assert len(calls) == 2


# ---------- a yes/no answer we can actually read ----------

@pytest.mark.parametrize("value,want", [
    (True, True), (False, False),
    ("true", True), ("True", True), ("  false ", False),
    ("yes", None), ("maybe", None), ("", None), (None, None), (1, None), (0, None),
])
def test_decided_only_returns_a_bool_when_the_answer_is_one(value, want):
    assert app.decided(value) == want


def test_string_true_still_reaches_the_feed(monkeypatch):
    # The whole point: this used to be silently dropped as "not an opportunity".
    monkeypatch.setattr(app, "fetch_raw", lambda url: "raw")
    monkeypatch.setattr(app, "parse_feed", lambda raw: _items("u1"))
    monkeypatch.setattr(app, "triage",
                        lambda it: {"is_opportunity": "true", "type": "job",
                                    "reason": "r"})
    d = _data()
    app.scan(d)
    assert len(d["feed"]) == 1
    assert d["last_scan"]["failed"] == 0


def test_an_answer_we_cannot_read_is_counted_and_asked_again(monkeypatch):
    monkeypatch.setattr(app, "fetch_raw", lambda url: "raw")
    monkeypatch.setattr(app, "parse_feed", lambda raw: _items("u1"))
    monkeypatch.setattr(app, "triage", lambda it: {"is_opportunity": "perhaps"})
    d = _data()
    app.scan(d)
    assert d["feed"] == []
    assert d["last_scan"]["skipped"] == 0, "unreadable is not the same as 'not an opportunity'"
    assert d["last_scan"]["failed"] == 1
    assert "u1" not in d["seen"], "it must be asked about again on the next scan"


def test_json_wrapped_in_extra_words_is_recovered(monkeypatch):
    # Small models like to add prose or code fences even when told to reply with JSON only.
    _reply(monkeypatch, {"message": {"content": 'Sure!\n```json\n{"score": 42}\n```'}})
    assert app.llm("sys", "user", schema=app.EXTRACT_SCHEMA) == {"score": 42}


def test_bare_null_is_a_model_error_not_a_crash(monkeypatch):
    _reply(monkeypatch, {"message": {"content": "null"}})
    with pytest.raises(app.LLMError):
        app.llm("sys", "user", schema=app.EXTRACT_SCHEMA)


# ---------- renderings a real page uses ----------

def _ord(n):
    if 11 <= n % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def test_ordinal_day_verifies():
    d = _d(45)
    out = app.check_deadline({"deadline_iso": d.isoformat()},
                             f"Apply by {d.day}{_ord(d.day)} of {d:%B} {d.year}.")
    assert out["status"] == "verified", out["note"]


def test_day_with_dashes_or_slashes_verifies():
    d = _d(45)
    for sep in ("-", "/", ".", ","):
        page = f"Deadline {d.day}{sep}{d:%b}{sep}{d.year}."
        out = app.check_deadline({"deadline_iso": d.isoformat()}, page)
        assert out["status"] == "verified", f"sep={sep!r} -> {out}"


def test_closing_date_in_a_range_verifies():
    # Pages print "Applications 6 Nov - 4 Dec 2026"; both dates are on the page and the
    # squashed form glued them together, so neither could ever confirm.
    a, b = _d(10), _d(20)
    page = f"Applications {a.day} {a:%B} {a.year} - {b.day} {b:%B} {b.year}."
    for d in (a, b):
        out = app.check_deadline({"deadline_iso": d.isoformat()}, page)
        assert out["status"] == "verified", f"{d} -> {out}"


def test_a_date_the_page_prints_for_another_reason_is_not_verified():
    # The killer case: the page DOES print the posted date, and the model mistook it for
    # the deadline. Presence alone cannot tell those apart, so the words around the date
    # have to be about applying or closing.
    posted, real = _d(5), _d(60)
    page = (f"Posted {posted.day} {posted:%B} {posted.year}. "
            f"Applications close {real.day} {real:%B} {real.year}.")
    out = app.check_deadline({"deadline_iso": posted.isoformat()}, page)
    assert out["status"] == "unconfirmed", out
    assert "closing date" in out["note"].lower()


def test_quote_that_does_not_contain_the_date_is_rejected():
    d = _d(45)
    page = f"Deadline {d:%B} {d.day}, {d.year}."
    out = app.check_deadline({"deadline_iso": d.isoformat(),
                              "deadline_quote": "we welcome everyone"}, page)
    assert out["status"] == "unconfirmed"


def test_quote_naming_a_different_date_is_rejected():
    d = _d(45)
    page = f"Deadline {d:%B} {d.day}, {d.year}."
    out = app.check_deadline({"deadline_iso": d.isoformat(),
                              "deadline_quote": "apply by 1 January 2030"}, page)
    assert out["status"] == "unconfirmed"


def test_a_bigger_model_is_not_counted_as_the_asked_one(monkeypatch):
    # Reporting gemma3:12b as healthy for a gemma3:4b request makes every chat fail.
    monkeypatch.setattr(app, "MODEL", "gemma3:4b")
    _tags(monkeypatch, {"models": [{"name": "gemma3:12b"}, {"name": "llama3:8b"}]})
    assert app._probe_model() is False


def test_non_dict_request_body_is_a_clean_error(monkeypatch, tmp_path):
    # do_POST turns this into a 400; without the guard it is an AttributeError on .get.
    monkeypatch.setattr(app, "DATA_FILE", tmp_path / "data.json")
    handler = object.__new__(app.Handler)
    with pytest.raises(ValueError, match="can't read"):
        handler._handle(42)


# ---------- how much of a page is read, and how fast ----------

def test_a_short_page_is_passed_through_untouched():
    assert app.sample("a short page") == "a short page"


def test_a_long_page_shows_its_start_and_its_end():
    # The old cut kept only the head, so a deadline printed near the bottom was invisible
    # to the model and the card said "not checked" about a page that did state it.
    text = "H" * 4000 + " apply by 5 March 2027 " + "T" * 4000
    out = app.sample(text)
    assert len(out) <= app.PAGE_CHARS
    assert out.startswith("H") and out.endswith("T")
    assert "the page continues" in out


def test_sampling_twice_does_not_chop_the_tail_it_just_kept():
    once = app.sample("H" * 5000 + "T" * 5000)
    assert app.sample(once) == once


def test_the_model_is_kept_loaded_between_jobs(monkeypatch):
    # Loading a 3.8 GB model costs more than answering a job does, and Ollama drops it
    # after five idle minutes, so two jobs in a row would pay that load cost twice.
    holder = _sent(monkeypatch)
    app.llm("sys", "user")
    assert holder["req"].body["options"]["keep_alive"] == "30m"


def test_one_dead_feed_does_not_stop_the_healthy_ones(monkeypatch):
    # Sources are fetched together now. A feed that refuses to answer must still be
    # reported by name, and must not take the other feed's items down with it.
    def fetch(url):
        if url.endswith("dead"):
            raise OSError("down")
        return "raw"

    monkeypatch.setattr(app, "fetch_raw", fetch)
    monkeypatch.setattr(app, "parse_feed", lambda raw: _items("u1"))
    monkeypatch.setattr(app, "triage", lambda it: {"is_opportunity": True,
                                                     "type": "job", "reason": "r"})
    d = _data()
    d["sources"] = ["https://dead", "https://alive"]
    app.scan(d)
    assert d["last_scan"]["added"] == 1
    assert any("did not answer" in e and "https://dead" in e
               for e in d["last_scan"]["errors"])
    assert not any("alive" in e for e in d["last_scan"]["errors"])


# ---------- the first run, before anything is typed ----------

def test_scan_needs_nothing_written_about_the_person(monkeypatch, tmp_path):
    # This route used to answer a first-time visitor with "Write your background first."
    # Finding openings does not need a person; saying whether one fits them does, and that
    # question now lives on the card they choose.
    monkeypatch.setattr(app, "DATA_FILE", tmp_path / "data.json")
    app.save({"profile": "", "sources": ["https://f1"]})
    monkeypatch.setattr(app, "model_available", lambda: True)
    monkeypatch.setattr(app, "fetch_raw", lambda url: "raw")
    monkeypatch.setattr(app, "parse_feed", lambda raw: _items("u1"))
    monkeypatch.setattr(app, "triage", lambda it: {"is_opportunity": True, "type": "job",
                                                   "reason": "remote and open to students"})
    handler = object.__new__(app.Handler)
    handler.path = "/api/scan"
    handler._send = lambda *a, **k: None
    handler._handle({})
    assert [x["url"] for x in app.load()["feed"]] == ["u1"]


def test_a_type_off_the_list_is_never_printed(monkeypatch, tmp_path):
    # The schema says `enum`, so I expected the answer to be one of seven words. A live scan
    # on the real model printed "Accelerator", "programme" and "essay award" instead: Ollama's
    # structured output is best-effort, so a schema narrows the odds and does not promise.
    # The last check has to be ours. An invented word on a card looks like a fact.
    monkeypatch.setattr(app, "DATA_FILE", tmp_path / "data.json")
    app.save({"profile": "", "sources": ["https://f1"]})
    monkeypatch.setattr(app, "model_available", lambda: True)
    monkeypatch.setattr(app, "fetch_raw", lambda url: "raw")
    monkeypatch.setattr(app, "parse_feed", lambda raw: _items("u1"))
    monkeypatch.setattr(app, "triage", lambda it: {"is_opportunity": True,
                                                   "type": "Accelerator",
                                                   "reason": "a funded programme for founders"})
    handler = object.__new__(app.Handler)
    handler.path = "/api/scan"
    handler._send = lambda *a, **k: None
    handler._handle({})
    assert app.load()["feed"][0]["type"] == ""
    assert app.load()["feed"][0]["reason"] == "a funded programme for founders"

    assert app.known_type("fellowship") == "fellowship"
    assert app.known_type("Fellowship") == "fellowship"
    assert app.known_type("essay award") == ""
    assert app.known_type("") == ""
    assert app.known_type(None) == ""


def test_a_tracked_card_can_not_print_a_made_up_type(monkeypatch, tmp_path):
    # The same rule has to hold on the second place a type is stored: a page tracked from a
    # link. Otherwise the list under the feed still shows whatever word the model liked.
    monkeypatch.setattr(app, "DATA_FILE", tmp_path / "data.json")
    app.save({"profile": "", "sources": [], "opportunities": []})
    monkeypatch.setattr(app, "model_available", lambda: True)
    monkeypatch.setattr(app, "extract", lambda text: dict(
        _page_fields(), type="essay award"))
    handler = object.__new__(app.Handler)
    handler.path = "/api/track"
    handler._send = lambda *a, **k: None
    handler._handle({"text": "PAGE"})
    assert app.load()["opportunities"][0]["fields"]["type"] == ""


def _page_fields():
    return {"title": "t", "organization": "", "type": "", "deadline": "", "deadline_iso": "",
            "deadline_quote": "", "location": "", "eligibility": [], "benefits": [],
            "how_to_apply": "", "summary": ""}


def test_a_tracked_card_can_not_print_a_line_about_the_page(monkeypatch, tmp_path):
    # The paste path stores a summary straight from the model, and the model writes "The page
    # announces a fully funded fellowship" there just as it does in a scan reason. Same rule as
    # known_type above: the check belongs where the words are stored, not only on the way out.
    monkeypatch.setattr(app, "DATA_FILE", tmp_path / "data.json")
    app.save({"profile": "", "sources": [], "opportunities": []})
    monkeypatch.setattr(app, "model_available", lambda: True)
    monkeypatch.setattr(app, "extract", lambda text: dict(
        _page_fields(), summary="The page announces a fully funded fellowship."))
    handler = object.__new__(app.Handler)
    handler.path = "/api/track"
    handler._send = lambda *a, **k: None
    handler._handle({"text": "PAGE"})
    assert app.load()["opportunities"][0]["fields"]["summary"] == \
        "A fully funded fellowship."


def test_a_scan_keep_stores_the_reason_without_its_framing(monkeypatch, tmp_path):
    # unframe_reason is only worth having if scan() actually calls it before saving.
    monkeypatch.setattr(app, "DATA_FILE", tmp_path / "data.json")
    app.save({"profile": "", "sources": ["https://a.example/feed"]})
    monkeypatch.setattr(app, "model_available", lambda: True)
    monkeypatch.setattr(app, "fetch_raw", lambda url: "raw")
    monkeypatch.setattr(app, "parse_feed", lambda raw: _items("https://a.example/1"))
    monkeypatch.setattr(app, "triage", lambda it: {"is_opportunity": True, "type": "grant",
                                                   "reason": "Post announces a grant round."})
    handler = object.__new__(app.Handler)
    handler.path = "/api/scan"
    handler._send = lambda *a, **k: None
    handler._handle({})
    assert app.load()["feed"][0]["reason"] == "A grant round."


def test_triage_is_never_shown_the_person(monkeypatch):
    # If the scan still pasted a background in, an empty one would leave the model judging
    # fit for a stranger it has to invent.
    holder = _sent(monkeypatch)
    app.triage({"title": "t", "url": "u", "snippet": "s"})
    assert "PERSON" not in holder["req"].body["messages"][1]["content"]
    for words in ("background", "person", "they"):
        assert words not in app.SYS_TRIAGE.lower()


def test_a_reason_never_starts_by_talking_about_the_container():
    # Asked not to write "the post announces", gemma3:4b answered "Post announces the HACK
    # PRADESH - RVIT Hackathon for participants." on four of nine live keeps. A sentence about
    # the feed is not information about the opening, and it is the one part of the line a
    # reader has to skip, so the app drops the leading clause about the container instead of
    # asking the model, again, to stop.
    strip = app.unframe_reason
    assert strip("Post announces the HACK PRADESH for participants.") == "The HACK PRADESH for participants."
    assert strip("The page is listing internships in Berlin.") == "Internships in Berlin."
    assert strip("This article announces a grant round.") == "A grant round."
    assert strip("Blog post shares six scholarships.") == "Six scholarships."
    assert strip("The post invites applications from young leaders.") == \
        "Applications from young leaders."
    # A sentence whose subject is the opening itself keeps its verb, even the same verb:
    # "covers" is only framing when the thing doing the covering is the container.
    assert strip("The fellowship covers tuition and travel.") == \
        "The fellowship covers tuition and travel."
    # Sentences that are already about the opening come back untouched...
    assert strip("The Loeb Fellowship is fully funded for practitioners.") == \
        "The Loeb Fellowship is fully funded for practitioners."
    assert strip("Application is open for the citiesRISE Fellowship.") == \
        "Application is open for the citiesRISE Fellowship."
    # ...and a line that is nothing but the framing stays as it is rather than going blank.
    assert strip("The post announces") == "The post announces"


def test_the_reason_names_the_opening_not_the_post():
    # One scan, ten cards, and every line began "The post announces". That is the model
    # reporting on the page it read instead of the opening a reader could enter, and it spent
    # the only line the feed gives on words nobody needed.
    assert "Do not write about the post" in app.SYS_TRIAGE
    assert 'not "The post announces' in app.SYS_TRIAGE
    assert "who it is for" in app.TRIAGE_SCHEMA["properties"]["reason"]["description"]


def test_the_fit_check_says_three_things_not_nine(monkeypatch):
    # Asked for "at most 3 points" in prose, the model answered "why you fit" with nine, and
    # the card became a wall of text to scroll instead of advice to act on. The count is the
    # one part of that sentence a program can hold it to.
    long = {"why": [f"w{i}" for i in range(9)], "gaps": [f"g{i}" for i in range(5)],
            "next_steps": [f"n{i}" for i in range(4)]}
    _sent(monkeypatch, long)
    m = app.match("a background", {"title": "t"})
    assert [len(m[k]) for k in ("why", "gaps", "next_steps")] == [3, 3, 3]
    assert m["why"] == ["w0", "w1", "w2"]


def test_the_default_sources_announce_things():
    # dev.to's tag feeds are blog posts about hackathons, not announcements of them. They sat
    # last in the list, so they were only ever judged after the real platforms had been seen
    # - which filled the whole feed with the app's worst material.
    assert not any("dev.to" in s for s in app.DEFAULT_SOURCES)
    assert len(app.DEFAULT_SOURCES) >= 4


def test_the_type_answer_can_only_come_from_the_list():
    # The feed printed tags reading "programme", "Accelerator" and "essay award", because the
    # field only held a sentence *describing* its choices. Prose is a request; an enum is a
    # rule, and Ollama can enforce the second one on a model that will not obey the first.
    for schema in (app.TRIAGE_SCHEMA, app.EXTRACT_SCHEMA):
        assert set(schema["properties"]["type"]["enum"]) == set(app.TYPES)
