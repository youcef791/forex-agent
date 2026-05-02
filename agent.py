import os
import json
import logging
import requests
from groq import Groq
from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime

# Option B: environment variables
GROQ_KEY       = os.environ.get("GROQ_KEY")
NEWS_API_KEY   = os.environ.get("NEWS_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT")

PAIRS = [
    # Majors
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "NZD/USD",
    # Yen Crosses
    "EUR/JPY", "GBP/JPY", "AUD/JPY", "CHF/JPY", "CAD/JPY", "NZD/JPY"
]

client = Groq(api_key=GROQ_KEY)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

# ── Data Fetchers ────────────────────────────────────────
def fetch_news():
    """NewsAPI — fetches latest forex news headlines."""
    try:
        r = requests.get("https://newsapi.org/v2/everything", params={
            "q": "forex central bank interest rates inflation GDP BOJ JPY yen Fed ECB",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 15,
            "apiKey": NEWS_API_KEY
        }, timeout=10)
        articles = r.json().get("articles", [])
        result = [{"title": a["title"], "description": a["description"]} for a in articles]
        logging.info(f"Fetched {len(result)} news articles")
        return result
    except Exception as e:
        logging.warning(f"News fetch failed: {e}")
        return []

def fetch_calendar():
    """Forex Factory feed — returns this week's high-impact economic events."""
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        events = r.json()
        high = [e for e in events if e.get("impact") == "High"]
        clean = []
        for e in high[:12]:
            clean.append({
                "date":     e.get("date", ""),
                "currency": e.get("country", ""),
                "event":    e.get("title", ""),
                "forecast": e.get("forecast", "N/A"),
                "previous": e.get("previous", "N/A"),
            })
        logging.info(f"Fetched {len(clean)} high-impact events")
        return clean
    except Exception as e:
        logging.warning(f"Calendar fetch failed: {e}")
        return []

# ── AI Analysis ────────────────────────────────────────
def analyze_pair(pair: str, news: list, calendar: list) -> dict:
    is_yen_cross = "JPY" in pair and pair != "USD/JPY"
    yen_context = """
- Focus on BOJ yield curve control and policy shift signals
- Consider Japanese MOF/BOJ intervention risk
- Assess carry trade demand and risk sentiment
""" if is_yen_cross else ""

    prompt = f"""You are a professional Forex fundamental analyst.
Analyze {pair}. Today: {datetime.utcnow().strftime('%Y-%m-%d')}
{yen_context}
LATEST NEWS: {json.dumps(news[:8])}
EVENTS: {json.dumps(calendar)}
Respond ONLY with a valid JSON object:
{{
  "bias": "BULLISH" or "BEARISH" or "NEUTRAL",
  "confidence": "High" or "Medium" or "Low",
  "score": integer from -100 to 100,
  "drivers": ["list of drivers"],
  "risks": ["list of risks"],
  "timeframe": "Short-term" or "Medium-term",
  "summary": "2-3 sentence analysis"
}}"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "Return JSON only. No markdown, no preamble."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )
    text = response.choices[0].message.content.strip()
    return json.loads(text.replace("```json", "").replace("```", ""))

# ── Telegram Reporter ────────────────────────────────────
def send_telegram(text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": text, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        logging.warning(f"Telegram send failed: {e}")

def format_report(pair: str, data: dict) -> str:
    icon = "🟢" if data["bias"] == "BULLISH" else "🔴" if data["bias"] == "BEARISH" else "🟡"
    score = data["score"]
    bar = "🟩" * (abs(score) // 20) if score > 0 else "🟥" * (abs(score) // 20)
    return f"📊 *{pair} REPORT*\n{icon} *{data['bias']}* | Score: `{score:+}`\n{bar}\n\n📝 {data['summary']}\n\n⏱ {data['timeframe']}"

# ── Main Cycle ───────────────────────────────────────────
def run_analysis_cycle():
    logging.info("Starting analysis cycle...")
    send_telegram(f"⚙️ *Forex Agent Starting*")
    news = fetch_news()
    calendar = fetch_calendar()

    for pair in PAIRS:
        try:
            result = analyze_pair(pair, news, calendar)
            send_telegram(format_report(pair, result))
            logging.info(f"✓ {pair} analysis sent")
        except Exception as e:
            logging.error(f"✗ {pair} failed: {e}")

# ── Scheduler ────────────────────────────────────────────
if __name__ == "__main__":
    run_analysis_cycle()  # Initial run
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(run_analysis_cycle, "cron", hour="0,4,8,12,16,20", minute=0)
    logging.info("Scheduler active — running every 4 hours.")
    scheduler.start()
