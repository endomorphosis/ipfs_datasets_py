import os
import tempfile
from tempfile import mkdtemp
from os import path
from os import listdir
from os.path import isfile, join
from os import walk
import toml

class config():
    def __init__(self, collection=None, meta=None):
        this_dir = os.path.dirname(os.path.realpath(__file__))
        if meta is not None:
            if "config" in meta:
                self.toml_file = meta["config"]
                self.baseConfig = self.requireConfig(self.toml_file)
        else:
            self.toml_file = "./config/config.toml"
            if os.path.exists(self.toml_file):
                self.toml_file = os.path.realpath(self.toml_file)
            elif os.path.exists(os.path.join(this_dir, self.toml_file)):
                self.toml_file = os.path.realpath(os.path.join(this_dir, self.toml_file))
            self.baseConfig = self.requireConfig(self.toml_file)

    def overrideToml(self, base, overrides):
        if not isinstance(overrides, dict):
            if isinstance(overrides, str):
                if os.path.exists(overrides):
                    with open(overrides) as f:
                        for key, value in toml.load(f).items():
                            base[key] = value
                        return base
                else:
                    raise Exception('file not found: ' + overrides)
            else:
                raise Exception('invalid override type: ' + str(type(overrides)))
        elif isinstance(overrides, dict):
            for item in overrides.items():
                key = item[0]
                value = item[1]
                if isinstance(value, dict):
                    base[key] = self.overrideToml(base[key], value)
                else:
                    base[key] = value
        else:
            return base
    
    def findConfig(self):
        paths = [
            './config.toml',
            '../config.toml',
            '../config/config.toml',
            './config/config.toml'
        ]
        foundPath = None

        for path in paths:
            thisdir = path.dirname(os.path.realpath(__file__))
            this_path = os.path.realpath(os.path.join(thisdir, path))
            if os.path.exists(this_path):
                foundPath = this_path
        
        print("foundPath: ", foundPath)
        return foundPath if foundPath != None else None

    def loadConfig(self, configPath, overrides = None):
        if configPath is None and "findConfig" in dir(self):
            configPath = self.findConfig()
        with open(configPath) as f:
            config = toml.load(f)
            if overrides is None:
                return config
            else:
                return self.overrideToml(config, overrides)

    def requireConfig(self, opts = None):
        configPath = None
        this_dir = os.path.dirname(os.path.realpath(__file__))
        this_config = os.path.join(this_dir, 'config.toml')
        if type(opts) == str and os.path.exists(opts) and opts is not None:
            configPath = opts
        elif  type(opts) == dict and 'config' in opts and os.path.exists(opts['config']) and opts['config'] is not None:
            configPath = opts['config']
        elif opts is None and "findConfig" in dir(self):
            configPath = self.findConfig(this_config)
        
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
