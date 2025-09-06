#!/bin/bash
# Comprehensive testing script for MCP Kubernetes deployment

set -e

NAMESPACE="ipfs-datasets-mcp"
TEST_OUTPUT_DIR="/tmp/mcp-k8s-tests"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Test results
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_TOTAL=0

# Create test output directory
mkdir -p ${TEST_OUTPUT_DIR}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((TESTS_PASSED++))
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((TESTS_FAILED++))
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

run_test() {
    local test_name="$1"
    local test_command="$2"
    ((TESTS_TOTAL++))
    
    log_info "Running test: ${test_name}"
    
    if eval "$test_command" > "${TEST_OUTPUT_DIR}/${test_name}_${TIMESTAMP}.log" 2>&1; then
        log_success "${test_name}"
        return 0
    else
        log_error "${test_name}"
        echo "  Check log: ${TEST_OUTPUT_DIR}/${test_name}_${TIMESTAMP}.log"
        return 1
    fi
}

# Test 1: Namespace exists
test_namespace() {
    kubectl get namespace ${NAMESPACE}
}

# Test 2: All pods are running
test_pods_running() {
    local not_running=$(kubectl get pods -n ${NAMESPACE} --field-selector=status.phase!=Running --no-headers | wc -l)
    [ "$not_running" -eq 0 ]
}

# Test 3: All deployments are available
test_deployments_available() {
    kubectl get deployments -n ${NAMESPACE} -o jsonpath='{.items[*].status.conditions[?(@.type=="Available")].status}' | grep -v False
}

# Test 4: Services are accessible
test_services() {
    kubectl get service mcp-server-service -n ${NAMESPACE} > /dev/null &&
    kubectl get service mcp-dashboard-service -n ${NAMESPACE} > /dev/null
}

# Test 5: HPA is configured
test_hpa() {
    kubectl get hpa mcp-server-hpa -n ${NAMESPACE} > /dev/null &&
    kubectl get hpa mcp-dashboard-hpa -n ${NAMESPACE} > /dev/null
}

# Test 6: Network policies exist
test_network_policies() {
    kubectl get networkpolicy mcp-network-policy -n ${NAMESPACE} > /dev/null
}

# Test 7: Pod disruption budgets exist
test_pdb() {
    kubectl get pdb mcp-server-pdb -n ${NAMESPACE} > /dev/null &&
    kubectl get pdb mcp-dashboard-pdb -n ${NAMESPACE} > /dev/null
}

# Test 8: ConfigMaps and Secrets exist
test_config() {
    kubectl get configmap mcp-config -n ${NAMESPACE} > /dev/null &&
    kubectl get secret mcp-secrets -n ${NAMESPACE} > /dev/null
}

# Test 9: Health endpoints (with port forwarding)
test_health_endpoints() {
    # Set up port forwarding
    kubectl port-forward service/mcp-server-service 18000:8000 -n ${NAMESPACE} &
    SERVER_PF_PID=$!
    kubectl port-forward service/mcp-dashboard-service 18080:8080 -n ${NAMESPACE} &
    DASHBOARD_PF_PID=$!
    
    # Wait for port forwarding
    sleep 5
    
    # Test health endpoints
    local success=0
    if curl -f http://localhost:18000/health > /dev/null 2>&1; then
        ((success++))
    fi
    
    if curl -f http://localhost:18080/health > /dev/null 2>&1; then
        ((success++))
    fi
    
    # Clean up
    kill $SERVER_PF_PID $DASHBOARD_PF_PID 2>/dev/null || true
    
    [ "$success" -eq 2 ]
}

# Test 10: API endpoints functionality
test_api_functionality() {
    # Set up port forwarding
    kubectl port-forward service/mcp-server-service 18000:8000 -n ${NAMESPACE} &
    SERVER_PF_PID=$!
    
    # Wait for port forwarding
    sleep 5
    
    local success=0
    
    # Test tools endpoint
    if curl -f http://localhost:18000/tools > /dev/null 2>&1; then
        ((success++))
    fi
    
    # Test execute endpoint
    if curl -X POST -H "Content-Type: application/json" \
        -d '{"tool_name": "echo", "parameters": {"text": "test"}}' \
        http://localhost:18000/execute > /dev/null 2>&1; then
        ((success++))
    fi
    
    # Clean up
    kill $SERVER_PF_PID 2>/dev/null || true
    
    [ "$success" -eq 2 ]
}

# Test 11: Resource limits and requests
test_resource_limits() {
    local pods_with_limits=$(kubectl get pods -n ${NAMESPACE} -o jsonpath='{.items[*].spec.containers[*].resources.limits}' | wc -w)
    local pods_with_requests=$(kubectl get pods -n ${NAMESPACE} -o jsonpath='{.items[*].spec.containers[*].resources.requests}' | wc -w)
    
    [ "$pods_with_limits" -gt 0 ] && [ "$pods_with_requests" -gt 0 ]
}

# Test 12: Security contexts
test_security_contexts() {
    local pods_with_security=$(kubectl get pods -n ${NAMESPACE} -o jsonpath='{.items[*].spec.securityContext.runAsNonRoot}' | grep -c true || echo 0)
    local total_pods=$(kubectl get pods -n ${NAMESPACE} --no-headers | wc -l)
    
    [ "$pods_with_security" -eq "$total_pods" ]
}

