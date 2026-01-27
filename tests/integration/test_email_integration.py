"""
Integration tests for email ingestion.

Tests the EmailProcessor functionality and MCP tools integration.
Uses anyio for asyncio/trio compatibility.
"""
import pytest
import anyio
import os
import tempfile
from pathlib import Path
from email.message import EmailMessage
import json

# Test the email processor module
from ipfs_datasets_py.multimedia.email_processor import (
    EmailProcessor,
    create_email_processor
)

# Test MCP tools
from ipfs_datasets_py.mcp_server.tools.email_tools import (
    email_test_connection,
    email_list_folders,
    email_export_folder,
    email_parse_eml,
    email_fetch_emails,
    email_analyze_export,
    email_search_export
)


class TestEmailProcessorCore:
    """Test the EmailProcessor core functionality."""
    
    def test_processor_initialization_imap(self):
        """
        GIVEN: Valid IMAP connection parameters
        WHEN: EmailProcessor is initialized
        THEN: Should create processor with correct settings
        """
        processor = EmailProcessor(
            protocol='imap',
            server='imap.gmail.com',
            username='test@example.com',
            password='test_password'
        )
        
        assert processor.protocol == 'imap'
        assert processor.server == 'imap.gmail.com'
        assert processor.port == 993  # Default IMAP SSL port
        assert processor.use_ssl is True
        assert processor.connected is False
    
    def test_processor_initialization_pop3(self):
        """
        GIVEN: Valid POP3 connection parameters
        WHEN: EmailProcessor is initialized
        THEN: Should create processor with correct settings
        """
        processor = EmailProcessor(
            protocol='pop3',
            server='pop.gmail.com',
            username='test@example.com',
            password='test_password'
        )
        
        assert processor.protocol == 'pop3'
        assert processor.server == 'pop.gmail.com'
        assert processor.port == 995  # Default POP3 SSL port
        assert processor.use_ssl is True
    
    def test_processor_initialization_eml(self):
        """
        GIVEN: EML protocol selected
        WHEN: EmailProcessor is initialized
        THEN: Should create processor without server requirements
        """
        processor = EmailProcessor(protocol='eml')
        
        assert processor.protocol == 'eml'
        assert processor.server is None
        assert processor.port is None
    
    def test_invalid_protocol_raises_error(self):
        """
        GIVEN: Invalid protocol name
        WHEN: EmailProcessor is initialized
        THEN: Should raise ValueError
        """
        with pytest.raises(ValueError, match="Protocol must be one of"):
            EmailProcessor(protocol='invalid')
    
    def test_missing_server_for_imap_raises_error(self):
        """
        GIVEN: IMAP protocol without server
        WHEN: EmailProcessor is initialized
        THEN: Should raise ValueError
        """
        with pytest.raises(ValueError, match="Server hostname required"):
            EmailProcessor(protocol='imap', server=None)
    
    def test_factory_function(self):
        """
        GIVEN: Factory function parameters
        WHEN: create_email_processor is called
        THEN: Should return EmailProcessor instance
        """
        processor = create_email_processor(
            protocol='imap',
            server='imap.example.com',
            username='user@example.com',
            password='password'
        )
        
        assert isinstance(processor, EmailProcessor)
        assert processor.protocol == 'imap'
        assert processor.server == 'imap.example.com'
    
    def test_environment_variable_credentials(self):
        """
        GIVEN: EMAIL_USER and EMAIL_PASS environment variables
        WHEN: EmailProcessor is initialized without credentials
        THEN: Should use environment variables
        """
        os.environ['EMAIL_USER'] = 'env_user@example.com'
        os.environ['EMAIL_PASS'] = 'env_password'
        
        try:
            processor = EmailProcessor(
                protocol='imap',
                server='imap.example.com'
            )
            
            assert processor.username == 'env_user@example.com'
            assert processor.password == 'env_password'
        finally:
            # Clean up
            os.environ.pop('EMAIL_USER', None)
            os.environ.pop('EMAIL_PASS', None)


