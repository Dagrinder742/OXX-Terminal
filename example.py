# Import necessary libraries
import urllib.request
import xml.etree.ElementTree as ET
import json
import time
import re
import nltk
from nltk.sentiment import SentimentIntensityAnalyzer

# Download necessary NLTK data
nltk.download('punkt', quiet=True)
nltk.download('vader_lexicon', quiet=True)

# Initialize sentiment analyzer
sia = SentimentIntensityAnalyzer()

def clean_html(raw_text):
    """Removes HTML tags, inline styles, and image sources from RSS descriptions."""
    if not raw_text:
        return ""
    # Remove HTML tags using a regular expression
    clean_text = re.sub(r'<[^<]+?>', '', raw_text)
    # Strip out extra whitespace or newlines left behind
    return ' '.join(clean_text.split())

class MobileApp:
    def __init__(self):
        self.articles = []

    def fetch_news(self, url="https://cointelegraph.com/rss"):
        """Fetches and parses the Cointelegraph RSS XML feed natively."""
        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()

            root = ET.fromstring(xml_data)
            channel = root.find('channel')
            if channel is None:
                return []

            articles = []
            for item in channel.findall('item'):
                title = item.find('title')
                link = item.find('link')
                pub_date = item.find('pubDate')
                description = item.find('description')

                title_text = title.text.strip() if title is not None and title.text else ""
                link_text = link.text.strip() if link is not None and link.text else ""
                date_text = pub_date.text.strip() if pub_date is not None and pub_date.text else ""

                # Extract and clean HTML from description text
                raw_desc = description.text if description is not None and description.text else ""
                desc_text = clean_html(raw_desc)

                articles.append({
                    "title": title_text,
                    "link": link_text,
                    "timestamp": date_text,
                    "description": desc_text
                })

            return articles
        except Exception as e:
            print(f"Fetch error: {e}")
            return []

    def analyze_sentiment(self, articles):
        for article in articles:
            sentiment = sia.polarity_scores(article['description'])
            article['sentiment'] = sentiment

            # Use a threshold instead of flattening everything <= 0
            compound = sentiment['compound']

            if compound >= 0.05:
                # Clearly Positive
                article['sentiment']['classification'] = "Bullish"
            elif compound <= -0.05:
                # Clearly Negative/Bearish
                article['sentiment']['classification'] = "Bearish"
            else:
                # Neutral / Macro chop
                article['sentiment']['classification'] = "Neutral"

        return articles

    def get_filtered_articles(self, articles):
        filtered_articles = []
        target_keywords = ["bitcoin", "btc", "sec", "liquidation", "etf", "solana"]

        for article in articles:
            combined_text = " ".join([article['title'], article['description']])
            if any(kw.lower() in combined_text.lower() for kw in target_keywords):
                filtered_articles.append(article)

        return filtered_articles

    def save_articles(self, articles, file_name='articles.json'):
        with open(file_name, 'w') as file:
            json.dump(articles, file, indent=2)
        print(f"Articles saved to {file_name}")

    def display_articles(self, articles):
        for article in articles:
            print(f"Title: {article['title']}")
            print(f"Link: {article['link']}")
            print(f"Timestamp: {article['timestamp']}")
            print(f"Description: {article['description'][:100]}...")
            print(f"Sentiment: {article['sentiment']}")
            print("-" * 40)

if __name__ == "__main__":
    app = MobileApp()
    url = "https://cointelegraph.com/rss"

    print("[*] Fetching live RSS feed...")
    articles = app.fetch_news(url)

    if articles:
        analyzed_articles = app.analyze_sentiment(articles)
        filtered_articles = app.get_filtered_articles(analyzed_articles)
        app.save_articles(filtered_articles)
        app.display_articles(filtered_articles)
    else:
        print("[!] No articles retrieved. Check network connection.")

    # Run the app every 10 minutes to fetch and analyze news
    while True:
        try:
            time.sleep(600)
            print("[*] Running scheduled RSS poll...")
            app = MobileApp()
            articles = app.fetch_news(url)
            if articles:
                analyzed_articles = app.analyze_sentiment(articles)
                filtered_articles = app.get_filtered_articles(analyzed_articles)
                app.save_articles(filtered_articles)
                app.display_articles(filtered_articles)
        except KeyboardInterrupt:
            print("\n[*] Script terminated by user.")
            break

