import logging
from logging.handlers import RotatingFileHandler
import os.path


def setup_loggers():
    # telethon_logger = logging.getLogger("telethon")
    # telethon_logger.setLevel(logging.CRITICAL)

    base_path = os.path.join(os.getcwd(), "logs")

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                                  datefmt='%Y-%m-%d %H:%M:%S')

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    # # Удаление всех существующих обработчиков из корневого логгера
    # for handler in logging.root.handlers[:]:
    #     logging.root.removeHandler(handler)

    errors = logging.getLogger("errors")
    file_error_handler = RotatingFileHandler(os.path.join(base_path, "error_log.log"),
                                             maxBytes=100 * 1024 * 1024, backupCount=2)
    file_error_handler.setFormatter(formatter)
    errors.setLevel(level=logging.ERROR)
    errors.addHandler(file_error_handler)
    errors.addHandler(stream_handler)

    access = logging.getLogger("access")
    access_file_handler = RotatingFileHandler(os.path.join(base_path, "access_log.log"),
                                              maxBytes=100 * 1024 * 1024, backupCount=2)
    access_file_handler.setFormatter(formatter)
    access.setLevel(level=logging.INFO)
    access.addHandler(access_file_handler)
    # access.addHandler(stream_handler)

    # Basic
    basic = logging.getLogger("main")
    debug_file_handler = RotatingFileHandler(os.path.join(base_path, "debug_log.log"),
                                             maxBytes=100 * 1024 * 1024, backupCount=2)
    debug_file_handler.setFormatter(formatter)
    basic.setLevel(logging.DEBUG)
    basic.addHandler(debug_file_handler)
    # basic.addHandler(stream_handler)

    # logging.getLogger().handlers.clear()

    logging.basicConfig(handlers=(debug_file_handler, stream_handler),
                        level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                        datefmt='%Y-%m-%d %H:%M:%S')

    httpcore_logger = logging.getLogger("httpcore")
    httpx_logger = logging.getLogger("httpx")
    mongo_logger = logging.getLogger("pymongo")
    mongo_logger.setLevel(logging.CRITICAL)
    httpx_logger.setLevel(logging.CRITICAL)
    httpcore_logger.setLevel(logging.CRITICAL)


class ToLog:
    error = logging.getLogger("error")
    access = logging.getLogger("access")
    basic = logging.getLogger("main")

    @classmethod
    def write_error(cls, msg: str):
        cls.error.error(msg)

    @classmethod
    def write_basic(cls, msg: str):
        cls.basic.info(msg)

    @classmethod
    def write_access(cls, msg: str):
        cls.access.info(msg)
