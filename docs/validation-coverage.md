# Remaining-issue coverage

See [remaining-validation.md](remaining-validation.md) for corrected live timezone contracts, persistent firmware tracking, weight source/unit fixes and current external acceptance boundaries.

Every in-scope issue has implementation/contract tests and a dedicated live
validation command. Tests do not operate hardware. Command examples and explicit
write payloads are in [app-validation.md](app-validation.md). Emptying is blocked.

| Issue | Current implementation / evidence | Validation command | Remaining acceptance |
| --- | --- | --- | --- |
| #11 | Exact integer lock payload; live flag change/restoration confirmed | `validate_lock.py` | Optional physical-button/app observation on other models |
| #12 | Shared DND builder; live switch change/restoration preserves raw clocks/LED | `validate_dnd.py` | DST/actual schedule firing belongs to #21 |
| #14 | Email-code metadata and migration implemented; authenticated reads work | `validate_login.py` | Fresh code exchange with current metadata; HA expiry/reauth flow |
| #15 | Central APK mappings clean=1, empty=2, level=3 | `validate_cleaning.py` | Clean and level physically confirmed by owner on 17 October; empty testing excluded |
| #16 | 1–15 minute Auto-only select and guarded action | `validate_settings.py` | Owner device reports 0; determine its meaning before a restorable write test |
| #17 | Plan CRUD/toggle fixed for live type 2 and validated with cleanup | `validate_schedules.py` | Actual scheduled physical firing |
| #19 | APK enums and guarded mode writes; all three mode readbacks passed with restoration | `validate_settings.py` | Actual scheduled physical firing and broader model behavior |
| #20 | Alias entity, stable HA IDs/override tests; live rename/restoration passed | `validate_alias.py` | Broader model acceptance only |
| #21 | Catalog/change actions, snapshot drift reporting and DST unit tests | `validate_timezone.py` | Explicit timezone transition and actual firing across date/DST boundaries |
| #22 | Update availability/install and Boolean pending target implemented | `validate_firmware.py`, `monitor_firmware.py` | Future offered update; restart persistence implemented; native JPush is not a verified HA transport; live offer pending |
| #23 | Scoped association actions, preservation tests and a live restored association toggle | `validate_associations.py` | API restoration passed; broader app/HA observations pending |
| #24 | Account category switches/actions; live toggle/restoration passed | `validate_notifications.py` | Broader app/model acceptance only |
| #25 | Scoped text memo list/detail/create/edit implemented | `validate_memos.py` | Selected text memo lifecycle and app date/reminder semantics |
| #26 | Explicit irreversible empty-body statistics-clear action | `validate_statistics.py` | Exact affected counters/history, only when deletion is wanted |
| #41 | Private weight before/after probes and cat-ID validation | `probe_weights.py` | Independently observed visits, measured source/freshness/history; upstream attribution is outside scope |
| #42 | Consolidated live acceptance checklist | `validation_status.py` plus feature scripts | Remaining physical/app observations; no untested criterion is treated as passed |
| #27/#28 | Deferred by owner | None | Feeder/water support excluded |

HA unit tests cover entity lifecycle, account ownership, request contracts,
invalid targets, name overrides, IDs, unknown data and failure recovery. A real HA
installation is still needed to observe device/model-specific UI and expired
session reauthentication. Native push delivery and independently timestamped weigh-in history remain unverified; the integration uses persistent HTTP firmware tracking and clearly labeled cloud daily weight summaries.

`validation_status.py` audits script coverage and private report counts without
publishing names, weights, account IDs, credentials or capture contents. It keeps
API readback, app-field matches and full acceptance distinct.
