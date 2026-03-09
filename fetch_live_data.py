#!/usr/bin/env python3
"""
Inflection OS - Live Data Fetcher
Fetches all 7 domain APIs (free, no keys) and writes data.json to GitHub.
"""
import json, os, base64, re, urllib.request, urllib.error, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO      = "hr185882-creator/inflection-point-research"
FILE_PATH = "data.json"
BRANCH    = "main"

def fetch_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "InflectionOS/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  [WARN] fetch_json {url[:60]} -> {e}")
        return None

def fetch_text(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "InflectionOS/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [WARN] fetch_text {url[:60]} -> {e}")
        return None

def parse_rss(xml_str, max_items=5):
    if not xml_str:
        return []
    try:
        root = ET.fromstring(xml_str)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = []
        for item in root.findall(".//item")[:max_items]:
            t = item.findtext("title", "").strip()
            l = item.findtext("link", "").strip()
            p = item.findtext("pubDate", "").strip()
            if t:
                items.append({"title": t, "link": l, "published": p})
        if not items:
            for entry in root.findall(".//atom:entry", ns)[:max_items]:
                t = entry.findtext("atom:title", "", ns).strip()
                l_el = entry.find("atom:link", ns)
                l = l_el.get("href", "") if l_el is not None else ""
                p = entry.findtext("atom:updated", "", ns).strip()
                if t:
                    items.append({"title": t, "link": l, "published": p})
        return items
    except Exception as e:
        print(f"  [WARN] parse_rss -> {e}")
        return []

