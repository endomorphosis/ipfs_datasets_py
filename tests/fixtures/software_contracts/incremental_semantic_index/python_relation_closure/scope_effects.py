"""Static-analysis fixture: never import or execute this module."""
counter = 0

def mutate_global(amount):
    global counter
    counter += amount

def shadowed():
    counter = 10
    counter += 1
    return counter

def outer():
    total = 0

    def mutate_nonlocal(amount):
        nonlocal total
        total += amount
        return total

    return mutate_nonlocal

class Bucket:
    def update(self, amount):
        self.value += amount
        self.items[0] += amount

def destructure(pair):
    left, right = pair
    items = [0]
    items[0] = left
    return left, right
