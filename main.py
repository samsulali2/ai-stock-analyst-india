import os
import json
import re
import feedparser
from groq import Groq

# Initialize Groq client
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ---------------------------
# Fetch News
# ---------------------------
def fetch_news():
    urls = [
        "https://news.google.com/rss/search?q=india+stock+market",
        "https://news.google.com/rss/search?q=defence+india+stocks",
        "https://news.google.com/rss/search?q=broker+upgrade+downgrade+india"
    ]

    articles = []

    for url in urls:
        feed = feedparser.parse(url)
        for entry in feed.entries[:5]:
            articles.append({
                "title": entry.title,
                "summary": entry.summary
            })

    return articles


# ---------------------------
# AI Analysis
# ---------------------------
def analyze_news(text):

    prompt = f"""
    You are a financial analyst.

    Analyze the news below and return ONLY valid JSON.
    Do NOT add any explanation or extra text.

    News: {text}

    Output:
    {{
        "sentiment": "positive/negative/neutral",
        "sector": "defence/bank/oil/other",
        "stocks": ["HAL", "BEL"],
        "event": "war/policy/upgrade/downgrade/other"
    }}
    """

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        print("❌ AI ERROR:", e)
        return None


# ---------------------------
# Safe JSON Extractor
# ---------------------------
def extract_json(text):

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


# ---------------------------
# Signal Generator
# ---------------------------
def generate_signal(data):

    sentiment = data.get("sentiment")
    event = data.get("event")
    sector = data.get("sector")

    if event == "war" and sector == "defence":
        return "🚀 STRONG BUY"

    if event == "upgrade":
        return "📈 BUY"

    if event == "downgrade":
        return "⚠️ SELL"

    return "HOLD"


# ---------------------------
# Main Runner
# ---------------------------
def main():

    news_list = fetch_news()

    for article in news_list:

        text = article["title"] + " " + article["summary"]

        print("\n📰", article["title"])

        ai_output = analyze_news(text)

        print("RAW AI:", ai_output)

        data = extract_json(ai_output)

        if not data:
            print("⚠️ Skipping invalid AI output")
            continue

        signal = generate_signal(data)

        # Optional: skip noise
        if signal == "HOLD":
            continue

        print("📊 Signal:", signal)
        print("🏷 Sector:", data.get("sector"))
        print("📈 Stocks:", data.get("stocks"))


if __name__ == "__main__":
    main()
