import random
import time

from utils.log import create_logger

logger = create_logger(None, __name__)


def sleep_stochastically(min_s: float = 0.25, max_s: float = 3.0):
    duration = random.uniform(min_s, max_s)
    logger.info(f"Sleeping for {duration:.2f} seconds")
    time.sleep(duration)
