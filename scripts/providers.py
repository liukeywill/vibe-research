#!/usr/bin/env python3
"""Replaceable bibliographic providers, normalized metadata and bounded retries."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import socket
import time
from typing import Protocol
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 8 * 1024 * 1024


def doi(value):
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", str(value or "").strip(), flags=re.I).lower()


def normalized(provider, payload):
    """Metadata received from canonical API, never claim/full-text verification."""
    docs = payload["message"]["items"] if provider == "crossref" else payload["response"]["docs"]
    if not isinstance(docs, list):
        raise ValueError("API records are not an array")
    result = []
    for item in docs:
        if provider == "crossref":
            title = (item.get("title") or [""])[0]
            ident = doi(item.get("DOI"))
            url = "https://doi.org/" + urllib.parse.quote(ident, safe="/") if ident else item.get("URL", "")
            authors = [" ".join(filter(None, [a.get("given"), a.get("family")])) or a.get("name", "") for a in item.get("author", [])]
            dates = item.get("issued", {}).get("date-parts", [[]])
            year = dates[0][0] if dates and dates[0] else None
            source_id = "CR_" + hashlib.sha256((ident or url or title).encode()).hexdigest()[:16]
            abstract = item.get("abstract", "")
        else:
            source_id = "ERIC_" + str(item["id"])
            title, authors, year = item.get("title", ""), item.get("author", []), item.get("publicationdateyear")
            url = "https://eric.ed.gov/?id=" + urllib.parse.quote(str(item["id"]))
            linked_url = item.get("url", "")
            ident = doi(linked_url) if re.match(r"https?://(?:dx\.)?doi\.org/", str(linked_url), re.I) else ""
            abstract = item.get("description", "")
        if not title or not url:
            continue
        authors = [author for author in authors if isinstance(author, str) and author.strip()]
        record = {"id": source_id, "title": title, "url": url, "authors": authors,
                  "year": year, "provider": provider, "abstract": abstract,
                  "access_level": "metadata", "metadata_status": "verified",
                  "verification_scope": "canonical API metadata retrieved; content and claims not verified"}
        if ident:
            record["doi"] = ident
        if provider == "eric":
            record["eric_id"] = str(item["id"])
        result.append(record)
    return result


class SourceProvider(Protocol):
    """search returns {records: list[dict], raw: bytes, url: str}."""
    name: str

    def search(self, query: str, limit: int) -> dict: ...


class HTTPSource:
    name = ""

    def __init__(self, timeout=25):
        if not 0 < timeout <= 120:
            raise ValueError("timeout must be 0–120 seconds")
        self.timeout = timeout
        self.last_raw = None
        self.last_url = ""

    def url(self, query, limit):
        raise NotImplementedError

    def search(self, query, limit):
        self.last_raw = None
        self.last_url = self.url(query, limit)
        request = urllib.request.Request(self.last_url, headers={"User-Agent": "research-workbench/3.0", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            self.last_raw = response.read(MAX_BYTES + 1)
        if len(self.last_raw) > MAX_BYTES:
            self.last_raw = None
            raise ValueError("API response exceeds 8 MiB")
        return {"records": normalized(self.name, json.loads(self.last_raw)), "raw": self.last_raw, "url": self.last_url}


class CrossrefProvider(HTTPSource):
    name = "crossref"

    def url(self, query, limit):
        return "https://api.crossref.org/works?" + urllib.parse.urlencode({"query": query, "rows": limit})


class EricProvider(HTTPSource):
    name = "eric"

    def url(self, query, limit):
        fields = "id,title,description,url,publicationdateyear,author,subject,peerreviewed"
        return "https://api.ies.ed.gov/eric/?" + urllib.parse.urlencode({"search": query, "format": "json", "rows": limit, "fields": fields})


class LocalJSONProvider:
    """Explicit local normalized array; '*' imports all; other queries match words."""
    name = "local-json"

    def __init__(self, file):
        self.file = Path(file).expanduser()
        if self.file.is_symlink() or not self.file.is_file():
            raise ValueError("local-json requires an existing ordinary JSON file")
        self.last_url, self.last_raw = self.file.resolve().as_uri(), None

    def search(self, query, limit):
        with self.file.open("rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("local JSON exceeds 8 MiB")
        self.last_raw = raw
        values = json.loads(raw)
        if not isinstance(values, list):
            raise ValueError("local JSON must be an array of normalized source records")
        result = []
        for value in values:
            if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or not value[k].strip() for k in ("id", "title", "url")):
                raise ValueError("local source records require nonempty string id, title, url")
            # Imported metadata is a candidate, irrespective of unverifiable incoming labels.
            record = {**value, "provider": self.name, "access_level": "metadata", "metadata_status": "unverified",
                      "verification_scope": "local import; canonical metadata and claims not verified"}
            haystack = (record["title"] + " " + str(record.get("abstract", ""))).casefold()
            if query == "*" or all(word in haystack for word in query.casefold().split()):
                result.append(record)
        return {"records": result[:limit], "raw": raw, "url": self.last_url}


_REGISTRY = {"crossref": CrossrefProvider, "eric": EricProvider, "local-json": LocalJSONProvider}


def register_provider(name, factory):
    """An explicit caller can register a provider without modifying the collector."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", name) or name in _REGISTRY or not callable(factory):
        raise ValueError("provider needs a unique safe name and callable factory")
    _REGISTRY[name] = factory


def make_provider(name, options=None):
    if name not in _REGISTRY:
        raise ValueError(f"unknown provider: {name}; available: {', '.join(_REGISTRY)}")
    return _REGISTRY[name](**(options or {}))


def retryable(error):
    if isinstance(error, urllib.error.HTTPError):
        return error.code == 429 or 500 <= error.code <= 599
    if isinstance(error, (TimeoutError, socket.timeout)):
        return True
    return isinstance(error, urllib.error.URLError) and isinstance(error.reason, (TimeoutError, socket.timeout))


class ProviderFailure(ValueError):
    def __init__(self, error, attempts, provider):
        super().__init__(f"{type(error).__name__}: {error}")
        self.attempts, self.raw, self.url = attempts, getattr(provider, "last_raw", None), getattr(provider, "last_url", "")


def run_search(provider, query, limit, max_attempts=1, backoff=0.25):
    if not isinstance(query, str) or not query.strip() or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("query must be nonempty; limit must be an integer in 1..100")
    if type(max_attempts) is not int or not 1 <= max_attempts <= 5 or not 0 <= backoff <= 2:
        raise ValueError("max_attempts must be 1..5; backoff must be 0..2 seconds")
    attempts = []
    for number in range(1, max_attempts + 1):
        try:
            found = provider.search(query, limit)
            if not isinstance(found, dict) or not isinstance(found.get("records"), list) or not isinstance(found.get("raw"), bytes) or not isinstance(found.get("url"), str):
                raise ValueError("provider response must contain records array, raw bytes and url string")
            from contracts import validate
            validate("source-record", found["records"])
            attempts.append({"attempt": number, "status": "ok"})
            return {**found, "attempts": attempts}
        except (OSError, ValueError, KeyError, TypeError) as error:
            can_retry = retryable(error)
            delay = min(2.0, backoff * 2 ** (number - 1)) if can_retry and number < max_attempts else 0
            attempts.append({"attempt": number, "status": "error", "error": f"{type(error).__name__}: {error}", "retryable": can_retry, "delay_seconds": delay})
            if not can_retry or number == max_attempts:
                raise ProviderFailure(error, attempts, provider) from error
            time.sleep(delay)
