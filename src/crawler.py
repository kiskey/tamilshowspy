import asyncio
import re
import time
import traceback
from urllib.parse import urlparse
from loguru import logger
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential
import httpx

from .config import settings
from .redis_client import redis_client
from .utils import get_user_agent
from .parser import process_thread

def _get_request_headers(url: str) -> dict:
    # --- UPDATED TO MATCH BROWSER HEADERS ---
    # These headers are now a near-perfect mimic of the ones you provided.
    parsed_uri = urlparse(settings.FORUM_URL)
    referer = f"{parsed_uri.scheme}://{parsed_uri.netloc}/"

    headers = {
        'authority': parsed_uri.netloc,
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-encoding': 'gzip, deflate, br, zstd',
        'accept-language': 'en-US,en;q=0.9',
        'priority': 'u=0, i',
        'sec-ch-ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'none', # 'none' is for the initial request, which is fine
        'sec-fetch-user': '?1',
        'upgrade-insecure-requests': '1',
        'user-agent': get_user_agent(), # We can still rotate this
    }
    return headers
    # --- END OF UPDATE ---

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
async def get_page_content(url: str, client: httpx.AsyncClient):
    headers = _get_request_headers(url)
    await asyncio.sleep(settings.REQUEST_THROTTLE_MS / 1000)
    try:
        response = await client.get(url, headers=headers, timeout=30) # No need for follow_redirects here, client is configured
        if response.status_code == 404:
            logger.warning(f"Page not found (404): {url}")
            return None
        response.raise_for_status()
        return response.text
    except httpx.TimeoutException:
        logger.error(f"Timeout while fetching {url}")
        raise
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP Status Error for {url}: {e.response.status_code}", exc_info=True)
        # Log the response body for 403 errors to see if Cloudflare gives a reason
        if e.response.status_code == 403:
            logger.error(f"403 Forbidden - Response body: {e.response.text[:500]}")
        raise
    except httpx.RequestError as e:
        logger.error(f"HTTP Request Error for {url}", exc_info=True)
        raise
    except Exception:
        logger.error(f"An unexpected error occurred in get_page_content for {url}", exc_info=True)
        raise

# ... The rest of this file (crawl_forum_page, worker, run_crawler) is unchanged ...
async def crawl_forum_page(page_num: int, client: httpx.AsyncClient, url_queue: asyncio.Queue):
    if page_num == 1:
        page_url = settings.FORUM_URL
    else:
        base_url = settings.FORUM_URL.rstrip('/')
        page_url = f"{base_url}/page/{page_num}/"
    logger.info(f"Crawling forum page: {page_url}")
    html = await get_page_content(page_url, client)
    if not html:
        return False
    soup = BeautifulSoup(html, 'html.parser')
    thread_links = soup.find_all('a', href=re.compile(r'/forums/topic/\d+'), attrs={'data-ipshover': ''})
    if not thread_links:
        logger.info(f"No more thread links found on page {page_num}. Ending crawl for this run.")
        return False
    for link in thread_links:
        thread_url = link['href']
        thread_id_match = re.search(r'/topic/(\d+)-', thread_url)
        if not thread_id_match: continue
        thread_id = thread_id_match.group(1)
        last_visited_str = await redis_client.hget(f"thread:{thread_id}", "last_visited")
        if last_visited_str:
            last_visited = int(last_visited_str)
            if time.time() - last_visited < settings.THREAD_REVISIT_HOURS * 3600:
                logger.trace(f"Skipping recently visited thread: {thread_id}")
                continue
        if not await redis_client.sismember("session:crawled_urls", thread_url):
            await url_queue.put(thread_url)
            await redis_client.sadd("session:crawled_urls", thread_url)
    return True

async def worker(name: str, url_queue: asyncio.Queue, client: httpx.AsyncClient):
    while True:
        try:
            url = await url_queue.get()
            logger.debug(f"Worker {name} processing {url}")
            await process_thread(url, client)
        except Exception:
            logger.error(f"Worker {name} caught an unhandled exception.", exc_info=True)
        finally:
            url_queue.task_done()

async def run_crawler(client: httpx.AsyncClient, initial_run=False):
    from main import url_queue
    logger.info("Starting crawler run...")
    await redis_client.delete("session:crawled_urls")
    max_pages = settings.INITIAL_PAGES if initial_run else 1000
    for page_num in range(1, max_pages + 1):
        if not await crawl_forum_page(page_num, client, url_queue):
            break
    logger.info("Crawler run finished. URLs queued for processing.")
