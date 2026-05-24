
import sys
# ANSI escape codes
RED = '\033[31m'
GREEN = '\033[32m'
YELLOW = '\033[33m'
BLUE = '\033[34m'
MAGENTA = '\033[35m'
CYAN = '\033[36m'
RESET = '\033[0m'
WHITE = '\033[37m'


def error_print(msg: str, header: str = '', header_color: str = '') -> None:
    if header == '':
        print(f'{RED}{msg}{RESET}')
    else:
        if header_color == '':
            header_color = WHITE
        print(f'{RED}{msg}{RESET}')
    sys.stdout.flush()


def warning_print(msg: str, header: str = '', header_color: str = '') -> None:
    if header == '':
        print(f'{YELLOW}{msg}{RESET}')
    else:
        if header_color == '':
            header_color = WHITE
        print(f'{header_color}[{header}] >> {YELLOW}{msg}{RESET}')
    sys.stdout.flush()


def info_print(msg: str, header: str = '', header_color: str = '') -> None:
    if header == '':
        print(f'{BLUE}{msg}{RESET}')
    else:
        if header_color == '':
            header_color = WHITE
        print(f'{header_color}[{header}] >> {BLUE}{msg}{RESET}')
    sys.stdout.flush()


def success_print(msg: str, header: str = '', header_color: str = '') -> None:
    if header == '':
        print(f'{GREEN}{msg}{RESET}')
    else:
        if header_color == '':
            header_color = WHITE
        print(f'{header_color}[{header}] >> {GREEN}{msg}{RESET}')
    sys.stdout.flush()


def pretty_print(msg: str, color: str) -> None:
    print(f'{color}{msg}{RESET}')
