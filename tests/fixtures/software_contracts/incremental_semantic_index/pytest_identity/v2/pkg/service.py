"""Production module under test — signature change."""


def service(value: int, flag: bool = False) -> int:
    return value


def caller() -> int:
    return service(1)
