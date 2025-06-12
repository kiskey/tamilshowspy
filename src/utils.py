import re
import asyncio
from typing import Optional, Dict
from urllib.parse import urlencode, unquote
from loguru import logger
from nltk.stem import PorterStemmer
from rapidfuzz import fuzz
import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

# Initialize once
stemmer = PorterStemmer()

# Language normalization mapping
LANG_MAP = {
    "tam": "ta", "tel": "te", "hin": "hi", "eng": "en", "mal": "ml",
    "kan": "kn", "kor": "ko", "jap": "ja", "chi": "zh",
    # Add more mappings as needed
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
]
_user_agent_cycle = 0

def get_user_agent():
    global _user_agent_cycle
    agent = USER_AGENTS[_user_agent_cycle % len(USER_AGENTS)]
    _user_agent_cycle += 1
    return agent

def normalize_title(title: str) -> str:
    if not title:
        return ""
    title = title.lower()
    # Synonym replacement
    title = re.sub(r'\b(season|se)\b', 's', title)
    title = re.sub(r'\b(episode|ep)\b', 'e', title)
    # Remove special characters, keeping alphanumeric and spaces
    title = re.sub(r'[^a-z0-9\s]', '', title)
    # Stemming
    title = ' '.join([stemmer.stem(word) for word in title.split()])
    # Remove extra whitespace
    return ' '.join(title.split())

def is_valid_btih(btih: str) -> bool:
    return bool(re.fullmatch(r"[a-fA-F0-9]{40}|[a-zA-Z2-7]{32}", btih))

def parse_magnet(magnet_uri: str) -> Optional[Dict]:
    if not magnet_uri.startswith("magnet:?"):
        return None
    
    parts = magnet_uri.split("&")
    xt_part = next((p for p in parts if p.startswith("xt=urn:btih:")), None)
    if not xt_part:
        return None

    btih = xt_part.split(":")[2]
    if not is_valid_btih(btih):
        logger.warning(f"Invalid BTIH found: {btih}")
        return None

    dn_part = next((p for p in parts if p.startswith("dn=")), None)
    title = unquote(dn_part.split("=")[1]) if dn_part else ""

    return {"btih": btih, "title": title.replace('+', ' ')}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def fetch_trackers() -> list[str]:
    url = "https://ngosang.github.io/trackerslist/trackers_best.txt"
    logger.info("Fetching latest trackers...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as response:
                response.raise_for_status()
                text = await response.text()
                trackers = [tracker.strip() for tracker in text.split('\n') if tracker.strip()]
                logger.info(f"Successfully fetched {len(trackers)} trackers.")
                return trackers
    except Exception as e:
        logger.error(f"Failed to fetch trackers: {e}")
        return []

def append_trackers_to_magnet(magnet: str, trackers: list[str]) -> str:
    if not trackers:
        return magnet
    tracker_str = "&".join([f"tr={t}" for t in trackers])
    return f"{magnet}&{tracker_str}"
