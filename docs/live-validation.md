# Live validation

Start with read-only captures. This checklist is for the device owner; the automated suite does not operate hardware.

1. Install in a test Home Assistant instance, or back up the existing integration first.
2. Request a fresh email verification code and test the email-code flow. Record success/failure without publishing credentials, error bodies, or tokens. Password and Google authentication are unsupported.
3. Run the datapoint probe with a valid token and user ID, saving a local raw capture and value-free report. Confirm discovery distinguishes physical box IDs from pet IDs.
4. Compare app/device values with Home Assistant: online state, mode, child lock, Do Not Disturb times, reminders, pet weight and toileting counts/durations. For DND, record NOTTY app clock times, device `time_zone_iana` if present, HA timezone, API readback clocks, and the result of a **single** confirmed write. Avoid reposting raw DND readback times; live tests showed that a same-state write shifted both boundaries by six hours. Verify readback times match the previous API values when only toggling DND, and check winter/summer behavior separately.
5. Check events in your own time zone, including the date boundary. The current server-time assumption is Asia/Shanghai unless a UTC message field is provided.
6. Observe a normal disconnect/reconnect and an expired session. Check unavailable state, recovery, stored renewed token, and the reauthentication flow.
6a. For timezone issue #21, run the **read-only**
   `uv run scripts/probe_timezones.py --session-file probe-output/session.pr30.private.json`
   to inspect the verified list-of-records schema (string `id`,
   `display_name`, and `offset`). Add `--find Amsterdam` to show
   matching public catalog entries. The live Amsterdam entry is
   `W. Europe Standard Time` / `01:00:00` (standard offset).
   Use the IANA timezone `Europe/Amsterdam` and its DST rules for
   clock conversions; do not infer summer offsets from the catalog.
   Do not publish tokens, unrelated private data or raw capture files.
   Verify the existing
   `time_zone_iana` sensor reports the device IANA zone and keeps the
   distinct Home Assistant and NOTTY API clock-source assumptions. No
   `change_time_zone` write is enabled without independent validation.
7. Only after read behavior is confirmed, verify each command individually using normal device precautions. Record the action, request field/code, resulting physical behavior, and reported state. Do not run a command sweep.
   - For issue #18, action 1 (with configured cycle) has been live-verified to enable/restart a countdown, and action 2 (with configured cycle) disables both reminder types. Action 3 without cycle is rejected. Action 3 with a changed cycle (30 → 29 days) is accepted for **litter renewal** and updated both the configured cycle and remaining days. Do **not** use action 2 to reset a reminder. Keep reset buttons and **trash-bag interval adjustment** disabled until their contracts are tested separately, one explicitly confirmed request at a time, with before/after enabled state, configured days, remaining days, and app verification. Do not send a command sweep.
8. Check pet-weight updates preserve the existing litter-box association. This path has regression tests but still needs production validation.
9. Turn real responses into small synthetic test fixtures with invented IDs, names and timestamps. Keep tokens, account details, images, and raw captures out of Git/issues.

Document the Home Assistant version, device model/firmware, account region, login method and each verified feature before describing a release as production ready.
