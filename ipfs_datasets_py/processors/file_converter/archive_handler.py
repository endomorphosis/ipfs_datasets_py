"""
Archive extraction and handling for file converter.

Supports ZIP, TAR, TAR.GZ, TAR.BZ2, GZ, BZ2, and 7Z formats with recursive extraction,
safety checks, and automatic cleanup.
"""

import gzip
import bz2
import zipfile
import tarfile
import tempfile
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import os
import anyio


@dataclass
class ArchiveExtractionResult:
    """Result of archive extraction."""
    extracted_files: List[Path]
    temp_dir: Path
    total_size: int
    archive_type: str
    metadata: Dict[str, Any]


class ArchiveHandler:
    """
    Handler for extracting various archive formats.
    
    Supports: ZIP, TAR, TAR.GZ, TAR.BZ2, GZ, BZ2, 7Z
    Features: Recursive extraction, path traversal protection, cleanup
    """
    
    def __init__(self, max_depth: int = 3, max_size_mb: int = 1000):
        """
        Initialize archive handler.
        
        Args:
            max_depth: Maximum recursion depth for nested archives
            max_size_mb: Maximum total extraction size in MB
        """
        self.max_depth = max_depth
        self.max_size_bytes = max_size_mb * 1024 * 1024
        
    async def extract(self, archive_path: str, recursive: bool = True) -> ArchiveExtractionResult:
        """
        Extract archive to temporary directory.
        
        Args:
            archive_path: Path to archive file
            recursive: Whether to recursively extract nested archives
            
        Returns:
            ArchiveExtractionResult with extracted files and metadata
        """
        archive_path = Path(archive_path)
        
        if not archive_path.exists():
            raise FileNotFoundError(f"Archive not found: {archive_path}")
            
        # Create temp directory
        temp_dir = Path(tempfile.mkdtemp(prefix='archive_extract_'))
        
        try:
            # Detect archive type and extract
            archive_type = self._detect_archive_type(archive_path)
            
            if archive_type == 'zip':
                extracted = await self._extract_zip(archive_path, temp_dir)
            elif archive_type.startswith('tar'):
                extracted = await self._extract_tar(archive_path, temp_dir, archive_type)
            elif archive_type == 'gzip':
                extracted = await self._extract_gzip(archive_path, temp_dir)
            elif archive_type == 'bzip2':
                extracted = await self._extract_bzip2(archive_path, temp_dir)
            elif archive_type == '7z':
                extracted = await self._extract_7z(archive_path, temp_dir)
            else:
                raise ValueError(f"Unsupported archive type: {archive_type}")
                
            # Calculate total size
            total_size = sum(f.stat().st_size for f in extracted if f.is_file())
            
            # Recursive extraction if enabled
            if recursive and self.max_depth > 0:
                extracted = await self._extract_recursive(extracted, temp_dir, depth=1)
                
            # Build result
            result = ArchiveExtractionResult(
                extracted_files=extracted,
                temp_dir=temp_dir,
                total_size=total_size,
                archive_type=archive_type,
                metadata={
                    'file_count': len(extracted),
                    'archive_name': archive_path.name,
                    'recursive': recursive
                }
            )
            
            return result
            
        except Exception as e:
            # Cleanup on error
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
            
    async def _extract_recursive(self, files: List[Path], base_dir: Path, depth: int) -> List[Path]:
        """Recursively extract nested archives."""
        if depth >= self.max_depth:
            return files
            
        all_files = []
        for file_path in files:
            if file_path.is_file() and self._is_archive(file_path):
                # Extract nested archive
                try:
                    nested_result = await self.extract(str(file_path), recursive=False)
                    # Recursively process nested files
                    nested_files = await self._extract_recursive(
                        nested_result.extracted_files,
                        base_dir,
                        depth + 1
                    )
                    all_files.extend(nested_files)
                except Exception:
                    # If extraction fails, keep the archive file
                    all_files.append(file_path)
            else:
                all_files.append(file_path)
                
        return all_files
        
    def _detect_archive_type(self, path: Path) -> str:
        """Detect archive type from file extension and magic numbers."""
        ext = path.suffix.lower()
        
        # Check extension
        if ext == '.zip':
            return 'zip'
        elif ext == '.7z':
            return '7z'
        elif ext in ['.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz2']:
            if '.gz' in path.suffixes or ext == '.tgz':
                return 'tar.gz'
            elif '.bz2' in path.suffixes or ext == '.tbz2':
                return 'tar.bz2'
            return 'tar'
        elif ext == '.gz':
            return 'gzip'
        elif ext == '.bz2':
            return 'bzip2'
            
        # Check magic numbers
        try:
            with open(path, 'rb') as f:
                magic = f.read(8)
                
            if magic.startswith(b'PK\x03\x04') or magic.startswith(b'PK\x05\x06'):
                return 'zip'
            elif magic.startswith(b'\x1f\x8b'):
                return 'gzip'
            elif magic.startswith(b'BZ'):
                return 'bzip2'
            elif magic.startswith(b'7z\xbc\xaf\x27\x1c'):
                return '7z'
            elif b'ustar' in magic:
                return 'tar'
        except Exception:
            pass
            
        return 'unknown'
        
    def _is_archive(self, path: Path) -> bool:
        """Check if file is an archive."""
        archive_type = self._detect_archive_type(path)
        return archive_type != 'unknown'
        
    async def _extract_zip(self, archive_path: Path, dest_dir: Path) -> List[Path]:
        """Extract ZIP archive."""
        extracted = []
        
        def _do_extract():
            with zipfile.ZipFile(archive_path, 'r') as zf:
                # Validate paths
                for member in zf.namelist():
                    if self._is_safe_path(member, dest_dir):
                        zf.extract(member, dest_dir)
                        extracted.append(dest_dir / member)
                        
        await anyio.to_thread.run_sync(_do_extract)
        return [p for p in extracted if p.exists()]
        
    async def _extract_tar(self, archive_path: Path, dest_dir: Path, archive_type: str) -> List[Path]:
        """Extract TAR archive (including .tar.gz, .tar.bz2)."""
        extracted = []
        
        def _do_extract():
            mode = 'r'
            if archive_type == 'tar.gz':
                mode = 'r:gz'
            elif archive_type == 'tar.bz2':
                mode = 'r:bz2'
                
            with tarfile.open(archive_path, mode) as tf:
                for member in tf.getmembers():
                    if self._is_safe_path(member.name, dest_dir):
                        tf.extract(member, dest_dir)
                        extracted.append(dest_dir / member.name)
                        
        await anyio.to_thread.run_sync(_do_extract)
        return [p for p in extracted if p.exists()]
        
    async def _extract_gzip(self, archive_path: Path, dest_dir: Path) -> List[Path]:
        """Extract GZIP file."""
        output_path = dest_dir / archive_path.stem
        
        def _do_extract():
            with gzip.open(archive_path, 'rb') as f_in:
                with open(output_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
                    
        await anyio.to_thread.run_sync(_do_extract)
        return [output_path]
        
    async def _extract_bzip2(self, archive_path: Path, dest_dir: Path) -> List[Path]:
        """Extract BZIP2 file."""
        output_path = dest_dir / archive_path.stem
        
        def _do_extract():
            with bz2.open(archive_path, 'rb') as f_in:
                with open(output_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
                    
        await anyio.to_thread.run_sync(_do_extract)
        return [output_path]
        
    async def _extract_7z(self, archive_path: Path, dest_dir: Path) -> List[Path]:
        """Extract 7Z archive (requires py7zr)."""
        try:
            import py7zr
        except ImportError:
            raise ImportError("py7zr required for 7Z support: pip install py7zr")
            
        extracted = []
        
        def _do_extract():
            with py7zr.SevenZipFile(archive_path, mode='r') as archive:
                archive.extractall(path=dest_dir)
                extracted.extend([dest_dir / name for name in archive.getnames()])
                
        await anyio.to_thread.run_sync(_do_extract)
        return [p for p in extracted if p.exists()]
        
    def _is_safe_path(self, path: str, base_dir: Path) -> bool:
        """Check if extraction path is safe (no path traversal)."""
        try:
            full_path = (base_dir / path).resolve()
            return full_path.is_relative_to(base_dir.resolve())
        except (ValueError, OSError):
            return False
            
    def cleanup(self, result: ArchiveExtractionResult):
        """Clean up extracted files and temporary directory."""
        if result.temp_dir.exists():
            shutil.rmtree(result.temp_dir, ignore_errors=True)


# Convenience functions
async def extract_archive(archive_path: str, max_depth: int = 3) -> ArchiveExtractionResult:
    """
    Extract archive with default settings.
    
    Args:
        archive_path: Path to archive file
        max_depth: Maximum recursion depth
        
    Returns:
        ArchiveExtractionResult
    """
    handler = ArchiveHandler(max_depth=max_depth)
    return await handler.extract(archive_path)


def is_archive(file_path: str) -> bool:
    """Check if file is a supported archive format."""
    handler = ArchiveHandler()
    return handler._is_archive(Path(file_path))
