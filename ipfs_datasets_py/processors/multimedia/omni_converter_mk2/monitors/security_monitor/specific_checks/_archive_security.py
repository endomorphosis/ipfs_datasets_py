from __future__ import annotations
from types_ import Any, Configs, Callable, Logger, ModuleType


import os


class ArchiveSecurity:
    """
    ArchiveSecurity class for handling security checks on archive files.
    
    This class is responsible for performing security checks on archive files
    and ensuring they meet the required security standards.
    """

    executable_extensions = {
        '.exe', '.bat', '.cmd', '.com', '.scr', '.pif', '.app', '.deb', 
        '.rpm', '.dmg', '.pkg', '.msi', '.sh', '.bash', '.zsh', '.fish', 
        '.csh', '.tcsh', '.pl', '.py', '.rb', '.php', '.jar', '.class', 
        '.vbs', '.js', '.ps1', '.psm1', '.psd1'
    }

    def __init__(self, *, resources: dict[str, Any], configs: Configs) -> None:
        self.resources = resources
        self.configs = configs

        self._max_archive_files = 10000 # TODO Un-hardcode this by unloading it into the configs.

        self._closing: Callable = self.resources['closing']
        self._zipfile: ModuleType = self.resources['zipfile']
        self._logger: Logger = self.resources['logger']
        self._tempfile: ModuleType = self.resources['tempfile']
        self._tarfile: ModuleType = self.resources['tarfile']
        self._os: ModuleType = self.resources['os']

        # Load security rules from config
        self._security_rules: dict[str, Any] = {}


    def _get_compression_ratio(self, file_path: str, format_name: str) -> float:
        """Calculate the compression ratio of an archive file.
        
        Args:
            file_path: Path to the archive file.
            format_name: Format of the archive (zip, tar, etc.).
            
        Returns:
            Compression ratio (uncompressed_size / compressed_size).
            Returns 1.0 if unable to determine ratio.
        """
        try:
            compressed_size = self._os.path.getsize(file_path)
            if compressed_size == 0:
                return 1.0

            uncompressed_size = 0

            if format_name == "zip": # TODO Find a way to un-hardcode this.
                with self._closing(self._zipfile.ZipFile(file_path, 'r')) as archive:
                    for info in archive.infolist():
                        uncompressed_size += info.file_size
            elif format_name in ["tar", "gz", "bz2", "xz"]:
                with self._closing(self._tarfile.open(file_path, 'r')) as tar_file:
                    for member in tar_file.getmembers():
                        if member.isfile():
                            uncompressed_size += member.size
            else:
                # For other formats, return 1.0 (no compression detected)
                return 1.0

            return uncompressed_size / compressed_size if compressed_size > 0 else 1.0

        except Exception:
            # If we can't determine the ratio, assume no compression 
            # # TODO Why assume no compression? This needs to be clarified.
            return 1.0
        

    def _is_archive_encrypted(self, file_path: str, format_name: str) -> bool:
        """Check if an archive is encrypted or password protected.
        
        Args:
            file_path: Path to the archive file.
            format_name: Format of the archive (zip, tar, etc.).
            
        Returns:
            True if the archive is encrypted, False otherwise.
        """
        try:
            if format_name == "zip":
                with self._closing(self._zipfile.ZipFile(file_path, 'r')) as archive:
                    for info in archive.infolist():
                        if info.flag_bits & 0x1:  # Check encryption flag
                            return True
                    # Additional check: try to read first file
                    if archive.infolist():
                        try:
                            archive.read(archive.infolist()[0].filename)
                        except RuntimeError as e:
                            if "password" in str(e).lower() or "encrypted" in str(e).lower():
                                return True
            elif format_name in ["tar", "gz", "bz2", "xz"]:
                # TAR files don't have built-in encryption, but check for GPG/PGP signatures
                with open(file_path, 'rb') as f:
                    header = f.read(512)
                    # Check for GPG/PGP magic bytes
                    if header.startswith(b'\x85\x01') or header.startswith(b'\x95\x01'):
                        return True
                    # Check for password-protected compressed files
                    if b'ENCRYPTED' in header or b'PASSWORD' in header:
                        return True
                        
                # Try to open and read archive structure
                try:
                    with self._closing(self._tarfile.open(file_path, 'r')) as tar_file:
                        tar_file.getnames()  # This will fail if encrypted
                except self._tarfile.ReadError as e:
                    if "password" in str(e).lower() or "encrypted" in str(e).lower():
                        return True
            return False
        except Exception:
            # If we can't analyze the archive, assume it might be encrypted
            return True

    def _count_nested_archives(self, file_path: str, format_name: str) -> int:
        """Count the number of nested archive levels in an archive file.
        
        Args:
            file_path: Path to the archive file.
            format_name: Format of the archive (zip, tar, etc.).
            
        Returns:
            Number of nested archive levels found.
        """
        def _is_archive_file(filename: str) -> bool:
            """Check if a filename appears to be an archive."""
            archive_extensions = {'.zip', '.tar', '.gz', '.bz2', '.xz', '.rar', '.7z'}
            _, ext = self._os.path.splitext(filename.lower())
            return ext in archive_extensions
        
        def _count_nested_in_zip(zip_path: str, current_depth: int = 0, max_depth: int = 10) -> int:
            """Recursively count nested archives in a ZIP file."""
            if current_depth >= max_depth:
                return current_depth
            
            max_nested = current_depth
            try:
                with self._closing(self._zipfile.ZipFile(zip_path, 'r')) as archive:
                    for info in archive.infolist():
                        if not info.is_dir() and _is_archive_file(info.filename):
                            # Found a nested archive - extract and analyze it
                            nested_depth = current_depth + 1
                            max_nested = max(max_nested, nested_depth)
                            
                            # Extract nested archive to temp location for deeper analysis
                            with self._tempfile.TemporaryDirectory() as temp_dir:
                                temp_path = self._os.path.join(temp_dir, info.filename)
                                with open(temp_path, 'wb') as temp_file:
                                    temp_file.write(archive.read(info.filename))
                                
                                # Recursively analyze the nested archive
                                deeper_nested = _count_nested_in_zip(temp_path, nested_depth, max_depth)
                                max_nested = max(max_nested, deeper_nested)
                            
            except Exception:
                pass  # Ignore errors and return what we found so far
            
            return max_nested
        
        def _count_nested_in_tar(tar_path: str, current_depth: int = 0, max_depth: int = 10) -> int:
            """Recursively count nested archives in a TAR file."""
            if current_depth >= max_depth:
                return current_depth
            
            max_nested = current_depth
            try:
                with self._closing(self._tarfile.open(tar_path, 'r')) as tar_file:
                    for member in tar_file.getmembers():
                        if member.isfile() and _is_archive_file(member.name):
                            # Found a nested archive
                            nested_depth = current_depth + 1
                            max_nested = max(max_nested, nested_depth)
                            
                            # TODO This needs to be thought over.
                            # For deeper analysis, we'd need to extract and analyze
                            # but for security reasons, we'll just count this level
                            
            except Exception:
                pass  # Ignore errors and return what we found so far
            
            return max_nested
        
        try:
            if format_name == "zip":
                return _count_nested_in_zip(file_path)
            elif format_name in ["tar", "gz", "bz2", "xz"]:
                return _count_nested_in_tar(file_path)
            else:
                return 0  # Unknown format, assume no nesting
                
        except Exception:
            return 0  # If we can't analyze, assume no nesting

    def _is_suspicious_path(self, path: str) -> bool:
        """Check if a file path is suspicious.
        
        Args:
            path: The file path to check.
            
        Returns:
            True if the path is suspicious, False otherwise.
        """
        # Check for directory traversal attempts
        if ".." in path or path.startswith("/") or path.startswith("\\"):
            return True
            
        # Check for Windows drive letters or UNC paths
        if len(path) > 1 and path[1] == ":" or path.startswith("\\\\"):
            return True
            
        # Check for hidden files (starting with .)
        filename = self._os.path.basename(path)
        if filename.startswith(".") and filename not in [".gitignore", ".gitkeep"]:
            return True
            
        # Check for system directories
        system_dirs = ["system32", "windows", "program files", "etc", "bin", "sbin", "usr"]
        path_lower = path.lower()
        for sys_dir in system_dirs:
            if sys_dir in path_lower:
                return True

        # Check for very long paths (potential buffer overflow)
        if len(path) > 255:
            return True

        return False
    
    @staticmethod
    def _check_archive_executables(self, file_path: str, format_name: str) -> list[str]:
        """Check for executable files in an archive.
        
        Args:
            file_path: Path to the archive file.
            format_name: Format of the archive (zip, tar, etc.).
            
        Returns:
            List of executable file paths found in the archive.
        """
        executable_files = set()
        # TODO Move executable_extensions to the resources so it can be fine-tuned/changed.

        try:
            if format_name == "zip":
                with self._closing(self._zipfile.ZipFile(file_path, 'r')) as archive:
                    for info in archive.infolist():
                        if not info.is_dir():
                            filename = info.filename
                            _, ext = self._os.path.splitext(filename.lower())
                            
                            # Check file extension
                            if ext in self.executable_extensions:
                                executable_files.add(filename)

                            # Check for files without extension that might be executable (Unix)
                            elif not ext and not filename.endswith('/'):
                                executable_files.add(filename)

                            # Check for shebang in first few bytes
                            elif filename.lower().endswith(tuple(self.executable_extensions)):
                                try:
                                    file_content = archive.read(info.filename)
                                    if file_content.startswith(b'#!'):
                                        executable_files.add(filename)
                                except Exception:
                                    pass  


            elif format_name in ["tar", "gz", "bz2", "xz"]:
                with self._closing(self._tarfile.open(file_path, 'r')) as tar_file:
                    for member in tar_file.getmembers():
                        if member.isfile():
                            filename = member.name
                            _, ext = self._os.path.splitext(filename.lower())
                            
                            # Check file extension
                            if ext in self.executable_extensions:
                                executable_files.add(filename)

                            # Check file permissions (Unix executable bit)
                            elif member.mode & 0o111:  # Check if any execute bit is set
                                executable_files.add(filename)

                            # Check for files without extension that might be executable
                            elif not ext and not filename.endswith('/'):
                                executable_files.add(filename)

        except Exception:
            # If we can't read the archive, return empty list
            pass
            
        return executable_files


    def _count_archive_files(self, file_path: str, format_name: str) -> int:
        """Count the total number of files in an archive.
        
        Args:
            file_path: Path to the archive file.
            format_name: Format of the archive (zip, tar, etc.).
            
        Returns:
            Total number of files in the archive (excluding directories).
        """
        file_count = 0

        try:
            if format_name == "zip":
                with self._closing(self._zipfile.ZipFile(file_path, 'r')) as archive:
                    for info in archive.infolist():
                        if not info.is_dir():
                            file_count += 1
                            
            elif format_name in ["tar", "gz", "bz2", "xz"]:
                with self._closing(self._tarfile.open(file_path, 'r')) as tar_file:
                    for member in tar_file.getmembers():
                        if member.isfile():
                            file_count += 1
            else:
                # For unknown formats, return 0
                return 0

        except Exception:
            # If we can't read the archive, return 0
            return 0

        return file_count

    def _check_archive_paths(self, file_path: str, format_name: str) -> list[str]:
        """Check for suspicious file paths in an archive.
        
        Args:
            file_path: Path to the archive file.
            format_name: Format of the archive (zip, tar, etc.).
            
        Returns:
            List of suspicious file paths found in the archive.
        """
        suspicious_paths = []
        
        try:
            if format_name == "zip":
                with self._closing(self._zipfile.ZipFile(file_path, 'r')) as archive:
                    for info in archive.infolist():
                        path = info.filename
                        if self._is_suspicious_path(path):
                            suspicious_paths.append(path)

            elif format_name in ["tar", "gz", "bz2", "xz"]:
                with self._closing(self._tarfile.open(file_path, 'r')) as tar_file:
                    for member in tar_file.getmembers():
                        if member.isfile():
                            path = member.name
                            if self._is_suspicious_path(path):
                                suspicious_paths.append(path)
                                
        except Exception:
            # If we can't read the archive, return empty list
            return []
            
        return suspicious_paths


    def check_archive_security(
            self, 
            file_path: str, 
            format_name: str, 
            ) -> list[str]:
        """
        Performs comprehensive security checks on archive files to detect potential threats.

        This method analyzes archive files for various security vulnerabilities and suspicious
        characteristics that could indicate malicious content or potential security risks.

        Security checks performed:
        - **Zip bomb detection**: Analyzes compression ratios to identify archives with
          suspiciously high decompression ratios (>100:1) that could exhaust system resources
        - **Encryption detection**: Identifies password-protected or encrypted archives that
          may bypass content inspection (configurable via reject_encrypted rule)
        - **Nested archive analysis**: Detects excessive levels of archive nesting (>3 levels)
          which is often used to evade security scanning
        - **Path traversal detection**: Scans for malicious file paths containing directory
          traversal sequences (../, absolute paths, UNC paths, system directories)
        - **Executable content scanning**: Identifies executable files based on extensions,
          file permissions, and shebang headers (configurable via reject_executable rule)
        - **File count validation**: Ensures archives don't contain excessive numbers of files
          that could overwhelm extraction processes (configurable via max_archive_files)

        Supported archive formats:
        - ZIP archives (.zip)
        - TAR archives (.tar, .tar.gz, .tar.bz2, .tar.xz)
        - Compressed archives (.gz, .bz2, .xz)

        Args:
            file_path (str): Absolute or relative path to the archive file to analyze.
                   Must be accessible and readable by the current process.
            format_name (str): Archive format identifier. Supported values include:
                     "zip", "tar", "gz", "bz2", "xz". Case-sensitive.

        Returns:
            list[str]: List of security issue descriptions found in the archive.
                  Each item describes a specific security concern or violation.
                  Returns empty list if no issues are detected.

        Raises:
            Exception: Individual check failures are caught and converted to issue
                  descriptions rather than propagating exceptions.
 
        Example:
            >>> security = ArchiveSecurity(resources=resources, configs=configs)
            >>> issues = security.check_archive_security("/path/to/file.zip", "zip")
            >>> if issues:
            ...     print(f"Security issues found: {issues}")
        """
        issues = []

        try:
            # Check for zip bombs (suspiciously large uncompressed size)
            if format_name in ["zip", "tar", "gz", "bz2", "xz"]:
                compressed_ratio = self._get_compression_ratio(file_path, format_name)
                if compressed_ratio > 100:  # Uncompressed is 100x larger than compressed # TODO compressed_ratio is Magic number, should be configurable.
                    issues.append(f"Suspicious compression ratio: {compressed_ratio}:1 (possible zip bomb)")

            # Check for encrypted archives
            if self._security_rules["reject_encrypted"]:
                if self._is_archive_encrypted(file_path, format_name):
                    issues.append("Archive is encrypted or password protected")

            # Check for nested archives (archives within archives)
            if self._security_rules.get("reject_nested_archives", True):
                nested_count = self._count_nested_archives(file_path, format_name)
                if nested_count > 3:  # More than 3 levels of nesting # TODO nested_count is a magic number, should be configurable.
                    issues.append(f"Excessive archive nesting detected: {nested_count} levels")

            # Check for suspicious file paths in archive
            suspicious_paths = self._check_archive_paths(file_path, format_name)
            if suspicious_paths:
                issues.extend([f"Suspicious file path in archive: {path}" for path in suspicious_paths])

            # Check for executable files in archive
            if self._security_rules["reject_executable"]:
                executable_files = self._check_archive_executables(file_path, format_name)
                if executable_files:
                    issues.extend([f"Executable file in archive: {exe}" for exe in executable_files])

            # Check total number of files in archive
            file_count = self._count_archive_files(file_path, format_name)
            max_files = self._security_rules.get("max_archive_files", self._max_archive_files)
            if file_count > max_files:
                issues.append(f"Archive contains too many files: {file_count} (max: {max_files})")

        except Exception as e:
            issues.append(f"Error analyzing archive: {e}")

        return issues