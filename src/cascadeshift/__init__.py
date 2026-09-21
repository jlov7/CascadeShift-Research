from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cascadeshift")
except PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = ["__version__"]
