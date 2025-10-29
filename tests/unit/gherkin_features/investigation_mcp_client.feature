Feature: Investigation MCP Client
  Client for MCP-based investigations

  Scenario: Connect to MCP server
    Given MCP server connection details
    When connection is initiated
    Then the client is connected

  Scenario: Invoke MCP tool
    Given a tool name and parameters
    When tool invocation is requested
    Then the tool executes and returns results

  Scenario: List available MCP tools
    Given a connected MCP client
    When tool listing is requested
    Then all available tools are returned

  Scenario: Monitor tool execution
    Given a running tool
    When execution monitoring is enabled
    Then execution progress is tracked

  Scenario: Handle tool errors
    Given a tool that encounters an error
    When the error occurs
    Then the error is captured and reported

  Scenario: Cache tool results
    Given a cacheable tool invocation
    When caching is enabled
    Then results are cached for reuse

  Scenario: Batch invoke tools
    Given multiple tool invocations
    When batch execution is requested
    Then all tools are executed in batch

  Scenario: Stream tool responses
    Given a tool with streaming output
    When streaming is enabled
    Then responses are streamed as they arrive
