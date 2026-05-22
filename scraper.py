#!/usr/bin/env python3
"""
Deals Dashboard Scraper
Draait op NAS via cron, scrapt bol.com + Amazon, schrijft deals.json, pusht naar GitHub.

Vereisten:
  pip install requests beautifulsoup4 lxml

Cron (dagelijks om 07:00):
  0 7 * * * cd /path/to/repo && python3 scraper.py >> /var/log/deals-scraper.log 2>&1
"""

import json
import os
import subprocess
import sys
import time
import re
import random
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ─── CONFIG ──────────────────────────────────────────────────────────────────
REPO_DIR     = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE  = os.path.join(REPO_DIR, "deals.json")
GIT_USER     = "Deals Bot"
GIT_EMAIL    = "bot@ryanain.com"
LOG_LEVEL    = logging.INFO

# ─── LOGGING ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── HTTP HELPERS ─────────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

def make_session(referer: str = "") -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "DNT": "1",
    })
    return s

def safe_get(url: str, session: requests.Session, timeout: int = 15) -> Optional[BeautifulSoup]:
    try:
        time.sleep(random.uniform(1.2, 2.8))
        r = session.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return BeautifulSoup(r.text, "lxml")
        log.warning(f"HTTP {r.status_code} for {url}")
    except Exception as e:
        log.warning(f"Request failed {url}: {e}")
    return None

# ─── PRICE HELPERS ────────────────────────────────────────────────────────────
def clean_price(txt: str) -> str:
    txt = txt.strip().replace("\xa0", " ").replace("  ", " ")
    if txt and not txt.startswith("€"):
        txt = "€" + txt
    return txt

def calc_discount(now_str: str, was_str: str) -> int:
    def extract(s):
        m = re.search(r"[\d,.]+", s.replace(".", "").replace(",", "."))
        return float(m.group()) if m else 0.0
    try:
        now = extract(now_str)
        was = extract(was_str)
        if was > 0 and now > 0 and was > now:
            return round((was - now) / was * 100)
    except Exception:
        pass
    return 0

# ─── BOL.COM SCRAPER ─────────────────────────────────────────────────────────
def scrape_bol_deals() -> list:
    log.info("Scraping bol.com deals …")
    results = []
    session = make_session("https://www.bol.com/")

    # Main deals page
    soup = safe_get("https://www.bol.com/nl/nl/deals/", session)
    if not soup:
        log.warning("bol.com deals page unreachable")
        return results

    # Product tiles — multiple possible selectors across redesigns
    tiles = (
        soup.select("[data-test='product-title']") or
        soup.select(".product-item--title") or
        soup.select("[class*='product-title']") or
        soup.select("article [data-test='product']")
    )

    for tile in tiles[:60]:
        try:
            # Name
            name_el = (
                tile.select_one("[data-test='product-title']") or
                tile.select_one(".product-item--title") or
                tile
            )
            name = name_el.get_text(strip=True) if name_el else ""
            if not name or len(name) < 4:
                continue

            # Prices
            price_el = tile.select_one("[data-test='price']") or tile.select_one(".promo-price")
            was_el   = tile.select_one("[data-test='from-price']") or tile.select_one(".price--old")
            price    = clean_price(price_el.get_text(strip=True)) if price_el else ""
            was      = clean_price(was_el.get_text(strip=True))   if was_el   else ""
            disc     = calc_discount(price, was) if was else 0

            # URL
            link_el = tile.select_one("a[href*='/p/']") or tile.find_parent("a")
            href    = link_el["href"] if link_el and link_el.get("href") else ""
            if href and not href.startswith("http"):
                href = "https://www.bol.com" + href

            # Category (breadcrumb or parent element text)
            cat_el  = tile.select_one("[data-test='product-category']") or tile.select_one(".breadcrumbs__item:last-child")
            cat     = cat_el.get_text(strip=True) if cat_el else "Aanbieding"

            results.append({
                "n": name[:80],
                "c": cat[:30],
                "p": price,
                "w": was,
                "d": disc,
                "u": href or f"https://www.bol.com/nl/nl/s/?searchtext={requests.utils.quote(name[:40])}"
            })
        except Exception as e:
            log.debug(f"bol tile parse error: {e}")
            continue

    log.info(f"  bol.com deals: {len(results)} items")
    return results[:50]


