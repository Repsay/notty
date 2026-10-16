"""Owner-only pet profile controls with cloud readback and stable device identity."""

from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.text import TextEntity, TextMode
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from custom_components.notty.api import JsonObject, NottyApiError
from custom_components.notty.entity import NottyEntity
from custom_components.notty.feature_contracts import MAX_PET_NAME_UNITS, true_state
from custom_components.notty.models import NottyConfigEntry
from custom_components.notty.pet_api import PetApi

SOURCE_PET = "pet"
MAX_STATE_LENGTH = 255
PET_SEX_OPTIONS = {1: "male", 2: "female"}


class NottyPetProfileEntity(NottyEntity):
    """Common ownership, profile lookup, mutation and registry-name handling."""

    _attr_entity_category = EntityCategory.CONFIG
    profile_key: str

    @property
    def profile(self) -> JsonObject:
        """Fresh detailed fields before falling back to discovery metadata.

        Returns:
            Current pet data, never a modified local copy after a write.
        """
        related = self.block["info"].get("_notty_related")
        detail = related.get("info") if isinstance(related, dict) else None
        return {**self.block["device"], **(detail if isinstance(detail, dict) else {})}

    @property
    def unique_id(self) -> str:
        """Keep profile controls tied to the existing pet identity.

        Returns:
            A stable ID independent of pet names or associations.
        """
        return f"{self.device_id}_profile_{self.profile_key}"

    @property
    def available(self) -> bool:
        """Permit profile changes only for current account-owned pets.

        Returns:
            Whether the current pet is present and editable.
        """
        return super().available and true_state(self.profile.get("is_owner"))

    async def apply(self, changes: JsonObject) -> None:
        """Use fresh ownership/binding validation and then poll authoritative state.

        Raises:
            HomeAssistantError: If a shared/unavailable pet or API error prevents editing.
        """
        if not self.available:
            msg = "Only a current NOTTY pet owner can change this profile"
            raise HomeAssistantError(msg)
        try:
            await PetApi(self.coordinator.api).update(str(self.profile.get("pet_id")), changes)
        except NottyApiError as exc:
            raise HomeAssistantError(str(exc)) from exc
        await self.coordinator.async_request_refresh()

    def _handle_coordinator_update(self) -> None:
        name = self.profile.get("name")
        if self.available and isinstance(name, str) and name.strip():
            self.update_device_name(name)
        super()._handle_coordinator_update()


class NottyPetName(NottyPetProfileEntity, TextEntity):
    """Edit the pet's cloud name independently from HA's display-name override."""

    profile_key = "name"
    _attr_name = "Name"
    _attr_translation_key = "pet_name"
    _attr_mode = TextMode.TEXT
    _attr_native_min = 1

    @property
    def native_value(self) -> str | None:
        """The exact reported pet name.

        Returns:
            A printable name, otherwise unknown.
        """
        value = self.profile.get("name")
        return value if isinstance(value, str) and value.isprintable() and 0 < len(value) <= MAX_STATE_LENGTH else None

    @property
    def native_max(self) -> int:
        """Accommodate longer existing readback without relaxing write validation.

        Returns:
            The UI display bound; API writes validate UTF-16 units explicitly.
        """
        return max(MAX_PET_NAME_UNITS, len(self.native_value or ""))

    async def async_set_value(self, value: str) -> None:
        """Save a name through the full profile-preserving request."""
        await self.apply({"name": value})


class NottyPetSex(NottyPetProfileEntity, SelectEntity):
    """Select the app's established male/female values."""

    profile_key = "sex"
    _attr_name = "Sex"
    _attr_translation_key = "pet_sex"

    @property
    def options(self) -> list[str]:
        """Supported pet sex choices.

        Returns:
            Only the app's established male and female values.
        """
        return list(PET_SEX_OPTIONS.values())

    @property
    def current_option(self) -> str | None:
        """Only established sex enums.

        Returns:
            The selected sex, or unknown for unsupported values.
        """
        value = self.profile.get("sex")
        return PET_SEX_OPTIONS.get(value) if type(value) is int else None

    async def async_select_option(self, option: str) -> None:
        """Save the selected app enum.

        Raises:
            HomeAssistantError: If an unsupported option is supplied.
        """
        values = {label: value for value, label in PET_SEX_OPTIONS.items()}
        if option not in values:
            msg = "Choose a supported pet sex"
            raise HomeAssistantError(msg)
        await self.apply({"sex": values[option]})


class NottyPetNeutered(NottyPetProfileEntity, SwitchEntity):
    """Edit the app's nullable neutered-state Boolean."""

    profile_key = "is_sterilization"
    _attr_name = "Neutered"
    _attr_translation_key = "pet_neutered"

    @property
    def is_on(self) -> bool | None:
        """Boolean readback, keeping unknown separate from false.

        Returns:
            Reported neutered state, or unknown.
        """
        value = self.profile.get("is_sterilization")
        return value if type(value) is bool else None

    async def async_turn_on(self, **_kwargs: object) -> None:
        """Record neutered state without changing any device setting."""
        await self.apply({"is_sterilization": True})

    async def async_turn_off(self, **_kwargs: object) -> None:
        """Record non-neutered state without changing any device setting."""
        await self.apply({"is_sterilization": False})


class NottyPetBirthday(NottyPetProfileEntity, DateEntity):
    """Edit a calendar date without timezone conversion."""

    profile_key = "birthday"
    _attr_name = "Birthday"
    _attr_translation_key = "pet_birthday"

    @property
    def native_value(self) -> date | None:
        """A valid birthday calendar date.

        Returns:
            Date readback, otherwise unknown.
        """
        value = self.profile.get("birthday")
        try:
            return date.fromisoformat(value) if isinstance(value, str) else None
        except ValueError:
            return None

    async def async_set_value(self, value: date) -> None:
        """Save the date without shifting it across local midnight."""
        await self.apply({"birthday": value.isoformat()})


def add_pet_entities(
    entry: NottyConfigEntry, add: AddConfigEntryEntitiesCallback, factory: type[NottyPetProfileEntity]
) -> None:
    """Discover pet profile controls initially and for pets found on later polls."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    def discover() -> None:
        entities: list[NottyPetProfileEntity] = []
        for device_id, block in coordinator.data.items():
            if device_id not in known and block["device"].get("_notty_source") == SOURCE_PET:
                entities.append(factory(coordinator, device_id, block["device"]))
                known.add(device_id)
        if entities:
            add(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))
