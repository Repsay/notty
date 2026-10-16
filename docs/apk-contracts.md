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

## Verification boundary

Automated checks establish request construction, Home Assistant service behavior,
state preservation, bounds and refresh behavior. They do not establish server
acceptance or physical behavior. Issues #11, #12 and #16 remain open pending
owner-observed live validation. No device commands are sent by this test suite.
