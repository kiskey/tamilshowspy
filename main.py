import sys
import asyncio
import aiohttp
from aiorun import run
from loguru import logger
from aiohttp import web
import nltk

from src.config import settings
from src.redis_client import redis_client, RedisClient
from src.api import routes
from src.crawler import run_crawler, worker
from src.utils import fetch_trackers

# --- Globals ---
url_queue = asyncio.Queue()
http_session = None

# --- Logger Setup ---
logger.remove()
log_format = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)
logger.add(sys.stderr, level=settings.LOG_LEVEL.upper(), format=log_format)
logger.add("logs/app.log", rotation="10 MB", level="DEBUG", enqueue=True, serialize=True) # JSON logs

async def setup_nltk():
    try:
        nltk.data.find('stem/porter_stemmer.zip')
    except LookupError:
        logger.info("Downloading NLTK porter_stemmer...")
        nltk.download('porter_stemmer', quiet=True)
        logger.info("NLTK porter_stemmer downloaded.")

async def scheduler_task():
    """A simple async scheduler loop."""
    logger.info("Scheduler started.")
    # Initial tasks on startup
    await update_trackers_task()
    await run_crawler(initial_run=True)
    
    while True:
        logger.info(f"Scheduler sleeping for {settings.CRAWL_INTERVAL} seconds.")
        await asyncio.sleep(settings.CRAWL_INTERVAL)
        
        # Scheduled tasks
        await update_trackers_task()
        await run_crawler()
        
async def update_trackers_task():
    logger.info("Running scheduled task: update trackers.")
    trackers = await fetch_trackers()
    if trackers:
        pipe = redis_client.pipeline()
        pipe.delete("trackers:latest")
        pipe.rpush("trackers:latest", *trackers)
        await pipe.execute()
        logger.info(f"Updated and cached {len(trackers)} trackers in Redis.")
    else:
        logger.warning("Tracker update failed, keeping old list.")

async def start_background_tasks(app):
    """aiohttp startup signal handler."""
    global http_session
    
    logger.info("Application starting up...")
    
    # Initialize shared aiohttp client session
    connector = aiohttp.TCPConnector(limit_per_host=settings.MAX_CONCURRENCY)
    http_session = aiohttp.ClientSession(connector=connector)
    app['http_session'] = http_session

    if settings.PURGE_ON_START:
        logger.warning("PURGE_ON_START is true. Flushing Redis.")
        await redis_client.flushdb()

    await setup_nltk()

    # Create worker pool
    app['workers'] = [
        asyncio.create_task(worker(f"worker-{i}", url_queue, http_session))
        for i in range(settings.MAX_CONCURRENCY)
    ]
    
    # Start the scheduler
    app['scheduler'] = asyncio.create_task(scheduler_task())
    logger.info("Background tasks and workers started.")

async def cleanup_background_tasks(app):
    """aiohttp cleanup signal handler."""
    logger.info("Application shutting down...")
    
    # Close shared HTTP session
    await app['http_session'].close()

    # Cancel scheduler and workers
    app['scheduler'].cancel()
    for task in app['workers']:
        task.cancel()
    
    await asyncio.gather(app['scheduler'], *app['workers'], return_exceptions=True)
    
    # Close Redis pool
    await RedisClient.get_pool().disconnect()
    logger.info("Cleanup complete.")

def main():
    """Main entry point."""
    app = web.Application()
    app.add_routes(routes)
    
    # Register startup and cleanup handlers
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)

    logger.info(f"Starting web server on {settings.SERVER_HOST}:{settings.SERVER_PORT}")
    
    # aiorun will handle the main loop and graceful shutdown
    run(web._run_app(app, host=settings.SERVER_HOST, port=settings.SERVER_PORT), stop_on_unhandled_errors=True)

if __name__ == "__main__":
    main()
