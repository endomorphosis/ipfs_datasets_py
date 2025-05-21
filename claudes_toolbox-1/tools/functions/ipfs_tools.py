# Assuming the server is running and you have access to the MCP interface
result = mcp.call_tool("test_generator", name="MyTest", description="A test for my function", test_parameter_json="params.json")
print(result)