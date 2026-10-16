# Live API and NOTTY phone-app validation

These developer scripts use the integration's request builders and a saved NOTTY
session. Run `uv sync --frozen --group dev` first. They do not need a running HA
server. `probe_weights.py` also runs with only Python and aiohttp installed.

**Emptying is prohibited.** The shared write transport rejects one-key code 2,
unknown/Boolean/string motor codes and unsupported methods. There is no empty
operation. Clean and level remain explicit physical actions.

## Separate commands

Each command starts with read-only collection. Use a new filename on every run;
captures, app values, requests and reports use `.private.json` and mode 0600.
Keep these files in ignored `probe-output/`. They can contain personal data.

| Script | Evidence / outstanding checks |
| --- | --- |
| `probe_weights.py` | Profile versus daily/other weight candidates; units, timestamp fields, potential historical rows and before/after changes |
| `validate_login.py` | Existing-session read; explicit fresh email-code request/exchange modes |
| `validate_lock.py` | Child lock state and set_key writes |
| `validate_dnd.py` | DND switch, both clocks, preserved LED and reported timezone; edits are device-local times |
| `validate_cleaning.py` | Clean/level acknowledgement and subsequent device/messages readback; record the physical effect yourself |
| `validate_settings.py` | Auto delay, mode and screen language; Scheduled requires an enabled plan |
| `validate_reminders.py` | Enabled flags, configured intervals, remaining counters; action-3 reset and interval writes |
| `validate_schedules.py` | Plan IDs/times/enable state; explicit add/edit/toggle/delete |
| `validate_timezone.py` | Server catalog, device zone and plans; explicit catalog-selected changes |
| `validate_alias.py` | Cloud alias, refreshed discovery; does not test HA's separate name override |
| `validate_pets.py` | Existing pet profile/breed catalog, preserved fields and bindings |
| `validate_associations.py` | One selected pet's profile and physical-box association list |
| `validate_notifications.py` | Account-wide litter-box categories and block state |
| `validate_memos.py` | Pet memo list; add `--memo-id ID` for scoped detail; explicit create/edit |
| `validate_firmware.py` | Installed/offered versions and raw task status; explicit offered-task installation |
| `validate_statistics.py` | Device info, daily counts/messages before/after an explicitly requested irreversible clear |

The old `validate_commands.py` remains available for its original child-lock/DND
workflow. The new physical-command script is `validate_cleaning.py`.

Example for each feature (replace `lock` in the filenames/script):

```sh
uv run python scripts/validate_lock.py \
  --session-file probe-output/session.private.json \
  --device-id YOUR_PHYSICAL_BOX_ID \
  --capture-raw probe-output/lock.before.private.json \
  --template probe-output/lock.app.private.json \
  --output probe-output/lock.report.private.json
```

Pet/memo/association scripts also accept `--pet-id YOUR_PET_ID`. A sole box/pet
can be selected automatically; ambiguous targets require an explicit selection.
IDs must come from your account. No feeder/water device is eligible.

Read the corresponding value in the NOTTY phone app. Edit the generated app
file, entering `equals` with the API field's type, then change
`confirmed_from_app` to `true`. Templates deliberately contain **null pending
placeholders**, not copied API values. Example:

```json
{
  "checks": [
    {"source": "info", "path": ["switch_key"], "equals": 1,
     "confirmed_from_app": true}
  ]
}
```

The app's On label maps to the integer expected by the field; enum meaning must
be checked independently. For lists, use literal indexes/keys such as
`"path": [0, "blocked"]`, verifying the row's ID in the private capture first.
You may add more checks, including preserved profile/binding fields. A missing
field does not match null, and Boolean true does not match integer 1.

Compare offline without contacting NOTTY:

```sh
uv run python scripts/validate_lock.py \
  --from-file probe-output/lock.before.private.json \
  --expect probe-output/lock.app.private.json
```

Add `--show-values` to inspect private API/app values locally. Default console
reports omit them. Exit codes: **0** supplied app values match, **1** failed
reads/mismatches/restoration, **2** input/auth/request failure (a write may be
uncertain), **3** app observations pending. API acknowledgement alone is never
marked as app or physical verification.

## Explicit writes and reversible tests

The owner authorized API testing except emptying. The scripts require a selected
request file so running a feature reader does not accidentally operate hardware.
Use `--execute request.private.json` plus `--capture-raw before.private.json`.
A baseline journal is saved **before** the operation. The after snapshot is saved
as `before.after.private.json`; a roundtrip also saves
`before.restored.private.json`. Nothing is automatically retried.

