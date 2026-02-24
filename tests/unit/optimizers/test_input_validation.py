"""
Comprehensive test suite for input validation and sanitization.

Tests cover:
    - Text sanitization (XSS, length limits)
    - SQL injection detection
    - Identifier validation
    - Path validation and traversal prevention
    - Entity and relationship validation
    - Confidence score validation
    - List size validation
    - JSON depth validation
    - Command injection detection
    - Convenience functions
"""

import pytest
from pathlib import Path
from ipfs_datasets_py.optimizers.security.input_validation import (
    InputValidator,
    EntityValidator,
    RelationshipValidator,
    ValidationError,
    ValidationLevel,
    ValidationResult,
    validate_and_sanitize_text,
    validate_identifier_safe,
    MAX_TEXT_LENGTH,
    MAX_ENTITY_TEXT_LENGTH,
    MAX_IDENTIFIER_LENGTH,
    MAX_LIST_SIZE,
    MAX_JSON_DEPTH,
)


class TestInputValidator:
    """Test suite for InputValidator class."""
    
    def test_sanitize_text_simple(self):
        """Test basic text sanitization."""
        validator = InputValidator()
        result = validator.sanitize_text("Hello World")
        assert result == "Hello World"
    
    def test_sanitize_text_removes_script_tags(self):
        """Test removal of script tags."""
        validator = InputValidator()
        result = validator.sanitize_text("User <script>alert('xss')</script> input")
        assert "<script>" not in result
        assert "alert" not in result
    
    def test_sanitize_text_removes_javascript_protocol(self):
        """Test removal of javascript: protocol."""
        validator = InputValidator()
        result = validator.sanitize_text("Click <a href='javascript:alert(1)'>here</a>")
        assert "javascript:" not in result
    
    def test_sanitize_text_removes_event_handlers(self):
        """Test removal of event handler attributes."""
        validator = InputValidator()
        result = validator.sanitize_text("<div onclick='malicious()'>Click</div>")
        assert "onclick=" not in result.lower()
    
    def test_sanitize_text_removes_iframe(self):
        """Test removal of iframe tags."""
        validator = InputValidator()
        result = validator.sanitize_text("<iframe src='evil.com'></iframe>")
        assert "<iframe" not in result.lower()
    
    def test_sanitize_text_html_escapes_special_chars(self):
        """Test HTML entity encoding."""
        validator = InputValidator()
        result = validator.sanitize_text("<>&\"'")
        assert "&lt;" in result
        assert "&gt;" in result
        assert "&amp;" in result
    
    def test_sanitize_text_max_length_enforced(self):
        """Test maximum length enforcement."""
        validator = InputValidator()
        long_text = "a" * (MAX_TEXT_LENGTH + 1)
        with pytest.raises(ValidationError, match="exceeds maximum length"):
            validator.sanitize_text(long_text)
    
    def test_sanitize_text_custom_max_length(self):
        """Test custom maximum length."""
        validator = InputValidator()
        with pytest.raises(ValidationError):
            validator.sanitize_text("a" * 101, max_length=100)
    
    def test_sanitize_text_non_string_raises_error(self):
        """Test non-string input raises error."""
        validator = InputValidator()
        with pytest.raises(ValidationError, match="Expected string"):
            validator.sanitize_text(12345)
    
    def test_sanitize_text_none_raises_error(self):
        """Test None input raises error."""
        validator = InputValidator()
        with pytest.raises(ValidationError):
            validator.sanitize_text(None)
    
    def test_check_sql_injection_union_select(self):
        """Test detection of UNION SELECT attack."""
        validator = InputValidator()
        result = validator.check_sql_injection("1' UNION SELECT username FROM users--")
        assert not result.valid
        assert "SQL injection" in result.errors[0]
    
    def test_check_sql_injection_drop_table(self):
        """Test detection of DROP TABLE attack."""
        validator = InputValidator()
        result = validator.check_sql_injection("'; DROP TABLE users; --")
        assert not result.valid
    
    def test_check_sql_injection_insert_into(self):
        """Test detection of INSERT INTO attack."""
        validator = InputValidator()
        result = validator.check_sql_injection("admin'; INSERT INTO users VALUES('hacker')--")
        assert not result.valid
    
    def test_check_sql_injection_delete_from(self):
        """Test detection of DELETE FROM attack."""
        validator = InputValidator()
        result = validator.check_sql_injection("'; DELETE FROM users WHERE 1=1--")
        assert not result.valid
    
    def test_check_sql_injection_or_condition(self):
        """Test detection of OR 1=1 attack."""
        validator = InputValidator()
        result = validator.check_sql_injection("admin' OR 1=1--")
        assert not result.valid
    
    def test_check_sql_injection_and_condition(self):
        """Test detection of AND 1=1 attack."""
        validator = InputValidator()
        result = validator.check_sql_injection("' AND 1=1--")
        assert not result.valid
    
    def test_check_sql_injection_exec_function(self):
        """Test detection of EXEC function attack."""
        validator = InputValidator()
        result = validator.check_sql_injection("'; EXEC sp_executesql--")
        assert not result.valid
    
    def test_check_sql_injection_clean_text(self):
        """Test clean text passes validation."""
        validator = InputValidator()
        result = validator.check_sql_injection("This is a normal comment")
        assert result.valid
        assert result.sanitized_value == "This is a normal comment"
    
    def test_validate_identifier_valid(self):
        """Test valid identifier."""
        validator = InputValidator()
        result = validator.validate_identifier("entity_id_123")
        assert result.valid
        assert result.sanitized_value == "entity_id_123"
    
    def test_validate_identifier_with_dots_and_dashes(self):
        """Test identifier with dots and dashes."""
        validator = InputValidator()
        result = validator.validate_identifier("my-entity.v2")
        assert result.valid
    
    def test_validate_identifier_empty_string(self):
        """Test empty identifier fails."""
        validator = InputValidator()
        result = validator.validate_identifier("")
        assert not result.valid
        assert "cannot be empty" in result.errors[0]
    
    def test_validate_identifier_too_long(self):
        """Test identifier exceeding max length."""
        validator = InputValidator()
        long_id = "a" * (MAX_IDENTIFIER_LENGTH + 1)
        result = validator.validate_identifier(long_id)
        assert not result.valid
        assert "exceeds maximum length" in result.errors[0]
    
    def test_validate_identifier_invalid_characters(self):
        """Test identifier with invalid characters."""
        validator = InputValidator()
        result = validator.validate_identifier("entity@id#123")
        assert not result.valid
        assert "invalid characters" in result.errors[0]
    
    def test_validate_identifier_spaces_not_allowed(self):
        """Test identifier with spaces fails."""
        validator = InputValidator()
        result = validator.validate_identifier("entity id 123")
        assert not result.valid
    
    def test_validate_identifier_non_string(self):
        """Test non-string identifier fails."""
        validator = InputValidator()
        result = validator.validate_identifier(12345)
        assert not result.valid
        assert "must be string" in result.errors[0]
    
    def test_validate_path_safe_relative(self):
        """Test safe relative path."""
        validator = InputValidator()
        result = validator.validate_path("data/entities.json")
        assert result.valid
    
    def test_validate_path_traversal_detected_dots_slash(self):
        """Test path traversal with ../ detected."""
        validator = InputValidator()
        result = validator.validate_path("../../etc/passwd")
        assert not result.valid
        assert "traversal" in result.errors[0]
    
    def test_validate_path_traversal_detected_dots_backslash(self):
        """Test path traversal with ..\\ detected."""
        validator = InputValidator()
        result = validator.validate_path("..\\..\\windows\\system32")
        assert not result.valid
        assert "traversal" in result.errors[0]
    
    def test_validate_path_absolute_path_warning(self):
        """Test absolute path generates warning."""
        validator = InputValidator()
        result = validator.validate_path("/tmp/data.json")
        assert result.valid
        assert len(result.warnings) > 0
    
    def test_validate_path_allowed_base_within_directory(self, tmp_path):
        """Test path validation within allowed directory."""
        validator = InputValidator()
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        file_path = allowed_dir / "data.json"
        
        result = validator.validate_path(file_path, allowed_base=allowed_dir)
        assert result.valid
    
    def test_validate_path_allowed_base_outside_directory(self, tmp_path):
        """Test path validation outside allowed directory fails."""
        validator = InputValidator()
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        outside_path = tmp_path / "outside" / "data.json"
        
        result = validator.validate_path(outside_path, allowed_base=allowed_dir)
        assert not result.valid
        assert "must be within" in result.errors[0]

    def test_validate_path_returns_error_on_typed_resolve_failure(self, monkeypatch):
        """Typed path resolution failures should produce validation errors."""
        validator = InputValidator()
        real_resolve = Path.resolve

        def _raise_oserror(self, *args, **kwargs):
            if str(self) == "bad/path":
                raise OSError("broken path")
            return real_resolve(self, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", _raise_oserror)
        result = validator.validate_path("bad/path")
        assert not result.valid
        assert "Invalid path" in result.errors[0]

    def test_validate_path_propagates_base_exception(self, monkeypatch):
        """Base exceptions must not be swallowed by path validation fallback."""
        validator = InputValidator()
        real_resolve = Path.resolve

        def _raise_interrupt(self, *args, **kwargs):
            if str(self) == "interrupt/path":
                raise KeyboardInterrupt("stop")
            return real_resolve(self, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", _raise_interrupt)
        with pytest.raises(KeyboardInterrupt):
            validator.validate_path("interrupt/path")
    
    def test_validate_entity_text_valid(self):
        """Test valid entity text."""
        validator = InputValidator()
        result = validator.validate_entity_text("Valid entity name")
        assert result.valid
    
    def test_validate_entity_text_empty_fails(self):
        """Test empty entity text fails."""
        validator = InputValidator()
        result = validator.validate_entity_text("")
        assert not result.valid
        assert "cannot be empty" in result.errors[0]
    
    def test_validate_entity_text_too_long(self):
        """Test entity text exceeding max length."""
        validator = InputValidator()
        long_text = "a" * (MAX_ENTITY_TEXT_LENGTH + 1)
        result = validator.validate_entity_text(long_text)
        assert not result.valid
    
    def test_validate_entity_text_with_sql_injection(self):
        """Test entity text with SQL injection fails."""
        validator = InputValidator()
        result = validator.validate_entity_text("name' OR 1=1--")
        assert not result.valid
    
    def test_validate_entity_text_sanitized_warning(self):
        """Test entity text sanitization generates warning."""
        validator = InputValidator()
        result = validator.validate_entity_text("Entity <b>name</b>")
        assert result.valid
        assert len(result.warnings) > 0
    
    def test_validate_entity_text_non_string(self):
        """Test non-string entity text fails."""
        validator = InputValidator()
        result = validator.validate_entity_text(12345)
        assert not result.valid
    
    def test_validate_confidence_valid_float(self):
        """Test valid confidence score."""
        validator = InputValidator()
        result = validator.validate_confidence(0.85)
        assert result.valid
        assert result.sanitized_value == 0.85
    
    def test_validate_confidence_valid_int(self):
        """Test valid integer confidence."""
        validator = InputValidator()
        result = validator.validate_confidence(1)
        assert result.valid
        assert result.sanitized_value == 1.0
    
    def test_validate_confidence_zero(self):
        """Test confidence of 0.0 is valid."""
        validator = InputValidator()
        result = validator.validate_confidence(0.0)
        assert result.valid
    
    def test_validate_confidence_one(self):
        """Test confidence of 1.0 is valid."""
        validator = InputValidator()
        result = validator.validate_confidence(1.0)
        assert result.valid
    
    def test_validate_confidence_negative_fails(self):
        """Test negative confidence fails."""
        validator = InputValidator()
        result = validator.validate_confidence(-0.5)
        assert not result.valid
        assert "between 0.0 and 1.0" in result.errors[0]
    
    def test_validate_confidence_greater_than_one_fails(self):
        """Test confidence > 1.0 fails."""
        validator = InputValidator()
        result = validator.validate_confidence(1.5)
        assert not result.valid
    
    def test_validate_confidence_non_numeric(self):
        """Test non-numeric confidence fails."""
        validator = InputValidator()
        result = validator.validate_confidence("0.85")
        assert not result.valid
        assert "must be numeric" in result.errors[0]
    
    def test_validate_list_size_valid(self):
        """Test valid list size."""
        validator = InputValidator()
        result = validator.validate_list_size([1, 2, 3, 4, 5])
        assert result.valid
    
    def test_validate_list_size_at_max(self):
        """Test list at maximum size."""
        validator = InputValidator()
        max_list = list(range(MAX_LIST_SIZE))
        result = validator.validate_list_size(max_list)
        assert result.valid
    
    def test_validate_list_size_exceeds_max(self):
        """Test list exceeding maximum size."""
        validator = InputValidator()
        oversized_list = list(range(MAX_LIST_SIZE + 1))
        result = validator.validate_list_size(oversized_list)
        assert not result.valid
        assert "exceeds maximum" in result.errors[0]
    
    def test_validate_list_size_custom_max(self):
        """Test custom maximum list size."""
        validator = InputValidator()
        result = validator.validate_list_size([1, 2, 3, 4, 5], max_size=3)
        assert not result.valid
    
    def test_validate_list_size_non_list(self):
        """Test non-list input fails."""
        validator = InputValidator()
        result = validator.validate_list_size("not a list")
        assert not result.valid
        assert "Expected list" in result.errors[0]
    
    def test_validate_json_depth_shallow(self):
        """Test shallow JSON structure."""
        validator = InputValidator()
        data = {"key": "value", "num": 123}
        result = validator.validate_json_depth(data)
        assert result.valid
    
    def test_validate_json_depth_nested_dict(self):
        """Test nested dictionary within limits."""
        validator = InputValidator()
        data = {"level1": {"level2": {"level3": "value"}}}
        result = validator.validate_json_depth(data)
        assert result.valid
    
    def test_validate_json_depth_nested_list(self):
        """Test nested list within limits."""
        validator = InputValidator()
        data = [[[["deep"]]]]
        result = validator.validate_json_depth(data)
        assert result.valid
    
    def test_validate_json_depth_exceeds_max(self):
        """Test JSON exceeding max depth."""
        validator = InputValidator()
        # Create deeply nested structure
        data = {"level": "value"}
        for i in range(MAX_JSON_DEPTH + 2):
            data = {"nested": data}
        
        result = validator.validate_json_depth(data)
        assert not result.valid
        assert "depth" in result.errors[0]
    
    def test_validate_json_depth_custom_max(self):
        """Test custom maximum depth."""
        validator = InputValidator()
        data = {"a": {"b": {"c": "too deep"}}}
        result = validator.validate_json_depth(data, max_depth=2)
        assert not result.valid
    
    def test_validate_command_input_safe(self):
        """Test safe command input."""
        validator = InputValidator()
        result = validator.validate_command_input("ls -la")
        assert result.valid
    
    def test_validate_command_input_semicolon(self):
        """Test command with semicolon fails."""
        validator = InputValidator()
        result = validator.validate_command_input("ls; rm -rf /")
        assert not result.valid
        assert "command injection" in result.errors[0]
    
    def test_validate_command_input_pipe(self):
        """Test command with pipe fails."""
        validator = InputValidator()
        result = validator.validate_command_input("cat file | evil_command")
        assert not result.valid
    
    def test_validate_command_input_ampersand(self):
        """Test command with ampersand fails."""
        validator = InputValidator()
        result = validator.validate_command_input("cmd1 & cmd2")
        assert not result.valid
    
    def test_validate_command_input_command_substitution(self):
        """Test command substitution fails."""
        validator = InputValidator()
        result = validator.validate_command_input("echo $(malicious)")
        assert not result.valid
    
    def test_validate_command_input_redirection(self):
        """Test file redirection fails."""
        validator = InputValidator()
        result = validator.validate_command_input("echo test > /etc/passwd")
        assert not result.valid


class TestEntityValidator:
    """Test suite for EntityValidator class."""
    
    def test_validate_entity_all_required_fields(self):
        """Test entity with all required fields."""
        validator = EntityValidator()
        entity = {"text": "Entity name", "type": "PERSON"}
        result = validator.validate_entity(entity)
        assert result.valid
        assert result.sanitized_value["text"] == "Entity name"
        assert result.sanitized_value["type"] == "PERSON"
    
    def test_validate_entity_with_confidence(self):
        """Test entity with confidence field."""
        validator = EntityValidator()
        entity = {"text": "Entity name", "type": "PERSON", "confidence": 0.95}
        result = validator.validate_entity(entity)
        assert result.valid
        assert result.sanitized_value["confidence"] == 0.95
    
    def test_validate_entity_with_context(self):
        """Test entity with context field."""
        validator = EntityValidator()
        entity = {
            "text": "Entity name",
            "type": "PERSON",
            "context": "Additional context information"
        }
        result = validator.validate_entity(entity)
        assert result.valid
        assert "context" in result.sanitized_value
    
    def test_validate_entity_missing_text(self):
        """Test entity missing required text field."""
        validator = EntityValidator()
        entity = {"type": "PERSON"}
        result = validator.validate_entity(entity)
        assert not result.valid
        assert any("text" in error for error in result.errors)
    
    def test_validate_entity_missing_type(self):
        """Test entity missing required type field."""
        validator = EntityValidator()
        entity = {"text": "Entity name"}
        result = validator.validate_entity(entity)
        assert not result.valid
        assert any("type" in error for error in result.errors)
    
    def test_validate_entity_invalid_confidence(self):
        """Test entity with invalid confidence."""
        validator = EntityValidator()
        entity = {"text": "Entity", "type": "PERSON", "confidence": 1.5}
        result = validator.validate_entity(entity)
        assert not result.valid
    
    def test_validate_entity_invalid_type_identifier(self):
        """Test entity with invalid type format."""
        validator = EntityValidator()
        entity = {"text": "Entity", "type": "PERSON@INVALID"}
        result = validator.validate_entity(entity)
        assert not result.valid


class TestRelationshipValidator:
    """Test suite for RelationshipValidator class."""
    
    def test_validate_relationship_all_required_fields(self):
        """Test relationship with all required fields."""
        validator = RelationshipValidator()
        rel = {"source": "entity1", "target": "entity2", "type": "RELATED_TO"}
        result = validator.validate_relationship(rel)
        assert result.valid
        assert result.sanitized_value["source"] == "entity1"
        assert result.sanitized_value["target"] == "entity2"
        assert result.sanitized_value["type"] == "RELATED_TO"
    
    def test_validate_relationship_with_confidence(self):
        """Test relationship with confidence field."""
        validator = RelationshipValidator()
        rel = {
            "source": "entity1",
            "target": "entity2",
            "type": "RELATED_TO",
            "confidence": 0.9
        }
        result = validator.validate_relationship(rel)
        assert result.valid
        assert result.sanitized_value["confidence"] == 0.9
    
    def test_validate_relationship_missing_source(self):
        """Test relationship missing source field."""
        validator = RelationshipValidator()
        rel = {"target": "entity2", "type": "RELATED_TO"}
        result = validator.validate_relationship(rel)
        assert not result.valid
        assert any("source" in error for error in result.errors)
    
    def test_validate_relationship_missing_target(self):
        """Test relationship missing target field."""
        validator = RelationshipValidator()
        rel = {"source": "entity1", "type": "RELATED_TO"}
        result = validator.validate_relationship(rel)
        assert not result.valid
        assert any("target" in error for error in result.errors)
    
    def test_validate_relationship_missing_type(self):
        """Test relationship missing type field."""
        validator = RelationshipValidator()
        rel = {"source": "entity1", "target": "entity2"}
        result = validator.validate_relationship(rel)
        assert not result.valid
        assert any("type" in error for error in result.errors)
    
    def test_validate_relationship_invalid_source_identifier(self):
        """Test relationship with invalid source identifier."""
        validator = RelationshipValidator()
        rel = {"source": "entity@invalid", "target": "entity2", "type": "RELATED_TO"}
        result = validator.validate_relationship(rel)
        assert not result.valid
    
    def test_validate_relationship_invalid_confidence(self):
        """Test relationship with invalid confidence."""
        validator = RelationshipValidator()
        rel = {
            "source": "entity1",
            "target": "entity2",
            "type": "RELATED_TO",
            "confidence": -0.5
        }
        result = validator.validate_relationship(rel)
        assert not result.valid


class TestConvenienceFunctions:
    """Test suite for convenience validation functions."""
    
    def test_validate_and_sanitize_text_clean(self):
        """Test sanitizing clean text."""
        result = validate_and_sanitize_text("Clean text")
        assert result == "Clean text"
    
    def test_validate_and_sanitize_text_with_xss(self):
        """Test sanitizing text with XSS."""
        result = validate_and_sanitize_text("Text <script>alert('xss')</script>")
        assert "<script>" not in result
    
    def test_validate_and_sanitize_text_custom_max_length(self):
        """Test custom max length."""
        with pytest.raises(ValidationError):
            validate_and_sanitize_text("a" * 101, max_length=100)
    
    def test_validate_identifier_safe_valid(self):
        """Test valid identifier returns True."""
        assert validate_identifier_safe("valid_identifier_123") is True
    
    def test_validate_identifier_safe_invalid(self):
        """Test invalid identifier returns False."""
        assert validate_identifier_safe("invalid@identifier") is False
    
    def test_validate_identifier_safe_empty(self):
        """Test empty identifier returns False."""
        assert validate_identifier_safe("") is False


class TestValidationLevel:
    """Test validation strictness levels."""
    
    def test_validator_with_strict_level(self):
        """Test validator with strict level."""
        validator = InputValidator(validation_level=ValidationLevel.STRICT)
        assert validator.validation_level == ValidationLevel.STRICT
    
    def test_validator_with_moderate_level(self):
        """Test validator with moderate level."""
        validator = InputValidator(validation_level=ValidationLevel.MODERATE)
        assert validator.validation_level == ValidationLevel.MODERATE
    
    def test_validator_with_permissive_level(self):
        """Test validator with permissive level."""
        validator = InputValidator(validation_level=ValidationLevel.PERMISSIVE)
        assert validator.validation_level == ValidationLevel.PERMISSIVE


class TestValidationResult:
    """Test ValidationResult dataclass."""
    
    def test_validation_result_defaults(self):
        """Test ValidationResult with default values."""
        result = ValidationResult(valid=True)
        assert result.valid is True
        assert result.sanitized_value is None
        assert result.errors == []
        assert result.warnings == []
    
    def test_validation_result_with_errors(self):
        """Test ValidationResult with errors."""
        result = ValidationResult(valid=False, errors=["Error 1", "Error 2"])
        assert not result.valid
        assert len(result.errors) == 2
    
    def test_validation_result_with_warnings(self):
        """Test ValidationResult with warnings."""
        result = ValidationResult(valid=True, warnings=["Warning 1"])
        assert result.valid
        assert len(result.warnings) == 1
    
    def test_validation_result_with_sanitized_value(self):
        """Test ValidationResult with sanitized value."""
        result = ValidationResult(valid=True, sanitized_value="cleaned text")
        assert result.sanitized_value == "cleaned text"
