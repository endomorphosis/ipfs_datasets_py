"""Authored, structurally disjoint development controls for the v2 grammar.

No benchmark source or CVE labels enter these examples. These are capability
controls, not a blind estimate of performance on arbitrary source code.
"""
from __future__ import annotations


def authored_formula_samples_v2() -> list[dict]:
    expressions = ["value", "17", "'safe'", "True", "False", "None", "value + 2", "value - 2",
        "value * 3", "+value", "-value", "not value", "'z' in value", "'z' not in value",
        "value == 9", "value != 9", "value < 9", "value <= 9", "value > 9", "value >= 9",
        "value or other", "value and other", "str(value)", "value.title()", "value.lower()",
        "value.upper()", "value.casefold()", "value.replace('a', 'b')",
        "value if value > other else other", "True if value == other else False",
        "None if value != other else None", "'safe' if value <= other else 'unsafe'",
        "value.lower().upper()", "value + other * 3"]
    train = [f"def control(value, other):\n    return {expression}\n" for expression in expressions]
    train += [
        "def local(value):\n    result = value + 4\n    return result\n",
        "def guard(value):\n    if '\\r' in value:\n        raise ValueError('invalid')\n    return value\n",
        "def choose(value, other):\n    if value < other:\n        return value\n    else:\n        return other\n",
        "def early(value):\n    if value < 0:\n        return -value\n    return value\n",
        "def local_branch(value):\n    if value > 0:\n        result = value + 1\n        return result\n    else:\n        return 0\n",
        "def local_early(value):\n    if value >= 0:\n        result = value - 1\n        return result\n    return 0\n",
        "def branch_bool(value):\n    if value == 0:\n        return True\n    else:\n        return False\n",
        "def branch_none(value):\n    if value == 0:\n        return None\n    else:\n        return None\n",
        "def logic(value, other):\n    return value > 0 and other <= 1\n",
        "def disjunction(value, other):\n    return value != 2 or other == 0\n",
        "def inverted(value):\n    return not (value < 0)\n",
        "def nested(value):\n    if value < 0:\n        return -value\n    else:\n        if value == 0:\n            return 1\n        else:\n            return value\n",
    ]
    validation = [
        "def bounded(left, right):\n    temporary = left + right * 5\n    return temporary if temporary >= 7 else -temporary\n",
        "def clamp(value):\n    if value < -3:\n        return -3\n    if value > 8:\n        return 8\n    return value\n",
        "def nonempty(value, other):\n    return not (value <= 0 or other >= 10)\n",
        "def nested_choice(value, other):\n    return (value if value < 0 else other) if value != other else 5\n",
        "def unicode_name(値):\n    return '安全' if 値 > 3 else '拒否'\n",
        "def condition_local(value):\n    flag = value > 0\n    if flag:\n        result = value * 2\n        return result\n    return -1\n",
    ]
    test = [
        "def range_guard(value, lower, upper):\n    if value < lower or value > upper:\n        return False\n    return value != 0\n",
        "def absolute_delta(left, right):\n    difference = left - right\n    if difference >= 0:\n        return difference * 2\n    else:\n        return -difference * 2\n",
        "def nested_boolean(left, right):\n    return (left < right and left != 0) or (right > 4 and right <= 9)\n",
        "def conditional_none(value):\n    present = value != 0\n    return None if not present else None\n",
        "def nested_result(value):\n    if value != 0:\n        if value > 3:\n            return value + 4\n        return value - 2\n    else:\n        return 7\n",
        "def combine(left, right):\n    first = left * 2\n    second = right + 3\n    return (first - second) if first == second else (second - first)\n",
    ]
    return [{"id": f"v2-authored-{split}-{index:03}", "split": split, "source": source}
        for split, sources in (("train", train), ("validation", validation), ("test", test))
        for index, source in enumerate(sources)]