class TestEmailParsingEML:
    """Test .eml file parsing functionality."""
    
    @pytest.fixture
    def sample_eml_file(self):
        """Create a sample .eml file for testing."""
        msg = EmailMessage()
        msg['Subject'] = 'Test Email'
        msg['From'] = 'sender@example.com'
        msg['To'] = 'recipient@example.com'
        msg['Date'] = 'Mon, 01 Jan 2024 12:00:00 +0000'
        msg.set_content('This is a test email body.')
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.eml', delete=False) as f:
            f.write(msg.as_bytes())
            temp_path = f.name
        
        yield temp_path
        
        # Cleanup
        Path(temp_path).unlink(missing_ok=True)
    
    @pytest.mark.anyio
    async def test_parse_simple_eml(self, sample_eml_file):
        """
        GIVEN: A valid .eml file
        WHEN: parse_eml_file is called
        THEN: Should parse and extract email data
        """
        processor = EmailProcessor(protocol='eml')
        result = await processor.parse_eml_file(sample_eml_file)
        
        assert result['status'] == 'success'
        assert result['protocol'] == 'eml'
        assert result['file_path'] == sample_eml_file
        
        email_data = result['email']
        assert email_data['subject'] == 'Test Email'
        assert email_data['from'] == 'sender@example.com'
        assert email_data['to'] == 'recipient@example.com'
        assert 'This is a test email body' in email_data['body_text']
    
    @pytest.mark.anyio
    async def test_parse_nonexistent_file(self):
        """
        GIVEN: A nonexistent .eml file path
        WHEN: parse_eml_file is called
        THEN: Should return error
        """
        processor = EmailProcessor(protocol='eml')
        result = await processor.parse_eml_file('/nonexistent/file.eml')
        
        assert result['status'] == 'error'
        assert 'error' in result


class TestEmailMCPTools:
    """Test MCP server tools for email operations."""
    
    @pytest.mark.anyio
    async def test_email_test_connection_missing_server(self):
        """
        GIVEN: Missing server parameter
        WHEN: email_test_connection is called
        THEN: Should return error
        """
        result = await email_test_connection(
            protocol='imap',
            server=None
        )
        
        assert result['status'] == 'error'
        assert 'server is required' in result['error']
    
    @pytest.mark.anyio
    async def test_email_test_connection_invalid_protocol(self):
        """
        GIVEN: Invalid protocol
        WHEN: email_test_connection is called
        THEN: Should return error
        """
        result = await email_test_connection(
            protocol='invalid',
            server='imap.example.com'
        )
        
        assert result['status'] == 'error'
        assert 'Protocol must be' in result['error']
    
    @pytest.mark.anyio
    async def test_email_test_connection_missing_credentials(self):
        """
        GIVEN: Missing username and password
        WHEN: email_test_connection is called
        THEN: Should return error about credentials
        """
        result = await email_test_connection(
            protocol='imap',
            server='imap.example.com'
        )
        
        assert result['status'] == 'error'
        assert 'username and password required' in result['error']
    
    @pytest.mark.anyio
    async def test_email_parse_eml_missing_file(self):
        """
        GIVEN: Missing file path
        WHEN: email_parse_eml is called
        THEN: Should return error
        """
        result = await email_parse_eml(file_path='')
        
        assert result['status'] == 'error'
        assert 'file_path is required' in result['error']
    
    @pytest.mark.anyio
    async def test_email_parse_eml_nonexistent_file(self):
        """
        GIVEN: Nonexistent file path
        WHEN: email_parse_eml is called
        THEN: Should return error
        """
        result = await email_parse_eml(file_path='/nonexistent/file.eml')
        
        assert result['status'] == 'error'
        assert 'File not found' in result['error']
    
    @pytest.mark.anyio
    async def test_email_export_folder_missing_server(self):
        """
        GIVEN: Missing server parameter
        WHEN: email_export_folder is called
        THEN: Should return error
        """
        result = await email_export_folder(
            folder='INBOX',
            server=None
        )
        
        assert result['status'] == 'error'
        assert 'server is required' in result['error']
    
    @pytest.mark.anyio
    async def test_email_export_folder_invalid_format(self):
        """
        GIVEN: Invalid export format
        WHEN: email_export_folder is called
        THEN: Should return error
        """
        result = await email_export_folder(
            folder='INBOX',
            server='imap.example.com',
            format='invalid'
        )
        
        assert result['status'] == 'error'
        assert 'Format must be' in result['error']
    
    @pytest.mark.anyio
    async def test_email_list_folders_missing_server(self):
        """
        GIVEN: Missing server parameter
        WHEN: email_list_folders is called
        THEN: Should return error
        """
        result = await email_list_folders(server=None)
        
        assert result['status'] == 'error'
        assert 'server is required' in result['error']


