import itertools
import logging
import random
from pathlib import Path


logger = logging.getLogger(__name__)


def select_sampled_places(citations: list[Path], sample_strategy: dict[str, int], reference_db) -> list[int]:
    """
    Randomly select specific places to validate based on sampling strategy.
    
    Args:
        citations (list[Path]): list of citation parquet files.
        sample_strategy (dict[str, int]): Dictionary mapping state names to sample sizes.
        reference_db (DatabaseConnection): Database connection to MySQL, reference database.

    Returns:
        list[int]: list of sampled place GNIS identifiers.
    """
    RANDOM_SEED = 420 # TODO Import this from a config file or environment variable
    # Extract GNIS IDs from citation filenames
    gnis_set: set[int] = set(int(file.stem.split('_')[0]) for file in citations)

    # Get state information for each GNIS ID
    state_to_gnis: dict[str, list[int]] = {}
    for batch in itertools.batched(gnis_set, 100):
        batch_str = ', '.join(map(str, batch))
        query = f"""
            SELECT gnis, state_name
            FROM locations 
            WHERE gnis IN ({batch_str})
            ORDER BY RAND({RANDOM_SEED})
        """
        # Group GNIS IDs by state
        results = reference_db.sql(query).fetchall()
        for result in results:
            gnis, state = result
            if state not in state_to_gnis:
                state_to_gnis[state] = []
            state_to_gnis[state].append(gnis)

    # Sample from each state according to stratified sample sizes
    sampled_places: list[int]
    sampled_places = [
        gnis
        for state, sample_size in sample_strategy.items()
        if state in state_to_gnis
        for gnis in random.sample(state_to_gnis[state], sample_size)
    ]

    # Remove duplicates and ensure unique GNIS IDs
    unique_gnis: set[int] = set(sampled_places)
    if len(unique_gnis) < len(sampled_places):
        logger.warning("Duplicate GNIS IDs found in sampled places, removing duplicates.")
    sampled_places = list(unique_gnis)
    return sampled_places
