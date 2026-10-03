# HopeHunter: a local model that reads opportunity posts so my friend Zohaib doesn't have to

*This is a submission for the [Hacktoberfest Weekend Challenge: Build for a Friend](https://dev.to/challenges/hacktoberfest-weekend-2026-10-01)*

I built this for Zohaib, who has sent me 400 links over the years. "You should
apply for this." Scholarships, hackathons, junior roles, fellowships, grants. Half of them
expired the week they arrived. The rest needed a page-by-page read of eligibility rules to
find out whether they were even for someone like me.

Zohaib is the one who asks me where I find these things. So I asked him a question back: you're
always asking me where I find these opportunities — what if there were a tool that searched for
them and just handed you the curated list? His answer was the entire brief for this project:
**"Damn, that would be great."** He hasn't run it yet. That's the real state of things: a
working tool on my laptop, waiting for the person it was built for.

It scans opportunity feeds, reads a posting with a small language model that runs on my
laptop, pulls out the deadline, tells him honestly what fits and what is missing,
and drafts the message he'd send. His work history never leaves the machine.

![Five of the nine openings one scan kept. Each has one plain line saying what it is, and
the feed that printed it.](shots/01-feed.png)

## Why the model had to be local

This is the part that decided the whole design, not a decoration I added afterwards.

A CV is the most personal document most people own. Sending it to an API means sending it to
a company whose terms you did not read, to a server you will never see, along with your name
and email address. For a tool whose entire job is "read my friend's history and judge it",
that is the wrong shape. An open-weight model running on the laptop keeps the one sensitive
input in the one place it belongs.

Three more things fell out of that choice, all of them true here:

- **Cost per run: zero.** A scan makes about ten model calls. On a hosted API I would have
  been paying to re-read blog posts that the app then throws away.
- **It works offline except for the fetching.** The only network traffic is downloading the
  public pages you asked for.
- **I could change the model.** Same app, different `OLLAMA_MODEL`. That mattered, because my
  GPU is from 2017.

## The GPU was broken, and it still runs

The machine is an i5-8400H with a Quadro P2000: 4 GB of VRAM, Pascal architecture, compute
capability 6.1. Every request came back HTTP 500 with `the provided PTX was compiled with an
unsupported toolchain`. That error is an upstream one (Ollama 0.35.1 with Pascal cards, fix
still open), not mine, and the driver branch that supports these cards is the last one that
ever will.

`OLLAMA_VULKAN=1` sidesteps it. Measured on the real thing: about **11 tokens per second**,
with 1.9 of 3.8 GB resident on the card. Slow, but it answers, and the laptop stayed the only
place the data lived.

## Eight times the app looked fine and was wrong

This is where most of my time went, because a wrong answer does not announce itself. Neither
does a wrong error message.

**1. It renamed my fields.** I asked in prose for `title`, `organization`, `deadline`. Gemma
answered with `name`, and put the deadline inside a nested object. The card rendered with no
title and no date, every test still passing, and nothing anywhere looked wrong. The fix is not
a politer prompt: Ollama can enforce a JSON Schema, so I hand it the schema and the shape stops
being a request.

Except that a schema is still only *mostly* a wall. Ollama's structured output is best-effort,
and a live scan came back with `Accelerator`, `programme` and `essay award` in a field whose
enum printed exactly seven allowed words. So the last check is mine, not the model's: a type
that is not on the list renders no tag at all. Same lesson for prose limits. "At most three
points" sits in a field description, and the model answered *why you fit* with nine sentences,
which is a wall to scroll, not advice. The three I show is a slice in Python.

**2. It invented a deadline.** A small model will print a plausible date the page never
showed. On a tool about deadlines, that single hallucination costs a person their only real
chance. So the app no longer trusts the field. It verifies the exact date appears in the page
text inside a sentence containing deadline-ish words, and that the model's own quoted sentence
names it. Otherwise the card says *not checked*, or *the page prints that date, but not as a
closing date*. Numeric forms like `03/11/2026` are never trusted at all, because day and month
order is ambiguous. I would rather show nothing than show a date I cannot point at.

The same check nearly threw away a real date. The Loeb Fellowship page prints *January 5, 2027*
under a heading that says Application Deadlines; the model answered with those exact words and
left its ISO field empty, so the app gave up with *the model gave no clean date to check* - an
excuse about a date it could have looked up. A date written in month names is just as checkable,
so now it is checked. A phrase with no year in it, like *end of November*, still is not: turning
that into a day would be the app inventing the one thing it exists to verify.

![Top: a date the model gave that the page does not print as a closing date, said so in amber
instead of being shown as fact. Bottom: a date the app found on the page, quoting the sentence it
came from.](shots/03-deadline-honesty.png)

**3. It gave me advice that was wrong about my own machine.** Every request failed and the app
told me to run `ollama pull gemma3:4b`. The model was already installed. The real reason was
the CUDA crash, sitting in the error body the app had thrown away. Now the server's own words
are kept and shown, because "run ollama pull" is a fix and "the scan paused" is not.

**4. Its fit score was fake, so I deleted it.** I gave the same hackathon post to two
backgrounds: one a perfect fit, one with no coding experience at all and no time. Both scored
**1 out of 100**. Same number, same sentence. The coach did the same thing: **0/100** for both.

That is the honest result of asking a 4-billion-parameter model for a number between 0 and 100.
It cannot do it, and a "ranked by fit" list where every item has the same number is decoration
that tricks the reader.

So there is no score anywhere now, and the scan stopped looking at who you are at all. Finding
openings and judging fit are two different questions, and only the second one needs a person.
The fit check and the draft still ask for your background, and answer in words: what fits, what
is missing, what to do next. On the two backgrounds above it writes things like *your open
source projects make you overqualified for a hackathon aimed at beginners*. A real judgement,
in words, that the person can argue with. The number was a lie. The sentence is useful.

![One hackathon read against a background invented for this screenshot: three reasons it fits,
three gaps that are real, three next steps, and a draft to edit before sending. The amber line is
the deadline check declining to vouch for a date range it cannot parse.](shots/02-card-fit-draft.png)

**5. I fed it blog posts and blamed the model.** Three of my eight default feeds were DEV tag
feeds, on the theory that `dev.to/feed/tag/hackathon` is where hackathons are announced. It
isn't. A tag feed is a list of posts *about* a topic, which mostly means people writing up a
hackathon they already entered. After one scan I looked at what the app had actually kept:
**six items, all six from DEV, and none of them a posting you could apply to.** One was titled
"eGain AI Hackathon Project Submission". One was "Confused About Your Career After
Graduation?", an advice article. The model had labelled them `hackathon` and `internship`, and
given only those words to work from, it was not being unreasonable. The bad judgement was mine.

I deleted those three feeds. The five that remain are platforms whose whole business is
announcing things people can enter. The next scan's ten items were ten named programmes with an
open application: the Loeb Fellowship 2027-2028, the citiesRISE Fellowship, a Google Ireland
scholarship, an essay award at American University. Same machine, same 4-billion-parameter
model, same prompt. Only the sources changed. It is the least interesting lesson in this
project and the one that improved the output more than anything else I did this week.

Two more feeds went in afterwards, both checked by hand before they were added: a scholarship
listing site and an opportunities roundup, each one asked live whether it returns posts that name
a real opening you can enter. One candidate that passed that test still came back out - EGA
Mentorship, whose items were press releases about the organisation rather than things to apply
for. Same feed, same model, and the filter kept one as an `internship`. That is mistake five
repeating itself with a better source list, so the honest place to look for its own misses is
the list in "What it still cannot do".

**6. "Couldn't read" was a lie I printed ten times.** I pasted a longer list of sites into the
feeds box — GitHub, Devfolio, Unstop, HackerEarth, a couple of scholarship blogs — and hit scan.
Ten lines came back, every one of them starting *Couldn't read*, and under them a feed the app
had filled from the sources that worked. Those ten lines said one thing about two completely
different problems. GitHub answered in half a second with a page full of HTML; the app had
tried to parse it as XML, failed, and reported it as unreadable. Nothing was unreadable. What
had actually happened is that I pasted homepages into a box that wants feeds, and the message
pointed at the network instead of at me.

So the app now asks the page. When a URL is not a feed it reads that page's own `<head>` for the
feed it advertises, and if the page says nothing it tries the two paths almost every blogging
engine answers: `/feed/` and `/rss.xml`. When one of those works it **rewrites the saved source
to the feed address**, so the next scan goes straight there and never pays for the detour. Two
of my ten upgraded themselves on the spot — `scholarshipscorner.website` became
`scholarshipscorner.website/feed/` and started returning items — and the other eight now say
what is actually wrong: *https://github.com is a web page with no feed on it, so there is
nothing here to scan. Add the site's feed or API link, or paste one opening into "Add one
yourself".* That distinction is the whole fix. Devpost's homepage genuinely has no feed, but its
hackathon API does, and the old message made those two cases look identical, so a reader had no
way to know which one they were in. An error you cannot act on is not an error, it is noise.

The same lie was sitting in the paste-a-link box. A page that answers 404 got described to me as
"login wall?", which is a guess dressed up as a diagnosis. It now says what the server said -
*Couldn't open that page (HTTP Error 403: Forbidden). If it needs a login, paste its text in
below instead* - so a blocked page tells you to use the fallback and a moved page tells you the
link is dead.

**7. Adding a site changed nothing.** I had eleven feeds in the box by then, and the scan still
only ever read the first two. It built its queue one feed after another and stopped after ten
posts, so ten posts came from whichever source happened to sit at the top of the list and the
sites below it were never asked a single question. Every scan looked healthy, because a scan
always returns ten items. A reader who adds a feed has no way to see that their feed was never
read.

The queue now goes round-robin - one post per feed, in turn - so ten posts across eleven sources
samples every source that has something new. Measured on the real thing: the first pass after the
change kept seven openings from six different sites, where the old order spent all ten questions
on whichever feed happened to be first. Each kept item also
carries the feed that printed it, and the card shows it, because a line about a fellowship with
no source on it is a claim the reader cannot weigh against the platform it came from.

![Five openings from four different sites, each naming the feed that printed it, and the list
capped at ten with one click to see the rest.](shots/05-feed-sources.png)

**8. Telling the model to stop was not making it stop.** One card line is supposed to say what
the opening is and who it is for. I asked for that in the prompt, and added the words "Do not
write about the post", and the next live scan answered four of its nine keeps with *"Post
announces the HACK PRADESH - RVIT Hackathon for participants."* That is the model reporting on
the page it read, in the one line the feed gives, and my instruction was still sitting there in
the prompt, unwritten-to.

So the app stopped asking. It cuts the leading clause itself: a fixed, recognisable shape at the
start of the line - a container word (*post, page, article, listing, feed, newsletter, blog
post*) plus its reporting verb (*announces, shares, lists, invites, covers*) - deleted, and the
remainder capitalised. Four words become *"The HACK PRADESH - RVIT Hackathon for participants."*
The rule only fires on words that can never name the opening itself, which is why *programme* is
not on the list: "Programme covers tuition for two years" is a sentence about the fellowship, and
a fix that ate that line would be worse than the padding it removed. A reason that is nothing but
framing comes back unchanged rather than going blank, because an empty line is a worse card than
a padded one.

This is the same lesson as mistake one, arriving from the other direction. A schema is a request.
A prompt sentence is a request. The only thing the app can rely on is the check it runs itself,
after the model has finished being persuasive.

## What I measured instead of guessing

I assumed reading long pages was the problem, so I started writing chunking code. Then I
benchmarked it. Of the 36 seconds it takes to read one page, the model spends **about 2
seconds reading** and **18 writing**. Prefill was never the bottleneck at 100 tokens per
second; generation at 11 was.

So the speed work went somewhere else. Feeds are network waits, not thinking, so they download
together rather than one after another. With five feeds that was a real win: **31.5 seconds to
4.7**. Then I kept adding feeds until there were eleven, re-measured, and got **23 to 43 seconds
in parallel against 27 to 29 one after another** - no win at all, and sometimes slower. One of
the eleven is a 2.2 MB job feed that takes 14 seconds by itself, and ten other threads sharing
one wire do not make that shorter. Parallelism only pays when no single wait dominates. The
honest version of a speedup is the number you measure after the input changes, and mine had gone
stale in the week it took me to write this down.

Asking for shorter answers cut 201 tokens to
163. And the read cap had been silently truncating We Work Remotely's 2.2 MB feed, which is why
it had produced exactly zero jobs since I added it; raising the cap gave back **89 jobs**.

## What it still cannot do

- About a minute per scan of ten posts, because it is one 4 GB GPU from 2017.
- The filter is not perfect, and the misses are not random. On a live scan it let through
  "EGA Mentorship International Deepens Strategic Partnerships..." tagged `internship`, and a
  roundup post of seven scholarships became one scholarship. Both times the fault was the feed,
  and both times the fix was to stop reading it - the same lesson as mistake five, learned twice.
- Only about 7,000 characters of a page reach the model, now taken from the top *and* the
  bottom, since closing dates often print at the end.
- A page behind a login has to be pasted in as text.
- It cannot tell you whether you got the thing.

## Try it

```bash
ollama pull gemma3:4b
python app.py          # then open http://127.0.0.1:8000
```

Python 3.9+, nothing to install, no account, no key. 102 tests run offline in under half a
second.
Windows users with an older card may need `OLLAMA_VULKAN=1`.

Repo: [github.com/Burry071/hopehunter](https://github.com/Burry071/hopehunter). Demo:
![demo]([GIF LINK]). How I built it, agent session included: [SESSION LINK].

![The same feed on a phone-width screen. It is one column of plain HTML, so there was nothing to
port.](shots/04-mobile-feed.png)

## What I got out of it

First Hacktoberfest, and I went in wanting experience rather than a prize. What I actually got
is a rule I did not have before: **a model's confidence is not evidence.** Every one of the eight
failures above looked like success on the screen. The app was green, polite, and wrong. The only
thing that caught them was checking one specific claim against the source it came from, which
is cheap, and which I should have been doing from the first day.

And Zohaib has a tool that reads his feeds on a laptop that sits in the same room he does, with
nothing about him sent anywhere, which is exactly what he asked for and no hosted API would have
given him.

#devchallenge #weekendchallenge #hf26challenge #gemma #opensource #python #ai
