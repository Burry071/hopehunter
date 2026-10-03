# HopeHunter

A local-first opportunity finder, built for one friend who gets sent 400 links a year. It reads
the feeds of platforms that announce things you can apply to and keeps only the posts that really
name one. Ask about a single opening and it reads the page, checks the deadline against the page's
own words, tells you honestly how you fit, and drafts the message you'd send.

![Five of the nine openings one scan kept, each with one plain line saying what it is and the feed
that printed it.](shots/01-feed.png)

Your background text and all AI processing stay on your machine: the model runs locally
through Ollama, and the only outgoing requests are reads of the public feeds and pages you
list. Nothing you write about yourself is sent anywhere.

## What it does

1. **Finds**: scans the RSS/Atom feeds and JSON APIs you list, and the local model keeps only the posts that really announce something you can apply to, with one short line each saying what it is. Blog posts, tutorials and writeups of work already finished are filtered out. Nothing about you is needed for this step.
2. **Reads**: "Track" opens the page and pulls out deadline, eligibility, benefits and how to apply.
3. **Coaches**: once you have written your background, an honest fit check in plain words - what fits, what is missing, what to do
   next - plus a draft application message.

Default feeds are the platforms listed in [SOURCES.md](SOURCES.md) (Opportunity Desk,
Opportunities for Youth, Devpost, We Work Remotely, Remote OK, Scholarships Corner,
Opportunities Feed) - each one exists to announce
things a person can enter. Add any feed, one per line. Each scan checks up to 10 new posts;
click again for the rest.

## Run it

1. Install [Ollama](https://ollama.com) and pull a model that fits a 4 GB GPU:
   ```
   ollama pull gemma3:4b
   ```
2. Start the app (Python 3.9+, no packages to install):
   ```
   python app.py
   ```
3. Open http://127.0.0.1:8000

## Use a different model

Set `OLLAMA_MODEL` to whatever you pulled:

```
OLLAMA_MODEL=qwen3:8b python app.py        # macOS / Linux
$env:OLLAMA_MODEL="qwen3:8b"; python app.py # PowerShell
```

`MAX_SCAN` (posts judged per scan) and `PORT` work the same way.

## If every request fails with a CUDA error

Older NVIDIA cards (Maxwell, Pascal, Volta - e.g. a Quadro P2000) crash on the CUDA path in
recent Ollama builds: `the provided PTX was compiled with an unsupported toolchain`. The
model is fine; the GPU backend isn't. Two ways past it, either of which is set on the
Ollama service rather than in `app.py`:

- `OLLAMA_VULKAN=1` plus `OLLAMA_LLM_LIBRARY=vulkan` runs the same model on the same card
  through Vulkan. Measured on a P2000: about 11 tokens/second, and a scan of 10 posts of a
  real DEV feed in 77 seconds.
- Or update the NVIDIA driver. The 580 branch is the last one that supports these cards.

Without either, ask for the GPU and Ollama answers on the CPU instead - roughly half the
speed, about 35 seconds to read one page.

## Deadlines are checked, not trusted

A small model will sometimes state a date the page never printed. So the app does not show
a deadline as fact unless that exact date appears in the text it read, and labels it
"confirmed on the page", "Closed", or "not checked" accordingly. An invented date shows as
unconfirmed instead of quietly becoming your plan. Numeric forms like `03/11/2026` are never
trusted on their own, because day and month order is ambiguous.

## Notes

- Data lives in `data.json` next to the app, and is git-ignored. Delete it to reset.
- The server binds to 127.0.0.1 only. Exposing it to a network would need a URL allowlist
  on the fetch step first.
- If a site needs a login, paste the page text into the second box.
- Long pages are read from the top *and* the bottom (about 7000 characters in total), because
  a closing date printed near the end used to be invisible to the model.
- Run the tests with `python -m pytest`. 102 of them, no network and no model needed.

## What it is still bad at

Honest list, from the failures that are still in the code rather than fixed:

- It is a 4-billion-parameter model on a laptop GPU. It misreads pages, and the checks in this
  repo catch the ones it used to get away with, not every one.
- The draft will sometimes put an institution in your mouth that came from the posting, not from
  your background. The label says "edit before sending" because it means it.
- A fit check is written prose, not a ranking. An earlier version scored fit out of 100; two
  opposite backgrounds both scored 1, so the number was deleted.
- It only finds what these feeds announce. A programme posted nowhere in the list stays
  invisible, and one scan reads 10 of the posts waiting, not all of them.
- Built and tested on one Windows laptop with one GPU. Nothing here is exotic, but it has not
  been run anywhere else.

## License

MIT. See [LICENSE](LICENSE). The write-up of how it was built, including the eight ways it was
wrong before it was right, is [ARTICLE.md](ARTICLE.md).
