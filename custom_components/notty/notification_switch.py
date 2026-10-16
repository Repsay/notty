"""Account-level notification category switches with explicit cloud scope."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.notty.api import JsonObject, NottyApiError, plan_enabled
from custom_components.notty.const import DOMAIN
from custom_components.notty.coordinator import NottyCoordinator
from custom_components.notty.device_features import NotificationApi
from custom_components.notty.models import NottyConfigEntry


class NottyNotificationSwitch(CoordinatorEntity[NottyCoordinator], SwitchEntity):
    """One NOTTY account preference, never a Home Assistant notification toggle."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "notification_category"

    def __init__(self, coordinator: NottyCoordinator, entry: NottyConfigEntry, row: JsonObject) -> None:
        super().__init__(coordinator)
        self.category_id = str(row["message_type_id"])
        self._attr_unique_id = f"{entry.entry_id}_notification_{self.category_id}"
        self._attr_translation_placeholders = {"category": str(row.get("message_type_name") or self.category_id)}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"account_{entry.entry_id}")},
            name="NOTTY account",
            manufacturer="NOTTY",
            model="Cloud notification preferences",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def category(self) -> JsonObject | None:
        """The latest matching category.

        Returns:
            Current account record, otherwise unavailable.
        """
        return next(
            (
                row
                for row in self.coordinator.notification_categories or []
                if str(row["message_type_id"]) == self.category_id
            ),
            None,
        )

    @property
    def available(self) -> bool:
        """Whether the account preference has a known current state.

        Returns:
            True only with successful coordinator data and explicit block state.
        """
        row = self.category
        return super().available and row is not None and plan_enabled(row.get("blocked")) is not None

    @property
    def is_on(self) -> bool | None:
        """Enabled notifications correspond to the inverse cloud block flag.

        Returns:
            True for unblocked, false for blocked, or unknown.
        """
        row = self.category
        blocked = plan_enabled(row.get("blocked")) if row is not None else None
        return not blocked if blocked is not None else None

    async def _set_enabled(self, *, enabled: bool) -> None:
        if not self.available:
            msg = "NOTTY notification preference is currently unavailable"
            raise HomeAssistantError(msg)
        try:
            await NotificationApi(self.coordinator.api).set_blocked(self.category_id, blocked=not enabled)
        except NottyApiError as exc:
            raise HomeAssistantError(str(exc)) from exc
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **_kwargs: object) -> None:
        """Enable this category in the NOTTY account."""
        await self._set_enabled(enabled=True)

    async def async_turn_off(self, **_kwargs: object) -> None:
        """Block this category in the NOTTY account."""
        await self._set_enabled(enabled=False)


def add_notification_switches(entry: NottyConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    """Discover current and later-recovered account categories once per config entry."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    def discover() -> None:
        entities: list[NottyNotificationSwitch] = []
        for row in coordinator.notification_categories or []:
            identifier = str(row["message_type_id"])
            if identifier not in known:
                entities.append(NottyNotificationSwitch(coordinator, entry, row))
                known.add(identifier)
        if entities:
            add(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))
