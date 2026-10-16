"""Home Assistant entry points for the NOTTY integration."""

from custom_components.notty.bootstrap import (
    async_migrate_entry as async_migrate_entry,
    async_setup_entry as async_setup_entry,
    async_unload_entry as async_unload_entry,
)
