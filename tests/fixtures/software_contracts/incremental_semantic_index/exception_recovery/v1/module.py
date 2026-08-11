def service() -> None:
    raise ValueError("old")


def recover() -> None:
    try:
        service()
    except ValueError:
        pass
