import re

LOWES_PDP_RE = re.compile(r"^https://www\.lowes\.com/pd/[^/?#]+/\d+/?(?:[?#].*)?$")


class InvalidProductUrlError(Exception):
    pass


def validate_lowes_pdp_url(raw: str) -> str:
    url = raw.strip()
    if not LOWES_PDP_RE.match(url):
        raise InvalidProductUrlError(
            "productUrl must match https://www.lowes.com/pd/{product-slug}/{product-id}"
        )
    return url
