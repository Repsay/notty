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
   distinct Home Assistant and NOTTY API clock-source assumptions.
   Add `--device-id 52963` to the read-only probe to compare only
   timezone fields from the account's device listing and litter-box info.
   The owner's 2026-10-16 readback confirmed
   `time_zone_iana: Europe/Amsterdam` in **both** responses; the
   catalog uses `W. Europe Standard Time`. The device's current
   zone therefore needs no Windows-to-IANA conversion for runtime
   DND reads/writes. The setter is now traced: the Windows catalog ID is
   sent under `time_zone_iana`, with an integer physical ID. Use
   `notty.device_time_zone` with `operation: list` first. An explicitly
   chosen `operation: change` also requires `catalog_id` and
   `confirm_schedule_change: true`. Inspect the returned before/after
   DND and plan snapshots and verify the app timezone and actual firing
   times across DST/date boundaries. No timezone change has been live-tested.
7. Only after read behavior is confirmed, verify each command individually using normal device precautions. Record the action, request field/code, resulting physical behavior, and reported state. Do not run a command sweep.
   - For issue #18, action 1 (with configured cycle) has been live-verified to enable/restart a countdown, and action 2 (with configured cycle) disables both reminder types. Action 3 without cycle is rejected. Action 3 with a changed cycle (30 → 29 days) is accepted for **litter renewal** and updated both the configured cycle and remaining days. Do **not** use action 2 to reset a reminder. Reset buttons and **trash-bag interval adjustment** now use the separately traced action-3 APK contract. Validate them separately, one owner-selected request at a time, with before/after enabled state, configured days, remaining days, and app verification. Do not send a command sweep.
8. Check pet-weight updates preserve the existing litter-box association. This path has regression tests but still needs production validation.
9. Turn real responses into small synthetic test fixtures with invented IDs, names and timestamps. Keep tokens, account details, images, and raw captures out of Git/issues.

Document the Home Assistant version, device model/firmware, account region, login method and each verified feature before describing a release as production ready.

Cloud name (#20): use one physical litter box and a short test name. Compare NOTTY app and refreshed HA cloud-name readback, then restore the original name. Check the HA user display-name override and all entity IDs remain unchanged. Do not treat HTTP success without cloud readback as a confirmed rename. No live rename was performed during implementation.


Firmware availability (#22): compare the update entity's installed/offered versions and release summary against the official app. Observe an explicit empty target versus an unavailable endpoint. If an update is performed in the official app, check that later polling reports the newly installed version. An explicit HA install now revalidates the offered task and confirms it once. Verify acknowledgement, failure/offline recovery and final installed-version readback during an owner-selected update. Only this HA session's requested target is tracked; no measured percentage or realtime subscription is implemented. Record model/firmware evidence before claiming support.

For #15, use the APK-backed mapping clean=1, empty=2, level=3; the old clean=0 and sterilize=3 labels were incorrect. Validate each physical effect separately with the owner present. No stop/pause or litter-box sterilize command has been established by the inspected callers. For #19, compare Scheduled=2 and Soft stool=3 against app readback; mode changes now require fresh matching device identity/current mode, and Scheduled requires a fresh enabled plan. Verify mode readback and actual scheduling behavior separately.

## Pet and account features

Read-only development checks found 95 breeds, two owner profiles and five litter-box notification categories (group 3); pet memo lists were empty. New writes remain unverified live.

- Edit one existing pet field and verify app/API readback; restore it. Check weight/unit, image, all bound devices and all unbound candidates remain unchanged, and HA entity IDs/user display names are retained.
- Associate/disassociate one owner-selected pet with one physical litter box; compare both association and profile readback before/after, then restore it.
- List account notification categories; toggle only an owner-selected category and verify the official app preference, then restore it. This is account scope.
- Create one owner-selected test memo, read its detail and edit it; verify date/reminder semantics in the app. No attachment or delete support is implemented.
- Statistics clearing permanently deletes data. Validate it only when the owner explicitly wants that device's history removed; record which counters/history actually change. An acknowledgement alone does not establish the affected scope.
