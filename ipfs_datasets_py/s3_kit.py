from boto3 import resource
from boto3.session import Session
import datetime
import os
import sys
import io
import tempfile
import json
from typing import Any, Dict, List, Optional, Union

class s3_kit:
    """
    S3 Toolkit for AWS S3 and S3-Compatible Storage Operations

    The s3_kit class provides a comprehensive interface for interacting with AWS S3 and 
    S3-compatible storage services. It offers simplified methods for common file and 
    directory operations including upload, download, copy, move, list, and delete 
    operations. The class supports both file-level and directory-level operations 
    with progress tracking capabilities.

    This toolkit abstracts the complexity of boto3 S3 operations and provides a 
    unified interface for managing S3 objects and directories. It supports custom 
    S3 configurations, session management, and handles both AWS S3 and S3-compatible 
    endpoints.

    Args:
        resources (Any): Resource configuration for S3 operations (currently unused)
        meta (Optional[Dict[str, Any]], optional): Metadata dictionary containing S3 
            configuration. If provided and contains 's3cfg' key, initializes the S3 
            session automatically. Defaults to None.

    Key Features:
    - File operations: upload, download, copy, move, list, delete
    - Directory operations: bulk upload/download, recursive copy/move, list contents
    - S3 session management with custom configurations
    - Support for AWS S3 and S3-compatible storage services
    - Progress callback support for long-running operations
    - Automatic path handling and directory creation
    - Metadata extraction and timestamp conversion

    Attributes:
        bucket (Any): Current S3 bucket reference
        bucket_files (Any): Cached bucket file listings
        config (Dict[str, Any]): S3 configuration dictionary
        session (Any): Active boto3 S3 session
        cp_dir (callable): Alias for s3_cp_dir method
        cp_file (callable): Alias for s3_cp_file method
        rm_dir (callable): Alias for s3_rm_dir method
        rm_file (callable): Alias for s3_rm_file method
        ls_dir (callable): Alias for s3_ls_dir method
        ls_file (callable): Alias for s3_ls_file method
        mv_dir (callable): Alias for s3_mv_dir method
        mv_file (callable): Alias for s3_mv_file method
        dl_dir (callable): Alias for s3_dl_dir method
        dl_file (callable): Alias for s3_dl_file method
        ul_dir (callable): Alias for s3_ul_dir method
        ul_file (callable): Alias for s3_ul_file method
        mk_dir (callable): Alias for s3_mk_dir method
        get_session (callable): Alias for get_session method

    Public Methods:
        __call__(method: str, **kwargs) -> Any:
            Dynamic method dispatcher for all S3 operations
        s3_ls_dir(dir: str, bucket_name: str, **kwargs) -> List[Dict[str, Any]]:
            List contents of an S3 directory
        s3_rm_dir(dir: str, bucket: str, **kwargs) -> List[Dict[str, Any]]:
            Delete an S3 directory and all its contents
        s3_cp_dir(src_path: str, dst_path: str, bucket: str, **kwargs) -> Dict[str, Dict[str, Any]]:
            Copy an S3 directory to another location
        s3_mv_dir(src_path: str, dst_path: str, bucket: str, **kwargs) -> Dict[str, Dict[str, Any]]:
            Move an S3 directory to another location
        s3_dl_dir(remote_path: str, local_path: str, bucket: str, **kwargs) -> Dict[str, Dict[str, Any]]:
            Download an S3 directory to local filesystem
        s3_ul_dir(local_path: str, remote_path: str, bucket: str, **kwargs) -> Dict[str, Dict[str, Any]]:
            Upload a local directory to S3
        s3_ls_file(filekey: str, bucket: str, **kwargs) -> Union[Dict[str, Dict[str, Any]], bool]:
            List metadata for a specific S3 file
        s3_rm_file(this_path: str, bucket: str, **kwargs) -> Dict[str, Any]:
            Delete a specific S3 file
        s3_cp_file(src_path: str, dst_path: str, bucket: str, **kwargs) -> Dict[str, Any]:
            Copy an S3 file to another location
        s3_mv_file(src_path: str, dst_path: str, bucket: str, **kwargs) -> Dict[str, Any]:
            Move an S3 file to another location
        s3_dl_file(remote_path: str, local_path: str, bucket: str, **kwargs) -> Dict[str, Any]:
            Download an S3 file to local filesystem
        s3_ul_file(upload_file: str, path: str, bucket: str, **kwargs) -> Dict[str, Any]:
            Upload a local file to S3
        s3_mk_dir(path: str, bucket: str, **kwargs) -> Dict[str, Any]:
            Create an S3 directory
        get_session(s3_config: Dict[str, Any]) -> Any:
            Create or retrieve S3 session with configuration
        config_to_boto(s3_config: Dict[str, Any]) -> Dict[str, Any]:
            Convert S3 configuration to boto3 format

    Usage Example:
        # Initialize with S3 configuration
        s3_config = {
            'accessKey': 'your_access_key',
            'secretKey': 'your_secret_key',
            'endpoint': 'https://s3.amazonaws.com'
        }
        s3 = s3_kit(None, {'s3cfg': s3_config})
        
        # List directory contents
        files = s3.s3_ls_dir('my-folder/', 'my-bucket')
        
        # Upload a file
        result = s3.s3_ul_file('/local/file.txt', 'remote/file.txt', 'my-bucket')
        
        # Download a directory
        result = s3.s3_dl_dir('remote-folder/', '/local/folder/', 'my-bucket')
        
        # Use callable interface
        files = s3('ls_dir', dir='my-folder/', bucket_name='my-bucket')

    Notes:
        - All methods return dictionaries with metadata including timestamps, sizes, and ETags
        - Timestamps are converted to Unix timestamps for consistency
        - Directory operations handle nested folder structures automatically
        - Supports both AWS S3 and S3-compatible storage endpoints
        - Session management is handled automatically with configuration caching
    """
    def __init__(self, resources: Any, meta: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialize the S3 toolkit with optional configuration.

        Sets up the S3 toolkit instance with method aliases and optional S3 configuration.
        If meta contains an 's3cfg' key, automatically initializes the S3 session with
        the provided configuration.

        Args:
            resources (Any): Resource configuration parameter (currently unused but 
                maintained for interface compatibility)
            meta (Optional[Dict[str, Any]], optional): Metadata dictionary that may contain:
                - 's3cfg': S3 configuration dictionary with connection parameters
                Defaults to None.

        Attributes initialized:
            bucket (None): Placeholder for current S3 bucket reference
            bucket_files (None): Placeholder for cached bucket file listings
            config (Dict[str, Any]): S3 configuration dictionary (set if meta contains s3cfg)
            cp_dir (callable): Alias method for s3_cp_dir
            cp_file (callable): Alias method for s3_cp_file
            rm_dir (callable): Alias method for s3_rm_dir
            rm_file (callable): Alias method for s3_rm_file
            ls_dir (callable): Alias method for s3_ls_dir
            ls_file (callable): Alias method for s3_ls_file
            mv_dir (callable): Alias method for s3_mv_dir
            mv_file (callable): Alias method for s3_mv_file
            dl_dir (callable): Alias method for s3_dl_dir
            dl_file (callable): Alias method for s3_dl_file
            ul_dir (callable): Alias method for s3_ul_dir
            ul_file (callable): Alias method for s3_ul_file
            mk_dir (callable): Alias method for s3_mk_dir
            get_session (callable): Alias method for get_session

        S3 Configuration Format:
            The s3cfg dictionary should contain either:
            - accessKey, secretKey, endpoint (legacy format)
            - aws_access_key_id, aws_secret_access_key, endpoint_url (boto3 format)

        Raises:
            Exception: If s3cfg is provided but doesn't contain required keys
        """
        self.bucket = None
        self.bucket_files = None
        self.cp_dir = self.s3_cp_dir
        self.cp_file = self.s3_cp_file
        self.rm_dir = self.s3_rm_dir
        self.rm_file = self.s3_rm_file
        self.ls_dir = self.s3_ls_dir
        self.ls_file = self.s3_ls_file
        self.mv_dir = self.s3_mv_dir
        self.mv_file = self.s3_mv_file
        self.dl_dir = self.s3_dl_dir
        self.dl_file = self.s3_dl_file
        self.ul_dir = self.s3_ul_dir
        self.ul_file = self.s3_ul_file
        self.mk_dir = self.s3_mk_dir
        self.get_session = self.get_session
        if meta is not None:
            if "s3cfg" in meta:
                if meta['s3cfg'] is not None:
                    self.config = meta['s3cfg']
                    self.get_session(meta['s3cfg'])

    def __call__(self, method: str, **kwargs: Any) -> Any:
        """
        Dynamic method dispatcher for S3 operations.

        Provides a callable interface to access all S3 operations through a single 
        method dispatcher. This allows for dynamic method invocation based on string
        method names.

        Args:
            method (str): Name of the S3 operation to perform. Supported methods:
                - 'ls_dir': List directory contents
                - 'rm_dir': Remove directory
                - 'cp_dir': Copy directory
                - 'mv_dir': Move directory
                - 'dl_dir': Download directory
                - 'ul_dir': Upload directory
                - 'ls_file': List file metadata
                - 'rm_file': Remove file
                - 'cp_file': Copy file
                - 'mv_file': Move file
                - 'dl_file': Download file
                - 'ul_file': Upload file
                - 'mk_dir': Make directory
                - 'get_session': Get S3 session
                - 'config_to_boto': Convert config to boto3 format
            **kwargs: Method-specific keyword arguments passed to the underlying method

        Returns:
            Any: Result from the called method, typically dictionaries with metadata
                or lists of metadata dictionaries

        Raises:
            AttributeError: If method name is not recognized
            Exception: Any exceptions raised by the underlying method

        Examples:
            >>> s3 = s3_kit(None, {'s3cfg': config})
            >>> files = s3('ls_dir', dir='folder/', bucket_name='my-bucket')
            >>> result = s3('ul_file', upload_file='local.txt', path='remote.txt', bucket='my-bucket')
        """
        if method == 'ls_dir':
            self.method = 'ls_dir'
            return self.s3_ls_dir(**kwargs)
        if method == 'rm_dir':
            self.method = 'rm_dir'
            return self.s3_rm_dir(**kwargs)
        if method == 'cp_dir':
            self.method = 'cp_dir'
            return self.s3_cp_dir(**kwargs)
        if method == 'mv_dir':
            self.method = 'mv_dir'
            return self.s3_mv_dir(**kwargs)
        if method == 'dl_dir':
            self.method = 'dl_dir'
            return self.s3_dl_dir(**kwargs)
        if method == 'ul_dir':
            self.method = 'ul_dir'
            return self.s3_ul_dir(**kwargs)
        if method == 'ls_file':
            self.method = 'ls_file'
            return self.s3_ls_file(**kwargs)
        if method == 'rm_file':
            self.method = 'rm_file'
            return self.s3_rm_file(**kwargs)
        if method == 'cp_file':
            self.method = 'cp_file'
            return self.s3_cp_file(**kwargs)
        if method == 'mv_file':
            self.method = 'mv_file'
            return self.s3_mv_file(**kwargs)
        if method == 'dl_file':
            self.method = 'dl_file'
            return self.s3_dl_file(**kwargs)
        if method == 'ul_file':
            self.method = 'ul_file'
            return self.s3_ul_file(**kwargs)
        if method == 'mk_dir':
            self.method = 'mk_dir'
            return self.s3_mkdir(**kwargs)
        if method == 'get_session':
            self.method = 'get_session'
            return self.get_session(**kwargs)
        if method == 'config_to_boto':
            self.method = 'config_to_boto'
            return self.config_to_boto(**kwargs)

    def s3_ls_dir(self, dir: str, bucket_name: str, **kwargs: Any) -> List[Dict[str, Any]]:
        """
        List contents of an S3 directory.

        Retrieves metadata for all objects within the specified S3 directory prefix.
        Returns a list of dictionaries containing object metadata including keys,
        timestamps, sizes, and ETags.

        Args:
            dir (str): Directory path/prefix to list (e.g., 'folder/' or 'path/to/folder/')
            bucket_name (str): Name of the S3 bucket to search
            **kwargs: Additional keyword arguments:
                - s3cfg (Dict[str, Any], optional): S3 configuration override

        Returns:
            List[Dict[str, Any]]: List of object metadata dictionaries, each containing:
                - key (str): S3 object key/path
                - last_modified (float): Unix timestamp of last modification
                - size (int): Object size in bytes
                - e_tag (str): Object ETag for integrity verification

        Raises:
            ClientError: If bucket doesn't exist or access is denied
            Exception: If S3 configuration is invalid

        Examples:
            >>> files = s3.s3_ls_dir('documents/', 'my-bucket')
            >>> for file in files:
            ...     print(f"File: {file['key']}, Size: {file['size']} bytes")
        """
        if "s3cfg" in kwargs:
            s3_config = kwargs['s3cfg']
        else:
            s3_config = self.config

        bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket_name)
        bucket_objects = bucket.objects.filter(Prefix=dir)
        objects = []
        directory = {}
        for obj in bucket_objects:
            result = {}
            result['key'] = obj.key
            result['last_modified'] = datetime.datetime.timestamp(obj.last_modified)
            result['size'] = obj.size
            result['e_tag'] = obj.e_tag
            objects.append(result)
        return objects

    def s3_rm_dir(self, dir: str, bucket: str, **kwargs: Any) -> List[Dict[str, Any]]:
        """
        Delete an S3 directory and all its contents.

        Recursively deletes all objects within the specified directory prefix.
        Returns metadata for each deleted object.

        Args:
            dir (str): Directory path/prefix to delete (e.g., 'folder/' or 'path/to/folder/')
            bucket (str): Name of the S3 bucket containing the directory
            **kwargs: Additional keyword arguments:
                - s3cfg (Dict[str, Any], optional): S3 configuration override

        Returns:
            List[Dict[str, Any]]: List of deleted object metadata dictionaries, each containing:
                - key (str): S3 object key/path that was deleted
                - e_tag (str): Object ETag before deletion
                - last_modified (float): Unix timestamp of last modification before deletion
                - size (int): Object size in bytes before deletion

        Raises:
            ClientError: If bucket doesn't exist, access is denied, or objects are not found
            Exception: If S3 configuration is invalid

        Warning:
            This operation permanently deletes all objects in the directory and cannot be undone.

        Examples:
            >>> deleted_files = s3.s3_rm_dir('old-documents/', 'my-bucket')
            >>> print(f"Deleted {len(deleted_files)} files")
        """
        if "s3cfg" in kwargs:
            s3_config = kwargs['s3cfg']
        else:
            s3_config = self.config
        s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
        objects = s3bucket.objects.filter(Prefix=dir)
        directory = []
        for obj in objects:
            this_key = obj.key
            this_etag = obj.e_tag
            last_modified = obj.last_modified
            size = obj.size
            request = obj.delete()
            results = {
                "key": this_key,
                "e_tag": this_etag,
                "last_modified": datetime.datetime.timestamp(last_modified),
                "size": size
            }
            directory.append(results)
        return directory


    def s3_cp_dir(self, src_path: str, dst_path: str, bucket: str, **kwargs: Any) -> Dict[str, Dict[str, Any]]:
        """
        Copy an S3 directory to another location within the same bucket.

        Recursively copies all objects from the source directory to the destination
        directory within the same S3 bucket. Original files remain unchanged.

        Args:
            src_path (str): Source directory path/prefix to copy from
            dst_path (str): Destination directory path/prefix to copy to
            bucket (str): Name of the S3 bucket containing the directories
            **kwargs: Additional keyword arguments:
                - s3cfg (Dict[str, Any], optional): S3 configuration override

        Returns:
            Dict[str, Dict[str, Any]]: Dictionary mapping original object keys to metadata
                dictionaries, each containing:
                - key (str): Original source object key
                - e_tag (str): Object ETag after copy
                - last_modified (float): Unix timestamp of copy operation
                - size (int): Object size in bytes (may be None)

        Raises:
            ClientError: If bucket doesn't exist, source objects not found, or access denied
            Exception: If S3 configuration is invalid

        Note:
            The exact source path directory is excluded from copying to avoid copying
            the directory marker itself.

        Examples:
            >>> results = s3.s3_cp_dir('old-docs/', 'backup-docs/', 'my-bucket')
            >>> print(f"Copied {len(results)} files")
        """
        if "s3cfg" in kwargs:
            s3_config = kwargs['s3cfg']
        else:
            s3_config = self.config

        s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
        objects = s3bucket.objects.filter(Prefix=src_path)
        directory = {}
        for obj in objects:
            src_key = obj.key
            dst_key = src_key.replace(src_path, dst_path)
            if src_key != src_path:
                request1 = obj.copy_from(
                    CopySource={
                        "Bucket": bucket,
                        "Key": src_key,
                    },
                    Bucket=bucket,
                    Key=dst_key,
                )

                last_modified = None
                size = None
                this_etag = obj.e_tag
                for item in request1:
                    if item == "CopyObjectResult":
                        for item2 in request1[item]:
                            if item2 == "ETag":
                                e_tag = request1[item][item2]
                            elif item2 == "LastModified":
                                last_modified = request1[item][item2]
                results = {
                    "key": src_key,
                    "e_tag": this_etag,
                    "last_modified": datetime.datetime.timestamp(last_modified),
                    "size": size
                }
                directory[obj.key] = results
        return directory

    def s3_mv_dir(self, src_path: str, dst_path: str, bucket: str, **kwargs: Any) -> Dict[str, Dict[str, Any]]:
        """
        Move an S3 directory to another location within the same bucket.

        Recursively moves all objects from the source directory to the destination
        directory within the same S3 bucket. Original files are deleted after copying.

        Args:
            src_path (str): Source directory path/prefix to move from
            dst_path (str): Destination directory path/prefix to move to
            bucket (str): Name of the S3 bucket containing the directories
            **kwargs: Additional keyword arguments:
                - s3cfg (Dict[str, Any], optional): S3 configuration override

        Returns:
            Dict[str, Dict[str, Any]]: Dictionary mapping original object keys to metadata
                dictionaries, each containing:
                - key (str): Original source object key
                - e_tag (str): Object ETag after move
                - last_modified (float): Unix timestamp of move operation
                - size (int): Object size in bytes (may be None)

        Raises:
            ClientError: If bucket doesn't exist, source objects not found, or access denied
            Exception: If S3 configuration is invalid

        Warning:
            This operation permanently deletes the original files after copying.
            If the copy operation fails, the original files may still be deleted.

        Note:
            The exact source path directory is excluded from moving to avoid moving
            the directory marker itself.

        Examples:
            >>> results = s3.s3_mv_dir('temp-docs/', 'archive-docs/', 'my-bucket')
            >>> print(f"Moved {len(results)} files")
        """
        if "s3cfg" in kwargs:
            s3_config = kwargs['s3cfg']
        else:
            s3_config = self.config

        s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
        objects = s3bucket.objects.filter(Prefix=src_path)
        directory = {}
        for obj in objects:
            src_key = obj.key
            dst_key = src_key.replace(src_path, dst_path)
            if src_key != src_path:
                request1 = obj.copy_from(
                    CopySource={
                        "Bucket": bucket,
                        "Key": src_key,
                    },
                    Bucket=bucket,
                    Key=dst_key,
                )

                last_modified = None
                size = None
                this_etag = obj.e_tag
                for item in request1:
                    if item == "CopyObjectResult":
                        for item2 in request1[item]:
                            if item2 == "ETag":
                                e_tag = request1[item][item2]
                            elif item2 == "LastModified":
                                last_modified = request1[item][item2]
                request2 = obj.delete(
                )
                results = {
                    "key": src_key,
                    "e_tag": this_etag,
                    "last_modified": datetime.datetime.timestamp(last_modified),
                    "size": size
                }
                directory[obj.key] = results
        return directory

    def s3_dl_dir(self, remote_path: str, local_path: str, bucket: str, **kwargs: Any) -> Dict[str, Dict[str, Any]]:
        """
        Download an S3 directory to the local filesystem.

        Recursively downloads all objects within the specified S3 directory to the
        local filesystem. Creates local directory structure as needed.

        Args:
            remote_path (str): S3 directory path/prefix to download from
            local_path (str): Local directory path to download to
            bucket (str): Name of the S3 bucket containing the directory
            **kwargs: Additional keyword arguments:
                - s3cfg (Dict[str, Any], optional): S3 configuration override

        Returns:
            Dict[str, Dict[str, Any]]: Dictionary mapping S3 object keys to metadata
                dictionaries, each containing:
                - key (str): S3 object key that was downloaded
                - last_modified (float): Unix timestamp of last modification
                - size (int): File size in bytes
                - e_tag (str): Object ETag for integrity verification

        Raises:
            ClientError: If bucket or objects don't exist, or access is denied
            IOError: If local files cannot be written
            OSError: If local directory structure cannot be created
            Exception: If S3 configuration is invalid

        Side Effects:
            Creates local directory structure including intermediate directories
            using os.makedirs and os.mkdir as needed.

        Examples:
            >>> results = s3.s3_dl_dir('documents/', '/local/docs/', 'my-bucket')
            >>> print(f"Downloaded {len(results)} files to /local/docs/")
        """
        if "s3cfg" in kwargs:
            s3_config = kwargs['s3cfg']
        else:
            s3_config = self.config
        directory = {}
        s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
        objects = s3bucket.objects.filter(Prefix=remote_path)
        for obj in objects:
            request = obj.get()
            data = request['Body'].read()
            filename = os.path.basename(obj.key)
            if not os.path.exists(local_path):
                os.makedirs(local_path)
            ## split te local path string and make sure that all the sub folders exist
            local_path_split = local_path.split('/')
            for i in range(1, len(local_path_split)):
                local_path_check = os.path.join('/', *local_path_split[:i])
                if not os.path.exists(local_path_check):
                    os.mkdir(local_path_check)

            local_file = os.path.join(local_path, filename)
            with open(local_file, 'wb') as this_file:
                this_file.write(data)
            results = {
                "key": obj.key,
                "last_modified": datetime.datetime.timestamp(obj.last_modified),
                "size": obj.size,
                "e_tag": obj.e_tag,
            }
            directory[obj.key] = results

        return directory

    def s3_ul_dir(self, local_path: str, remote_path: str, bucket: str, **kwargs: Any) -> Dict[str, Dict[str, Any]]:
        """
        Upload a local directory to S3.

        Uploads all files from the specified local directory to the S3 bucket
        under the given remote path prefix.

        Args:
            local_path (str): Local directory path containing files to upload
            remote_path (str): S3 directory path/prefix to upload to
            bucket (str): Name of the S3 bucket to upload to
            **kwargs: Additional keyword arguments:
                - s3cfg (Dict[str, Any], optional): S3 configuration override

        Returns:
            Dict[str, Dict[str, Any]]: Dictionary mapping S3 object keys to metadata
                dictionaries, each containing:
                - key (str): S3 object key where file was uploaded
                - last_modified (float): Unix timestamp of upload
                - size (int): File size in bytes
                - e_tag (str): Object ETag for integrity verification

        Raises:
            ClientError: If bucket doesn't exist or access is denied
            IOError: If local files cannot be read
            OSError: If local directory doesn't exist
            Exception: If upload_file is not a file or S3 configuration is invalid

        Note:
            Only uploads regular files, skips subdirectories. Each file is opened
            in binary mode for upload.

        Examples:
            >>> results = s3.s3_ul_dir('/local/docs/', 'uploaded-docs/', 'my-bucket')
            >>> print(f"Uploaded {len(results)} files")
        """
        if "s3cfg" in kwargs:
            s3_config = kwargs['s3cfg']
        else:
            s3_config = self.config
        s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
        objects = s3bucket.objects.filter(Prefix=remote_path).all()
        files = [os.path.join(local_path, file) for file in os.listdir(local_path)]

        results = {}
        for upload_file in files:
            if os.path.isfile(upload_file):
                file_extension = os.path.splitext(upload_file)[1]
                upload_file = open(upload_file, 'rb')
            else:
                raise Exception("upload_file must be a file")
            upload_key = os.path.join(remote_path, os.path.basename(upload_file.name))
            response = s3bucket.put_object(Key=upload_key, Body=upload_file)
            result = {
                "key": response.key,
                "last_modified": datetime.datetime.timestamp(response.last_modified),
                "size": response.content_length,
                "e_tag": response.e_tag,
            }
            results[response.key] = result
        return results

    def s3_ls_file(self, filekey: str, bucket: str, **kwargs: Any) -> Union[Dict[str, Dict[str, Any]], bool]:
        """
        List metadata for a specific S3 file or files matching a prefix.

        Retrieves metadata for S3 objects that match the specified key prefix.
        Returns False if no matching objects are found.

        Args:
            filekey (str): S3 object key or prefix to search for
            bucket (str): Name of the S3 bucket to search
            **kwargs: Additional keyword arguments:
                - s3cfg (Dict[str, Any], optional): S3 configuration override

        Returns:
            Union[Dict[str, Dict[str, Any]], bool]: 
                - If objects found: Dictionary mapping object keys to metadata dictionaries,
                  each containing:
                  - key (str): S3 object key
                  - last_modified (float): Unix timestamp of last modification
                  - size (int): File size in bytes
                  - e_tag (str): Object ETag for integrity verification
                - If no objects found: False

        Raises:
            ClientError: If bucket doesn't exist or access is denied
            Exception: If S3 configuration is invalid

        Examples:
            >>> metadata = s3.s3_ls_file('documents/report.pdf', 'my-bucket')
            >>> if metadata:
            ...     for key, info in metadata.items():
            ...         print(f"File: {key}, Size: {info['size']} bytes")
            >>> else:
            ...     print("File not found")
        """
        if "s3cfg" in kwargs:
            s3_config = kwargs['s3cfg']
        else:
            s3_config = self.config
        s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
        bucket_objects = s3bucket.objects.filter(Prefix=filekey)
        bucket_object_metadata = bucket_objects.all()
        objects = []
        directory = {}
        for obj in bucket_objects:
            objects.append(obj)
        if len(objects) == 0:
            return False
        for obj in objects:
            metadata = {
                "key": obj.key,
                "last_modified": datetime.datetime.timestamp(obj.last_modified),
                "size": obj.size,
                "e_tag": obj.e_tag,
            }
            directory[obj.key] = metadata
        return directory

    def s3_rm_file(self, this_path: str, bucket: str, **kwargs: Any) -> Dict[str, Any]:
        """
        Delete a specific S3 file.

        Permanently deletes the specified object from the S3 bucket and returns
        metadata about the deleted file.

        Args:
            this_path (str): S3 object key/path to delete
            bucket (str): Name of the S3 bucket containing the file
            **kwargs: Additional keyword arguments:
                - s3cfg (Dict[str, Any], optional): S3 configuration override

        Returns:
            Dict[str, Any]: Deleted file metadata containing:
                - key (str): S3 object key that was deleted
                - e_tag (str): Object ETag before deletion
                - last_modified (float): Unix timestamp of last modification before deletion
                - size (int): File size in bytes before deletion

        Raises:
            ClientError: If bucket or object doesn't exist, or access is denied
            Exception: If S3 configuration is invalid

        Warning:
            This operation permanently deletes the file and cannot be undone.

        Examples:
            >>> result = s3.s3_rm_file('documents/old-report.pdf', 'my-bucket')
            >>> print(f"Deleted file: {result['key']}, Size: {result['size']} bytes")
        """
        if "s3cfg" in kwargs:
            s3_config = kwargs['s3cfg']
        else:
            s3_config = self.config
        s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
        this_object = s3bucket.Object(this_path)
        key = this_object.key
        last_modified = this_object.last_modified
        content_length = this_object.content_length
        e_tag = this_object.e_tag
        request = this_object.delete(
            Key=this_path,
        )
        #print(request)
        results = {
            "key": key,
            "e_tag": e_tag,
            "last_modified": datetime.datetime.timestamp(last_modified),
            "size": content_length,
        }
        return results

    def s3_cp_file(self, src_path: str, dst_path: str, bucket: str, **kwargs: Any) -> Dict[str, Any]:
        """
        Copy an S3 file to another location within the same bucket.

        Copies a single object from the source path to the destination path within
        the same S3 bucket. The original file remains unchanged.

        Args:
            src_path (str): Source S3 object key/path to copy from
            dst_path (str): Destination S3 object key/path to copy to
            bucket (str): Name of the S3 bucket containing the file
            **kwargs: Additional keyword arguments:
                - s3cfg (Dict[str, Any], optional): S3 configuration override

        Returns:
            Dict[str, Any]: Copy operation metadata containing:
                - key (str): Destination object key where file was copied
                - e_tag (str): Object ETag after copy
                - last_modified (float): Unix timestamp of copy operation
                - size (int): File size in bytes

        Raises:
            ClientError: If bucket or source object doesn't exist, or access is denied
            Exception: If S3 configuration is invalid

        Examples:
            >>> result = s3.s3_cp_file('docs/report.pdf', 'backup/report.pdf', 'my-bucket')
            >>> print(f"Copied to: {result['key']}, Size: {result['size']} bytes")
        """
        if "s3cfg" in kwargs:
            s3_config = kwargs['s3cfg']
        else:
            s3_config = self.config
        s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
        this_object = s3bucket.Object(src_path)
        request = this_object.copy_from(
            CopySource={
                "Bucket": bucket,
                "Key": src_path,
            },
            Bucket=bucket,
            Key=dst_path,
        )
        for item in request:
            if item == "CopyObjectResult":
                for item2 in request[item]:
                    if item2 == "ETag":
                        e_tag = request[item][item2]
                    elif item2 == "LastModified":
                        last_modified = request[item][item2]
        key = dst_path
        content_length = this_object.content_length
        results = {
            "key": dst_path,
            "e_tag": e_tag,
            "last_modified": datetime.datetime.timestamp(last_modified),
            "size": content_length,
        }
        return results

    def s3_mv_file(self, src_path: str, dst_path: str, bucket: str, **kwargs: Any) -> Dict[str, Any]:
        """
        Move an S3 file to another location within the same bucket.

        Moves a single object from the source path to the destination path within
        the same S3 bucket. The original file is deleted after copying.

        Args:
            src_path (str): Source S3 object key/path to move from
            dst_path (str): Destination S3 object key/path to move to
            bucket (str): Name of the S3 bucket containing the file
            **kwargs: Additional keyword arguments:
                - s3cfg (Dict[str, Any], optional): S3 configuration override

        Returns:
            Dict[str, Any]: Move operation metadata containing:
                - key (str): Destination object key where file was moved
                - e_tag (str): Object ETag after move
                - last_modified (float): Unix timestamp of move operation
                - size (int): File size in bytes

        Raises:
            ClientError: If bucket or source object doesn't exist, or access is denied
            Exception: If S3 configuration is invalid

        Warning:
            This operation permanently deletes the original file after copying.
            If the copy operation fails, the original file may still be deleted.

        Examples:
            >>> result = s3.s3_mv_file('temp/report.pdf', 'final/report.pdf', 'my-bucket')
            >>> print(f"Moved to: {result['key']}, Size: {result['size']} bytes")
        """
        if "s3cfg" in kwargs:
            s3_config = kwargs['s3cfg']
        else:
            s3_config = self.config
        s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
        this_object = s3bucket.Object(src_path)
        request1 = this_object.copy_from(
            CopySource={
                "Bucket": bucket,
                "Key": src_path,
            },
            Bucket=bucket,
            Key=dst_path,
        )

        content_length = this_object.content_length
        for obj in request1:
            #print(obj)
            if obj == "CopyObjectResult":
                request_result = request1[obj]
                for result in request_result:
                    #print(result)
                    if result == "ETag":
                        e_tag = request_result[result]
                    elif result == "LastModified":
                        last_modified = request_result[result]
                        pass
        request2 = this_object.delete(
        )
        results = {
            "key": dst_path,
            "e_tag": e_tag,
            "last_modified": datetime.datetime.timestamp(last_modified),
            "size": content_length,
        }
        return results


    def s3_dl_file(self, remote_path: str, local_path: str, bucket: str, **kwargs: Any) -> Dict[str, Any]:
        """
        Download an S3 file to the local filesystem.

        Downloads a single file from S3 to the specified local path. Handles S3 URL 
        parsing and creates local directory structure as needed.

        Args:
            remote_path (str): S3 object key/path to download. Supports s3:// URLs which
                will be automatically parsed
            local_path (str): Local filesystem path where the file will be saved
            bucket (str): Name of the S3 bucket containing the file
            **kwargs: Additional keyword arguments:
                - s3cfg (Dict[str, Any], optional): S3 configuration override

        Returns:
            Dict[str, Any]: Download result metadata containing:
                - key (str): S3 object key that was downloaded
                - last_modified (float): Unix timestamp of last modification
                - size (int): File size in bytes
                - e_tag (str): Object ETag for integrity verification
                - local_path (str): Local path where file was saved

        Raises:
            ClientError: If bucket or object doesn't exist, or access is denied
            IOError: If local file cannot be written
            Exception: If S3 configuration is invalid

        Examples:
            >>> result = s3.s3_dl_file('documents/report.pdf', '/local/report.pdf', 'my-bucket')
            >>> print(f"Downloaded {result['size']} bytes to {result['local_path']}")
            
            >>> # Using S3 URL
            >>> result = s3.s3_dl_file('s3://my-bucket/documents/report.pdf', '/local/report.pdf', 'my-bucket')
        """
        if "s3cfg" in kwargs:
            s3_config = kwargs['s3cfg']
        else:
            s3_config = self.config
        if "s3://" in remote_path:
            remote_path = remote_path.replace("s3://", "")
            remote_path = remote_path.replace(bucket + "/", "")

        s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
        this_object = s3bucket.Object(remote_path)
        response = this_object.get()
        data = response['Body'].read()
        with open(local_path, 'wb') as this_file:
            this_file.write(data)
        results = {
            "key": remote_path,
            "last_modified": datetime.datetime.timestamp(this_object.last_modified),
            "size": this_object.content_length,
            "e_tag": this_object.e_tag,
            "local_path": local_path,
        }
        return results

    def s3_ul_file(self, upload_file: str, path: str, bucket: str, **kwargs: Any) -> Dict[str, Any]:
        """
        Upload a local file to S3.

        Uploads a file from the local filesystem or from a byte string to the
        specified S3 bucket and path. Handles both file paths and raw data.

        Args:
            upload_file (str): Either a local file path to upload, or raw bytes data
            path (str): S3 object key/path where the file will be stored
            bucket (str): Name of the S3 bucket to upload to
            **kwargs: Additional keyword arguments:
                - s3cfg (Dict[str, Any], optional): S3 configuration override

        Returns:
            Dict[str, Any]: Upload operation metadata containing:
                - key (str): S3 object key where file was uploaded
                - last_modified (float): Unix timestamp of upload
                - size (int): File size in bytes
                - e_tag (str): Object ETag for integrity verification

        Raises:
            ClientError: If bucket doesn't exist or access is denied
            IOError: If local file cannot be read
            OSError: If temporary file operations fail
            Exception: If S3 configuration is invalid

        Note:
            If upload_file is not a valid file path, it's treated as raw bytes and
            written to a temporary file before upload. File extension is derived
            from the path parameter in this case.

        Examples:
            >>> # Upload local file
            >>> result = s3.s3_ul_file('/local/report.pdf', 'documents/report.pdf', 'my-bucket')
            >>> print(f"Uploaded to: {result['key']}, Size: {result['size']} bytes")
            
            >>> # Upload raw bytes
            >>> data = b"Hello, world!"
            >>> result = s3.s3_ul_file(data, 'text/hello.txt', 'my-bucket')
        """
        if "s3cfg" in kwargs:
            s3_config = kwargs['s3cfg']
        else:
            s3_config = self.config

        if os.path.isfile(upload_file):
            file_extension = os.path.splitext(upload_file)[1]
            upload_file = open(upload_file, 'rb')
        else:
            upload_file = io.BytesIO(upload_file)
            file_extension = os.path.splitext(path)[1]

        with tempfile.NamedTemporaryFile(suffix=file_extension, dir="/tmp") as this_temp_file:
            this_temp_file.write(upload_file.read())
            upload_file = this_temp_file.name

        s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
        response = s3bucket.put_object(Key=path, Body=upload_file)
        results = {
            "key": response.key,
            "last_modified": datetime.datetime.timestamp(response.last_modified),
            "size": response.content_length,
            "e_tag": response.e_tag,
        }
        return results

    def s3_mk_dir(self, path: str, bucket: str, **kwargs: Any) -> Dict[str, Any]:
        """
        Create an S3 directory marker object.

        Creates a zero-byte object at the specified path to serve as a directory
        marker in S3. This is useful for creating empty directory structures.

        Args:
            path (str): S3 directory path to create (should typically end with '/')
            bucket (str): Name of the S3 bucket to create the directory in
            **kwargs: Additional keyword arguments:
                - s3cfg (Dict[str, Any], optional): S3 configuration override

        Returns:
            Dict[str, Any]: Directory creation metadata containing:
                - key (str): S3 object key of the created directory marker
                - last_modified (float): Unix timestamp of creation
                - size (int): Object size (typically 0 for directory markers)
                - e_tag (str): Object ETag

        Raises:
            ClientError: If bucket doesn't exist or access is denied
            Exception: If S3 configuration is invalid

        Note:
            S3 doesn't have true directories, so this creates a zero-byte object
            that serves as a directory placeholder. The path should typically end
            with '/' to indicate it's a directory.

        Examples:
            >>> result = s3.s3_mk_dir('new-folder/', 'my-bucket')
            >>> print(f"Created directory: {result['key']}")
        """
        if "s3cfg" in kwargs:
            s3_config = kwargs['s3cfg']
        else:
            s3_config = self.config
        s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
        response = s3bucket.put_object(Key=path)
        results = {
            "key": response.key,
            "last_modified": datetime.datetime.timestamp(response.last_modified),
            "size": response.content_length,
            "e_tag": response.e_tag,
        }
        return results


    def s3_upload_object(self, f: Any, bucket: str, key: str, s3_config: Any, progress_callback: Any) -> Any:
        s3 = self.get_session(s3_config)
        return s3.upload_fileobj(
            f,
            bucket,
            key,
            Callback=progress_callback
        )

    def s3_download_object(self, f, bucket, key, s3_config, progress_callback):
        s3 = self.get_session(s3_config)
        return s3.download_fileobj(
            bucket,
            key,
            f,
            Callback=progress_callback
        )


    def upload_dir(self, dir: str, bucket: str, s3_config: Any, progress_callback: Any) -> Any:
        s3 = self.get_session(s3_config)
        return s3.upload_file(
            dir,
            bucket,
            progress_callback
        )

    def download_dir(self, dir: str, bucket: str, s3_config: Any, progress_callback: Any) -> Any:
        s3 = self.get_session(s3_config)
        return s3.download_file(
            bucket,
            dir,
            progress_callback
        )

    def s3_read_dir(self, dir: str, bucket: str, s3_config: Any) -> Any:
        s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
        bucket_objects = bucket.objects.filter(Prefix=dir)
        bucket_object_metadata = bucket_objects.all()
        objects = []
        directory = {}
        for obj in bucket_object_metadata:
            objects.append(obj)
        for obj in objects:
            metadata = {
                "key": obj.key,
                "last_modified": datetime.datetime.timestamp(obj.last_modified),
                "size": obj.size,
                "e_tag": obj.e_tag,
            }
            directory[obj.key] = metadata
        return directory

    def s3_download_object(self, f, bucket, key, s3_config, progress_callback):
        s3 = self.get_session(s3_config)
        return s3.download_fileobj(
            bucket,
            key,
            f,
            Callback=progress_callback
        )

    def s3_mkdir(self, dir: str, bucket: str, s3_config: Any) -> Any:
        s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
        return s3bucket.put_object(Key=dir)

    def get_session(self, s3_config: Dict[str, Any]) -> Any:
        """
        Create or retrieve an S3 session with the provided configuration.

        Manages S3 session creation and caching. Creates a new boto3 client session
        if one doesn't exist, or returns the existing cached session.

        Args:
            s3_config (Dict[str, Any]): S3 configuration dictionary containing connection
                parameters. Will be converted to boto3 format using config_to_boto.

        Returns:
            Any: boto3 S3 client session configured with the provided parameters

        Raises:
            Exception: If s3_config is invalid or missing required keys
            ClientError: If S3 connection cannot be established

        Note:
            Session is cached in self.session to avoid recreating connections for
            subsequent operations.

        Examples:
            >>> config = {'accessKey': 'key', 'secretKey': 'secret', 'endpoint': 'https://s3.amazonaws.com'}
            >>> session = s3.get_session(config)
        """

        if "session" not in self.__dict__:
            self.session = Session().client(**self.config_to_boto(s3_config))
        return self.session

    def config_to_boto(self, s3_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert S3 configuration dictionary to boto3-compatible format.

        Transforms various S3 configuration formats into the standardized boto3 client
        configuration format. Supports both legacy and boto3 configuration key names.

        Args:
            s3_config (Dict[str, Any]): S3 configuration dictionary in one of two formats:
                Legacy format:
                    - accessKey (str): AWS access key ID
                    - secretKey (str): AWS secret access key
                    - endpoint (str): S3 endpoint URL
                Boto3 format:
                    - aws_access_key_id (str): AWS access key ID
                    - aws_secret_access_key (str): AWS secret access key
                    - endpoint_url (str): S3 endpoint URL

        Returns:
            Dict[str, Any]: boto3-compatible configuration dictionary containing:
                - service_name (str): Always 's3'
                - aws_access_key_id (str): AWS access key ID
                - aws_secret_access_key (str): AWS secret access key
                - endpoint_url (str): S3 endpoint URL

        Raises:
            Exception: If s3_config doesn't contain required keys in either format

        Side Effects:
            Sets self.config to the converted configuration for caching

        Examples:
            >>> # Legacy format
            >>> legacy_config = {'accessKey': 'key', 'secretKey': 'secret', 'endpoint': 'https://s3.amazonaws.com'}
            >>> boto_config = s3.config_to_boto(legacy_config)
            
            >>> # Boto3 format
            >>> boto3_config = {'aws_access_key_id': 'key', 'aws_secret_access_key': 'secret', 'endpoint_url': 'https://s3.amazonaws.com'}
            >>> boto_config = s3.config_to_boto(boto3_config)
        """
        if "accessKey" in s3_config.keys():
            results = dict(
                service_name = 's3',
                aws_access_key_id = s3_config['accessKey'],
                aws_secret_access_key = s3_config['secretKey'],
                endpoint_url = s3_config['endpoint'],
            )
            self.config = results
            return results
        elif "aws_access_key_id" in s3_config.keys():
            results = dict(
                service_name = 's3',
                aws_access_key_id = s3_config['aws_access_key_id'],
                aws_secret_access_key = s3_config['aws_secret_access_key'],
                endpoint_url = s3_config['endpoint_url'],
            )
            self.config = results
            return results
        else:
            raise Exception("s3_config must contain accessKey, secretKey, and endpoint")
