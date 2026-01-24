from itertools import batched
from concurrent.futures import ThreadPoolExecutor
from tests._test_utils import get_ast_tree, BadDocumentationError

import anyio
from pathlib import Path
import importlib
import importlib.util as importlib_util
import csv
import sys

def _save_to_csv(file_path, data: tuple[str]):
    """
    Save the given data to a CSV file at the specified path.
    """
    with open(file_path, mode='w', newline='') as file:
        writer = csv.writer(file)
        for row in data:
            writer.writerow(row)

async def main():
    """
    This function is a placeholder for test tasks.
    """
    this_dir = Path(__file__).parent
    auto_generated_dir = this_dir / "tests" / "auto_generated"
    bad_files = []

    try:
        for file in auto_generated_dir.glob("*.py"):
            print(f"Processing file: {file.name}")
            if not file.name.startswith("test_"):
                continue

            try:
                # Try to compile the file to check for syntax errors
                try:
                    compile(file.read_text(), file.name, 'exec')
                except SyntaxError as e:
                    print(f"Syntax error in {file.name}: {e}")
                    bad_files.append((file.resolve(), type(e).__name__ , str(e)))
                    continue
                except Exception as e:
                    print(f"Error compiling {file.name}: {e}")
                    bad_files.append((file.resolve(), type(e).__name__ , str(e)))
                    continue

                # Try to import it to check for import errors
                try:
                    module_name = file.stem
                    spec = importlib_util.spec_from_file_location(module_name, file)
                    if spec is None:
                        print(f"Could not find spec for {file.name}")
                        bad_files.append((file.resolve(), "ImportError" ,"Could not find spec"))
                        continue
                    module = importlib_util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                except ImportError as e:
                    print(f"Import error in {file.name}: {e}")
                    bad_files.append((file.resolve(), type(e).__name__ , str(e)))
                    continue
                except Exception as e:
                    print(f"Unexpected Error importing {file.name}: {e}")
                    bad_files.append((file.resolve(), type(e).__name__ , str(e)))
                    continue

                # Run them to check for runtime errors
                # This should throw attribute errors for all those assert statements.
                if "if __name__ == '__main__':" in file.read_text():
                    try:
                        with open(file, 'r') as f:
                            code = f.read()
                        exec(code, module.__dict__)
                    except AttributeError as e:
                        print(f"Attribute error in {file.name}: {e}")
                        bad_files.append((file.resolve(), type(e).__name__ , str(e)))
                        continue
                    except Exception as e: 
                        print(f"Runtime error in {file.name}: {e}")
                        bad_files.append((file.resolve(), type(e).__name__ , str(e)))
                        continue
            except Exception as e:
                continue # NO BREAKS
            finally:
                # Ensure the module is cleaned up after each test
                if module_name in sys.modules:
                    del sys.modules[module_name]
    finally:
        # Save the results to a CSV file
        csv_file_path = this_dir / "test_results.csv"
        _save_to_csv(csv_file_path, bad_files)

        # Perform maintenance tasks on each file
        print(f"Found {len(bad_files)} test files with issues.")


if __name__ == "__main__":
    try:
        anyio.run(main())
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
        exit(0)
    except Exception as e:
        import traceback
        print(f"Error: {e}\n{traceback.format_exc()}")
        exit(1)
    else:
        print("Process completed successfully.")
        exit(0)
