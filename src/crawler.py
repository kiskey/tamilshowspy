import asyncio
import re
import time
from urllib.parse import urlparse
from loguru import logger
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential
import aiohttp

from .config import settings
from .redis_client import redis_client
from .utils import get_user_agent
from .parser import process_thread

def _get_request_headers(url: str) -> dict:
    """
    Builds a dictionary of headers to mimic a real browser request.
    This is crucial for avoiding 403 Forbidden errors from anti-bot systems.
    """
    # Use the base domain of the forum as a plausible Referer.
    parsed_uri = urlparse(settings.FORUM_URL)
    referer = f"{parsed_uri.scheme}://{parsed_uri.netloc}/"

    headers = {
        "User-Agent": get_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "DNT": "1", # Do Not Track
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Sec-Ch-Ua": '"Not/A)Brand";v="99", "Google Chrome";v="115", "Chromium";v="115"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
    }
    return headers

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
async def get_page_content(url, session: aiohttp.ClientSession):
    # Get a full set of realistic browser headers for the request.
    headers = _get_request_headers(url)

    await asyncio.sleep(settings.REQUEST_THROTTLE_MS / 1000)
    try:
        async with session.get(url, headers=headers, timeout=30) as response:
            if response.status == 404:
                logger.warning(f"Page not found (404): {url}")
                return None
            
            # This will now raise an exception for 403, triggering the tenacity retry.
            response.raise_for_status() 
            return await response.text()
            
    except asyncio.TimeoutError:
        logger.error(f"Timeout while fetching {url}")
    except aiohttp.ClientError as e:
        logger.error(f"HTTP request failed for {url}: {e}")
        raise
    except Exception as e:
        logger.error(f"An unexpected error occurred in get_page_content for {url}: {e}", exc_info=True)
        raise

async def crawl_forum_page(page_num: int, session: aiohttp.ClientSession, url_queue: asyncio.Queue):
    if page_num == 1:
        page_url = settings.FORUM_URL
    else:
        # Ensure the base URL ends with a slash before appending page number
        base_url = settings.FORUM_URL.rstrip('/')
        page_url = f"{base_url}/page/{page_num}/"

    logger.info(f"Crawling forum page: {page_url}")
    html = await get_page_content(page_url, session)
    if not html:
        return False  # Stop crawling this path

    soup = BeautifulSoup(html, 'html.parser')
    thread_links = soup.find_all('a', href=re.compile(r'/forums/topic/\d+'), attrs={'data-ipshover': ''})
    
    if not thread_links:
        logger.info(f"No more thread links found on page {page_num}. Ending crawl for this run.")
        return False

    for link in thread_links:
        thread_url = link['href']
        thread_id_match = re.search(r'/topic/(\d+)-', thread_url)
        if not thread_id_match:
            continue
        thread_id = thread_id_match.group(1)

        # Check if recently visited
        last_visited_str = await redis_client.hget(f"thread:{thread_id}", "last_visited")
        if last_visited_str:
            last_visited = int(last_visited_str)
            if time.time() - last_visited < settings.THREAD_REVISIT_HOURS * 3600:
                logger.trace(f"Skipping recently visited thread: {thread_id}")
                continue
        
        # Use a Redis set for this session to avoid queueing duplicates
        if not await redis_client.sismember("session:crawled_urls", thread_url):
            await url_queue.put(thread_url)
            await redis_client.sadd("session:crawled_urls", thread_url)

    return True

async def worker(name: str, url_queue: asyncio.Queue, session: aiohttp.ClientSession):
    """Worker to process URLs from the queue."""
    while True:
        try:
            url = await url_queue.get()
            logger.debug(f"Worker {name} processing {url}")
            await process_thread(url, session)
        except Exception as e:
            logger.error(f"Worker {name} caught an exception: {e}", exc_info=True)
        finally:
            url_queue.task_done()
            
async def run_crawler(session: aiohttp.ClientSession, initial_run=False):
    """Main crawler function to be scheduled."""
    from main import url_queue
    
    logger.info("Starting crawler run...")
    # Clear session's crawled set
    await redis_client.delete("session:crawled_urls")

    max_pages = settings.INITIAL_PAGES if initial_run else 1000 # Crawl more on startup

    for page_num in range(1, max_pages + 1):
        if not await crawl_forum_page(page_num, session, url_queue):
            break
    
    logger.info("Crawler run finished. URLs queued for processing.")
