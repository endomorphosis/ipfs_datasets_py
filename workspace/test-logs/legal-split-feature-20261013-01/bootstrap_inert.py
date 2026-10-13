"""Load explicitly scoped code without top-level plugin initialization or ML backends."""
from pathlib import Path
import importlib.abc,sys,os
from types import ModuleType
ROOT=Path(__file__).resolve().parent/'datasets'
PACKAGES=('ipfs_datasets_py','ipfs_datasets_py.logic','ipfs_datasets_py.logic.legal_ir','ipfs_datasets_py.logic.autoformal','ipfs_datasets_py.logic.CEC','ipfs_datasets_py.logic.CEC.native','ipfs_datasets_py.logic.formalization','ipfs_datasets_py.logic.formalization.autoencoder','ipfs_datasets_py.optimizers','ipfs_datasets_py.optimizers.logic_theorem_optimizer','ipfs_datasets_py.utils')
class NoModels(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'torch','transformers','sentence_transformers','numpy'}:raise AssertionError('ML/numerical backend prohibited: '+fullname)
  return None
def install():
 sys.path.insert(0,str(ROOT));sys.meta_path.insert(0,NoModels());os.environ['IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI']='0'
 for name in PACKAGES:
  module=ModuleType(name);module.__path__=[str(ROOT.joinpath(*name.split('.')))];module.__file__=str(ROOT.joinpath(*name.split('.'),'__init__.py'));sys.modules[name]=module
