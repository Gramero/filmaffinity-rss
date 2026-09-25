#!/usr/bin/env python3
"""Build RSS feeds for El Correo de Andalucía's Sevilla and Andalucía sections.

Uses only the Python standard library. Article titles, canonical URLs and
publication timestamps are taken from article metadata, not from URL slugs or
the date printed in the section listing.
"""

from __future__ import annotations

import concurrent.futures
import email.utils
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


BASE = "https://www.elcorreoweb.es"
OUT_DIR = Path("feeds")
MAX_ARTICLES_PER_SECTION = 60
WORKERS = 8
USER_AGENT = (
    "Mozilla/5.0 (compatible; ElCorreoRSS/1.0; "
    "+https://github.com/gramero/filmaffinity-rss)"
)

SOURCES = {
    "elcorreoweb-sevilla": {
        "section": "sevilla",
        "url": f"{BASE}/sevilla/",
        "feed_title": "El Correo de Andalucía - Sevilla",
        "description": "Últimas noticias de Sevilla - El Correo de Andalucía",
        "file": "elcorreoweb-sevilla.xml",
    },
    "elcorreoweb-andalucia": {
        "section": "andalucia",
        "url": f"{BASE}/andalucia/",
        "feed_title": "El Correo de Andalucía - Andalucía",
        "description": "Últimas noticias de Andalucía - El Correo de Andalucía",
        "file": "elcorreoweb-andalucia.xml",
    },
}


