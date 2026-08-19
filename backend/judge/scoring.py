"""Pure interest scoring (Story 3.1, FR-6).

score() reads a Listing's title/keywords only and returns an int 0..100.
No DB access, no mutation — AD-4 holds by construction and is pinned by test.

Weighting (PRD §4.4 brainstorm decision): problem-domain overlap and post
sanity weigh MORE than tech-stack overlap.
"""

import re

BASE = 50
DOMAIN_WEIGHT = 8
STACK_WEIGHT = 4
ABSURD_STACK_CUTOFF = 4  # distinct stack terms in one title = absurd
ABSURD_STACK_PENALTY = 40
EMPTY_TITLE_PENALTY = 15
MIN_TITLE_LEN = 4

_TOKEN_RE = re.compile(r'[a-z0-9]+')


def _tokens(text):
    """Lowercased alphanumeric tokens: 'Full-stack NodeJS' -> {'full','stack','nodejs'}."""
    return set(_TOKEN_RE.findall((text or '').lower()))


def _token_sequence(text):
    """'Next.js API' -> 'next js api' — de-punctuated, for phrase matching."""
    return ' '.join(_TOKEN_RE.findall((text or '').lower()))


def _match_count(text, terms):
    """Distinct profile terms matched in the text.

    Matching is token-exact (no substring false positives like 'api' inside
    'scraping'). A term matches when every token of the term is present;
    multi-word terms must appear ADJACENTLY in de-punctuated text (so
    'web scraping' does not match 'Web content scraping', while 'Next.js'
    still matches 'next js'). Signatures are canonical: spelling variants
    ('full-stack'/'fullstack', 'web scraping'/'webscraping') collapse.
    """
    tokens = _tokens(text)
    sequence = _token_sequence(text)
    matched = set()
    for term in terms:
        if not isinstance(term, str):
            continue
        words = _TOKEN_RE.findall(term.lower())
        if not words or not set(words) <= tokens:
            continue
        if len(words) > 1 and ' '.join(words) not in sequence:
            continue
        matched.add(''.join(sorted(words)))
    return len(matched)


def _as_list(value):
    return value if isinstance(value, list) else []


def score_text(title, keywords, profile):
    """Pure score for title + keyword list against a profile dict.

    profile: {'tech_stack': [..], 'domains': [..], 'project_types': [..]}
    """
    profile = profile or {}
    title = (title or '').strip()
    keywords = _as_list(keywords)
    keywords_text = ' '.join(k for k in keywords if isinstance(k, str))

    stack_terms = _as_list(profile.get('tech_stack'))
    domain_terms = _as_list(profile.get('domains')) + _as_list(profile.get('project_types'))
    # A term listed as both stack and domain counts once (domain weight wins).
    stack_terms = [t for t in stack_terms if t not in domain_terms]

    title_stack = _match_count(title, stack_terms)
    # Stack matched in title AND keywords counts once (keywords are the user's
    # own search terms; they only confirm, never double-count).
    stack = title_stack if title_stack else _match_count(keywords_text, stack_terms)
    domain = _match_count(title + ' ' + keywords_text, domain_terms)

    score = BASE + domain * DOMAIN_WEIGHT + stack * STACK_WEIGHT

    if title_stack >= ABSURD_STACK_CUTOFF:
        score -= ABSURD_STACK_PENALTY
    if len(title) < MIN_TITLE_LEN or not _tokens(title):
        score -= EMPTY_TITLE_PENALTY

    return max(0, min(100, score))


def score(listing, profile):
    """Score a Listing instance (title + keywords only — AD-4 read-only)."""
    return score_text(listing.title, listing.keywords, profile)