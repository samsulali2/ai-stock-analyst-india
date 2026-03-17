import os
import json
import feedparser
from groq import Groq

# Initialize Groq
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

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


def analyze_news(text):

    prompt = f"""
    Analyze this news and return JSON:

    News: {text}

    Output format:
    {{
        "sentiment": "positive/negative/neutral",
        "sector": "",
        "stocks": [],
        "event": "war/policy/upgrade/downgrade/other"
    }}
    """

    response = client.chat.completions.create(
        model="llama3-70b-8192",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content


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


def main():

    news_list = fetch_news()

    for article in news_list:

        text = article["title"] + " " + article["summary"]

        print("\n📰", article["title"])

        ai_output = analyze_news(text)

        try:
            data = json.loads(ai_output)
        except:
            continue

        signal = generate_signal(data)

        print("📊 Signal:", signal)
        print("Stocks:", data.get("stocks"))


if __name__ == "__main__":
    main()
