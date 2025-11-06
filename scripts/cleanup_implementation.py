#!/usr/bin/env python3
"""
Root Directory Cleanup Implementation Script

This script implements the cleanup plan defined in ROOT_CLEANUP_PLAN.md
to organize and clean up the project root directory.
"""

import os
import shutil
import sys
from pathlib import Path
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class RootDirectoryCleanup:
    """Implements the root directory cleanup plan."""
    
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.project_root = Path.cwd()
        self.moved_files = []
        self.removed_files = []
        self.created_dirs = []
        
    def log_action(self, action, path, target=None):
        """Log cleanup actions."""
        if self.dry_run:
            prefix = "[DRY RUN]"
        else:
            prefix = "[EXECUTE]"
            
        if target:
            logger.info(f"{prefix} {action}: {path} -> {target}")
        else:
            logger.info(f"{prefix} {action}: {path}")
    
    def create_directory(self, path):
        """Create directory if it doesn't exist."""
        path = Path(path)
        if not path.exists():
            self.log_action("CREATE DIR", path)
            if not self.dry_run:
                path.mkdir(parents=True, exist_ok=True)
            self.created_dirs.append(str(path))
        return path
    
    def move_file(self, source, target):
        """Move file from source to target."""
        source = Path(source)
        target = Path(target)
        
        if not source.exists():
            logger.warning(f"Source file does not exist: {source}")
            return False
            
        # Create target directory if needed
        target.parent.mkdir(parents=True, exist_ok=True)
        
        self.log_action("MOVE", source, target)
        if not self.dry_run:
            shutil.move(str(source), str(target))
        self.moved_files.append((str(source), str(target)))
        return True
    
    def remove_file(self, path):
        """Remove file or directory."""
        path = Path(path)
        if not path.exists():
            return False
            
        self.log_action("REMOVE", path)
        if not self.dry_run:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        self.removed_files.append(str(path))
        return True
    
    def phase1_create_structure(self):
        """Phase 1: Create new directory structure."""
        logger.info("=== PHASE 1: Creating Directory Structure ===")
        
        # Create main directories
        self.create_directory("scripts")
        self.create_directory("archive")
        self.create_directory("archive/migration")
        self.create_directory("archive/migration/docs")
        self.create_directory("archive/migration/logs")
        self.create_directory("archive/migration/scripts")
        self.create_directory("archive/migration/tests")
        self.create_directory("archive/validation")
        self.create_directory("archive/test_results")
        self.create_directory("archive/audit_visuals")
        self.create_directory("docs/migration")
        
    def phase2_move_files(self):
        """Phase 2: Move files to appropriate locations."""
        logger.info("=== PHASE 2: Moving Files ===")
        
        # Utility scripts to scripts/
        utility_scripts = [
            "start_fastapi.py",
            "deploy.py",
            "cleanup_root_directory.py"
        ]
        
        for script in utility_scripts:
            if Path(script).exists():
                self.move_file(script, f"scripts/{script}")
        
        # Simple example to examples/
        if Path("simple_fastapi.py").exists():
            self.move_file("simple_fastapi.py", "examples/simple_fastapi.py")
        
        # Migration documentation to archive
        migration_docs = [
            "COMPREHENSIVE_MIGRATION_PLAN.md",
            "FINAL_COMPLETION_REPORT.md", 
            "FINAL_INTEGRATION_COMPLETION_REPORT.md",
            "FINAL_INTEGRATION_STATUS.md",
            "INTEGRATION_COMPLETE.md",
            "INTEGRATION_STATUS_SUMMARY.md",
            "IPFS_EMBEDDINGS_TOOL_MAPPING.md",
            "MIGRATION_COMPLETION_REPORT.md",
            "MIGRATION_COMPLETION_SUMMARY.md",
            "MIGRATION_ORGANIZATION.md",
            "PHASE5_COMPLETION_REPORT.md",
            "PHASE5_VALIDATION_REPORT.md",
            "PHASE_3_COMPLETION_REPORT.md",
            "PHASE_4_COMPLETION_REPORT.md",
            "POST_RELOAD_STATUS.md",
            "PROJECT_COMPLETION_SUMMARY.md"
        ]
        
        for doc in migration_docs:
            if Path(doc).exists():
                self.move_file(doc, f"archive/migration/docs/{doc}")
        
        # Validation scripts to archive
        validation_scripts = [
            "comprehensive_integration_validation.py",
            "comprehensive_mcp_test.py",
            "comprehensive_validation.py",
            "core_integration_test.py",
            "final_integration_test.py",
            "final_integration_validation.py",
            "final_migration_test.py",
            "final_validation.py",
            "final_validation_check.py",
            "integration_status_check.py",
            "integration_test_quick.py",
            "migration_verification.py",
            "phase5_validation.py",
            "production_readiness_check.py",
            "quick_check.py",
            "quick_integration_test.py",
            "quick_validation.py",
            "robust_integration_test.py",
            "simple_integration_test.py",
            "simple_test.py",
            "sync_validation.py",
            "systematic_validation.py",
            "test_fastapi_service.py",
            "test_ipfs_embeddings_integration.py",
            "test_migration_integration.py",
            "test_migration_simple.py",
            "test_minimal_integration.py",
            "validate_fastapi.py",
            "validate_integration.py",
            "verify_final_status.py",
            "verify_integration.py"
        ]
        
        for script in validation_scripts:
            if Path(script).exists():
                self.move_file(script, f"archive/validation/{script}")
        
        # Move directories
        directories_to_move = [
            ("migration_docs", "archive/migration/docs_old"),
            ("migration_logs", "archive/migration/logs"),
            ("migration_scripts", "archive/migration/scripts"),
            ("migration_tests", "archive/migration/tests"),
            ("test_results", "archive/test_results"),
            ("test_visualizations", "archive/test_visualizations"),
            ("tool_test_results", "archive/tool_test_results"),
            ("audit_visuals", "archive/audit_visuals")
        ]
        
        for source_dir, target_dir in directories_to_move:
            if Path(source_dir).exists():
                self.move_file(source_dir, target_dir)
    
    def phase3_cleanup(self):
        """Phase 3: Remove temporary and redundant files."""
        logger.info("=== PHASE 3: Cleanup ===")
        
        # Remove files that are no longer needed
        files_to_remove = [
            "__init__.py",  # Not needed in root
            "migration_temp"  # Temporary directory
        ]
        
        for file_path in files_to_remove:
            if Path(file_path).exists():
                self.remove_file(file_path)
        
        # Clean up __pycache__ directories in root
        pycache_dirs = list(Path('.').glob('__pycache__'))
        for pycache_dir in pycache_dirs:
            if pycache_dir.parent == Path('.'):  # Only root level
                self.remove_file(pycache_dir)
    
    def phase4_update_references(self):
        """Phase 4: Update file references (manual step)."""
        logger.info("=== PHASE 4: Update References (Manual) ===")
        logger.info("Manual tasks after cleanup:")
        logger.info("1. Update VS Code tasks.json if needed")
        logger.info("2. Update documentation with new file paths")
        logger.info("3. Test that everything still works")
        logger.info("4. Update any scripts that reference moved files")
    
    def generate_summary(self):
        """Generate cleanup summary."""
        logger.info("=== CLEANUP SUMMARY ===")
        logger.info(f"Directories created: {len(self.created_dirs)}")
        logger.info(f"Files moved: {len(self.moved_files)}")
        logger.info(f"Files removed: {len(self.removed_files)}")
        
        if self.dry_run:
            logger.info("This was a DRY RUN - no actual changes made")
            logger.info("Run with --execute to perform actual cleanup")
        else:
            logger.info("Cleanup completed successfully!")
            
        # Save summary to file
        summary_file = "archive/cleanup_summary.txt" if not self.dry_run else "cleanup_summary_preview.txt"
        
        with open(summary_file, 'w') as f:
            f.write("Root Directory Cleanup Summary\n")
            f.write("=" * 40 + "\n\n")
            f.write(f"Directories created: {len(self.created_dirs)}\n")
            for dir_path in self.created_dirs:
                f.write(f"  + {dir_path}\n")
            
            f.write(f"\nFiles moved: {len(self.moved_files)}\n")
            for source, target in self.moved_files:
                f.write(f"  {source} -> {target}\n")
            
            f.write(f"\nFiles removed: {len(self.removed_files)}\n")
            for file_path in self.removed_files:
                f.write(f"  - {file_path}\n")
        
        logger.info(f"Summary saved to: {summary_file}")
    
    def run_cleanup(self):
        """Execute the complete cleanup process."""
        logger.info("Starting Root Directory Cleanup")
        logger.info(f"Project root: {self.project_root}")
        logger.info(f"Dry run: {self.dry_run}")
        logger.info("")
        
        try:
            self.phase1_create_structure()
            self.phase2_move_files()
            self.phase3_cleanup()
            self.phase4_update_references()
            self.generate_summary()
            
            return True
            
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            return False

def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Clean up root directory")
    parser.add_argument("--execute", action="store_true", 
                       help="Actually perform cleanup (default is dry run)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Verbose output")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Confirm before actual execution
    if args.execute:
        print("⚠️  WARNING: This will modify your file system!")
        print("⚠️  Make sure you have committed all important changes to git!")
        response = input("Continue with cleanup? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("Cleanup cancelled.")
            return 1
    
    cleanup = RootDirectoryCleanup(dry_run=not args.execute)
    success = cleanup.run_cleanup()
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
