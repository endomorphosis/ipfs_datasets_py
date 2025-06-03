# Step 2: Smart Sampling Functions
import functools
import itertools
from pathlib import Path

def count_gnis_by_state(citations: list[Path], reference_db) -> dict[str, int]:
    """
    Count how many GNIS exist in each state from filenames.
    
    Args:
        citations (list[Path]): list of citation parquet files.
        reference_db (DatabaseConnection): Database connection to MySQL, reference database.
        mysql_configs (dict[str, Any]): MySQL connection settings.
    
    Returns:
        dict[str, int]: dictionary mapping state names to jurisdiction counts.
    """
    gnis_set: set[int] = set(int(file.stem.split('_')[0]) for file in citations)

    states = []
    for batch in itertools.batched(gnis_set, 100):
        # Use a batch size to avoid SQL query length limits
        batch_str = ', '.join(map(str, batch))
        query = f"""
            SELECT state_name, COUNT(state_name) AS counts
            FROM locations 
            WHERE gnis IN ({batch_str}) 
            GROUP BY state;
        """
        # Get the results as a list of dictionaries
        result: list[dict[str, int]] = reference_db.sql(query).fetchdf().to_records('records')
        states.extend(result)

    # Reduce the list of dictionaries to one dictionary with counts
    gnis_counts_by_state = functools.reduce(
        lambda acc, item: {
            **acc, item['state_name']: acc.get(item['state_name'], 0) + item['counts']
        }, states, {}
    )
    return gnis_counts_by_state
