# Development history and evidence

The user supplied a summary of two earlier ChatGPT development conversations on 16 October 2026. The original transcripts were not available to this checkout; this is a summary of the supplied account, not an independent verification of those chats.

## 25 July 2026

Initial investigation of the Android APK identified `https://api.nottycat.com`, account authentication, device discovery, litter-box commands/settings, pet records and usage/weight statistics. An experimental v0.2.0 Home Assistant custom integration followed. Authentication payloads and commands were inferred, and production compatibility was not fully established.

## 22 August 2026

Work focused on sensor classification: time strings must not become numeric durations, weight-unit enums must not become weight measurements, and cleaning schedules must not become measurements. The proposed solution used explicit metadata allowlists rather than broad name-based type inference. The conversation summary reported validation, but supplied no live response fixtures or independently reproducible results.

## 16 October 2026

The provided files were in a new local Git repository with no commits or remotes, a blank README, and a placeholder Python CLI. The API, coordinator and seven platforms already existed. This conversion places them under `custom_components/notty`, adds HACS metadata, original brand icons, developer probes, value-free diagnostics, regression tests and GitHub validation workflows. It also guards against recursive authentication retries, adds reauthentication, and persists renewed access tokens.

The initial prototype stored refresh tokens without implementing their exchange and attempted speculative password-based recovery. The authentication follow-up removes those password/Firebase attempts: existing valid access tokens survive migration, obsolete credentials are removed, and expired sessions need a fresh email code. Claims of automatic refresh-token renewal in earlier summaries should therefore not be treated as verified functionality.

Live authentication, response semantics, server time-zone assumptions, hardware command codes, and device compatibility remain unverified in this development session.
