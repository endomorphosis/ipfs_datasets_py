result = await mcp.call("test_generator", name="MyTest", description="A test for my function", test_parameter_json="params.json")
print(result)