Example lock request:

```json
{"operation": "set_key", "changes": {"switch": 1}}
```

```sh
uv run python scripts/validate_lock.py \
  --session-file probe-output/session.private.json \
  --device-id YOUR_PHYSICAL_BOX_ID \
  --execute probe-output/lock.request.private.json --roundtrip \
  --capture-raw probe-output/lock-test.before.private.json \
  --output probe-output/lock-test.report.private.json
```

`--roundtrip` restores and checks the original lock, mode/delay/language, alias,
pet edited fields, a selected association or notification category. It attempts restoration even after
an uncertain write failure. Inspect the restoration file and app before retrying
an interrupted test. Immediate readback may lag; a mismatch needs investigation,
not a blind repeat. Roundtrips are deliberately rejected for motor commands,
reminder countdowns, schedules, timezone changes, memos, firmware
and deleted history because their original effect cannot be generically restored.
Those operations can be selected explicitly without `--roundtrip`.

| Feature | Operation | `changes` example |
| --- | --- | --- |
| Lock | `set_key` | `{"switch": 1}` |
| DND | `set_dnd` | `{"switch_dnd": 0}` or device-local clock fields `dnd_begin_time`, `dnd_end_time` |
| Settings | `set_auto_delay` / `set_mode` / `set_language` | `{"delay": 5}` / `{"mode": 1}` / `{"language": 1}` |
| Reminders | `set_litter_remind` / `set_garbage_bag_remind` | `{"action": 1, "cycle_time": CURRENT_CYCLE}` (2 disables) |
| Reminders | `reset_litter_reminder` / `reset_garbage_bag_reminder` | `{"cycle_time": CURRENT_CYCLE}` (reset preserves cycle) |
| Reminders | `set_litter_reminder_days` / `set_garbage_bag_reminder_days` | `{"cycle_time": NEW_CYCLE}` |
| Alias | `set_alias` | `{"alias": "Test box"}` |
| Pets | `update` | `{"name": "Milo"}`; supported birthday/sex/neutered/breed fields follow the integration |
| Associations | `associate` / `disassociate` | `{}`; explicit `--pet-id` selects the pet |
| Notifications | `block` / `unblock` | `{"message_type_id": SERVER_LISTED_ID}` |
| Schedules | `add_plan` / `edit_plan` / `open_plan` / `delete_plan` | `{"time":"06:30"}` / `{"plan_id":ID,"time":"06:30"}` / `{"plan_id":ID,"open":false}` / `{"plan_id":ID}` |
| Timezone | `change` | `{"catalog_id":"EXACT_CATALOG_ID","confirm_schedule_change":true}` |
| Memos | `create` / `update` | `{"fields":{"title":"Visit","content":"Check","date":"2026-10-17 15:00"}}`; update also requires `memo_id` |
| Cleaning | `clean` / `level` | `{}`; empty is never supported |
| Firmware | `install` | `{}`; confirms only a freshly eligible offered task |
| Statistics | `clear` | `{"confirm_irreversible":true}`; data cannot be restored |

JSON examples containing uppercase placeholders must be filled before use. No
bulk write/sweep command is provided. Firmware percentage/realtime events,
installation across restarts, actual timed firing/DST and physical cleaning
behavior require observation beyond a one-shot HTTP test. Statistics clearing's
exact affected history must be established from before/after evidence. HA entity
identity/name overrides must be checked in a running HA instance separately.

Fresh login is separate from checking an existing session:

```sh
export NOTTY_EMAIL='your-account-email'
uv run python scripts/validate_login.py --request-code
# Read the fresh email code, then provide it through the environment:
export NOTTY_VERIFICATION_CODE='your-new-code'
uv run python scripts/validate_login.py --exchange-code \
  --new-session-file probe-output/session-new.private.json
unset NOTTY_VERIFICATION_CODE
```

Code exchange uses the integration's current APK-backed metadata and saves the
session before its authenticated read. It does not test expiry/reauthentication
in a running HA instance or claim automatic refresh-token support.

## Weight before/after evidence

```sh
uv run python scripts/probe_weights.py \
  --session-file probe-output/session.private.json \
  --capture-raw probe-output/weight-before.private.json \
  --output probe-output/weight-before.json

# After a normal visit, take a second snapshot and compare private stable IDs:
uv run python scripts/probe_weights.py \
  --session-file probe-output/session.private.json \
  --capture-raw probe-output/weight-after.private.json \
  --compare probe-output/weight-before.private.json \
  --output probe-output/weight-after.json

# Inspect actual values locally, or reanalyse entirely offline:
uv run python scripts/probe_weights.py \
  --from-file probe-output/weight-after.private.json --show-values
```

