"""Learning Management System backend package."""

__version__ = "0.1.0"
APP_NAME = "lms"

__all__ = ["APP_NAME", "__version__", "create_app"]


def create_app(*args: object, **kwargs: object):
    """Lazily resolve the app factory to avoid import cycles at package import time."""
    from lms.main import create_app as _create_app

    return _create_app(*args, **kwargs)
