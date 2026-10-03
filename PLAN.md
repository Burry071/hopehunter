# HopeHunter: from prototype to Hacktoberfest submission

Deadline: **Mon 5 Oct, 11:59 AM Pakistan time** (6:59 AM UTC). Aim to submit by **10:00 AM** so a glitch doesn't cost you the entry.

Rules to remember: the project must be new and built during the challenge window, open-source AI must be at its core, it must be built for one real person, and the DEV post must use the official template (it adds the tags `#devchallenge #weekendchallenge #hf26challenge`). Judging weights **writing quality most**, then theme fit, creativity, technical execution, and optional partner tech.

## The decision: what does "real app" mean here?

HopeHunter's whole pitch is that it runs on your own laptop and your CV never leaves it. A hosted public site would cut against that and a model needs a GPU to host. So:

- **Submit as a local-first open-source app.** GitHub repo, one-command run, Docker option, demo video, screenshots. This is the strongest story for "why open matters".
- **Do not** host it publicly with other people's CVs on it. Skip Render and DigitalOcean unless you want those prize categories and can explain why hosting fits.

## Timeline (Pakistan time)

| When | Goal |
|---|---|
| Sat 3 Oct evening | Create the GitHub repo and commit the prototype now (commit history inside the window matters). Run it with a real model and fix what breaks. Choose your person. |
| Sun 4 Oct morning | Improve the core flow (Phase 2). Add tests and Docker (Phase 3). |
| Sun 4 Oct afternoon | Sit with your person. Load their real background, run real opportunities, note their exact words. |
| Sun 4 Oct evening | Screenshots, 60-90 second demo video, README polish. |
| Sun 4 Oct night | Write the DEV post (Phase 5). Sleep on it. |
| Mon 5 Oct morning | Re-read, fix typos, publish by 10:00 AM. |

## Phase 0: set up in Qoder (30 min)

1. Unzip `hopehunter.zip` and open the folder in Qoder.
2. `git init`, create a new public GitHub repo named `hopehunter`, and push. Add an MIT `LICENSE`.
3. Install Ollama, then check what's available: `ollama list`. Pull a model that fits your 4 GB GPU, such as `ollama pull gemma3:4b`. For Gemma 4 check the exact tag at ollama.com/library before pulling, since I couldn't confirm it.
4. Run `python app.py` and open http://127.0.0.1:8000.

Qoder prompt to start:
> Read app.py and index.html. Explain the architecture in 10 lines, then run the app and tell me any errors. Don't change anything yet.

## Phase 1: test with the real model (1-2 hours)

The prototype was only tested against a stand-in model. Real small models will surprise you.

- Scan the default sources. Check that opportunities are kept and blog posts are dropped. Count mistakes in both directions.
- Add 3 real opportunity links. Check the extracted deadline against the page. Small models sometimes misread dates.
- Record numbers for your post: seconds per scan, seconds per fit check, model size, RAM used.

Qoder prompt:
> Add a `/api/health` endpoint that reports whether Ollama is reachable and the model is pulled, and show a friendly banner in the UI when it isn't.

## Phase 2: improvements worth the time (pick in this order)

1. **Closing-soon sorting.** Ask the model for a deadline in `YYYY-MM-DD` when stated, sort and badge items due within 14 days. Deadlines are what people miss.
2. **Scan progress.** The scan blocks while the model works. Show "checking 4 of 10" with a streaming response or polling.
3. **Cheaper filtering.** Skip obvious blog posts before calling the model (title keywords like "I built", "tutorial", "how to") so scans run faster on a weak GPU.
4. **Profile from a CV file.** Accept a pasted CV or a `.txt` and keep it local.
5. **Honest uncertainty.** If the model isn't sure about a date, show "check the page" instead of a guess.

Qoder prompt for #1:
> In `extract()`, ask for `deadline_iso` (YYYY-MM-DD or null). Sort tracked opportunities by soonest deadline, show a "closes in N days" badge, and add a unit test for the date handling.

