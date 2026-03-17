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

SEEN_FILE = "seen.json"

groq_client = Groq(api_key=GROQ_API_KEY)

print("🔧 Configuration Check:")
print(f"GROQ_API_KEY:       {'✅ Present' if GROQ_API_KEY else '❌ MISSING'}")
print(f"TELEGRAM_BOT_TOKEN: {'✅ Present' if TELEGRAM_BOT_TOKEN else '❌ MISSING'}")
print(f"TELEGRAM_CHAT_ID:   {'✅ Present' if TELEGRAM_CHAT_ID else '❌ MISSING'}")
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

# ====================== FETCH NEWS ======================
def fetch_all_news():
    articles = []
    seen_titles = set()

    feeds = [
        "https://news.google.com/rss/search?q=defence+india+stocks+HAL+BEL+BDL+order",
        "https://news.google.com/rss/search?q=broker+upgrade+downgrade+india+stocks",
    ]

    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                title = entry.title.strip()
                if title in seen_titles:
                    continue
                seen_titles.add(title)

                articles.append({
                    "title": title,
                    "summary": getattr(entry, "summary", "")
                })
        except Exception as e:
            print(f"Feed error: {e}")

    return articles

# ====================== HELPERS ======================
def clean_ticker(t):
    if not t:
        return None
    t = re.sub(r'[^A-Z0-9]', '', t.upper())
    if len(t) < 3 or t in ["NIFTY", "SENSEX", "CRUDEOIL"]:
        return None
    return t

def get_price_and_volume(ticker):
    try:
        stock = yf.Ticker(f"{ticker}.NS")
        info = stock.fast_info
        price = info.get("lastPrice")

        hist = stock.history(period="5d")
        if hist.empty:
            return None, False

        avg_vol = hist["Volume"].mean()
        latest_vol = hist["Volume"].iloc[-1]

        volume_spike = latest_vol > avg_vol

        return round(float(price), 2) if price else None, volume_spike
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
  "stocks": ["HAL"],
  "confidence": 0-100,
  "reason": "max 12 words, specific catalyst"
}}
"""
        resp = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=200
        )

        return resp.choices[0].message.content.strip()

    except Exception as e:
        print(f"Groq Error: {e}")
        return None

def safe_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                return None
    return None

# ====================== MAIN ======================
def main():
    seen = load_seen()
    articles = fetch_all_news()

    results = []
    price_cache = {}

    for article in articles:
        raw = analyze_news(article["title"] + " " + article["summary"])
        data = safe_json(raw)

        if not data or not data.get("stocks"):
            continue

        ticker = clean_ticker(data["stocks"][0])
        if not ticker:
            continue

        key = f"{ticker}_{article['title']}"
        if key in seen:
            continue

        conf = int(data.get("confidence", 50))

        # Filter weak signals
        if conf < 65:
            continue

        if ticker not in price_cache:
            price, volume_spike = get_price_and_volume(ticker)
            price_cache[ticker] = (price, volume_spike)

        price, volume_spike = price_cache[ticker]

        # Skip if no volume support
        if not volume_spike:
            continue

        entry = price if price else "Market"
        target = round(price * 1.18, 2) if price else "N/A"

        if conf >= 85:
            signal = "🚀 Momentum Build-up"
            risk = "Low"
        elif conf >= 75:
            signal = "📈 Early Accumulation"
            risk = "Medium"
        else:
            signal = "⚡ Breakout Watch"
            risk = "High"

        results.append({
            "ticker": ticker,
            "signal": signal,
            "entry": entry,
            "target": target,
            "reason": data.get("reason", ""),
            "confidence": conf,
            "risk": risk
        })

        seen.add(key)

    save_seen(seen)

    # ====================== MESSAGE ======================
    if not results:
        print("No strong signals found.")
        return

    msg = f"🧠 AI Stock Signals — {datetime.now().strftime('%d %b %H:%M')}\n\n"

    results = sorted(results, key=lambda x: x["confidence"], reverse=True)[:8]

    for r in results:
        msg += f"**{r['ticker']}** — {r['signal']}\n"
        msg += f"Entry ≈ ₹{r['entry']} | Target ₹{r['target']}\n"
        msg += f"Risk: {r['risk']}\n"
        msg += f"→ {r['reason']}\n\n"

    msg += "⚡ Powered by AI"

    print(msg)

    # ====================== TELEGRAM ======================
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": msg,
                    "parse_mode": "Markdown"
                }
            )

            if response.status_code == 200:
                print("✅ Sent to Telegram")
            else:
                print(f"❌ Telegram Error: {response.status_code} | {response.text}")

        except Exception as e:
            print(f"❌ Telegram failed: {e}")
    else:
        print("⚠️ Telegram not configured")

# ====================== RUN ======================
if __name__ == "__main__":
    main()
