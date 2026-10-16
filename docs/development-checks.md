# Development checks

Run the same commands locally and in CI:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest --cov=custom_components.notty --cov=scripts --cov-report=term-missing
```

Ruff includes `custom_components/`, `scripts/` and `tests/`, with the existing
`ALL` rule selection. Mypy includes the integration and `scripts/`, retaining the
existing test exclusion. The gitignored `apk/` workspace is excluded from both.
Strict mypy options, including explicit/dynamic `Any` restrictions, remain enabled.

The HTTP boundary uses a recursive JSON value type. Device blocks and config-entry
runtime data have explicit types. Casts describe framework, JSON-decoder and CLI
boundaries; response parsers narrow their values before accessing rows or fields.
The schema adapter uses Probatio on newer Home Assistant versions and falls back
to Voluptuous on older versions. CI exercises the locked development Home Assistant version and the declared minimum 2026.3.0. The minimum job uses the nearest historical test plugin (0.13.317, normally pinned to 2026.3.1) with an explicit HA 2026.3.0 override. Registry linking uses the version-supported parent-device field and lookup API.

## Narrow exceptions

- Home Assistant requires coroutine entry points even when a platform's setup is
  synchronous. Those functions alone have local `RUF029` exceptions.
- The update installation callback defines `backup` as a positional Boolean; only that framework signature has a Boolean-argument lint exception.
- Home Assistant requires the platform filenames `select.py` and `time.py`. Those
  two files alone have `A005` exceptions.
- `CONF_REFRESH_TOKEN` is a schema key, not a credential. Its declaration alone has
  an `S105` exception.
- The custom-integration fixture must run before the Home Assistant test plugin's
  timer tracking starts. Only `tests/conftest.py` permits an autouse fixture.
- Home Assistant's `ConfigFlowResult` includes framework-owned `Any` fields.
  Only `config_flow.py` relaxes `disallow_any_expr`; its strict signatures,
  explicit-`Any` prohibition and other strict checks remain active.

There are no blanket ignores for scripts, tests, missing annotations, complexity,
private access, credentials or JSON payloads.
