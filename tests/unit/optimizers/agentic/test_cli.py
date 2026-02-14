"""Test suite for CLI commands."""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call
import tempfile

from ipfs_datasets_py.optimizers.agentic.cli import OptimizerCLI


class TestOptimizerCLI:
    """Test OptimizerCLI class."""
    
    @pytest.fixture
    def cli(self, tmp_path):
        """Create CLI instance with temp config."""
        config_file = tmp_path / ".optimizer-config.json"
        cli = OptimizerCLI(config_file=str(config_file))
        return cli
    
    def test_init(self, tmp_path):
        """Test CLI initialization."""
        config_file = tmp_path / "test_config.json"
        cli = OptimizerCLI(config_file=str(config_file))
        
        assert cli.config_file == str(config_file)
        assert isinstance(cli.config, dict)
    
    def test_load_config_default(self, cli):
        """Test loading default configuration."""
        cli.load_config()
        
        assert "change_control" in cli.config
        assert "validation_level" in cli.config
        assert "max_agents" in cli.config
    
    def test_load_config_existing(self, tmp_path):
        """Test loading existing configuration."""
        config_file = tmp_path / "existing_config.json"
        config_data = {
            "change_control": "github",
            "validation_level": "strict",
            "max_agents": 10,
        }
        with open(config_file, 'w') as f:
            json.dump(config_data, f)
        
        cli = OptimizerCLI(config_file=str(config_file))
        
        assert cli.config["change_control"] == "github"
        assert cli.config["validation_level"] == "strict"
        assert cli.config["max_agents"] == 10
    
    def test_save_config(self, cli, tmp_path):
        """Test saving configuration."""
        cli.config["test_key"] = "test_value"
        cli.save_config()
        
        # Verify file was created
        config_file = Path(cli.config_file)
        assert config_file.exists()
        
        # Load and verify content
        with open(config_file) as f:
            data = json.load(f)
        
        assert data["test_key"] == "test_value"
    
    def test_cmd_optimize(self, cli):
        """Test optimize command."""
        args = Mock()
        args.method = "test_driven"
        args.target = "test.py"
        args.description = "Test optimization"
        args.priority = 50
        args.dry_run = False
        
        with patch.object(cli, '_create_optimizer') as mock_optimizer:
            mock_optimizer.return_value = Mock()
            mock_optimizer.return_value.optimize.return_value = Mock(success=True)
            
            cli.cmd_optimize(args)
        
        assert mock_optimizer.called
    
    def test_cmd_optimize_dry_run(self, cli):
        """Test optimize command with dry run."""
        args = Mock()
        args.method = "adversarial"
        args.target = "module.py"
        args.description = "Dry run test"
        args.priority = 60
        args.dry_run = True
        
        with patch('builtins.print') as mock_print:
            cli.cmd_optimize(args)
        
        # Should print dry run message
        mock_print.assert_any_call("🏃 Dry run mode enabled - no changes will be made")
    
    def test_cmd_agents_list(self, cli):
        """Test agents list command."""
        args = Mock()
        
        with patch.object(cli, '_get_active_agents') as mock_agents:
            mock_agents.return_value = [
                {"id": "agent-1", "status": "running", "task": "optimize"},
                {"id": "agent-2", "status": "idle", "task": None},
            ]
            
            with patch('builtins.print'):
                cli.cmd_agents_list(args)
        
        mock_agents.assert_called_once()
    
    def test_cmd_agents_status(self, cli):
        """Test agents status command."""
        args = Mock()
        args.agent_id = "agent-123"
        
        with patch.object(cli, '_get_agent_status') as mock_status:
            mock_status.return_value = {
                "id": "agent-123",
                "status": "running",
                "tasks_completed": 5,
                "tasks_failed": 1,
            }
            
            with patch('builtins.print'):
                cli.cmd_agents_status(args)
        
        mock_status.assert_called_with("agent-123")
    
    def test_cmd_queue_process(self, cli):
        """Test queue process command."""
        args = Mock()
        
        with patch.object(cli, '_process_queue') as mock_process:
            mock_process.return_value = {"processed": 3, "failed": 0}
            
            cli.cmd_queue_process(args)
        
        mock_process.assert_called_once()
    
    def test_cmd_stats(self, cli):
        """Test stats command."""
        args = Mock()
        
        with patch.object(cli, '_get_statistics') as mock_stats:
            mock_stats.return_value = {
                "total_optimizations": 10,
                "successful": 8,
                "failed": 2,
                "completion_rate": 0.8,
            }
            
            with patch('builtins.print'):
                cli.cmd_stats(args)
        
        mock_stats.assert_called_once()
    
    def test_cmd_rollback(self, cli):
        """Test rollback command."""
        args = Mock()
        args.patch_id = "patch-123"
        args.force = True
        
        with patch.object(cli, '_rollback_patch') as mock_rollback:
            mock_rollback.return_value = True
            
            cli.cmd_rollback(args)
        
        mock_rollback.assert_called_with("patch-123")
    
    def test_cmd_rollback_no_force(self, cli):
        """Test rollback requires force flag."""
        args = Mock()
        args.patch_id = "patch-123"
        args.force = False
        
        with patch('builtins.print') as mock_print:
            cli.cmd_rollback(args)
        
        # Should print warning about force flag
        assert any("--force" in str(call) for call in mock_print.call_args_list)
    
    def test_cmd_config_show(self, cli):
        """Test config show command."""
        args = Mock()
        args.action = "show"
        args.key = None
        args.value = None
        
        cli.config = {"test": "value"}
        
        with patch('builtins.print') as mock_print:
            cli.cmd_config(args)
        
        # Should print config
        assert mock_print.called
    
    def test_cmd_config_set(self, cli):
        """Test config set command."""
        args = Mock()
        args.action = "set"
        args.key = "max_agents"
        args.value = "10"
        
        cli.cmd_config(args)
        
        assert cli.config["max_agents"] == "10"
    
    def test_cmd_config_reset(self, cli):
        """Test config reset command."""
        args = Mock()
        args.action = "reset"
        args.key = None
        args.value = None
        
        # Modify config
        cli.config["test"] = "modified"
        
        cli.cmd_config(args)
        
        # Should be back to defaults
        assert "test" not in cli.config
        assert "change_control" in cli.config
    
    def test_cmd_validate(self, cli):
        """Test validate command."""
        args = Mock()
        args.file = "test.py"
        args.level = "standard"
        
        with patch.object(cli, '_validate_file') as mock_validate:
            mock_validate.return_value = Mock(passed=True)
            
            cli.cmd_validate(args)
        
        mock_validate.assert_called_with("test.py", "standard")
    
    def test_create_optimizer(self, cli):
        """Test creating optimizer instance."""
        with patch('ipfs_datasets_py.optimizers.agentic.llm_integration.OptimizerLLMRouter'):
            with patch('ipfs_datasets_py.optimizers.agentic.methods.TestDrivenOptimizer'):
                optimizer = cli._create_optimizer("test_driven")
        
        assert optimizer is not None
    
    def test_create_optimizer_invalid_method(self, cli):
        """Test creating optimizer with invalid method."""
        with pytest.raises(ValueError):
            cli._create_optimizer("invalid_method")
    
    def test_validate_file_valid(self, cli, tmp_path):
        """Test validating valid file."""
        test_file = tmp_path / "valid.py"
        test_file.write_text("def test(): return 42")
        
        with patch('ipfs_datasets_py.optimizers.agentic.validation.OptimizationValidator'):
            result = cli._validate_file(str(test_file), "basic")
        
        # Should complete without error
        assert True
    
    def test_get_statistics(self, cli):
        """Test getting statistics."""
        stats = cli._get_statistics()
        
        assert isinstance(stats, dict)
        # Should have basic stats even if empty
    
    def test_get_active_agents(self, cli):
        """Test getting active agents."""
        agents = cli._get_active_agents()
        
        assert isinstance(agents, list)
    
    def test_config_validation_level_values(self, cli):
        """Test validation level configuration."""
        valid_levels = ["basic", "standard", "strict", "paranoid"]
        
        for level in valid_levels:
            cli.config["validation_level"] = level
            cli.save_config()
            
            # Should save without error
            assert cli.config["validation_level"] == level
    
    def test_config_change_control_values(self, cli):
        """Test change control configuration."""
        valid_controls = ["patch", "github"]
        
        for control in valid_controls:
            cli.config["change_control"] = control
            cli.save_config()
            
            assert cli.config["change_control"] == control


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
