import re
from dataclasses import dataclass
from typing import Optional

_BLOCK_SIGNATURES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"<TITLE>Access Denied</TITLE>", re.I), "akamai-access-denied"),
    (re.compile(r"errors\.edgesuite\.net|Reference\s*#\s*\d", re.I), "akamai-reference-block"),
    (re.compile(r"Pardon Our Interruption", re.I), "akamai-bot-manager-challenge"),
    (re.compile(r"sec-if-cpt-container|sec-bc-tile-parent|behavioral-content", re.I), "akamai-interactive-challenge"),
    (re.compile(r"px-captcha|perimeterx|_pxCaptcha", re.I), "perimeterx-challenge"),
    (re.compile(r"captcha-delivery\.com|geo\.captcha-delivery", re.I), "datadome-captcha"),
    (re.compile(r"are you a (human|robot)", re.I), "human-check"),
    (re.compile(r"Request unsuccessful\.\s*Incapsula", re.I), "incapsula-block"),
    (re.compile(r"Please verify you are a human", re.I), "human-verify"),
    (re.compile(r'"cpr_chlge"\s*:\s*"?true"?', re.I), "akamai-json-challenge"),
]

MIN_PLAUSIBLE_HTML_LENGTH = 5000


@dataclass
class BlockCheckResult:
    blocked: bool
    reason: Optional[str] = None


def detect_block(
    status: Optional[int], html: str, headers: Optional[dict[str, str]] = None
) -> BlockCheckResult:
    if status is not None and status in (403, 429, 503):
        return BlockCheckResult(True, f"http-{status}")
    if headers and headers.get("akamai-grn") and status != 200:
        return BlockCheckResult(True, "akamai-grn-block")
    for pattern, reason in _BLOCK_SIGNATURES:
        if pattern.search(html):
            return BlockCheckResult(True, reason)
    if len(html) < MIN_PLAUSIBLE_HTML_LENGTH:
        return BlockCheckResult(True, "suspiciously-short-response")
    return BlockCheckResult(False)
