#!/usr/bin/env python3
"""
Deals Dashboard Scraper — v3
Cron: 0 7,19 * * * cd /volume1/Documenten/webshop && python3 scraper.py >> /volume1/Documenten/webshop/scraper.log 2>&1
"""
import json, os, subprocess, time, re, random, logging
from datetime import datetime, timezone
from typing import Optional
import requests
from bs4 import BeautifulSoup

REPO_DIR    = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(REPO_DIR, "deals.json")
GIT_USER    = "Deals Bot"
GIT_EMAIL   = "bot@ryanain.com"

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)

UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

def make_session(referer=""):
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(UA),
        "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer, "DNT": "1",
    })
    return s

def fetch(url, s, timeout=20):
    try:
        time.sleep(random.uniform(1.5, 3.0))
        r = s.get(url, timeout=timeout, allow_redirects=True)
        log.info(f"  GET {url} → {r.status_code} ({len(r.text):,} bytes)")
        if r.status_code == 200:
            return BeautifulSoup(r.text, "lxml")
        log.warning(f"  HTTP {r.status_code}")
    except Exception as e:
        log.warning(f"  Fout: {e}")
    return None

def clean_price(t):
    t = (t or "").strip().replace("\xa0"," ").replace("  "," ")
    return ("€"+t) if t and not t.startswith("€") else t

def calc_disc(now_s, was_s):
    def n(s):
        m = re.search(r"[\d,.]+", (s or "").replace(".","").replace(",","."))
        return float(m.group()) if m else 0.0
    try:
        a, b = n(now_s), n(was_s)
        if b > a > 0: return round((b-a)/b*100)
    except: pass
    return 0

def fallback(key, section):
    try:
        if os.path.exists(OUTPUT_FILE):
            items = json.load(open(OUTPUT_FILE)).get("stores",{}).get(key,{}).get(section,[])
            if items: log.info(f"  Fallback: {len(items)} items uit vorige run")
            return items
    except: pass
    return []

def q(name): return requests.utils.quote((name or "").replace("™","").replace("®","").strip()[:50])

# ─── BOL.COM ──────────────────────────────────────────────────────────────────
def bol_deals():
    log.info("─── bol.com deals ───")
    s    = make_session("https://www.bol.com/")
    soup = fetch("https://www.bol.com/nl/nl/deals/", s)
    if not soup: return []
    out, seen = [], set()

    # Methode 1: data-test selectors
    for el in soup.select("[data-test='product-title']"):
        name = el.get_text(strip=True)
        if not name or len(name) < 5 or name in seen: continue
        seen.add(name)
        card      = el.find_parent("li") or el.find_parent("article") or el.find_parent("div")
        price_el  = card.select_one("[data-test='price']") if card else None
        was_el    = card.select_one("[data-test='from-price']") if card else None
        link_el   = card.select_one("a[href*='/p/']") if card else None
        price     = clean_price(price_el.get_text(strip=True)) if price_el else ""
        was       = clean_price(was_el.get_text(strip=True))   if was_el   else ""
        href      = link_el["href"] if link_el and link_el.get("href") else ""
        if href and not href.startswith("http"): href = "https://www.bol.com" + href
        out.append({"n": name[:80], "c": "Aanbieding", "p": price, "w": was,
                    "d": calc_disc(price, was), "u": href or f"https://www.bol.com/nl/nl/s/?searchtext={q(name)}"})

    # Methode 2: alle /p/ links als fallback
    if not out:
        for a in soup.select("a[href*='/p/']"):
            name = a.get_text(strip=True)
            if not name or len(name) < 8 or name in seen: continue
            if any(x in name.lower() for x in ["login","account","winkelwagen","meer","bekijk"]): continue
            seen.add(name)
            href = a["href"]
            if not href.startswith("http"): href = "https://www.bol.com" + href
            parent    = a.find_parent("li") or a.find_parent("article")
            price_str = ""
            if parent:
                pm = re.search(r"€\s*\d+[,.]?\d*", parent.get_text())
                if pm: price_str = pm.group().replace(" ","")
            out.append({"n": name[:80], "c": "Aanbieding", "p": price_str, "w": "", "d": 0, "u": href})
            if len(out) >= 50: break

    if not out:
        # Debug: sla HTML op
        open(os.path.join(REPO_DIR, "debug_bol_deals.html"), "w").write(soup.prettify())
        log.warning("  0 items — debug_bol_deals.html opgeslagen")

    log.info(f"  bol.com deals: {len(out)} items")
    return out[:50]


