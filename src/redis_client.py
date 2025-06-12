import redis.asyncio as redis
from loguru import logger
from .config import settings

class RedisClient:
    _pool = None

    @classmethod
    def get_pool(cls):
        if cls._pool is None:
            logger.info(f"Creating Redis connection pool for {settings.REDIS_URL}")
            cls._pool = redis.ConnectionPool.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                max_connections=20
            )
        return cls._pool

    @classmethod
    def get_client(cls) -> redis.Redis:
        return redis.Redis(connection_pool=cls.get_pool())

# Global client instance
redis_client = RedisClient.get_client()
