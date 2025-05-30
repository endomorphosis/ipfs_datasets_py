#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Test generator for Audit tools in the MCP server.
This script generates tests for the Audit tools:
- generate_audit_report
- record_audit_event
"""

import os
import sys
import inspect
import importlib
from unittest.mock import patch, MagicMock

# Add the parent directory to the path so we can import the tools
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the Audit tools
try:
    from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report
    from ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event import record_audit_event
except ImportError as e:
    print(f"Error importing Audit tools: {e}")
    sys.exit(1)

# Function to analyze the function signature
def analyze_function_signature(func):
    sig = inspect.signature(func)
    params = []
    for name, param in sig.parameters.items():
        param_type = param.annotation if param.annotation != inspect.Parameter.empty else "Any"
        if param_type != inspect.Parameter.empty:
            # Convert annotations to strings to handle forward references
            param_type = str(param_type).replace("typing.", "").replace("'", "")
            if "ForwardRef" in param_type:
                param_type = param_type.split("'")[1]
        default = param.default if param.default != inspect.Parameter.empty else None
        params.append({
            'name': name,
            'type': param_type,
            'default': default
        })
    return_type = sig.return_annotation
    if return_type != inspect.Signature.empty:
        return_type = str(return_type).replace("typing.", "").replace("'", "")
        if "ForwardRef" in return_type:
            return_type = return_type.split("'")[1]
    else:
        return_type = "Any"
    return params, return_type

# Create a test class for generate_audit_report
def generate_audit_report_test():
    try:
        params, return_type = analyze_function_signature(generate_audit_report)

        test_content = f"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import os
import tempfile
import json
import datetime

# Import the function to test
from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report

class TestGenerateAuditReport:
    @pytest.fixture
    def mock_audit_manager(self):
        mock_manager = MagicMock()

        # Sample audit events data
        sample_events = [
            {{
                'event_id': '1',
                'timestamp': datetime.datetime.now().isoformat(),
                'event_type': 'dataset_access',
                'user_id': 'user123',
                'resource_id': 'dataset_abc',
                'action': 'read',
                'status': 'success'
            }},
            {{
                'event_id': '2',
                'timestamp': datetime.datetime.now().isoformat(),
                'event_type': 'dataset_modification',
                'user_id': 'user456',
                'resource_id': 'dataset_xyz',
                'action': 'write',
                'status': 'success'
            }}
        ]

        mock_manager.get_audit_events = AsyncMock(return_value=sample_events)
        return mock_manager

    @pytest.mark.asyncio
    async def test_generate_audit_report_default(self, mock_audit_manager):
        # Create a temporary directory for output
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, 'audit_report.json')

        try:
            # Mock the audit manager
            with patch('ipfs_datasets_py.audit_kit.AuditManager', return_value=mock_audit_manager):
                # Call the function
                result = await generate_audit_report(output_path=output_path)

                # Assertions
                assert result is not None
                assert os.path.exists(output_path)

                # Verify the content of the report
                with open(output_path, 'r') as f:
                    report_content = json.load(f)

                assert 'audit_events' in report_content
                assert len(report_content['audit_events']) == 2

                # Verify the mock was called correctly
                mock_audit_manager.get_audit_events.assert_called_once()
        finally:
            # Clean up the temporary directory
            import shutil
            shutil.rmtree(temp_dir)

    @pytest.mark.asyncio
    async def test_generate_audit_report_with_filters(self, mock_audit_manager):
        # Create a temporary directory for output
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, 'audit_report.json')

        try:
            # Set up filter parameters
            start_date = datetime.datetime.now() - datetime.timedelta(days=7)
            end_date = datetime.datetime.now()
            event_type = 'dataset_access'
            user_id = 'user123'

            # Mock the audit manager
            with patch('ipfs_datasets_py.audit_kit.AuditManager', return_value=mock_audit_manager):
                # Call the function
                result = await generate_audit_report(
                    start_date=start_date,
                    end_date=end_date,
                    event_type=event_type,
                    user_id=user_id,
                    output_path=output_path
                )

                # Assertions
                assert result is not None
                assert os.path.exists(output_path)

                # Verify the mock was called correctly with filters
                mock_audit_manager.get_audit_events.assert_called_once()
                call_kwargs = mock_audit_manager.get_audit_events.call_args[1]
                assert 'start_date' in call_kwargs
                assert 'end_date' in call_kwargs
                assert 'event_type' in call_kwargs
                assert 'user_id' in call_kwargs
                assert call_kwargs['event_type'] == event_type
                assert call_kwargs['user_id'] == user_id
        finally:
            # Clean up the temporary directory
            import shutil
            shutil.rmtree(temp_dir)
"""
        return test_content
    except Exception as e:
        print(f"Error generating test for generate_audit_report: {e}")
        return None

