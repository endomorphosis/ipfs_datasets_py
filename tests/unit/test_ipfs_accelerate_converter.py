"""
Tests for IPFS-accelerated file converter.

Tests the integration of file conversion with IPFS storage and ML acceleration.
"""

import pytest
import asyncio
from pathlib import Path
import tempfile
import os

from ipfs_datasets_py.file_converter import (
    IPFSAcceleratedConverter,
    IPFSConversionResult,
    create_converter,
    IPFSBackend,
    get_ipfs_backend,
    IPFS_AVAILABLE
)


class TestIPFSBackend:
    """Test IPFS backend functionality."""
    
    def test_backend_initialization(self):
        """Test IPFSBackend initialization."""
        backend = IPFSBackend()
        assert backend is not None
        assert backend.gateway_url is not None
        
    def test_backend_status(self):
        """Test backend status reporting."""
        backend = IPFSBackend()
        status = backend.get_status()
        
        assert 'available' in status
        assert 'connected' in status
        assert 'gateway_url' in status
        assert isinstance(status['available'], bool)
    
    def test_get_ipfs_backend(self):
        """Test convenience function."""
        backend = get_ipfs_backend()
        assert isinstance(backend, IPFSBackend)
    
    def test_gateway_url_generation(self):
        """Test gateway URL generation."""
        backend = IPFSBackend()
        cid = "QmTest123"
        url = backend.get_gateway_url(cid)
        
        assert cid in url
        assert 'ipfs' in url.lower()