def scrape_bol_section(url: str, label: str) -> list:
    log.info(f"Scraping bol.com {label} …")
    results = []
    session = make_session("https://www.bol.com/")
    soup    = safe_get(url, session)
    if not soup:
        return results

    tiles = (
        soup.select("[data-test='product-title']") or
        soup.select(".product-item--title") or
        soup.select("[class*='product-title']")
    )
    for tile in tiles[:50]:
        try:
            name = tile.get_text(strip=True)
            if not name or len(name) < 4:
                continue
            cat_el = tile.select_one("[data-test='product-category']")
            cat    = cat_el.get_text(strip=True) if cat_el else label
            results.append({"n": name[:80], "c": cat[:30]})
        except Exception:
            continue

    log.info(f"  bol.com {label}: {len(results)} items")
    return results[:50]


# ─── AMAZON SCRAPER ───────────────────────────────────────────────────────────
def scrape_amazon_deals(domain: str, lang_prefix: str) -> list:
    """
    Try to scrape Amazon deals page. Amazon heavily blocks bots,
    so we try a few approaches and fall back gracefully.
    """
    log.info(f"Scraping amazon.{domain} deals …")
    results  = []
    base_url = f"https://www.amazon.{domain}"
    session  = make_session(base_url)
    session.headers["Accept-Language"] = "nl-NL,nl;q=0.9,de;q=0.8,en;q=0.7"

    urls_to_try = [
        f"{base_url}/{lang_prefix}/gp/goldbox",
        f"{base_url}/{lang_prefix}/deals",
        f"{base_url}/gp/deals/ajax-loadMore?dealType=LIGHTNING_DEAL",
    ]

    soup = None
    for url in urls_to_try:
        soup = safe_get(url, session)
        if soup and len(soup.find_all("span")) > 20:
            break
        soup = None

    if not soup:
        log.warning(f"  amazon.{domain} blocked/unreachable — using cached fallback")
        return []

    # Try multiple deal card selectors
    cards = (
        soup.select("[data-testid='deal-card']") or
        soup.select("[class*='DealCard']") or
        soup.select("[data-component-type='s-search-result']") or
        soup.select(".a-section.a-spacing-base")
    )

    for card in cards[:60]:
        try:
            # Name
            name_el = (
                card.select_one("span.a-text-normal") or
                card.select_one("h2 a span") or
                card.select_one("[class*='truncate']") or
                card.select_one(".a-size-base-plus")
            )
            name = name_el.get_text(strip=True) if name_el else ""
            if not name or len(name) < 4:
                continue

            # Price
            price_el = (
                card.select_one("span.a-price .a-offscreen") or
                card.select_one("span.a-price-whole") or
                card.select_one("[class*='price']")
            )
            was_el = (
                card.select_one("span.a-text-price .a-offscreen") or
                card.select_one("[data-a-strike='true']")
            )
            price = clean_price(price_el.get_text(strip=True)) if price_el else ""
            was   = clean_price(was_el.get_text(strip=True))   if was_el   else ""
            disc  = calc_discount(price, was) if was else 0

            # Discount badge
            badge_el = card.select_one(".a-badge-text") or card.select_one("[class*='discount']")
            if badge_el and disc == 0:
                m = re.search(r"(\d+)", badge_el.get_text())
                if m:
                    disc = int(m.group(1))

            # URL
            link_el = card.select_one("a[href*='/dp/']") or card.select_one("h2 a")
            href    = link_el["href"] if link_el and link_el.get("href") else ""
            if href and not href.startswith("http"):
                href = base_url + href
            if not href:
                q    = requests.utils.quote(name[:40])
                href = f"{base_url}/{lang_prefix}/s?k={q}"

            # Category
            cat_el = card.select_one("[data-component-id='categoriesRefinements']") or card.select_one(".a-color-secondary")
            cat    = cat_el.get_text(strip=True)[:30] if cat_el else "Aanbieding"

            results.append({
                "n": name[:80], "c": cat,
                "p": price, "w": was, "d": disc, "u": href
            })
        except Exception as e:
            log.debug(f"amazon.{domain} card parse error: {e}")

    log.info(f"  amazon.{domain} deals: {len(results)} items scraped")
    return results[:50]


