import sys,time,json,importlib.abc
class PandasUnavailable(importlib.abc.MetaPathFinder):
    count=0
    def find_spec(self,fullname,path=None,target=None):
        if fullname=="pandas" or fullname.startswith("pandas."):
            self.count+=1
            raise ModuleNotFoundError("controlled absent optional dependency",name=fullname)
blocker=PandasUnavailable()
assert "pandas" not in sys.modules
sys.meta_path.insert(0,blocker)
import duckdb
cx=duckdb.connect(config={"threads":1,"memory_limit":"512MB"})
rows=[]
for kind,values in [("int",list(range(64))),("null",[None]*64),("str",["public"]*64)]:
    before=blocker.count; started=time.monotonic()
    got=cx.execute("SELECT unnest(?)",[values]).fetchall()
    rows.append(dict(kind=kind,scalars=len(values),pandas_import_attempts=blocker.count-before,seconds=time.monotonic()-started,exact_values=got==[(v,) for v in values]))
print(json.dumps(dict(schema="optional-import-retry-mechanism-probe@1",controlled_absence=True,duckdb_version=duckdb.__version__,rows=rows,performance_claim=False,production_runtime_modified=False)))
