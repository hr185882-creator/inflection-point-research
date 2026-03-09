#!/usr/bin/env python3
"""
fetch_data.py -- Live data fetcher for inflection-point-research
Fetches market, energy, geopolitics, tech, policy, sports, media, and claims data
from free public APIs and pushes updated data.json to GitHub.
"""

import json
import base64
import os
from datetime import datetime, timezone

import requests

# -- helpers ------------------------------------------------------------------

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def safe_get(url, params=None, headers=None, timeout=15):
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"  [WARN] GET {url} failed: {e}")
        return None

# -- 1. Markets (Yahoo Finance) -----------------------------------------------

def fetch_yahoo(symbol):
    """Return (price, change_pct) for a Yahoo Finance symbol, or (None, None)."""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + symbol
    params = {"interval": "1d", "range": "1d"}
    headers = {"User-Agent": "Mozilla/5.0"}
    r = safe_get(url, params=params, headers=headers)
    if r is None:
        return None, None
    try:
        data = r.json()
        meta = data["chart"]["result"][0]["meta"]
        price = round(meta.get("regularMarketPrice") or meta.get("previousClose"), 4)
        prev  = meta.get("chartPreviousClose") or meta.get("previousClose")
        pct   = round((price - prev) / prev * 100, 4) if prev else None
        return price, pct
    except Exception as e:
        print(f"  [WARN] Yahoo parse failed for {symbol}: {e}")
        return None, None

def fetch_markets():
    print("[markets] Fetching from Yahoo Finance...")
    sp500, sp500_chg = fetch_yahoo("^GSPC")
    us10y, _         = fetch_yahoo("^TNX")
    dxy, _           = fetch_yahoo("DX-Y.NYB")
    btc, _           = fetch_yahoo("BTC-USD")
    gold, _          = fetch_yahoo("GLD")
    return {
        "sp500":            sp500,
        "sp500_change_pct": sp500_chg,
        "us10y":            us10y,
        "dxy":              dxy,
        "btc":              btc,
        "gold":             gold,
        "last_updated":     utc_now(),
    }

# -- 2. Energy (Yahoo Finance futures) ----------------------------------------

def fetch_energy():
    print("[energy] Fetching from Yahoo Finance...")
    wti, _   = fetch_yahoo("CL=F")
    brent, _ = fetch_yahoo("BZ=F")
    ng, _    = fetch_yahoo("NG=F")
    return {
        "wti_crude":    wti,
        "brent_crude":  brent,
        "natural_gas":  ng,
        "last_updated": utc_now(),
    }

# -- 3. Hacker News top 5 -----------------------------------------------------

def fetch_hn():
    print("[technology] Fetching Hacker News top stories...")
    r = safe_get("https://hacker-news.firebaseio.com/v0/topstories.json")
    if r is None:
        return {"hn_top": [], "last_updated": utc_now()}
    ids = r.json()[:5]
    stories = []
    for sid in ids:
        sr = safe_get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
        if sr:
            item = sr.json()
            stories.append({
                "id":    item.get("id"),
                "title": item.get("title"),
                "url":   item.get("url"),
                "score": item.get("score"),
            })
    return {"hn_top": stories, "last_updated": utc_now()}

# -- 4. Geopolitics (GDELT) ---------------------------------------------------

def fetch_geopolitics():
    print("[geopolitics] Fetching GDELT conflict events...")
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query":      "conflict",
        "mode":       "artlist",
        "maxrecords": 5,
        "format":     "json",
    }
    r = safe_get(url, params=params)
    events = []
    if r:
        try:
            data = r.json()
            articles = data.get("articles", [])
            for a in articles:
                events.append({
                    "title":  a.get("title"),
                    "url":    a.get("url"),
                    "source": a.get("domain"),
                    "date":   a.get("seendate"),
                })
        except Exception as e:
            print(f"  [WARN] GDELT parse failed: {e}")
    return {
        "top_events":         events,
        "conflict_count_24h": len(events) if events else None,
        "last_updated":       utc_now(),
    }

# -- 5. Polymarket top markets ------------------------------------------------

def fetch_polymarket():
    print("[claims] Fetching Polymarket top markets...")
    url = "https://gamma-api.polymarket.com/markets"
    params = {"limit": 5, "active": "true", "order": "volume", "ascending": "false"}
    r = safe_get(url, params=params)
    markets = []
    if r:
        try:
            data = r.json()
            for m in data:
                markets.append({
                    "question":    m.get("question"),
                    "volume":      m.get("volume"),
                    "end_date":    m.get("endDate") or m.get("end_date_iso"),
                    "market_slug": m.get("slug"),
                })
        except Exception as e:
            print(f"  [WARN] Polymarket parse failed: {e}")
    return {"polymarket_top": markets, "last_updated": utc_now()}

# -- 6. Media headlines (GNews free tier) -------------------------------------

def fetch_media():
    print("[media] Fetching top headlines...")
    headlines = []
    r = safe_get(
        "https://gnews.io/api/v4/top-headlines",
        params={"lang": "en", "max": 5, "token": "free"},
    )
    if r and r.status_code == 200:
        try:
            data = r.json()
            for a in data.get("articles", []):
                headlines.append({
                    "title":  a.get("title"),
                    "url":    a.get("url"),
                    "source": a.get("source", {}).get("name"),
                })
        except Exception:
            pass
    return {"top_headlines": headlines, "last_updated": utc_now()}

