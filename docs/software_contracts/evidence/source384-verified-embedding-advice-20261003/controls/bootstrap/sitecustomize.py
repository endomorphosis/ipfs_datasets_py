from pathlib import Path
import hashlib,importlib.abc,importlib.util,sys
ROOT=Path(__file__).resolve().parents[1]/'proposed'
PINS={'ipfs_datasets_py.logic.software_contracts.codebase_source_units_384': 'cad72bdf21e24b947e660f52bba5f1f95983a5f04e82a51425f29fda29198d58', 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_runtime': 'ce80ed6294009e04580051e6eb06a817d74a8a56f04814ad0a698e3d27dd0d41'}
class Loader(importlib.abc.Loader):
    def __init__(self,p,b):self.p,self.b=p,b
    def create_module(self,spec):return None
    def exec_module(self,module):exec(compile(self.b,str(self.p),'exec'),module.__dict__)
class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname not in PINS:return None
        p=ROOT/Path(*fullname.split('.')).with_suffix('.py')
        with p.open('rb') as f:b=f.read(262145)
        if len(b)>262144 or hashlib.sha256(b).hexdigest()!=PINS[fullname]:raise ImportError('candidate source drift')
        return importlib.util.spec_from_file_location(fullname,p,loader=Loader(p,b))
if any(n in sys.modules for n in PINS):raise RuntimeError('late candidate selection')
sys.meta_path.insert(0,Finder())
