"""
Tests for CEC Logic CLI Integration

Tests command-line interface for CEC logic operations including parsing,
proving, and analysis with multi-language support.
"""

import pytest
import sys


class TestLogicCLIParseCommand:
    """Test logic parse CLI command (4 tests)"""
    
    def test_parse_basic_text(self):
        """Test parse command with English text"""
        from scripts.cli.logic_cli import parse_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['parse', 'The agent must obey'])
        result = parse_command(args)
        assert result is not None
    
    def test_parse_with_language_flag(self):
        """Test parse command with language flag"""
        from scripts.cli.logic_cli import parse_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['parse', 'El agente', '--language', 'es'])
        result = parse_command(args)
        assert result is not None
    
    def test_parse_with_domain_flag(self):
        """Test parse with domain flag"""
        from scripts.cli.logic_cli import parse_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['parse', 'contract', '--domain', 'legal'])
        result = parse_command(args)
        assert result is not None
    
    def test_parse_json_output(self):
        """Test parse with JSON output format"""
        from scripts.cli.logic_cli import parse_command, create_parser, format_output
        parser = create_parser()
        args = parser.parse_args(['parse', 'test', '--format', 'json'])
        result = parse_command(args)
        output = format_output(result, 'json')
        assert output is not None


class TestLogicCLIProveCommand:
    """Test logic prove CLI command (4 tests)"""
    
    def test_prove_simple_formula(self):
        """Test prove command"""
        from scripts.cli.logic_cli import prove_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['prove', 'P(x)|~P(x)'])
        result = prove_command(args)
        assert result is not None
    
    def test_prove_with_axioms(self):
        """Test prove with axioms"""
        from scripts.cli.logic_cli import prove_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['prove', 'Q(x)', '--axioms', 'P(x),P(x)->Q(x)'])
        result = prove_command(args)
        assert result is not None
    
    def test_prove_with_strategy(self):
        """Test prove with strategy flag"""
        from scripts.cli.logic_cli import prove_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['prove', 'P(x)->P(x)', '--strategy', 'z3'])
        result = prove_command(args)
        assert result is not None
    
    def test_prove_with_timeout(self):
        """Test prove with timeout flag"""
        from scripts.cli.logic_cli import prove_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['prove', 'P(x)', '--timeout', '5'])
        result = prove_command(args)
        assert result is not None


class TestLogicCLIAnalyzeCommand:
    """Test logic analyze CLI command (2 tests)"""
    
    def test_analyze_simple(self):
        """Test analyze command"""
        from scripts.cli.logic_cli import analyze_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['analyze', 'P(x)'])
        result = analyze_command(args)
        assert result is not None
    
    def test_analyze_complex(self):
        """Test analyze complex formula"""
        from scripts.cli.logic_cli import analyze_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['analyze', 'O(K(a,P(x)))'])
        result = analyze_command(args)
        assert result is not None


class TestLogicCLIMultiLanguageSupport:
    """Test multi-language CLI support (10 tests)"""
    
    def test_spanish_parse(self):
        """Test Spanish language parsing"""
        from scripts.cli.logic_cli import parse_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['parse', 'El agente debe', '-l', 'es'])
        result = parse_command(args)
        assert result is not None
    
    def test_french_parse(self):
        """Test French language parsing"""
        from scripts.cli.logic_cli import parse_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['parse', "L'agent doit", '-l', 'fr'])
        result = parse_command(args)
        assert result is not None
    
    def test_german_parse(self):
        """Test German language parsing"""
        from scripts.cli.logic_cli import parse_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['parse', 'Der Agent muss', '-l', 'de'])
        result = parse_command(args)
        assert result is not None
    
    def test_auto_detect_language(self):
        """Test auto language detection"""
        from scripts.cli.logic_cli import parse_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['parse', 'agent', '--language', 'auto'])
        result = parse_command(args)
        assert result is not None
    
    def test_spanish_legal_domain(self):
        """Test Spanish with legal domain"""
        from scripts.cli.logic_cli import parse_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['parse', 'contrato', '-l', 'es', '-d', 'legal'])
        result = parse_command(args)
        assert result is not None
    
    def test_french_medical_domain(self):
        """Test French with medical domain"""
        from scripts.cli.logic_cli import parse_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['parse', 'traitement', '-l', 'fr', '-d', 'medical'])
        result = parse_command(args)
        assert result is not None
    
    def test_german_technical_domain(self):
        """Test German with technical domain"""
        from scripts.cli.logic_cli import parse_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['parse', 'System', '-l', 'de', '-d', 'technical'])
        result = parse_command(args)
        assert result is not None
    
    def test_text_output_format(self):
        """Test text output format"""
        from scripts.cli.logic_cli import format_output
        result = {'success': True, 'formula': 'O(P(x))'}
        output = format_output(result, 'text')
        assert isinstance(output, str)
    
    def test_json_output_format(self):
        """Test JSON output format"""
        from scripts.cli.logic_cli import format_output
        import json
        result = {'success': True}
        output = format_output(result, 'json')
        parsed = json.loads(output)
        assert parsed == result
    
    def test_compact_output_format(self):
        """Test compact output format"""
        from scripts.cli.logic_cli import format_output
        import json
        result = {'success': True}
        output = format_output(result, 'compact')
        parsed = json.loads(output)
        assert '\n' not in output


class TestLogicCLIErrorHandling:
    """Test CLI error handling (10 tests)"""
    
    def test_parse_empty_text(self):
        """Test parse with empty text"""
        from scripts.cli.logic_cli import parse_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['parse', ''])
        result = parse_command(args)
        assert result is not None
    
    def test_prove_error_handling(self):
        """Test prove error handling"""
        from scripts.cli.logic_cli import prove_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['prove', 'P(x)'])
        result = prove_command(args)
        assert result is not None
    
    def test_invalid_command(self):
        """Test invalid command"""
        from scripts.cli.logic_cli import create_parser
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(['invalid'])
    
    def test_missing_argument(self):
        """Test missing required argument"""
        from scripts.cli.logic_cli import create_parser
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(['parse'])
    
    def test_profile_command(self):
        """Test profile command"""
        from scripts.cli.logic_cli import profile_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['profile', 'parse', 'O(P(x))', '-i', '5'])
        result = profile_command(args)
        assert result is not None
    
    def test_translate_command(self):
        """Test translate command"""
        from scripts.cli.logic_cli import translate_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['translate', 'O(P(x))', '--format', 'tptp'])
        result = translate_command(args)
        assert result is not None
    
    def test_validate_command(self):
        """Test validate command"""
        from scripts.cli.logic_cli import validate_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['validate', 'O(P(x))'])
        result = validate_command(args)
        assert result is not None
    
    def test_validate_invalid_formula(self):
        """Test validate with invalid formula"""
        from scripts.cli.logic_cli import validate_command, create_parser
        parser = create_parser()
        args = parser.parse_args(['validate', 'O((('])
        result = validate_command(args)
        assert result is not None
    
    def test_help_text(self):
        """Test help text availability"""
        from scripts.cli.logic_cli import create_parser
        parser = create_parser()
        help_text = parser.format_help()
        assert 'parse' in help_text
        assert 'prove' in help_text
    
    def test_workflow_integration(self):
        """Test parse then validate workflow"""
        from scripts.cli.logic_cli import parse_command, validate_command, create_parser
        parser = create_parser()
        parse_args = parser.parse_args(['parse', 'agent'])
        parse_result = parse_command(parse_args)
        assert parse_result is not None
        if parse_result.get('formula'):
            val_args = parser.parse_args(['validate', parse_result['formula']])
            val_result = validate_command(val_args)
            assert val_result is not None
