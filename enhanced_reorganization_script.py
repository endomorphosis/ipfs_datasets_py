#!/usr/bin/env python3
"""
Enhanced Root Directory Reorganization Script
Implements comprehensive project structure optimization for IPFS Datasets MCP Server.

This script reorganizes the project directory to create a clean, maintainable structure
while preserving all development history and maintaining functionality.
"""

import os
import shutil
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Set, Dict, List, Tuple
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'reorganization_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ProjectReorganizer:
    """Handles comprehensive project directory reorganization."""
    
    def __init__(self, root_path: str = "."):
        self.root_path = Path(root_path).resolve()
        self.backup_path = None
        self.moved_files = {}
        self.errors = []
        
    def create_backup(self) -> bool:
        """Create a backup of the current project state."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.backup_path = self.root_path.parent / f"ipfs_datasets_py_backup_{timestamp}"
            
            logger.info(f"Creating backup at {self.backup_path}")
            shutil.copytree(self.root_path, self.backup_path)
            logger.info("✅ Backup created successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to create backup: {e}")
            return False
    
    def get_file_classifications(self) -> Dict[str, Set[str]]:
        """Classify all files in the root directory."""
        
        # Essential files that stay in root
        essential_root_files = {
            'README.md', 'LICENSE', 'requirements.txt', 'pyproject.toml', 
            'setup.py', 'Dockerfile', 'pytest.ini', 'uv.lock', '.gitignore',
            '__init__.py'
        }
        
        # Migration documentation patterns
        migration_doc_patterns = [
            'MCP_', 'COMPLETE_', 'FINAL_', 'MIGRATION_', 'RESTART_', 'SERVER_',
            'IMPLEMENTATION_', 'DOCUMENTATION_', 'PHASE', 'VERIFICATION_',
            'CLEANUP_', 'FFMPEG_', 'PDF_', 'YTDLP_', 'POST_'
        ]
        
        # Test file patterns  
        test_patterns = [
            'test_', 'comprehensive_', 'debug_', 'simple_', 'quick_', 'minimal_',
            'run_', 'validate_', 'check_', 'final_', 'direct_'
        ]
        
        # Script patterns
        script_patterns = [
            'fix_', 'verify_', 'install_', 'mcp_', 'dependency_', 'project_',
            'migration_', 'list_', 'server_'
        ]
        
        # Active examples to keep accessible
        active_examples = {
            'demo_multimedia_final.py',
            'validate_multimedia_simple.py', 
            'test_multimedia_comprehensive.py',
            'demo_mcp_server.py'
        }
        
        # Log and result files
        log_result_patterns = [
            '.log', '.json', '_output', '_results', '_status'
        ]
        
        # Scan root directory and classify files
        classifications = {
            'essential_root': set(),
            'migration_docs': set(),
            'development_tests': set(),
            'utility_scripts': set(),
            'active_examples': set(),
            'logs_results': set(),
            'unknown': set()
        }
        
        for item in self.root_path.iterdir():
            if item.is_file():
                filename = item.name
                
                # Skip hidden files and directories
                if filename.startswith('.') and filename not in essential_root_files:
                    continue
                    
                # Essential root files
                if filename in essential_root_files:
                    classifications['essential_root'].add(filename)
                
                # Active examples
                elif filename in active_examples:
                    classifications['active_examples'].add(filename)
                
                # Migration documentation
                elif (any(filename.startswith(pattern) for pattern in migration_doc_patterns) and 
                      filename.endswith('.md')):
                    classifications['migration_docs'].add(filename)
                
                # Test files
                elif (any(filename.startswith(pattern) for pattern in test_patterns) and 
                      filename.endswith('.py')):
                    classifications['development_tests'].add(filename)
                
                # Utility scripts
                elif (any(filename.startswith(pattern) for pattern in script_patterns) and 
                      filename.endswith('.py')):
                    classifications['utility_scripts'].add(filename)
                
                # Log and result files
                elif any(filename.endswith(pattern) for pattern in log_result_patterns):
                    classifications['logs_results'].add(filename)
                
                # Unknown files
                else:
                    classifications['unknown'].add(filename)
        
        return classifications
    
    def create_directory_structure(self) -> bool:
        """Create the new organized directory structure."""
        directories = [
            'archive/migration_docs',
            'archive/migration_tests', 
            'archive/migration_scripts',
            'archive/development_history',
            'archive/experiments',
            'docs/api',
            'docs/user_guides',
            'scripts/development',
            'scripts/testing',
            'scripts/deployment', 
            'scripts/maintenance',
            'examples/multimedia',
            'examples/mcp_tools',
            'examples/pdf_processing',
            'examples/integrations',
            'config/mcp_server',
            'config/development',
            'config/production'
        ]
        
        try:
            for directory in directories:
                dir_path = self.root_path / directory
                dir_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"📁 Created directory: {directory}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to create directory structure: {e}")
            return False
    
    def move_files(self, classifications: Dict[str, Set[str]]) -> bool:
        """Move files to their new locations."""
        
        # Define file movement mappings
        movement_mappings = [
            (classifications['migration_docs'], 'archive/migration_docs'),
            (classifications['development_tests'], 'archive/migration_tests'),
            (classifications['utility_scripts'], 'archive/migration_scripts'),
            (classifications['logs_results'], 'archive/development_history'),
            (classifications['active_examples'], 'examples')
        ]
        
        moved_count = 0
        
        for file_set, target_dir in movement_mappings:
            for filename in file_set:
                source_path = self.root_path / filename
                target_path = self.root_path / target_dir / filename
                
                if source_path.exists():
                    try:
                        shutil.move(str(source_path), str(target_path))
                        self.moved_files[filename] = target_dir
                        logger.info(f"📁 Moved {filename} → {target_dir}/")
                        moved_count += 1
                        
                    except Exception as e:
                        error_msg = f"Failed to move {filename}: {e}"
                        self.errors.append(error_msg)
                        logger.error(f"❌ {error_msg}")
        
        # Handle unknown files
        if classifications['unknown']:
            logger.warning(f"⚠️  Unknown files found: {classifications['unknown']}")
            for filename in classifications['unknown']:
                # Move unknown files to experiments directory for manual review
                source_path = self.root_path / filename
                target_path = self.root_path / 'archive' / 'experiments' / filename
                
                try:
                    shutil.move(str(source_path), str(target_path))
                    self.moved_files[filename] = 'archive/experiments'
                    logger.info(f"📁 Moved unknown file {filename} → archive/experiments/")
                    moved_count += 1
                    
                except Exception as e:
                    error_msg = f"Failed to move unknown file {filename}: {e}"
                    self.errors.append(error_msg)
                    logger.error(f"❌ {error_msg}")
        
        logger.info(f"✅ Moved {moved_count} files total")
        return len(self.errors) == 0
    
    def create_navigation_files(self) -> bool:
        """Create index and navigation files for the new structure."""
        try:
            # Create main project index
            main_index = """# IPFS Datasets MCP Server - Reorganized Structure

