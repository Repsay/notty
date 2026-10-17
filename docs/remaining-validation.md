# Remaining litter-box validation

## Timezones (#21)

Live testing on 17 October 2026 disproved the APK-only setter assumption. Sending
`W. Europe Standard Time` under `time_zone_iana` stores that Windows name as the
reported IANA value. It is not a valid IANA zone and breaks later clock conversion.
Returning to the original Windows ID alone does not repair it. The backend also
shifts DND readback clocks during timezone changes.

The change action now requires both the server catalog ID and an explicitly
selected valid IANA name. It sends the IANA name and verifies both reported fields.
No Windows-to-IANA mapping is invented. Existing change automations must add
`iana_time_zone`; incomplete requests fail before writing.

```yaml
action: notty.device_time_zone
data:
  user_device_id: YOUR_PHYSICAL_BOX_ID
  operation: change
  catalog_id: GMT Standard Time
  iana_time_zone: Europe/London
  confirm_schedule_change: true
  preserve_dnd_local_times: true
```

Preserving DND is opt-in. It preserves the original device-local start/end,
enabled state and LED through one additional settings write. A preservation error
is reported as a partial failure after the timezone has changed; it never replays
the timezone change, silently rolls back or rewrites cleaning plans. Inspect the
response and phone app before retrying a partial failure. Unchanged raw clocks
alone do not prove unchanged local behavior.

The corrected Amsterdam → London → Amsterdam run restored both timezone fields,
all original DND/settings values and every cleaning plan. DST firing remains an
external acceptance check. The offline observer handles gaps, repeated clocks,
non-hour offsets and UTC date boundaries without inventing device DST behavior:

```sh
uv run python scripts/validate_schedule_observation.py \
  --date 2026-10-25 --local-time 02:30 --time-zone Europe/Amsterdam
```

On that date 02:30 has two UTC occurrences. Select `--occurrence 1` or `2` and
supply the independently observed physical start, for example
`--observed-at 2026-10-25T02:30:20+02:00`. No observation means pending, never pass.
A spring-forward gap has no valid occurrence. These calculations do not determine
whether NOTTY will skip, repeat or move a cleaning at that boundary.

## Firmware (#22)

HA persists its requested target, exact task identity and pre-confirmation status
before sending the installation POST. Reload/startup resumes tracking without
resending it. A transport timeout remains pending because acknowledgement may
have been lost after the backend accepted the request. A failed storage write
prevents the confirmation POST.

Installed-version readback establishes completion. A matching task's new failure
or cancellation ends tracking; an old failure from before a retry does not.
Another task's failure cannot complete this request. Changed task identity makes
progress unknown and installation stays blocked while the original request is
unresolved. HA restart/reload recovery has automated coverage. No measured
percentage is fabricated.

The APK's event path is Android JPush: `XjCore::jpInit` creates JPush at `0xbeb424`,
registers event handlers at `0xbeb478`, obtains a registration ID at `0xbeb4d4`, and
registers the phone token through `/message/update_device_token` at `0xbeb630`.
The event callback dispatches firmware event types 19/20. This is not a verified
HA-compatible WebSocket/MQTT endpoint. The integration keeps HTTP polling; it does
not overwrite a phone's push registration or claim a native JPush subscription.

A fresh live read still reports no offered update. Installation, offline/reboot
and failure behavior on hardware require a future actual offer. Use
`validate_firmware.py` and `monitor_firmware.py` then.

## Weight tracking (#41)

The existing per-cat today/yesterday weight sensors now use fresh profile values
instead of allowing older discovery values to overwrite them. Unknown, absent,
zero, negative, Boolean and nonfinite values remain unknown. Missing daily values
never fall back to an editable profile/reference weight. New optional fields are
discovered after startup and existing entity IDs remain stable.

APK `AddCatsController` compares tagged integer 1 with the kg label
(`0xbf39e8` → `0xbf3a14`) and integer 2 with lb
(`0xbf3a94` → `0xbf3ac0`). Its save closure `0xc8aecc` reads and returns the same
`weight_unit`. Profile editing now accepts exactly 1/2 rather than the erroneous
0/1. Daily weight sensors normalize recognized units to kilograms so HA statistics
keep a consistent unit. Other/missing unit codes produce unknown readings.

Each sensor identifies its source field and daily cloud-summary role. It reports
measurement time as null and freshness as not reported: receiving a new poll is
not evidence of a new weigh-in. Standard HA Recorder can retain these reported
summary values going forward; it is not a timestamped per-visit weight log or a
historical import.

Fresh live reads found weight candidates only in pet profiles, with no measurement
timestamps in the inspected responses. They do not establish an independent
measured source. `probe_weights.py --compare` can compare captures around an
independently observed visit. NOTTY's upstream attribution of a weight to the
wrong cat remains outside this integration; identities are never swapped.

## Physical and installed-HA checks (#42)

The owner physically confirmed normal cleaning and leveling after separate live
commands on 17 October 2026. Emptying is excluded and remains blocked in the
validation transport. The automatic delay still reads 0; its app meaning must be
established before testing a change which cannot restore that original value
through the APK-supported 1–15 minute setter.

Fresh email-code exchange, actual installed-HA UI/reauth observations, selected
memo/reminder semantics and the exact effect of statistics deletion remain
external checks. No history is deleted merely to obtain a test result. Feature
scripts and the evidence audit retain pending/partial status separately from
API acknowledgement and owner observations.
