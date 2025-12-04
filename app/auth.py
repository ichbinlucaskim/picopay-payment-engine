from fastapi import Header, HTTPException, status, Security
from fastapi.security import APIKeyHeader
import os
import logging

logger = logging.getLogger(__name__)

# API Key configuration
API_KEY_HEADER_NAME = "X-API-Key"
APP_API_KEY = os.getenv("APP_API_KEY")

# Create API Key header security scheme
api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)


def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """
    FastAPI dependency to verify API key from X-API-Key header.
    
    Args:
        api_key: API key from X-API-Key header
        
    Returns:
        str: The validated API key
        
    Raises:
        HTTPException: 401 Unauthorized if API key is missing or invalid
    """
    # Check if API key is configured
    if not APP_API_KEY:
        logger.warning("APP_API_KEY environment variable is not set. API key authentication is disabled.")
        # In production, you might want to raise an error here
        # For now, we'll allow requests if no key is configured (development mode)
        return api_key or ""
    
    # Check if API key is provided
    if not api_key:
        logger.warning("API key missing from request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is required. Please provide X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    # Validate API key
    if api_key != APP_API_KEY:
        logger.warning(f"Invalid API key attempted: {api_key[:8]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    logger.debug("API key validated successfully")
    return api_key

