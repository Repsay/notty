# APK-backed API contracts

**Live correction (17 October 2026):** The timezone setter assumption below was disproved by live testing. The backend stores the supplied Windows string as an invalid IANA value. Changes now require an explicit valid IANA name and verify both fields. See [remaining-validation.md](remaining-validation.md) for the corrected contract and opt-in DND preservation.

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

Some older device actions retain a `device_id` alias alongside `user_device_id`.
That is compatibility behavior, not a field established by these app paths.
Child lock now uses only the exact APK fields.

## Child lock (#11)

`SettingController::setLitterBoxLock` at `0xcd3e24` captures the boolean argument
in context field `0x13`. Its shared closure at `0xccd7dc` converts the Dart boolean
to an integer (`cset`, then the Dart small-integer tag shift): true becomes `1`,
false becomes `0`. The map inserts `switch` at `0xcd3ebc` and POSTs at `0xcd3f04`.
Reading state continues to use `switch_key` and entity unique IDs are unchanged.
The physical-ID closure `0xcc1b14` boxes the controller ID as an integer. The
child-lock builder now sends exactly integer `user_device_id` and integer
`switch`, rejecting legacy aliases, target overrides and non-enum values. An
owner-authorized live change and restoration both matched fresh API readback
after two seconds on 17 October 2026. This verifies the endpoint flag transition,
not physical button behavior on every model.

## Do Not Disturb (#12)

`IndicatorLightTimeController::saveIndcatorTime` at `0xcc6fc8` inserts LED, times
and device ID; its litter-box branch adds `switch` at `0xcc7104`. The switch
closure at `0xcc73d4` reads the controller boolean and converts it to integer
`0`/`1`. The LED closure at `0xe92364` returns tagged `4`, meaning Dart integer
`2`. This app screen explicitly selects LED mode `2` when saving the schedule.

The integration preserves the device's reported LED value instead of forcing
mode `2` during a DND-only edit. This preservation policy still needs live
verification.

**Owner DND roundtrip (2026-10-16):** The app showed start 07:00 and end 22:00
in Europe/Amsterdam (CEST, UTC+2), while GET `get_info` reported 13:00 and
04:00. Reposting the raw readback as `set_dnd` fields produced 19:00 and
10:00: another +6-hour shift. The switch remained enabled, so checking only
`switch_dnd` falsely reported success.

The new conversion treats readback DND clocks as an apparent Asia/Shanghai
wall-clock representation (UTC+8) and translates to Home Assistant's configured
IANA zone for display. When writing, **device `time_zone_iana` takes priority**
over the Home Assistant fallback. Unchanged fields are translated from the
API's clock representation to the device timezone; edited times are translated
from HA's timezone to the device timezone. The `led` and `switch` values are
preserved, and equal start/end times cannot be enabled. An invalid reported
device timezone blocks the write instead of silently falling back.

Because these are recurring clocks without dates, conversions use the current
offsets; synthetic tests cover CEST/CET and different HA/device zones.
Future DST changes require separate owner validation: the server's scheduling
semantics across transitions have not been established. In particular, the
`Asia/Shanghai` storage assumption is grounded in one live device's behavior,
not a general guarantee for every NOTTY model/region.

The standalone `validate_commands.py` tool auto-uses a reported
`time_zone_iana`; if absent, the operator must supply `--time-zone`.
After any DND write it compares the entire LED/time window, not only the
on/off state, and reports drift instead of auto-retrying.

**Owner follow-up (2026-10-16):** Before the corrected write, the API
reported DND `19:00–10:00`, corresponding to `13:00–04:00` Amsterdam
time at the current +6-hour offset. The PR's live dry-run constructed
`13:00–04:00` and an explicitly confirmed write returned the **same
`19:00–10:00` readback**, with LED and enabled state unchanged.
This verifies an actual no-drift roundtrip on this device in CEST.
It does **not** restore the original desired `07:00–22:00` schedule:
the user must set that schedule separately in the official NOTTY app.
Future DST behavior and cross-region devices remain unverified.

## Device timezone catalog and setting (#21)

The NOTTY app's timezone controller refers to
`/entity/get_time_zones` (catalog read; APK address `0xc0d018`) and
`/device/change_time_zone` (setting write; `0xcd6570`).

**Owner-observed live catalog on 2026-10-16:** GET
`/entity/get_time_zones` succeeded and returned **141 entries** in
a top-level array. Each entry contains `id`, `display_name`, and
`offset`, all **strings**. An Amsterdam entry was:

```json
{
  "id": "W. Europe Standard Time",
  "display_name": "(UTC+01:00) Amsterdam, Berlin, Bern, Rome, Stockholm, Vienna",
  "offset": "01:00:00"
}
```

`id` is a **Windows timezone identifier**, not an IANA name or numeric
code. Unicode CLDR windowsZones maps this Windows ID to `Europe/Amsterdam`
for territory **NL** (global default `Europe/Berlin`); country context is
therefore necessary for an exact regional IANA mapping. The catalog's
`01:00:00` is a standard-offset label, **not evidence of a live DST offset**:
Amsterdam is UTC+02:00 on 2026-10-16 and UTC+01:00 in winter. Do not
use this field alone for scheduling or HA↔NOTTY conversions.

**Owner live device inspection, also 2026-10-16:** both the account
device listing and `/device/litter_box/get_info` returned
`"time_zone_iana": "Europe/Amsterdam"` for the same device. This
confirms that this device stores/reports its selected zone in **IANA**
format even though the selection catalog uses **Windows** identifiers.
There was no separate `time_zone_id` in either inspected response.
Keep three concepts distinct:

