import re
import html
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from email.utils import format_datetime
from datetime import datetime, timezone


SOURCES = {
    "elcorreoweb-sevilla": {
        "url": "https://www.elcorreoweb.es/sevilla/",
        "title": "El Correo de Andalucía - Sevilla",
        "description": "Últimas noticias de Sevilla - El Correo de Andalucía",
        "section": "sevilla",
    },
    "elcorreoweb-andalucia": {
        "url": "https://www.elcorreoweb.es/andalucia",
        "title": "El Correo de Andalucía - Andalucía",
        "description": "Últimas noticias de Andalucía - El Correo de Andalucía",
        "section": "andalucia",
    },
}


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )
}


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def get_articles(source):
    response = requests.get(
        source["url"],
        headers=HEADERS,
        timeout=30
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    articles = []
    seen = set()

    pattern = re.compile(
        rf"/{re.escape(source['section'])}/\d{{4}}/\d{{2}}/\d{{2}}/[^\"']+\.html"
    )

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()

        if not pattern.search(href):
            continue

        url = urljoin(source["url"], href)

        if url in seen:
            continue

        title = clean_text(a.get_text(" ", strip=True))

        if not title or len(title) < 8:
            continue

        seen.add(url)

        # Fecha aproximada tomada de la propia URL del artículo
        match = re.search(
            rf"/{re.escape(source['section'])}/(\d{{4}})/(\d{{2}})/(\d{{2}})/",
            url
        )

        if match:
            year, month, day = map(int, match.groups())
            pub_date = datetime(
                year, month, day,
                0, 0, 0,
                tzinfo=timezone.utc
            )
        else:
            pub_date = datetime.now(timezone.utc)

        articles.append({
            "title": title,
            "url": url,
            "pub_date": pub_date,
        })

        if len(articles) >= 30:
            break

    return articles


def make_rss(source, articles):
    now = format_datetime(datetime.now(timezone.utc), usegmt=True)

    items = []

    for article in articles:
        title = html.escape(article["title"])
        url = html.escape(article["url"], quote=True)
        pub_date = format_datetime(article["pub_date"], usegmt=True)

        items.append(
            f"""    <item>
      <title>{title}</title>
      <link>{url}</link>
      <guid isPermaLink="true">{url}</guid>
      <description>{html.escape(source["description"])}</description>
      <pubDate>{pub_date}</pubDate>
    </item>"""
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{html.escape(source["title"])}</title>
    <link>{html.escape(source["url"], quote=True)}</link>
    <description>{html.escape(source["description"])}</description>
    <language>es-ES</language>
    <lastBuildDate>{now}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
"""


def main():
    import os

    os.makedirs("feeds", exist_ok=True)

    for key, source in SOURCES.items():
        print(f"Procesando: {source['url']}")

        try:
            articles = get_articles(source)

            print(f"  Artículos encontrados: {len(articles)}")

            if not articles:
                print("  AVISO: no se encontraron artículos.")
                continue

            rss = make_rss(source, articles)

            filename = f"feeds/{key}.xml"

            with open(filename, "w", encoding="utf-8") as f:
                f.write(rss)

            print(f"  Generado: {filename}")

        except Exception as e:
            print(f"  ERROR: {e}")


if __name__ == "__main__":
    main()
