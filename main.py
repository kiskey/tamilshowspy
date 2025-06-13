import sys
import asyncio
import httpx
from aiorun import run
from loguru import logger
from aiohttp import web
import nltk

from src.config import settings
from src.redis_client import redis_client, RedisClient
from src.api import routes
from src.crawler import run_crawler, worker
from src.utils import fetch_trackers

url_queue = asyncio.Queue()

logger.remove()
log_format = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)
logger.add(sys.stderr, level=settings.LOG_LEVEL.upper(), format=log_format)
logger.add("logs/app.log", rotation="10 MB", level="DEBUG", enqueue=True, serialize=True)

CHROME_CIPHERS = (
    "TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256"
    ":TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256:TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256"
    ":TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384:TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384"
    ":TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256:TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256"
    ":TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA:TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA"
    ":TLS_RSA_WITH_AES_128_GCM_SHA256:TLS_RSA_WITH_AES_256_GCM_SHA384"
    ":TLS_RSA_WITH_AES_128_CBC_SHA:TLS_RSA_WITH_AES_256_CBC_SHA"
)

async def scheduler_task(client: httpx.AsyncClient):
    logger.info("Scheduler started.")
    await update_trackers_task(client)
    await run_crawler(client, initial_run=True)
    while True:
        logger.info(f"Scheduler sleeping for {settings.CRAWL_INTERVAL} seconds.")
        await asyncio.sleep(settings.CRAWL_INTERVAL)
        await update_trackers_task(client)
        await run_crawler(client)

async def update_trackers_task(client: httpx.AsyncClient):
    logger.info("Running scheduled task: update trackers.")
    trackers = await fetch_trackers(client)
    if trackers:
        pipe = redis_client.pipeline()
        pipe.delete("trackers:latest")
        pipe.rpush("trackers:latest", *trackers)
        await pipe.execute()
        logger.info(f"Updated and cached {len(trackers)} trackers in Redis.")
    else:
        logger.warning("Tracker update failed, keeping old list.")

async def start_background_tasks(app: web.Application):
    logger.info("Application starting up...")

    limits = httpx.Limits(max_connections=settings.MAX_CONCURRENCY, max_keepalive_connections=settings.MAX_CONCURRENCY)
    context = httpx.create_default_ssl_context()
    context.set_ciphers(CHROME_CIPHERS)
    
    # --- THE CRITICAL COOKIE FIX ---
    # We pre-set the cookie that Cloudflare's JavaScript check expects to find.
    # This is the most important part of the fix.
    cookies = {"ips4_hasJS": "true"}
    logger.info(f"Initializing httpx client with preset cookie: {cookies}")
    # --- END OF FIX ---
    
    http_client = httpx.AsyncClient(
        http2=True,
        verify=context,
        limits=limits,
        follow_redirects=True,
        cookies=cookies # <-- Set the cookies on the client
    )
    app['http_client'] = http_client

    if settings.PURGE_ON_START:
        logger.warning("PURGE_ON_START is true. Flushing Redis.")
        await redis_client.flushdb()

    app['workers'] = [
        asyncio.create_task(worker(f"worker-{i}", url_queue, app['http_client']))
        for i in range(settings.MAX_CONCURRENCY)
    ]
    app['scheduler'] = asyncio.create_task(scheduler_task(app['http_client']))
    logger.info("Background tasks and workers started.")

async def cleanup_background_tasks(app: web.Application):
    logger.info("Application shutting down...")
    await app['http_client'].aclose()
    app['scheduler'].cancel()
    for task in app['workers']:
        task.cancel()
    await asyncio.gather(app['scheduler'], *app['workers'], return_exceptions=True)
    pool = RedisClient.get_pool()
    if pool:
        await pool.disconnect()
    logger.info("Cleanup complete.")

def main():
    app = web.Application()
    app.add_routes(routes)
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    logger.info(f"Starting web server on {settings.SERVER_HOST}:{settings.SERVER_PORT}")
    run(web._run_app(app, host=settings.SERVER_HOST, port=settings.SERVER_PORT), stop_on_unhandled_errors=True)

if __name__ == "__main__":
    main()
