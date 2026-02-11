"""
Test suite to validate the anyio migration from asyncio.

This test suite verifies that:
1. Basic anyio functionality works
2. Task groups work as expected
3. Migrated modules import correctly
4. No asyncio imports remain in production code
"""

import pytest
import anyio
import sys
from pathlib import Path


class TestAnyioMigration:
    """Test the anyio migration."""
    
    def test_basic_anyio_sleep(self):
        """Test basic anyio sleep functionality."""
        async def sleep_test():
            await anyio.sleep(0.01)
            return "success"
        
        result = anyio.run(sleep_test)
        assert result == "success"
    
    def test_anyio_task_groups(self):
        """Test anyio task groups (replacement for asyncio.gather)."""
        async def task_group_test():
            results = []
            
            async def task1():
                await anyio.sleep(0.01)
                results.append("task1")
            
            async def task2():
                await anyio.sleep(0.01)
                results.append("task2")
            
            async with anyio.create_task_group() as tg:
                tg.start_soon(task1)
                tg.start_soon(task2)
            
            return sorted(results)
        
        results = anyio.run(task_group_test)
        assert results == ["task1", "task2"]
    
    def test_anyio_event(self):
        """Test anyio Event (replacement for asyncio.Event)."""
        async def event_test():
            event = anyio.Event()
            assert not event.is_set()
            event.set()
            assert event.is_set()
            await event.wait()
            return "success"
        
        result = anyio.run(event_test)
        assert result == "success"
    
    def test_anyio_lock(self):
        """Test anyio Lock (replacement for asyncio.Lock)."""
        async def lock_test():
            lock = anyio.Lock()
            async with lock:
                return "success"
        
        result = anyio.run(lock_test)
        assert result == "success"
    
    def test_anyio_semaphore(self):
        """Test anyio Semaphore (replacement for asyncio.Semaphore)."""
        async def semaphore_test():
            semaphore = anyio.Semaphore(2)
            async with semaphore:
                return "success"
        
        result = anyio.run(semaphore_test)
        assert result == "success"
    
    def test_anyio_fail_after(self):
        """Test anyio fail_after (replacement for asyncio.wait_for)."""
        async def timeout_test():
            try:
                with anyio.fail_after(0.1):
                    await anyio.sleep(0.01)
                return "success"
            except TimeoutError:
                return "timeout"
        
        result = anyio.run(timeout_test)
        assert result == "success"
    
    def test_migrated_modules_import(self):
        """Test that migrated modules can be imported."""
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        
        # Test critical migrated modules
        try:
            from ipfs_datasets_py.alerts import alert_manager
            assert True
        except ImportError as e:
            pytest.fail(f"Failed to import alerts.alert_manager: {e}")
        
        try:
            from ipfs_datasets_py.multimedia import ytdlp_wrapper
            assert True
        except ImportError as e:
            pytest.fail(f"Failed to import multimedia.ytdlp_wrapper: {e}")
        
        try:
            from ipfs_datasets_py import unified_web_scraper
            assert True
        except ImportError as e:
            pytest.fail(f"Failed to import unified_web_scraper: {e}")
    
    def test_no_asyncio_imports_in_production(self):
        """Verify no asyncio imports remain in production code."""
        import subprocess
        import os
        
        repo_root = Path(__file__).parent.parent.parent

        # Ignore vendored/submodule directories that intentionally retain asyncio
        # (these are maintained upstream and not part of the anyio migration work).
        excluded_dirs = [
            'ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/scrape_the_law_mk3',
            'ipfs_datasets_py/data_transformation/multimedia/omni_converter_mk2',
            'ipfs_datasets_py/data_transformation/multimedia/convert_to_txt_based_on_mime_type',
        ]

        grep_cmd = ['grep', '-r', '^import asyncio$', '--include=*.py']
        for rel_dir in excluded_dirs:
            if (repo_root / rel_dir).exists():
                grep_cmd.append(f"--exclude-dir={os.path.basename(rel_dir)}")
        grep_cmd.append('ipfs_datasets_py/')

        result = subprocess.run(
            grep_cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        
        # Should have no matches (exit code 1)
        assert result.returncode == 1, f"Found asyncio imports in production code:\n{result.stdout}"
    
    def test_anyio_imports_present(self):
        """Verify anyio imports are present in migrated code."""
        import subprocess
        
        # Check for anyio imports in ipfs_datasets_py/ directory
        result = subprocess.run(
            ['grep', '-r', '^import anyio$', '--include=*.py', 'ipfs_datasets_py/'],
            cwd=Path(__file__).parent.parent.parent,
            capture_output=True,
            text=True
        )
        
        # Should have matches (exit code 0)
        assert result.returncode == 0, "No anyio imports found in production code"
        
        # Count the number of anyio imports
        import_count = len(result.stdout.strip().split('\n'))
        assert import_count > 100, f"Expected >100 anyio imports, found {import_count}"


@pytest.mark.trio
class TestAnyioTrioBackend:
    """Test that code works with trio backend."""
    
    async def test_basic_trio(self):
        """Test basic functionality with trio backend."""
        await anyio.sleep(0.01)
        assert True
    
    async def test_trio_task_groups(self):
        """Test task groups with trio backend."""
        results = []
        
        async def task1():
            await anyio.sleep(0.01)
            results.append("task1")
        
        async def task2():
            await anyio.sleep(0.01)
            results.append("task2")
        
        async with anyio.create_task_group() as tg:
            tg.start_soon(task1)
            tg.start_soon(task2)
        
        assert sorted(results) == ["task1", "task2"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
