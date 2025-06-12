import sys
import asyncio
import aiohttp
from aiorun import run
from loguru import logger
from aiohttp import web
import nltk # Keep the import, it's still used by utils.py

from src.config import settings
from src.redis_client import redis_client, RedisClient
from src.api import routes
from src.crawler import run_crawler, worker
from src.utils import fetch_trackers

# --- Globals ---
url_queue = asyncio.Queue()

# --- Logger Setup ---
logger.remove()
log_format = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)
logger.add(sys.stderr, level=settings.LOG_LEVEL.upper(), format=log_format)
logger.add("logs/app.log", rotation="10 MB", level="DEBUG", enqueue=True, serialize=True)

async def scheduler_task(session: aiohttp.ClientSession):
    """A simple async scheduler loop."""
    logger.info("Scheduler started.")
    await update_trackers_task(session)
    await run_crawler(session, initial_run=True)
    
    while True:
        logger.info(f"Scheduler sleeping for {settings.CRAWL_INTERVAL} seconds.")
        await asyncio.sleep(settings.CRAWL_INTERVAL)
        
        await update_trackers_task(session)
        await run_crawler(session)
        
async def update_trackers_task(session: aiohttp.ClientSession):
    logger.info("Running scheduled task: update trackers.")
    trackers = await fetch_trackers(session)
    if trackers:
        pipe = redis_client.pipeline()
        pipe.delete("trackers:latest")
        pipe.rpush("trackers:latest", *trackers)
        await pipe.execute()
        logger.info(f"Updated and cached {len(trackers)} trackers in Redis.")
    else:
        logger.warning("Tracker update failed, keeping old list.")

async def start_background_tasks(app: web.Application):
    """aiohttp startup signal handler."""
    logger.info("Application starting up...")
    
    # --- MODIFIED BLOCK ---
    # Create a TCPConnector with SSL verification disabled. This is a robust way to
    # prevent SSL/TLS handshake errors with sites behind Cloudflare or with
    # non-standard certificate chains.
    logger.warning("Creating aiohttp session with SSL verification disabled.")
    connector = aiohttp.TCPConnector(limit_per_host=settings.MAX_CONCURRENCY, ssl=False)
    # --- END MODIFIED BLOCK ---

    # Initialize shared aiohttp client session and store it in the app object
    http_session = aiohttp.ClientSession(connector=connector)
    app['http_session'] = http_session

    if settings.PURGE_ON_START:
        logger.warning("PURGE_ON_START is true. Flushing Redis.")
        await redis_client.flushdb()

    # Create worker pool, passing the session to each worker
    app['workers'] = [
        asyncio.create_task(worker(f"worker-{i}", url_queue, app['http_session']))
        for i in range(settings.MAX_CONCURRENCY)
    ]
    
    # Start the scheduler, passing the session
    app['scheduler'] = asyncio.create_task(scheduler_task(app['http_session']))
    logger.info("Background tasks and workers started.")

async def cleanup_background_tasks(app: web.Application):
    """aiohttp cleanup signal handler."""
    logger.info("Application shutting down...")
    
    await app['http_session'].close()

    app['scheduler'].cancel()
    for task in app['workers']:
        task.cancel()
    
    await asyncio.gather(app['scheduler'], *app['workers'], return_exceptions=True)
    
    pool = RedisClient.get_pool()
    if pool:
        await pool.disconnect()
    logger.info("Cleanup complete.")

def main():
    """Main entry point."""
    app = web.Application()
    app.add_routes(routes)
    
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)

    logger.info(f"Starting web server on {settings.SERVER_HOST}:{settings.SERVER_PORT}")
    
    run(web._run_app(app, host=settings.SERVER_HOST, port=settings.SERVER_PORT), stop_on_unhandled_errors=True)

if __name__ == "__main__":
    main()
