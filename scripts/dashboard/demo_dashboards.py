#!/usr/bin/env python3
"""
Demo script showing how to use the new finance and medicine dashboards.
"""

import sys
from pathlib import Path

# Add repository to path
repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root))


def demo_dashboards():
    """Demonstrate the new dashboard functionality."""

    print("=" * 70)
    print("IPFS Datasets - Finance & Medicine Dashboards Demo")
    print("=" * 70)
    print()

    print("📋 Available Dashboards:")
    print("-" * 70)
    dashboards = [
        {
            "name": "Caselaw Analysis",
            "url": "http://127.0.0.1:8080/mcp/caselaw",
            "icon": "⚖️",
            "domain": "Legal",
            "description": "Analyze legal documents using temporal deontic logic",
        },
        {
            "name": "Finance Analysis",
            "url": "http://127.0.0.1:8080/mcp/finance",
            "icon": "📈",
            "domain": "Financial",
            "description": "Analyze financial documents and compliance rules",
        },
        {
            "name": "Medicine Analysis",
            "url": "http://127.0.0.1:8080/mcp/medicine",
            "icon": "❤️",
            "domain": "Medical",
            "description": "Analyze medical documents and clinical guidelines",
        },
    ]

    for db in dashboards:
        print(f"{db['icon']} {db['name']}")
        print(f"   URL: {db['url']}")
        print(f"   Domain: {db['domain']}")
        print(f"   Description: {db['description']}")
        print()

    print()
    print("🔌 API Endpoints:")
    print("-" * 70)

    endpoints = [
        {
            "domain": "Finance",
            "endpoints": [
                "POST /api/mcp/finance/check_document",
                "POST /api/mcp/finance/query_theorems",
            ],
        },
        {
            "domain": "Medicine",
            "endpoints": [
                "POST /api/mcp/medicine/check_document",
                "POST /api/mcp/medicine/query_theorems",
            ],
        },
    ]

    for ep in endpoints:
        print(f"📡 {ep['domain']} API:")
        for endpoint in ep["endpoints"]:
            print(f"   {endpoint}")
        print()

    print()
    print("🚀 Quick Start:")
    print("-" * 70)
    print("1. Start the MCP dashboard server:")
    print("   $ ipfs-datasets mcp start")
    print()
    print("2. Open your browser to one of the dashboard URLs above")
    print()
    print("3. Try the document consistency checker:")
    print("   - Paste a document (financial/medical/legal)")
    print("   - Select appropriate filters")
    print("   - Click 'Check Consistency'")
    print()
    print("4. Query rules/guidelines/theorems:")
    print("   - Enter a search query")
    print("   - Select operator (OBLIGATION/PROHIBITION/PERMISSION)")
    print("   - Click 'Query'")
    print()

    print()
    print("💡 Example API Usage:")
    print("-" * 70)

    print("\nCheck a finance document:")
    print("""
curl -X POST http://127.0.0.1:8080/api/mcp/finance/check_document \\
  -H "Content-Type: application/json" \\
  -d '{
    "document_text": "Company must disclose material risks",
    "jurisdiction": "SEC",
    "legal_domain": "finance"
  }'
""")

    print("\nQuery medical guidelines:")
    print("""
curl -X POST http://127.0.0.1:8080/api/mcp/medicine/query_theorems \\
  -H "Content-Type: application/json" \\
  -d '{
    "query_text": "patient consent",
    "operator": "OBLIGATION",
    "legal_domain": "medicine",
    "top_k": 5
  }'
""")

    print()
    print("🔧 Technical Details:")
    print("-" * 70)
    print("• All dashboards share the same temporal deontic logic engine")
    print("• Backend: TemporalDeonticRAGStore + DocumentConsistencyChecker")
    print("• Templates customized for domain-specific terminology")
    print("• Cross-dashboard navigation via sidebar links")
    print()

    print("=" * 70)
    print("✅ Setup complete! All three dashboards are ready to use.")
    print("=" * 70)
    print()


if __name__ == "__main__":
    demo_dashboards()
