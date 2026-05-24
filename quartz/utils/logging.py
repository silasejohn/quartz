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
from typing import Optional

from rich.logging import RichHandler
from rich.console import Console

# Custom SUCCESS level — sits between INFO (20) and WARNING (30)
SUCCESS_LEVEL = 25
logging.addLevelName(SUCCESS_LEVEL, "SUCCESS")


def success(self, message, *args, **kwargs):
    if self.isEnabledFor(SUCCESS_LEVEL):
        self._log(SUCCESS_LEVEL, message, args, **kwargs)


logging.Logger.success = success  # type: ignore[attr-defined]

console = Console(highlight=False)
_file_handler: Optional[logging.FileHandler] = None
_configured = False


# ---------------------------------------------------------------------------
# Drop-in replacements for color_utils — use rich styles, no markup parsing
# ---------------------------------------------------------------------------

def info_print(msg: str) -> None:
    console.print(msg, style="blue", markup=False)


def success_print(msg: str) -> None:
    console.print(msg, style="green", markup=False)


def warning_print(msg: str) -> None:
    console.print(msg, style="yellow", markup=False)


def error_print(msg: str) -> None:
    console.print(msg, style="red", markup=False)


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
    Creates parent directories as needed.

    [param] log_path: absolute path to the log file e.g. data/gcs/s4/logs/pipeline.log
    """
    global _file_handler, _configured

    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    _file_handler = logging.FileHandler(log_path, encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    root = logging.getLogger("quartz")
    root.addHandler(_file_handler)
    _configured = True


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
