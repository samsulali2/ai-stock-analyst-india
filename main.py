import os
import json
import re
import time
from datetime import datetime
import yfinance as yf
import logging
from groq import Groq

# ========================= CONFIG =========================
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Suppress yfinance spam
yf.pdr_override = lambda *args, **kwargs: None
logging.getLogger("yfinance").setLevel(logging.ERROR)

RSS_FEEDS = [
    "https://news.google.com/rss/search?q=india+stock+market+OR+defence+stocks+OR+broker+upgrade+OR+downgrade+OR+HAL+BEL+BDL",
    "https://news.google.com/rss/search?q=defence+india+stocks+OR+order+win+HAL+BEL+Mazagon",
    "https://www.moneycontrol.com/news/rss/latestnews.xml",
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
]

def fetch_all_news():
    articles = []
    seen = set()
    import feedparser
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:12]:
                title = entry.title.strip()
                summary = getattr(entry, 'summary', '') or getattr(entry, 'description', '')
                key = (title + summary)[:100].lower()
                if key in seen: continue
                seen.add(key)
                articles.append({"title": title, "summary": summary})
        except:
            pass
    return articles

def clean_ticker(ticker: str) -> str:
    if not ticker:
        return None
    t = re.sub(r'[^A-Z0-9]', '', ticker.upper().strip())
    if len(t) < 3 or t in ['NIFTY', 'SENSEX', 'CRUDEOIL', 'GOLD', 'BANKNIFTY']:
        return None
    return t

def get_current_price(ticker: str):
    if not ticker: return None
    try:
        data = yf.Ticker(f"{ticker}.NS").fast_info
        price = data.get('lastPrice') or data.get('regularMarketPrice')
        return round(float(price), 2) if price else None
    except:
        return None

def analyze_news(text: str):
    prompt = f"""You are an elite Indian equity analyst. Return ONLY valid JSON.

News: {text}

JSON:
{{"stocks": ["HAL", "BEL"], "sentiment": "positive", "sector": "defence", "event": "upgrade", "confidence": 85, "reason": "short clear reason"}}
"""
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=600
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Groq Error: {e}")
        return None

def safe_json(text):
    if not text: return None
    try: return json.loads(text)
    except:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try: return json.loads(match.group())
            except: pass
    return None

# ====================== MAIN ======================
def main():
    print("🚀 Starting Clean Defence Stock Scanner...\n")
    articles = fetch_all_news()
    results = []
    price_cache = {}

    for article in articles:
        text = article["title"] + " " + article.get("summary", "")
        print(f"📰 {article['title'][:95]}...")

        raw = analyze_news(text)
        data = safe_json(raw)
        if not data or not data.get("stocks"):
            continue

        # Clean tickers
        clean_stocks = [clean_ticker(t) for t in data.get("stocks", []) if clean_ticker(t)]
        if not clean_stocks: continue

        ticker = clean_stocks[0]

        if ticker not in price_cache:
            price_cache[ticker] = get_current_price(ticker)

        price = price_cache[ticker]
        conf = int(data.get("confidence", 60))

        signal = "🚀 STRONG BUY" if conf >= 80 else "📈 BUY" if conf >= 60 else "HOLD"
        if signal == "HOLD": continue

        entry = price if price else "Market Price"
        target = round(price * 1.18, 2) if price else None
        stop = round(price * 0.92, 2) if price else None

        results.append({
            "ticker": ticker,
            "signal": signal,
            "entry": entry,
            "target": target,
            "stop": stop,
            "reason": data.get("reason", "Strong momentum"),
            "confidence": conf
        })

    # ====================== TELEGRAM MESSAGE ======================
    print("\n" + "="*90)
    print("📲 COPY THIS FOR YOUR TELEGRAM CHANNEL 📲\n")

    now = datetime.now().strftime('%d %b %H:%M')
    msg = f"🧠 **AI Defence & Momentum Signals** — {now}\n\n"
    msg += "**High Conviction Calls**\n\n"

    # Remove duplicate tickers, keep highest confidence
    seen = {}
    for r in sorted(results, key=lambda x: x["confidence"], reverse=True):
        if r["ticker"] not in seen:
            seen[r["ticker"]] = r

    for r in list(seen.values())[:8]:
        target_str = f"₹{r['target']}" if r['target'] else "N/A"
        stop_str = f"₹{r['stop']}" if r['stop'] else "N/A"
        msg += f"**{r['ticker']}** — {r['signal']}\n"
        msg += f"Entry ≈ ₹{r['entry']} | Target {target_str} | Stop {stop_str}\n"
        msg += f"→ {r['reason']}\n\n"

    if not seen:
        msg += "No strong signals in this scan."

    msg += "\n⚡ Powered by Groq • Live NSE prices • Defence focus"

    print(msg)

    # Auto post to Telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        import requests
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
                timeout=10
            )
            if response.status_code == 200:
                print("✅ Successfully posted to your Telegram channel!")
            else:
                print(f"❌ Telegram failed: {response.text}")
        except Exception as e:
            print(f"❌ Telegram error: {e}")
    else:
        print("⚠️  Telegram not configured (add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID secrets)")

if __name__ == "__main__":
    main()
