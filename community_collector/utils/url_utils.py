"""URL normalization utilities."""
from __future__ import annotations
import re
from urllib.parse import urlparse, urljoin, urlunparse, parse_qs, urlencode


# UTM and tracking params to strip
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "fbclid", "gclid", "msclkid", "ref", "referral", "mkt_tok",
    "mc_eid", "mc_cid", "_hsenc", "_hsmi", "hsCtaTracking",
})


def normalize_url(url: str | None, base: str | None = None) -> str | None:
    """
    Normalize a URL:
    - Resolve relative URLs against base if provided
    - Strip tracking query parameters
    - Remove fragments
    - Force https where http is used
    """
    if not url:
        return None
    url = url.strip()
    if not url or url.startswith(("javascript:", "mailto:")):
        return None
    if base and not url.startswith("http"):
        url = urljoin(base, url)
    try:
        parsed = urlparse(url)
        scheme = "https" if parsed.scheme == "http" else parsed.scheme
        # Strip tracking params
        if parsed.query:
            qs = {k: v for k, v in parse_qs(parsed.query).items()
                  if k.lower() not in _TRACKING_PARAMS}
            clean_query = urlencode(qs, doseq=True)
        else:
            clean_query = ""
        normalized = urlunparse((
            scheme,
            parsed.netloc.lower(),
            parsed.path,
            parsed.params,
            clean_query,
            "",  # strip fragment
        ))
        return normalized
    except Exception:
        return url


def extract_domain(url: str | None) -> str | None:
    """Return the domain from a URL, e.g. 'meetup.com'."""
    if not url:
        return None
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return None
