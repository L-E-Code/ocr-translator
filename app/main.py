import sys

from core.logger_config import setup_logger
logger = setup_logger()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        from core.selftest import run
        sys.exit(run())
    from ui.launcher import run_gui
    run_gui()
