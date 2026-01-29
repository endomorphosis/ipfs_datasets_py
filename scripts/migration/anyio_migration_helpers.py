"""Helper utilities for migrating from asyncio to anyio."""

import re
from pathlib import Path
from typing import List, Tuple


class AnyioMigrationHelper:
    """Helper class for migrating asyncio code to anyio."""
    
    # Simple 1-to-1 replacements
    SIMPLE_REPLACEMENTS = [
        (r'import anyio\b', 'import anyio'),
        (r'from anyio import', 'from anyio import'),
        (r'asyncio\.sleep\(', 'anyio.sleep('),
        (r'asyncio\.Event\(', 'anyio.Event('),
        (r'asyncio\.Lock\(', 'anyio.Lock('),
        (r'asyncio\.Semaphore\(', 'anyio.Semaphore('),
        (r'asyncio\.TimeoutError', 'TimeoutError'),
        (r'asyncio\.CancelledError', 'anyio.get_cancelled_exc_class()()'),
    ]
    
    # Patterns that need manual conversion
    COMPLEX_PATTERNS = [
        r'asyncio\.gather\(',
        r'asyncio\.create_task\(',
        r'asyncio\.wait_for\(',
        r'asyncio\.get_event_loop\(',
        r'asyncio\.run\(',
        r'asyncio\.Queue\(',
        r'asyncio\.create_subprocess',
    ]
    
    @staticmethod
    def apply_simple_replacements(content: str) -> Tuple[str, int]:
        """Apply simple 1-to-1 replacements.
        
        Returns:
            Tuple of (modified_content, num_replacements)
        """
        num_replacements = 0
        for pattern, replacement in AnyioMigrationHelper.SIMPLE_REPLACEMENTS:
            new_content, count = re.subn(pattern, replacement, content)
            content = new_content
            num_replacements += count
        return content, num_replacements
    
    @staticmethod
    def has_complex_patterns(content: str) -> List[str]:
        """Check if content has patterns requiring manual conversion.
        
        Returns:
            List of complex patterns found
        """
        found = []
        for pattern in AnyioMigrationHelper.COMPLEX_PATTERNS:
            if re.search(pattern, content):
                found.append(pattern)
        return found
    
    @staticmethod
    def convert_asyncio_run(content: str) -> str:
        """Convert anyio.run() to anyio.run()."""
        return re.sub(r'asyncio\.run\(', 'anyio.run(', content)
    
    @staticmethod
    def needs_anyio_import(content: str) -> bool:
        """Check if file needs anyio import."""
        return bool(re.search(r'\banyio\.\w+', content))
    
    @staticmethod
    def add_anyio_import(content: str) -> str:
        """Add anyio import if needed and not present."""
        if 'import anyio' in content:
            return content
        
        # Find first import statement
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if line.startswith('import ') or line.startswith('from '):
                lines.insert(i, 'import anyio')
                return '\n'.join(lines)
        
        # If no imports, add at top after docstring
        if lines and lines[0].startswith('"""'):
            for i, line in enumerate(lines):
                if line.endswith('"""') and i > 0:
                    lines.insert(i + 1, '\nimport anyio')
                    return '\n'.join(lines)
        
        # Add at very top
        lines.insert(0, 'import anyio\n')
        return '\n'.join(lines)


def migrate_file(file_path: Path, dry_run: bool = False) -> dict:
    """Migrate a single file from asyncio to anyio.
    
    Args:
        file_path: Path to the file to migrate
        dry_run: If True, don't write changes
        
    Returns:
        Dictionary with migration statistics
    """
    try:
        content = file_path.read_text()
        original_content = content
        
        # Apply simple replacements
        content, num_simple = AnyioMigrationHelper.apply_simple_replacements(content)
        
        # Convert asyncio.run
        content = AnyioMigrationHelper.convert_asyncio_run(content)
        
        # Add anyio import if needed
        if AnyioMigrationHelper.needs_anyio_import(content):
            content = AnyioMigrationHelper.add_anyio_import(content)
        
        # Check for complex patterns
        complex_patterns = AnyioMigrationHelper.has_complex_patterns(content)
        
        changed = content != original_content
        
        if changed and not dry_run:
            file_path.write_text(content)
        
        return {
            'file': str(file_path),
            'changed': changed,
            'simple_replacements': num_simple,
            'complex_patterns': complex_patterns,
            'migrated': changed and not complex_patterns
        }
    except Exception as e:
        return {
            'file': str(file_path),
            'error': str(e),
            'changed': False
        }
