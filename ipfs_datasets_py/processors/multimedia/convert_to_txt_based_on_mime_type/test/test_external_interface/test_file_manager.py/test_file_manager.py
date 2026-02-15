
import asyncio
from concurrent.futures import ProcessPoolExecutor
import os
from pathlib import Path
import shutil
import tempfile


import pytest


from pydantic_models.configs import Configs
from external_interface.file_paths_manager.file_paths_manager import (
    FilePathsManager
)
from fixtures.mock_input_output_directory import mock_input_output_directory


from utils.common.asyncio_coroutine import asyncio_coroutine
from logger.logger import Logger
logger = Logger(__name__)


# 1. Test Instantiation
@pytest.mark.parametrize("configs", [
    Configs(batch_size=10, input_folder="input", output_folder="output", max_workers=4, max_queue_size=2048)
])
def test_file_paths_manager_initialization(configs: Configs):
    file_manager = FilePathsManager(configs)

    # Test input and output folders
    assert file_manager._input_folder == Path("input")
    assert file_manager._output_folder == Path("output")

    # Test max queue size
    assert file_manager._max_queue_size == 2048

    # Test logger
    assert file_manager._logger is not None
    assert callable(file_manager._logger.info)
    assert callable(file_manager._logger.error)

    # Test DuckDB connection
    assert file_manager._duck_db_path is not None
    # NOTE DuckDB connections persist until explicitly closed,
    # so we ignore these until the rest of the class has been successfully debugged.
    # assert hasattr(file_manager.duck_db, 'execute')
    # assert hasattr(file_manager.duck_db, 'fetchall')

    # Test asyncio queues
    assert isinstance(file_manager.get_inputs_queue, asyncio.Queue)
    assert isinstance(file_manager.extract_metadata_queue, asyncio.Queue)
    assert isinstance(file_manager.output_queue, asyncio.Queue)
    assert file_manager.get_inputs_queue.maxsize == 2048
    assert file_manager.extract_metadata_queue.maxsize == 2048
    assert file_manager.output_queue.maxsize == 10 # batch size because we want to batch outputs.



# 2. Test File Detection
# Criteria: All files in the input folder and sub-folders must be detected.
# NOTE We assume that the input folder contains files and sub-folders.



@pytest.fixture
def test_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a directory structure
        os.makedirs(os.path.join(tmpdir, "subfolder1"))
        os.makedirs(os.path.join(tmpdir, "subfolder2", "subsubfolder"))

        # Create some files
        open(os.path.join(tmpdir, "file1.txt"), "w").close()
        open(os.path.join(tmpdir, "subfolder1", "file2.txt"), "w").close()
        open(os.path.join(tmpdir, "subfolder2", "file3.txt"), "w").close()
        open(os.path.join(tmpdir, "subfolder2", "subsubfolder", "file4.txt"), "w").close()

        yield Path(tmpdir)

import os
import pytest
from pathlib import Path


@pytest.fixture
def test_files_all_valid(tmp_path: Path):
    # Create temporary test files
    valid_path1 = tmp_path / "valid1.txt"
    valid_path2 = tmp_path / "valid2.txt"
    valid_path3 = tmp_path / "valid3.txt"

    # Create the actual files
    valid_path1.write_text("test content")
    valid_path2.write_text("test content")
    valid_path3.write_text("test content")

    # Set read permissions explicitly
    os.chmod(valid_path1, 0o644)  # User read/write, group/others read
    os.chmod(valid_path2, 0o644)
    os.chmod(valid_path3, 0o644)

    # Return a list of Paths
    return [valid_path1, valid_path2, valid_path3]


@pytest.fixture
def test_files(tmp_path: Path):
    # Create temporary test files
    valid_path1 = tmp_path / "valid1.txt"
    valid_path2 = tmp_path / "valid2.txt"
    invalid_path = tmp_path / "invalid.IDENTIFIER"  # unsupported extension

    # Create the actual files
    valid_path1.write_text("test content")
    valid_path2.write_text("test content")
    invalid_path.write_text("test content")

    # Set read permissions explicitly
    os.chmod(valid_path1, 0o644)  # User read/write, group/others read
    os.chmod(valid_path2, 0o644)
    os.chmod(invalid_path, 0o000)  # No permissions (should fail validation)

    # Return a list of Paths
    return [valid_path1, valid_path2, invalid_path]


