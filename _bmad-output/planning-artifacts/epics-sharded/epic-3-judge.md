# Epic 3: Judge and pace the hunt (v2)

Every listing earns a worth-my-time score; urgency and churn signals surface from engine history; outcomes steer collection and tell Akram when to rest.

**FRs covered:** FR6, FR7, FR8

## Story 3.1: Interest scoring

As a job hunter,
I want each listing scored for worth-my-time,
So that I can skip the noise and apply where it counts.

**Acceptance Criteria:**

**Given** persisted Listings with keywords and text
**When** the scoring service runs against a hand-maintained profile of Akram's stack and project types
**Then** every Listing receives an Interest Score from 0–100 (FR-6, AD-4 data only)
**And** the score weights problem-domain overlap and post sanity over tech-stack overlap (brainstorm decision, PRD §4.4)
**And** posts with absurd requirement stacks (e.g., nodejs + python + go + java for one backend role) score low via rule-based sanity heuristics
**And** the score appears in the listings API payload and the UI detail view
**And** scoring never mutates `status`, `seen_sources`, or the dedup fingerprint (AD-4)

## Story 3.2: Urgency signals

As a job hunter,
I want to see which postings are urgent and which are churn,
So that I can prioritize live opportunities and skip ghost postings.

**Acceptance Criteria:**

**Given** engine-persisted history (`seen_sources` sets, fetch history, deletion events)
**When** the urgency service runs
**Then** a role appearing on N Sources yields a cross-posting footprint per recruiter-role (dire-need signal)
**And** a Listing whose normalized title+text reappears after deletion is flagged churn-possible
**And** a company posting a cluster of new, related roles yields a growth-possible flag
**And** signals derive from engine history alone, so they work on sparse platforms with limited metadata (FR-7, AD-8)

## Story 3.3: Outcome feedback and pacing

As a job hunter,
I want the tool to learn from my application outcomes and tell me when to rest,
So that my effort goes where it responds and my morale survives the hunt.

**Acceptance Criteria:**

**Given** Applications with outcomes (response/interview/silence, manual entry)
**When** outcomes are recorded against Applications
**Then** collection weighting for future passes adjusts toward responding postings (self-tuning, FR-8)
**And** a stop signal appears when sustained high-quality activity is detected (e.g., "10 great matches applied this week — rest")
**And** outcome entry is available from the application record and never duplicates Applications (AD-5)