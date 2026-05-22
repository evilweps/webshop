# Deals Dashboard — NAS Setup

## Bestanden

```
/
├── index.html       ← de website (laadt deals.json dynamisch)
├── deals.json       ← data, automatisch bijgewerkt door scraper
├── scraper.py       ← draait op de NAS
└── requirements.txt ← Python dependencies
```

## NAS installatie

### 1. Python dependencies
```bash
pip3 install -r requirements.txt
```

### 2. Git repo klonen (als dat nog niet gedaan is)
```bash
git clone https://github.com/JOUW-USERNAME/ryanain.git /volume1/scripts/ryanain
```

### 3. Git credentials instellen
```bash
cd /volume1/scripts/ryanain
git config user.name  "Deals Bot"
git config user.email "bot@ryanain.com"
# Als je HTTPS gebruikt, sla credentials op:
git config credential.helper store
# Doe daarna eenmalig een handmatige push zodat credentials opgeslagen worden
```

### 4. Cron instellen op NAS
Open Synology Task Scheduler (of crontab -e) en voeg toe:

```
# Elke dag om 07:00 en 19:00
0 7,19 * * * cd /volume1/scripts/ryanain && python3 scraper.py >> /volume1/scripts/deals-scraper.log 2>&1
```

Voor Synology DSM via Task Scheduler:
- Taaktype: Geplande taak → Door gebruiker gedefinieerd script
- Schema: Dagelijks, 07:00 + 19:00
- Script: `cd /volume1/scripts/ryanain && python3 scraper.py`

### 5. Eerste run handmatig testen
```bash
cd /volume1/scripts/ryanain
python3 scraper.py
# Kijk of deals.json bijgewerkt is en of de push geslaagd is
cat /volume1/scripts/deals-scraper.log
```

## Hoe het werkt

```
NAS (cron 2x/dag)
  └── scraper.py
        ├── scrapt bol.com deals/trending/bestsellers
        ├── scrapt amazon.nl / .com.be / .de (indien niet geblokkeerd)
        ├── schrijft deals.json
        └── git commit + push → GitHub
                                    └── GitHub Pages serveert index.html
                                              └── fetch('./deals.json') → laadt verse data
```

## Fallback

Als Amazon scrapen mislukt (ze blokkeren bots vaak), blijft de **vorige data** staan.
bol.com is veel toegankelijker en zal doorgaans altijd werken.

## Log controleren
```bash
tail -f /volume1/scripts/deals-scraper.log
```
