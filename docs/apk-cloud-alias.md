# Cloud device aliases (#20)

Source: NOTTY Smart Pet 1.1.30, SHA-256
`3b6dc21037f2802e92233ecd9f685e76b03a79afa2d82dd52a5dfcd689a18e6a`.
Addresses refer to local Blutter ARM64 output. APK inputs and decoded code stay
ignored. Synthetic contract fields/IDs are recorded in
`tests/fixtures/apk_cloud_alias.json`.

## Outbound request

`view/tabs/device/device_setting/alias/alias_controller.dart`,
`AliasController::sureAlias` (`0xcc17a8`), inserts only `user_device_id` at
`0xcc18d0` and `alias` at `0xcc18f4`, then POSTs `/device/set_alias` at `0xcc1918`.
It does not send the compatibility `device_id` alias used by some older helpers.

The shared physical-ID closure (`0xcc1b14`) reads the controller's unboxed
`field_23` (`0xcc1b28`) and boxes it as a Dart integer (`0xcc1b2c`). Its initial
value comes from the physical device argument. The shared text closure (`0xc8072c`
in `view/tabs/mine/help_feedback/feedback/feedback_controller.dart`) returns the
text-editing controller's string at `0xc80768`. There is no trimming or truncation
in that captured-text path. The integration requires a positive decimal physical
ID, serializes it as an integer, and sends the exact accepted string. The generic
`set_alias` API entry point delegates to this builder and rejects additional fields
that could override targeting.

## Length and input policy

The save method loads the string length at `0xcc1834`, unboxes it and compares
against **2** at `0xcc183c`. Short names show `名称长度需要在在2-8之间` at
`0xcc1844` (the name length should be 2–8). The inspected save method does not
also compare against 8; the message alone does not establish an enforced server
maximum. The page reuses `LoginInfoNickNamePage::nickNameWidget` (`0xcc16a8`),
whose inspected text-field construction does not establish an additional upper
bound. We deliberately choose the conservative 2–8 range for **new writes**, not
claim that the backend rejects every longer name.

Dart's `String.length` counts UTF-16 code units. Python/HA text bounds count code
points. The API helper validates UTF-16 length explicitly: one non-BMP emoji uses
two units and can satisfy the minimum; five such emoji exceed the eight-unit
maximum. HA's lower display bound is therefore one code point, with the exact
write constraint enforced before HTTP. Blank/control/surrogate text is rejected
as a client input policy; the APK path alone does not establish that filtering.
Existing longer reported names remain visible without truncation, with the HA
display bound accommodating the current value; new writes still use 2–8 units.

## Response, identity and HA naming

The app success callback (`0xcc1964`) reads the server message, waits briefly
and returns the entered alias in a navigation result at `0xcc1a7c`. That UI
behavior is not independent proof that later cloud discovery reflects the change.
The integration instead refreshes the coordinator and displays the reported alias;
it does not optimistically set either the text state or the registry name.
Discovery's explicit `alias` field takes precedence over device-info alias fallback.

The configuration text entity uses physical ID `{user_device_id}_cloud_alias`.
It is available only with current device presence and usable alias metadata. Pets
and other unsupported device kinds do not receive this control. Matching names
are no-ops. API errors surface once without retrying or changing local names.

On successful polling, the text entity updates the integration-provided registry
`name` from the cloud alias. It never writes `name_by_user`, changes identifiers,
recreates entity IDs, or treats a Home Assistant rename as a cloud rename. This
also follows names changed in the official app. The registry lookup is scoped
to the integration's config entry on current HA, with the existing older-HA API
fallback for compatibility.

## Verification boundary

Synthetic tests cover exact payloads, integer physical targeting, type/length
validation, Unicode, unchanged/rejected/unconfirmed writes, longer existing names,
cloud readback, registry overrides and device/entity identity. No live cloud alias
was changed. #20 remains open for owner-observed server readback and restoration
of a chosen device's original name before declaring this production validated.
