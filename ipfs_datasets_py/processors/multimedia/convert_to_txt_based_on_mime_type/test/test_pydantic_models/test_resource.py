
import pytest
import pytest_asyncio

from pydantic_models.resource.resource import Resource

### Test Resource


# 1. Test instantiation of Resource
resource = Resource()

# 2. Test setting and getting attributes
resource = Resource(
    file_path="test_file.txt",
)