- **Catalog choice:** Windows ID `W. Europe Standard Time`.
- **Configured device zone:** IANA `Europe/Amsterdam`.
- **Home Assistant zone:** its own configurable IANA timezone; the
  cloud's apparent Shanghai DND readback clock remains a separate
  hypothesis requiring broader validation.

The setter is now traced end-to-end in the APK: the view reads the selected
row’s `id` at `0xcd6280` and passes that string to `confirmTimeZone` at
`0xcd62e8`. The captured string is inserted under `time_zone_iana` at
`0xcd6534` (shared closure `0xa36c5c` returns context field `0x13`).
The physical ID closure `0xcc13a4` boxes controller field `0x27` as an
integer at `0xcc13bc`. The two-field request is POSTed at `0xcd657c`.
Thus the misnamed `time_zone_iana` request field carries the Windows
catalog ID, while device readback uses IANA. This is static app evidence;
server acceptance and schedule behavior remain unverified. The
integration's existing DND builder can use the verified device IANA
readback without Windows conversion; it must not use catalog offsets.

The opt-in `scripts/probe_timezones.py` performs **one read-only GET**
and prints only schema paths, types and total entry count by default.
Use `--find Amsterdam` to show at most ten matching `id`,
`display_name` and `offset` triples, with all other keys excluded;
`--capture-raw` remains optional and stores raw replies only in
local `*.private.json` files. The public integration does **not**
poll the catalog or infer timezone IDs from IANA names. The explicit
`notty.device_time_zone` action lists the validated catalog and can submit
one selected catalog ID with `confirm_schedule_change: true`.
The optional `--device-id` argument adds two read-only calls (account
device listing and the selected litter-box info) and returns only
whitelisted timezone fields; it never includes device identifiers,
aliases or unrelated account fields.

The existing dynamic `time_zone_iana` sensor gets read-only diagnostic
attributes: validated device IANA zone, current device/HA UTC offsets,
their difference, and the **assumed** API event clock basis
(`Asia/Shanghai`). It preserves the existing sensor identity. These values
do not imply that the app's timezone-selection catalog has been decoded.
Offsets are instant-dependent: European and US DST transitions differ,
so unit tests compare summer, interstitial transition and winter dates.

Timezone changes capture DND fields and complete cleaning-plan readback
before and after one write. Unreadable baseline or mismatched identity
blocks the operation. A directly reported matching Windows ID is a no-op;
we do not infer equality from an IANA name. Differences are reported without
automatic retries, rollback or rewriting clock fields. Acknowledged writes
with failed readback are distinguished from read failures before writing.
The app warns at `0xcd63d0` that operations use the selected device local
time: unchanged clock strings therefore do not prove unchanged firing times.
Issue #21 remains open for an owner-selected live change, app confirmation,
and schedule/DST preservation validation. No timezone was changed here.

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

Further static tracing of the Reset label in `SettingController` (`0xcccb30`, action insertion `0xcccc68`) establishes action **3** with the configured cycle for both reminder types. Reset buttons and the trash-bag interval selector now use this contract, with fresh enabled-state/cycle validation. Reset must retain the existing cycle; interval changes skip same-value writes. Same-cycle reset and trash-bag action 3 have **not** been exercised live. The original action-2 reset assumption remains incorrect. See [additional APK evidence](apk-pet-maintenance.md).

## Verification boundary

Automated checks establish request construction, Home Assistant service behavior,
state preservation, bounds and refresh behavior. They do not establish server
acceptance or physical behavior. Issues #11, #12, #16 and #18 remain open pending
owner-observed live validation. No device commands are sent by this test suite.

## Email verification authentication (#13, #14)

`view/login/login_account/login_controller.dart`, `LoginController::login`
(`0xc87640`), constructs `/account/login_by_email` with exactly `email`, `code`,
`device_id` and `version_number`. The device ID is the string `"1"` loaded at
`0xc876f8`; it is not a physical device identifier. The version closure
(`0xc7ff10`) returns `AppConfig.app_version_number`. Its initializer (`0xc80784`)
joins the package version, `"+"`, and build number: `"1.1.30+76"` for this APK.

The separate `/account/get_email_code` request (`0xc88fa0`) contains `email`,
`code_type_id: 1` (login), and `client_id: "0"`. Those last two fields do not
belong in the login exchange. HTTP defaults include the app's `User-Aagent`
header and anonymous `HZUID: "2"`; authenticated requests use the stored NOTTY
session token. The integration retains its existing compatibility headers.

The inspected email flow does not establish any password or Firebase email
password endpoint. Google authentication uses `/account/login_by_google` and
is a separate flow. The integration now supports email codes only and rejects
an `idToken` as a NOTTY session credential. A code is discarded after one exchange,
including failures. Expired sessions trigger Home Assistant reauthentication;
they never replay a code or try speculative endpoints. No refresh-token exchange
has been established. Migration preserves existing sessions and removes stored
passwords, Firebase API keys, and verification codes.

An earlier local email-code login succeeded with the previous payload, which
omitted the app version and used extra fields. This shows that the observed
request differences did not prevent that login; it does not establish which
metadata fields the server requires. We now choose the traced app metadata for
consistency, while retaining existing HTTP compatibility headers.

Synthetic tests verify payloads, failure handling, credential cleanup and
migration. The corrected metadata still requires a fresh live login to establish
server acceptance; these changes do not claim new live authentication validation.

See [one-key commands and mode contracts](apk-command-contracts.md) for #15 and #19, including corrected command values and remaining live-validation boundaries.