def scrape_amazon_list(domain: str, lang_prefix: str, list_type: str) -> list:
    """Scrape Amazon bestsellers or movers & shakers."""
    log.info(f"Scraping amazon.{domain} {list_type} …")
    results  = []
    base_url = f"https://www.amazon.{domain}"
    session  = make_session(base_url)

    # Bestsellers across main categories
    categories = [
        ("", ""),       # root
        ("electronics", "Elektronica"),
        ("kitchen",     "Keuken"),
        ("sporting-goods", "Sport"),
        ("beauty",      "Beauty"),
        ("toys",        "Speelgoed"),
    ] if list_type == "bestsellers" else [("", "")]

    seen = set()
    for cat_slug, cat_label in categories:
        if list_type == "bestsellers":
            url = f"{base_url}/{lang_prefix}/gp/bestsellers/{cat_slug}" if cat_slug else f"{base_url}/{lang_prefix}/gp/bestsellers"
        else:
            url = f"{base_url}/{lang_prefix}/gp/movers-and-shakers"

        soup = safe_get(url, session)
        if not soup:
            continue

        items = (
            soup.select("#gridItemRoot") or
            soup.select(".zg-item-immersion") or
            soup.select("[class*='_cDEzb_grid-cell']") or
            soup.select(".p13n-sc-uncoverable-faceout")
        )

        for item in items:
            try:
                name_el = (
                    item.select_one("._cDEzb_p13n-sc-css-line-clamp-3") or
                    item.select_one(".p13n-sc-line-clamp-2") or
                    item.select_one("span.zg-text-center-align") or
                    item.select_one("a .a-text-normal") or
                    item.select_one("span.a-size-small")
                )
                name = name_el.get_text(strip=True) if name_el else ""
                if not name or len(name) < 4 or name in seen:
                    continue
                seen.add(name)

                cat = cat_label or "Bestseller"
                results.append({"n": name[:80], "c": cat})
            except Exception:
                continue

        if len(results) >= 50:
            break
        time.sleep(random.uniform(0.8, 1.5))

    log.info(f"  amazon.{domain} {list_type}: {len(results)} items")
    return results[:50]


# ─── FALLBACK DATA ────────────────────────────────────────────────────────────
def load_fallback(output_file: str, store_key: str, section: str) -> list:
    """Return previous data from deals.json if scraping fails."""
    try:
        if os.path.exists(output_file):
            with open(output_file) as f:
                old = json.load(f)
            return old.get("stores", {}).get(store_key, {}).get(section, [])
    except Exception:
        pass
    return []


