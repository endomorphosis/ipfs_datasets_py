def service() -> None:
    raise KeyError("new")


def recover() -> None:
    try:
        service()
    except ValueError:
        pass
