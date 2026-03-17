import os
import json
import re
from datetime import datetime
import requests
import feedparser
import yfinance as yf
from groq import Groq

# ====================== CONFIG ======================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY")
MARKETAUX_API_KEY = os.getenv("MARKETAUX_API_KEY")

SEEN_FILE = "seen.json"

groq_client = Groq(api_key=GROQ_API_KEY)

print("🔧 Config Check:")
print(f"GROQ: {'✅' if GROQ_API_KEY else '❌'} | TG: {'✅' if TELEGRAM_BOT_TOKEN else '❌'} | Chat: {'✅' if TELEGRAM_CHAT_ID else '❌'}")
print(f"NewsData: {'✅' if NEWSDATA_API_KEY else '❌'} | MarketAux: {'✅' if MARKETAUX_API_KEY else '❌'}")
print("=" * 60)

# ====================== STORAGE ======================
def load_seen():
    try:
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

# ====================== RSS ======================
def fetch_rss_news():
    feeds = [
        "https://news.google.com/rss/search?q=indian+stocks+market",
        "https://news.google.com/rss/search?q=NSE+BSE+stocks",
        "https://news.google.com/rss/search?q=broker+upgrade+downgrade+india",
        "https://news.google.com/rss/search?q=india+business+breaking+stocks",
    ]

    articles, seen = [], set()

    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:6]:
                title = e.title.strip()
                if title in seen:
                    continue
                seen.add(title)

                articles.append({
                    "title": title,
                    "summary": getattr(e, "summary", "")
                })
        except Exception as e:
            print(f"RSS error: {e}")

    print(f"📰 RSS: {len(articles)}")
    return articles

# ====================== NEWSDATA ======================
def fetch_newsdata():
    if not NEWSDATA_API_KEY:
        return []

    url = "https://newsdata.io/api/1/news"
    params = {
        "apikey": NEWSDATA_API_KEY,
        "q": "india stock market OR NSE OR BSE",
        "country": "in",
        "language": "en",
        "category": "business",
    }

    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()

        articles = [{
            "title": i.get("title", "").strip(),
            "summary": i.get("description", "").strip()
        } for i in data.get("results", []) if i.get("title")]

        print(f"🛰️ NewsData: {len(articles)}")
        return articles

    except Exception as e:
        print(f"NewsData error: {e}")
        return []

# ====================== MARKETAUX ======================
def fetch_marketaux():
    if not MARKETAUX_API_KEY:
        return []

    url = "https://api.marketaux.com/v1/news/all"
    params = {
        "api_token": MARKETAUX_API_KEY,
        "countries": "in",
        "language": "en",
        "limit": 20,
    }

    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()

        articles = []
        for i in data.get("data", []):
            tickers = [
                ent.get("symbol", "").replace(".NS", "").replace(".BO", "")
                for ent in i.get("entities", [])
                if ent.get("symbol")
            ]

            articles.append({
                "title": i.get("title", "").strip(),
                "summary": i.get("description", "").strip(),
                "tickers": tickers
            })

        print(f"📊 MarketAux: {len(articles)}")
        return articles

    except Exception as e:
        print(f"MarketAux error: {e}")
        return []

# ====================== HELPERS ======================
def clean_ticker(t):
    if not t:
        return None
    t = re.sub(r'[^A-Z0-9]', '', t.upper())
    return t if len(t) >= 3 else None

def get_price_volume(ticker):
    try:
        s = yf.Ticker(f"{ticker}.NS")
        price = s.fast_info.get("lastPrice")

        hist = s.history(period="5d")
        if hist.empty:
            return None, False

        return round(price, 2), hist["Volume"].iloc[-1] > hist["Volume"].mean()

    except:
        return None, False

# ====================== AI ======================
def analyze_news(text):
    try:
        prompt = f"""
Return ONLY JSON.

News: {text}

Format:
{{
 "stocks": ["RELIANCE"],
 "confidence": 0-100,
 "reason": "max 12 words, specific catalyst"
}}
"""
        r = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=150
        )

        return r.choices[0].message.content.strip()

    except Exception as e:
        print(f"Groq error: {e}")
        return None

def safe_json(t):
    try:
        return json.loads(t)
    except:
        m = re.search(r'\{.*\}', t or "", re.DOTALL)
        return json.loads(m.group()) if m else None

# ====================== MAIN ======================
def main():
    seen = load_seen()

    # Fetch all sources
    articles = (
        fetch_rss_news() +
        fetch_newsdata() +
        fetch_marketaux()
    )

    # Deduplicate
    unique = {}
    for a in articles:
        key = a["title"].lower()
        if key not in unique:
            unique[key] = a

    articles = list(unique.values())
    print(f"🧠 Total: {len(articles)}")

    results, price_cache = [], {}

    for a in articles:
        text_blob = (a["title"] + " " + a.get("summary", "")).lower()

        if not any(k in text_blob for k in ["stock", "nse", "bse", "shares", "earnings", "order"]):
            continue

        ticker, conf, reason = None, 50, ""

        # Prefer MarketAux ticker
        if a.get("tickers"):
            ticker = clean_ticker(a["tickers"][0])
            raw = analyze_news(a["title"])
            data = safe_json(raw)
            if data:
                conf = int(data.get("confidence", 70)) + 10
                reason = data.get("reason", "")
        else:
            raw = analyze_news(a["title"] + " " + a.get("summary", ""))
            data = safe_json(raw)
            if not data or not data.get("stocks"):
                continue

            ticker = clean_ticker(data["stocks"][0])
            conf = int(data.get("confidence", 50))
            reason = data.get("reason", "")

        if not ticker or conf < 65:
            continue

        key = f"{ticker}_{a['title']}"
        if key in seen:
            continue

        if ticker not in price_cache:
            price_cache[ticker] = get_price_volume(ticker)

        price, vol_ok = price_cache[ticker]
        if not vol_ok:
            continue

        entry = price or "Market"
        target = round(price * 1.18, 2) if price else "N/A"

        signal = "🚀 Momentum" if conf >= 85 else "📈 Accumulation" if conf >= 75 else "⚡ Watch"
        risk = "Low" if conf >= 85 else "Medium" if conf >= 75 else "High"

        results.append({
            "ticker": ticker,
            "signal": signal,
            "entry": entry,
            "target": target,
            "reason": reason,
            "confidence": conf,
            "risk": risk
        })

        seen.add(key)

    save_seen(seen)

    if not results:
        print("No signals.")
        return

    results = sorted(results, key=lambda x: x["confidence"], reverse=True)[:8]

    msg = f"🧠 AI Stock Signals — {datetime.now().strftime('%d %b %H:%M')}\n\n"

    for r in results:
        msg += f"**{r['ticker']}** — {r['signal']}\n"
        msg += f"₹{r['entry']} → ₹{r['target']} | Risk: {r['risk']}\n"
        msg += f"→ {r['reason']}\n\n"

    print(msg)

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            res = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
            )
            print("✅ Sent" if res.status_code == 200 else f"❌ {res.text}")
        except Exception as e:
            print(f"Telegram error: {e}")

# ====================== RUN ======================
if __name__ == "__main__":
    main()
