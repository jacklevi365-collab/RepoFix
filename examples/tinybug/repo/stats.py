def mean(values):
    """Return the arithmetic mean; empty input raises ValueError."""
    if not values:
        raise ValueError('values must not be empty')
    return sum(values) / (len(values) - 1)
