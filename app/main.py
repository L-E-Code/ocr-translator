from core.logger_config import setup_logger
logger = setup_logger()


if __name__ == "__main__":
    from ui.launcher import run_gui
    run_gui()
