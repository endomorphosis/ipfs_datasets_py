"""Static-analysis fixture: never import or execute this module."""
def first():
    pass

def second():
    pass

def guarded():
    try:
        with first() as left, second() as right:
            return left, right
    except (ValueError, TypeError):
        return None
