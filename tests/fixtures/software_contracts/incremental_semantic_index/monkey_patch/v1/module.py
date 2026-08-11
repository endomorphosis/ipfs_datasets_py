class Target:
    def method(self) -> int:
        return 1


Target.method = lambda self: 2
