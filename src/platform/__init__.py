# Standard library proxy logic to prevent shadowing conflicts.
# Because this project package is named 'platform', it shadows the Python standard library 'platform' module
# when added to PYTHONPATH in Docker or local dev.
# We dynamically import the real standard library 'platform' module and inject its attributes into this package.
import sys

_original_path = list(sys.path)
_cached_platform = sys.modules.pop("platform", None)

try:
    # Filter out paths that point to our source directory/app
    sys.path = [
        p
        for p in sys.path
        if p != ""
        and "trading-platform" not in p.lower()
        and "/app" not in p
        and "src" not in p.split("/")
        and "src" not in p.split("\\")
    ]
    import platform as _std_platform

    # Copy all standard platform attributes into this package's namespace
    for _name in dir(_std_platform):
        if not _name.startswith("__"):
            globals()[_name] = getattr(_std_platform, _name)

finally:
    # Restore the original path and re-cache our package in sys.modules
    sys.path = _original_path
    if _cached_platform:
        sys.modules["platform"] = _cached_platform
