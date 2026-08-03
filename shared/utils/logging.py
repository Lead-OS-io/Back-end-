"""
Shared logging configuration for all microservices.
"""
import logging
import sys
import json
from typing import Optional
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "service": getattr(record, "service", "unknown"),
            "message": record.getMessage(),
            "logger": record.name,
        }
        
        # Add extra fields
        if hasattr(record, "tenant_id"):
            log_data["tenant_id"] = record.tenant_id
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


def setup_logging(
    service_name: str,
    level: str = "INFO",
    json_format: bool = True,
) -> None:
    """Setup logging for a service."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper()))
    
    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            f"%(asctime)s | {service_name} | %(levelname)s | %(name)s | %(message)s"
        ))
    
    root_logger.addHandler(handler)
    
    # Suppress noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str, service: Optional[str] = None) -> logging.Logger:
    """Get a logger with optional service context."""
    logger = logging.getLogger(name)
    if service:
        logger = logging.LoggerAdapter(logger, {"service": service})
    return logger


class LogContext:
    """Context manager for adding context to logs."""
    
    def __init__(
        self,
        logger: logging.Logger,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ):
        self.logger = logger
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.request_id = request_id
        self._old_factory = None
    
    def __enter__(self):
        self._old_factory = logging.getLogRecordFactory()
        
        def record_factory(*args, **kwargs):
            record = self._old_factory(*args, **kwargs)
            if self.tenant_id:
                record.tenant_id = self.tenant_id
            if self.user_id:
                record.user_id = self.user_id
            if self.request_id:
                record.request_id = self.request_id
            return record
        
        logging.setLogRecordFactory(record_factory)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        logging.setLogRecordFactory(self._old_factory)