def test_file_detection(test_directory: Path):
    configs = Configs(batch_size=10, input_folder=test_directory, output_folder="output", max_workers=4, max_queue_size=2048)
    file_manager = FilePathsManager(configs)

    # Call the method that detects and gets files (assuming it's called scan_for_files)
    # Now it returns a generator instead of a list
    file_generator = file_manager.scan_for_files()

    test_directory = Path(test_directory)
    # Define the expected files
    expected_files = {
        test_directory / "file1.txt",
        test_directory / "subfolder1" / "file2.txt",
        test_directory / "subfolder2" / "file3.txt",
        test_directory / "subfolder2" / "subsubfolder" / "file4.txt"
    }

    # Use a set to collect detected files
    detected_files = set()

    # Iterate through the generator
    for file in file_generator:
        detected_files.add(file)

    # Check if all expected files are detected
    assert detected_files == expected_files

    # Optionally, you can check the count of files
    assert len(detected_files) == len(expected_files)


def test_empty_directory(test_directory: Path):
    # Remove all files and subdirectories
    for root, dirs, files in os.walk(test_directory, topdown=False):
        for name in files:
            os.remove(os.path.join(root, name))
        for name in dirs:
            os.rmdir(os.path.join(root, name))

    configs = Configs(batch_size=10, input_folder=test_directory, output_folder="output", max_workers=4, max_queue_size=2048)
    file_manager = FilePathsManager(configs)

    # Assuming scan_for_files now returns a generator
    file_generator = file_manager.scan_for_files()

    # Convert generator to list to check its length
    detected_files = list(file_generator)

    assert len(detected_files) == 0

    # Alternatively, if you want to avoid converting to a list:
    # assert sum(1 for _ in file_generator) == 0

def test_hidden_files(test_directory: Path):
    # Create a hidden file
    hidden_file = test_directory / ".hidden_file.txt"
    open(hidden_file, "w").close()

    configs = Configs(batch_size=10, input_folder=test_directory, output_folder="output", max_workers=4, max_queue_size=2048)
    file_manager = FilePathsManager(configs)

    # Assuming scan_for_files now returns a generator
    file_generator = file_manager.scan_for_files()

    # Collect all files from the generator
    detected_files = [file for file in file_generator]

    assert hidden_file in detected_files

    # Optional: You might want to add an assertion to check if other expected files are also present
    # For example:
    assert len(detected_files) > 1  # Ensures other files are also detected

# NOTE Had to turn on developer mode in windows to test this.
def test_ignore_symlinks(test_directory: Path):
    # Create a symlink
    os.symlink(test_directory / "file1.txt", test_directory / "symlink.txt")

    configs = Configs(batch_size=10, input_folder=test_directory, output_folder="output", max_workers=4, max_queue_size=2048)
    file_manager = FilePathsManager(configs)

    # Assuming scan_for_files now returns a generator
    file_generator = file_manager.scan_for_files()

    # Collect all files from the generator
    detected_files = [file for file in file_generator]

    # Change the assertion to verify that the symlink is NOT in the detected files
    assert test_directory / "symlink.txt" not in detected_files

    # Optional: Add an additional assertion to verify the target file IS detected
    assert test_directory / "file1.txt" in detected_files

import pytest
import asyncio
from pathlib import Path
from pydantic import ValidationError

from pydantic_models.file_paths_manager.file_path import FilePath
from external_interface.file_paths_manager.file_paths_manager import FilePathsManager


