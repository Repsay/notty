"""Use the schema library native to the installed Home Assistant version."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import probatio as vol
else:
    try:
        import probatio as vol
    except ImportError:
        import voluptuous as vol

__all__ = ["vol"]
