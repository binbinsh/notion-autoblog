import logging
import os
import sys
from typing import Optional

# ANSI color codes
RESET = "\033[0m"
DIM = "\033[2m"
BLUE = "\033[34m"
GREY = "\033[90m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD_RED = "\033[1;31m"

LEVEL_COLORS = {
    logging.DEBUG: GREY,
    logging.INFO: GREEN,
    logging.WARNING: YELLOW,
    logging.ERROR: RED,
    logging.CRITICAL: BOLD_RED,
}


def _should_use_color(stream, force: Optional[bool] = None) -> bool:
    """Decide whether to use colors.

    Priority:
    1) Explicit force flag if provided
    2) LOG_COLOR env var ("1"/"true" to enable, "0"/"false" to disable)
    3) TTY detection (isatty)
    """
    if force is not None:
        return bool(force)

    env = os.getenv("LOG_COLOR")
    if env is not None:
        return env.strip().lower() in {"1", "true", "yes", "on"}

    # Respect NO_COLOR convention
    if os.getenv("NO_COLOR") is not None:
        return False

    try:
        return hasattr(stream, "isatty") and stream.isatty()
    except Exception:
        return False


class ColorFormatter(logging.Formatter):
    """A simple colorizing formatter for Python logging."""

    def __init__(self, fmt: Optional[str] = None, datefmt: Optional[str] = None, use_color: Optional[bool] = None):
        if not fmt:
            # Example: I 25-08-10 12:34:56 module.name: message
            fmt = f"%(levelshort_colored)s {DIM}%(asctime)s{RESET} {BLUE}%(name)s{RESET}: %(message)s"
        if not datefmt:
            # Include date in yy-mm-dd format
            datefmt = "%y-%m-%d %H:%M:%S"
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.use_color = _should_use_color(sys.stdout, use_color)

    def format(self, record: logging.LogRecord) -> str:
        # Map standard levels to single-letter shorthand
        level_shorthand_map = {
            logging.DEBUG: "D",
            logging.INFO: "I",
            logging.WARNING: "W",
            logging.ERROR: "E",
            logging.CRITICAL: "C",
        }
        level_short = level_shorthand_map.get(record.levelno, record.levelname[:1])
        record.levelshort = level_short

        if self.use_color:
            color = LEVEL_COLORS.get(record.levelno, "")
            record.levelshort_colored = f"{color}{level_short}{RESET}"
        else:
            record.levelshort_colored = level_short
        return super().format(record)


def setup_logging(level: Optional[str] = None, use_color: Optional[bool] = None) -> None:
    """Configure root logger with colorized console output.

    - level: string name (e.g., "DEBUG", "INFO"). Defaults to LOG_LEVEL env or INFO.
    - use_color: force enable/disable color. Defaults to auto-detect/LOG_COLOR env.
    """
    level_name = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    numeric_level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Clear existing handlers to avoid duplicate logs when re-running in REPLs
    if root_logger.handlers:
        root_logger.handlers.clear()

    stream_handler = logging.StreamHandler(stream=sys.stdout)
    stream_handler.setLevel(numeric_level)
    stream_handler.setFormatter(ColorFormatter(use_color=use_color))
    root_logger.addHandler(stream_handler)

    # Reduce verbosity of noisy third-party loggers if desired
    for noisy_logger_name in ("urllib3", "notion_client", "PIL", "httpx", "httpcore"):
        logging.getLogger(noisy_logger_name).setLevel(max(logging.WARNING, numeric_level))


