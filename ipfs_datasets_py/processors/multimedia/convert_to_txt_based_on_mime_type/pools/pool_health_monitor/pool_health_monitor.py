
from pydantic_models.configs import Configs

class PoolHealthMonitor:

    def __init__(self, resources, configs):
        self.configs = configs
        self.resources = resources
        self.pool_id = self.resources.pool_id
        self.pool_name = self.resources.pool_name
        self.pool_size = self.resources.pool_size
        self.pool_current_health = self.resources.pool_current_health
        self.criteria = self.configs.criteria











