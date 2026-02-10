"""
Text normalizer module for the Omni-Converter.

This module provides the TextNormalizer class for normalizing text content.
"""
from types_ import (
    Callable,
    Configs,
    Content,
    Logger,
    ModuleType,
    NormalizedContent,
    Optional,
    Path
)
from protocols import NormalizerFunction


class TextNormalizer:
    """
    Text normalizer for the Omni-Converter.
    
    Normalizes text from content objects by applying various normalization functions.
    
    Attributes:
        resources (dict[str, Callable]): Dictionary of callable objects and dependencies.
        configs (Configs): Configuration settings containing paths and other config data.

    Properties:
        applied_normalizers (list[str]): List of registered normalizer names.
        normalizers (dict[str, NormalizerFunction]): Dictionary of registered normalizer functions.

    Methods:
        normalize_text: Normalize text content using specified normalizers.
        register_normalizer: Register a new normalizer function.
        register_normalizers_from: Register normalizers from a specified folder.
    """
    def __init__(self, 
                 resources: dict[str, Callable] = None, 
                 configs: Configs = None
                 ):
        """Initialize a text normalizer instance.

        Creates a TextNormalizer that can apply various text normalization functions
        to content objects. The normalizer automatically discovers and registers
        normalization functions from the configured directories during initialization.

        Args:
            resources (dict[str, Callable]): A dictionary containing callable 
            objects and dependencies required by the normalizer, including:
            - 'importlib_util': Module for dynamic imports
            - 'normalized_content': Factory for creating NormalizedContent objects
            - 'logger': Logger instance for operation logging
            Defaults to None.
            configs (Configs): A pydantic model containing configuration 
            Must include paths.NORMALIZER_FUNCTIONS_DIR and paths.PLUGINS_DIR.
            Defaults to None.

        Raises:
            TypeError: If resources is not a dictionary or configs is not provided.
            KeyError: If required keys are missing in the resources dictionary.
            AttributeError: If the required configs do not have the expected attributes.
            RuntimeError: If no normalizers could be loaded from the default or plugins folder.
        """
        self.resources = resources
        self.configs = configs

        self._default_normalizers_folder: Path = self.configs.paths.NORMALIZER_FUNCTIONS_DIR
        self._plugins_folder:             Path = self.configs.paths.PLUGINS_DIR

        self._importlib_util:     ModuleType = self.resources['importlib_util']
        self._normalized_content: NormalizedContent = self.resources["normalized_content"]
        self._logger:             Logger = self.resources["logger"]

        self._logger.isEnabledFor(10)

        self._normalizers: dict[str, NormalizerFunction] = {}

        self.register_normalizers_from(self._default_normalizers_folder)
        self.register_normalizers_from(self._plugins_folder)
        if not self._normalizers:
            raise RuntimeError("No normalizers could be loaded from the default or plugins folder.")

    def register_normalizers_from(self, folder: Path) -> None:
        """
        Registers all normalizer functions from Python modules in the specified folder.

        This method dynamically loads Python modules from the given folder and registers
        any functions that are instances of `NormalizerFunction`. It skips certain files
        such as `__init__.py`, private modules (those starting with an underscore), or
        modules that do not contain the word 'normalizer' in their name.

        Args:
            folder (Path): The folder containing Python files to scan for normalizer functions.

        Raises:
            RuntimeError: Any unexpected error occurs while loading a module.

        Logging:
            - Logs the start and completion of the registration process.
            - Logs debug information for each module being loaded.
            - Logs errors for failed imports or registration attempts.
            - Logs warnings for individual normalizer registration failures.
        """
        self._logger.info(f"Registering normalizers from folder: {folder}")
        count = 0
        if folder is None or not folder.exists() or not folder.is_dir():
            self._logger.error(f"Folder '{folder}' does not exist or is None. Skipping registration.")
            return

        for file in folder.rglob('*.py'):
            if file.is_file():
                # Skip the __init__.py file, private modules, or modules that do not contain 'normalizer' in their name
                if file.name == '__init__.py' or file.name.startswith('_') or 'normalize' not in file.stem.lower():
                    continue

                self._logger.debug(f"Loading normalizer module from {file}")

                # Import the module dynamically
                module = None
                try:
                    spec = self._importlib_util.spec_from_file_location(file.stem, file.resolve())
                    module = self._importlib_util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                except Exception as e:
                    self._logger.error(f"Failed to import module from {file}: {e}\nSkipping this file.")
                    continue

                if module is None:
                    self._logger.error(f"Module from {file} could not be loaded. Skipping this file.")
                    continue

                # Register all normalizers in the module
                for name, normalizer in module.__dict__.items():
                    if isinstance(normalizer, NormalizerFunction):
                        try:
                            self.register_normalizer(name, normalizer)
                            count += 1
                        except Exception as e:
                            self._logger.warning(f"Failed to register normalizer '{name}': {e}")
                    else:
                        self._logger.debug(f"Normalizer '{name}' in module {file} does not implement NormalizerFunction protocol. Skipping.")

        self._logger.info(f"Registered {count} normalizers from folder: {folder}")

    def normalize_text(self, 
                       content: 'Content', 
                       normalizers: Optional[list[str]] = None, 
                       skip: bool = False
                       ) -> 'NormalizedContent':
        """Normalize text content using specified or all available normalizer functions.
        
        This method processes the text content from a Content object by applying a sequence
        of normalization functions. Each normalizer transforms the text in a specific way,
        such as cleaning whitespace, standardizing line endings, or normalizing Unicode
        characters. The normalizers are applied sequentially, with each one operating on
        the output of the previous normalizer.

        Args:
            content (Content): The content object containing the text to be normalized.
            normalizers (Optional[list[str]]): A list of normalizer function names to apply in the specified order. 
                If None or not provided, all registered normalizers will be applied.
                Unknown normalizer names will be skipped with a warning logged.
            skip (bool): If True, skips the normalization process entirely.
                This is meant to allow for conditional skipping of normalization
                based on external conditions or configurations. Defaults to False.

        Returns:
            NormalizedContent: A specialized content object that wraps the original content
                     with additional metadata about which normalizers were successfully
                     applied during the normalization process.

        Raises:
            No exceptions are raised directly, but individual normalizer failures are logged
            as errors and those normalizers are skipped to allow processing to continue.

        Note:
            - The original content object is modified in-place with the normalized text
            - Failed normalizers are logged but do not stop the overall process
            - The order of normalizers matters as they are applied sequentially
        """
        normalized_text = None
        applied_normalizers = []

        if skip:
            self._logger.info(f"Skipping normalization for '{content.source_path}'.")
            return self._normalized_content(
                content=content,
                normalized_by=[]
            )
        self._logger.debug(f"Normalizing text from {content.source_path}", {'format': content.source_format})

        # If no normalizers are specified, use all of them
        normalizers = list(self._normalizers.keys()) if normalizers is None else normalizers

        # Check for unknown normalizers
        unknown_normalizers = [n for n in normalizers if n not in self._normalizers]
        if unknown_normalizers:
            self._logger.warning(f"Unknown normalizers specified: '{unknown_normalizers}'. They will be skipped.")

        # Apply each normalizer in sequence
        normalized_text = content.text
        for name in normalizers:
            if name not in self._normalizers:
                continue  # Skip unknown normalizers
            try:
                print(f"Applying normalizer '{name}' to content from {content.source_path}")
                normalized_text = self._normalizers[name](normalized_text)
            except Exception as e:
                self._logger.error(f"Error applying normalizer '{name}': {e}. Skipping.")
            else:
                applied_normalizers.append(name)
                self._logger.debug(f"Applied normalizer: {name}")

        # if normalized_text == content.text:
        #     self._logger.warning(f"No changes made to content from {content.source_path} after applying normalizers.")

        content.text = normalized_text if normalized_text is not None else content.text

        # Create normalized content
        return self._normalized_content(
            content=content,
            normalized_by=applied_normalizers
        )

    def register_normalizer(self, name: str, normalizer: NormalizerFunction) -> None:
        """Register a normalizer function with the text normalizer.
        
        This method adds a new normalizer function to the internal registry, allowing it
        to be used during text normalization operations. The normalizer must conform to
        the NormalizerFunction protocol, which requires it to accept a single string
        argument and return a normalized string. If a normalizer with the same name already exists, 
        it will be overwritten and a warning will be logged.
        
        Args:
            name (str): A unique identifier for the normalizer function. This name will
                   be used to reference the normalizer in normalization operations.
            normalizer (NormalizerFunction): A callable that implements the NormalizerFunction
                           protocol. Must accept a string input and return
                           a normalized string output.

        Logs:
            Warning: Logs a warning if the normalizer doesn't implement NormalizerFunction
                protocol or if a normalizer with the same name already exists.
        """
        if not callable(normalizer) or not hasattr(normalizer, '__annotations__'):
            self._logger.warning(f"Normalizer '{name}' must be a class or function whose only argument is a string and returns a string. Skipping.")
            return

        if name in self._normalizers:
            self._logger.warning(f"Normalizer '{name}' already exists. Overwriting it.")

        self._normalizers[name] = normalizer
        self._logger.info(f"Registered normalizer function '{name}'")

    @property
    def normalizers(self) -> dict[str, NormalizerFunction]:
        """Get the dictionary of registered normalizers.
        
        Returns:
            dict: A dictionary where keys are normalizer names and values are the corresponding
                  normalizer functions.
        """
        return self._normalizers.copy()

    @property
    def applied_normalizers(self) -> list[str]:
        """Get the names of all registered normalizers.
        
        Returns:
            list of normalizer names.
        """
        return list(self._normalizers.keys())
