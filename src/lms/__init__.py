"""Learning Management System backend package."""

__version__ = "0.1.0"
APP_NAME = "lms"

__all__ = ["APP_NAME", "__version__", "create_app"]

from lms.main import create_app
