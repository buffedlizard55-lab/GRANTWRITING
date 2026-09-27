"""Refuse to publish a catalog that violates the fact boundary."""

from __future__ import annotations

from datetime import date
from urllib.parse import urlparse

from pipeline.codes import STATUS_VALUES


class CatalogError(RuntimeError):
    def __init__(self, errors: list[str]):
        super().__init__(f"{len(errors)} catalog validation errors")
        self.errors = errors


def _bad_url(url: str | None) -> bool:
    if not url:
        return True
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return True
    host = parsed.netloc.lower()
    return not (host.endswith(".gov") or host.endswith(".mil") or host.endswith(".gov."))


def validate_opportunities(records: list[dict], as_of: date) -> list[str]:
    errors = []
    ids = [r.get("id") for r in records]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate opportunity ids.")
    if not records:
        errors.append("Catalog has zero opportunities. Refusing to publish an empty catalog as if the refresh succeeded.")
    for record in records:
        rid = record.get("id")
        if not record.get("title") or not record.get("source", {}).get("name"):
            errors.append(f"{rid}: missing title or source name")
        if record.get("status") not in STATUS_VALUES:
            errors.append(f"{rid}: bad status {record.get('status')}")
        if _bad_url((record.get("urls") or {}).get("official")):
            errors.append(f"{rid}: official URL is missing or not a .gov/.mil URL")
        close = (record.get("dates") or {}).get("close")
        if record.get("status") == "open" and close and close < as_of.isoformat():
            errors.append(f"{rid}: status open but close date {close} is before as-of {as_of}")
        funding = record.get("funding") or {}
        for key in ("ceiling", "floor", "estimated_total", "expected_awards"):
            value = funding.get(key)
            if value is not None and not isinstance(value, int):
                errors.append(f"{rid}: funding.{key} is {type(value).__name__}, expected int or null")
        if "probability" in record or "win_probability" in record:
            errors.append(f"{rid}: catalog must not contain a win probability")
        for topic in record.get("topics") or []:
            if topic.get("method") == "keyword" and not topic.get("matched_terms"):
                errors.append(f"{rid}: keyword topic {topic.get('id')} has no matched term")
        if record.get("record_kind") != "program" and not record.get("inclusion", {}).get("basis"):
            errors.append(f"{rid}: research opportunity has no inclusion basis")
    return errors


def validate_awards(records: list[dict]) -> list[str]:
    errors = []
    for record in records:
        rid = record.get("id")
        if not record.get("title"):
            errors.append(f"{rid}: award missing title")
        if _bad_url((record.get("urls") or {}).get("official")):
            errors.append(f"{rid}: award official URL is missing or not .gov/.mil")
        amount = record.get("amount_obligated", record.get("amount"))
        if amount is not None and not isinstance(amount, int):
            errors.append(f"{rid}: amount is not an int or null")
        if record.get("record_type") not in {"historical_award", "obligation"}:
            errors.append(f"{rid}: award record_type missing")
    return errors


def assert_valid(opportunities: list[dict], awards: list[dict], as_of: date) -> None:
    errors = validate_opportunities(opportunities, as_of) + validate_awards(awards)
    if errors:
        raise CatalogError(errors[:50])
