import logging
import os
from logging.handlers import RotatingFileHandler

CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)

def setup_logging():
    log_dir = CURR_DIR
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "app.log")
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )


    print("LOG FILE ABS PATH:", os.path.abspath(log_file))
    print("CWD:", os.getcwd())


    handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5
    )
    handler.setFormatter(formatter)

    # ROOT logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if not root_logger.handlers:
        root_logger.addHandler(handler)

    # Uvicorn loggers
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.setLevel(logging.INFO)
        uvicorn_logger.propagate = True   # IMPORTANT
