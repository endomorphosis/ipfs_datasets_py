"""Test function for MCP tool testing"""

def test_function_name(input_data="test"):
    """A simple test function for MCP tool testing"""
    return {
        "status": "success",
        "result": f"Processed: {input_data}",
        "function": "test_function_name"
    }

if __name__ == "__main__":
    print(test_function_name("hello world"))
