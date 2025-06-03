from .stratified_sampler import StratifiedSampler
from ._count_gnis_by_state import count_gnis_by_state
from ._calculate_sample_sizes import calculate_sample_sizes
from ._select_sampled_places import select_sampled_places


def make_stratified_sampler():
    from main import RANDOM_SEED
    resources = {
        'calculate_sample_sizes': calculate_sample_sizes,
        'count_gnis_by_state': count_gnis_by_state,
        'select_sampled_places': select_sampled_places,
    }
    configs = {
        'random_seed': RANDOM_SEED,
    }
    return StratifiedSampler(resources=resources, configs=configs)
