"""Firmware availability and explicit installation of the current offered task."""

from __future__ import annotations

from hashlib import sha256
from typing import override

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity, UpdateEntityFeature
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.storage import Store

from custom_components.notty.api import JsonObject, JsonValue, NottyApiError
from custom_components.notty.coordinator import NottyCoordinator
from custom_components.notty.device_features import FIRMWARE_IDLE_STATUSES, FirmwareApi, firmware_task_id
from custom_components.notty.entity import NottyEntity, value_from_block
from custom_components.notty.models import DeviceBlock, DeviceData, NottyConfigEntry

DEVICE_TYPE_LITTER_BOX = "litter_box"
SOURCE_PET = "pet"
MAX_VERSION_LENGTH = 255
FIELD_SOURCE_VERSION = "src_version"
FIELD_DESTINATION_VERSION = "dest_version"


def firmware_data(block: DeviceBlock) -> JsonObject:
    """Read the current endpoint response without falling back to stale summaries.

    Returns:
        Upgrade metadata, or an empty object if the optional endpoint is unavailable.
    """
    related = block["info"].get("_notty_related")
    value = related.get("upgrade") if isinstance(related, dict) else None
    return value if isinstance(value, dict) else {}


def firmware_version(value: JsonValue) -> str | None:
    """Accept bounded firmware strings without inventing semantic version ordering.

    Returns:
        A nonempty printable version, otherwise None.
    """
    if not isinstance(value, str):
        return None
    version = value.strip()
    return version if version and len(version) <= MAX_VERSION_LENGTH and version.isprintable() else None


