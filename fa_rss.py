#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


SOURCES = {
    "movistar": {
        "title": "Estrenos Movistar Plus+ - FilmAffinity",
        "url": "https://www.filmaffinity.com/es/cat_new_movistar_f.html",
        "id": "new_movistar_f",
    },
    "filmin": {
        "title": "Estrenos Filmin - FilmAffinity",
        "url": "https://www.filmaffinity.com/es/cat_new_filmin.html",
        "id": "new_filmin",
    },
    "prime-video": {
        "title": "Estrenos Prime Video España - FilmAffinity",
        "url": "https://www.filmaffinity.com/es/rdcat.php?id=new_amazon_es",
        "id": "new_amazon_es",
    },
    "max-hbo": {
        "title": "Estrenos HBO Max / Max España - FilmAffinity",
        "url": "https://www.filmaffinity.com/es/cat_new_hbo_es.html",
        "id": "new_hbo_es",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
}


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fetch(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def is_date(text: str) -> bool:
    t = clean(text).lower()
    return bool(
        re.match(r"^\d{1,2}\s+[a-záéíóúñ]{3,}\.?$", t)
        or re.match(r"^\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}$", t)
        or t == "hoy"
    )


def is_real_film_link(href: str | None) -> bool:
    return bool(href and re.search(r"/film\d+\.html", href))


def find_results_area(soup: BeautifulSoup, source_id: str):
    """
    Intenta localizar la zona real de resultados.
    FilmAffinity mete muchos menús antes, así que NO recorremos toda la página.
    """
    # En muchas páginas, la pestaña activa apunta al id de categoría.
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if source_id in href:
            parent = a
            for _ in range(8):
                parent = parent.parent
                if parent is None:
                    break
                links = parent.find_all("a", href=True)
                film_links = [x for x in links if is_real_film_link(x.get("href"))]
                if len(film_links) >= 3:
                    return parent

    # Fallback: busca el contenedor más pequeño con varias fichas /film123.html
    candidates = []
    for tag in soup.find_all(["div", "section", "main", "table"]):
        film_links = [a for a in tag.find_all("a", href=True) if is_real_film_link(a.get("href"))]
        if len(film_links) >= 3:
            candidates.append((len(str(tag)), tag))

    if candidates:
        return sorted(candidates, key=lambda x: x[0])[0][1]

    return soup


def extract_items(soup: BeautifulSoup, page_url: str, source_id: str, max_items: int = 80) -> list[dict]:
    area = find_results_area(soup, source_id)

    items = []
    seen = set()
    pending_date_by_url = {}
    current_date = ""

    for a in area.find_all("a", href=True):
        text = clean(a.get_text(" "))
        href = a.get("href")

        if not text:
            continue

        if not is_real_film_link(href):
            continue

        link = urljoin(page_url, href)

        if is_date(text):
            current_date = text
            pending_date_by_url[link] = text
            continue

        if link in seen:
            continue

        seen.add(link)
        date_label = pending_date_by_url.get(link, current_date)

        title = f"{text} — {date_label}" if date_label else text
        items.append({
            "title": title,
            "link": link,
            "description": f"Estreno/incorporación en plataforma según FilmAffinity{(' — ' + date_label) if date_label else ''}",
        })

        if len(items) >= max_items:
            break

    return items


def rss_xml(channel_title: str, channel_link: str, items: list[dict]) -> str:
    now = format_datetime(datetime.now(timezone.utc))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        '<channel>',
        f'<title>{html.escape(channel_title)}</title>',
        f'<link>{html.escape(channel_link)}</link>',
        f'<description>{html.escape(channel_title)}</description>',
        f'<lastBuildDate>{now}</lastBuildDate>',
    ]

    for item in items:
        lines += [
            "<item>",
            f"<title>{html.escape(item['title'])}</title>",
            f"<link>{html.escape(item['link'])}</link>",
            f"<guid isPermaLink=\"true\">{html.escape(item['link'])}</guid>",
            f"<description>{html.escape(item['description'])}</description>",
            f"<pubDate>{now}</pubDate>",
            "</item>",
        ]

    lines += ["</channel>", "</rss>"]
    return "\n".join(lines)


def main() -> None:
    out_dir = Path("feeds")
    out_dir.mkdir(exist_ok=True)

    for slug, cfg in SOURCES.items():
        print(f"Generando {slug}...")
        soup = fetch(cfg["url"])
        items = extract_items(soup, cfg["url"], cfg["id"])

        if not items:
            raise RuntimeError(f"No se encontraron títulos para {slug}")

        out_file = out_dir / f"{slug}.xml"
        out_file.write_text(rss_xml(cfg["title"], cfg["url"], items), encoding="utf-8")
        print(f"OK: {out_file} ({len(items)} items)")


if __name__ == "__main__":
    main()
