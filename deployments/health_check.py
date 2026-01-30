#!/usr/bin/env python3
"""
Health Check Script for GraphRAG System

Provides comprehensive health checking for all system components
during deployment and runtime monitoring.
"""

import os
import sys
import json
import anyio
try:
    import aiohttp
except ImportError as e:
    print(f"connection dependency missing: aiohttp ({e})", file=sys.stderr)
    sys.exit(1)

try:
    from ipfs_datasets_py.database_utils import check_database_health as check_db_health
except ImportError as e:
    print(f"connection dependency missing: database_utils ({e})", file=sys.stderr)
    sys.exit(1)

try:
    import redis.asyncio as redis
except ImportError as e:
    print(f"connection dependency missing: redis ({e})", file=sys.stderr)
    sys.exit(1)
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class HealthCheckResult:
    """Result of a health check."""
    service: str
    status: str  # HEALTHY, UNHEALTHY, DEGRADED
    response_time_ms: float
    message: str
    details: Optional[Dict] = None

class GraphRAGHealthChecker:
    """Comprehensive health checker for GraphRAG system."""
    
    def __init__(self):
        self.results: List[HealthCheckResult] = []
    
    async def check_database(self) -> HealthCheckResult:
        """Check SQLite/DuckDB database health."""
        start_time = datetime.now()
        
        try:
            health = await check_db_health()
            
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            if health["status"] == "healthy":
                sqlite_info = health["databases"]["sqlite"]
                duckdb_info = health["databases"]["duckdb"]
                
                return HealthCheckResult(
                    service="database",
                    status="HEALTHY",
                    response_time_ms=response_time,
                    message=f"SQLite and DuckDB databases healthy",
                    details={
                        "sqlite": sqlite_info,
                        "duckdb": duckdb_info
                    }
                )
            else:
                return HealthCheckResult(
                    service="database",
                    status="UNHEALTHY",
                    response_time_ms=response_time,
                    message="Database health check failed",
                    details=health["databases"]
                )
            
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            return HealthCheckResult(
                service="database",
                status="UNHEALTHY",
                response_time_ms=response_time,
                message=f"Database connection failed: {e}"
            )
    
    async def check_redis(self, redis_url: str) -> HealthCheckResult:
        """Check Redis cache health."""
        start_time = datetime.now()
        
        try:
            r = redis.from_url(redis_url)
            
            # Test basic connectivity
            await r.ping()
            
            # Test set/get operations
            test_key = "health_check_test"
            await r.set(test_key, "test_value", ex=10)
            value = await r.get(test_key)
            await r.delete(test_key)
            
            # Get info
            info = await r.info()
            
            await r.close()
            
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return HealthCheckResult(
                service="redis",
                status="HEALTHY",
                response_time_ms=response_time,
                message="Redis is healthy and responsive",
                details={
                    "redis_version": info.get("redis_version"),
                    "connected_clients": info.get("connected_clients"),
                    "used_memory_human": info.get("used_memory_human")
                }
            )
            
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            return HealthCheckResult(
                service="redis",
                status="UNHEALTHY",
                response_time_ms=response_time,
                message=f"Redis connection failed: {e}"
            )
    
    async def check_api_service(self, api_url: str) -> HealthCheckResult:
        """Check GraphRAG API service health."""
        start_time = datetime.now()
        
        try:
            async with aiohttp.ClientSession() as session:
                # Check health endpoint
                async with session.get(f"{api_url}/health") as resp:
                    if resp.status == 200:
                        health_data = await resp.json()
                    else:
                        raise Exception(f"Health endpoint returned {resp.status}")
                
                # Check API documentation endpoint
                async with session.get(f"{api_url}/docs") as resp:
                    docs_available = resp.status == 200
            
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return HealthCheckResult(
                service="api",
                status="HEALTHY",
                response_time_ms=response_time,
                message="API service is healthy and responsive",
                details={
                    "health_data": health_data,
                    "docs_available": docs_available
                }
            )
            
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            return HealthCheckResult(
                service="api",
                status="UNHEALTHY",
                response_time_ms=response_time,
                message=f"API service check failed: {e}"
            )
    
    async def check_elasticsearch(self, es_url: str) -> HealthCheckResult:
        """Check Elasticsearch health."""
        start_time = datetime.now()
        
        try:
            async with aiohttp.ClientSession() as session:
                # Check cluster health
                async with session.get(f"{es_url}/_cluster/health") as resp:
                    if resp.status == 200:
                        health_data = await resp.json()
                        cluster_status = health_data.get("status", "unknown")
                    else:
                        raise Exception(f"Elasticsearch health check returned {resp.status}")
            
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            if cluster_status == "green":
                status = "HEALTHY"
            elif cluster_status == "yellow":
                status = "DEGRADED"
            else:
                status = "UNHEALTHY"
            
            return HealthCheckResult(
                service="elasticsearch",
                status=status,
                response_time_ms=response_time,
                message=f"Elasticsearch cluster status: {cluster_status}",
                details=health_data
            )
            
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            return HealthCheckResult(
                service="elasticsearch",
                status="UNHEALTHY",
                response_time_ms=response_time,
                message=f"Elasticsearch check failed: {e}"
            )
    
    async def check_ipfs_node(self, ipfs_api_url: str) -> HealthCheckResult:
        """Check IPFS node health."""
        start_time = datetime.now()
        
        try:
            async with aiohttp.ClientSession() as session:
                # Check IPFS ID
                async with session.post(f"{ipfs_api_url}/api/v0/id") as resp:
                    if resp.status == 200:
                        node_info = await resp.json()
                    else:
                        raise Exception(f"IPFS ID check returned {resp.status}")
                
                # Check swarm peers
                async with session.post(f"{ipfs_api_url}/api/v0/swarm/peers") as resp:
                    if resp.status == 200:
                        peers_data = await resp.json()
                        peer_count = len(peers_data.get("Peers", []))
                    else:
                        peer_count = 0
            
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return HealthCheckResult(
                service="ipfs",
                status="HEALTHY",
                response_time_ms=response_time,
                message=f"IPFS node healthy with {peer_count} peers",
                details={
                    "node_id": node_info.get("ID"),
                    "peer_count": peer_count,
                    "addresses": node_info.get("Addresses", [])
                }
            )
            
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            return HealthCheckResult(
                service="ipfs",
                status="UNHEALTHY",
                response_time_ms=response_time,
                message=f"IPFS node check failed: {e}"
            )
    
    async def run_comprehensive_health_check(self) -> Dict:
        """Run health checks for all system components."""
        print("🏥 Running comprehensive health checks...")
        
        # Get configuration from environment (no more POSTGRES_URL)
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        api_url = os.getenv("API_URL", "http://localhost:8000")
        es_url = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
        ipfs_url = os.getenv("IPFS_API_URL", "http://localhost:5001")
        
        # Run all health checks concurrently
        tasks = [
            self.check_database(),  # Now checks SQLite/DuckDB
            self.check_redis(redis_url),
            self.check_api_service(api_url),
            self.check_elasticsearch(es_url),
            self.check_ipfs_node(ipfs_url),
        ]
        health_checks = [None] * len(tasks)

        async def _run_task(index, coro):
            try:
                health_checks[index] = await coro
            except Exception as exc:
                health_checks[index] = exc

        async with anyio.create_task_group() as task_group:
            for index, coro in enumerate(tasks):
                task_group.start_soon(_run_task, index, coro)
        
        # Process results
        for result in health_checks:
            if isinstance(result, Exception):
                self.results.append(HealthCheckResult(
                    service="unknown",
                    status="UNHEALTHY",
                    response_time_ms=0,
                    message=f"Health check error: {result}"
                ))
            else:
                self.results.append(result)
        
        # Calculate overall health
        healthy_count = sum(1 for r in self.results if r.status == "HEALTHY")
        total_count = len(self.results)
        overall_health = "HEALTHY" if healthy_count == total_count else "DEGRADED" if healthy_count > 0 else "UNHEALTHY"
        
        return {
            "timestamp": datetime.now().isoformat(),
            "overall_health": overall_health,
            "services_healthy": healthy_count,
            "total_services": total_count,
            "results": [
                {
                    "service": r.service,
                    "status": r.status,
                    "response_time_ms": r.response_time_ms,
                    "message": r.message,
                    "details": r.details
                }
                for r in self.results
            ]
        }

def main():
    """Main entry point."""
    checker = GraphRAGHealthChecker()
    
    result = anyio.run(checker.run_comprehensive_health_check())
    
    # Display summary
    print(f"\n🎯 Health Check Summary")
    print("=" * 30)
    print(f"Overall Health: {result['overall_health']}")
    print(f"Healthy Services: {result['services_healthy']}/{result['total_services']}")
    
    # Display individual results
    for service_result in result['results']:
        status_icon = "✅" if service_result['status'] == "HEALTHY" else "⚠️" if service_result['status'] == "DEGRADED" else "❌"
        print(f"{status_icon} {service_result['service']}: {service_result['message']} ({service_result['response_time_ms']:.0f}ms)")
    
    # Save results
    report_file = Path("health_check_report.json")
    with open(report_file, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"\n📄 Detailed report saved to: {report_file}")
    
    # Exit with appropriate code
    sys.exit(0 if result['overall_health'] in ['HEALTHY', 'DEGRADED'] else 1)

if __name__ == "__main__":
    main()