import unittest
import json
import os
import shutil


from pathlib import Path
try:
    from pydantic import ValidationError
except ImportError:
    raise ImportError("Pydantic is required for this test suite. Please install it with 'pip install pydantic'.")


from core._pipeline_status import PipelineStatus
import tempfile


class TestPipelineStatusInitialization(unittest.TestCase):
    """Test PipelineStatus initialization and validation."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a temp directory for test files
        self.temp_dir = tempfile.mkdtemp()
        
        # Create test files
        self.test_file_path = os.path.join(self.temp_dir, "test_file.txt")
        with open(self.test_file_path, 'w') as f:
            f.write("Test content")
        
        self.large_file_path = os.path.join(self.temp_dir, "large_file.txt")
        with open(self.large_file_path, 'w') as f:
            f.write("A" * (15 * 1024 * 1024))  # 15 MB file (exceeds text limit)

        self.executable_file_path = os.path.join(self.temp_dir, "test_script.sh")
        with open(self.executable_file_path, 'w') as f:
            f.write("#!/bin/sh\necho 'Hello, world!'")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_initialization(self):
        """
        GIVEN no arguments
        WHEN PipelineStatus() is instantiated
        THEN expect:
            - total_files = 0
            - successful_files = 0
            - failed_files = 0
            - current_file = ""
            - is_processing = False
        """
        status = PipelineStatus()
        
        self.assertEqual(status.total_files, 0)
        self.assertEqual(status.successful_files, 0)
        self.assertEqual(status.failed_files, 0)
        self.assertEqual(status.current_file, "")
        self.assertEqual(status.is_processing, False)

    def test_initialization_with_all_parameters(self):
        """
        GIVEN all valid parameters
        WHEN PipelineStatus is instantiated with specific values
        THEN expect:
            - All attributes match the provided values
            - Instance is created successfully
        """

        status = PipelineStatus(
            total_files=10,
            successful_files=7,
            failed_files=2,
            current_file=self.test_file_path,
            is_processing=True
        )
        
        self.assertEqual(status.total_files, 10)
        self.assertEqual(status.successful_files, 7)
        self.assertEqual(status.failed_files, 2)
        self.assertEqual(status.current_file, Path(self.test_file_path))
        self.assertEqual(status.is_processing, True)
    
    def test_initialization_with_partial_parameters(self):
        """
        GIVEN only some parameters
        WHEN PipelineStatus is instantiated with partial values
        THEN expect:
            - Provided attributes match the given values
            - Unprovided attributes use default values
        """
        status = PipelineStatus(total_files=5, is_processing=True)
        
        self.assertEqual(status.total_files, 5)
        self.assertEqual(status.successful_files, 0)  # default
        self.assertEqual(status.failed_files, 0)      # default
        self.assertEqual(status.current_file, "")     # default
        self.assertEqual(status.is_processing, True)
    
    def test_initialization_with_invalid_types(self):
        """
        GIVEN invalid parameter types
        WHEN PipelineStatus is instantiated with wrong types
        THEN expect:
            - ValidationError is raised
            - Error message indicates type mismatch
        """
        with self.assertRaises(ValidationError) as context:
            PipelineStatus(total_files="not_a_number")
        
        error_details = str(context.exception)
        self.assertIn("total_files", error_details)
        
        with self.assertRaises(ValidationError):
            PipelineStatus(is_processing="not_a_boolean")
        
        with self.assertRaises(ValidationError):
            PipelineStatus(current_file=123)
    
    def test_initialization_with_negative_file_counts(self):
        """
        GIVEN negative values for file counts
        WHEN PipelineStatus is instantiated with negative numbers
        THEN expect:
            - Either ValidationError is raised OR
            - Values are accepted (depending on validation rules)
        """
        # Test if negative values are accepted or rejected
        try:
            status = PipelineStatus(
                total_files=-1,
                successful_files=-2,
                failed_files=-3
            )
            # If accepted, verify they are stored as-is
            self.assertEqual(status.total_files, -1)
            self.assertEqual(status.successful_files, -2)
            self.assertEqual(status.failed_files, -3)
        except ValidationError:
            # If validation rejects negative values, that's also valid behavior
            pass


class TestPipelineStatusAttributes(unittest.TestCase):
    """Test PipelineStatus attribute access and behavior."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a temp directory for test files
        self.temp_dir = tempfile.mkdtemp()
        
        # Create test files
        self.test_file_path = os.path.join(self.temp_dir, "test_file.txt")
        with open(self.test_file_path, 'w') as f:
            f.write("Test content")
        
        self.large_file_path = os.path.join(self.temp_dir, "large_file.txt")
        with open(self.large_file_path, 'w') as f:
            f.write("A" * (15 * 1024 * 1024))  # 15 MB file (exceeds text limit)

        self.executable_file_path = os.path.join(self.temp_dir, "test_script.sh")
        with open(self.executable_file_path, 'w') as f:
            f.write("#!/bin/sh\necho 'Hello, world!'")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)


    def test_attribute_access(self):
        """
        GIVEN a PipelineStatus instance
        WHEN accessing individual attributes
        THEN expect:
            - All attributes are accessible
            - Values match those set during initialization
        """
        test_path = os.path.join(self.temp_dir, "test_file.txt")

        status = PipelineStatus(
            total_files=15,
            successful_files=10,
            failed_files=3,
            current_file=self.test_file_path,
            is_processing=True
        )
        
        # Test all attributes are accessible
        self.assertIsInstance(status.total_files, int)
        self.assertIsInstance(status.successful_files, int)
        self.assertIsInstance(status.failed_files, int)
        self.assertIsInstance(status.current_file, Path)
        self.assertIsInstance(status.is_processing, bool)
        
        # Test values match initialization
        self.assertEqual(status.total_files, 15)
        self.assertEqual(status.successful_files, 10)
        self.assertEqual(status.failed_files, 3)
        self.assertEqual(status.current_file, Path(self.test_file_path))
        self.assertEqual(status.is_processing, True)
    
    def test_attribute_immutability(self):
        """
        GIVEN a PipelineStatus instance (Pydantic model)
        WHEN attempting to modify attributes
        THEN expect:
            - Attributes can be modified (if mutable)
            - Model validates new values
        """
        status = PipelineStatus()

        # Test attribute modification
        status.total_files = 5
        self.assertEqual(status.total_files, 5)

        status.current_file = self.test_file_path
        self.assertEqual(status.current_file, Path(self.test_file_path))

        status.is_processing = True
        self.assertEqual(status.is_processing, True)

        # Test validation on modification
        with self.assertRaises(ValidationError):
            status.total_files = "not_a_number"

    def test_pydantic_model_fields(self):
        """
        GIVEN the PipelineStatus class
        WHEN inspecting model fields
        THEN expect:
            - All documented fields are present
            - Field types match documentation
        """
        model_fields = PipelineStatus.model_fields
        
        # Check all expected fields are present
        expected_fields = {
            'total_files', 'successful_files', 'failed_files', 
            'current_file', 'is_processing'
        }
        actual_fields = set(model_fields.keys())
        self.assertEqual(expected_fields, actual_fields)
        
        # Check field types
        self.assertEqual(model_fields['total_files'].annotation, int)
        self.assertEqual(model_fields['successful_files'].annotation, int)
        self.assertEqual(model_fields['failed_files'].annotation, int)
        self.assertEqual(model_fields['current_file'].annotation, Path)
        self.assertEqual(model_fields['is_processing'].annotation, bool)


