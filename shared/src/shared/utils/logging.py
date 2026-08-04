import logging
import sys


def setup_logging(service_name: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        f"%(asctime)s %(levelname)s [{service_name}] %(name)s: %(message)s"
    ))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
