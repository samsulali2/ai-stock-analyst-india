import os
import json
import re
from datetime import datetime
import yfinance as yf
from groq import Groq

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print("🔧 Configuration Check:")
print(f"TELEGRAM_BOT_TOKEN: {'✅ Present' if TELEGRAM_BOT_TOKEN else '❌ MISSING'}")
print(f"TELEGRAM_CHAT_ID:   {'✅ Present' if TELEGRAM_CHAT_ID else '❌ MISSING'}")
print(f"GROQ_API_KEY:       {'✅ Present' if groq_client.api_key else '❌ MISSING'}")
print("=" * 80)

# ====================== FETCH & ANALYZE ======================
def fetch_all_news():
    articles = []
    seen = set()
    import feedparser
    feeds = [
        "https://news.google.com/rss/search?q=defence+india+stocks+OR+HAL+BEL+BDL+order+win",
        "https://news.google.com/rss/search?q=broker+upgrade+OR+downgrade+india+stocks",
    ]
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                title = entry.title.strip()
                if title in seen: continue
                seen.add(title)
                articles.append({"title": title, "summary": getattr(entry, 'summary', '')})
        except:
            pass
    return articles

def clean_ticker(t: str):
    if not t: return None
    t = re.sub(r'[^A-Z0-9]', '', t.upper())
    return t if len(t) >= 3 and t not in ['NIFTY','SENSEX','CRUDEOIL'] else None

def get_price(ticker):
    try:
        p = yf.Ticker(f"{ticker}.NS").fast_info.get('lastPrice')
        return round(float(p), 2) if p else None
    except:
        return None

def analyze_news(text):
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",   # Much cheaper & higher limits
            messages=[{"role": "user", "content": f"""Return ONLY JSON.\nNews: {text}\nJSON: {{"stocks": ["HAL"], "confidence": 80, "reason": "short reason"}}"""}],
            temperature=0.1,
            max_tokens=300
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Groq Error: {e}")
        return None

def safe_json(text):
    try:
        return json.loads(text)
    except:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        return json.loads(match.group()) if match else None

# ====================== MAIN ======================
def main():
    articles = fetch_all_news()
    results = []
    price_cache = {}

    for article in articles:
        raw = analyze_news(article["title"] + " " + article.get("summary", ""))
        data = safe_json(raw)
        if not data or not data.get("stocks"): continue

        ticker = clean_ticker(data["stocks"][0])
        if not ticker: continue

        if ticker not in price_cache:
            price_cache[ticker] = get_price(ticker)

        price = price_cache[ticker]
        conf = int(data.get("confidence", 60))
        signal = "🚀 STRONG BUY" if conf >= 75 else "📈 BUY"

        entry = price if price else "Market Price"
        target = round(price * 1.18, 2) if price else None

        results.append({"ticker": ticker, "signal": signal, "entry": entry, "target": target, "reason": data.get("reason", "")})

    # Build Message
    msg = f"🧠 **AI Defence Signals** — {datetime.now().strftime('%d %b %H:%M')}\n\n"
    for r in sorted(results, key=lambda x: x.get("confidence",0), reverse=True)[:8]:
        msg += f"**{r['ticker']}** — {r['signal']}\n"
        msg += f"Entry ≈ ₹{r['entry']} | Target ₹{r.get('target','N/A')}\n"
        msg += f"→ {r['reason']}\n\n"

    msg += "⚡ Powered by Groq"

    print(msg)

    # Send to Telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        import requests
        try:
            r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                              json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
            print("✅ Sent to Telegram" if r.status_code == 200 else f"❌ Telegram Error {r.status_code}")
        except Exception as e:
            print(f"❌ Telegram failed: {e}")
    else:
        print("⚠️ Telegram secrets still missing")

if __name__ == "__main__":
    main()
