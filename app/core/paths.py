"""
Where the program keeps its files (config.json, glossaries, cache, logs, .env).
In the source tree this is the project folder; in the packaged build, the folder of the executable
(the packaged code itself lives in a read-only bundle, so user data must not be written there).
"""
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))


def app_root():
    if FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def root_path(*parts):
    return os.path.join(app_root(), *parts)
