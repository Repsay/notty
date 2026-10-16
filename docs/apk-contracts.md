# APK-backed settings contracts

These contracts were traced in NOTTY Smart Pet 1.1.30 (SHA-256
`3b6dc21037f2802e92233ecd9f685e76b03a79afa2d82dd52a5dfcd689a18e6a`).
Addresses refer to Blutter's ARM64 annotated assembly. APK inputs and decoded
output remain local and ignored. Tests use synthetic data.

| Setting | Read fields | POST endpoint and write fields |
| --- | --- | --- |
| Child lock | `switch_key` | `/device/litter_box/set_key`: `switch`, `user_device_id` |
| Do Not Disturb | `switch_dnd`, `led`, `dnd_begin_time`, `dnd_end_time` | `/device/litter_box/set_dnd`: `switch`, `led`, `dnd_begin_time`, `dnd_end_time`, `user_device_id` |
| Automatic cleaning delay | `auto_delay`, `mode` | `/device/litter_box/set_auto_delay`: `delay` (integer minutes), `user_device_id` |
| Litter renewal reminder | `open_litter_remind`, `default_remaining_days`, `remaining_days` | `/device/litter_box/set_litter_remind`: `action` (1 enable, 2 disable) and required `cycle_time`; `user_device_id` |
| Trash bag reminder | `open_garbagebag_remind`, `garbage_bag_cycle_time`, `garbage_bag_remaining_days` | `/device/litter_box/set_garbage_bag_remind`: `action` (1 enable, 2 disable) and required `cycle_time`; `user_device_id` |

The client currently adds a `device_id` alias alongside `user_device_id` for
device actions. That is existing compatibility behavior, not a field established
by these app paths.

## Child lock (#11)

`SettingController::setLitterBoxLock` at `0xcd3e24` captures the boolean argument
in context field `0x13`. Its shared closure at `0xccd7dc` converts the Dart boolean
to an integer (`cset`, then the Dart small-integer tag shift): true becomes `1`,
false becomes `0`. The map inserts `switch` at `0xcd3ebc` and POSTs at `0xcd3f04`.
Reading state continues to use `switch_key` and entity unique IDs are unchanged.

## Do Not Disturb (#12)

`IndicatorLightTimeController::saveIndcatorTime` at `0xcc6fc8` inserts LED, times
and device ID; its litter-box branch adds `switch` at `0xcc7104`. The switch
closure at `0xcc73d4` reads the controller boolean and converts it to integer
`0`/`1`. The LED closure at `0xe92364` returns tagged `4`, meaning Dart integer
`2`. This app screen explicitly selects LED mode `2` when saving the schedule.

The integration preserves the device's reported LED value instead of forcing
mode `2` during a DND-only edit. This preservation policy needs live verification:
the decoded schedule screen alone does not establish whether the server requires
LED mode `2` for a particular DND behavior. Unknown LED, switch or time values
prevent writes. The switch, time entities and local validation helper share the
same request builder. Enabling with equal boundaries is rejected; disabling
preserves an existing equal-boundary interval.

## Automatic cleaning delay (#16)

`SettingController` builds the delay picker at `0xc0b05c`: an unboxed integer loop
starts at `1`, stops after `15`, labels each item with the minutes translation
(`XX分钟`), and stores its integer `value`. `delayMode` at `0xcd466c` gates the
picker on raw mode `1` (tagged `2` at `0xcd4720`). It reads `auto_delay` at
`0xcd478c`. The picker callback extracts the selected item's integer `value`
at `0xcd4a04`, inserts `delay` at `0xcd4ad0`, and POSTs at `0xcd4b18`.

The configuration select offers 1–15 minutes only, is unavailable outside Auto
mode or without current delay data, and reports unknown values without adding
them to writable choices. Its ID is `{physical_device_id}_setting_auto_delay`.
The generic action service does not expose this endpoint yet; the select applies
the mode restriction. API validation also rejects noninteger/out-of-range delays.

## Reminder switches and resets (#18)

The decoded `SettingController::setByProduct` branches select
`/device/litter_box/set_litter_remind` at `0xccac2c`, reading
`open_litter_remind` at `0xccac60`; for trash bags they select
`/device/litter_box/set_garbage_bag_remind` at `0xccad00`, reading
`open_garbagebag_remind` at `0xccad34`. The client also adds the
pre-existing `device_id` alias to `user_device_id`, which is not
independently established by the decoded APK paths.

**Live owner validation on physical device 52963 (2026-10-16):**

- `action=1`, with `cycle_time`: accepted for both reminder endpoints;
  `open_litter_remind` / `open_garbagebag_remind` changed to true,
  configured cycles stayed at 30 / 8 days respectively, and the remaining
  days changed from 0 to those configured values.
- `action=2`, with `cycle_time`: accepted for both endpoints, but
  **disabled** the reminders, leaving configured cycles unchanged; the
  remaining-days counters were 0. This is not a reset operation.
- `action=3`, without `cycle_time`: rejected on both endpoints with
  server messages requiring valid configured days (5–30 for litter, 2–15
  for trash bag).
- `action=3`, **with** `cycle_time=30`: accepted on the **litter**
  endpoint while already at a 30-day countdown. All values remained 30;
  this did not demonstrate a reset.
- `action=3`, **with** `cycle_time=29`: accepted on the **litter**
  endpoint while the reminder was enabled. Three consecutive readbacks
  confirmed `open_litter_remind=true`, `default_remaining_days=29`,
  and `remaining_days=29` (all were 30 before the request).
  This establishes that action 3 changes the configured litter interval
  **and** sets the remaining countdown to that interval. It does *not*
  separately prove a same-cycle reset. Action 3 remains **untested for
  trash bags**.

The safe configuration switches now use `action=1` to enable and
`action=2` to disable, **always** validating and sending the current
configured `cycle_time`. Unknown enable states, invalid cycles and
no-op switches never send a write. This preserves the configured cycle
but does not preserve the *remaining countdown* when enabling; on the
tested device, enabling restarted the countdown.

The **litter renewal interval selector** and matching generic
`set_litter_reminder_days` service now use the verified `action=3`
with a supplied, validated `cycle_time` in the 5–30 day range. Only
**enabled** reminders with a valid configured interval can be edited.
Selecting the existing interval does not write, since the effect of an
unchanged-cycle action 3 on a partially elapsed countdown is unverified.

`reset_litter_reminder`, `reset_garbage_bag_reminder`, and
`set_garbage_bag_reminder_days` remain **blocked at the API
boundary**, including their HA reset buttons, the trash-bag interval
selector and generic service. The original `action=2` assumption
disabled reminders, and bag action 3 has not been tested live.


## Verification boundary

Automated checks establish request construction, Home Assistant service behavior,
state preservation, bounds and refresh behavior. They do not establish server
acceptance or physical behavior. Issues #11, #12, #16 and #18 remain open pending
owner-observed live validation. No device commands are sent by this test suite.
