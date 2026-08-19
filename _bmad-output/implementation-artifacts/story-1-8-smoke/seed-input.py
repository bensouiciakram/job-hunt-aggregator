"""Story 1.8 smoke seed — recorded shell input (run via manage.py shell).

Run with:
    uv run python manage.py shell -c "exec(open('..\\..\\_bmad-output\\implementation-artifacts\\story-1-8-smoke\\seed-input.py').read())"
"""
from datetime import timedelta

from django.utils import timezone

from collector.pipeline import compute_fingerprint
from listings.models import FetchLog, Listing


def add(title, company, days_ago, **kw):
    url = f"https://example.com/jobs/{abs(hash(title + company))}"
    defaults = {
        'company': company,
        'url': url,
        'published_at': timezone.now() - timedelta(days=days_ago),
        'keywords': kw.pop('keywords', []),
    }
    defaults.update(kw)
    defaults['dedup_fingerprint'] = compute_fingerprint(title, company, url)
    return Listing.objects.create(title=title, **defaults)


titles = [
    ('Smoke Newest Posting', 'Acme Corp'),
    ('Python Developer', 'PyWorks'),
    ('Senior Python Engineer', 'DataHive'),
    ('Backend Engineer', 'OpsCo'),
    ('Junior Web Developer', 'Webify'),
    ('DevOps Engineer', 'CloudNine'),
    ('Data Analyst', 'DataHive'),
    ('Machine Learning Engineer', 'AI Labs'),
    ('Frontend Engineer', 'Webify'),
    ('Full Stack Developer', 'StartupX'),
    ('QA Tester', 'QualityCo'),
    ('Product Manager', 'StartupX'),
    ('UX Designer', 'DesignHub'),
    ('Mobile Developer', 'AppWorks'),
    ('Site Reliability Engineer', 'CloudNine'),
    ('Security Engineer', 'SafeNet'),
    ('Systems Administrator', 'InfraCo'),
    ('Database Administrator', 'DataHive'),
    ('Network Engineer', 'InfraCo'),
    ('Technical Writer', 'DocsCo'),
    ('Support Engineer', 'SupportCo'),
    ('Sales Engineer', 'Vendora'),
    ('Marketing Specialist', 'BrandCo'),
    ('Finance Analyst', 'MoneyWorks'),
    ('HR Coordinator', 'PeopleCo'),
    ('Operations Manager', 'OpsCo'),
    ('Weaver Specialist', 'TextileWorks'),
    ('Research Scientist', 'AI Labs'),
    ('Software Architect', 'ArchTech'),
    ('Cloud Consultant', 'CloudNine'),
]
for i, (title, company) in enumerate(titles):
    add(title, company, i)

# One listing with NULL published_at (NULL_DATE case in the real UI).
add('Smoke Null Date Listing', 'NullCo', 0, published_at=None)

# 'zigzag' lives only in the keywords JSON field — searching it must yield
# zero title/company icontains matches (the smoke asserts the empty search
# state for 'zigzag').
add('Smoke Zigzag Keyword Listing', 'PatternWorks', 0, keywords=['zigzag'])

# The one ok=True stage='pass' FetchLog that drives the sweep stamp.
FetchLog.objects.create(stage='pass', ok=True, error='')

print(
    'seeded:',
    Listing.objects.filter(title__startswith='Smoke ').count(),
    'listings + 1 FetchLog (pass/ok)',
)