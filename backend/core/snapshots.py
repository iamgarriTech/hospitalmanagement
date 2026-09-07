from django.forms.models import model_to_dict


def snapshot(instance, fields=None):
    """JSON-safe field snapshot for audit before/after values."""
    data = model_to_dict(instance, fields=fields)
    return {key: (value if isinstance(value, (int, float, bool, type(None))) else str(value))
            for key, value in data.items()}