Weight reports distinguish profile `weight` from daily/other measurement
candidates, reject nonpositive/nonfinite/Boolean values, preserve unverified unit
codes, and show available timestamp field types. Comparing responses is not
per-visit event deduplication. Numeric-series rows are candidates, not historical
measurements proven to have a known date, unit and cat attribution. This tool
does not import past records into HA.

## Development run, 17 October 2026

All fifteen feature readbacks completed without endpoint errors using the owner's
saved session. Phone-app observations remain pending. Lock, one notification
category, device alias and one pet name were tested with temporary changes and
restoration. Notification/alias/pet changes appeared in API readback; restoration
matched the baselines. The pet's weight, unit, image path, collar and device
bindings were unchanged. The child-lock request was acknowledged, but immediate
readback did not change; its effect is **unverified**, not a passed test.

Both pets returned positive profile weight plus today_weight/yesterday_weight,
unit code 1 and no measurement timestamp. The scoped litter-box responses had no
recognized weight fields. This does not establish the enum meaning, per-visit
sampling, missing history, or which daily value the app displays.

No motor command, reminder reset, schedule/timezone change, firmware installation
or history deletion was performed in this development run. Those scripts exist
for explicit owner-selected tests with app/physical observations. No empty command
was sent. Raw captures and editable app-value templates remain private under
`probe-output/app-validation-20261017/`; they are not published in GitHub.

## Follow-up verification, 17 October 2026

The child-lock request now follows the exact APK contract: integer
`user_device_id`, integer `switch`, and no legacy `device_id` field. A live
transition and restoration both matched API readback after two seconds. This
resolves the earlier unchanged-immediate-readback result. The scripts now poll
GET readback after one mutation; they never resend a write while waiting.
Use `--readback-attempts 4 --readback-interval 2` to control the bounded wait.
Restoration also waits for matching readback. A final mismatch remains a failure.

DND off/on, English/Icons and Auto/Soft stool changes were also observed in live
API readback, then restored. Raw DND boundaries and LED were unchanged throughout.
DND switch-only and selected known-association roundtrips are now supported; clock edits still require explicit
before/after app verification. Actual scheduled firing and DST remain separate
checks, not implied by matching JSON clocks. The device currently reports
`auto_delay: 0`, outside the app-traced 1–15 minute write options; an automatic
roundtrip must not alter it because the original value cannot be safely restored
through that established contract.

Inspect coverage of every in-scope issue without contacting NOTTY:

```sh
uv run python scripts/validation_status.py \
  --evidence-dir /absolute/path/to/probe-output
```

This lists script coverage, observed API/app comparisons, failures and restoration
results. It does not automatically close an issue or treat a script's existence
as successful validation. Older failure reports can coexist with newer passes.
Feeders/water (#27/#28) remain deferred. See [issue coverage](validation-coverage.md).

Monitor an owner-selected firmware update without starting another installation:

```sh
uv run python scripts/monitor_firmware.py \
  --session-file probe-output/session.private.json \
  --device-id YOUR_PHYSICAL_BOX_ID \
  --output-dir probe-output/firmware-observation \
  --samples 12 --interval 10
```

Each sample and the selected target are saved privately. To continue after
restarting the script, pass `--target-version EXACT_PREVIOUS_TARGET` and a new
output directory. Only matching installed-version readback confirms completion;
a success status alone does not. A failure from a different offered target is
not attributed to the selected update. No firmware is installed by this monitor,
no percentage is inferred, and this does not add restart persistence or realtime
firmware-event subscriptions to HA itself. On the owner's current device there
is no offered firmware update, so installation/failure lifecycle validation needs
a future offer.

The follow-up schedule test found and fixed a real edit guard error: litter-box
plans report `plan_type_id: 2`, not the earlier assumed 1. After correction,
a temporary plan passed create, edit, disable, enable and delete. Scheduled mode
readback also matched, then the original mode and all original plan records
were restored. A selected pet association was toggled and restored with matching
readback. Actual scheduled physical firing still needs observation; these
roundtrips do not assert that it occurred.

Completed implementation tickets link to [#42](https://github.com/Repsay/notty/issues/42)
for their remaining external acceptance checks. #21, #22 and #41 retain the
specific timezone, firmware and measured-weight work. Emptying is excluded.
