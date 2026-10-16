"""Pet birthday calendar controls."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from custom_components.notty.models import NottyConfigEntry
from custom_components.notty.pet_entities import NottyPetBirthday, add_pet_entities


async def async_setup_entry(  # ruff: ignore[unused-async] -- Home Assistant requires an async platform setup callback.
    _hass: HomeAssistant, entry: NottyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Expose birthday editing on the existing pet devices."""
    add_pet_entities(entry, async_add_entities, NottyPetBirthday)
