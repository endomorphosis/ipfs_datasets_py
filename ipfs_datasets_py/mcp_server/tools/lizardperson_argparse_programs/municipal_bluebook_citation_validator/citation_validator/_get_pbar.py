
from types_ import Container, ProgressBar

def get_pbar(container: Container, desc: str = "Processing...", unit: str = "item") -> ProgressBar:
    from dependencies import dependencies
    return dependencies.tqdm.tqdm(total=len(container), desc=desc, unit=unit)
