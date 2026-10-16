# Cleaning schedule contracts (#17)

Source: NOTTY Smart Pet 1.1.30, SHA-256
`3b6dc21037f2802e92233ecd9f685e76b03a79afa2d82dd52a5dfcd689a18e6a`.
Addresses refer to local Blutter ARM64 output; the APK and decoded files remain
ignored. Synthetic payloads are in `tests/fixtures/apk_litter_plans.json`.
Paths below are relative to `package:notty/view/tabs/device/device_setting/`.

## Requests and identity

`timing_task/timing_task_controller.dart`, `TimingTaskBinController::getTimingList`
(`0xc0d6e0`), selects `/device/litter_box/plans/` at `0xc0d740`, appends the
physical device ID, and GETs at `0xc0d830`. Its response callback (`0xc0d87c`)
requires a `data` list and assigns the list directly. Device-scoped membership
therefore comes from that GET, not from trusting a submitted plan ID.

| Operation | Endpoint | Serialized fields and evidence |
| --- | --- | --- |
| Add | `/device/litter_box/add_plan` | `time` at `0xcc1050`, `quantity` at `0xcc1074`, `user_device_id` at `0xcc11d0` |
| Edit | `/device/litter_box/edit_plan` | `time`, `quantity`, `plan_id` at `0xcc1154`; no device ID |
| Toggle | `/device/litter_box/open_plan` | `plan_id` at `0xcd7ce4`, `open` at `0xcd7d08` |
| Delete | `/device/litter_box/delete_plan` | only `plan_id` at `0xcd7888` |

Add/edit use `add_timing_task/add_timing_task_controller.dart`,
`AddTimingTaskController::addOrEidtPlan` (`0xcc0fc4`). A nonzero plan ID selects
edit (`0xcc110c`); zero selects add (`0xcc1188`), then both POST at `0xcc11f8`.
The time, quantity and edit-ID closures (`0xcc151c`, `0xcc1480`, `0xcc13e4`)
read the corresponding observable values. The add-device closure (`0xcc13a4`)
boxes the physical ID. The constructor initializes quantity to integer `1`
(`0xd24b2c`) and plan type to `1` (`0xd24aa8`). The quantity controls in
`add_timing_task_view.dart` are gated to feeder type `4` (tagged `8` comparison
at `0xcbf4d0`); litter-box writes use quantity `1`.

Toggle uses `TimingTaskBinController::openPlan` (`0xcd7bec`): the view's switch
callback passes the selected row and Boolean at `0xcd7bd4`. The row is captured
in context field `0x13`; the Boolean in `0x17`. Closure `0xcd7ecc` returns the
row's plan ID. Shared closure `0xc7c30c` returns field `0x17` directly: there is
no integer conversion. The request POST is at `0xcd7d28`. Its success callback
updates only the row's `open` field (`0xcd7dac`). The read-only list can also
contain integer/string state representations; counts must explicitly decode them
rather than treat all nonempty strings as true.

Delete's confirmed callback (`0xcd77a8`) captures the explicit ID. Shared closure
`0xa36c5c` returns context field `0x13`, inserted at `0xcd7888`; POST at
`0xcd78b0`. The integration preserves the ID type returned by the fresh list.
It does not add `device_id` aliases to any schedule request or send unrelated rows.

`TimingTaskBinController::toAddTime` (`0xcd8850`) compares the complete list's
length with unboxed `10` at `0xcd88b4` and rejects adding at or above that limit.
Disabled entries count toward it. This client-side check cannot make concurrent
app edits atomic; the backend remains responsible for enforcing its own limits.

## Clock and recurrence boundary

`setPlanTime` (`0xcc06e4`) seeds the picker from the existing clock string and
formats its selected value with `HH`, `:`, `nn` at `0xcc0c74`–`0xcc0cb8`.
The formatted string is stored as the observable `time` and subsequently passed
to add/edit. The litter-box view displays the returned `time` directly at
`0xcd83a8`. No UTC/offset conversion is established by these inspected paths.

The request has no date, timezone, weekday or recurrence field. An initialized
`plan_type_id` is not serialized by the inspected add/edit map. This establishes
fixed-clock plans, not arbitrary weekday rules or guaranteed daily/DST behavior.
We expose raw NOTTY schedule clock strings and label them accordingly. The reported
device timezone is separate context, not proof of the server's clock basis. We
never reuse DND's apparent Shanghai-read/device-write conversion for schedules.
Time edits reject reported quantity or plan-type values other than integer `1`.

The mode controller describes mode 2 as cleaning at configured fixed times;
management leaves mode unchanged. It does not create prerequisite plans when
changing mode or establish what happens with zero enabled plans. #19 remains
separate; this implementation does not enable mode writes.

## Verification

Synthetic tests cover exact fields/types, device membership, ID preservation,
unknown response shapes, the ten-plan limit, disabled and repeated toggles,
unsupported recurrence, clock strings across seasons, HA action lifecycle,
read-only listing and failures without retries. No schedule writes were performed
against the owner's account or physical device. Server acceptance, creation's
default enable state, actual firing time, DST behavior and recurrence require
owner-observed live checks; #17 remains open for that validation.

## Live plan-schema correction (17 October 2026)

Fresh litter-box plans, including a temporary plan created with this client,
report `plan_type_id: 2` and omit `quantity`. The earlier synthetic type-1
assumption incorrectly blocked edits. Editing now accepts the observed type 2
(or absent type metadata) and quantity 1 (or absent quantity), while rejecting
unknown types/quantities. The write still sends only time, quantity 1 and the
selected native plan ID. No recurrence meaning is inferred from the type marker.