@pytest.mark.asyncio
async def test_get_inputs(monkeypatch: pytest.MonkeyPatch, test_files):

    # Mock FilePathsManager and its methods
    class MockFilePathsManager(FilePathsManager):
        def __init__(self):
            self.extract_metadata_queue = asyncio.Queue()
            self._logger = MockLogger()

        def scan_for_files(self):
            yield from test_files

    class MockLogger:
        def __init__(self):
            self.error_messages = []

        def error(self, message):
            self.error_messages.append(message)

    # Create instance of mock FilePathsManager
    fpm = MockFilePathsManager()

    # Mock FilePath validation
    def mock_filepath_validation(file_path):
        if "invalid" in str(file_path):
            errors = [{'loc': ('file_path',), 'msg': r'^Invalid file path.*', 'type': 'value_error'}]
            raise ValidationError(errors, FilePath)
        return FilePath(file_path=file_path)

    # Patch FilePath with mock validation
    monkeypatch.setattr("pydantic_models.file_paths_manager.file_path.FilePath", mock_filepath_validation)

    # Run the get_inputs method
    await fpm.get_inputs()

    # Check if valid paths were added to extract_metadata_queue
    assert fpm.extract_metadata_queue.qsize() == 2

    # Check error was logged
    assert len(fpm._logger.error_messages) == 1
    assert "Invalid file path" in fpm._logger.error_messages[0]

    # Check if the paths in extract_metadata_queue are correct
    paths = []
    while not fpm.extract_metadata_queue.empty():
        paths.append(await fpm.extract_metadata_queue.get())

    valid_test_files = [f for f in test_files if "invalid" not in str(f)]
    assert all(FilePath(file_path=f) in paths for f in valid_test_files)

    # Check if invalid path was logged
    assert len(fpm._logger.error_messages) == 1
    assert "Invalid file path" in fpm._logger.error_messages[0]

    # Check if get_inputs_queue is empty after processing
    assert fpm.extract_metadata_queue.empty()

@pytest.mark.asyncio
async def test_get_inputs_empty_directory():

    class MockLogger:
        def __init__(self):
            self.error_messages = []

        def error(self, message):
            self.error_messages.append(message)

    class MockEmptyFilePathsManager(FilePathsManager):
        def __init__(self):
            self.get_inputs_queue = asyncio.Queue()
            self.extract_metadata_queue = asyncio.Queue()
            self._logger = MockLogger()

        def scan_for_files(self):
            return []

    fpm = MockEmptyFilePathsManager()
    await fpm.get_inputs()

    assert fpm.extract_metadata_queue.empty()
    assert fpm.get_inputs_queue.empty()

@pytest.mark.asyncio
async def test_get_inputs_all_invalid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):

    class MockLogger:
        def __init__(self):
            self.error_messages = []

        def error(self, message):
            self.error_messages.append(message)

    class MockInvalidFilePathsManager(FilePathsManager):
        def __init__(self):
            self.get_inputs_queue = asyncio.Queue()
            self.extract_metadata_queue = asyncio.Queue()
            self._logger = MockLogger()

        def scan_for_files(self):
            return [Path("/invalid/path1.txt"), Path("/invalid/path2.txt")]

    fpm = MockInvalidFilePathsManager()

    def mock_invalid_filepath_validation(path):
        raise ValidationError("Invalid path")

    monkeypatch.setattr("pydantic_models.file_paths_manager.file_path.FilePath", mock_invalid_filepath_validation)

    await fpm.get_inputs()

    assert fpm.extract_metadata_queue.empty()
    assert len(fpm._logger.error_messages) == 2
    assert all("Invalid file path" in msg for msg in fpm._logger.error_messages)

from pydantic_models.file_paths_manager.file_path_and_metadata import FilePathAndMetadata


@pytest.mark.asyncio
async def test_extract_metadata(test_directory):
    configs = Configs(batch_size=10, input_folder=test_directory, output_folder="output", max_workers=4, max_queue_size=2048)

    fpm = FilePathsManager(configs)

    await fpm.extract_metadata()

    assert fpm.extract_metadata_queue.empty()
    assert fpm.processing_queue.qsize() == 4
    check_set = set()

    while not fpm.processing_queue.empty():
        path_with_metadata: FilePathAndMetadata = await fpm.processing_queue.get()

        assert isinstance(path_with_metadata, FilePathAndMetadata)

        assert isinstance(path_with_metadata.cid, str)
        assert len(path_with_metadata.cid) == 59

        assert path_with_metadata.file_name
        assert path_with_metadata.file_extension
        assert path_with_metadata.mime_type
        assert path_with_metadata.file_size == 0
        assert path_with_metadata.checksum
        assert path_with_metadata.created_timestamp
        assert path_with_metadata.modified_timestamp

        cid = path_with_metadata.cid
        logger.debug(f"cid: {cid}")
        check_set.add(cid)

    # 3. Test Repeat File Detection
    # Criteria: Files with the same name in different sub-folders must be detected.
    # CID generation
    # NOTE Because files in sub-folders can have the same name, we base the CID off of the whole path.

    # Make sure all CIDs are unique
    logger.debug(f"check_set: {check_set}")
    assert len(check_set) == 4



