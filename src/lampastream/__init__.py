"""LampaStream - spectrum-reactive Philips Hue Entertainment sync for Lyrion Music Server."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__: str = _pkg_version("lampastream")
except PackageNotFoundError:
    __version__ = "0.2.0"

try:
    from ._commit import COMMIT as __git_hash__
except ImportError:
    __git_hash__: str = "unknown"