def clean(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", html.unescape(str(value))).strip()


def fetch(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


class PageParser(HTMLParser):
    """Collect page metadata, JSON-LD, headings, times and article links."""

    def __init__(self, page_url: str, section: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.section = section
        self.meta: dict[str, str] = {}
        self.links: list[tuple[str, str]] = []
        self.jsonld: list[str] = []
        self.times: list[tuple[str, str]] = []
        self.h1: list[str] = []
        self._title: list[str] = []
        self._capture: str | None = None
        self._capture_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop")).lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"])
        elif tag == "link" and "canonical" in a.get("rel", "").lower().split():
            self.meta.setdefault("canonical", a.get("href", ""))
        elif tag == "time":
            value = a.get("datetime") or a.get("content")
            if value:
                self.times.append((a.get("itemprop", "").lower(), value))
        elif tag == "a" and a.get("href"):
            absolute = urllib.parse.urljoin(self.page_url, a["href"])
            if self.is_article_url(absolute):
                self._capture = "link"
                self._capture_parts = [absolute]
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._capture = "jsonld"
            self._capture_parts = []
        elif tag == "title":
            self._capture = "title"
            self._capture_parts = []
        elif tag == "h1":
            self._capture = "h1"
            self._capture_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture == "link":
            self.links.append((self._capture_parts[0], clean("".join(self._capture_parts[1:]))))
            self._capture = None
        elif tag == "script" and self._capture == "jsonld":
            self.jsonld.append("".join(self._capture_parts))
            self._capture = None
        elif tag == "title" and self._capture == "title":
            self.meta.setdefault("document_title", clean("".join(self._capture_parts)))
            self._capture = None
        elif tag == "h1" and self._capture == "h1":
            self.h1.append(clean("".join(self._capture_parts)))
            self._capture = None

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._capture_parts.append(data)

    def is_article_url(self, url: str) -> bool:
        p = urllib.parse.urlsplit(url)
        path = urllib.parse.unquote(p.path)
        if p.netloc.lower() not in {"www.elcorreoweb.es", "elcorreoweb.es"}:
            return False
        return bool(re.search(rf"/{re.escape(self.section)}/\d{{4}}/\d{{2}}/\d{{2}}/[^/]+\.html$", path, re.I))


def canonicalize(url: str, section: str) -> str | None:
    p = urllib.parse.urlsplit(urllib.parse.urljoin(BASE, url))
    if p.netloc.lower() not in {"www.elcorreoweb.es", "elcorreoweb.es"}:
        return None
    path = urllib.parse.unquote(p.path)
    if not re.search(rf"/{re.escape(section)}/\d{{4}}/\d{{2}}/\d{{2}}/[^/]+\.html$", path, re.I):
        return None
    return urllib.parse.urlunsplit(("https", "www.elcorreoweb.es", path, "", ""))


def walk_json(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def parse_datetime(raw: object) -> datetime | None:
    value = clean(raw)
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if dt.tzinfo is None:
        # Publisher timestamps without an offset are local Spanish editorial time.
        # In the absence of an explicit offset, interpret as UTC to keep RSS valid.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def article_data(url: str, section: str) -> dict | None:
    try:
        source = fetch(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"Skipping article ({url}): {exc}", file=sys.stderr)
        return None

    parser = PageParser(url, section)
    parser.feed(source)
    final_url = canonicalize(parser.meta.get("canonical", url), section) or url

    title = ""
    published: datetime | None = None
    modified: datetime | None = None
    description = ""
    json_articles = []
    for raw in parser.jsonld:
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for node in walk_json(parsed):
            types = node.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if any("article" in t.lower() or "news" in t.lower() for t in types):
                json_articles.append(node)
    for node in json_articles:
        title = title or clean(node.get("headline") or node.get("name"))
        published = published or parse_datetime(node.get("datePublished"))
        modified = modified or parse_datetime(node.get("dateModified"))
        description = description or clean(node.get("description"))

    title = title or clean(parser.meta.get("og:title")) or clean(parser.meta.get("twitter:title"))
    title = title or clean(parser.meta.get("document_title")) or (parser.h1[0] if parser.h1 else "")
    description = description or clean(parser.meta.get("og:description")) or clean(parser.meta.get("description"))
    published = published or parse_datetime(parser.meta.get("article:published_time"))
    published = published or parse_datetime(parser.meta.get("datepublished"))
    modified = modified or parse_datetime(parser.meta.get("article:modified_time"))
    modified = modified or parse_datetime(parser.meta.get("datemodified"))
    for prop, value in parser.times:
        if prop in {"datepublished", "datepublished"}:
            published = published or parse_datetime(value)
        elif prop in {"datemodified", "dateupdated"}:
            modified = modified or parse_datetime(value)

    # Prefer the original publication date. Use the update date only when the
    # publisher omits publication metadata; never infer a date from the URL.
    published = published or modified
    if not title or not published:
        print(f"Skipping article without headline/publication metadata: {url}", file=sys.stderr)
        return None
    title = re.sub(r"\s*[|–-]\s*El Correo de Andalucía\s*$", "", title, flags=re.I).strip()
    return {
        "title": title,
        "url": final_url,
        "published": published,
        "description": description,
    }


def get_section_articles(source: dict) -> list[dict]:
    page = fetch(source["url"])
    parser = PageParser(source["url"], source["section"])
    parser.feed(page)
    urls: list[str] = []
    seen: set[str] = set()
    for href, _anchor_title in parser.links:
        normalized = canonicalize(href, source["section"])
        if normalized and normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)
    if not urls:
        raise RuntimeError(f"No se encontraron enlaces de artículos en {source['url']}; se conserva el XML publicado anterior.")

    urls = urls[:MAX_ARTICLES_PER_SECTION]
    articles: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(article_data, url, source["section"]) for url in urls]
        for future in concurrent.futures.as_completed(futures):
            try:
                item = future.result()
            except Exception as exc:
                print(f"Article parse failed: {exc}", file=sys.stderr)
                item = None
            if item:
                articles.append(item)
    articles.sort(key=lambda x: x["published"], reverse=True)
    if not articles:
        raise RuntimeError(f"No se pudieron extraer artículos válidos de {source['url']}; se conserva el XML publicado anterior.")
    return articles


def build_xml(source: dict, articles: list[dict]) -> bytes:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = source["feed_title"]
    ET.SubElement(channel, "link").text = source["url"]
    ET.SubElement(channel, "description").text = source["description"]
    ET.SubElement(channel, "language").text = "es-ES"
    ET.SubElement(channel, "lastBuildDate").text = email.utils.format_datetime(datetime.now(timezone.utc), usegmt=True)
    for article in articles:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = article["title"]
        ET.SubElement(item, "link").text = article["url"]
        guid = ET.SubElement(item, "guid", {"isPermaLink": "true"})
        guid.text = article["url"]
        ET.SubElement(item, "description").text = article["description"] or article["title"]
        ET.SubElement(item, "pubDate").text = email.utils.format_datetime(article["published"], usegmt=True)
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def atomic_write(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(contents)
    temporary.replace(path)


def main() -> None:
    failures = []
    for feed_id, source in SOURCES.items():
        try:
            articles = get_section_articles(source)
            xml_bytes = build_xml(source, articles)
            atomic_write(OUT_DIR / source["file"], xml_bytes)
            print(f"{feed_id}: {len(articles)} articles -> {OUT_DIR / source['file']}")
        except Exception as exc:
            failures.append((feed_id, exc))
            print(f"ERROR {feed_id}: {exc}", file=sys.stderr)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
