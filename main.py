import os
import json
import re
import time
from datetime import datetime
from collections import defaultdict
from groq import Groq
import yfinance as yf
import logging

# ========================= CONFIG =========================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")

if not GROQ_API_KEY:
    raise ValueError("❌ GROQ_API_KEY is missing!")

groq_client = Groq(api_key=GROQ_API_KEY)

# Optional Cerebras (only create if key exists)
cerebras_client = None
if CEREBRAS_API_KEY:
    try:
        from cerebras.cloud.sdk import Cerebras
        cerebras_client = Cerebras(api_key=CEREBRAS_API_KEY)
        print("✅ Cerebras client initialized successfully")
    except Exception as e:
        print(f"⚠️ Cerebras import failed: {e} (falling back to Groq only)")
else:
    print("⚠️ CEREBRAS_API_KEY not found → Running in Groq-only mode")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ====================== REST OF THE CODE (same as last stable version) ======================
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
            for entry in feed.entries[:10]:
                title = entry.title.strip()
                summary = getattr(entry, 'summary', '') or getattr(entry, 'description', '')
                key = title.lower()
                if key in seen: continue
                seen.add(key)
                articles.append({"title": title, "summary": summary})
        except:
            pass
    return articles[:40]

def get_current_price(ticker):
    try:
        data = yf.Ticker(f"{ticker}.NS").fast_info
        price = data.get('lastPrice') or data.get('regularMarketPrice')
        return round(float(price), 2) if price else None
    except:
        return None

def analyze_news(text: str, use_cerebras=False):
    prompt = f"""You are an elite Indian stock analyst. Return ONLY valid JSON.

News: {text}

{{"stocks": ["HAL"], "sentiment": "positive", "sector": "defence", "event": "upgrade", "confidence": 80, "reason": "short reason"}}
"""
    try:
        if use_cerebras and cerebras_client:
            resp = cerebras_client.chat.completions.create(
                model="gpt-oss-120b", messages=[{"role": "user", "content": prompt}], temperature=0.1
            )
        else:
            resp = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.1
            )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"AI Error: {e}")
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
    print("🚀 Starting AI Stock Scanner (Groq + optional Cerebras)...\n")
    articles = fetch_all_news()
    results = []
    price_cache = {}

    for article in articles:
        text = article["title"] + " " + article.get("summary", "")
        print(f"📰 {article['title'][:90]}...")

        raw = analyze_news(text, use_cerebras=bool(cerebras_client))
        data = safe_json(raw)
        if not data or not data.get("stocks"):
            continue

        ticker = data["stocks"][0]
        if ticker not in price_cache:
            price_cache[ticker] = get_current_price(ticker)
        price = price_cache[ticker]

        conf = int(data.get("confidence", 60))
        signal = "🚀 STRONG BUY" if conf >= 80 else "📈 BUY" if conf >= 60 else "HOLD"
        if signal == "HOLD": continue

        entry = price or "Market Price"
        target = round(price * 1.18, 2) if price else "N/A"
        stop = round(price * 0.92, 2) if price else "N/A"

        results.append({
            "ticker": ticker,
            "signal": signal,
            "entry": entry,
            "target": target,
            "stop": stop,
            "reason": data.get("reason", "Strong momentum detected"),
            "confidence": conf
        })

    # ====================== CLEAN TELEGRAM MESSAGE ======================
    print("\n" + "="*85)
    print("📲 **COPY THIS BLOCK FOR YOUR TELEGRAM CHANNEL** 📲\n")

    now = datetime.now().strftime('%d %b %H:%M')
    msg = f"🧠 **AI Brainstorm Signals** — {now}\n\n"
    msg += "**High Conviction India Stock Calls**\n\n"

    for r in sorted(results, key=lambda x: x["confidence"], reverse=True)[:8]:
        msg += f"**{r['ticker']}** — {r['signal']}\n"
        msg += f"Entry ≈ ₹{r['entry']} | Target ₹{r['target']} | Stop ₹{r['stop']}\n"
        msg += f"→ {r['reason']}\n\n"

    if not results:
        msg += "No strong signals detected in latest scan."

    msg += "\n⚡ Powered by Groq (Cerebras when available) • Live NSE prices"

    print(msg)

    # Auto-post to Telegram if configured
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        import requests
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                          json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
            print("✅ Posted successfully to your Telegram channel!")
        except Exception as e:
            print("❌ Telegram post failed:", e)

if __name__ == "__main__":
    main()
