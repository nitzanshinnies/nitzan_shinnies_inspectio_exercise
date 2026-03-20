# Tests

## Unit (TDD)

1. **`reference_spec.py`** — canonical functions and `ActivationLedgerRef` (behavior described in the module docstring; must align with **`plans/`**).
2. **`inspectio_exercise.domain`** — must match `reference_spec` (currently stubs raise **`NotImplementedError`**).
3. **`tests/unit/test_*.py`** — assert `domain` matches `reference_spec` (and HTTP/fake smoke where applicable).

**Red → green:** implement `src/inspectio_exercise/domain/*.py` until `pytest tests/unit` passes.

## Integration (`tests/integration/`)

**Scope:** in-process ASGI checks and stubs-only contract tests per **`plans/TESTS.md` §5** (no Docker required for the passing subset). Full moto/Redis/compose scenarios stay **`@pytest.mark.skip`** until backends exist.

```bash
pytest -m integration
pytest tests/integration
```

**Branch `feature-implement-tests-integration`:** changes should stay under **`tests/integration/`** (and this README) unless a small **`conftest`**/marker tweak is unavoidable.