## Phase 3: make it a real project (2 hours)

- **Tests.** `pytest` for `parse_feed` (RSS, Atom, JSON shapes), dedupe, and API errors. The sample shapes are already in my test notes: Devpost `{"hackathons": [...]}`, RemoteOK list with a leading legal object, plain RSS.
- **Docker.** A `docker-compose.yml` running the app plus Ollama, so anyone can start it with `docker compose up`.
- **Config.** `.env.example` for `OLLAMA_MODEL`, `PORT`, `MAX_SCAN`.
- **Security note.** The app fetches URLs you give it. It's bound to 127.0.0.1 so that's fine locally. Say in the README that exposing it publicly would need a URL allowlist.
- **README.** What it is, a screenshot, run steps, how to swap models, the sources list, limits.
- **Repo hygiene.** `.gitignore` with `data.json` so nobody's personal data gets committed. Double check nothing personal is in the repo or screenshots.

Qoder prompt:
> Add pytest tests for parse_feed covering RSS, Atom, and the Devpost and RemoteOK JSON shapes, add a Dockerfile and docker-compose.yml with Ollama, and add `.gitignore` excluding data.json.

## Phase 4: hand it to a real person (the part that wins)

Pick one real person who is job-hunting or applying for programs: a classmate, cousin, neighbor. Not "students in general".

1. Ask them first what the hardest part of finding opportunities is. Write down their words.
2. Load their real background. Run 2 or 3 real opportunities they care about.
3. Note what surprised them, what they liked, what annoyed them, and one thing they did afterward (applied, saved a deadline).
4. Ask permission to quote them and to mention their first name or a nickname. Never publish private details.
5. Fix the one thing that annoyed them before you submit.

If you truly can't find someone, say so honestly in the post. Don't invent a friend or a quote.

## Phase 5: the DEV post (writing is weighted most)

Use the template on the challenge page so the tags are added. Suggested structure:

1. **Hook (3-4 sentences).** The real pain, in a person's voice. Name the person, or a nickname.
2. **What I built.** One paragraph plus a screenshot. Then a 60-90 second demo video or GIF.
3. **Who it's for and what they said.** Their quote and what they did with it.
4. **How it works.** A short diagram or list: sources, local model filter, tracking, fit check, draft.
5. **Why open mattered.** Be specific: the CV never left the laptop, no per-token cost, swapped model X for Y in one setting and compared results, runs with no cloud account. Give your measured numbers.
6. **Where it failed.** One or two real mistakes the small model made and how you handled them. Judges trust honest posts.
7. **Code.** Link to the repo.
8. **Prize categories.** Only claim ones you really used:
   - *Best Use of Gemma* if Gemma is your core model.
   - *Best Use of Entire* if you embed your agent sessions in the post.
   - *Best Use of GitHub Copilot* only if you really used it.

Writing tips: short paragraphs, plain words, one story thread, no hype. Avoid "revolutionary". Show a before and after for your person.

## Submission checklist

- [x] Public GitHub repo, MIT license, README with screenshot and run steps
- [x] Repo history shows work during the challenge window
- [x] Runs from a fresh clone (clone, `python -m pytest`, then `python app.py` with no data.json)
- [x] No personal data or secrets in the repo or the screenshots: the fit-and-draft shot runs
      against a background invented for it, and `data.json` is ignored
- [x] Real person's feedback quoted, with his permission to use his first name and his words
- [x] "Why open" section with measured numbers
- [x] Honest limitations section
- [ ] Demo video or GIF in the post
- [ ] DEV post published with the official template and tags
- [ ] Submitted before Mon 5 Oct 10:00 AM PKT

## If time gets short

Cut in this order: Docker, scan progress, CV upload, closing-soon sorting. Never cut: running with a real model, the real person, and the honest post.
