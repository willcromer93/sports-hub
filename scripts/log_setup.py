"""
Logging for the pipeline scripts, using Python's built-in logging module.

Compared with print(): every line gets a timestamp and a level (INFO, WARNING,
ERROR), tracebacks are captured in full, and the log file rotates (5 files of up
to 5 MB each) so it can never fill the disk.

Usage, at the top of a script:

    from log_setup import setup_logging
    log = setup_logging("pipeline")      # writes logs/pipeline.log
    log.info("Pulled %d games", n)

When you run a script by hand in a terminal, lines also appear on screen. Under
cron they go only to the file (cron's own output redirect would otherwise
duplicate every line).
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = Path(os.getenv("LOG_DIR") or PROJECT_DIR / "logs")

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(name):
    """Configure logging for one script (name = log file name) and return the logger.

    The handlers go on the shared parent logger "sports_hub". Loggers form a tree
    by their dotted names, so "sports_hub.notify" and "sports_hub.run_report"
    (used by the other modules) inherit them and end up in the same file."""
    logger = logging.getLogger("sports_hub")
    if logger.handlers:  # already set up in this process; don't add duplicates
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        LOG_DIR / f"{name}.log",
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if sys.stdout.isatty():  # a person is watching: show it on screen too
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        logger.addHandler(console)

    return logger
