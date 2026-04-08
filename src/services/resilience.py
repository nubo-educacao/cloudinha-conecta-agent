import logging
import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger("resilience")

# Exceções retriáveis (rede e API transitórias)
RETRIABLE_EXCEPTIONS = (
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.ConnectError,
    ConnectionError,
    TimeoutError,
    OSError,
)


def retry_with_backoff(retries: int = 3, min_delay: float = 1.0, max_delay: float = 10.0):
    """Decorator: retry com backoff exponencial para chamadas LLM e Supabase."""
    return retry(
        stop=stop_after_attempt(retries),
        wait=wait_exponential(multiplier=1, min=min_delay, max=max_delay),
        retry=retry_if_exception_type(RETRIABLE_EXCEPTIONS),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
