from typing import Any, Callable, Optional


from types_ import Configs, Content, Logger


class CsvProcessor:
    """
    Processor for CSV files.
    """

    def __init__(self, 
                 resources: dict[str, Callable] = None, 
                 configs: Configs = None
                 ) -> None:
        """
        Initialize the CSV processor with resources.
        
        Args:
            resources (dict): Dictionary of resources including parsers and services.
        """
        self.configs = configs
        self.resources = resources

        self._logger: Logger = self.resources["logger"]
