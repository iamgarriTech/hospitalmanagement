"""Number formatting shared by anything that shows a stored decimal to a human."""
from decimal import Decimal, InvalidOperation


def trim_decimal(value):
    """Render a Decimal the way a report prints it.

    Decimal keeps its scale, so a value stored as 12.000 formats as "12.000"
    under both `:g` and `:f` — and a dose of 500 mg prints on a dispensing label
    as "500.000 mg". `normalize()` drops the trailing zeros; `:f` then expands
    the exponent that normalize() introduces for values like 150 (1.5E+2).

    Takes ints, floats and numeric strings as well, because the callers are
    format strings and a field that is nullable in one place is a plain number
    in another. Anything it cannot read comes back as `str(value)` rather than
    raising: this is display code, and a traceback in a drug-safety message is
    worse than an ugly number.
    """
    if value is None or value == "":
        return ""
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return str(value)
    return f"{value.normalize():f}"
