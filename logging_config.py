"""
Structured logging configuration for Social Optimize Machine.

- JSON output for production (when FLASK_ENV=production or LOG_FORMAT=json)
- Readable console output for development
- Log level controlled by LOG_LEVEL env var (default: INFO)
- Integrates with gunicorn's logging
"""
import logging
import json
import os
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production."""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Include extra fields if present
        for key in ("method", "path", "status", "duration_ms", "remote_addr"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)
        return json.dumps(log_entry)


class ReadableFormatter(logging.Formatter):
    """Human-readable formatter for development."""

    FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    def __init__(self):
        super().__init__(self.FORMAT, datefmt="%Y-%m-%d %H:%M:%S")


def setup_logging(app=None):
    """
    Configure logging for the application.

    Call once at startup. When running under gunicorn, this hooks into
    gunicorn's existing loggers so messages flow through a single pipeline.
    """
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    use_json = (
        os.environ.get("LOG_FORMAT", "").lower() == "json"
        or os.environ.get("FLASK_ENV", "").lower() == "production"
    )

    # Choose formatter
    formatter = JSONFormatter() if use_json else ReadableFormatter()

    # Root logger
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level, logging.INFO))

    # Remove existing handlers to avoid duplicates on reload
    root.handlers.clear()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(getattr(logging, log_level, logging.INFO))
    console.setFormatter(formatter)
    root.addHandler(console)

    # App-specific logger
    app_logger = logging.getLogger("som")
    app_logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Integrate with gunicorn if present
    if "gunicorn" in os.environ.get("SERVER_SOFTWARE", ""):
        gunicorn_logger = logging.getLogger("gunicorn.error")
        gunicorn_logger.handlers.clear()
        gunicorn_logger.addHandler(console)
        gunicorn_access = logging.getLogger("gunicorn.access")
        gunicorn_access.handlers.clear()
        gunicorn_access.addHandler(console)

    # If a Flask app is provided, wire its logger too
    if app is not None:
        app.logger.handlers.clear()
        app.logger.addHandler(console)
        app.logger.setLevel(getattr(logging, log_level, logging.INFO))

    return app_logger
