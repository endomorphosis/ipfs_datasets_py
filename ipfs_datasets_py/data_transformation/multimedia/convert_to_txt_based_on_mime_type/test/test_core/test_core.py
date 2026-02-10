# import pytest
# import asyncio
# import tempfile
# import os
# from pathlib import Path
# from unittest.mock import Mock, patch
# from collections import Counter
# from dataclasses import dataclass
# from typing import Optional


# from converter_system.core.core import Core


# # First, let's create a minimal test implementation of our Resource class
# @dataclass
# class TestResource:
#     thread: int
#     input_path: Path
#     output_path: Path
#     content: Optional[bytes] = None

#     async def load(self) -> bytes:
#         """Load file content"""
#         with open(self.input_path, 'rb') as f:
#             self.content = f.read()
#         return self.content
    
#     def convert(self) -> str:
#         """Convert bytes to plaintext"""
#         if not self.content:
#             raise ValueError("No content loaded")
#         return self.content.decode('utf-8')
    
#     async def save(self) -> Path:
#         """Save converted content"""
#         text = self.convert()
#         with open(self.output_path, 'w') as f:
#             f.write(text)
#         return self.output_path

# @dataclass
# class TestConfigs:
#     con: int = 4

# # Test fixtures
# @pytest.fixture
# def test_files():
#     """Create temporary test files"""
#     with tempfile.TemporaryDirectory() as tmpdir:
#         # Create input files
#         input_dir = Path(tmpdir) / 'input'
#         output_dir = Path(tmpdir) / 'output'
#         input_dir.mkdir()
#         output_dir.mkdir()
        
#         # Create test files with content
#         files = []
#         for i in range(3):
#             in_path = input_dir / f'test_{i}.txt'
#             out_path = output_dir / f'test_{i}.txt'
#             content = f'Test content {i}\nLine 2\nLine 3'.encode('utf-8')
#             with open(in_path, 'wb') as f:
#                 f.write(content)
#             files.append((in_path, out_path, content))
            
#         yield files
#     os.remove(input_dir)
#     os.remove(output_dir)


# @pytest.fixture
# def configs():
#     return TestConfigs(con=2)

# @pytest.fixture
# def core(configs):
#     return Core(configs)

# # Unit Tests
# def test_resource_load(test_files):
#     """Test resource load functionality"""
#     in_path, out_path, content = test_files[0]
#     resource = TestResource(thread=0, input_path=in_path, output_path=out_path)
    
#     # Run load operation
#     result = asyncio.run(resource.load())
#     assert result == content
#     assert resource.content == content


# def test_resource_convert(test_files):
#     """Test resource conversion"""
#     in_path, out_path, content = test_files[0]
#     resource = TestResource(thread=0, input_path=in_path, output_path=out_path)

#     # Load and convert
#     asyncio.run(resource.load())
#     result = resource.convert()
#     assert result == content.decode('utf-8')


# def test_resource_save(test_files):
#     """Test resource save operation"""
#     in_path, out_path, content = test_files[0]
#     resource = TestResource(thread=0, input_path=in_path, output_path=out_path)
    
#     # Process and save
#     asyncio.run(resource.load())
#     saved_path = asyncio.run(resource.save())
    
#     assert saved_path == out_path
#     assert saved_path.exists()
#     with open(saved_path, 'r') as f:
#         saved_content = f.read()
#     assert saved_content == content.decode('utf-8')

# # Integration Tests
# async def test_pipeline_single_resource(core: Core, test_files):
#     """Test full pipeline with a single resource"""
#     in_path, out_path, content = test_files[0]
#     resource = TestResource(thread=0, input_path=in_path, output_path=out_path)
    
#     # Run pipeline
#     result = await core.process_resource(resource)
    
#     # Verify results
#     assert isinstance(result, Counter)
#     assert out_path.exists()
#     with open(out_path, 'r') as f:
#         processed_content = f.read()
#     assert processed_content == content.decode('utf-8')

# async def test_pipeline_multiple_resources(core, test_files):
#     """Test pipeline with multiple resources"""
#     resources = [
#         TestResource(thread=i, input_path=in_path, output_path=out_path)
#         for i, (in_path, out_path, _) in enumerate(test_files)
#     ]
    
#     # Create resource generator
#     def resource_gen():
#         for resource in resources:
#             yield resource
    
#     # Process resources
#     results = []
#     async for result in core.process_stream(resource_gen()):
#         results.append(result)
    
#     # Verify results
#     assert len(results) == len(test_files)
#     for (in_path, out_path, content) in test_files:
#         assert out_path.exists()
#         with open(out_path, 'r') as f:
#             processed_content = f.read()
#         assert processed_content == content.decode('utf-8')

# async def test_pipeline_error_handling(core, test_files):
#     """Test pipeline error handling with failing resources"""
#     in_path, out_path, content = test_files[0]
    
#     # Create a resource that will fail during conversion
#     class FailingResource(TestResource):
#         def convert(self):
#             raise ValueError("Conversion failed")
    
#     resource = FailingResource(thread=0, input_path=in_path, output_path=out_path)
    
#     # Run pipeline and expect it to handle the error
#     with pytest.raises(Exception):
#         await core.process_resource(resource)
    
#     # Verify output file wasn't created
#     assert not out_path.exists()

# async def test_pipeline_concurrent_processing(core, test_files):
#     """Test concurrent processing of resources"""
#     import time
    
#     class SlowResource(TestResource):
#         async def load(self):
#             await asyncio.sleep(0.1)  # Simulate slow IO
#             return await super().load()
    
#     resources = [
#         SlowResource(thread=i, input_path=in_path, output_path=out_path)
#         for i, (in_path, out_path, _) in enumerate(test_files)
#     ]
    
#     # Process resources and measure time
#     start_time = time.time()
#     results = []
#     async for result in core.process_stream(iter(resources)):
#         results.append(result)
#     end_time = time.time()
    
#     # Verify concurrent processing
#     processing_time = end_time - start_time
#     sequential_time = 0.1 * len(resources)  # Expected sequential time
#     assert processing_time < sequential_time  # Should be faster than sequential

# # Run all async tests
# @pytest.mark.asyncio
# async def test_all():
#     """Run all async tests"""
#     pytest.main([__file__])

# if __name__ == '__main__':
#     pytest.main([__file__])




