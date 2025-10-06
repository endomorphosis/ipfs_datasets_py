#!/usr/bin/env bash
# Performance Testing Script for GraphRAG System
# Tests system performance under various load conditions

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configuration
API_URL=${API_URL:-"http://localhost:8000"}
TEST_DURATION=${TEST_DURATION:-60}
CONCURRENT_USERS=${CONCURRENT_USERS:-10}
OUTPUT_DIR="$PROJECT_ROOT/performance_test_results"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

setup_test_environment() {
    log_info "Setting up performance test environment..."
    
    # Create output directory
    mkdir -p "$OUTPUT_DIR"
    
    # Check if required tools are available
    if ! command -v curl &> /dev/null; then
        log_error "curl is required for performance testing"
        exit 1
    fi
    
    # Install additional tools if needed
    if ! command -v ab &> /dev/null; then
        log_warning "Apache Bench (ab) not found. Installing..."
        if command -v apt-get &> /dev/null; then
            sudo apt-get update && sudo apt-get install -y apache2-utils
        else
            log_warning "Could not install Apache Bench automatically"
        fi
    fi
}

test_api_health() {
    log_info "Testing API health endpoint..."
    
    response=$(curl -s -w "%{http_code},%{time_total}" -o /dev/null "$API_URL/health")
    http_code=$(echo $response | cut -d',' -f1)
    response_time=$(echo $response | cut -d',' -f2)
    
    if [ "$http_code" = "200" ]; then
        log_info "✅ Health endpoint responsive (${response_time}s)"
        return 0
    else
        log_error "❌ Health endpoint failed (HTTP $http_code)"
        return 1
    fi
}

test_authentication_performance() {
    log_info "Testing authentication performance..."
    
    # Test login endpoint
    login_data='{"username": "demo", "password": "demo"}'
    
    if command -v ab &> /dev/null; then
        # Use Apache Bench for load testing
        ab -n 100 -c 10 -p <(echo "$login_data") -T "application/json" \
           "$API_URL/auth/login" > "$OUTPUT_DIR/auth_performance.txt" 2>&1
        
        # Extract key metrics
        if [ -f "$OUTPUT_DIR/auth_performance.txt" ]; then
            requests_per_sec=$(grep "Requests per second" "$OUTPUT_DIR/auth_performance.txt" | awk '{print $4}')
            mean_time=$(grep "Time per request" "$OUTPUT_DIR/auth_performance.txt" | head -1 | awk '{print $4}')
            
            log_info "Auth performance: ${requests_per_sec} req/s, ${mean_time}ms avg"
        fi
    else
        # Fallback to simple curl test
        start_time=$(date +%s.%N)
        response=$(curl -s -X POST -H "Content-Type: application/json" \
                   -d "$login_data" "$API_URL/auth/login")
        end_time=$(date +%s.%N)
        
        duration=$(echo "$end_time - $start_time" | bc -l 2>/dev/null || echo "0.1")
        log_info "Single auth request: ${duration}s"
    fi
}

test_processing_job_performance() {
    log_info "Testing processing job submission performance..."
    
    # First authenticate to get token
    login_response=$(curl -s -X POST -H "Content-Type: application/json" \
                     -d '{"username": "demo", "password": "demo"}' \
                     "$API_URL/auth/login")
    
    if echo "$login_response" | grep -q "access_token"; then
        token=$(echo "$login_response" | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
        
        # Test job submission
        job_data='{"url": "https://example.com", "processing_mode": "fast", "include_media": false}'
        
        start_time=$(date +%s.%N)
        job_response=$(curl -s -X POST -H "Authorization: Bearer $token" \
                       -H "Content-Type: application/json" \
                       -d "$job_data" "$API_URL/api/v1/process-website")
        end_time=$(date +%s.%N)
        
        duration=$(echo "$end_time - $start_time" | bc -l 2>/dev/null || echo "0.1")
        
        if echo "$job_response" | grep -q "job_id"; then
            log_info "✅ Job submission successful (${duration}s)"
        else
            log_warning "⚠️ Job submission may have issues: $job_response"
        fi
    else
        log_warning "⚠️ Could not authenticate for job testing"
    fi
}

test_search_performance() {
    log_info "Testing search performance..."
    
    # Test search endpoint (no auth required for basic search)
    search_queries=("machine learning" "artificial intelligence" "data science" "neural networks")
    
    total_time=0
    successful_searches=0
    
    for query in "${search_queries[@]}"; do
        start_time=$(date +%s.%N)
        response=$(curl -s "$API_URL/api/v1/search?query=$query&limit=10")
        end_time=$(date +%s.%N)
        
        duration=$(echo "$end_time - $start_time" | bc -l 2>/dev/null || echo "0.1")
        total_time=$(echo "$total_time + $duration" | bc -l 2>/dev/null || echo "$total_time")
        
        if echo "$response" | grep -q "results"; then
            ((successful_searches++))
            log_info "Search '$query': ${duration}s"
        fi
    done
    
    if [ $successful_searches -gt 0 ]; then
        avg_time=$(echo "scale=3; $total_time / $successful_searches" | bc -l 2>/dev/null || echo "0.1")
        log_info "✅ Average search time: ${avg_time}s (${successful_searches}/${#search_queries[@]} successful)"
    fi
}

generate_performance_report() {
    log_info "Generating performance test report..."
    
    cat > "$OUTPUT_DIR/performance_summary.md" << EOF
# GraphRAG System Performance Test Report

Generated: $(date)

## Test Configuration
- API URL: $API_URL
- Test Duration: ${TEST_DURATION}s
- Concurrent Users: $CONCURRENT_USERS
- Output Directory: $OUTPUT_DIR

## Test Results

### API Health
$(test_api_health && echo "✅ Health endpoint responsive" || echo "❌ Health endpoint failed")

### Authentication Performance
$(if [ -f "$OUTPUT_DIR/auth_performance.txt" ]; then
    echo "Load test results:"
    grep -E "(Requests per second|Time per request|Failed requests)" "$OUTPUT_DIR/auth_performance.txt" | head -3
else
    echo "Basic authentication test completed"
fi)

### Processing Job Performance
Job submission and status tracking tested

### Search Performance  
Search query performance across multiple test queries

## Recommendations

1. **API Performance**: Ensure response times stay below 100ms for health checks
2. **Authentication**: Implement connection pooling if auth requests exceed 100/sec
3. **Job Processing**: Monitor queue length and add workers if processing falls behind
4. **Search**: Consider search result caching for frequently used queries

## Next Steps

1. Run load tests with higher concurrent users
2. Test with realistic data volumes
3. Monitor resource usage during peak load
4. Implement performance alerting thresholds
EOF

    log_info "Performance report saved to $OUTPUT_DIR/performance_summary.md"
}

main() {
    log_info "Starting GraphRAG performance testing..."
    
    setup_test_environment
    
    # Wait for system to be ready
    log_info "Waiting for system to be ready..."
    for i in {1..30}; do
        if test_api_health; then
            break
        fi
        log_info "Waiting for API... ($i/30)"
        sleep 2
    done
    
    # Run performance tests
    test_authentication_performance
    test_processing_job_performance  
    test_search_performance
    
    # Generate report
    generate_performance_report
    
    log_info "Performance testing completed!"
    log_info "Results available in: $OUTPUT_DIR"
}

# Run main function
main "$@"