# Test 13: Scaling test
test_scaling() {
    local original_replicas=$(kubectl get deployment mcp-server -n ${NAMESPACE} -o jsonpath='{.spec.replicas}')
    
    # Scale up
    kubectl scale deployment mcp-server --replicas=4 -n ${NAMESPACE}
    kubectl wait --for=condition=available --timeout=120s deployment/mcp-server -n ${NAMESPACE}
    
    local scaled_replicas=$(kubectl get deployment mcp-server -n ${NAMESPACE} -o jsonpath='{.status.readyReplicas}')
    
    # Scale back to original
    kubectl scale deployment mcp-server --replicas=${original_replicas} -n ${NAMESPACE}
    kubectl wait --for=condition=available --timeout=120s deployment/mcp-server -n ${NAMESPACE}
    
    [ "$scaled_replicas" -eq 4 ]
}

# Test 14: Liveness and readiness probes
test_probes() {
    local liveness_probes=$(kubectl get pods -n ${NAMESPACE} -o jsonpath='{.items[*].spec.containers[*].livenessProbe}' | wc -w)
    local readiness_probes=$(kubectl get pods -n ${NAMESPACE} -o jsonpath='{.items[*].spec.containers[*].readinessProbe}' | wc -w)
    
    [ "$liveness_probes" -gt 0 ] && [ "$readiness_probes" -gt 0 ]
}

# Test 15: Performance test
test_performance() {
    # Set up port forwarding
    kubectl port-forward service/mcp-server-service 18000:8000 -n ${NAMESPACE} &
    SERVER_PF_PID=$!
    
    # Wait for port forwarding
    sleep 5
    
    # Simple performance test - 10 concurrent requests
    local success_count=0
    for i in {1..10}; do
        if curl -f http://localhost:18000/health > /dev/null 2>&1; then
            ((success_count++))
        fi &
    done
    
    wait  # Wait for all background jobs to complete
    
    # Clean up
    kill $SERVER_PF_PID 2>/dev/null || true
    
    [ "$success_count" -eq 10 ]
}

# Generate test report
generate_report() {
    local report_file="${TEST_OUTPUT_DIR}/test_report_${TIMESTAMP}.md"
    
    cat > "$report_file" << EOF
# MCP Kubernetes Deployment Test Report

**Date:** $(date)  
**Namespace:** ${NAMESPACE}  
**Test Results:** ${TESTS_PASSED}/${TESTS_TOTAL} tests passed

## Summary

- ✅ Passed: ${TESTS_PASSED}
- ❌ Failed: ${TESTS_FAILED}
- 📊 Total: ${TESTS_TOTAL}
- 📈 Success Rate: $(( TESTS_PASSED * 100 / TESTS_TOTAL ))%

## Infrastructure Status

### Pods
\`\`\`
$(kubectl get pods -n ${NAMESPACE} -o wide)
\`\`\`

### Services
\`\`\`
$(kubectl get services -n ${NAMESPACE})
\`\`\`

### Deployments
\`\`\`
$(kubectl get deployments -n ${NAMESPACE})
\`\`\`

### HPA Status
\`\`\`
$(kubectl get hpa -n ${NAMESPACE})
\`\`\`

### Resource Usage
\`\`\`
$(kubectl top pods -n ${NAMESPACE} 2>/dev/null || echo "Metrics server not available")
\`\`\`

## Test Details

Individual test logs are available in: ${TEST_OUTPUT_DIR}/

EOF

    log_info "Test report generated: $report_file"
}

# Main test execution
main() {
    log_info "Starting MCP Kubernetes deployment tests..."
    log_info "Test output directory: ${TEST_OUTPUT_DIR}"
    echo ""
    
    # Run all tests
    run_test "namespace_exists" "test_namespace"
    run_test "pods_running" "test_pods_running"
    run_test "deployments_available" "test_deployments_available"
    run_test "services_accessible" "test_services"
    run_test "hpa_configured" "test_hpa"
    run_test "network_policies" "test_network_policies"
    run_test "pdb_configured" "test_pdb"
    run_test "config_exists" "test_config"
    run_test "health_endpoints" "test_health_endpoints"
    run_test "api_functionality" "test_api_functionality"
    run_test "resource_limits" "test_resource_limits"
    run_test "security_contexts" "test_security_contexts"
    run_test "scaling_works" "test_scaling"
    run_test "probes_configured" "test_probes"
    run_test "performance_basic" "test_performance"
    
    echo ""
    
    # Generate report
    generate_report
    
    # Final summary
    if [ "$TESTS_FAILED" -eq 0 ]; then
        log_success "All tests passed! 🎉"
        echo ""
        log_info "Your MCP Kubernetes deployment is ready for production!"
        echo ""
        log_info "Access points:"
        echo "  - MCP Server: kubectl port-forward service/mcp-server-service 8000:8000 -n ${NAMESPACE}"
        echo "  - MCP Dashboard: kubectl port-forward service/mcp-dashboard-service 8080:8080 -n ${NAMESPACE}"
        echo ""
        exit 0
    else
        log_error "${TESTS_FAILED} tests failed"
        echo ""
        log_info "Check the logs in ${TEST_OUTPUT_DIR} for details"
        exit 1
    fi
}

# Handle script arguments
case ${1:-test} in
    test)
        main
        ;;
    help|--help|-h)
        echo "MCP Kubernetes Deployment Test Script"
        echo ""
        echo "Usage: $0 [test]"
        echo ""
        echo "This script runs comprehensive tests on the MCP Kubernetes deployment."
        echo "It will test pods, services, health endpoints, scaling, and more."
        echo ""
        ;;
    *)
        echo "Unknown command: $1"
        echo "Use '$0 help' for usage information"
        exit 1
        ;;
esac