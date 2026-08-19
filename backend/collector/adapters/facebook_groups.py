"""FacebookGroupsAdapter — the `facebook-groups` SourcePort adapter.

Target: job postings shared inside Algerian **public** Facebook groups,
browsed logged-out with Playwright's **sync API** (headless chromium).
Facebook's post DOM is client-rendered and login-gated — the
architecture reserved Playwright for exactly this target (the other two
adapters are JSON/requests).

Logged-out browsing reality (2026-08-19):
- Visiting a group logged-out either renders the feed (public groups) or
  redirects to a login wall (private/gated groups). The adapter's
  contract: rendered feed -> extract; login wall -> labelled failure
  ('login required'). Silent empty results are forbidden (they would
  masquerade as "no jobs found").
- Post dates render as relative text ("2 h", "hier"); parseable ISO is
  not available logged-out, so `published_at` is None always (deferred:
  relative-date parsing, see
  `_bmad-output/implementation-artifacts/deferred-work.md`).
- The login wall is detected by a COMPOUND check after `goto` — visible
  wall marker (short probe timeout, `state='visible'`) OR the page URL
  redirected to a login path ('/login' in page.url) — BEFORE waiting for
  the feed container. On a feed-wait timeout the same check is re-probed:
  a gated group must be reported as 'login required', a slow public
  group must never false-positive into NAV_TIMEOUT.

Selector drift is the adapter's single point of maintenance: Facebook
ships DOM changes weekly. The pinned selector set below is grouped and
documented as of 2026-08-19; when the live DOM changes, only this block
(and `collector/tests/fixtures/facebook_feed.html`) moves.

AD-1: pure adapter — no DB access, no Django imports. `fetch` raises
`FacebookGroupsAdapterError` (group URL context) on config violation,
keyword capture failure, browser/playwright launch failure, navigation
timeout, login wall, or selector structure collapse; a rendered feed with
zero posts is a valid empty result. Per-card failures never abort the
group (one broken card is skipped). `parse` is pure — it raises the
labelled error when called without a prior `fetch` (never silently
filters everything out), and applies the case-insensitive substring
keyword filter over the post text, canonical six-key mapping, title =
first non-blank line truncated to 500 (validate's cap — truncated HERE).
"""

from urllib.parse import urljoin, urlsplit

from playwright.sync_api import sync_playwright

from ..ports import SourcePort

# --- Pinned selector set (drift-maintenance point) --------------------------
# Documented as of 2026-08-19, matching the logged-out group feed DOM
# (mirrored by collector/tests/fixtures/facebook_feed.html). When
# Facebook changes the DOM, only this block + that fixture move.
#
# Feed container: the GroupFeed pagelet that renders on public groups.
# Post cards are queried SCOPED to this container (descendant combinator):
# sidebar/suggested-group articles live OUTSIDE the pagelet and must not
# be extracted.
FEED_CONTAINER_SELECTOR = 'div[data-pagelet="GroupFeed"]'
# Post card: one per post in the feed (scoped: feed container > article).
# Nested comment articles still match the scoped selector but are skipped
# by the no-permalink rule / the (netloc, path) dedupe identity.
POST_CARD_SELECTOR = 'div[role="article"]'
# Post text: ALL message blocks inside the card (a multi-paragraph post
# renders several dir="auto" blocks; their texts are joined with '\n').
POST_TEXT_SELECTOR = 'div[dir="auto"]'
# Author: the poster name in the card header.
AUTHOR_SELECTOR = 'h2 span'
# Permalink: the post link (relative /groups/... href, resolved against
# BASE_URL). Cards without it are skipped.
PERMALINK_SELECTOR = 'a[href^="/groups/"]'
# Login wall: the redirect target for gated/private groups.
LOGIN_WALL_SELECTOR = 'form[action^="/login"]'
# --- End of pinned selector set ---------------------------------------------

BASE_URL = 'https://www.facebook.com'
# Navigation hardening: same 30s convention as the other adapters.
NAV_TIMEOUT = 30000
# Login-wall probe: SHORT timeout so a public group that merely renders
# slowly never spends the full nav budget on the marker query; the wall
# marker, when present, appears with the first paint of the login page.
WALL_PROBE_TIMEOUT = 3000
# Hard sample cap: same convention as collector/test_fetch.py.
MAX_SAMPLE = 50


