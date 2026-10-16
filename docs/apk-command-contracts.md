# Litter-box commands and modes from the APK

Source: NOTTY Smart Pet **1.1.30**, SHA-256
`3b6dc21037f2802e92233ecd9f685e76b03a79afa2d82dd52a5dfcd689a18e6a`.
Addresses refer to Blutter's annotated ARM64 output. The APK and decoded output
stay local and gitignored; fixtures contain synthetic IDs and transcribed contracts.

## One-key operations (#15)

All paths below are relative to `package:notty/`.

| Operation | UI label address in `view/tabs/device/litter_box/litter_box_view.dart` | UI callback and unboxed argument | Controller confirmation | JSON `one_key` |
| --- | --- | --- | --- | --- |
| Clean | `立即清理`, `0xceb6a8` | closure `0xcec628`, argument `1` at `0xcec65c`, call `0xcec660` | immediate cleaning, `0xcec238` | `1` |
| Empty | `清除猫砂`, `0xcebdb0` | closure `0xcec0d8`, argument `2` at `0xcec10c`, call `0xcec110` | all litter into garbage bag, `0xcec254` | `2` |
| Level | `抚平猫砂`, `0xceba2c` | closure `0xcec5d8`, argument `3` at `0xcec60c`, call `0xcec610` | smooth litter, `0xcec26c` | `3` |

The callbacks call `LitterBoxController::sterilizeHandle` at `0xcec128` in
`view/tabs/device/litter_box/litter_box_controller.dart`. Despite its name, its
confirmation strings describe the three operations above. At `0xcec168`, the
unboxed argument is shifted left once and stored in context field `0x13`.
The shared closure `0xc0a4e0` in
`view/tabs/mine/setting/unit_managment/unit_managment_controller.dart` returns
that exact field (`0xc0a4ec`). The value is therefore a Dart integer, not an
additional offset or a boolean. The confirmation callback inserts `user_device_id`
at `0xcec424`, `one_key` at `0xcec448`, and POSTs
`/device/litter_box/one_key` at `0xcec46c`.

Minimal synthetic payloads are recorded independently in
[`tests/fixtures/apk_litter_commands.json`](../tests/fixtures/apk_litter_commands.json).
The fixture tests check API calls, buttons and named HA services. One mapping in
`api.py` owns all exposed entry points. Only integer codes 1–3 and their names
are accepted; booleans, floats, numeric strings and unsupported codes fail before
HTTP. Generic one-key requests use the same validated command method and retain
the selected physical ID. Feeder/dispenser commands do not inherit these values.

The former `clean=0`, `level=1`, `empty=2`, `sterilize=3` mapping was inconsistent
with both UI callers and confirmations. Clean and level are corrected, and the
unsupported sterilize button/service option is removed. Existing numeric
HA automations need review: **1 means clean, 3 means level**. Existing stale
sterilize registry entries may remain unavailable until removed in HA.

No start/stop variant, meaning for zero, or litter-box sterilize command is
established by these inspected callers. The method name alone establishes none
of those operations. No device commands were executed during this work. Physical
effects still require individual owner-observed tests; #15 remains open for that.

## Cleaning modes (#19)

`LitterBoxController::changeMode` at `0xcec97c` uses the same argument capture,
integer boxing and shared field-return closure as above. Its confirmation texts
independently identify all three values:

| Value | Readback label | UI callback / call | Confirmation and behavior |
| --- | --- | --- | --- |
| `1` | Auto | `0xced1a0` / `0xced1d8` | `0xcecb28`: clean once after the cat leaves |
| `2` | Scheduled | `0xced150` / `0xced188` | `0xcecb44`: clean at the configured fixed times |
| `3` | Soft stool | `0xcec92c` / `0xcec964` | `0xcecb5c`: swing to cover litter after departure, then clean after 15 minutes |

The view labels Auto (`自动清理`) at `0xcea250` and Scheduled (`定时清理`) at
`0xcea820`, linking their touch callbacks at `0xcea488` and `0xceaa58`.
The controller inserts `mode` at `0xcecd14`, `user_device_id` at `0xcecd38`,
and POSTs `/device/litter_box/set_mode` at `0xcecd5c`.

Raw mode 1 already had owner-observed Auto readback. Modes 2/3 now have static
label/value evidence and are displayed accurately; unknown values retain numeric
fallbacks. Auto delay remains editable only in mode 1. Mode 2 relies on fixed
cleaning plans (#17); the inspected mode request itself does not create a plan
or establish behavior when no enabled plan exists. Soft-stool mode's stated
15-minute delay is not evidence that the Auto-delay field configures it.

All mode writes remain blocked pending schedule prerequisites and live tests.
The API now applies this guard too; the generic service no longer advertises
`set_mode`. This closes the earlier bypass of the select guard. #19 is partially
addressed, not complete: these labels are static app evidence, not a claim of
successful mode changes on the owner's hardware.