# Create a test class for record_audit_event
def generate_record_audit_event_test():
    try:
        params, return_type = analyze_function_signature(record_audit_event)

        test_content = f"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import datetime

# Import the function to test
from ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event import record_audit_event

class TestRecordAuditEvent:
    @pytest.fixture
    def mock_audit_manager(self):
        mock_manager = MagicMock()
        mock_manager.record_event = AsyncMock(return_value={{'event_id': 'test_event_123'}})
        return mock_manager

    @pytest.mark.asyncio
    async def test_record_audit_event_minimal(self, mock_audit_manager):
        # Mock the audit manager
        with patch('ipfs_datasets_py.audit_kit.AuditManager', return_value=mock_audit_manager):
            # Call the function with minimal parameters
            event_type = 'dataset_access'
            resource_id = 'dataset_abc'
            action = 'read'

            result = await record_audit_event(
                event_type=event_type,
                resource_id=resource_id,
                action=action
            )

            # Assertions
            assert result is not None
            assert 'event_id' in result
            assert result['event_id'] == 'test_event_123'

            # Verify the mock was called correctly
            mock_audit_manager.record_event.assert_called_once()
            call_args = mock_audit_manager.record_event.call_args[1]
            assert call_args['event_type'] == event_type
            assert call_args['resource_id'] == resource_id
            assert call_args['action'] == action

    @pytest.mark.asyncio
    async def test_record_audit_event_full(self, mock_audit_manager):
        # Mock the audit manager
        with patch('ipfs_datasets_py.audit_kit.AuditManager', return_value=mock_audit_manager):
            # Call the function with all parameters
            event_type = 'dataset_modification'
            resource_id = 'dataset_xyz'
            action = 'write'
            user_id = 'user456'
            status = 'success'
            metadata = {{'changed_fields': ['title', 'description'], 'reason': 'update'}}

            result = await record_audit_event(
                event_type=event_type,
                resource_id=resource_id,
                action=action,
                user_id=user_id,
                status=status,
                metadata=metadata
            )

            # Assertions
            assert result is not None
            assert 'event_id' in result

            # Verify the mock was called correctly with all parameters
            mock_audit_manager.record_event.assert_called_once()
            call_args = mock_audit_manager.record_event.call_args[1]
            assert call_args['event_type'] == event_type
            assert call_args['resource_id'] == resource_id
            assert call_args['action'] == action
            assert call_args['user_id'] == user_id
            assert call_args['status'] == status
            assert call_args['metadata'] == metadata

    @pytest.mark.asyncio
    async def test_record_audit_event_error_handling(self, mock_audit_manager):
        # Mock the audit manager to raise an exception
        mock_audit_manager.record_event.side_effect = Exception("Error recording audit event")

        # Mock the audit manager
        with patch('ipfs_datasets_py.audit_kit.AuditManager', return_value=mock_audit_manager):
            # Test error handling
            with pytest.raises(Exception):
                await record_audit_event(
                    event_type='error_test',
                    resource_id='test_resource',
                    action='test'
                )
"""
        return test_content
    except Exception as e:
        print(f"Error generating test for record_audit_event: {e}")
        return None

# Generate the test file
def generate_test_file():
    generate_audit_report_test_content = generate_audit_report_test()
    record_audit_event_test_content = generate_record_audit_event_test()

    test_file_content = """#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
    test_file_content += '"""'
    test_file_content += """
Test suite for Audit tools in the MCP server.
This file was automatically generated by test_generator_for_audit_tools.py.
"""
    test_file_content += '"""'
    test_file_content += """

import os
import sys
import pytest
"""

    if generate_audit_report_test_content:
        test_file_content += "\n" + generate_audit_report_test_content

    if record_audit_event_test_content:
        test_file_content += "\n" + record_audit_event_test_content

    # Create the test file
    test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
    os.makedirs(test_dir, exist_ok=True)
    test_file_path = os.path.join(test_dir, "test_audit_tools.py")

    with open(test_file_path, "w") as f:
        f.write(test_file_content)

    print(f"Generated test file: {test_file_path}")

# Main function
def main():
    print("Generating tests for Audit tools...")
    generate_test_file()
    print("Done!")

if __name__ == "__main__":
    main()