def bol_list(label):
    log.info(f"─── bol.com {label} ───")
    s = make_session("https://www.bol.com/")

    urls = {
        "Bestsellers": [
            "https://www.bol.com/nl/nl/l/top-100/N/8299+0/",
            "https://www.bol.com/nl/nl/l/top-100/",
            "https://www.bol.com/nl/nl/zoekresultaten/?sort=ranking&searchtext=boeken",
        ],
        "Trending": [
            "https://www.bol.com/nl/nl/l/meest-bekeken/",
            "https://www.bol.com/nl/nl/l/nieuw/",
            "https://www.bol.com/nl/nl/zoekresultaten/?sort=relevance&searchtext=elektronica",
        ],
    }

    soup = None
    for url in urls.get(label, []):
        soup = fetch(url, s)
        if soup: break
    if not soup: return []

    out, seen = [], set()
    for el in soup.select("[data-test='product-title']"):
        name = el.get_text(strip=True)
        if name and len(name) > 5 and name not in seen:
            seen.add(name); out.append({"n": name[:80], "c": label})

    if not out:
        for a in soup.select("a[href*='/p/']"):
            name = a.get_text(strip=True)
            if not name or len(name) < 8 or name in seen: continue
            if any(x in name.lower() for x in ["login","account","winkelwagen","meer","bekijk"]): continue
            seen.add(name); out.append({"n": name[:80], "c": label})
            if len(out) >= 50: break

    log.info(f"  bol.com {label}: {len(out)} items")
    return out[:50]


# ─── AMAZON ───────────────────────────────────────────────────────────────────
def amz_deals(domain, lang):
    log.info(f"─── amazon.{domain} deals ───")
    base = f"https://www.amazon.{domain}"
    s    = make_session(base)
    out, seen = [], set()

    urls = [f"{base}/{lang}/gp/goldbox" if lang else f"{base}/gp/goldbox",
            f"{base}/{lang}/deals"       if lang else f"{base}/deals"]
    soup = None
    for url in urls:
        soup = fetch(url, s)
        if soup and len(soup.find_all("span")) > 10: break
        soup = None
    if not soup: return []

    # Probeer meerdere selector-strategieën
    cards = (soup.select("[data-testid='deal-card']") or
             soup.select("[class*='DealCard']") or
             soup.select("[data-asin]") or
             soup.select("[data-component-type='s-search-result']"))

    for card in cards[:80]:
        try:
            asin = card.get("data-asin","")
            name_el = (card.select_one("span.a-text-normal") or
                       card.select_one("h2 a span") or
                       card.select_one("[class*='truncate']") or
                       card.select_one(".a-size-base-plus") or
                       card.select_one(".a-size-medium"))
            name = name_el.get_text(strip=True) if name_el else ""
            if not name or len(name) < 5 or name in seen: continue
            seen.add(name)
            price_el = (card.select_one("span.a-price .a-offscreen") or
                        card.select_one(".a-price-whole"))
            was_el   = card.select_one("span.a-text-price .a-offscreen")
            link_el  = card.select_one("a[href*='/dp/']") or card.select_one("h2 a")
            price = clean_price(price_el.get_text(strip=True)) if price_el else ""
            was   = clean_price(was_el.get_text(strip=True))   if was_el   else ""
            href  = link_el["href"] if link_el and link_el.get("href") else ""
            if href and not href.startswith("http"): href = base + href
            if not href and asin: href = f"{base}/dp/{asin}"
            out.append({"n": name[:80], "c": "Aanbieding", "p": price, "w": was,
                        "d": calc_disc(price, was), "u": href or f"{base}/s?k={q(name)}"})
        except: continue

    log.info(f"  amazon.{domain} deals: {len(out)} items")
    return out[:50]


def amz_list(domain, lang, soort):
    log.info(f"─── amazon.{domain} {soort} ───")
    base = f"https://www.amazon.{domain}"
    s    = make_session(base)

    cats = ([("","Algemeen"),("electronics","Elektronica"),("kitchen","Keuken"),
             ("sporting-goods","Sport"),("beauty","Beauty"),("toys","Speelgoed"),
             ("books","Boeken"),("home-garden","Huis & Tuin")]
            if soort == "bestsellers" else [("","Trending")])

    seen, out = set(), []
    for cat_slug, cat_label in cats:
        if soort == "bestsellers":
            url = (f"{base}/{lang}/gp/bestsellers/{cat_slug}" if cat_slug
                   else f"{base}/{lang}/gp/bestsellers" if lang
                   else f"{base}/gp/bestsellers")
        else:
            url = (f"{base}/{lang}/gp/movers-and-shakers" if lang
                   else f"{base}/gp/movers-and-shakers")

        soup = fetch(url, s)
        if not soup: continue

        # Robuuste aanpak: zoek alle /dp/ links met tekst
        for a in soup.select("a[href*='/dp/']"):
            # Pak de langste tekstnode dichtbij (productnaam)
            spans = a.select("span")
            name  = ""
            for sp in spans:
                t = sp.get_text(strip=True)
                if len(t) > len(name) and len(t) > 8: name = t
            if not name:
                name = a.get_text(strip=True)
            name = name.strip()
            if not name or len(name) < 8 or name in seen: continue
            if any(x in name.lower() for x in ["klanten","beoordelingen","ster","star","review","€","kopen","klik"]): continue
            seen.add(name)
            out.append({"n": name[:80], "c": cat_label})
            if len(out) >= 50: break

        if len(out) >= 50: break
        time.sleep(random.uniform(0.8, 1.5))

    log.info(f"  amazon.{domain} {soort}: {len(out)} items")
    return out[:50]


