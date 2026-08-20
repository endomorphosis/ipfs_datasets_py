"""Production module under test."""


def service(value: int) -> int:
    return value


def caller() -> int:
    return service(1)
