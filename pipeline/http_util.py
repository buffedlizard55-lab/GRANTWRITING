"""Small HTTP helper with retries. Stdlib only."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = (
    "FederalResearchGrantIntelligence/1.0 "
    "(+https://github.com/buffedlizard55-lab/GRANTWRITING; public research catalog)"
)


class HttpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _request(url: str, method: str, data: bytes | None, headers: dict, timeout: int):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read(500).decode("utf-8", "replace")
        raise HttpError(f"{method} {url} failed: HTTP {exc.code} {body}", exc.code) from exc
    except urllib.error.URLError as exc:
        raise HttpError(f"{method} {url} failed: {exc.reason}") from exc


def fetch_bytes(url: str, timeout: int = 90, attempts: int = 4, method: str = "GET", data: bytes | None = None, headers: dict | None = None) -> tuple[bytes, dict]:
    hdrs = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with _request(url, method, data, hdrs, timeout) as resp:
                payload = resp.read()
                info = {k.lower(): v for k, v in resp.headers.items()}
                info["status"] = str(getattr(resp, "status", ""))
                info["final_url"] = resp.geturl()
                return payload, info
        except HttpError as exc:
            last = exc
            if exc.status and 400 <= exc.status < 500 and exc.status != 429:
                raise
            time.sleep(min(8, 2 ** (attempt - 1)))
    raise HttpError(f"{method} {url} failed after {attempts} attempts: {last}")


def fetch_text(url: str, timeout: int = 90, attempts: int = 4) -> str:
    payload, _info = fetch_bytes(url, timeout=timeout, attempts=attempts)
    return payload.decode("utf-8", "replace")


def post_json(url: str, payload: dict, timeout: int = 90, attempts: int = 4) -> dict:
    body = json.dumps(payload).encode("utf-8")
    raw, _info = fetch_bytes(
        url,
        timeout=timeout,
        attempts=attempts,
        method="POST",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HttpError(f"POST {url} returned non-JSON: {raw[:200]!r}") from exc


def download(url: str, dest: Path, timeout: int = 300, attempts: int = 3) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".partial")
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp, partial.open("wb") as handle:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    handle.write(chunk)
            partial.replace(dest)
            return
        except Exception as exc:  # network errors vary
            last = exc
            time.sleep(min(10, 2 ** (attempt - 1)))
    raise HttpError(f"Download {url} failed: {last}")
