# Pet, account and maintenance request evidence

Source: NOTTY Smart Pet 1.1.30+76, SHA-256
`3b6dc21037f2802e92233ecd9f685e76b03a79afa2d82dd52a5dfcd689a18e6a`.
Addresses below refer to local Blutter ARM64 disassembly. The APK, decoded
sources, account captures and session credentials remain ignored.

| Feature | Caller / address | Contract |
| --- | --- | --- |
| Reminder Reset | `SettingController`, Reset label closure `0xcccb30`, action insertion `0xcccc68` | Label selection produces integer action 3 (Dart tagged 6); configured cycle is retained. Disable is action 2. |
| Screen language | `SettingController::setLanguage`, `0xcd32a0`–`0xcd33b0`, field `0xcd3430`, POST `0xcd3454` | `/device/litter_box/set_language`, language 0 Simplified Chinese, 1 English, 2 Traditional Chinese, 3 Icons |
| Associated pets | GET URL `0xc098f4`, request `0xc09910` | `/device/get_associated_pets/{physicalID}` |
| Association write | fields `0xcc3db4`, `0xcc3dd8`, `0xcc3dfc`, POST `0xcc3e20` | `/device/associate_pet`: integer pet_id, Boolean associate, integer user_device_id. Closure `0xcc41a4` toggles a captured Boolean. |
| Notification categories | `MessageSettingController::getMessageList`, litter mapping `0xc0a314` | GET `/message/get_type_block_stats_list?message_group_id=3` for litter product type 2 |
| Notification write | fields `0xcc7cac`, `0xcc7cd0`, POST `0xcc7cf4`; Boolean closure `0xc953f4` | `/message/block_type`: Boolean block, message_type_id; no physical ID. Account/category scope. |
| Delete statistics | `SettingController::cleanStatistics`, integer ID `0xcc9bc8`, URL `0xcc9c08`, empty map `0xcc9c28`, POST `0xcc9c3c` | `/device/clear_statistics/{physicalID}` with empty object body. App warns deletion is irreversible. Exact affected history remains unverified. |
| Pet profile | `AddCatsController`, GET `0xbf3ec4`/`0xbf3ee0` | `/pet/info/{petID}` |
| Breed catalog | GET `0xbf3ccc`/`0xbf3cd8` | `/pet/breeds` |
| Pet save | `enterNotty`, copied fields `0xc8af68`, weight unit `0xc8aecc`, POST `0xc8accc` | `/pet/save`, copies profile fields, includes weight_unit. App rejects non-owners (`0xc8bbdc`). |
| Binding list on save | `0xbf41e8`, `0xbf4228`, `0xbf427c` | Comma-separated user_device_ids. Preserve only devices marked is_bind; unbound candidates must remain unbound. |
| Pet sex | `0xc8d238`–`0xc8d248` | Male 1, female 2; neutered state is nullable Boolean (`0xd20f50`). Birthday is YYYY-MM-DD. |
| Pet name | `CatsNameController`, `0xaff688` | App guidance 2–10 characters; integration bounds Dart UTF-16 units conservatively. |
| Memo detail | `0xbf7c00`/`0xbf7c1c` | GET `/pet/memo_detail/{memoID}`; integration checks fresh selected-pet memo membership first. |
| Memo save | `addOrUpdateMemo`, paths `0xca7078`/`0xca7084`, pet_id `0xca7108`, POST `0xca715c` | memo_id 0 creates via `/pet/add_memo`; existing ID edits via `/pet/edit_memo`. Text fields title, content, date; Boolean remind/expired retained. Date is raw YYYY-MM-DD HH:MM, without inferred timezone. |

Standalone `setLed` (`0xcc4f54`) selects water `/set_led` at `0xcc5090`
or feeder at `0xcc50a4`, otherwise an empty path. It does not establish a
standalone litter-box LED setter. Feeders and water remain outside this work.

Profile writes fetch fresh account membership, ownership and binding data,
serialize per-pet mutations, preserve weight/unit/image metadata, and refresh
readback without optimistic state. Supported changes are name, birthday, sex,
neutered state and catalog-selected breed. Association writes target exactly
one pet and one physical litter box. Memo attachments and pet creation/deletion
are not implemented.

Read-only production checks returned 95 breeds (`breed_id`, `breed_name`,
`letter`), five litter notification categories (group 3; IDs 8, 9, 10, 11, 22;
Boolean `blocked`), and two owned pet profiles with weight_unit 1 and explicit
`pet_devices[].is_bind` states. Both memo lists were empty. These checks validate
read schemas, not write acceptance. No profile, association, notification, memo,
mode, statistics or firmware write was performed for this feature batch.

Synthetic contracts live in `tests/test_pet_features.py` and
`tests/test_device_features.py`; native HA behavior is exercised in
`tests/test_feature_ui.py`. Their invented IDs, names, versions and text do not
contain private captures. Firmware evidence is documented separately in
[apk-firmware.md](apk-firmware.md).