## 📁 Directory Structure

### Essential Files (Root)
- Core project configuration and documentation
- Only essential files remain in root directory

### 📚 Documentation (`docs/`)
- API documentation in `docs/api/`
- User guides in `docs/user_guides/`

### 🧪 Examples (`examples/`)
- Working examples and demonstrations
- Organized by feature area (multimedia, mcp_tools, etc.)

### 🔧 Scripts (`scripts/`)
- Development utilities in `scripts/development/`
- Testing scripts in `scripts/testing/`
- Deployment tools in `scripts/deployment/`
- Maintenance utilities in `scripts/maintenance/`

### 📦 Archive (`archive/`)
- Migration documentation in `archive/migration_docs/`
- Development tests in `archive/migration_tests/`
- Utility scripts in `archive/migration_scripts/`
- Historical logs in `archive/development_history/`
- Experimental code in `archive/experiments/`

### ⚙️ Configuration (`config/`)
- MCP server configs in `config/mcp_server/`
- Development settings in `config/development/`
- Production configs in `config/production/`

## 🚀 Quick Start

1. **Run the MCP Server**: See examples/mcp_tools/
2. **Test Multimedia Features**: See examples/multimedia/
3. **PDF Processing**: See examples/pdf_processing/
4. **Development**: See scripts/development/

