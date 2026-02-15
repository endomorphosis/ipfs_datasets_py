

import argparse
from utils.config_parser.config_parser import ConfigParser

from __version__ import __version__

def run_with_argparse():

    parser = argparse.ArgumentParser(
            prog="convert_to_txt_based_on_mime_type",
            formatter_class=argparse.MetavarTypeHelpFormatter,
            description="Convert files into text documents based on their MIME type. Format of the text documents will be Markdown."
        )
    parser.add_argument("input-folder", 
                        type=str, 
                        default="input", 
                        help="Path to the folder containing the files to be converted. Defaults to 'input', the name of the input folder in the working directory.")
    parser.add_argument("output-folder", 
                        type=str, 
                        default="output", 
                        help="Path to the folder where the converted files will be saved. Defaults to 'output', the name of the output folder in the working directory.")
    parser.add_argument("--max-memory", 
                        type=int, 
                        default=1024, 
                        help="Maximum amount of memory in Megabytes the program can use at any one time. Defaults to 1024 MB.")
    parser.add_argument("--conversion-timeout", 
                        type=int, 
                        default=30, 
                        help="Maximum amount of time in seconds an API-bounded conversion can run before it is terminated. Defaults to 30 seconds.")
    parser.add_argument("--log-level", 
                        type=str, 
                        default="INFO", 
                        help="Level of logging to be used. Defaults to 'INFO'.")
    parser.add_argument("--max-connections-per-api", 
                        type=int, 
                        default=3, 
                        help="Maximum number of concurrent API connections the program can have at any one time. Defaults to 3.")
    parser.add_argument("--max-threads", 
                        type=int, 
                        default=4, 
                        help="Maximum number of threads to be used for processing the program can use at any one time. Defaults to 4.")
    parser.add_argument("--batch-size", 
                        type=int, 
                        default=1024, 
                        help="Number of files to be processed in a single batch. Defaults to 1024.")
    parser.add_argument("--llm-api-key", 
                        type=str, 
                        default="abcde123456", 
                        help="API key for the LLM API. Defaults to 'abcde123456'.")
    parser.add_argument("--llm-api-url", 
                        type=str, 
                        default="www.example.com", 
                        help="URL for the LLM API. Defaults to 'www.example.com'.")
    parser.add_argument("--use-docintel", 
                        action="store_true", 
                        help="Use Document Intelligence to extract text instead of offline conversion. Requires a valid Document Intelligence Endpoint. Defaults to False.")
    parser.add_argument("--docintel-endpoint", 
                        type=str, 
                        default="www.example2.com", 
                        help="Document Intelligence Endpoint. Required if using Document Intelligence. Defaults to 'www.example2.com'.")
    parser.add_argument("-v", "--version", 
                        action="version", 
                        version=f"{__version__}", 
                        help="Show program's version number and exit.")
    parser.add_argument("--pool-refresh-rate", 
                        type=int, 
                        default=60, 
                        help="Refresh rate in seconds for refreshing resources in the Pools. Defaults to 60 seconds.")
    parser.add_argument("--pool-health-check-rate", 
                        type=int, 
                        default=30, 
                        help="Health check rate in seconds for checking resources in the Pools. Defaults to 30 seconds.")
    parser.add_argument("--print_configs_on_startup",
                        type=bool,
                        default=False, 
                        help="Print the program configs to console on start-up. Sensitive values like API keys will be [REDACTED]. Defaults to False.")
    args = parser.parse_args()

    config_parser = ConfigParser()
    return config_parser.parse_command_line(args)