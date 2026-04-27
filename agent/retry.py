"""Retry decorator with exponential backoff."""

from __future__ import annotations

import functools
import logging
import time

logger = logging.getLogger(__name__)


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable: tuple = (Exception,),
):
    """Sync retry decorator with exponential backoff."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except retryable as e:
                    if attempt == max_attempts - 1:
                        raise
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    logger.warning(
                        f"Retry {attempt + 1}/{max_attempts} for {func.__name__}: {e}. "
                        f"Waiting {delay:.1f}s"
                    )
                    time.sleep(delay)
        return wrapper
    return decorator
