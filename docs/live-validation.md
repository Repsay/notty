# Live validation

Start with read-only captures. This checklist is for the device owner; the automated suite does not operate hardware.

1. Install in a test Home Assistant instance, or back up the existing integration first.
2. Try email/password authentication. Record success/failure without publishing credentials, error bodies, or tokens. If necessary try the email-code flow.
3. Run the datapoint probe with a valid token and user ID, saving a local raw capture and value-free report. Confirm discovery distinguishes physical box IDs from pet IDs.
4. Compare app/device values with Home Assistant: online state, mode, child lock, Do Not Disturb times, reminders, pet weight and toileting counts/durations.
5. Check events in your own time zone, including the date boundary. The current server-time assumption is Asia/Shanghai unless a UTC message field is provided.
6. Observe a normal disconnect/reconnect and an expired session. Check unavailable state, recovery, stored renewed token, and the reauthentication flow.
7. Only after read behavior is confirmed, verify each command individually using normal device precautions. Record the action, request field/code, resulting physical behavior, and reported state. Do not run a command sweep.
   - For issue #18, read each reminder's enabled state, configured cycle and remaining-days countdown before any change. Disable one reminder, confirm readback and that its cycle was preserved, then re-enable and confirm the cycle. Reset its countdown separately and observe the reported result. Repeat with the other reminder. Check what a reset does when disabled, without assuming it automatically enables or restarts. Record any mismatches; do not send bulk setting writes.
8. Check pet-weight updates preserve the existing litter-box association. This path has regression tests but still needs production validation.
9. Turn real responses into small synthetic test fixtures with invented IDs, names and timestamps. Keep tokens, account details, images, and raw captures out of Git/issues.

Document the Home Assistant version, device model/firmware, account region, login method and each verified feature before describing a release as production ready.
