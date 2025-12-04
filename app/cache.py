from redis import Redis
from typing import Optional
import os
import json
import logging

logger = logging.getLogger(__name__)

# Redis connection configuration
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

# Cache TTL in seconds (24 hours)
CACHE_TTL = int(os.getenv("CACHE_TTL", "86400"))


def get_redis_client() -> Redis:
    """
    Get Redis client instance.
    
    Returns:
        Redis: Redis client instance
    """
    return Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5
    )


def get_cache_key(idempotency_key: str) -> str:
    """
    Generate cache key for idempotency key.
    
    Args:
        idempotency_key: UUID string of the idempotency key
        
    Returns:
        str: Cache key
    """
    return f"idempotency:{idempotency_key}"


def get_cached_transaction(idempotency_key: str) -> Optional[dict]:
    """
    Retrieve cached transaction from Redis.
    
    Args:
        idempotency_key: UUID string of the idempotency key
        
    Returns:
        Optional[dict]: Cached transaction data if found, None otherwise
    """
    try:
        redis_client = get_redis_client()
        cache_key = get_cache_key(idempotency_key)
        cached_data = redis_client.get(cache_key)
        
        if cached_data:
            logger.debug(f"Cache hit for Idempotency-Key={idempotency_key}")
            return json.loads(cached_data)
        else:
            logger.debug(f"Cache miss for Idempotency-Key={idempotency_key}")
            return None
    except Exception as e:
        # Log error but don't fail the request - fall back to database
        logger.warning(f"Redis cache error: {str(e)}. Falling back to database.")
        return None


def cache_transaction(idempotency_key: str, transaction_data: dict) -> bool:
    """
    Cache transaction result in Redis.
    
    Args:
        idempotency_key: UUID string of the idempotency key
        transaction_data: Dictionary containing transaction response data
        
    Returns:
        bool: True if cached successfully, False otherwise
    """
    if not idempotency_key:
        return False
        
    try:
        redis_client = get_redis_client()
        cache_key = get_cache_key(idempotency_key)
        
        # Serialize transaction data to JSON
        cached_value = json.dumps(transaction_data)
        
        # Store with TTL
        redis_client.setex(cache_key, CACHE_TTL, cached_value)
        logger.info(
            f"Cached transaction for Idempotency-Key={idempotency_key}, "
            f"TTL={CACHE_TTL}s"
        )
        return True
    except Exception as e:
        # Log error but don't fail the request
        logger.warning(f"Failed to cache transaction in Redis: {str(e)}")
        return False

