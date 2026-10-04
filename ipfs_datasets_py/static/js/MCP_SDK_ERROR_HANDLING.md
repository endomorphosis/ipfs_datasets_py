# MCP SDK Error Handling Guide

## Overview

The MCP JavaScript SDKs have been enhanced with better error handling to provide more informative error messages and graceful degradation when tools are unavailable.

## Improved Error Messages

### Before
```javascript
// Generic error: "Internal error"
```

### After
```javascript
// Specific errors based on HTTP status:
// 404: "Tool or endpoint not found: /tools/category/tool_name"
// 500: "Server error: [detailed message]"
// 503: "MCP server unavailable"
// Network: "Network error: Unable to connect to MCP server"
```

## Safe Tool Execution

### Using `safeExecuteTool()` (Main MCP SDK)

For optional features that shouldn't crash the dashboard if unavailable:

```javascript
// Standard method - throws on errors
const mcpClient = new MCPClient('http://localhost:8080/api/mcp');
try {
    const result = await mcpClient.executeTool('workflow_tools', 'fetch_workflows', {});
} catch (error) {
    // Dashboard crashes or shows error modal
    console.error('Tool failed:', error);
}

// Safe method - returns null for missing tools
const result = await mcpClient.safeExecuteTool('workflow_tools', 'fetch_workflows', {});
if (result === null) {
    // Tool not available - continue gracefully
    console.warn('Workflow features unavailable');
} else {
    // Tool succeeded - use the result
    displayWorkflows(result);
}
```

### Using `safeMCPToolCall()` (Investigation SDK)

For the unified investigation dashboard:

```javascript
const invClient = new UnifiedInvestigationMCPClient();

// Standard method - throws on errors
try {
    const result = await invClient._callMCPTool('fetch_github_workflows', {});
} catch (error) {
    // Dashboard crashes
    console.error('Tool failed:', error);
}

// Safe method - returns null for missing tools
const result = await invClient.safeMCPToolCall('fetch_github_workflows', {});
if (result === null) {
    // Tool not available - continue gracefully
    console.warn('[GitHub Workflows] Feature unavailable');
} else {
    // Tool succeeded
    displayWorkflows(result);
}
```

## When to Use Safe vs Standard Methods

### Use `safeExecuteTool()` / `safeMCPToolCall()` for:
- Optional features (GitHub workflows, advanced analytics, etc.)
- Features that may not be available in all deployments
- Background data fetching that shouldn't interrupt user experience
- Progressive enhancement scenarios

### Use standard `executeTool()` / `_callMCPTool()` for:
- Core features required for dashboard functionality
- User-initiated actions where errors should be shown
- Critical operations that need explicit error handling

## Error Handling Best Practices

### 1. Provide User Feedback
```javascript
const result = await mcpClient.safeExecuteTool('optional_tool', 'action', {});
if (result === null) {
    // Show user-friendly message in UI
    document.getElementById('feature-status').innerHTML = 
        '<span class="text-warning">⚠️ This feature is temporarily unavailable</span>';
} else {
    // Show success
    displayResults(result);
}
```

### 2. Log for Debugging
```javascript
// Safe methods already log warnings to console
const result = await mcpClient.safeExecuteTool('workflow_tools', 'fetch_workflows', {});
// Console output: "[MCP SDK] Tool workflow_tools/fetch_workflows not available: Tool or endpoint not found"
```

### 3. Implement Fallbacks
```javascript
const result = await mcpClient.safeExecuteTool('advanced_analytics', 'analyze', { data });
if (result === null) {
    // Fallback to basic analytics
    const basicResult = await mcpClient.executeTool('basic_analytics', 'analyze', { data });
    displayBasicAnalytics(basicResult);
} else {
    displayAdvancedAnalytics(result);
}
```

## Migration Guide

### Updating Existing Code

Replace tool execution for optional features:

```javascript
// Before
async function loadWorkflows() {
    try {
        const result = await mcpClient.executeTool('workflow_tools', 'fetch_workflows', {});
        displayWorkflows(result);
    } catch (error) {
        alert('Error loading workflows: ' + error.message);
    }
}

// After
async function loadWorkflows() {
    const result = await mcpClient.safeExecuteTool('workflow_tools', 'fetch_workflows', {});
    if (result === null) {
        // Show non-intrusive warning
        document.getElementById('workflows-section').innerHTML = 
            '<div class="alert alert-info">Workflow features are currently unavailable</div>';
    } else {
        displayWorkflows(result);
    }
}
```

## Testing

### Test Error Scenarios
```javascript
// Test with unavailable tool
const result = await mcpClient.safeExecuteTool('nonexistent_category', 'nonexistent_tool', {});
console.assert(result === null, 'Should return null for missing tool');

// Test with available tool
const result2 = await mcpClient.safeExecuteTool('dataset_tools', 'list_datasets', {});
console.assert(result2 !== null, 'Should return result for available tool');
```

## Troubleshooting

### Issue: Still seeing generic errors
**Solution**: Ensure you're using the updated SDK files:
- `/static/js/mcp-sdk.js`
- `/static/admin/js/mcp-sdk.js`
- `/static/admin/js/unified-investigation-mcp-sdk.js`

### Issue: Dashboard crashes on missing tools
**Solution**: Replace `executeTool()` with `safeExecuteTool()` for optional features.

### Issue: Not seeing console warnings
**Solution**: Check browser console settings - warnings may be filtered out.

## Summary

The enhanced MCP SDK error handling provides:
1. ✅ More specific error messages for debugging
2. ✅ Graceful degradation for optional features
3. ✅ Better user experience when features are unavailable
4. ✅ Consistent error handling across all SDK variants
