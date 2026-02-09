"""Retry decorator with exponential backoff"""
import time
import logging
from functools import wraps
from typing import Callable, Type, Tuple

logger = logging.getLogger(__name__)


def retry(
    max_attempts: int = 3,
    delay: float = 2.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """
    Декоратор для повторных попыток с экспоненциальной задержкой.
    
    Args:
        max_attempts: Максимальное количество попыток (включая первую)
        delay: Начальная задержка в секундах
        backoff: Множитель для увеличения задержки (2.0 = каждый раз *2)
        exceptions: Кортеж исключений, при которых делать retry
    
    Example:
        @retry(max_attempts=3, delay=2, backoff=2)
        def unstable_api_call():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 1
            current_delay = delay
            
            while attempt <= max_attempts:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt >= max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        raise
                    
                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt}/{max_attempts}): {e}. "
                        f"Retrying in {current_delay:.1f}s..."
                    )
                    
                    time.sleep(current_delay)
                    current_delay *= backoff
                    attempt += 1
            
            # На всякий случай (не должно сюда попадать)
            return func(*args, **kwargs)
        
        return wrapper
    return decorator