import pytest
from pathlib import Path
from pydantic_models.file_paths_manager.file_path_and_metadata import FilePathAndMetadata
from external_interface.file_paths_manager.file_paths_manager import FilePathsManager
from pydantic_models.configs import Configs


@pytest.fixture
def file_paths_manager_fixture():
    configs = Configs(batch_size=10, input_folder="input", output_folder="output", max_workers=4, max_queue_size=2048)
    return FilePathsManager(configs), configs

@pytest.fixture
def test_proc_methods_files(tmp_path: Path):
    # Create temporary test files
    valid_path1 = tmp_path / "valid1.txt"
    valid_path2 = tmp_path / "valid2.txt"
    invalid_path = tmp_path / "invalid.IDENTIFIER"  # unsupported extension
    subfolder_valid_path1 = tmp_path / "subfolder" / "valid1.txt" # Same file, different subdirectories

    # Create the actual files
    valid_path1.write_text("test content")
    valid_path2.write_text("test content")
    invalid_path.write_text("test content")

    subfolder_valid_path1.parent.mkdir(parents=True, exist_ok=True)
    subfolder_valid_path1.write_text("test content")

    # Set read permissions explicitly
    os.chmod(valid_path1, 0o644)  # User read/write, group/others read
    os.chmod(valid_path2, 0o644)
    os.chmod(subfolder_valid_path1, 0o644)

    os.chmod(invalid_path, 0o000)  # No permissions (should fail validation)

    # Create mock output folder
    output_folder = tmp_path / "output"
    output_folder.mkdir(parents=True, exist_ok=True)

    # Write one file in the output folder that is the same as in the test_proc_methods_files
    output_valid_path1 = output_folder / "valid1.txt"
    output_valid_path1.write_text("test content")
    os.chmod(output_valid_path1, 0o644)

    # Return a dict of Paths
    return {
        "valid1": valid_path1,
        "valid2": valid_path2,
        "invalid": invalid_path,
        "subfolder_valid_path1": subfolder_valid_path1,
        "output_folder": output_folder,
        "output_valid1": output_valid_path1
    }


@pytest.mark.asyncio
async def test_requires_processing_new_file(file_paths_manager_fixture, test_proc_methods_files):

    file_paths_manager: FilePathsManager = file_paths_manager_fixture[0]
    configs: Configs = file_paths_manager_fixture[1]

    # Test case for a new file that hasn't been processed
    file_path = FilePath(file_path=Path(test_proc_methods_files['valid1']))
    input_path = FilePathAndMetadata(
        max_program_memory=configs.max_program_memory,
        file_path=file_path,
    )

    result = file_paths_manager.requires_processing(input_path)
    assert result == True

# 4. Test Repeat File Prevention


@pytest.mark.asyncio
async def test_requires_processing_existing_file(mock_input_output_directory):

    input_dir, output_dir = mock_input_output_directory
    configs = Configs(batch_size=10, input_folder=input_dir, output_folder=output_dir, max_workers=4, max_queue_size=2048)

    file_paths_manager = FilePathsManager(configs)
    already_processed_path = input_dir / "data" / "already_processed.csv"

    # Test case for a file that has already been processed
    file_path = FilePath(file_path=already_processed_path)
    input_path = FilePathAndMetadata(
        max_program_memory=configs.max_program_memory,
        file_path=file_path,
    )

    result = file_paths_manager.requires_processing(input_path)
    assert result == False


