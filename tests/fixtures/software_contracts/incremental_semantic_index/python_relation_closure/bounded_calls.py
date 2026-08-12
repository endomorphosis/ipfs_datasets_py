"""Static-analysis fixture: never import or execute this module."""
import pkg.relations as module_alias

def target():
    return 1

def direct_caller():
    return target()

def module_alias_caller():
    return module_alias.target()

def local_alias_caller():
    import pkg.relations as local_alias
    return local_alias.target()

class Worker:
    def helper(self):
        return 1

    def caller(self):
        return self.helper()

def outer():
    def nested():
        return 1

    return nested()
