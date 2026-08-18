# Deferred Work

<!-- Collected from build workflow reviews. Each entry: source spec, one-sentence summary, evidence of reality. -->

- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-backend-foundation.md`
  summary: Enforce dedup_fingerprint immutability and seen_sources append-only semantics at the model/repository layer (save guard / helper API).
  evidence: Review finding — invariants are currently documented in comments only; story 1.3 (collection pipeline) owns the upsert semantics and should enforce them.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-backend-foundation.md`
  summary: Pin backend dependencies reproducibly (pyproject.toml + uv.lock) instead of `uv pip install "Django>=6.1,<7"`.
  evidence: Review finding — no lockfile exists yet; worth doing once the backend dependency set stabilizes (after adapters land).
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