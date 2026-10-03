# Secret sources

Paste any of these into the Sources box in HopeHunter (one per line). Each was checked live on 3 Oct 2026 and returned real items.

## Fellowships, scholarships, internships, grants (global, good for students anywhere)
- Opportunity Desk: `https://opportunitydesk.org/feed/`
- Opportunities for Youth: `https://opportunitiesforyouth.org/feed/`
- Opportunities for Youth, grants only: `https://opportunitiesforyouth.org/category/grants/feed/` (10 items)
- Scholarship Scorer: `https://scholarshipscorner.website/feed/` (10 items) or
  `https://www.scholarshipscorner.website/category/scholarships/feed/` (10 items)
- Opportunities Feed: `https://opportunitiesfeed.com/feed/` (50 items)
- Funds for NGOs: `https://www.fundsforngos.org/feed/` (25 items) - **mixed**. Real grant
  calls sit between "A Sample Grant Proposals On..." writing exercises, so it is a good test
  of the filter and a bad feed to trust on its own.

## Hackathons and contests
- Devpost upcoming hackathons (JSON API): `https://devpost.com/api/hackathons?status[]=upcoming&order_by=deadline`

## Remote jobs
- We Work Remotely: `https://weworkremotely.com/remote-jobs.rss`
- Remote OK (JSON API): `https://remoteok.com/api`. Its terms ask you to link back to Remote OK and name it as the source if you republish listings.

## Why DEV tag feeds are not in the defaults
`https://dev.to/feed/tag/<tag>` works for any tag, and I had three of them in the defaults.
That was wrong. A DEV tag feed is a list of **blog posts about** a topic, not a list of
announcements, so it is full of writeups of hackathons already entered and advice articles
about internships. Because those feeds sat last in the list, they were only ever judged after
the real platforms had been seen - which meant every return visit filled the feed with the
worst material in the app. Measured on 3 Oct 2026: all six items left in the feed came from
dev.to and none of them were openings you could apply to.

Keep a DEV tag feed if you want a specific community's posts, but expect to screen a lot.

## A site homepage is not a feed, but you can paste one
Checked live on 3 Oct 2026: `https://scholarshipscorner.website` and
`https://opportunitiesfeed.com` are homepages, and the app now reads the feed each page
advertises in its own `<head>`, or tries `/feed/` and `/rss.xml`, and saves the feed address it
found so the next scan goes straight there. Both of those upgraded themselves this way.

A homepage with no feed anywhere gets said so, with what to do instead. That is the honest
answer for `https://github.com`, `https://devfolio.co`, `https://unstop.com`,
`https://hackerearth.com`, `https://careerflora.com` and `https://feedspot.com` - all of them
announce things, none of them publish a feed. Devpost's homepage is in that group too; its
**API** link above is the one that works.

## Trick: any GitHub repo can be a feed
Append `/commits/main.atom` to a repo's URL to follow its changes. Curated internship lists on GitHub update this way.

## Not verified, so not included
Remotive (its API blocked my checker), MLH (no public feed found), Reddit (blocked from my checker). Try them yourself if you want them.

## Why EGA Mentorship came back out
`https://egamentorship.org/feed.xml` answers, and it is full of internships, so it looked like a
keep. It is a **blog**. One scan let through "EGA Mentorship International Deepens Strategic
Partnerships to Expand Youth Opportunities Across..." tagged `internship` - a partnership
announcement, not something a person can apply to. Same rule that removed the DEV tag feeds: a
feed of news *about* opportunities is not a feed *of* opportunities.
