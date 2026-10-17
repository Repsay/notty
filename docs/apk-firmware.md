# Firmware metadata and installation boundary (#22)

Source: NOTTY Smart Pet 1.1.30, SHA-256
`3b6dc21037f2802e92233ecd9f685e76b03a79afa2d82dd52a5dfcd689a18e6a`.
All addresses refer to local Blutter ARM64 output. The APK and decoded files stay
ignored. `tests/fixtures/apk_firmware.json` contains invented versions/task IDs
and a separately transcribed request/field contract, not private API captures.

## Read-only metadata

In `view/tabs/device/device_setting/version_upgrade/version_upgrade_controller.dart`,
`DeviceVersionUpgradeController::checkUpdate` (`0xbecd4c`) concatenates the physical
ID with `/device/check_upgrade/` at `0xbecde0`, then GETs at `0xbecdfc`. Its
response callback (`0xbece48`) reads `data`; callback `0xbecef8` copies recognized,
non-null keys to the controller's observable field map. The constructor includes
`src_version`, `dest_version`, `task_id`, `task_status`, `utc_create`,
`utc_modified` and `firmware_desc`.

The corresponding `version_upgrade_view.dart` reads:

| Field | View address | Meaning established by the surrounding UI |
| --- | --- | --- |
| `src_version` | `0xcd9170` | current firmware version, label `当前版本号` at `0xcd90e8` |
| `dest_version` | `0xcd93a8`, `0xcd9a00` | offered/new version; empty target selects the no-update label `无需更新` at `0xcd9aa8` |
| `firmware_desc` | `0xcd962c` | version notes (`版本日志` at `0xcd95a4`); empty notes select a no-notes label at `0xcd970c` |

The integration uses the endpoint response already collected by the coordinator,
so the entity adds no network calls. It is created only for supported physical
litter boxes reporting both version keys, including when the optional endpoint
recovers after startup. Pets and other device kinds are excluded. An empty target
string means latest equals installed. Null/missing/invalid targets are unknown,
not evidence of no update. Version strings are opaque; an offered recovery build
must not be hidden by assuming a semantic-version ordering.

The entity becomes unavailable after coordinator failure, device removal,
explicit offline flags or missing/malformed metadata. It reads the current raw
upgrade response rather than stale flattened version summaries. Release notes
are summarized to Home Assistant's 255-character limit. Only raw `task_status`
is added as a custom attribute; task IDs and arbitrary backend fields are not
copied into the entity. Installation eligibility is computed from current metadata; full notes are exposed in the update dialog.

## Explicit confirmation of a fresh task

`confirmUpdate` (`0xcc5264`) builds only `task_id` (`0xcc52f0`) and
`user_device_id` (`0xcc5314`), then POSTs `/device/confirm_upgrade` at `0xcc5338`.
Closure `0xcc548c` gets the current task observable; `0xcc5224` boxes the physical
ID as an integer. The success callback sets an app-local busy flag at `0xcc53e4`.
This is not independent evidence of a completed installation. The task-ID type,
current-task eligibility, supported models and behavior during failures still
need live verification. The unchecked generic `confirm_upgrade` API action remains removed. The update entity supports an explicit install after fresh owned-device and offered-task checks, preserving the server task ID type and using an integer physical ID. An absent/busy/unknown task or a requested version different from the offer is rejected. No automatic installation or request replay is implemented.

## Progress is a separate event flow

`share/utils/xjCore.dart` dispatches event types `"19"` and `"20"` to
`firmwareUpgrade` (`0xbec454`) and `firmwareUpgradeState` (`0xbec514`). Both
handlers check the physical ID before updating the screen. `firmwareUpgrade`
starts a periodic timer at `0xbed1d8`; its callback uses a local counter to display
percentages and parses the event's `step` string at `0xbed35c`. The displayed
percentage is therefore not established as an HTTP metadata field or a measured
value that Home Assistant can reproduce from ordinary polling.

`firmwareUpgradeState` (`0xbec52c`) recognizes terminal event statuses
`SUCCEEDED` (`0xbec644`), `FAILED` (`0xbec6bc`) and `CANCELED` (`0xbec72c`). Success
triggers a fresh `checkUpdate` at `0xbec67c`. We do not assume that the HTTP
`task_status` field has the same complete lifecycle vocabulary, derive an active
state from an unknown status, or turn a success string into a fabricated installed
version. Later version readback remains authoritative.

## Verification status

Synthetic tests cover version availability, explicit empty versus missing targets,
opaque version labels, task failures/unknown states, metadata loss/recovery, late
discovery, offline devices, lifecycle, bounded notes, exact confirmation payloads and rejected absent/busy/unknown tasks.
They do not verify production API payloads or device firmware behavior. No model
has yet been validated for this new entity; no firmware update or cloud write was
performed during development. #22 remains open for model validation and the separate realtime progress lifecycle. The HA entity tracks only its own requested target in memory until installed-version readback or a reported failure/cancellation; no measured percentage or restart persistence is claimed.


## Follow-up: restart persistence and native push

The previous in-memory-only limitation is superseded by persistent task tracking.
The native event transport was traced to Android JPush, rather than a verified
HA-compatible socket. See [remaining-validation.md](remaining-validation.md).
