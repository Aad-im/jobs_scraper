"""One shared HTTP client for every source.

Job boards fail in three annoying ways: transient 5xx, rate-limit 429s, and —
the nastiest — a 200 with an empty payload. The first two are handled by urllib3's
retry policy; the third is why callers get `expect_nonempty`, which turns "200 but
nothing in it" into a retryable error instead of silently publishing an empty board.
"""
from __future__ import annotations

import random
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0.0.0 Safari/537.36 (+personal job tracker)")

DEFAULT_TIMEOUT = 45
_RETRY_STATUS = (408, 425, 429, 500, 502, 503, 504)

_local = threading.local()


def session() -> requests.Session:
    """Thread-local pooled session (requests.Session is not thread-safe)."""
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        retry = Retry(
            total=4, connect=3, read=3, status=3,
            backoff_factor=0.8,                      # 0.8s, 1.6s, 3.2s, 6.4s
            status_forcelist=_RETRY_STATUS,
            allowed_methods=frozenset({"GET", "POST"}),
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=32, pool_connections=32)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        # Brotli is advertised by default whenever the optional decoder is
        # installed, and Ashby's CDN serves br bodies that the decoder then
        # chokes on ("called with data when can_accept_more_data() is False").
        # gzip/deflate are universally supported and cost nothing here.
        s.headers.update({"User-Agent": UA,
                          "Accept": "application/json, text/plain, */*",
                          "Accept-Encoding": "gzip, deflate"})
        _local.session = s
    return s


class EmptyPayload(RuntimeError):
    """A 200 response whose body held no records — treated as a soft failure."""


def get_json(url: str, *, timeout: int = DEFAULT_TIMEOUT, headers: dict | None = None,
             expect_nonempty: str | None = None, attempts: int = 3):
    """GET JSON. `expect_nonempty` names a key that must be present and truthy."""
    return _json("GET", url, None, timeout, headers, expect_nonempty, attempts)


def post_json(url: str, body: dict, *, timeout: int = DEFAULT_TIMEOUT,
              headers: dict | None = None, expect_nonempty: str | None = None,
              attempts: int = 3):
    """POST JSON. Same contract as `get_json`."""
    return _json("POST", url, body, timeout, headers, expect_nonempty, attempts)


def _json(method, url, body, timeout, headers, expect_nonempty, attempts):
    last: Exception | None = None
    for i in range(attempts):
        try:
            s = session()
            r = (s.post(url, json=body, timeout=timeout, headers=headers)
                 if method == "POST" else
                 s.get(url, timeout=timeout, headers=headers))
            r.raise_for_status()
            data = r.json()
            if expect_nonempty is not None and not _has(data, expect_nonempty):
                raise EmptyPayload(f"200 but no '{expect_nonempty}' in {url}")
            return data
        except Exception as e:  # noqa: BLE001 — every failure mode retries the same way
            last = e
            if i < attempts - 1:
                time.sleep((0.7 * 2 ** i) + random.uniform(0, 0.4))
    raise last  # type: ignore[misc]


def _has(data, key: str) -> bool:
    if isinstance(data, list):
        return bool(data)
    if isinstance(data, dict):
        return bool(data.get(key))
    return bool(data)
