import os
import json
import re
import asyncio
import aiohttp
import feedparser
from datetime import datetime
from collections import defaultdict
from groq import Groq
import logging

# ========================= CONFIG =========================
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# High-signal RSS feeds (add more as needed)
RSS_FEEDS = [
    "https://news.google.com/rss/search?q=india+stock+market+OR+defence+stocks+OR+broker+upgrade+OR+downgrade",
    "https://news.google.com/rss/search?q=defence+india+stocks+HAL+BEL+BDL+Mazagon",
    "https://www.moneycontrol.com/news/rss/latestnews.xml",  # Broad + upgrades often appear
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",  # ET Markets
    # Add Trendlyne / broker-specific if they expose RSS (or scrape below)
]

# Research houses known for timely India coverage
RESEARCH_HOUSES = {"Motilal Oswal", "Emkay", "ICICI Direct", "HDFC Securities", "Goldman Sachs", "Jefferies", "CLSA", "Nomura"}

# Optional: Webhook for instant alerts (Telegram/Discord)
WEBHOOK_URL = os.getenv("ALERT_WEBHOOK")  # e.g. Telegram bot

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ====================== FETCHING ======================
async def fetch_feed(session, url):
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status == 200:
                content = await resp.text()
                return feedparser.parse(content)
    except Exception as e:
        logging.error(f"Feed error {url}: {e}")
    return None

async def fetch_all_news(limit_per_feed=8):
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_feed(session, url) for url in RSS_FEEDS]
        feeds = await asyncio.gather(*tasks, return_exceptions=True)
    
    articles = []
    seen = set()
    for feed in feeds:
        if isinstance(feed, Exception) or not feed:
            continue
        for entry in feed.entries[:limit_per_feed]:
            title = entry.title.strip()
            summary = getattr(entry, 'summary', '') or getattr(entry, 'description', '')
            link = getattr(entry, 'link', '')
            key = title.lower()
            if key in seen:
                continue
            seen.add(key)
            articles.append({
                "title": title,
                "summary": summary,
                "link": link,
                "published": getattr(entry, 'published', '')
            })
    return articles[:50]  # Cap for cost/speed

# ====================== AI ANALYSIS ======================
def analyze_news(text: str):
    prompt = f"""You are an elite Indian equity research analyst specializing in early momentum signals.
Analyze the news and return **ONLY** valid JSON (no extra text, no markdown).

News:
{text}

Output schema (strict):
{{
  "stocks": ["HAL", "BEL", "BDL", ...],          // NSE tickers only, empty if none
  "sentiment": "positive" | "negative" | "neutral" | "very_positive",
  "sector": "defence" | "banking" | "oil_gas" | "pharma" | "it" | "auto" | "other",
  "event": "upgrade" | "downgrade" | "war_geopolitical" | "order_win" | "policy" | "results" | "other",
  "research_house": "Motilal Oswal" | "Emkay" | ... | null,
  "confidence": 0-100,                           // How strong is the signal?
  "reason": "short 1-sentence explanation"
}}

Focus on actionable moves: broker upgrades/downgrades, defence orders, geopolitical tailwinds, large contracts.
Extract every mentioned ticker accurately.
"""
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",  # Or try mixtral, gemma2, or faster Llama-4 variant if available on Groq
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=800,
            response_format={"type": "json_object"}  # Groq supports this on many models
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"AI Error: {e}")
        return None

def safe_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except:
        match = re.search(r'\{.*\}', text, re.DOTALL | re.IGNORECASE)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
    return None

# ====================== SIGNAL ENGINE ======================
def calculate_signal(data: dict) -> dict:
    if not data:
        return {"signal": "HOLD", "score": 0}
    
    sent = data.get("sentiment", "").lower()
    event = data.get("event", "").lower()
    sector = data.get("sector", "").lower()
    conf = data.get("confidence", 50)
    house = data.get("research_house")
    
    score = conf
    
    # Boosts
    if event in ("upgrade", "order_win", "war_geopolitical", "policy"):
        score += 30
    if sent in ("very_positive", "positive"):
        score += 25
    if sector == "defence" and event in ("war_geopolitical", "order_win"):
        score += 40
    if house and house in RESEARCH_HOUSES:
        score += 20
    
    # Penalties
    if event == "downgrade":
        score -= 50
    if sent == "negative":
        score -= 30
    
    score = max(0, min(100, score))
    
    if score >= 85:
        signal = "🚀 STRONG BUY"
    elif score >= 65:
        signal = "📈 BUY"
    elif event == "downgrade" or score <= 25:
        signal = "⚠️ SELL"
    else:
        signal = "HOLD"
    
    return {
        "signal": signal,
        "score": score,
        "stocks": data.get("stocks", []),
        "sector": sector,
        "event": event,
        "house": house,
        "reason": data.get("reason")
    }

# ====================== CLUSTERING (Multi-article conviction) ======================
def cluster_signals(all_results):
    by_stock = defaultdict(list)
    for res in all_results:
        for ticker in res.get("stocks", []):
            by_stock[ticker.upper()].append(res)
    
    clustered = []
    for ticker, signals in by_stock.items():
        avg_score = sum(s["score"] for s in signals) / len(signals)
        top_signal = max(signals, key=lambda x: x["score"])
        clustered.append({
            "ticker": ticker,
            "avg_score": round(avg_score, 1),
            "strongest_signal": top_signal["signal"],
            "count": len(signals),
            "reasons": [s["reason"] for s in signals[:3]]
        })
    return sorted(clustered, key=lambda x: x["avg_score"], reverse=True)

# ====================== MAIN ======================
async def main():
    print("🔍 Fetching fresh news...")
    articles = await fetch_all_news()
    print(f"📥 Got {len(articles)} articles")
    
    results = []
    for article in articles:
        text = f"{article['title']} {article['summary']}"
        print(f"\n📰 {article['title'][:120]}...")
        
        raw = analyze_news(text)
        data = safe_json(raw)
        if not data:
            continue
            
        signal_data = calculate_signal(data)
        if signal_data["signal"] == "HOLD" and signal_data["score"] < 50:
            continue
            
        result = {
            **signal_data,
            "title": article["title"],
            "link": article["link"]
        }
        results.append(result)
        
        print(f"   → {signal_data['signal']} | Score: {signal_data['score']} | Stocks: {data.get('stocks')} | {data.get('reason')}")
    
    # Cluster for higher-conviction ideas
    clusters = cluster_signals(results)
    
    print("\n" + "="*80)
    print("🎯 TOP SIGNALS (Clustered by Stock)")
    for c in clusters[:10]:
        print(f"{c['strongest_signal']:12} | {c['ticker']:6} | Score {c['avg_score']} | {c['count']} mentions")
        for r in c['reasons']:
            print(f"   └─ {r}")
    
    # Optional: Save + alert
    timestamp = datetime.now().isoformat()
    with open(f"signals_{timestamp[:10]}.json", "w") as f:
        json.dump({"timestamp": timestamp, "signals": results, "clusters": clusters}, f, indent=2)
    
    if WEBHOOK_URL and clusters:
        # Simple alert (expand as needed)
        top = clusters[0]
        payload = {"content": f"🚨 Early Signal: {top['strongest_signal']} {top['ticker']} (Score {top['avg_score']})"}
        async with aiohttp.ClientSession() as s:
            await s.post(WEBHOOK_URL, json=payload)

if __name__ == "__main__":
    asyncio.run(main())
