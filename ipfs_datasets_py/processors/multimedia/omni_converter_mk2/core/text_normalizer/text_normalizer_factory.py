import importlib.util


from ._text_normalizer import TextNormalizer
from ._normalized_content import NormalizedContent
from configs import configs
from logger import logger


def make_text_normalizer():
    """
    Create a text normalizer instance.

    This function initializes and returns a text normalizer that can be used
    to process and normalize text data.
    """
    resources = {
        "logger": logger,
        "normalized_content": NormalizedContent,
        "importlib_util" : importlib.util,
    }
    return TextNormalizer(resources=resources, configs=configs)
