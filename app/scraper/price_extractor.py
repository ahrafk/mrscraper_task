import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

_PRICE_JSON_RE = re.compile(r'"(?:currentPrice|price)"\s*:\s*"?(\d+(?:\.\d{1,2})?)"?')

# Lowe's own product data carries this flag straight from their catalog, separate from
# whatever markup the price widget happens to render with. Confirmed against a real
# archived/no-longer-sold listing and a normal in-stock one side by side, it's true only
# on the genuinely unavailable page, so it's a much safer signal than scanning the page
# for wording like "unavailable", which also shows up in unrelated delivery/pickup copy
# on completely ordinary, priced listings.
_CONFIRMED_UNAVAILABLE_RE = re.compile(r'"isNotAvailable"\s*:\s*true')


@dataclass
class PriceExtractResult:
    found: bool
    price_text: Optional[str] = None


def _clean_amount(text: str) -> str:
    text = text.strip()
    return text if text.startswith("$") else f"${text}"


def is_confirmed_unavailable(html: str) -> bool:
    return bool(_CONFIRMED_UNAVAILABLE_RE.search(html))


def extract_price(html: str) -> PriceExtractResult:
    soup = BeautifulSoup(html, "html.parser")

    dollars_el = soup.select_one("span.item-price-dollar")
    if dollars_el:
        dollars = dollars_el.get_text(strip=True).replace("$", "")
        if dollars:
            # the cents piece isn't always a span, on some listings it renders as a div
            # with the same class names, matching on tag as well as class silently
            # truncated the price down to whole dollars for those
            cents_el = soup.select_one(".item-price-cents, .item-price-cent")
            cents = cents_el.get_text(strip=True).lstrip(".") if cents_el else ""
            price_text = f"${dollars}.{cents}" if cents else _clean_amount(dollars)
            return PriceExtractResult(True, price_text)

    json_match = _PRICE_JSON_RE.search(html)
    if json_match:
        return PriceExtractResult(True, f"${json_match.group(1)}")

    return PriceExtractResult(False)