class TestIPFSAcceleratedConverter:
    """Test IPFS-accelerated converter."""
    
    def test_converter_initialization(self):
        """Test converter initialization with default settings."""
        converter = IPFSAcceleratedConverter(backend="native", )
        
        assert converter is not None
        assert converter.converter is not None
        assert converter.cache_dir is not None
        assert converter.cache_dir.exists()
    
    def test_converter_with_custom_settings(self):
        """Test converter with custom settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / 'cache'
            
            converter = IPFSAcceleratedConverter(backend='native',
                enable_ipfs=False,
                enable_acceleration=False,
                cache_dir=cache_dir
            )
            
            assert converter.converter.backend == 'native'
            assert not converter.enable_ipfs
            assert not converter.enable_acceleration
            assert converter.cache_dir == cache_dir
    
    def test_converter_status(self):
        """Test status reporting."""
        converter = IPFSAcceleratedConverter(backend="native", )
        status = converter.get_status()
        
        assert 'converter_backend' in status
        assert 'ipfs_enabled' in status
        assert 'acceleration_enabled' in status
        assert 'ipfs' in status
        assert 'acceleration' in status
    
    @pytest.mark.asyncio
    async def test_convert_basic_file(self):
        """Test converting a basic text file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Hello, this is a test file!")
            temp_path = f.name
        
        try:
            converter = IPFSAcceleratedConverter(backend="native", 
                enable_ipfs=False,  # Disable IPFS for basic test
                enable_acceleration=False
            )
            
            result = await converter.convert(temp_path)
            
            assert isinstance(result, IPFSConversionResult)
            assert result.text
            assert "test file" in result.text
            assert result.metadata is not None
            assert result.processing_time is not None
        finally:
            Path(temp_path).unlink(missing_ok=True)
    
    def test_convert_sync_wrapper(self):
        """Test synchronous conversion wrapper."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Synchronous test content")
            temp_path = f.name
        
        try:
            converter = IPFSAcceleratedConverter(backend="native", 
                enable_ipfs=False,
                enable_acceleration=False
            )
            
            result = converter.convert_sync(temp_path)
            
            assert isinstance(result, IPFSConversionResult)
            assert result.text
            assert "Synchronous" in result.text
        finally:
            Path(temp_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_convert_batch(self):
        """Test batch conversion."""
        temp_files = []
        try:
            # Create test files
            for i in range(3):
                f = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
                f.write(f"Test file {i+1}")
                f.close()
                temp_files.append(f.name)
            
            converter = IPFSAcceleratedConverter(backend="native", 
                enable_ipfs=False,
                enable_acceleration=False
            )
            
            results = await converter.convert_batch(temp_files, max_concurrent=2)
            
            assert len(results) == 3
            for result in results:
                if not isinstance(result, Exception):
                    assert isinstance(result, IPFSConversionResult)
                    assert result.text
        finally:
            for path in temp_files:
                Path(path).unlink(missing_ok=True)
    
    def test_ipfs_conversion_result_dataclass(self):
        """Test IPFSConversionResult dataclass."""
        result = IPFSConversionResult(
            text="Sample text",
            metadata={"format": "txt"},
            ipfs_cid="QmTest",
            ipfs_pinned=True,
            accelerated=True
        )
        
        assert result.text == "Sample text"
        assert result.ipfs_cid == "QmTest"
        assert result.ipfs_pinned
        assert result.accelerated
        assert result.success
        
        # Test to_dict
        result_dict = result.to_dict()
        assert result_dict['text'] == "Sample text"
        assert result_dict['ipfs_cid'] == "QmTest"
    
    def test_create_converter_convenience_function(self):
        """Test create_converter convenience function."""
        converter = create_converter(
            backend='native',
            enable_ipfs=False
        )
        
        assert isinstance(converter, IPFSAcceleratedConverter)
        assert converter.converter.backend == 'native'


class TestIPFSIntegration:
    """Test IPFS integration (conditional on IPFS availability)."""
    
    @pytest.mark.skipif(not IPFS_AVAILABLE, reason="IPFS not available")
    @pytest.mark.asyncio
    async def test_ipfs_storage_enabled(self):
        """Test conversion with IPFS storage (if available)."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test content for IPFS storage")
            temp_path = f.name
        
        try:
            converter = IPFSAcceleratedConverter(backend="native", 
                enable_ipfs=True,
                enable_acceleration=False
            )
            
            # Check if IPFS backend is connected
            if converter.ipfs_backend and converter.ipfs_backend.is_available():
                result = await converter.convert(temp_path, store_on_ipfs=True, pin=False)
                
                # If IPFS is actually available, we should get a CID
                # Otherwise, conversion should still succeed without IPFS
                assert isinstance(result, IPFSConversionResult)
                assert result.text
                
                if result.ipfs_cid:
                    assert result.ipfs_gateway_url
                    assert result.ipfs_cid in result.ipfs_gateway_url
        finally:
            Path(temp_path).unlink(missing_ok=True)
    
    def test_ipfs_disabled_conversion(self):
        """Test conversion with IPFS explicitly disabled."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("No IPFS test")
            temp_path = f.name
        
        try:
            converter = IPFSAcceleratedConverter(backend="native", enable_ipfs=False)
            result = converter.convert_sync(temp_path)
            
            assert isinstance(result, IPFSConversionResult)
            assert result.text
            assert result.ipfs_cid is None
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestAccelerationIntegration:
    """Test ML acceleration integration."""
    
    def test_acceleration_status_check(self):
        """Test acceleration availability check."""
        converter = IPFSAcceleratedConverter(backend="native", )
        status = converter.get_status()
        
        assert 'acceleration' in status
        assert 'available' in status['acceleration']
    
    def test_acceleration_manager_initialization(self):
        """Test acceleration manager initialization."""
        converter = IPFSAcceleratedConverter(backend="native", enable_acceleration=True)
        
        # Manager may be None if accelerate not available
        # This should not cause errors
        assert converter.accel_manager is None or hasattr(converter.accel_manager, 'is_available')


class TestEnvironmentControl:
    """Test environment-based control."""
    
    def test_ipfs_disabled_via_env(self, monkeypatch):
        """Test disabling IPFS via environment variable."""
        monkeypatch.setenv('IPFS_STORAGE_ENABLED', '0')
        
        # Need to reimport to pick up env change
        from ipfs_datasets_py.file_converter.backends.ipfs_backend import IPFSBackend
        
        backend = IPFSBackend()
        # When disabled, backend should indicate unavailability
        status = backend.get_status()
        assert not status['connected']
    
    def test_converter_with_env_disabled(self, monkeypatch):
        """Test converter with acceleration disabled via env."""
        monkeypatch.setenv('IPFS_ACCELERATE_ENABLED', '0')
        
        converter = IPFSAcceleratedConverter(backend="native", enable_acceleration=True)
        status = converter.get_status()
        
        # Acceleration should respect env variable
        assert not status['acceleration']['available']


class TestErrorHandling:
    """Test error handling in IPFS operations."""
    
    @pytest.mark.asyncio
    async def test_missing_file_handling(self):
        """Test handling of missing file."""
        converter = IPFSAcceleratedConverter(backend="native", enable_ipfs=False)
        
        # Should handle missing file gracefully
        with pytest.raises(Exception):  # FileNotFoundError or similar
            await converter.convert('/nonexistent/file.txt')
    
    @pytest.mark.asyncio
    async def test_ipfs_failure_fallback(self):
        """Test fallback when IPFS operations fail."""
        converter = IPFSAcceleratedConverter(backend="native", enable_ipfs=True)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test fallback")
            temp_path = f.name
        
        try:
            # Even if IPFS fails, conversion should succeed
            result = await converter.convert(temp_path)
            
            assert isinstance(result, IPFSConversionResult)
            assert result.text
            # IPFS CID may or may not be present depending on availability
        finally:
            Path(temp_path).unlink(missing_ok=True)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