def yahoo_quote(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?interval=1d&range=1d"
    data = fetch_json(url)
    if not data:
        return None
    try:
        meta  = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        prev  = meta.get("chartPreviousClose") or meta.get("previousClose")
        change = round(price - prev, 4) if price and prev else None
        pct    = round((change / prev) * 100, 2) if change and prev else None
        return {"price": price, "prev_close": prev, "change": change, "change_pct": pct, "currency": meta.get("currency", "USD")}
    except Exception as e:
        print(f"  [WARN] yahoo_quote {symbol} -> {e}")
        return None

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def fetch_markets():
    print("  Fetching: Markets")
    symbols = {"SPY": "S&P 500 ETF", "QQQ": "Nasdaq 100 ETF", "GLD": "Gold ETF", "TLT": "20Y Treasury ETF", "BTC-USD": "Bitcoin", "EURUSD=X": "EUR/USD", "DX-Y.NYB": "DXY"}
    quotes = {}
    for sym, label in symbols.items():
        q = yahoo_quote(sym)
        if q:
            quotes[sym] = {"label": label, **q}
    csv = fetch_text("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10")
    yield_10y = None
    if csv:
        lines = [l for l in csv.strip().splitlines() if l and not l.startswith("DATE")]
        if lines:
            try: yield_10y = float(lines[-1].split(",")[1])
            except: pass
    btc_price = quotes.get("BTC-USD", {}).get("price")
    spy_pct   = quotes.get("SPY", {}).get("change_pct")
    return {"last_updated": now_iso(), "quotes": quotes, "yield_10y": yield_10y,
            "headline": f"SPY {spy_pct}%  |  BTC ${btc_price:,.0f}  |  10Y {yield_10y}%" if btc_price and yield_10y else None}

def fetch_energy():
    print("  Fetching: Energy")
    symbols = {"CL=F": "WTI Crude ($/bbl)", "NG=F": "Natural Gas ($/MMBtu)", "BZ=F": "Brent Crude ($/bbl)", "XLE": "Energy ETF"}
    quotes = {}
    for sym, label in symbols.items():
        q = yahoo_quote(sym)
        if q:
            quotes[sym] = {"label": label, **q}
    headlines = parse_rss(fetch_text("https://www.eia.gov/rss/todayinenergy.xml"), max_items=4)
    wti = quotes.get("CL=F", {}).get("price")
    return {"last_updated": now_iso(), "quotes": quotes, "headlines": headlines,
            "headline": f"WTI ${wti:.2f}/bbl" if wti else None}

def fetch_companies():
    print("  Fetching: Companies")
    watchlist = {"NVDA": "NVIDIA", "MSFT": "Microsoft", "AAPL": "Apple", "META": "Meta", "TSLA": "Tesla", "AMZN": "Amazon", "GOOGL": "Alphabet"}
    quotes = {}
    for sym, label in watchlist.items():
        q = yahoo_quote(sym)
        if q:
            quotes[sym] = {"label": label, **q}
    # SEC EDGAR: filter by form + recent date (no q= to avoid old-doc relevance ranking)
    sec_data = fetch_json("https://efts.sec.gov/LATEST/search-index?forms=8-K&startdt=2026-03-01")
    filings = []
    if sec_data and "hits" in sec_data:
        for hit in sec_data["hits"].get("hits", [])[:5]:
            src = hit.get("_source", {})
            names = src.get("display_names", [])
            entity = names[0].split(" (CIK")[0].strip() if names else ""
            period = src.get("file_date", "")
            link   = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={urllib.parse.quote(entity)}&type=8-K&dateb=&owner=include&count=5"
            if entity:
                filings.append({"title": f"{entity} — 8-K ({period})", "link": link, "published": period})
    nvda_pct = quotes.get("NVDA", {}).get("change_pct")
    msft_pct = quotes.get("MSFT", {}).get("change_pct")
    return {"last_updated": now_iso(), "quotes": quotes, "recent_filings": filings,
            "headline": f"NVDA {nvda_pct}%  |  MSFT {msft_pct}%" if nvda_pct else None}

def fetch_sports():
    print("  Fetching: Sports")
    leagues = {"nfl": ("football", "NFL"), "nba": ("basketball", "NBA"), "mlb": ("baseball", "MLB")}
    scores = {}
    injuries = {}
    for lid, (sport, label) in leagues.items():
        sb = fetch_json(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{lid}/scoreboard")
        if sb and "events" in sb:
            games = []
            for ev in sb["events"][:4]:
                comps = ev.get("competitions", [{}])[0]
                cs = comps.get("competitors", [])
                if len(cs) == 2:
                    games.append({"home": cs[0].get("team", {}).get("abbreviation", ""), "away": cs[1].get("team", {}).get("abbreviation", ""),
                                  "home_score": cs[0].get("score", ""), "away_score": cs[1].get("score", ""),
                                  "status": ev.get("status", {}).get("type", {}).get("shortDetail", "")})
            scores[lid] = {"label": label, "games": games}
        if lid in ("nfl", "nba"):
            inj = fetch_json(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{lid}/injuries")
            if inj and "injuries" in inj:
                top = []
                for ti in inj["injuries"][:3]:
                    for p in ti.get("injuries", [])[:2]:
                        top.append({"player": p.get("athlete", {}).get("displayName", ""), "team": ti.get("team", {}).get("abbreviation", ""),
                                    "status": p.get("status", ""), "detail": p.get("shortComment", "")})
                injuries[lid] = top
    return {"last_updated": now_iso(), "scores": scores, "injuries": injuries, "headline": "NFL / NBA / MLB live scores"}

def fetch_geopolitics():
    print("  Fetching: Geopolitics")
    # GDELT JSON (RSS is malformed; OR terms need parentheses)
    gdelt_data = fetch_json("https://api.gdeltproject.org/api/v2/doc/doc?query=%28conflict+OR+sanctions+OR+military%29+sourcelang%3Aeng&mode=artlist&maxrecords=10&format=json")
    gdelt = []
    if gdelt_data and "articles" in gdelt_data:
        for a in gdelt_data["articles"][:5]:
            if a.get("title"):
                gdelt.append({"title": a["title"], "link": a.get("url", ""), "published": a.get("seendate", "")})
    bbc   = parse_rss(fetch_text("https://feeds.bbci.co.uk/news/world/rss.xml"), 5)
    seen, headlines = set(), []
    for item in gdelt + bbc:
        key = item["title"][:40].lower()
        if key not in seen:
            seen.add(key)
            headlines.append(item)
        if len(headlines) >= 7:
            break
    return {"last_updated": now_iso(), "headlines": headlines[:7], "headline": headlines[0]["title"] if headlines else None}

def fetch_technology():
    print("  Fetching: Technology")
    hn_top = fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json")
    hn_stories = []
    if hn_top:
        for sid in hn_top[:8]:
            s = fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
            if s and s.get("title"):
                hn_stories.append({"title": s["title"], "url": s.get("url", f"https://news.ycombinator.com/item?id={sid}"), "score": s.get("score", 0), "comments": s.get("descendants", 0)})
            if len(hn_stories) >= 5:
                break
    tech_news = parse_rss(fetch_text("https://www.wired.com/feed/category/science/latest/rss"), 5)
    if not tech_news:
        tech_news = parse_rss(fetch_text("https://feeds.arstechnica.com/arstechnica/technology-lab"), 5)
    return {"last_updated": now_iso(), "hn_top": hn_stories, "tech_headlines": tech_news,
            "headline": hn_stories[0]["title"] if hn_stories else None}

def fetch_policy():
    print("  Fetching: Policy")
    # Congress: most-viewed bills (most-recent-bills.xml returns 404)
    bills = parse_rss(fetch_text("https://www.congress.gov/rss/most-viewed-bills.xml"), 5)
    # Federal Register: use JSON API (RSS has malformed XML)
    fr_data = fetch_json("https://www.federalregister.gov/api/v1/articles.json?conditions[type][]=RULE&conditions[type][]=PROPOSED_RULE&per_page=5&order=newest")
    rules = []
    if fr_data and "results" in fr_data:
        for r in fr_data["results"][:5]:
            title = r.get("title", "")
            link  = r.get("html_url", "")
            pub   = r.get("publication_date", "")
            if title:
                rules.append({"title": title, "link": link, "published": pub})
    # SCOTUS: RSS server returning 404/503 as of 2026-03; graceful empty fallback
    scotus = parse_rss(fetch_text("https://www.supremecourt.gov/rss/opinions/slipopinion/25"), 3) or []
    headline = bills[0]["title"] if bills else (rules[0]["title"] if rules else None)
    return {"last_updated": now_iso(), "bills": bills, "federal_rules": rules, "scotus": scotus, "headline": headline}


def fetch_legal():
    print("  Fetching: Legal (CourtListener)")
    token = os.environ.get("COURTLISTENER_TOKEN", "")
    headers = {"User-Agent": "InflectionOS/1.0"}
    if token:
        headers["Authorization"] = f"Token {token}"

    queries = [
        ("antitrust OR monopoly", "Antitrust"),
        ("SEC enforcement OR FTC complaint", "Regulatory"),
        ("First Amendment OR Fourth Amendment", "Constitutional"),
    ]

    cases = []
    seen = set()
    for q, tag in queries:
        url = (
            "https://www.courtlistener.com/api/rest/v4/search/"
            "?q=" + urllib.parse.quote(q) + "&type=o&order_by=score+desc&page_size=3"
        )
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
            for hit in (data.get("results") or [])[:3]:
                name = hit.get("caseName") or hit.get("case_name", "")
                court = hit.get("court", "")
                date = (hit.get("dateFiled") or hit.get("date_filed", ""))[:10]
                url_path = hit.get("absolute_url", "")
                link = "https://www.courtlistener.com" + url_path if url_path else ""
                key = name[:40].lower()
                if name and key not in seen:
                    seen.add(key)
                    cases.append({
                        "title": name,
                        "court": court,
                        "date": date,
                        "tag": tag,
                        "link": link,
                    })
        except Exception as e:
            print("  [WARN] CourtListener query -> " + str(e))

    scotus_rss = parse_rss(fetch_text("https://www.supremecourt.gov/rss/opinions/slipopinion/25"), 3)
    headline = cases[0]["title"] if cases else (scotus_rss[0]["title"] if scotus_rss else None)
    return {
        "last_updated": now_iso(),
        "cases": cases[:8],
        "scotus_opinions": scotus_rss,
        "headline": headline,
    }

def build_payload():
    print("Building live data payload...")
    return {
        "schema_version": "1.2",
        "fetched_at": now_iso(),
        "domains": {
            "markets":     fetch_markets(),
            "energy":      fetch_energy(),
            "companies":   fetch_companies(),
            "sports":      fetch_sports(),
            "geopolitics": fetch_geopolitics(),
            "technology":  fetch_technology(),
            "policy":      fetch_policy(),
            "legal":       fetch_legal(),
        }
    }

def push_to_github(payload):
    if not GITHUB_TOKEN:
        print("[ERROR] GITHUB_TOKEN not set")
        return False
    content_b64 = base64.b64encode(json.dumps(payload, indent=2).encode()).decode()
    api_url = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json", "User-Agent": "InflectionOS/1.0"}
    req = urllib.request.Request(api_url, headers=headers)
    sha = None
    try:
        with urllib.request.urlopen(req) as r:
            sha = json.loads(r.read().decode()).get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"[ERROR] GitHub GET {e.code}")
            return False
    body = {"message": f"chore: live data update {payload['fetched_at']}", "content": content_b64, "branch": BRANCH}
    if sha:
        body["sha"] = sha
    put_req = urllib.request.Request(api_url, data=json.dumps(body).encode(),
        headers={**headers, "Content-Type": "application/json"}, method="PUT")
    try:
        with urllib.request.urlopen(put_req) as r:
            sha_new = json.loads(r.read().decode()).get("content", {}).get("sha", "")[:7]
            print(f"  Pushed data.json -> {sha_new}")
            return True
    except urllib.error.HTTPError as e:
        print(f"[ERROR] GitHub PUT {e.code}: {e.read().decode()[:200]}")
        return False

if __name__ == "__main__":
    payload = build_payload()
    with open("/tmp/live_data_preview.json", "w") as f:
        json.dump(payload, f, indent=2)
    print("  Preview saved to /tmp/live_data_preview.json")
    success = push_to_github(payload)
    print(f"  GitHub push: {'OK' if success else 'FAILED'}")
