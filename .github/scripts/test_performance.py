#!/usr/bin/env python3
"""Performance test for CI/CD"""
import requests
import time
import statistics
import json

def measure_endpoint_performance():
    endpoints = [
        "http://127.0.0.1:8899/api/mcp/status",
        "http://127.0.0.1:8899/",
        "http://127.0.0.1:8899/api/mcp/tools"
    ]
    
    results = {}
    for endpoint in endpoints:
        times = []
        for i in range(10):
            start = time.time()
            try:
                response = requests.get(endpoint, timeout=5)
                end = time.time()
                if response.status_code == 200:
                    times.append(end - start)
            except:
                pass
        
        if times:
            results[endpoint] = {
                "avg_response_time": statistics.mean(times),
                "min_response_time": min(times),
                "max_response_time": max(times),
                "requests_tested": len(times)
            }
            print(f"{endpoint}: avg={statistics.mean(times):.3f}s, min={min(times):.3f}s, max={max(times):.3f}s")
    
    return results

if __name__ == "__main__":
    perf_results = measure_endpoint_performance()
    print("✅ Performance test completed")
    
    with open("/app/test-results/perf_results.json", "w") as f:
        json.dump(perf_results, f, indent=2)
