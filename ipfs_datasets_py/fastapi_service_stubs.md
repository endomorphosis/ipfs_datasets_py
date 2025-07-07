# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/fastapi_service.py'

Files last updated: 1751667740.2063653

Stub file last updated: 2025-07-07 02:11:01

## AnalysisRequest

```python
class AnalysisRequest(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DatasetLoadRequest

```python
class DatasetLoadRequest(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DatasetProcessRequest

```python
class DatasetProcessRequest(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DatasetSaveRequest

```python
class DatasetSaveRequest(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## EmbeddingGenerationRequest

```python
class EmbeddingGenerationRequest(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## IPFSPinRequest

```python
class IPFSPinRequest(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TokenResponse

```python
class TokenResponse(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## UserCredentials

```python
class UserCredentials(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## VectorIndexRequest

```python
class VectorIndexRequest(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## VectorSearchRequest

```python
class VectorSearchRequest(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## WorkflowRequest

```python
class WorkflowRequest(BaseModel):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## batch_generate_embeddings

```python
@app.post("/embeddings/batch")
async def batch_generate_embeddings(texts: List[str], model: str = "sentence-transformers/all-MiniLM-L6-v2", normalize: bool = True, current_user: Dict[str, Any] = Depends(get_current_user), http_request: Request = None):
    """
    Generate embeddings for multiple texts in batch.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## check_rate_limit

```python
async def check_rate_limit(request: Request, endpoint: str) -> None:
    """
    Check if request exceeds rate limit.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## clear_cache

```python
@app.post("/cache/clear")
async def clear_cache(cache_type: Optional[str] = None, pattern: Optional[str] = None, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Clear cache entries.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## clustering_analysis

```python
@app.post("/analysis/clustering")
async def clustering_analysis(request: AnalysisRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Perform clustering analysis on vectors.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## convert_dataset_format

```python
@app.post("/datasets/convert")
async def convert_dataset_format(dataset_id: str, target_format: str, output_path: Optional[str] = None, options: Optional[Dict[str, Any]] = None, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Convert a dataset to a different format.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## create_access_token

```python
def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create JWT access token.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_vector_index

```python
@app.post("/vectors/create-index")
async def create_vector_index(request: VectorIndexRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Create a vector index for similarity search.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## custom_openapi

```python
def custom_openapi():
    """
    Generate custom OpenAPI schema.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## detailed_health_check

```python
@app.get("/admin/health")
async def detailed_health_check(current_user: Dict[str, Any] = Depends(get_current_user), http_request: Request = None):
    """
    Get detailed health information.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## execute_tool

```python
@app.post("/tools/execute/{tool_name}")
async def execute_tool(tool_name: str, parameters: Dict[str, Any], current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Execute a specific MCP tool.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## execute_workflow

```python
@app.post("/workflows/execute")
async def execute_workflow(request: WorkflowRequest, background_tasks: BackgroundTasks, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Execute a workflow with multiple steps.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## general_exception_handler

```python
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """
    Handle general exceptions.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## generate_audit_report

```python
@app.get("/audit/report")
async def generate_audit_report(report_type: str = "comprehensive", start_time: Optional[str] = None, end_time: Optional[str] = None, output_format: str = "json", current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Generate an audit report.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## generate_embeddings_api

```python
@app.post("/embeddings/generate")
async def generate_embeddings_api(request: EmbeddingGenerationRequest, background_tasks: BackgroundTasks, current_user: Dict[str, Any] = Depends(get_current_user), http_request: Request = None):
    """
    Generate embeddings for text input.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## get_cache_stats

```python
@app.get("/cache/stats")
async def get_cache_stats(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Get cache statistics.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## get_current_user

```python
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """
    Get current authenticated user.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## get_from_ipfs

```python
@app.get("/ipfs/get/{cid}")
async def get_from_ipfs(cid: str, output_path: Optional[str] = None, timeout_seconds: int = 60, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Get content from IPFS by CID.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## get_password_hash

```python
def get_password_hash(password: str) -> str:
    """
    Generate password hash.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_system_stats

```python
@app.get("/admin/stats")
async def get_system_stats(current_user: Dict[str, Any] = Depends(get_current_user), http_request: Request = None):
    """
    Get system statistics.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## get_workflow_status

```python
@app.get("/workflows/status/{task_id}")
async def get_workflow_status(task_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Get the status of a running workflow.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## health_check

```python
@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## http_exception_handler

```python
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Handle HTTP exceptions.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## hybrid_search

```python
@app.post("/search/hybrid")
async def hybrid_search(query: str, collection_name: str, top_k: int = 10, vector_weight: float = 0.7, text_weight: float = 0.3, current_user: Dict[str, Any] = Depends(get_current_user), http_request: Request = None):
    """
    Perform hybrid vector + text search.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## list_available_tools

```python
@app.get("/tools/list")
async def list_available_tools(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    List all available MCP tools.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## load_dataset

```python
@app.post("/datasets/load")
async def load_dataset(request: DatasetLoadRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Load a dataset from various sources.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## log_api_request

```python
async def log_api_request(user_id: str, endpoint: str, input_size: int = None, status: str = "success", error: str = None):
    """
    Log API request for analytics.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## login

```python
@app.post("/auth/login", response_model=TokenResponse)
async def login(credentials: UserCredentials):
    """
    Authenticate user and return JWT token.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## pin_to_ipfs

```python
@app.post("/ipfs/pin")
async def pin_to_ipfs(request: IPFSPinRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Pin content to IPFS.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## process_dataset

```python
@app.post("/datasets/process")
async def process_dataset(request: DatasetProcessRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Process a dataset with a series of operations.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## quality_assessment

```python
@app.post("/analysis/quality")
async def quality_assessment(vectors: List[List[float]], metadata: Optional[Dict[str, Any]] = None, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Assess embedding quality.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## record_audit_event

```python
@app.post("/audit/record")
async def record_audit_event(action: str, resource_id: Optional[str] = None, resource_type: Optional[str] = None, details: Optional[Dict[str, Any]] = None, severity: str = "info", tags: Optional[List[str]] = None, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Record an audit event.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## refresh_token

```python
@app.post("/auth/refresh")
async def refresh_token(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Refresh JWT token.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## run_development_server

```python
def run_development_server():
    """
    Run development server with configuration.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## run_production_server

```python
def run_production_server():
    """
    Run production server with optimized settings.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## run_workflow_background

```python
async def run_workflow_background(task_id: str, workflow_name: str, steps: List[Dict[str, Any]], parameters: Optional[Dict[str, Any]], user_id: str):
    """
    Run workflow in background.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## save_dataset

```python
@app.post("/datasets/save")
async def save_dataset(request: DatasetSaveRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Save a dataset to a destination.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## search_vector_index

```python
@app.post("/vectors/search")
async def search_vector_index(index_id: str, query_vector: List[float], top_k: int = 5, include_metadata: bool = True, include_distances: bool = True, filter_metadata: Optional[Dict[str, Any]] = None, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Search a vector index for similar vectors.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## semantic_search

```python
@app.post("/search/semantic")
async def semantic_search(request: VectorSearchRequest, current_user: Dict[str, Any] = Depends(get_current_user), http_request: Request = None):
    """
    Perform semantic vector search.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## verify_password

```python
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
