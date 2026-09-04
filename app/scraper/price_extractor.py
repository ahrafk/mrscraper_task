import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

_PRICE_JSON_RE = re.compile(r'"(?:currentPrice|price)"\s*:\s*"?(\d+(?:\.\d{1,2})?)"?')


@dataclass
class PriceExtractResult:
    found: bool
    price_text: Optional[str] = None


def _clean_amount(text: str) -> str:
    text = text.strip()
    return text if text.startswith("$") else f"${text}"


def extract_price(html: str) -> PriceExtractResult:
    soup = BeautifulSoup(html, "html.parser")

    dollars_el = soup.select_one("span.item-price-dollar")
    if dollars_el:
        dollars = dollars_el.get_text(strip=True).replace("$", "")
        if dollars:
            cents_el = soup.select_one("span.item-price-cents, span.item-price-cent")
            cents = cents_el.get_text(strip=True).lstrip(".") if cents_el else ""
            price_text = f"${dollars}.{cents}" if cents else _clean_amount(dollars)
            return PriceExtractResult(True, price_text)

    json_match = _PRICE_JSON_RE.search(html)
    if json_match:
        return PriceExtractResult(True, f"${json_match.group(1)}")

    return PriceExtractResult(False)
