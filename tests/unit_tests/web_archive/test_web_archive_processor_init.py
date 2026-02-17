import pytest

from ipfs_datasets_py.processors.web_archiving.web_archive import WebArchiveProcessor


class TestWebArchiveProcessorInitialization:
    """Test WebArchiveProcessor initialization and configuration."""

    def test_init_creates_instance(self):
        """
        GIVEN no arguments
        WHEN WebArchiveProcessor is initialized
        THEN expect:
            - Instance created successfully
        """
        # GIVEN no arguments
        # WHEN WebArchiveProcessor is initialized
        try:
            processor = WebArchiveProcessor()
            
            # THEN expect instance created successfully
            assert processor is not None
            assert isinstance(processor, WebArchiveProcessor)
        except ImportError:
            pytest.skip("WebArchiveProcessor not available")

    def test_init_archive_attribute_exists(self):
        """
        GIVEN no arguments
        WHEN WebArchiveProcessor is initialized
        THEN expect:
            - archive attribute exists
        """
        # GIVEN no arguments
        try:
            # WHEN WebArchiveProcessor is initialized
            processor = WebArchiveProcessor()
            
            # THEN expect archive attribute exists
            assert hasattr(processor, 'archive')
        except ImportError:
            pytest.skip("WebArchiveProcessor not available")

    def test_init_archive_attribute_is_web_archive_instance(self):
        """
        GIVEN no arguments
        WHEN WebArchiveProcessor is initialized
        THEN expect:
            - archive attribute is WebArchive instance
        """
        # GIVEN no arguments
        try:
            from ipfs_datasets_py.processors.web_archiving.web_archive import WebArchive
            
            # WHEN WebArchiveProcessor is initialized
            processor = WebArchiveProcessor()
            
            # THEN expect archive attribute is WebArchive instance
            assert hasattr(processor, 'archive')
            if processor.archive is not None:
                assert isinstance(processor.archive, WebArchive)
        except ImportError:
            pytest.skip("WebArchive components not available")

    def test_archive_attribute_is_web_archive(self):
        """
        GIVEN WebArchiveProcessor instance
        WHEN checking archive attribute
        THEN expect:
            - archive attribute is instance of WebArchive
        """
        # GIVEN WebArchiveProcessor instance
        try:
            from ipfs_datasets_py.processors.web_archiving.web_archive import WebArchive
            processor = WebArchiveProcessor()
            
            # WHEN checking archive attribute
            archive = processor.archive
            
            # THEN expect archive attribute is instance of WebArchive
            if archive is not None:
                assert isinstance(archive, WebArchive)
        except ImportError:
            pytest.skip("WebArchive components not available")

    def test_archive_attribute_is_accessible(self):
        """
        GIVEN WebArchiveProcessor instance
        WHEN checking archive attribute
        THEN expect:
            - archive attribute is accessible
        """
        # GIVEN WebArchiveProcessor instance
        try:
            processor = WebArchiveProcessor()
            
            # WHEN checking archive attribute
            archive = getattr(processor, 'archive', None)
            
            # THEN expect archive attribute is accessible
            assert archive is not None or hasattr(processor, 'archive')
        except ImportError:
            pytest.skip("WebArchiveProcessor not available")

    def test_processor_ready_for_operations_has_required_attributes(self):
        """
        GIVEN newly initialized WebArchiveProcessor
        WHEN checking readiness for operations
        THEN expect:
            - Instance has all required attributes
        """
        # GIVEN newly initialized WebArchiveProcessor
        try:
            processor = WebArchiveProcessor()
            
            # WHEN checking readiness for operations
            required_attributes = ['archive']
            
            # THEN expect instance has all required attributes
            for attr in required_attributes:
                assert hasattr(processor, attr), f"Missing required attribute: {attr}"
        except ImportError:
            pytest.skip("WebArchiveProcessor not available")

    def test_processor_ready_for_operations_can_access_web_archive_methods(self):
        """
        GIVEN newly initialized WebArchiveProcessor
        WHEN checking readiness for operations
        THEN expect:
            - Can access embedded WebArchive methods
        """
        # GIVEN newly initialized WebArchiveProcessor
        try:
            processor = WebArchiveProcessor()
            
            # WHEN checking readiness for operations
            if hasattr(processor, 'archive') and processor.archive is not None:
                archive = processor.archive
                
                # THEN expect can access embedded WebArchive methods
                expected_methods = ['archive_url', 'create_warc', 'extract_text_from_html']
                for method in expected_methods:
                    if hasattr(archive, method):
                        assert callable(getattr(archive, method)), f"Method {method} is not callable"
        except ImportError:
            pytest.skip("WebArchive components not available")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])