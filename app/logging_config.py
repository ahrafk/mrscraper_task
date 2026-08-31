import logging
import sys

from app.config import settings

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s", "%H:%M:%S")
    )
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL.upper())
    root.handlers = [handler]
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
