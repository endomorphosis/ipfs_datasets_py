def target(value: int) -> int:
    return value + 1


def caller() -> int:
    return target(1)
