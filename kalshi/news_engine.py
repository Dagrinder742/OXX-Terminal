import requests
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
    logger.info("NLTK prerequisites verified successfully.")
except Exception as e:
    logger.error(f"Failed to download NLTK prerequisites: {e}")

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
            # Use requests with a standard browser user-agent to bypass basic bot filters
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            response = requests.get(self.feed_url, headers=headers, timeout=10)

            if response.status_code != 200:
                logger.error(f"NewsEngine HTTP Error: Status code {response.status_code}")
                return False

            root = ET.fromstring(response.content)
            channel = root.find('channel')
            if channel is None: 
                logger.error("NewsEngine Error: Invalid RSS structure (no channel found)")
                return False

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
                        "sentiment_score": round(compound, 4),
                        "snippet": desc[:200] + "..." if len(desc) > 200 else desc
                    })

            if articles:
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(articles[:15], f, indent=2)
                logger.info(f"NewsEngine: Successfully cached {len(articles[:15])} fresh articles.")
                return True
            else:
                logger.warning("NewsEngine: Parsed feed, but zero articles matched keywords.")
                return False

        except ET.ParseError as pe:
            logger.error(f"NewsEngine XML Parse Error (Possible Cloudflare block): {pe}")
            return False
        except Exception as e:
            logger.error(f"NewsEngine Cycle Error: {e}")
            return False

async def background_news_poller(interval=600):
    engine = NewsEngine()
    # Run once immediately on startup so articles.json updates right away
    await asyncio.to_thread(engine.fetch_and_process)

    while True:
        try:
            logger.info("NewsEngine: Synchronizing RSS Wire...")
            await asyncio.to_thread(engine.fetch_and_process)
        except Exception as e:
            logger.error(f"NewsEngine Loop Failure: {e}")
        await asyncio.sleep(interval)