async def async_setup_entry(  # ruff: ignore[unused-async] -- Home Assistant requires an async platform setup callback.
    _hass: HomeAssistant, entry: NottyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Discover supported firmware metadata now and after optional endpoint recovery."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    def discover() -> None:
        """Add a firmware entity once a physical box reports upgrade metadata."""
        entities: list[NottyFirmwareUpdate] = []
        for device_id, block in coordinator.data.items():
            if device_id in known or block["type"] != DEVICE_TYPE_LITTER_BOX:
                continue
            if block["device"].get("_notty_source") == SOURCE_PET:
                continue
            metadata = firmware_data(block)
            if FIELD_SOURCE_VERSION not in metadata or FIELD_DESTINATION_VERSION not in metadata:
                continue
            entities.append(NottyFirmwareUpdate(coordinator, device_id, block["device"]))
            known.add(device_id)
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class NottyFirmwareUpdate(NottyEntity, UpdateEntity):
    """Install a fresh eligible task without claiming measured percentage progress."""

    _attr_translation_key = "firmware"
    _attr_name = "Firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: NottyCoordinator, device_id: str, device: DeviceData) -> None:
        super().__init__(coordinator, device_id, device)
        self._attr_unique_id = f"{device_id}_firmware"
        self._requested_version: str | None = None
        self._requested_task: JsonValue = None
        self._request_baseline: JsonObject = {}
        self._installing = False
        identity = sha256(device_id.encode()).hexdigest()
        self._request_store: Store[JsonObject] = Store(
            coordinator.hass, 1, f"notty.{coordinator.entry_id}.{identity}.firmware"
        )

    async def async_added_to_hass(self) -> None:
        """Recover the pending task without repeating its installation request."""
        saved = await self._request_store.async_load()
        if isinstance(saved, dict):
            target, task = saved.get("target"), saved.get("task")
            if firmware_version(target) is not None and firmware_task_id(task):
                self._requested_version = firmware_version(target)
                self._requested_task = task
                baseline = saved.get("baseline")
                self._request_baseline = baseline if isinstance(baseline, dict) else {}
        await super().async_added_to_hass()
        self._reconcile_request()

    def _saved_request(self) -> JsonObject:
        return {"target": self._requested_version, "task": self._requested_task, "baseline": self._request_baseline}

    async def _remember_request(self, target: str, metadata: JsonObject) -> None:
        # Persist before the POST: a timeout may still mean the device accepted it.
        task = metadata.get("task_id")
        baseline = {key: metadata.get(key) for key in ("task_status", "utc_modified")}
        await self._request_store.async_save({"target": target, "task": task, "baseline": baseline})
        self._requested_version, self._requested_task, self._request_baseline = target, task, baseline

    def _reconcile_request(self) -> None:
        if self._requested_version is None or not self.available:
            return
        metadata = firmware_data(self.block)
        same_task = (
            type(metadata.get("task_id")) is type(self._requested_task)
            and metadata.get("task_id") == self._requested_task
            and metadata.get("dest_version") == self._requested_version
        )
        status = metadata.get("task_status")
        changed = any(metadata.get(key) != value for key, value in self._request_baseline.items())
        failed = same_task and changed and isinstance(status, str) and status in {"FAILED", "CANCELED"}
        if self.installed_version == self._requested_version or failed:
            self._requested_version, self._requested_task = None, None
            self._request_baseline = {}
            self._request_store.async_delay_save(self._saved_request, 0)
        elif same_task and changed and self._request_baseline != {"task_status": None, "utc_modified": None}:
            self._request_baseline = {"task_status": None, "utc_modified": None}
            self._request_store.async_delay_save(self._saved_request, 0)

    def _handle_coordinator_update(self) -> None:
        self._reconcile_request()
        super()._handle_coordinator_update()

    @property
    def supported_features(self) -> UpdateEntityFeature:
        """Expose installation only when cached metadata contains an eligible task.

        Returns:
            Full notes, plus install/progress when a current task is available.
        """
        features = UpdateEntityFeature.RELEASE_NOTES | UpdateEntityFeature.PROGRESS
        if self._requested_version is not None or self._installing:
            return features
        metadata = firmware_data(self.block)
        status = metadata.get("task_status")
        if (
            firmware_task_id(metadata.get("task_id"))
            and isinstance(status, str)
            and status in FIRMWARE_IDLE_STATUSES
            and self.latest_version != self.installed_version
            and self.available
        ):
            features |= UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
        return features

    @property
    def in_progress(self) -> bool | None:
        """Track this HA-requested target until installed-version readback or failure.

        Returns:
            Boolean progress, unknown when unavailable; never a fabricated percentage.
        """
        if not self.available:
            return None
        if self._installing:
            return True
        if self._requested_version is None:
            status = firmware_data(self.block).get("task_status")
            return False if isinstance(status, str) and status in FIRMWARE_IDLE_STATUSES else None
        if self.installed_version == self._requested_version:
            return False
        metadata = firmware_data(self.block)
        if (
            type(metadata.get("task_id")) is not type(self._requested_task)
            or metadata.get("task_id") != self._requested_task
            or metadata.get("dest_version") != self._requested_version
        ):
            return None
        return True

    async def async_install(self, version: str | None, backup: bool, **_kwargs: object) -> None:  # ruff: ignore[boolean-type-hint-positional-argument] -- Home Assistant defines this positional callback signature.
        """Confirm the current offered task once, then rely on version readback.

        Raises:
            HomeAssistantError: If unavailable, already running, backup requested or the API rejects the task.
        """
        if backup or not self.available or self._installing or self._requested_version is not None:
            msg = "NOTTY firmware installation requires an available idle device and does not support backup"
            raise HomeAssistantError(msg)
        self._installing = True
        self.async_write_ha_state()
        try:
            await FirmwareApi(self.coordinator.api).install(
                self.device_id, version, before_confirm=self._remember_request
            )
        except NottyApiError as exc:
            raise HomeAssistantError(str(exc)) from exc
        finally:
            self._installing = False
            self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_release_notes(self) -> str | None:
        """Return the complete already-fetched firmware description.

        Returns:
            Full cloud notes without an external URL request.
        """
        value = firmware_data(self.block).get("firmware_desc")
        return value if isinstance(value, str) else None

    @property
    def installed_version(self) -> str | None:
        """The installed-version field from the current check response.

        Returns:
            The reported source version.
        """
        return firmware_version(firmware_data(self.block).get("src_version"))

    @property
    def latest_version(self) -> str | None:
        """Use the app's empty destination marker for no offered update.

        Returns:
            The offered version, current version for an explicit empty marker, or None.
        """
        destination = firmware_data(self.block).get("dest_version")
        if isinstance(destination, str) and not destination:
            return self.installed_version
        return firmware_version(destination)

    @property
    def release_summary(self) -> str | None:
        """The app's firmware description, without fetching external URLs.

        Returns:
            A summary bounded to Home Assistant's 255-character limit.
        """
        description = firmware_data(self.block).get("firmware_desc")
        return description[:255] if isinstance(description, str) and description else None

    @property
    def available(self) -> bool:
        """Require fresh usable metadata and honor explicit offline readback.

        Returns:
            Whether current version availability can be reported.
        """
        for key in ("online", "is_online"):
            value = value_from_block(self.block, key)
            if isinstance(value, (bool, int, str)) and value in {False, "0", "false", "offline"}:
                return False
        return super().available and self.installed_version is not None and self.latest_version is not None

    @property
    def extra_state_attributes(self) -> DeviceData | None:
        """Keep cloud task status visible without interpreting it as measured progress.

        Returns:
            Only the reported task-status string, without task IDs or arbitrary response fields.
        """
        status = firmware_data(self.block).get("task_status")
        attributes: DeviceData = {"requested_version": self._requested_version}
        if isinstance(status, str):
            attributes["task_status"] = status
        return attributes

    @override
    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """Follow offered target versions rather than assume a semantic version scheme.

        Returns:
            Whether the offered firmware differs from the installed firmware.
        """
        return latest_version != installed_version
