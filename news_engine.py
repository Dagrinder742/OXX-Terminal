import urllib.request
import xml.etree.ElementTree as ET
import json
import re
import nltk
import logging
import asyncio
from nltk.sentiment import SentimentIntensityAnalyzer

# Sub-engine Logging
logger = logging.getLogger("NewsEngine")

# NLTK Prerequisites
try:
    nltk.download('punkt', quiet=True)
    nltk.download('vader_lexicon', quiet=True)
except Exception:
    pass

sia = SentimentIntensityAnalyzer()

def clean_html(raw_text):
    if not raw_text: return ""
    clean_text = re.sub(r'<[^<]+?>', '', raw_text)
    return ' '.join(clean_text.split())

class NewsEngine:
    def __init__(self, cache_file='articles.json'):
        self.cache_file = cache_file
        self.feed_url = "https://cointelegraph.com/rss"
        self.keywords = ["bitcoin", "btc", "sec", "liquidation", "etf", "solana", "fed", "inflation"]

    def fetch_and_process(self):
        try:
            req = urllib.request.Request(self.feed_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()

            root = ET.fromstring(xml_data)
            channel = root.find('channel')
            if channel is None: return False

            articles = []
            for item in channel.findall('item'):
                title = item.find('title').text.strip() if item.find('title') is not None else ""
                desc = clean_html(item.find('description').text if item.find('description') is not None else "")
                combined = f"{title} {desc}".lower()
                
                if any(kw in combined for kw in self.keywords):
                    sentiment = sia.polarity_scores(desc)
                    compound = sentiment['compound']
                    articles.append({
                        "title": title,
                        "timestamp": item.find('pubDate').text.strip() if item.find('pubDate') is not None else "",
                        "classification": "Bullish" if compound >= 0.05 else "Bearish" if compound <= -0.05 else "Neutral",
                        "sentiment_score": compound,
                        "snippet": desc[:200] + "..." if len(desc) > 200 else desc
                    })

            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(articles[:15], f, indent=2)
            return True
        except Exception as e:
            logger.error(f"NewsEngine Cycle Error: {e}")
            return False

async def background_news_poller(interval=600):
    engine = NewsEngine()
    while True:
        try:
            logger.info("NewsEngine: Synchronizing RSS Wire...")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, engine.fetch_and_process)
        except Exception as e:
            logger.error(f"NewsEngine Loop Failure: {e}")
        await asyncio.sleep(interval)
