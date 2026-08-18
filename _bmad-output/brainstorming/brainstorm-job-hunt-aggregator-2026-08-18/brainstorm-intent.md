# Intent — Job Hunt Aggregator

## Summary
A local job-hunt web app (Next.js frontend + Django backend) that scrapes an extensible set of job sites, scores postings against the owner's profile, and closes the application loop. Owner: Akram Bensouici — full-stack web dev with a Fiverr web-scraping/automation background. Goal: land a full-stack web dev role faster.

## Locked Direction

### Build order (locked)
1. Simple extensible engine skeleton + application loop
2. Interest scoring + urgency signals

### Design principle
Engine starts simple, designed to be extended. Jobs are the first client of a generic scraping engine.

## Scoring Model
- **Weights:** problem-domain overlap + post sanity favored over tech-stack overlap.
- **Interest signals:**
  - Requirements/tech stack matches owner's stack
  - Company's problem type already solved in the owner's previous work (problem-domain overlap)
  - Post well-written with realistic expectations (no absurd stacked requirements)
- **Urgency signals:**
  - Cross-posting footprint (same job posted by same recruiter on multiple sites) = recruiter in dire need of filling the role
  - Repost history from persistent scraping: same title/text reappears after delete = churn; cluster of new related roles = growth — works on sparse platforms

## Application Loop
- Mark-as-applied
- Self-tuning feedback: backend tracks application outcomes (response / interview / silence), learns which postings respond to the profile, steers next fetch toward what works
- Stop-and-rest: tool tells the user when to stop (e.g., 10 great matches applied this week -> rest); sanity/anti-burnout mode. Self-tuning filter and stop-signal are one feedback mechanism.

## MVP Scope (v1)
- **In:** job listings + easy add-new-site extensibility
- **Cut from v1:** dashboards, tracking, feedback loop, LLM parsing, notifications (deferred to later versions)

## Tech Direction Notes
- Reuse the multi-phase pipeline from prior scraping projects (Fiverr-era Ouedkniss scraper / real estate platform):
  raw > extraction > cleaning > normalization > deduplication > validation
- Stack: scrapy + playwright + LLM-based parsing
- Real-time: websockets/polling from the Django scraper loop; paged full list
- Browser notification: one-click actionable -> opens local job detail page with Mark-as-applied button next to the external link

## Key Insights
1. Urgency signals are queries over persistent engine data — free once the engine exists
2. Scoring is the product — judgment no job board offers
3. Self-tuning filter and stop-signal are one feedback mechanism
4. The engine is generic; jobs are its first client (repurposable to social-media monitoring / trending products later)