@pytest.mark.asyncio
async def test_requires_processing_invalid_input(file_paths_manager_fixture):

    file_paths_manager: FilePathsManager = file_paths_manager_fixture[0]
    configs: Configs = file_paths_manager_fixture[1]

    # Test case for invalid input (None).
    # Skip invalid inputs. NO BREAKS
    result = file_paths_manager.requires_processing(None)
    assert result == False

import pytest
import asyncio
from pydantic_models.file_paths_manager.file_path_and_metadata import FilePathAndMetadata
from pydantic_models.configs import Configs


@pytest.mark.asyncio
async def test_make_batch_empty_queue(mock_input_output_directory):
    """
    Test make_batch when processing_queue is empty.
    """
    input_dir, output_dir = mock_input_output_directory

    configs = Configs(batch_size=10, input_folder=input_dir, output_folder=output_dir, max_workers=4, max_queue_size=2048)
    file_manager = FilePathsManager(configs)

    await file_manager.make_batch()

    batches = await file_manager.output_queue.get()
    print(f"batches: {batches}")
    assert len(batches) == 0


@pytest.mark.asyncio
async def test_make_batch_full_batch(test_files_all_valid):
    """
    Test make_batch when a full batch can be created.
    """
    configs = Configs(batch_size=2, input_folder="input", output_folder="output", max_workers=4, max_queue_size=2048)
    file_manager = FilePathsManager(configs)

    # Mock the required methods
    file_manager.get_inputs = asyncio_coroutine(lambda: None)
    file_manager.extract_metadata = asyncio_coroutine(lambda: None)
    file_manager.requires_processing = lambda x: True

    # Add items to the processing_queue
    for path in test_files_all_valid:
        file_path = FilePath(file_path=path)
        await file_manager.processing_queue.put(
            FilePathAndMetadata(
                max_program_memory=configs.max_program_memory,
                file_path=file_path
            )
        )

    await file_manager.make_batch()

    batches = [batch for batch in file_manager.output_queue.get_nowait()]
    assert len(batches) == 2
    assert len(batches[0]) == 2
    assert len(batches[1]) == 1

@pytest.mark.asyncio
async def test_make_batch_partial_batch(test_files_all_valid):
    """
    Test make_batch when only a partial batch can be created.
    """
    configs = Configs(batch_size=3, input_folder="input", output_folder="output", max_workers=4, max_queue_size=2048)
    file_manager = FilePathsManager(configs)

    # Mock the required methods
    file_manager.get_inputs = asyncio_coroutine(lambda: None)
    file_manager.extract_metadata = asyncio_coroutine(lambda: None)
    file_manager.requires_processing = lambda x: True

    # Add items to the processing_queue
    for path in test_files_all_valid:
        file_path = FilePath(file_path=path)
        await file_manager.processing_queue.put(
            FilePathAndMetadata(
                max_program_memory=configs.max_program_memory,
                file_path=file_path
            )
        )

    # Remove 1 of the 3 files in test_files.
    _  = await file_manager.processing_queue.get_nowait()
    await file_manager.make_batch()

    batches = [batch for batch in file_manager.output_queue.get_nowait()]
    logger.debug(f"batches: {batches}")
    assert len(batches) == 1
    assert len(batches[0]) == 2

@pytest.mark.asyncio
async def test_make_batch_skip_processing(test_files_all_valid):
    """
    Test make_batch when some items don't require processing.
    """
    configs = Configs(batch_size=2, input_folder="input", output_folder="output", max_workers=4, max_queue_size=2048)
    file_manager = FilePathsManager(configs)

    # Mock the required methods
    file_manager.get_inputs = asyncio_coroutine(lambda: None)
    file_manager.extract_metadata = asyncio_coroutine(lambda: None)
    file_manager.requires_processing = lambda x: x.file_path != "valid1.txt"

    # Add items to the processing_queue
    for path in test_files_all_valid:
        file_path = FilePath(file_path=path)
        await file_manager.processing_queue.put(
            FilePathAndMetadata(
                max_program_memory=configs.max_program_memory,
                file_path=file_path
            )
        )

    await file_manager.make_batch()
    batches = [batch for batch in file_manager.output_queue.get_nowait()]

    assert len(batches) == 1
    assert len(batches[0]) == 2
    assert all(item.file_path != "valid.txt" for item in batches[0])