## 📋 Migration Summary

This project was reorganized on {timestamp} to improve maintainability and navigation.
All files have been preserved and organized by purpose.
"""
            
            index_path = self.root_path / 'PROJECT_STRUCTURE.md'
            with open(index_path, 'w') as f:
                f.write(main_index.format(timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            
            # Create archive index
            archive_index = f"""# Archive Directory Index

This directory contains all files from the project reorganization completed on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}.

## 📁 Subdirectories

### migration_docs/
Migration-related documentation, reports, and guides created during development.

### migration_tests/ 
Test files, validation scripts, and diagnostic tools created during development.

### migration_scripts/
Utility scripts, fix tools, and maintenance scripts created during development.

### development_history/
Log files, result files, and build artifacts from the development process.

### experiments/
Experimental code and unknown files moved during reorganization for manual review.

## 🔍 Finding Files

All files have been preserved. If you're looking for a specific file:
1. Check the appropriate subdirectory based on file type
2. Use grep to search across all archive files
3. Refer to the reorganization log for exact file movements

## 📋 File Movement Log

Total files moved: {len(self.moved_files)}
Movement details available in reorganization log.
"""
            
            archive_index_path = self.root_path / 'archive' / 'README.md'
            with open(archive_index_path, 'w') as f:
                f.write(archive_index)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to create navigation files: {e}")
            return False
    
    def validate_reorganization(self) -> bool:
        """Validate that the reorganization was successful."""
        try:
            # Check that essential files are still in root
            essential_files = ['README.md', 'requirements.txt', 'pyproject.toml']
            for filename in essential_files:
                if not (self.root_path / filename).exists():
                    logger.error(f"❌ Essential file missing from root: {filename}")
                    return False
            
            # Check that source code directory is intact
            source_dir = self.root_path / 'ipfs_datasets_py'
            if not source_dir.exists():
                logger.error("❌ Source code directory missing")
                return False
            
            # Check that tests directory is intact
            tests_dir = self.root_path / 'tests'
            if not tests_dir.exists():
                logger.error("❌ Tests directory missing")
                return False
            
            # Count files in root directory
            root_files = [f for f in self.root_path.iterdir() if f.is_file()]
            if len(root_files) > 15:
                logger.warning(f"⚠️  Root directory still has {len(root_files)} files (target: ≤15)")
            else:
                logger.info(f"✅ Root directory cleaned: {len(root_files)} files")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Validation failed: {e}")
            return False
    
    def create_rollback_script(self) -> bool:
        """Create a script to rollback the reorganization if needed."""
        if not self.backup_path:
            return False
            
        rollback_script = f"""#!/usr/bin/env python3
\"\"\"
Rollback script for project reorganization.
Restores project state from backup created on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
\"\"\"

import shutil
import os
from pathlib import Path

def rollback():
    backup_path = Path("{self.backup_path}")
    current_path = Path("{self.root_path}")
    
    if not backup_path.exists():
        print("❌ Backup directory not found!")
        return False
    
    print("🔄 Rolling back project reorganization...")
    
    # Remove current directory contents (except .git)
    for item in current_path.iterdir():
        if item.name != '.git':
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    
    # Restore from backup
    for item in backup_path.iterdir():
        if item.name != '.git':
            if item.is_dir():
                shutil.copytree(item, current_path / item.name)
            else:
                shutil.copy2(item, current_path / item.name)
    
    print("✅ Rollback completed successfully")
    return True

if __name__ == "__main__":
    rollback()