class TestPipelineStatusToDict(unittest.TestCase):
    """Test the to_dict method."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a temp directory for test files
        self.temp_dir = tempfile.mkdtemp()

        # Create test files
        self.test_file_path = os.path.join(self.temp_dir, "test_file.txt")
        with open(self.test_file_path, 'w') as f:
            f.write("Test content")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_to_dict_with_default_values(self):
        """
        GIVEN a PipelineStatus instance with default values
        WHEN to_dict() is called
        THEN expect:
            - Returns a dictionary
            - Contains all expected keys
            - Values match instance attributes
        """
        status = PipelineStatus()
        result = status.to_dict()
        
        self.assertIsInstance(result, dict)
        
        expected_keys = {
            'total_files', 'successful_files', 'failed_files',
            'current_file', 'is_processing'
        }
        self.assertEqual(set(result.keys()), expected_keys)
        
        self.assertEqual(result['total_files'], 0)
        self.assertEqual(result['successful_files'], 0)
        self.assertEqual(result['failed_files'], 0)
        self.assertEqual(result['current_file'], "")
        self.assertEqual(result['is_processing'], False)
    
    def test_to_dict_with_custom_values(self):
        """
        GIVEN a PipelineStatus instance with custom values
        WHEN to_dict() is called
        THEN expect:
            - Returns a dictionary
            - All custom values are preserved
            - No extra keys are present
        """
        status = PipelineStatus(
            total_files=20,
            successful_files=15,
            failed_files=3,
            current_file=self.test_file_path,
            is_processing=True
        )
        result = status.to_dict()
        
        self.assertIsInstance(result, dict)
        self.assertEqual(len(result), 5)  # No extra keys
        
        self.assertEqual(result['total_files'], 20)
        self.assertEqual(result['successful_files'], 15)
        self.assertEqual(result['failed_files'], 3)
        self.assertEqual(result['current_file'], Path(self.test_file_path))
        self.assertEqual(result['is_processing'], True)
    
    def test_to_dict_return_type(self):
        """
        GIVEN a PipelineStatus instance
        WHEN to_dict() is called
        THEN expect:
            - Return type is dict[str, Any]
            - All keys are strings
        """
        status = PipelineStatus()
        result = status.to_dict()
        
        self.assertIsInstance(result, dict)
        
        # Check all keys are strings
        for key in result.keys():
            self.assertIsInstance(key, str)
        
        # Check annotation matches expected type
        self.assertTrue(hasattr(status.to_dict, '__annotations__'))
    
    def test_to_dict_with_processing_active(self):
        """
        GIVEN a PipelineStatus instance with is_processing=True
        WHEN to_dict() is called
        THEN expect:
            - Dictionary correctly reflects processing state
            - current_file value is included
        """
        status = PipelineStatus(
            is_processing=True,
            current_file=self.test_file_path
        )
        result = status.to_dict()
        
        self.assertEqual(result['is_processing'], True)
        self.assertEqual(result['current_file'], Path(self.test_file_path))


class TestPipelineStatusBusinessLogic(unittest.TestCase):
    """Test business logic constraints and relationships."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a temp directory for test files
        self.temp_dir = tempfile.mkdtemp()

        # Create test files
        self.test_file_path = os.path.join(self.temp_dir, "test_file.txt")
        with open(self.test_file_path, 'w') as f:
            f.write("Test content")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_file_count_consistency(self):
        """
        GIVEN various file count combinations
        WHEN PipelineStatus is created
        THEN expect:
            - total_files >= successful_files + failed_files (if enforced)
            - OR accept any values (if not enforced)
        """
        # Test consistent counts
        status1 = PipelineStatus(
            total_files=10,
            successful_files=7,
            failed_files=3
        )
        self.assertEqual(status1.total_files, 10)
        self.assertEqual(status1.successful_files + status1.failed_files, 10)
        
        # Test inconsistent counts - check if validation exists
        try:
            status2 = PipelineStatus(
                total_files=5,
                successful_files=7,  # More than total
                failed_files=3
            )
            # If no validation, values are stored as-is
            self.assertEqual(status2.total_files, 5)
            self.assertEqual(status2.successful_files, 7)
            self.assertEqual(status2.failed_files, 3)
        except ValidationError:
            # If validation exists and rejects inconsistent counts
            pass
    
    def test_current_file_when_not_processing(self):
        """
        GIVEN is_processing=False
        WHEN current_file has a value
        THEN expect:
            - Either validation error OR
            - Value is accepted (depending on business rules)
        """
        try:
            status = PipelineStatus(
                is_processing=False,
                current_file=self.test_file_path
            )
            # If accepted, verify values
            self.assertEqual(status.is_processing, False)
            self.assertEqual(status.current_file, Path(self.test_file_path))
        except ValidationError:
            # If business logic rejects this combination
            pass
    
    def test_current_file_when_processing(self):
        """
        GIVEN is_processing=True
        WHEN current_file is empty or has value
        THEN expect:
            - Appropriate validation behavior
        """
        # Test with empty current_file
        try:
            status1 = PipelineStatus(
                is_processing=True,
                current_file=""
            )
            self.assertEqual(status1.is_processing, True)
            self.assertEqual(status1.current_file, "")
        except ValidationError:
            pass
        
        # Test with valid current_file
        status2 = PipelineStatus(
            is_processing=True,
            current_file=self.test_file_path
        )
        self.assertEqual(status2.is_processing, True)
        self.assertEqual(status2.current_file, Path(self.test_file_path))