# -- 7. Sports headlines (ESPN public API) ------------------------------------

def fetch_sports():
    print("[sports] Fetching ESPN headlines...")
    url = "https://site.api.espn.com/apis/site/v2/sports/news"
    r = safe_get(url, params={"limit": 5})
    headlines = []
    if r:
        try:
            data = r.json()
            for a in data.get("articles", []):
                headlines.append({
                    "headline":  a.get("headline"),
                    "url":       a.get("links", {}).get("web", {}).get("href"),
                    "sport":     a.get("categories", [{}])[0].get("description"),
                    "published": a.get("published"),
                })
        except Exception as e:
            print(f"  [WARN] ESPN parse failed: {e}")
    return {"top_headlines": headlines, "last_updated": utc_now()}

# -- 8. Policy (Federal Register) ---------------------------------------------

def fetch_policy():
    print("[policy] Fetching Federal Register headlines...")
    url = "https://www.federalregister.gov/api/v1/articles"
    params = {
        "per_page": 5,
        "order":    "newest",
        "fields[]": ["title", "document_number", "publication_date", "html_url", "type"],
    }
    r = safe_get(url, params=params)
    bills = []
    if r:
        try:
            data = r.json()
            for a in data.get("results", []):
                bills.append({
                    "title":      a.get("title"),
                    "doc_number": a.get("document_number"),
                    "date":       a.get("publication_date"),
                    "url":        a.get("html_url"),
                    "type":       a.get("type"),
                })
        except Exception as e:
            print(f"  [WARN] Federal Register parse failed: {e}")
    return {
        "recent_bills":               bills,
        "federal_register_headlines": bills,
        "last_updated":               utc_now(),
    }

# -- 9. Companies top movers (Yahoo Finance most-active) ----------------------

def fetch_companies():
    print("[companies] Fetching top movers from Yahoo Finance...")
    url = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
    params = {"scrIds": "most_actives", "count": 5}
    headers = {"User-Agent": "Mozilla/5.0"}
    r = safe_get(url, params=params, headers=headers)
    movers = []
    if r:
        try:
            data = r.json()
            quotes = data["finance"]["result"][0]["quotes"]
            for q in quotes:
                movers.append({
                    "symbol":     q.get("symbol"),
                    "name":       q.get("shortName") or q.get("longName"),
                    "price":      q.get("regularMarketPrice"),
                    "change_pct": round(q.get("regularMarketChangePercent", 0), 4),
                    "volume":     q.get("regularMarketVolume"),
                })
        except Exception as e:
            print(f"  [WARN] Companies parse failed: {e}")
    return {"top_movers": movers, "last_updated": utc_now()}

# -- GitHub push --------------------------------------------------------------

def push_to_github(data, token):
    repo    = "hr185882-creator/inflection-point-research"
    path    = "data.json"
    api_url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept":        "application/vnd.github+json",
    }

    # Get current SHA
    sha = None
    r = requests.get(api_url, headers=headers, timeout=15)
    if r.status_code == 200:
        sha = r.json().get("sha")
        print(f"[github] Existing data.json SHA: {sha}")
    else:
        print("[github] data.json not found -- will create fresh.")

    content_b64 = base64.b64encode(
        json.dumps(data, indent=2).encode("utf-8")
    ).decode("utf-8")

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "message": f"Auto-update: data.json [{timestamp}]",
        "content": content_b64,
        "branch":  "main",
    }
    if sha:
        payload["sha"] = sha

    r2 = requests.put(api_url, headers=headers, json=payload, timeout=15)
    if r2.status_code in (200, 201):
        commit_sha = r2.json()["commit"]["sha"]
        print(f"[github] Pushed successfully. Commit: {commit_sha}")
        return True
    else:
        print(f"[github] Push failed: {r2.status_code} {r2.text[:300]}")
        return False

# -- main ---------------------------------------------------------------------

def main():
    print("=" * 60)
    print("fetch_data.py -- Inflection Point Research Live Fetcher")
    print("=" * 60)

    markets     = fetch_markets()
    energy      = fetch_energy()
    technology  = fetch_hn()
    geopolitics = fetch_geopolitics()
    claims      = fetch_polymarket()
    media       = fetch_media()
    sports      = fetch_sports()
    policy      = fetch_policy()
    companies   = fetch_companies()

    data = {
        "last_updated": utc_now(),
        "geopolitics":  geopolitics,
        "markets":      markets,
        "energy":       energy,
        "companies":    companies,
        "technology":   technology,
        "policy":       policy,
        "sports":       sports,
        "media":        media,
        "claims":       claims,
    }

    print("\n[result] Final data.json:")
    print(json.dumps(data, indent=2))

    token = os.getenv("GITHUB_TOKEN")
    if token:
        print("\n[github] Pushing updated data.json...")
        push_to_github(data, token)
    else:
        print("\n[github] GITHUB_TOKEN not set -- skipping push.")

    return data

if __name__ == "__main__":
    main()
