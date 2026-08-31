import re
from dataclasses import dataclass
from typing import Optional

_PRICE_JSON_RE = re.compile(r'"(?:currentPrice|price)"\s*:\s*"?(\d+(?:\.\d{1,2})?)"?')
_PRICE_TEXT_RE = re.compile(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?")


@dataclass
class PriceExtractResult:
    found: bool
    price_text: Optional[str] = None


def extract_price(html: str) -> PriceExtractResult:
    json_match = _PRICE_JSON_RE.search(html)
    if json_match:
        value = json_match.group(1)
        return PriceExtractResult(True, f"${value}")

    text_match = _PRICE_TEXT_RE.search(html)
    if text_match:
        return PriceExtractResult(True, text_match.group(0))

    return PriceExtractResult(False)
