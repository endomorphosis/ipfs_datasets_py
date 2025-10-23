#!/usr/bin/env python3
"""
Fixed Caselaw Dashboard Demo

This script demonstrates the working caselaw dashboard with proper template and routing.
"""

import os
import json
import sys
from pathlib import Path
from datetime import datetime

# Add the repository root to Python path
repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root))

try:
    from flask import Flask, render_template, request, jsonify
    
    app = Flask(__name__, 
                template_folder='ipfs_datasets_py/templates',
                static_folder='ipfs_datasets_py/static')
    
    # Demo data
    DEMO_THEOREMS = [
        {
            "operator": "PROHIBITION",
            "proposition": "disclose confidential information to third parties without authorization",
            "agent": "Employee",
            "source_case": "Confidentiality Standards Act (2015)",
            "jurisdiction": "Federal",
            "legal_domain": "confidentiality", 
            "precedent_strength": 0.95
        },
        {
            "operator": "OBLIGATION", 
            "proposition": "provide 30 days written notice before contract termination",
            "agent": "Contractor",
            "source_case": "Contract Termination Standards (2020)",
            "jurisdiction": "State",
            "legal_domain": "contract",
            "precedent_strength": 0.85
        }
    ]
    
    @app.route('/')
    def index():
        """Main dashboard redirect."""
        return f'''
        <html>
        <head><title>IPFS Datasets Dashboard</title></head>
        <body style="font-family: Arial, sans-serif; margin: 40px;">
            <h1>🏠 IPFS Datasets Dashboard</h1>
            <div style="margin: 20px 0;">
                <a href="/mcp/caselaw" style="background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">
                    ⚖️ Caselaw Analysis Dashboard
                </a>
            </div>
            <p>Navigate to the caselaw analysis dashboard to test the temporal deontic logic RAG system.</p>
        </body>
        </html>
        '''
    
    @app.route('/mcp/caselaw')
    def caselaw_dashboard():
        """Render the fixed caselaw analysis dashboard."""
        dashboard_data = {
            'system_ready': True,
            'theorem_count': len(DEMO_THEOREMS),
            'jurisdictions': 2,
            'legal_domains': 3,
            'error_message': None
        }
        
        return render_template('admin/caselaw_dashboard.html', **dashboard_data)
    
    @app.route('/api/mcp/caselaw/check_document', methods=['POST'])
    def api_check_document():
        """Check document consistency (demo implementation)."""
        try:
            data = request.get_json()
            document_text = data.get('document_text', '')
            
            # Demo analysis - detect conflicts with confidentiality
            has_conflict = 'share confidential' in document_text.lower() or 'disclose confidential' in document_text.lower()
            
            result = {
                "is_consistent": not has_conflict,
                "confidence_score": 0.85,
                "formulas_extracted": 1,
                "processing_time": 0.002,
                "extracted_formulas": [
                    {
                        "operator": "PERMISSION",
                        "proposition": "share confidential information with partners", 
                        "agent": "Employee",
                        "confidence": 0.8
                    }
                ],
                "debug_report": {
                    "total_issues": 1 if has_conflict else 0,
                    "issues": [
                        {
                            "severity": "critical",
                            "message": "Permission to disclose conflicts with confidentiality prohibition",
                            "suggestion": "Add authorization requirements or restrict disclosure scope"
                        }
                    ] if has_conflict else []
                }
            }
            
            return jsonify(result)
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/mcp/caselaw/query_theorems', methods=['POST'])
    def api_query_theorems():
        """Query theorems using RAG (demo implementation)."""
        try:
            data = request.get_json()
            query_text = data.get('query_text', '').lower()
            
            # Simple keyword matching for demo
            relevant_theorems = []
            for theorem in DEMO_THEOREMS:
                if any(word in theorem['proposition'].lower() for word in query_text.split()):
                    relevant_theorems.append(theorem)
            
            result = {
                "total_results": len(relevant_theorems),
                "query": {"text": data.get('query_text', '')},
                "theorems": relevant_theorems
            }
            
            return jsonify(result)
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/mcp/caselaw/bulk_process', methods=['POST'])
    def api_bulk_process():
        """Start bulk processing (demo implementation)."""
        try:
            import uuid
            session_id = str(uuid.uuid4())[:8]
            
            return jsonify({
                "success": True,
                "session_id": session_id,
                "status": "started",
                "message": "Demo bulk processing started"
            })
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/mcp/caselaw/bulk_process/<session_id>')
    def api_bulk_status(session_id):
        """Get bulk processing status (demo implementation)."""
        # Simulate completed processing
        return jsonify({
            "session_id": session_id,
            "status": "completed",
            "progress": 100,
            "stats": {
                "processed_documents": 50000,
                "extracted_theorems": 10000,
                "jurisdictions_processed": ["Federal", "State", "Supreme Court"],
                "legal_domains_processed": ["contract", "employment", "confidentiality"],
                "processing_errors": 12,
                "success_rate": 0.95
            },
            "processing_time": "45 minutes",
            "output_directory": "unified_deontic_logic_system_demo"
        })
    
    if __name__ == '__main__':
        print("🚀 Starting Fixed Caselaw Dashboard Demo...")
        print("📍 Dashboard available at: http://localhost:5000/")
        print("⚖️  Caselaw Analysis at: http://localhost:5000/mcp/caselaw")
        print("\n🔧 Features:")
        print("  ✅ Document consistency checking")
        print("  ✅ RAG-based theorem retrieval") 
        print("  ✅ Bulk caselaw processing interface")
        print("  ✅ Real-time progress monitoring")
        print("\n🛑 Press Ctrl+C to stop")
        
        app.run(host='0.0.0.0', port=5000, debug=True)
        
except ImportError as e:
    print(f"❌ Missing dependencies: {e}")
    print("This demo requires Flask to be installed")