# Weight source investigation (#41)

## What the APK establishes

Source: NOTTY Smart Pet 1.1.30, SHA-256
`3b6dc21037f2802e92233ecd9f685e76b03a79afa2d82dd52a5dfcd689a18e6a`.
Addresses refer to local ARM64 Blutter output; decoded files stay ignored.

- `CatsController::getPetList` GETs `/pet/list` at `0xbf67cc`.
  `cats_view.dart` reads the selected row's `today_weight` at `0xc9d8f4`.
- `PetCardController::getAllPetDetail` GETs `/pet/info/{pet_id}`
  (`0xbf9590`, GET `0xbf95ac`); its response callback (`0xbf95f8`, field
  callback `0xbf9690`) assigns recognized fields to observables. Its constructor
  initializes `today_weight` and `yesterday_weight` (`0xd23158`, `0xd23198`).
  Neither the presence of these fields nor their defaults proves a fresh weigh-in.
- Account toilet charts use `/pet/pet_wc_data_statistics` (`0xbf86dc`), with
  `pet_id` and `type` parameters (`0xbf8780`, `0xbf87a4`). The `type` closure
  (`0xbf9474`) reads controller field `0x63`.
- Device/pet charts use `/device/litter_box/pet_data_statistics/{box_id}`
  (`0xbf986c`) with `pet_id` and `type` (`0xbf9914`, `0xbf9938`).
- The chart tab controller has four positions (`0xbf809c`). Its listener assigns
  `index + 1` to the selection (`0xbfac08` → `0xbfac28`), establishing query
  types 1–4. These are selector values, not an invented pagination range.
- Per-box detail uses `/device/litter_box/pet_data_detail/{box_id}`
  (`0xbfa6f0`). No separate timestamped weight-history request was identified in
  these inspected callers. The inspected native pet-card view does not establish
  a weight-history chart. This is not proof that the backend has no such data.

## Fresh live evidence

The expanded probe completed 25 GET reads without failures: both pet profiles,
all four account toilet-chart selections for each account pet, box info/list/
associations, and the selected box's detail/default chart/four chart selections
for each associated pet. Feeder and water endpoints were not called.

Recognized weight fields appeared only in the profiles: `weight`, `today_weight`
and `yesterday_weight`, without a measurement timestamp. Chart responses contain
`duration` and `count`; detail responses contain today's/yesterday's toilet
counts and duration plus profile metadata, without recognized weight fields.
The comparable profile weight/unit/timestamp context was unchanged from the
prior capture. Toilet-event rows inspected in box info had no weight field.

The owner recalls a visit sometime that morning but cannot identify the cat or
time. This is **not** an independently bracketed visit. Neither unchanged values
nor a later poll establishes measurement freshness, reference fallback behavior
or which cat was measured. No independent per-visit weight history is claimed.

The API also supplies an external health-report SPA link. Only the public root
was requested, without its private URL fragment or credentials. The HTTPS root
was unreachable during this investigation, so that application's data requests
remain uninspected. A failed fetch is not evidence that it has no weight history.
Do not publish account health URLs or private fragments in an issue or report.

## Repeatable read-only comparison

`probe_weights.py` now includes all four APK chart selections. Captures retain
`capture_started_at`/`captured_at` and per-source `requested_at`/`received_at`.
These delimit collection intervals; they are **not measurement timestamps**.
Default reports omit names, IDs, weight values and captured timestamp values.
Existing captures remain readable and comparison joins by private stable IDs.

Before the next independently observed normal visit:

```sh
uv run python scripts/probe_weights.py \
  --session-file probe-output/fresh-login-20261017.private.json \
  --capture-raw probe-output/weight-before-next-visit.private.json \
  --output probe-output/weight-before-next-visit.report.json
```

After the visit and phone-app refresh:

```sh
uv run python scripts/probe_weights.py \
  --session-file probe-output/fresh-login-20261017.private.json \
  --compare probe-output/weight-before-next-visit.private.json \
  --capture-raw probe-output/weight-after-next-visit.private.json \
  --output probe-output/weight-after-next-visit.report.json
```

Use new output filenames for each attempt. Record the independently identified
cat, approximate visit start/end and phone-app weight/unit separately and
privately. For a clean before/after window the first capture must finish before
the visit starts and the second must start afterward. A different numeric weight
still needs source/timestamp investigation; an unchanged weight cannot disprove
a measurement. NOTTY's own cat attribution may be wrong and is not corrected by
reassigning API identities in this integration.
