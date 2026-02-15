

# import json
# from pathlib import Path


# import yaml


# # TODO Fix so that it actually can load the JSON as a string.
# # Right now, it's just loading the first one due to how it's structured.
# def make_json_from_log_file(log_file_path: Path, output_json_path: Path) -> None:
#     """
#     Reads a JSON-formatted log file and writes its contents to a new JSON file.

#     This function attempts to read a JSON-formatted log file, parse its contents,
#     and then write the parsed data to a new JSON file with proper formatting.

#     Args:
#         log_file_path (Path): The path to the input log file containing JSON data.
#         output_json_path (Path): The path where the formatted JSON file will be written.

#     Raises:
#         FileNotFoundError: If the input log file does not exist.
#     """

#     if log_file_path.exists():
#         try:
#             with open(log_file_path, 'r') as log_file:
#                 json_as_str = yaml.load(log_file.read(), Loader=yaml.FullLoader)
#             print(f"json_as_str: {json_as_str}")
#         except Exception as e:
#             print(f"The file {log_file_path} is not a valid JSON file: {e}")
#             return
#     else:
#         raise FileNotFoundError(f"The file {log_file_path} does not exist or is at a different path than specified.")

#     if not output_json_path.exists():
#         output_json_path.touch(exist_ok=True)

#     try:
#         with open(output_json_path, 'w') as json_file:
#             json_file.write(json.dumps(json_as_str, indent=4))
#     except Exception as e:
#         print(f"An error occurred while writing to the JSON file: {e}")
#         return
