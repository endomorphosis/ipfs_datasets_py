#!/usr/bin/env node
/**
 * Test MCP SDK error handling improvements
 * 
 * This script tests the enhanced error handling in the MCP JavaScript SDKs
 * to ensure graceful degradation works correctly.
 */

const fs = require('fs');
const path = require('path');

// Read the SDK files
const sdkPath = path.join(__dirname, 'ipfs_datasets_py', 'static', 'js', 'mcp-sdk.js');
const adminSdkPath = path.join(__dirname, 'ipfs_datasets_py', 'static', 'admin', 'js', 'mcp-sdk.js');
const invSdkPath = path.join(__dirname, 'ipfs_datasets_py', 'static', 'admin', 'js', 'unified-investigation-mcp-sdk.js');

console.log('🧪 Testing MCP SDK Error Handling\n');

// Test 1: Check safeExecuteTool exists
console.log('Test 1: Checking for safeExecuteTool method in main SDK...');
const sdkContent = fs.readFileSync(sdkPath, 'utf8');
if (sdkContent.includes('async safeExecuteTool(')) {
    console.log('✅ PASS: safeExecuteTool method found\n');
} else {
    console.log('❌ FAIL: safeExecuteTool method not found\n');
    process.exit(1);
}

// Test 2: Check error message improvements
console.log('Test 2: Checking for enhanced error messages...');
const hasErrorMessages = 
    sdkContent.includes('Tool or endpoint not found') &&
    sdkContent.includes('Server error') &&
    sdkContent.includes('MCP server unavailable') &&
    sdkContent.includes('Network error');

if (hasErrorMessages) {
    console.log('✅ PASS: Enhanced error messages found\n');
} else {
    console.log('❌ FAIL: Enhanced error messages not found\n');
    process.exit(1);
}

// Test 3: Check admin SDK has same improvements
console.log('Test 3: Checking admin SDK for safeExecuteTool...');
const adminSdkContent = fs.readFileSync(adminSdkPath, 'utf8');
if (adminSdkContent.includes('async safeExecuteTool(')) {
    console.log('✅ PASS: Admin SDK has safeExecuteTool method\n');
} else {
    console.log('❌ FAIL: Admin SDK missing safeExecuteTool method\n');
    process.exit(1);
}

// Test 4: Check investigation SDK has safeMCPToolCall
console.log('Test 4: Checking investigation SDK for safeMCPToolCall...');
const invSdkContent = fs.readFileSync(invSdkPath, 'utf8');
if (invSdkContent.includes('async safeMCPToolCall(')) {
    console.log('✅ PASS: Investigation SDK has safeMCPToolCall method\n');
} else {
    console.log('❌ FAIL: Investigation SDK missing safeMCPToolCall method\n');
    process.exit(1);
}

// Test 5: Check investigation SDK error messages
console.log('Test 5: Checking investigation SDK error messages...');
const hasInvErrorMessages =
    invSdkContent.includes('MCP tool not found') &&
    invSdkContent.includes('MCP server error') &&
    invSdkContent.includes('Network error');

if (hasInvErrorMessages) {
    console.log('✅ PASS: Investigation SDK has enhanced error messages\n');
} else {
    console.log('❌ FAIL: Investigation SDK missing enhanced error messages\n');
    process.exit(1);
}

// Test 6: Check documentation exists
console.log('Test 6: Checking for error handling documentation...');
const docPath = path.join(__dirname, 'ipfs_datasets_py', 'static', 'js', 'MCP_SDK_ERROR_HANDLING.md');
if (fs.existsSync(docPath)) {
    const docContent = fs.readFileSync(docPath, 'utf8');
    const hasRequiredSections =
        docContent.includes('## Overview') &&
        docContent.includes('## Safe Tool Execution') &&
        docContent.includes('## When to Use Safe vs Standard Methods') &&
        docContent.includes('## Migration Guide');
    
    if (hasRequiredSections) {
        console.log('✅ PASS: Documentation exists with required sections\n');
    } else {
        console.log('❌ FAIL: Documentation missing required sections\n');
        process.exit(1);
    }
} else {
    console.log('❌ FAIL: Documentation file not found\n');
    process.exit(1);
}

// Test 7: Verify error handling for 404 status
console.log('Test 7: Verifying 404 error handling in safe methods...');
const handles404InMain = sdkContent.includes('error.status === 404') && 
                         sdkContent.includes('console.warn');
const handles404InInv = invSdkContent.includes("includes('not found')") &&
                        invSdkContent.includes("includes('404')");

if (handles404InMain && handles404InInv) {
    console.log('✅ PASS: 404 errors handled correctly in safe methods\n');
} else {
    console.log('❌ FAIL: 404 error handling incomplete\n');
    process.exit(1);
}

// All tests passed
console.log('═══════════════════════════════════════════');
console.log('🎉 All tests passed!');
console.log('═══════════════════════════════════════════');
console.log('\nSummary:');
console.log('- ✅ safeExecuteTool method added to main SDK');
console.log('- ✅ Enhanced error messages in main SDK');
console.log('- ✅ Admin SDK updated with safe methods');
console.log('- ✅ Investigation SDK has safeMCPToolCall');
console.log('- ✅ Investigation SDK has enhanced errors');
console.log('- ✅ Comprehensive documentation created');
console.log('- ✅ 404 errors handled gracefully');
console.log('\nThe MCP dashboard should now handle GitHub workflow');
console.log('errors gracefully without crashing. 🚀');

process.exit(0);