class TestEmailAnalysis:
    """Test email analysis functionality."""
    
    @pytest.fixture
    def sample_export_file(self):
        """Create a sample email export file for testing."""
        export_data = {
            'metadata': {
                'folder': 'INBOX',
                'export_date': '2024-01-01T12:00:00',
                'email_count': 3,
                'protocol': 'imap',
                'server': 'imap.example.com'
            },
            'emails': [
                {
                    'subject': 'Meeting Tomorrow',
                    'from': 'alice@example.com',
                    'to': 'bob@example.com',
                    'date': '2024-01-01T10:00:00',
                    'body_text': 'Let\'s meet tomorrow at 3pm.',
                    'body_html': '',
                    'attachments': [],
                    'headers': {},
                    'message_id_header': '<msg1@example.com>',
                    'in_reply_to': '',
                    'references': ''
                },
                {
                    'subject': 'Project Update',
                    'from': 'bob@example.com',
                    'to': 'alice@example.com',
                    'date': '2024-01-02T14:00:00',
                    'body_text': 'The project is on track.',
                    'body_html': '',
                    'attachments': [
                        {'filename': 'report.pdf', 'content_type': 'application/pdf', 'size': 1024}
                    ],
                    'headers': {},
                    'message_id_header': '<msg2@example.com>',
                    'in_reply_to': '',
                    'references': ''
                },
                {
                    'subject': 'Re: Meeting Tomorrow',
                    'from': 'bob@example.com',
                    'to': 'alice@example.com',
                    'date': '2024-01-01T11:00:00',
                    'body_text': 'Sounds good, see you then.',
                    'body_html': '',
                    'attachments': [],
                    'headers': {},
                    'message_id_header': '<msg3@example.com>',
                    'in_reply_to': '<msg1@example.com>',
                    'references': '<msg1@example.com>'
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(export_data, f)
            temp_path = f.name
        
        yield temp_path
        
        Path(temp_path).unlink(missing_ok=True)
    
    @pytest.mark.anyio
    async def test_analyze_export(self, sample_export_file):
        """
        GIVEN: A valid email export file
        WHEN: email_analyze_export is called
        THEN: Should return statistics
        """
        result = await email_analyze_export(sample_export_file)
        
        assert result['status'] == 'success'
        assert result['total_emails'] == 3
        assert result['attachment_stats']['total_attachments'] == 1
        assert result['thread_count'] == 1  # One thread with reply
        assert len(result['top_senders']) > 0
        assert len(result['top_recipients']) > 0
    
    @pytest.mark.anyio
    async def test_search_export_by_subject(self, sample_export_file):
        """
        GIVEN: A valid email export file
        WHEN: email_search_export is called with subject search
        THEN: Should return matching emails
        """
        result = await email_search_export(
            file_path=sample_export_file,
            query='meeting',
            field='subject'
        )
        
        assert result['status'] == 'success'
        assert result['match_count'] == 2  # "Meeting Tomorrow" and "Re: Meeting Tomorrow"
        assert result['query'] == 'meeting'
        assert result['field'] == 'subject'
    
    @pytest.mark.anyio
    async def test_search_export_by_body(self, sample_export_file):
        """
        GIVEN: A valid email export file
        WHEN: email_search_export is called with body search
        THEN: Should return matching emails
        """
        result = await email_search_export(
            file_path=sample_export_file,
            query='project',
            field='body'
        )
        
        assert result['status'] == 'success'
        assert result['match_count'] == 1  # "The project is on track"
    
    @pytest.mark.anyio
    async def test_search_export_all_fields(self, sample_export_file):
        """
        GIVEN: A valid email export file
        WHEN: email_search_export is called with 'all' field
        THEN: Should search across all fields
        """
        result = await email_search_export(
            file_path=sample_export_file,
            query='bob@example.com',
            field='all'
        )
        
        assert result['status'] == 'success'
        assert result['match_count'] == 3  # All emails mention bob
    
    @pytest.mark.anyio
    async def test_analyze_nonexistent_file(self):
        """
        GIVEN: Nonexistent file path
        WHEN: email_analyze_export is called
        THEN: Should return error
        """
        result = await email_analyze_export('/nonexistent/file.json')
        
        assert result['status'] == 'error'
        assert 'File not found' in result['error']


class TestEmailFormats:
    """Test different export formats."""
    
    @pytest.mark.anyio
    async def test_format_validation_json(self):
        """
        GIVEN: JSON format specified
        WHEN: export format is validated
        THEN: Should accept JSON
        """
        result = await email_export_folder(
            folder='INBOX',
            server='imap.example.com',
            format='json',
            username='test@example.com',
            password='password'
        )
        
        # Will fail connection but format validation should pass
        assert 'Format must be' not in result.get('error', '')
    
    @pytest.mark.anyio
    async def test_format_validation_html(self):
        """
        GIVEN: HTML format specified
        WHEN: export format is validated
        THEN: Should accept HTML
        """
        result = await email_export_folder(
            folder='INBOX',
            server='imap.example.com',
            format='html',
            username='test@example.com',
            password='password'
        )
        
        # Will fail connection but format validation should pass
        assert 'Format must be' not in result.get('error', '')
    
    @pytest.mark.anyio
    async def test_format_validation_csv(self):
        """
        GIVEN: CSV format specified
        WHEN: export format is validated
        THEN: Should accept CSV
        """
        result = await email_export_folder(
            folder='INBOX',
            server='imap.example.com',
            format='csv',
            username='test@example.com',
            password='password'
        )
        
        # Will fail connection but format validation should pass
        assert 'Format must be' not in result.get('error', '')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