class TestPipelineStatusSerialization(unittest.TestCase):
    """Test serialization and deserialization capabilities."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a temp directory for test files
        self.temp_dir = tempfile.mkdtemp()
        
        # Create test files
        self.json_test_file_path = os.path.join(self.temp_dir, "test_json_file.json")
        with open(self.json_test_file_path, 'w') as f:
            json.dump({"test": "content", "format": "json"}, f)

        # Create test files
        self.test_file_path = os.path.join(self.temp_dir, "test_text_file.txt")
        with open(self.test_file_path, 'w') as f:
            f.write("Test content")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_json_serialization(self):
        """
        GIVEN a PipelineStatus instance
        WHEN converting to JSON (via Pydantic)
        THEN expect:
            - Valid JSON string is produced
            - All fields are included
        """
        status = PipelineStatus(
            total_files=25,
            successful_files=20,
            failed_files=3,
            current_file=self.json_test_file_path,
            is_processing=False
        )

        json_str = status.model_dump_json()
        self.assertIsInstance(json_str, str)

        # Parse back to verify it's valid JSON
        parsed = json.loads(json_str)
        self.assertIsInstance(parsed, dict)
        
        # Check all fields are present
        expected_keys = {
            'total_files', 'successful_files', 'failed_files',
            'current_file', 'is_processing'
        }
        self.assertEqual(set(parsed.keys()), expected_keys)
    
    def test_json_deserialization(self):
        """
        GIVEN a valid JSON string
        WHEN creating PipelineStatus from JSON
        THEN expect:
            - Instance is created successfully
            - All values match the JSON data
        """
        json_data = {
            'total_files': 30,
            'successful_files': 25,
            'failed_files': 2,
            'current_file': self.test_file_path,
            'is_processing': True
        }
        json_str = json.dumps(json_data)
        
        status = PipelineStatus.model_validate_json(json_str)
        
        self.assertEqual(status.total_files, 30)
        self.assertEqual(status.successful_files, 25)
        self.assertEqual(status.failed_files, 2)
        self.assertEqual(status.current_file, Path(self.test_file_path))
        self.assertEqual(status.is_processing, True)
    
    def test_dict_serialization_compatibility(self):
        """
        GIVEN a PipelineStatus instance
        WHEN using Pydantic's dict() method vs custom to_dict()
        THEN expect:
            - Both methods produce compatible output
            - OR differences are documented
        """
        status = PipelineStatus(
            total_files=40,
            successful_files=35,
            failed_files=3,
            current_file=self.test_file_path,
            is_processing=False
        )
        
        pydantic_dict = status.model_dump()
        custom_dict = status.to_dict()
        
        # Check both are dictionaries
        self.assertIsInstance(pydantic_dict, dict)
        self.assertIsInstance(custom_dict, dict)
        
        # Check they have the same keys
        self.assertEqual(set(pydantic_dict.keys()), set(custom_dict.keys()))
        
        # Check values are the same
        for key in pydantic_dict.keys():
            self.assertEqual(pydantic_dict[key], custom_dict[key])


if __name__ == "__main__":
    unittest.main()