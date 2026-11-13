"""Process log output for the service entrypoint; never configured on import."""

import logging
import os
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parents[1]) + os.sep
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ProjectRecords(logging.Filter):
    """Pass project records at the configured level and third-party ones from WARNING."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Keep library INFO/DEBUG (request URLs, model downloads) out of the service log."""
        if record.levelno >= logging.WARNING:
            return True
        return record.pathname.startswith(PROJECT_ROOT) and "site-packages" not in record.pathname


def configure_logging(level: str, root: logging.Logger | None = None) -> bool:
    """Install one stderr handler unless logging is already configured.

    Returns whether the handler was installed. An existing handler (an explicit
    uvicorn ``--log-config`` or a test runner) is left untouched, so repeated
    application factories never add duplicate output.
    """
    root = root or logging.getLogger()
    if root.handlers:
        return False
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(ProjectRecords())
    root.addHandler(handler)
    root.setLevel(level)
    return True
