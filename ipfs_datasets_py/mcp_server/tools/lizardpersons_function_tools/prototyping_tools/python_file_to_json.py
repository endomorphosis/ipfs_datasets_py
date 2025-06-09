# Modified from: https://github.com/YoloSwagTeam/ast2json
# Copyright (c) 2013, Laurent Peuch <cortex@worlddomination.be>
#
# All rights reserved.
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in the
#   documentation and/or other materials provided with the distribution.
# * Neither the name of the University of California, Berkeley nor the
#   names of its contributors may be used to endorse or promote products
#   derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE REGENTS AND CONTRIBUTORS ``AS IS'' AND ANY
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE REGENTS AND CONTRIBUTORS BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from typing import Any, Optional

from mcp_server.utils import python_builtins

### Utility Functions ###
def _type_name(obj: Any) -> str:
    """Get the __name__ attribute of an object."""
    if isinstance(obj, type):
        return obj.__name__
    return type(obj).__name__


class _AstToJson:

    def __init__(self, builtins=None): 
        # Lazy loading since we don't need to import them until we call the tool.
        self.ast = builtins.ast
        self.AST = self.ast.AST
        self.getencoder = builtins.codecs.getencoder
        self.re = builtins.re

    def _decode_str(self, value: str) -> str:
        return value

    def _decode_bytes(self, value: bytes | bytearray) -> str:
        """Decode bytes to a string using various encodings and codecs."""
        encoders = ('utf-8', 'latin-1', 'ascii')
        codecs = ('hex_codec', 'base64_codec', 'utf-16', 'utf-32')
        for encoder in encoders:
            try:
                return value.decode(encoder)
            except UnicodeDecodeError:
                continue
        # If the value fails to decode, try re-encoding them THEN decoding them.
        for codec in codecs:
            try:
                return self.getencoder(codec)(value)[0].decode('utf-8')
            except UnicodeDecodeError:
                continue
        raise ValueError(
            f"Unable to decode bytes with '{encoders}' encoders, or '{codecs}' codecs."
        )

    def _ast2json(self, node) -> dict:
        """
        Convert an AST node to a JSON-like dictionary representation.

        Args:
            node (AST): The AST node to convert.

        Returns:
            dict: JSON-like representation of the AST node's public attributes.

        Raises:
            AttributeError: If the node is not an instance of AST.
        """
        if not isinstance(node, self.AST):
            raise AttributeError(f"Expected an AST node, got '{node}' of type '{_type_name(node)}'")

        to_return = {
            attr: self._get_value(getattr(node, attr))
            for attr in dir(node)
            if not attr.startswith("_")
        }
        to_return['_type'] = node.__class__.__name__

        return self._fix_complex_kinds(to_return)

    def _get_value(self, attr_value: Any) -> Optional[Any]:
        """
        Match the type of the attribute value and return a JSON-compatible representation.

        Args:
            attr_value (Any): The value of the attribute to convert.
            key (str): The name of the attribute, used for special cases like 'kind'.

        Returns:
            Optional[str]: A JSON-compatible representation of the attribute value.
            Returns None if the value is None.
        """
        match attr_value:
            case None:
                return None
            case int() | float() | bool():
                return attr_value
            case bytearray() | bytes():
                return self._decode_bytes(attr_value)
            case str():
                return self._decode_str(attr_value)
            case _ if isinstance(attr_value, complex):
                return str(attr_value)
            case list():
                return [self._get_value(x) for x in attr_value]
            case self.AST():
                return self._ast2json(attr_value) # Recursively convert AST nodes
            case _ if isinstance(attr_value, type(Ellipsis)):
                return '...'
            case _:
                raise TypeError(f"Could not identify type of attribute '{attr_value}', got '{_type_name(attr_value)}'")

    def _fix_complex_kinds(self, obj: Any) -> Any:
        """
        Recursively walk through the JSON structure and fix 'kind' values 
        that should represent complex numbers.
        """
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                if key == 'kind' and isinstance(value, str):
                    if self._is_complex_literal(value.strip()):
                        result[key] = 'complex'
                    else:
                        result[key] = value
                else:
                    result[key] = self._fix_complex_kinds(value)
            return result
        elif isinstance(obj, list):
            return [self._fix_complex_kinds(item) for item in obj]
        else:
            return obj

    def _is_complex_literal(self, value: str) -> bool:
        """
        Check if a string represents a valid Python complex number literal.
        
        Args:
            value (str): String to check
            
        Returns:
            bool: True if it's a valid complex number literal
        """
        try:
            # Try to evaluate it as a Python literal
            # This handles all valid Python complex number formats
            parsed = self.ast.literal_eval(value)
            return isinstance(parsed, complex)
        except (ValueError, SyntaxError):
            # If literal_eval fails, it's not a valid complex literal
            return False

    def str2json(self, string: str) -> dict[str, Any]:
        """Get the JSON representation of a Python source code string."""
        return self._ast2json(self.ast.parse(string))

