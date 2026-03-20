# Tests

## Unit (TDD)

1. **`reference_spec.py`** — canonical functions and `ActivationLedgerRef` (behavior described in the module docstring; must align with **`plans/`**).
2. **`inspectio_exercise.domain`** — must match `reference_spec` (currently stubs raise **`NotImplementedError`**).
3. **`tests/unit/test_*.py`** — assert `domain` matches `reference_spec` (and HTTP/fake smoke where applicable).

**Red → green:** implement `src/inspectio_exercise/domain/*.py` until `pytest tests/unit` passes.
