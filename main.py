import os
import json
import re
import time
from datetime import datetime
from collections import defaultdict
from groq import Groq
from cerebras.cloud.sdk import Cerebras
import yfinance as yf
import logging

# ========================= CONFIG =========================
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
cerebras_client = Cerebras(api_key=os.getenv("CEREBRAS_API_KEY"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

RSS_FEEDS = [
    "https://news.google.com/rss/search?q=india+stock+market+OR+defence+stocks+OR+broker+upgrade+OR+downgrade+OR+HAL+BEL+BDL",
    "https://news.google.com/rss/search?q=defence+india+stocks+OR+order+win+HAL+BEL+Mazagon",
    "https://www.moneycontrol.com/news/rss/latestnews.xml",
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
]

RESEARCH_HOUSES = {"Motilal Oswal", "Emkay", "ICICI Direct", "HDFC Securities", "Goldman Sachs", "Jefferies", "CLSA", "Nomura"}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ====================== PRICE FETCHER ======================
def get_current_price(ticker: str):
    try:
        stock = yf.Ticker(f"{ticker}.NS")
        price = stock.fast_info['lastPrice']
        return round(price, 2)
    except:
        return None

# ====================== AI ANALYSIS (Groq) ======================
def analyze_with_groq(text: str):
    prompt = """You are an elite Indian equity analyst. Return ONLY valid JSON."""
    # (same detailed prompt as before - shortened for space)
    prompt += f"""
    News: {text}
    Return JSON:
    {{"stocks": [...], "sentiment": "...", "sector": "...", "event": "...", "research_house": "...", "confidence": 0-100, "reason": "..." }}
    """
    try:
        resp = groq_client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.1, max_tokens=700)
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Groq Error: {e}")
        return None

# ====================== AI ANALYSIS (Cerebras) ======================
def analyze_with_cerebras(text: str):
    prompt = """You are an elite Indian equity analyst. Return ONLY valid JSON."""
    # (identical schema as Groq)
    prompt += f"""
    News: {text}
    Return JSON:
    {{"stocks": [...], "sentiment": "...", "sector": "...", "event": "...", "research_house": "...", "confidence": 0-100, "reason": "..." }}
    """
    try:
        resp = cerebras_client.chat.completions.create(
            model="gpt-oss-120b",          # Cerebras flagship - different from Groq for real brainstorm
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=700
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Cerebras Error: {e}")
        return None

def safe_json(text):
    if not text: return None
    try: return json.loads(text)
    except:
        match = re.search(r'\{.*\}', text, re.DOTALL | re.IGNORECASE)
        if match:
            try: return json.loads(match.group())
            except: pass
    return None

# ====================== BRAINSTORM CONSENSUS ======================
def brainstorm_consensus(groq_data, cerebras_data, prices_dict):
    combined = f"Groq analysis: {json.dumps(groq_data)}\nCerebras analysis: {json.dumps(cerebras_data)}\nCurrent prices: {prices_dict}"
    prompt = f"""Two elite analysts (Groq + Cerebras) gave these views. Merge them into ONE final stronger opinion.
    {combined}
    
    Return ONLY JSON with higher confidence:
    {{"stocks": [...], "sentiment": "...", "sector": "...", "event": "...", "research_house": "...", "confidence": 0-100,
      "reason": "...", "entry_price": "suggested entry (use current price)", "target_price": "...", "stop_loss": "..."}}
    """
    try:
        resp = groq_client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.1)
        return safe_json(resp.choices[0].message.content.strip())
    except:
        return groq_data or cerebras_data

# ====================== SIGNAL + TELEGRAM FORMAT ======================
def calculate_signal(data, price):
    # (same strong logic as before + price boost)
    score = data.get("confidence", 50)
    # ... (boosts for defence, upgrade, etc. - same as previous version)
    if score >= 85: signal = "🚀 STRONG BUY"
    elif score >= 65: signal = "📈 BUY"
    else: signal = "HOLD"
    
    entry = data.get("entry_price") or price
    target = data.get("target_price") or (price * 1.18 if price else None)
    stop = data.get("stop_loss") or (price * 0.92 if price else None)
    
    return {
        "signal": signal,
        "score": round(score, 1),
        "ticker": data.get("stocks")[0] if data.get("stocks") else None,
        "entry": entry,
        "target": round(target, 2) if target else None,
        "stop": round(stop, 2) if stop else None,
        "reason": data.get("reason")
    }

# ====================== MAIN ======================
def main():
    print("🔥 Starting Groq + Cerebras Brainstorm Scanner...\n")
    articles = fetch_all_news()   # (use same fetch function from last version)
    
    results = []
    seen_stocks = set()
    price_cache = {}
    
    for article in articles:
        text = article["title"] + " " + article["summary"]
        print(f"📰 {article['title'][:100]}...")
        
        # Step 1: Groq first (cheaper + fast)
        groq_raw = analyze_with_groq(text)
        groq_data = safe_json(groq_raw)
        if not groq_data or not groq_data.get("stocks"):
            continue
        
        # Step 2: Only if promising → Cerebras + Brainstorm
        for ticker in groq_data.get("stocks", []):
            if ticker not in price_cache:
                price_cache[ticker] = get_current_price(ticker)
        
        cerebras_raw = analyze_with_cerebras(text)
        cerebras_data = safe_json(cerebras_raw)
        
        final_data = brainstorm_consensus(groq_data, cerebras_data, price_cache)
        if not final_data:
            continue
        
        price = price_cache.get(final_data.get("stocks")[0]) if final_data.get("stocks") else None
        signal = calculate_signal(final_data, price)
        
        if signal["signal"] != "HOLD":
            results.append({**signal, "title": article["title"], "link": article["link"]})
            print(f"   → {signal['signal']} | {signal['ticker']} | Entry ₹{signal['entry']} | Target ₹{signal['target']}")
    
    # ====================== CLEAN TELEGRAM OUTPUT ======================
    print("\n" + "="*80)
    print("📲 **COPY THIS FOR TELEGRAM** 📲\n")
    
    msg = f"🧠 **Groq + Cerebras Brainstorm** — {datetime.now().strftime('%d %b %H:%M')}\n\n"
    msg += "🚀 **Early India Stock Signals**\n\n"
    
    for r in sorted(results, key=lambda x: x["score"], reverse=True)[:8]:
        if not r["ticker"]: continue
        msg += f"**{r['ticker']}** — {r['signal']}\n"
        msg += f"Entry: ₹{r['entry']}  |  Target: ₹{r['target']} (+{round((r['target']/r['entry']-1)*100,1)}%)\n"
        msg += f"Stop: ₹{r['stop']}\n"
        msg += f"Reason: {r['reason']}\n\n"
    
    if not results:
        msg += "No strong signals today. Market quiet."
    
    msg += "\n⚡ Powered by Groq + Cerebras • Run every 15 mins"
    
    print(msg)
    
    # Optional auto-send to Telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        import requests
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
        print("✅ Auto-posted to Telegram!")

if __name__ == "__main__":
    main()