def python_file_to_json(
        python_file: str,
        is_path: bool,
        save_path: Optional[str] = None
        ) -> str:
    """
    Convert a python file or python source code into a JSON-like dictionary representation.
    If save_path is provided, the JSON representation will also be saved to that path.

    Args:
        python_file(str): Path to the Python file or source code to parse.
        is_path(bool): If True, treat python_file as a file path; if False, treat it as file content.
        save_path(Optional[str]): Optional path to save the JSON representation to a json file.

    Returns:
        str: JSON-like string representation of the AST. 
            If the JSON representation is over 20,000 characters, a truncated string of the first 19,000 characters is returned.

    Raises:
        TypeError: If the python_file is not a string or save_path is not a string.
        ValueError: If the python_file does not end with '.py', save_path does not end with '.json', or if there's a failure converting the file string.
        FileNotFoundError: If the input python file does not exist.
        IOError: If there is an error reading the input python file, or saving the JSON to the specified path.
    """
    # Type and value check the arguments.
    if not isinstance(python_file, str):
        raise TypeError(f"Expected python file path to be a string, got '{_type_name(python_file)}'")

    if not python_file:
        raise ValueError("Expected python file path to be a non-empty string.")

    content = None

    if is_path:
        path = python_builtins.pathlib.Path(python_file)
        if path.exists() and path.is_file() and path.suffix.lower() == '.py':
            try:
                with open(path.resolve(), 'r', encoding='utf-8') as file:
                    content: str = file.read()
            except Exception as e:
                raise IOError(f"{_type_name(e)} writing JSON to '{save_path}': {e}") from e 
        else:
            raise FileNotFoundError(f"File '{python_file}' does not exist or is not a valid Python file.")
    else:
        content = python_file

    if content is None:
        raise ValueError("No valid content found. Code should never reach this point.")

    if save_path is not None:
        if not isinstance(save_path, str):
            raise TypeError(f"Expected save path to be a string, got '{type(save_path).__name__}'")
        if not save_path.endswith('.json'):
            raise ValueError(f"Save path does not end with '.json'. Got '{save_path.split('.')[-1]}'.")
        save_path = python_builtins.pathlib.Path(save_path)

    # Turn the python file content into a JSON object.
    try:
        json_dict = _AstToJson(builtins=python_builtins).str2json(content)
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise ValueError(f"{_type_name(e)} parsing content with ast_to_json: {e}") from e

    if save_path: # Save the file if input.
        try:
            with open(save_path.resolve(), 'w', encoding='utf-8') as file:
                python_builtins.json.dump(json_dict, file, indent=4)
            print(f"JSON saved to '{save_path}'")
        except Exception as e:
            raise IOError(f"{_type_name(e)} writing JSON to '{save_path}': {e}") from e 

    # If the JSON string is over 20,000 characters, return a truncated version of 19,000 instead.
    json_str = python_builtins.json.dumps(json_dict)
    return json_str[:19000] if len(json_str) >= 20000 else json_str
