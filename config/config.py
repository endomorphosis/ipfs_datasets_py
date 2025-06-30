from pathlib import Path

try:
    import toml
except ImportError:
    raise ImportError("Please install the 'toml' package to use this module. You can do this by running 'pip install toml'.")

class config():

    def __init__(self, collection=None, meta=None):
        this_dir = Path(__file__).parent
        if meta is not None:
            if "config" in meta:
                self.toml_file = Path(meta["config"])
                self.baseConfig = self.requireConfig(self.toml_file)
        else:
            self.toml_file = Path("./config/config.toml")
            if self.toml_file.exists():
                self.toml_file = self.toml_file.resolve()
            elif (this_dir / self.toml_file).exists():
                self.toml_file = (this_dir / self.toml_file).resolve()
            self.baseConfig = self.requireConfig(self.toml_file)

    def overrideToml(self, base, overrides: dict | str | Path = None) -> dict:
        match overrides:
            case dict():
                for item in overrides.items():
                    key = item[0]
                    value = item[1]
                    match value:
                        case dict():
                            base[key] = self.overrideToml(base[key], value)
                        case _:
                            base[key] = value
            case Path() | str():
                if Path(overrides).exists():
                    with open(overrides) as f:
                        for key, value in toml.load(f).items():
                            base[key] = value
                        return base
            case str():
                raise Exception('file not found: ' + overrides)
            case _:
                raise Exception('invalid override type: ' + str(type(overrides)))
        return base

    def findConfig(self) -> Path | None:
        paths = [
            './config.toml',
            '../config.toml',
            '../config/config.toml',
            './config/config.toml'
        ]
        foundPath = None

        for path in paths:
            this_path = (Path(__file__).parent / Path(path)).resolve()
            if this_path.exists():
                foundPath = this_path

        print("foundPath: ", foundPath)
        return foundPath if foundPath != None else None

    def loadConfig(self, configPath: Path, overrides = None) -> dict:
        if configPath is None and "findConfig" in dir(self):
            configPath = self.findConfig()
        with open(configPath.resolve()) as f:
            config = toml.load(f)
            return config if overrides is None else self.overrideToml(config, overrides)

    def requireConfig(self, opts: dict | str = None) -> dict:
        configPath = None
        this_dir = Path(__file__).parent
        this_config = this_dir / 'config.toml'
    
        if isinstance(opts, (str, Path)) and Path(opts).exists() and opts is not None:
            configPath = Path(opts)
        elif isinstance(opts, dict) and 'config' in opts and Path(opts['config']).exists() and opts['config'] is not None:
            configPath = Path(opts['config'])
        elif opts is None and "findConfig" in dir(self):
            configPath = self.findConfig()

        if not configPath:
            print('this_dir: ')
            print(this_dir)
            print('this_config: ')
            print(this_config)
            print('no config file found')
            print('make sure config.toml is in the working directory')
            print('or specify path using --config')
            exit(1)
        return self.loadConfig(configPath, opts)
