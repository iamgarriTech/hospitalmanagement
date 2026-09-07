"""Number formatting shared by anything that shows a stored decimal to a human."""


def trim_decimal(value):
    """Render a Decimal the way a report prints it.

    Decimal keeps its scale, so a value stored as 12.000 formats as "12.000" under both
    :g and :f. normalize() drops the trailing zeros; :f then expands the exponent that
    normalize() introduces for values like 150 (1.5E+2).
    """
    if value is None:
        return ""
    return f"{value.normalize():f}"
