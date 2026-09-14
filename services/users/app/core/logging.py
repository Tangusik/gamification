"""Структурированное (JSON) логирование сервиса users."""

import json
import logging
import sys
from datetime import UTC, datetime
from logging.config import dictConfig
from typing import Any


class JsonFormatter(logging.Formatter):
    """Форматтер, печатающий один JSON-объект на строку."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    """Настроить корневой логгер и логгеры uvicorn на JSON-вывод в stdout."""
    normalized_level = level.upper()
    uvicorn_logger = {
        "handlers": ["stdout"],
        "level": normalized_level,
        "propagate": False,
    }
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {"()": f"{JsonFormatter.__module__}.JsonFormatter"},
            },
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "stream": sys.stdout,
                },
            },
            "root": {"handlers": ["stdout"], "level": normalized_level},
            "loggers": {
                "uvicorn": uvicorn_logger,
                "uvicorn.error": uvicorn_logger,
                "uvicorn.access": uvicorn_logger,
            },
        }
    )