# ─── GIT ──────────────────────────────────────────────────────────────────────
def git_push():
    env = os.environ.copy()
    env.update({"GIT_AUTHOR_NAME": GIT_USER, "GIT_AUTHOR_EMAIL": GIT_EMAIL,
                "GIT_COMMITTER_NAME": GIT_USER, "GIT_COMMITTER_EMAIL": GIT_EMAIL,
                # Zorg dat git nooit interactief om credentials vraagt
                "GIT_TERMINAL_PROMPT": "0"})

    # credential helper instellen
    subprocess.run(["git","-C",REPO_DIR,"config","credential.helper","store"],
                   capture_output=True, env=env)

    msg = f"deals: auto-update {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    for cmd in [
        ["git","-C",REPO_DIR,"add","deals.json"],
        ["git","-C",REPO_DIR,"commit","-m", msg],
        ["git","-C",REPO_DIR,"push","--no-verify"],
    ]:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
        out = (r.stdout + r.stderr).strip()
        if r.returncode != 0:
            if "nothing to commit" in out:
                log.info("git: niets te committen"); return
            log.error(f"git fout ({' '.join(cmd[-2:])}): {out}")
            raise RuntimeError(out)
        if out: log.info(f"git: {out[:150]}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    log.info("═══════════════════════════════════")
    log.info("  Deals scraper v3 gestart")
    log.info("═══════════════════════════════════")
    now    = datetime.now(timezone.utc)
    stores = {}

    # bol.com
    stores["bol"] = {
        "name":"bol.com", "url":"https://www.bol.com/nl/nl/deals/",
        "bsUrl":"https://www.bol.com/nl/nl/l/top-100/N/8299+0/",
        "badge":"Live gescraped", "badgeBg":"#fde8e8", "badgeTxt":"#b91c1c",
        "note": f"bol.com — gescraped {now.strftime('%-d %b %Y %H:%M')} UTC",
        "deals":       bol_deals()      or fallback("bol","deals"),
        "trending":    bol_list("Trending")    or fallback("bol","trending"),
        "bestsellers": bol_list("Bestsellers") or fallback("bol","bestsellers"),
    }

    # Amazon
    for domain, lang, key, name, bg, txt in [
        ("nl",     "-/nl", "amz_nl", "amazon.nl",     "#d1fae5", "#065f46"),
        ("com.be", "-/nl", "amz_be", "amazon.com.be", "#fff3cd", "#92400e"),
        ("de",     "",     "amz_de", "amazon.de",     "#dbeafe", "#1e40af"),
    ]:
        base = f"https://www.amazon.{domain}"
        stores[key] = {
            "name": name,
            "url":  f"{base}/{lang}/events/deals" if lang else f"{base}/deals",
            "bsUrl": f"{base}/{lang}/gp/bestsellers" if lang else f"{base}/gp/bestsellers",
            "badge":"Live data", "badgeBg":bg, "badgeTxt":txt,
            "note": f"{name} — gescraped {now.strftime('%-d %b %Y %H:%M')} UTC",
            "deals":       amz_deals(domain, lang) or fallback(key,"deals"),
            "trending":    amz_list(domain, lang, "trending")    or fallback(key,"trending"),
            "bestsellers": amz_list(domain, lang, "bestsellers") or fallback(key,"bestsellers"),
        }

    # Schrijf JSON
    output = {"updated": now.isoformat(),
              "updated_fmt": now.strftime("%-d %B %Y om %H:%M"),
              "stores": stores}
    with open(OUTPUT_FILE,"w",encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log.info(f"deals.json geschreven ({os.path.getsize(OUTPUT_FILE)//1024} KB)")

    # Samenvatting
    log.info("─── Resultaat ───────────────────────")
    for k, s in stores.items():
        log.info(f"  {s['name']:15}  deals={len(s['deals']):2}  trending={len(s['trending']):2}  best={len(s['bestsellers']):2}")

    git_push()
    log.info("═══ Klaar ═══")

if __name__ == "__main__":
    main()
