# From: https://platform.openai.com/docs/pricing
# As of: 4-6-2025
# From: https://www.anthropic.com/pricing#api
# As of: 6-9-2025
# TODO Find a way to automate this update process. This will quickly become outdated.
MODEL_USAGE_COSTS_USD_PER_MILLION_TOKENS = {
    "openai": {
        "gpt-4o": {
            "input": 2.50,
            "output": 10.00
        },
        "gpt-4.5-preview": {
            "input": 75.00,
            "output": 150.00
        },
        "gpt-4-turbo": {
            "input": 10.00,
            "output": 30.00
        },
        "gpt-4": {
            "input": 30.00,
            "output": 60.00
        },
        "gpt-4-32k": {
            "input": 60.00,
            "output": 120.00
        },
        "gpt-3.5-turbo": {
            "input": 0.50,
            "output": 1.50
        },
        "gpt-3.5-turbo-instruct": {
            "input": 1.50,
            "output": 2.00
        },
        "gpt-3.5-turbo-16k-0613": {
            "input": 3.00,
            "output": 4.00
        },
        "gpt-4o-mini": {
            "input": 0.15,
            "output": 0.60
        },
        "o1": {
            "input": 15.00,
            "output": 60.00
        },
        "o1-pro": {
            "input": 150.00,
            "output": 600.00
        },
        "o1-mini": {
            "input": 1.10,
            "output": 4.40
        },
        "o3-mini": {
            "input": 1.10,
            "output": 4.40
        },
        "chatgpt-4o-latest": {
            "input": 5.00,
            "output": 15.00
        },
        "text-embedding-3-small": {
            "input": 0.02,
            "output": None
        },
        "text-embedding-3-large": {
            "input": 0.13,
            "output": None
        },
        "text-embedding-ada-002": {
            "input": 0.10,
            "output": None
        },
        "davinci-002": {
            "input": 2.00,
            "output": 2.00
        },
        "babbage-002": {
            "input": 0.40,
            "output": 0.40
        }
    },
    "anthropic": {
        "claude-4-opus": {
            "input": 15.00,
            "output": 75.00
        },
        "claude-4-sonnet": {
            "input": 3.00,
            "output": 15.00
        },
        "claude-3-5-haiku": {
            "input": 0.80,
            "output": 4.00
        },
    }
}