# Owned synthetic readiness fixtures

These JSON documents are contracts, not captured device records.

- `initial-plan.json`: all twelve areas/gates/stages NOT_TESTED, no device data.
- `hypothetical-h1.json`: SCHEMA_EXAMPLE with fictional zero hashes and relative
  filenames; demonstrates required categories, never an attestation or actual
  SteamOS compatibility. Its physical status stays NOT_TESTED.
- `invalid-missing-context.json`: H1 lacks active-context reference; reject.
- `invalid-ubuntu-compatibility.json`: attempts SteamOS compatibility from OTHER;
  reject.
- `invalid-interop-skip.json`: attempts XRT import PASS without prerequisites;
  reject.

Run `python tests/test_steamos_readiness.py` with existing development dependencies.
For checklist files run `python scripts/steamos_readiness.py --validate FILE`;
JSON Schema alone does not enforce cross-field/reference rules. The validator
never opens these fictional artifacts. Real evidence stays private outside Git
and uses the existing hardware-evidence format for execution measurements.