"""
        
        try:
            rollback_path = self.root_path / 'rollback_reorganization.py'
            with open(rollback_path, 'w') as f:
                f.write(rollback_script)
            os.chmod(rollback_path, 0o755)
            logger.info("📜 Created rollback script: rollback_reorganization.py")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to create rollback script: {e}")
            return False
    
    def save_reorganization_report(self, classifications: Dict[str, Set[str]]) -> bool:
        """Save a detailed report of the reorganization."""
        try:
            report = {
                'timestamp': datetime.now().isoformat(),
                'backup_path': str(self.backup_path) if self.backup_path else None,
                'total_files_moved': len(self.moved_files),
                'file_movements': self.moved_files,
                'classifications': {k: list(v) for k, v in classifications.items()},
                'errors': self.errors,
                'success': len(self.errors) == 0
            }
            
            report_path = self.root_path / 'reorganization_report.json'
            with open(report_path, 'w') as f:
                json.dump(report, f, indent=2)
            
            logger.info("📊 Saved reorganization report: reorganization_report.json")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to save report: {e}")
            return False
    
    def run_reorganization(self) -> bool:
        """Execute the complete reorganization process."""
        logger.info("🚀 Starting Project Reorganization")
        logger.info("=" * 60)
        
        # Step 1: Create backup
        if not self.create_backup():
            logger.error("❌ Failed to create backup. Aborting reorganization.")
            return False
        
        # Step 2: Classify files
        logger.info("📋 Classifying files...")
        classifications = self.get_file_classifications()
        
        for category, files in classifications.items():
            if files:
                logger.info(f"  {category}: {len(files)} files")
        
        # Step 3: Create directory structure
        logger.info("📁 Creating directory structure...")
        if not self.create_directory_structure():
            logger.error("❌ Failed to create directory structure.")
            return False
        
        # Step 4: Move files
        logger.info("📦 Moving files...")
        if not self.move_files(classifications):
            logger.warning("⚠️  Some file movements failed. Check errors.")
        
        # Step 5: Create navigation files
        logger.info("📚 Creating navigation files...")
        if not self.create_navigation_files():
            logger.warning("⚠️  Failed to create some navigation files.")
        
        # Step 6: Create rollback script
        logger.info("🔄 Creating rollback script...")
        if not self.create_rollback_script():
            logger.warning("⚠️  Failed to create rollback script.")
        
        # Step 7: Validate reorganization
        logger.info("✅ Validating reorganization...")
        validation_success = self.validate_reorganization()
        
        # Step 8: Save report
        logger.info("📊 Saving reorganization report...")
        self.save_reorganization_report(classifications)
        
        # Final summary
        logger.info("=" * 60)
        if validation_success and len(self.errors) == 0:
            logger.info("🎉 PROJECT REORGANIZATION COMPLETED SUCCESSFULLY!")
            logger.info(f"📁 Files moved: {len(self.moved_files)}")
            logger.info(f"💾 Backup created: {self.backup_path}")
            logger.info("🔄 Rollback available: rollback_reorganization.py")
        else:
            logger.warning("⚠️  PROJECT REORGANIZATION COMPLETED WITH ISSUES")
            logger.warning(f"❌ Errors encountered: {len(self.errors)}")
            logger.warning("🔄 Use rollback_reorganization.py if needed")
        
        return validation_success and len(self.errors) == 0


def main():
    """Main function to run the reorganization."""
    print("🧹 IPFS Datasets MCP Server - Project Reorganization")
    print("=" * 60)
    print("This script will reorganize the project directory structure.")
    print("A backup will be created before any changes are made.")
    print("")
    
    response = input("Proceed with reorganization? (y/N): ").strip().lower()
    if response != 'y':
        print("❌ Reorganization cancelled.")
        return
    
    reorganizer = ProjectReorganizer()
    success = reorganizer.run_reorganization()
    
    if success:
        print("\n🎉 Reorganization completed successfully!")
        print("Next steps:")
        print("1. Review the new directory structure")
        print("2. Test MCP server functionality")
        print("3. Verify multimedia integration")
        print("4. Update any custom scripts or documentation")
    else:
        print("\n⚠️  Reorganization completed with issues.")
        print("Review the log file and reorganization report for details.")
        print("Use rollback_reorganization.py if needed.")


if __name__ == "__main__":
    main()
