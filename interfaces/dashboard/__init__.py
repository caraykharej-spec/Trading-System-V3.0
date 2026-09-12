from pathlib import Path


def dashboard_static_dir() -> Path:
    """Return the packaged same-origin dashboard asset directory."""

    return Path(__file__).resolve().with_name("static")
