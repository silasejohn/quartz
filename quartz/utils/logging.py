"""
Quartz logging setup.

Provides a pre-configured logger with:
  - RichHandler: colored console output (replaces color_utils print functions)
  - FileHandler: persistent log files at data/{tournament}/{round}/logs/pipeline.log

Usage:
    from quartz.utils.logging import get_logger
    logger = get_logger(__name__)

    logger.info("Processing player: slaveknightkos")
    logger.warning("Soft error: current rank missing for PlayerName#NA1")
    logger.error("Browser setup failed")
    logger.success("OPGG_SCRAPE_RANK complete")   # custom level, green output

Call configure_file_logging(log_path) once at startup (e.g. in PipelineRunner.__init__)
to enable persistent log files. Console logging is always active.
"""

import logging
import os

from rich.console import Console
from rich.logging import RichHandler

# Custom SUCCESS level — sits between INFO (20) and WARNING (30)
SUCCESS_LEVEL = 25
logging.addLevelName(SUCCESS_LEVEL, "SUCCESS")


def success(self, message, *args, **kwargs):
    if self.isEnabledFor(SUCCESS_LEVEL):
        self._log(SUCCESS_LEVEL, message, args, **kwargs)


logging.Logger.success = success  # type: ignore[attr-defined]

console = Console(highlight=False)

# File-only logger — no console handler, so it never double-prints.
# Silent until configure_file_logging() is called.
_file_logger = logging.getLogger("quartz.file")
_file_logger.propagate = False
_file_logger.addHandler(logging.NullHandler())
_file_logger.setLevel(logging.DEBUG)


# ---------------------------------------------------------------------------
# Print functions — colored console output + file logging when configured
# ---------------------------------------------------------------------------

def info_print(msg: str) -> None:
    console.print(msg, style="blue", markup=False)
    _file_logger.info(msg)


def success_print(msg: str) -> None:
    console.print(msg, style="green", markup=False)
    _file_logger.log(SUCCESS_LEVEL, msg)


def warning_print(msg: str) -> None:
    console.print(msg, style="yellow", markup=False)
    _file_logger.warning(msg)


def error_print(msg: str) -> None:
    console.print(msg, style="red", markup=False)
    _file_logger.error(msg)


def _build_rich_handler() -> RichHandler:
    return RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        markup=False,
        level=logging.DEBUG,
    )


def configure_file_logging(log_path: str) -> None:
    """
    Enable persistent file logging. Call once at startup with the target log file path.
    Console output is unaffected — this only adds a file sink.
    Creates parent directories as needed.

    [param] log_path: absolute path to the log file e.g. data/gcs/s4/logs/pipeline.log
    """
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    _file_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger for the given module name.
    Console output is always active. File output requires configure_file_logging() first.

    [param] name: typically __name__ — used to identify the source module in log output
    """
    logger = logging.getLogger(name)

    if not logger.handlers and not logging.getLogger("quartz").handlers:
        root = logging.getLogger("quartz")
        root.setLevel(logging.DEBUG)
        root.addHandler(_build_rich_handler())
        root.propagate = False

    return logger