# ─── GIT PUSH ─────────────────────────────────────────────────────────────────
def git_push(repo_dir: str, message: str):
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"]     = GIT_USER
    env["GIT_AUTHOR_EMAIL"]    = GIT_EMAIL
    env["GIT_COMMITTER_NAME"]  = GIT_USER
    env["GIT_COMMITTER_EMAIL"] = GIT_EMAIL

    cmds = [
        ["git", "-C", repo_dir, "add", "deals.json"],
        ["git", "-C", repo_dir, "commit", "-m", message],
        ["git", "-C", repo_dir, "push"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            # "nothing to commit" is not a real error
            if "nothing to commit" in result.stdout + result.stderr:
                log.info("git: nothing to commit, skipping push")
                return
            log.error(f"git error: {result.stderr.strip()}")
            raise RuntimeError(f"git command failed: {' '.join(cmd)}")
        log.info(f"git: {result.stdout.strip() or 'ok'}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    log.info("═══ Deals scraper gestart ═══")
    now = datetime.now(timezone.utc)

    stores_data = {}

    # ── bol.com ──────────────────────────────────────────────────────────────
    bol_deals = scrape_bol_deals()
    if not bol_deals:
        log.warning("bol.com deals: scrape mislukt, gebruik fallback")
        bol_deals = load_fallback(OUTPUT_FILE, "bol", "deals")

    bol_trending = scrape_bol_section(
        "https://www.bol.com/nl/nl/l/populaire-producten/", "Trending")
    if not bol_trending:
        bol_trending = load_fallback(OUTPUT_FILE, "bol", "trending")

    bol_best = scrape_bol_section(
        "https://www.bol.com/nl/nl/l/bestsellers/", "Bestsellers")
    if not bol_best:
        bol_best = load_fallback(OUTPUT_FILE, "bol", "bestsellers")

    stores_data["bol"] = {
        "name": "bol.com",
        "url": "https://www.bol.com/nl/nl/deals/",
        "bsUrl": "https://www.bol.com/nl/nl/l/bestsellers/",
        "badge": "Live gescraped",
        "badgeBg": "#fde8e8", "badgeTxt": "#b91c1c",
        "note": f"bol.com — live gescraped op {now.strftime('%d %b %Y %H:%M')} UTC",
        "deals": bol_deals,
        "trending": bol_trending,
        "bestsellers": bol_best,
    }

    # ── amazon.nl ─────────────────────────────────────────────────────────────
    for domain, lang, key, name, badge_bg, badge_txt in [
        ("nl",      "-/nl",  "amz_nl", "amazon.nl",     "#d1fae5", "#065f46"),
        ("com.be",  "-/nl",  "amz_be", "amazon.com.be", "#fff3cd", "#92400e"),
        ("de",      "",      "amz_de", "amazon.de",     "#dbeafe", "#1e40af"),
    ]:
        deals   = scrape_amazon_deals(domain, lang)
        best    = scrape_amazon_list(domain, lang, "bestsellers")
        trend   = scrape_amazon_list(domain, lang, "trending")

        if not deals:
            deals = load_fallback(OUTPUT_FILE, key, "deals")
        if not best:
            best  = load_fallback(OUTPUT_FILE, key, "bestsellers")
        if not trend:
            trend = load_fallback(OUTPUT_FILE, key, "trending")

        base = f"https://www.amazon.{domain}"
        stores_data[key] = {
            "name": name,
            "url":  f"{base}/{lang}/events/deals" if lang else f"{base}/deals",
            "bsUrl": f"{base}/{lang}/gp/bestsellers" if lang else f"{base}/gp/bestsellers",
            "badge": "Live data",
            "badgeBg": badge_bg, "badgeTxt": badge_txt,
            "note": f"{name} — gescraped op {now.strftime('%d %b %Y %H:%M')} UTC · klik door voor live prijzen",
            "deals":       deals,
            "trending":    trend,
            "bestsellers": best,
        }

    # ── Schrijf JSON ──────────────────────────────────────────────────────────
    output = {
        "updated":     now.isoformat(),
        "updated_fmt": now.strftime("%-d %B %Y om %H:%M"),
        "stores":      stores_data,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log.info(f"deals.json geschreven ({os.path.getsize(OUTPUT_FILE) // 1024} KB)")

    # ── Git commit + push ─────────────────────────────────────────────────────
    commit_msg = f"deals: auto-update {now.strftime('%Y-%m-%d %H:%M')} UTC"
    git_push(REPO_DIR, commit_msg)

    log.info("═══ Scraper klaar ═══")


if __name__ == "__main__":
    main()
