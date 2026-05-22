"""Shared test fixtures and utilities.

This conftest.py provides schema consistency checking utilities that validate
all _Test* SQLite-compatible models stay in sync with their corresponding
production SQLAlchemy models.  When a production model gains a new column,
the schema sync check will fail in CI until every _Test* variant is updated.
"""

from sqlalchemy import inspect


def get_model_columns(model_class: type) -> set[str]:
    """Return the set of column names for a SQLAlchemy model class.

    Uses SQLAlchemy's runtime inspection to extract mapper column attributes.
    This works for both production models (backed by PostgreSQL types) and
    lightweight test models (backed by SQLite-compatible types).
    """
    mapper = inspect(model_class)
    return {c.key for c in mapper.column_attrs}


def assert_models_synced(
    test_model: type,
    prod_model: type,
    *,
    test_model_label: str | None = None,
    prod_model_label: str | None = None,
) -> None:
    """Assert that a _Test* model's columns are a superset of the production model's columns.

    The check validates that every column present in the production model also
    exists in the test model.  This catches cases where a new column is added
    to the production model but the test model is not updated accordingly.

    It also validates that every column in the test model exists in the
    production model, catching stale / renamed columns in test models.

    Args:
        test_model: The _Test* SQLite-compatible model class.
        prod_model: The production SQLAlchemy model class.
        test_model_label: Optional display name for the test model in error messages.
        prod_model_label: Optional display name for the production model in error messages.

    Raises:
        AssertionError: With a detailed diff report if columns are out of sync.
    """
    test_label = test_model_label or test_model.__name__
    prod_label = prod_model_label or prod_model.__name__

    test_cols = get_model_columns(test_model)
    prod_cols = get_model_columns(prod_model)

    # Check for columns in production but missing from test model
    missing_in_test = prod_cols - test_cols
    # Check for columns in test model but missing from production (stale)
    extra_in_test = test_cols - prod_cols

    if not missing_in_test and not extra_in_test:
        return  # All good

    parts: list[str] = [f"Schema mismatch between {test_label} and {prod_label}:"]
    if missing_in_test:
        parts.append(f"  Production has {sorted(missing_in_test)} but {test_label} is missing them")
    if extra_in_test:
        parts.append(f"  {test_label} has {sorted(extra_in_test)} but production {prod_label} does not")
    parts.append(f"  Production columns: {sorted(prod_cols)}")
    parts.append(f"  Test columns:       {sorted(test_cols)}")

    raise AssertionError("\n".join(parts))
