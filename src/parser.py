import re
import time
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
import guessit
from loguru import logger

from .redis_client import redis_client
from .utils import normalize_title, parse_magnet, LANG_MAP

# Regex fallback for parsing torrent titles
# Example: The Great Indian Kitchen (2023) S01E01-03 [1080p HEVC - x265 - 2.1GB - ESub - Tamil + Telugu]
FALLBACK_REGEX = re.compile(
    r'(?P<title>.+?)\s+'
    r'(?:\((?P<year>\d{4})\)\s+)?'
    r'(?:S(?P<season>\d{1,2}))?\s*'
    r'(?:E(?P<episodeStart>\d{1,3}))?'
    r'(?:-(?:E)?(?P<episodeEnd>\d{1,3}))?.*?'
    r'\[(?P<resolution>\d{3,4}p).*?'
    r'(?P<language>(?:tam|tel|hin|eng|mal|kan)(?:\s?[+]\s?[a-z]{3})*)\s*.*?\]',
    re.IGNORECASE
)

async def process_thread(thread_url: str, session):
    from .crawler import get_page_content
    
    thread_id_match = re.search(r'/topic/(\d+)-', thread_url)
    if not thread_id_match:
        logger.warning(f"Could not extract thread ID from URL: {thread_url}")
        return
    thread_id = thread_id_match.group(1)

    try:
        html = await get_page_content(thread_url, session)
        if not html:
            return

        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract all magnet links
        magnet_links = {a['href'] for a in soup.find_all('a', href=re.compile(r'^magnet:\?xt=urn:btih:'))}

        if not magnet_links:
            logger.debug(f"No magnet links found in thread {thread_id}")
            return
            
        logger.info(f"Found {len(magnet_links)} magnet links in thread {thread_id}")

        for magnet in magnet_links:
            await parse_and_persist_magnet(magnet, thread_id)
        
        # Update last visited time for the thread
        await redis_client.hset(f"thread:{thread_id}", "last_visited", int(time.time()))
        
    except Exception as e:
        logger.error(f"Error processing thread {thread_url}: {e}")
        await redis_client.rpush("error_queue", f"Error in thread {thread_id}: {e}")

def parse_title(title: str) -> Optional[Dict[str, Any]]:
    # Primary: guessit
    guess = guessit.guessit(title)
    
    # Fallback: regex
    if not guess.get('season') or not guess.get('episode'):
        match = FALLBACK_REGEX.search(title)
        if match:
            data = match.groupdict()
            guess['title'] = data.get('title', guess.get('title', '')).strip()
            guess['year'] = data.get('year') or guess.get('year')
            guess['season'] = data.get('season') or guess.get('season')
            guess['episode'] = data.get('episodeStart') or guess.get('episode')
            guess['episode_end'] = data.get('episodeEnd')
            guess['screen_size'] = data.get('resolution') or guess.get('screen_size')
            
            # Language from regex is often more reliable
            lang_str = data.get('language', '')
            if lang_str:
                langs = re.split(r'\s?[+]\s?', lang_str.lower())
                guess['language'] = [LANG_MAP.get(lang.strip(), lang.strip()) for lang in langs if lang.strip()]

    if not guess.get('title') or not guess.get('season') or not guess.get('episode'):
        logger.warning(f"Failed to parse required fields from title: {title}")
        return None

    return guess

async def parse_and_persist_magnet(magnet_uri: str, thread_id: str):
    magnet_info = parse_magnet(magnet_uri)
    if not magnet_info:
        return

    parsed_data = parse_title(magnet_info['title'])
    if not parsed_data:
        return

    title = parsed_data.get('title')
    year = parsed_data.get('year')
    season = parsed_data.get('season')
    ep_start = parsed_data.get('episode')
    ep_end = parsed_data.get('episode_end') or ep_start

    if not all([title, season, ep_start]):
        return
        
    normalized_show_title = normalize_title(f"{title} {year}" if year else title)
    show_id = f"tb:{normalized_show_title.replace(' ', '_')}"
    
    # Prepare metadata
    languages = parsed_data.get('language', [])
    if isinstance(languages, str): languages = [languages]
    normalized_langs = sorted(list({LANG_MAP.get(lang, lang) for lang in languages}))
    
    resolution = parsed_data.get('screen_size', 'SD')
    
    pipe = redis_client.pipeline()
    
    # 1. Update Show metadata
    pipe.hsetnx(f"show:{show_id}", "name", f"{title}{f' ({year})' if year else ''}")
    pipe.hsetnx(f"show:{show_id}", "id", show_id)
    pipe.sadd(f"show:{show_id}:langs", *normalized_langs)
    pipe.sadd("catalog:series", show_id)

    # 2. Add to season ZSET
    season_key = f"season:{show_id}:{season}"
    timestamp = int(time.time())
    member = f"{thread_id}:{resolution}:{','.join(normalized_langs)}"
    
    # Store episodes in this season
    for ep in range(int(ep_start), int(ep_end) + 1):
        # 3. Store Episode data
        episode_key = f"episode:{season_key}:{ep}"
        
        episode_data = {
            "magnet": magnet_uri,
            "title": magnet_info['title'],
            "resolution": resolution,
            "languages": ",".join(normalized_langs),
            "video_codec": parsed_data.get('video_codec', 'N/A'),
            "audio_codec": parsed_data.get('audio_codec', 'N/A'),
            "size": str(parsed_data.get('size', 'N/A')),
            "source": parsed_data.get('source', 'N/A'),
            "thread_id": thread_id,
            "timestamp": timestamp,
        }
        pipe.hset(episode_key, mapping=episode_data)
        pipe.zadd(season_key, {f"{ep}:{resolution}": timestamp})


    logger.info(f"Persisting {title} S{season:02d}E{ep_start}-{ep_end}")
    await pipe.execute()
