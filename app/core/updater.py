"""
Update check: asks GitHub for the latest release and compares it with the running version.
It only reads the version; nothing is downloaded or installed, and no data about the user is sent.
"""
import json
import re
import ssl
import urllib.error
import urllib.request

from core.logger_config import get_logger
from core.version import __version__, REPOSITORY

logger = get_logger("Updater")


def parse_version(text):
    """'v1.2.3-beta' -> (1, 2, 3); () if there are no numbers."""
    core = re.split(r"[-+ ]", str(text).strip().lstrip("vV"), maxsplit=1)[0]
    return tuple(int(n) for n in re.findall(r"\d+", core))


def is_newer(latest, current=__version__):
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    size = max(len(a), len(b))  # 1.2 == 1.2.0
    return a + (0,) * (size - len(a)) > b + (0,) * (size - len(b))


def fetch_latest_release(repo=REPOSITORY, timeout=6, opener=urllib.request.urlopen):
    """{'version': tag, 'url': release page} of the latest published release, or None (no release, offline...)."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "OCR-Translator-update-check"},
    )
    try:
        with opener(request, timeout=timeout, context=ssl.create_default_context()) as response:
            data = json.load(response)
    except urllib.error.HTTPError as e:
        if e.code != 404:  # 404 = no release published yet
            logger.debug(f"Update check: HTTP {e.code}")
        return None
    except Exception as e:
        logger.debug(f"Update check failed: {e}")
        return None
    tag = data.get("tag_name") if isinstance(data, dict) else None
    if not tag or data.get("draft") or data.get("prerelease"):
        return None
    return {"version": tag, "url": data.get("html_url") or f"https://github.com/{repo}/releases"}


def check_for_update(current=__version__, **kwargs):
    """The release information if there is a newer version than `current`, otherwise None."""
    release = fetch_latest_release(**kwargs)
    if release and is_newer(release["version"], current):
        logger.info(f"Newer version available: {release['version']} (running {current}).")
        return release
    return None
