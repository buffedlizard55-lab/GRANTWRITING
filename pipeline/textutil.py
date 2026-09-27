"""Text, date, and money parsing. Never invents a value for a blank field."""

from __future__ import annotations

import html
import re
from datetime import date, datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

_WS = re.compile(r"[ \t]+\n")
_MULTI_NL = re.compile(r"\n{3,}")
_MULTI_SP = re.compile(r"[ \t]{2,}")
_MONEY = re.compile(r"-?\d[\d,]*\.?\d*")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        if tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "section"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    raw = html.unescape(str(value))
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _MULTI_SP.sub(" ", text)
    text = _WS.sub("\n", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


def parse_date(value: str | None) -> date | None:
    """Parse Grants.gov dates. Returns None if blank or unrecognized.

    Accepted forms, all seen in official Grants.gov or NSF fields:
    MMDDYYYY, MM/DD/YYYY, YYYY-MM-DD, and 'Mon DD, YYYY ...'.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "n/a", "na", "tbd", "null"}:
        return None
    for fmt in ("%m%d%Y", "%m/%d/%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).date()
        except ValueError:
            continue
    # 'Oct 11, 2023 12:00:00 AM EDT' and 'Sep 26, 2026 04:41:24 AM EDT'
    match = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2}),\s+(\d{4})", text)
    if match:
        try:
            return datetime.strptime(
                f"{match.group(1)} {match.group(2)} {match.group(3)}", "%b %d %Y"
            ).date()
        except ValueError:
            try:
                return datetime.strptime(
                    f"{match.group(1)} {match.group(2)} {match.group(3)}", "%B %d %Y"
                ).date()
            except ValueError:
                return None
    return None


def iso_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def parse_money(value: str | int | float | None) -> int | None:
    """Parse a published dollar amount to integer dollars.

    Blank, TBD, and non-numeric values become None — never zero.
    A published zero stays zero.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value != value:  # NaN
            return None
        return int(round(float(value)))
    text = str(value).strip()
    if not text or text.lower() in {"none", "n/a", "na", "tbd", "null", "not specified", "see announcement"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    match = _MONEY.search(text.replace("$", ""))
    if not match:
        return None
    number = match.group(0).replace(",", "")
    try:
        amount = float(number)
    except ValueError:
        return None
    if negative:
        amount = -amount
    return int(round(amount))


def parse_int(value: str | int | None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().replace(",", "")
    if not text or not re.fullmatch(r"-?\d+", text):
        return None
    return int(text)


def parse_bool_yes_no(value: str | bool | None) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"yes", "y", "true", "1"}:
        return True
    if text in {"no", "n", "false", "0"}:
        return False
    return None


def eastern_today(now: datetime | None = None) -> date:
    moment = now or datetime.now(EASTERN)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=EASTERN)
    return moment.astimezone(EASTERN).date()


def split_sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text)
    out = []
    for part in parts:
        cleaned = part.strip()
        if len(cleaned) >= 40:
            out.append(cleaned)
    return out


def clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[: limit - 1].rstrip() + "…", True


def host_of(url: str) -> str:
    match = re.match(r"https?://([^/]+)", url or "", re.I)
    return match.group(1).lower() if match else ""