@pytest.mark.asyncio
async def test_make_batch_multiple_iterations():
    """
    Test make_batch with multiple iterations of the while loop.
    """
    configs = Configs(batch_size=2, input_folder="input", output_folder="output", max_workers=4, max_queue_size=2048)
    file_manager = FilePathsManager(configs)

    # Mock the required methods
    file_manager.get_inputs = asyncio_coroutine(lambda: None)
    file_manager.extract_metadata = asyncio_coroutine(lambda: None)
    file_manager.requires_processing = lambda x: True

    # Simulate multiple iterations by adding items in batches
    async def add_items():
        for i in range(5):
            await file_manager.processing_queue.put(FilePathAndMetadata(file_path=f"file{i}.txt"))
            if i % 2 == 1:
                await asyncio.sleep(0.1)  # Small delay to allow for iteration

    asyncio.create_task(add_items())

    await file_manager.make_batch()
    batches = [batch for batch in file_manager.output_queue.get_nowait()]

    assert len(batches) == 3
    assert all(len(batch) <= 2 for batch in batches)
    assert sum(len(batch) for batch in batches) == 5


# @pytest.fixture
# def test_directory_with_repeats(tmp_path):
#     # Create a directory structure with repeat file names
#     (tmp_path / "subfolder1").mkdir()
#     (tmp_path / "subfolder2").mkdir()

#     # Create files with the same name in different subfolders
#     (tmp_path / "subfolder1" / "repeat_file.txt").write_text("content1")
#     (tmp_path / "subfolder2" / "repeat_file.txt").write_text("content2")
#     (tmp_path / "unique_file.txt").write_text("content3")

#     return tmp_path

# @pytest.mark.asyncio
# async def test_repeat_file_prevention(test_directory_with_repeats):
#     configs = Configs(
#         batch_size=2,
#         input_folder=str(test_directory_with_repeats),
#         output_folder="output",
#         max_workers=4,
#         max_queue_size=2048
#     )
#     file_manager = FilePathsManager(configs)

#     # Populate the processing_queue with FilePathAndMetadata objects
#     for file_path in test_directory_with_repeats.rglob('*.txt'):
#         metadata = FilePathAndMetadata(
#             file_path=str(file_path),
#             cid="dummy_cid",
#             file_name=file_path.name,
#             file_extension=file_path.suffix,
#             mime_type="text/plain",
#             file_size=0,
#             checksum="dummy_checksum",
#             created_timestamp="2023-01-01",
#             modified_timestamp="2023-01-01"
#         )
#         await file_manager.processing_queue.put(metadata)

#     # Call the method that generates batches (assuming it's called generate_batches)
#     batches = await file_manager.generate_batches()

#     # Check that files with the same name are not in the same batch
#     for batch in batches:
#         file_names = [item.file_name for item in batch]
#         assert len(file_names) == len(set(file_names)), "Duplicate file names found in a single batch"

#     # Check that all files are included in the batches
#     all_files = set(file_path.name for file_path in test_directory_with_repeats.rglob('*.txt'))
#     batched_files = set(item.file_name for batch in batches for item in batch)
#     assert all_files == batched_files, "Not all files were included in the batches"

#     # Check that the batch size is respected
#     for batch in batches:
#         assert len(batch) <= configs.batch_size, f"Batch size {len(batch)} exceeds configured size {configs.batch_size}"


# 4. Test Batch Generation
# Criteria: batches must of size to equal or lesser than the batch size specified in the configs.
# If the batch size is larger than the total files, all files should be in one batch.
# If the batch size is smaller than the total number files, each batch must NOT contain repeat files.

# 5. Test File Attribute Generation
# Criteria: Each file must have a CID, a path, and a batch number.

# 6. Handle Validation

# 7. Cross-Platform Support for Windows and Linux.

# 8. Invalid Paths are logged and ignored.

# 9. Inaccessible Paths are logged and ignored.

# 11. Files Larger than the memory allocated to the program are logged and ignored.
