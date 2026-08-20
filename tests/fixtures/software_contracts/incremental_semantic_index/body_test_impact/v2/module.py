def target(value: int) -> int:
    return value + 2


def caller() -> int:
    return target(1)
