



class StratifiedSampler:

    def __init__(self, resources=None, configs=None):
        self.resources = resources
        self.configs = configs

        self.random_seed = configs['random_seed']

        self._count_gnis_by_state = resources['count_gnis_by_state']
        self._calculate_sample_sizes = resources['calculate_sample_sizes'] 
        self._select_sampled_places = resources['select_sampled_places']

    def get_stratified_sample(self, citations, reference_db) -> tuple[list]:
        print("Step 2: Calculating stratified sampling...")

        gnis_counts_by_state: dict[str, int] = self._count_gnis_by_state(citations, reference_db)
        sample_sizes_for_each_state: dict[str, int] = self._calculate_sample_sizes(gnis_counts_by_state)
        gnis_for_sampled_places: dict[int] = self._select_sampled_places(citations, sample_sizes_for_each_state)  
    
        print(f"Selected {len(gnis_for_sampled_places)} places for validation from {len(gnis_counts_by_state)} states")

        return gnis_counts_by_state, gnis_for_sampled_places
