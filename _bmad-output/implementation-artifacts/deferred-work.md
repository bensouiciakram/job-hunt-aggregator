# Deferred Work

<!-- Collected from build workflow reviews. Each entry: source spec, one-sentence summary, evidence of reality. -->

- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-backend-foundation.md`
  summary: Enforce dedup_fingerprint immutability and seen_sources append-only semantics at the model/repository layer (save guard / helper API).
  evidence: Review finding — invariants are currently documented in comments only; story 1.3 (collection pipeline) owns the upsert semantics and should enforce them.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-backend-foundation.md`
  summary: Define and enforce the dedup_fingerprint format (non-empty, sha256 hex, algorithm/version headroom) with the pipeline that generates it.
  evidence: Review round 2 — max_length=64 fits sha256 hex exactly with no headroom; empty-string fingerprints would collide on the unique index; story 1.3 owns fingerprint generation.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-backend-foundation.md`
  summary: Enforce FetchLog ok/error consistency (ok=False implies an error message; ok=True implies none) when the pipeline writes logs (story 1.3).
  evidence: Review round 2 — misleading audit records undermine AD-6 failure isolation.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-backend-foundation.md`
  summary: Harden Listing.status at the DB layer (CheckConstraint) when Epic 2 introduces the apply service.
  evidence: Review round 2 — choices are form-layer only; ORM can insert 'bogus' status today.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-source-registry.md`
  summary: Add CORS headers when the Next.js frontend (Story 1.8) calls this API cross-origin (localhost:3000 → localhost:8000); csrf_exempt is already granted.
  evidence: Review finding — the API is same-origin-only today; the Story 1.8 frontend posts from a different localhost origin.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-source-registry.md`
  summary: SSRF hardening — host allow-list for test-fetch URLs — if the tool ever binds beyond localhost.
  evidence: Review finding — test-fetch fetches arbitrary url_pattern hosts; acceptable for a local single-user tool (NFR-1) but unsafe if exposed.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-collection-pipeline.md`
  summary: seen_sources lost-update window — check-then-append on `listing.seen_sources` has no row lock, so two writers appending concurrently could drop one source key.
  evidence: Post-review finding (Story 1.3 patch) — SQLite lacks row locks; the single collector process makes this moot today; revisit if a second writer ever appends to the same Listing.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-4-collector-worker.md`
  summary: Wake-from-sleep backfill bookkeeping — the misfire_grace_time fix stops coalesced runs from being silently dropped, but writing a backfill FetchLog row on resume requires spec renegotiation.
  evidence: Post-review finding (Story 1.4 patch) — grace time applied; revisit.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-4-collector-worker.md`
  summary: Stale-cutoff anchored to pre-poll `now` — the stale count uses the `now` captured before the poll; drift only on long passes.
  evidence: Post-review finding (Story 1.4 patch) — nit; revisit.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-4-collector-worker.md`
  summary: Source-deleted-mid-poll dangling FK — Listing.source and FetchLog.source use SET_NULL; snapshot semantics; revisit if FK enforcement is ever enabled.
  evidence: Post-review finding (Story 1.4 patch) — revisit if FK enforcement ever enabled.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-4-collector-worker.md`
  summary: Boot-time DB crash fails loud by design — AD-6 isolation is per-source only; startup pass errors are not swallowed.
  evidence: Post-review finding (Story 1.4 patch) — revisit.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-5-ouedkniss-adapter.md`
  summary: ouedkniss GraphQL shape drift — site API changes (field renames, category slug changes, GraphQL deprecations) break the adapter silently; surfaced only via worker stale counts / backfill signals; revisit periodically.
  evidence: Story 1.5 implementation — the live probe (2026-08-18) already showed the spec-era `emploi` category slug returning zero results (the working slug is `offres_demandes_emploi`), and schema introspection is disabled on the endpoint, so drift cannot be detected programmatically.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-5-ouedkniss-adapter.md`
  summary: ouedkniss adapter: blank keyword unguarded at the adapter level (q='' is sent) — mitigated upstream by collect_source's Keyword Set validation; revisit if the adapter is ever called directly.
  evidence: Story 1.5 patch review — `fetch(['python', ''])` pins current behavior (the second SearchQuery sends q='').
- source_spec: `_bmad-output/implementation-artifacts/spec-1-5-ouedkniss-adapter.md`
  summary: ouedkniss 'cities' field currently unmapped (future location-key intent).
  evidence: Story 1.5 patch review — `cities { name }` is kept in the query for future use; the six-key canonical contract has no location key yet.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-6-google-jobs-adapter.md`
  summary: google-jobs/google blocking risk — JobSpy's reverse-engineered Google Jobs endpoints may break or rate-limit without warning; surfaced only via worker stale counts / FetchLog failures; the python-jobspy version pin is the mitigation.
  evidence: Story 1.6 implementation — the live probe (2026-08-19) succeeded but returned an empty DataFrame for the 24h window, so real-world availability is only visible through collection outcomes; hermetic tests mock the transport and the adapter is pinned to python-jobspy 1.1.82.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-6-google-jobs-adapter.md`
  summary: jobspy's google path sorts the mixed date/None `date_posted` column — a TypeError from comparing `datetime.date` with `None` wraps into a labelled fetch failure; unexercised since the probe returned empty; monitor via future probes.
  evidence: Story 1.6 patch review — the fixture is date-only (no None cells), so mixed-type sorting is untested; revisit when a real scrape returns mixed date_posted values.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-7-facebook-groups-adapter.md`
  summary: FB relative-date parsing — `published_at` is always None logged-out (Facebook renders relative dates like "2 h"/"hier", not parseable ISO); parsing them into dates is a future pipeline enhancement.
  evidence: Story 1.7 implementation — the approved spec freezes published_at=None for the logged-out path; the lenient pipeline stores None; deferred deliberately.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-7-facebook-groups-adapter.md`
  summary: Private-group manual login — logged-out browsing only today; a `user-data-dir` persistent-context option (one-time manual login in a headed browser) is a future option for private groups.
  evidence: Story 1.7 implementation — login walls raise the labelled 'login required' error by design; the adapter contains no credentials/login code; out of scope per the approved spec.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-7-facebook-groups-adapter.md`
  summary: FB message-node pinning (`[data-ad-preview="message"]`) and comment-article exclusion are the next drift-maintenance triggers for feed extraction — the fixture's nested-comment decoy documents that comment bodies must not pollute post text, and card-level comment exclusion currently rides on the no-permalink rule and the (netloc, path) dedupe identity.
  evidence: Story 1.7 review loopback — extraction keys on div[dir="auto"] text blocks inside div[role="article"] cards; the review's fixture decoys (nested comment article, sidebar article) are the drift canaries for these two selectors; relative-date parsing and private-group login entries above already exist.