class FacebookGroupsAdapterError(Exception):
    """Facebook/Playwright failure with the group context in the message.

    `collect_source` catches everything (AD-6) and logs the message with
    stage 'fetch'; the group URL + failure kind make the log actionable.
    """


class FacebookGroupsAdapter(SourcePort):
    """Fetch public Facebook group feeds via Playwright (headless chromium).

    The config channel (Story 1.7 review loopback, ratified) passes
    `Source.config` (dict-guarded) to every adapter constructor: this
    adapter reads `config['groups']` — the group URLs to browse.
    """

    def __init__(self, config=None):
        self.config = config or {}
        # Keyword Set for parse(): captured by fetch (the SourcePort
        # contract passes keywords only to fetch; parse stays pure).
        self.keywords = []
        # Parse purity guard (review loopback, ratified): fetch sets this;
        # parse without a prior fetch raises the labelled error instead of
        # silently filtering everything out.
        self._fetched = False

    def _check_login_wall(self, page, group_url):
        """Raise the labelled 'login required' error on a compound wall check.

        Visible wall marker (short probe timeout) OR the page URL
        redirected to a login path ('/login' in page.url). The marker
        probe swallows its own timeout — a slow public group that never
        renders the marker must not be mislabelled.
        """
        marker = None
        try:
            marker = page.wait_for_selector(
                LOGIN_WALL_SELECTOR, timeout=WALL_PROBE_TIMEOUT, state='visible'
            )
        except Exception:
            pass
        redirected = False
        try:
            redirected = '/login' in page.url
        except Exception:
            pass
        if marker is not None or redirected:
            raise FacebookGroupsAdapterError(
                f'facebook-groups login required for group '
                f'{group_url!r}: public group feed not accessible'
            )

    def _extract_card(self, card, seen, raw_items):
        """One post card -> one raw item; no-permalink cards are skipped.

        The dedupe identity ignores query/fragment and trailing slashes:
        `urlsplit(permalink).path.rstrip('/')` keyed with the lowercased
        netloc — a `?comment_id=` variant or a trailing-slash variant
        collapses onto the post's canonical identity (first occurrence
        wins; the permalink is emitted as-is).
        """
        link = card.query_selector(PERMALINK_SELECTOR)
        if link is None:
            return
        href = link.get_attribute('href')
        if not isinstance(href, str) or not href.strip():
            return
        permalink = urljoin(BASE_URL, href)
        parts = urlsplit(permalink)
        key = (parts.netloc.lower(), parts.path.rstrip('/'))
        if key in seen:
            return
        seen.add(key)
        text = '\n'.join(
            el.inner_text()
            for el in card.query_selector_all(POST_TEXT_SELECTOR)
        )
        author_el = card.query_selector(AUTHOR_SELECTOR)
        author = author_el.inner_text() if author_el is not None else ''
        raw_items.append({
            'text': text,
            'author': author,
            'permalink': permalink,
        })

    def fetch(self, keywords: list[str]) -> list[dict]:
        """Browse every configured group once; permalink-deduped, capped.

        One browser + one context per fetch, all groups always visited
        (the 50-item output cap never short-circuits the group loop),
        dedupe across groups by (netloc, path) identity, output
        truncated silently at 50 first-occurrence. Each raw item is
        `{'text', 'author', 'permalink'}` (JSON-safe; parse keeps the
        Keyword Set filter). The browser/context/pages are closed in
        `finally` on every path, including launch failures — every close
        is guarded so a teardown failure can never mask the in-flight
        labelled error. Keyword capture and the Playwright context
        manager are inside the try: driver-level failures are labelled,
        never bare. Config groups are deduped (`dict.fromkeys`) after
        validation so a duplicate group URL is visited once.
        """
        groups = self.config.get('groups')
        if (
            not isinstance(groups, list)
            or not groups
            or not all(isinstance(g, str) and g.strip() for g in groups)
        ):
            raise FacebookGroupsAdapterError(
                "facebook-groups config 'groups' must be a non-empty "
                'list of strings'
            )
        groups = list(dict.fromkeys(groups))
        seen = set()
        raw_items = []
        self._fetched = True
        try:
            self.keywords = list(keywords)
        except Exception as exc:
            raise FacebookGroupsAdapterError(
                f'facebook-groups fetch failed: {exc}'
            ) from exc
        try:
            with sync_playwright() as p:
                browser = None
                context = None
                try:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context()
                    for group_url in groups:
                        page = None
                        try:
                            page = context.new_page()
                            page.goto(group_url, timeout=NAV_TIMEOUT)
                            self._check_login_wall(page, group_url)
                            try:
                                page.wait_for_selector(
                                    FEED_CONTAINER_SELECTOR, timeout=NAV_TIMEOUT
                                )
                            except Exception:
                                # The feed never rendered: re-probe the
                                # wall before labelling NAV_TIMEOUT (a
                                # gated group lands here after a slow
                                # redirect; a slow public group must be
                                # reported as a timeout, not a wall).
                                self._check_login_wall(page, group_url)
                                raise
                            for card in page.query_selector_all(
                                f'{FEED_CONTAINER_SELECTOR} {POST_CARD_SELECTOR}'
                            ):
                                try:
                                    self._extract_card(card, seen, raw_items)
                                except Exception:
                                    continue
                        except FacebookGroupsAdapterError:
                            raise
                        except Exception as exc:
                            raise FacebookGroupsAdapterError(
                                f'facebook-groups fetch failed for group '
                                f'{group_url!r}: {exc}'
                            ) from exc
                        finally:
                            try:
                                if page is not None:
                                    page.close()
                            except Exception:
                                pass
                except FacebookGroupsAdapterError:
                    raise
                except Exception as exc:
                    raise FacebookGroupsAdapterError(
                        f'facebook-groups browser failed: {exc}'
                    ) from exc
                finally:
                    try:
                        if context is not None:
                            context.close()
                    except Exception:
                        pass
                    try:
                        if browser is not None:
                            browser.close()
                    except Exception:
                        pass
        except FacebookGroupsAdapterError:
            raise
        except Exception as exc:
            raise FacebookGroupsAdapterError(
                f'facebook-groups browser failed: {exc}'
            ) from exc
        return raw_items[:MAX_SAMPLE]

    def parse(self, raw_items: list[dict]) -> list[dict]:
        """Canonical six-key mapping per the Story 1.7 matrix.

        Exactly six keys: title, company, url, published_at, keywords,
        raw_snapshot. A post is kept only when its text contains at
        least one Keyword Set entry (case-insensitive substring);
        `keywords` lists every matching keyword (first-occurrence order,
        deduped). Title = first non-blank line of the text, truncated to
        500 HERE (validate never sees an overlong title); company =
        author or ''; published_at = None always (logged-out Facebook
        renders relative dates only); raw_snapshot keeps the full text.
        Parse purity guard: calling parse without a prior fetch raises
        the labelled error — parse must never silently filter everything
        out as if a keyword-less fetch had returned zero posts.
        """
        if not self._fetched:
            raise FacebookGroupsAdapterError(
                'facebook-groups parse called before fetch: adapter never '
                'fetched; refusing to silently filter everything out'
            )
        parsed = []
        keywords = self.keywords
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            text = raw.get('text')
            permalink = raw.get('permalink')
            if not isinstance(text, str) or not isinstance(permalink, str):
                continue
            if not permalink.strip():
                continue
            lowered = text.lower()
            matches = list(dict.fromkeys(
                kw for kw in keywords
                if isinstance(kw, str) and kw.strip() and kw.lower() in lowered
            ))
            if not matches:
                continue
            title = next(
                (line.strip() for line in text.splitlines() if line.strip()),
                '',
            )[:500]
            author = raw.get('author')
            if not isinstance(author, str):
                author = ''
            parsed.append({
                'title': title,
                'company': author,
                'url': permalink,
                'published_at': None,
                'keywords': matches,
                'raw_snapshot': {
                    'text': text,
                    'author': author,
                    'permalink': permalink,
                },
            })
        return parsed