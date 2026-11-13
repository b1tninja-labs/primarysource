"""Where the corpus lives and where it comes from.

The corpus never lives in the working directory: MCP clients start servers from wherever they like, so a
cwd-relative home would point every session at a different, empty library.
"""

from __future__ import annotations

import os
from pathlib import Path

from primarysource.home import collection_home

from . import __version__

USER_AGENT = f"primarysource-cve/{__version__} (local vulnerability corpus sync)"

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
EPSS_URL = "https://epss.empiricalsecurity.com/epss_scores-current.csv.gz"
KERNEL_REPO_URL = "https://git.kernel.org/pub/scm/linux/security/vulns.git"
CVELIST_RELEASE_API = "https://api.github.com/repos/CVEProject/cvelistV5/releases/latest"
CVELIST_DELTA_LOG = "https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/deltaLog.json"

KERNEL_ORG_ID = "f4215fc3-5b6b-47ff-a258-f7189bd81038"
CISA_ADP_SHORT_NAME = "CISA-ADP"

SOURCES = ("cvelist", "kernel", "kev", "epss")

# Age, in days, past which `info` and every tool call a source stale. Chosen per source's own cadence.
STALE_DAYS = {"cvelist": 3, "kernel": 7, "kev": 7, "epss": 3}


def home() -> Path:
    """Where the corpus lives (PLAN.md §5.8). The first that applies: `$CVELIB_HOME` (an explicit setting from
    before the move keeps working), `$PRIMARYSOURCE_CVE_HOME`, `$PRIMARYSOURCE_HOME/cve`, an existing `~/.cvelib`,
    then the per-user `primarysource/cve`. Point one at a large disk: the corpus is a few GB. Nothing is created."""
    explicit = any(os.environ.get(name) for name in ("CVELIB_HOME", "PRIMARYSOURCE_CVE_HOME", "PRIMARYSOURCE_HOME"))
    legacy = Path.home() / ".cvelib"
    if not explicit and legacy.is_dir():
        return legacy
    return collection_home("cve", "cvelib").expanduser()


def index_path() -> Path:
    return home() / "index.sqlite"


def raw_dir() -> Path:
    return home() / "raw"


def kernel_repo_dir() -> Path:
    return home() / "repos" / "kernel-vulns"


def min_free_bytes() -> int:
    """Free space a sync must leave behind. CVELIB_MIN_FREE_GB overrides the 2 GB default."""
    return int(float(os.environ.get("CVELIB_MIN_FREE_GB") or "2") * 1024**3)
