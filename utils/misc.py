import random
import time
import uuid
from functools import wraps
from pathlib import Path
from typing import Union

from utils.log import create_logger

logger = create_logger(None, __name__)


def sleep_stochastically(min_s: float = 0.25, max_s: float = 3.0):
    duration = random.uniform(min_s, max_s)
    logger.info(f"Sleeping for {duration:.2f} seconds")
    time.sleep(duration)


def get_override_safe_path(
    path: Union[Path, str], max_iter=100, uuid_on_max_iter=True
) -> Path:
    path = Path(path)
    logger.debug("Resolving collision-safe path for '%s'", path)
    suffix_count = 0

    original_stem = path.stem
    original_suffix = path.suffix
    parent = path.parent

    while path.exists():
        suffix_count += 1
        path = parent / f"{original_stem}_{suffix_count}{original_suffix}"
        logger.debug("Path already exists; trying '%s'", path)

        if suffix_count >= max_iter:
            break

    if path.exists():
        if uuid_on_max_iter:
            new_path = parent / f"{original_stem}_{uuid.uuid4()}{original_suffix}"
            logger.warning(
                "Reached max_iter=%d collision attempts for '%s'; "
                "falling back to UUID path '%s'",
                max_iter,
                original_stem,
                new_path,
            )
            path = new_path
        else:
            logger.error(
                "Could not find a free path after %d attempts for '%s'",
                max_iter,
                original_stem,
            )
            raise FileExistsError(
                f"Could not find free path after {max_iter} attempts: {path}"
            )

    logger.debug("Resolved safe output path: '%s'", path)
    return path


def run_on_mode(mode_required):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_mode = globals().get("mode")
            if current_mode != mode_required:
                logger.debug(
                    "Skipping '%s': requires mode='%s', current mode='%s'",
                    func.__name__,
                    mode_required,
                    current_mode,
                )
                return None
            logger.debug(
                "Running '%s' (mode='%s' matches requirement)",
                func.__name__,
                mode_required,
            )
            return func(*args, **kwargs)

        return wrapper

    return decorator
