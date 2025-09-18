#!/usr/bin/env python3
"""
Simple test server to demonstrate temporal deontic logic functionality.
"""

from flask import Flask, render_template_string, jsonify, request
import json
import asyncio
import sys
from pathlib import Path

# Add the project directory to the path
project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))

from ipfs_datasets_py.temporal_deontic_caselaw_processor import TemporalDeonticCaselawProcessor

app = Flask(__name__)

# HTML template for the temporal logic demo
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Temporal Deontic Logic Demo</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 40px; border-radius: 10px; }
        .header { text-align: center; margin-bottom: 30px; }
        .doctrine-selector { background: #f8f9fa; padding: 25px; border-radius: 10px; margin-bottom: 30px; }
        .doctrine-selector select { padding: 10px; font-size: 16px; margin: 0 15px; }
        .analyze-btn { background: #28a745; color: white; padding: 12px 24px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; }
        .analyze-btn:hover { background: #218838; }
        .loading { display: none; text-align: center; color: #666; }
        .results { margin-top: 30px; }
        .timeline-item { background: #f8f9fa; padding: 15px; margin: 10px 0; border-left: 4px solid #007bff; }
        .theorem-card { background: #e9ecef; padding: 20px; margin: 15px 0; border-radius: 8px; }
        .theorem-formal { background: #fff; padding: 10px; border-radius: 5px; margin: 10px 0; font-family: monospace; }
        .consistency-status { font-size: 1.2em; font-weight: bold; text-align: center; margin: 20px 0; }
        .status-success { color: #28a745; }
        .status-error { color: #dc3545; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚖️ Temporal Deontic Logic Analysis</h1>
            <p>Convert case law precedents into formal temporal deontic logic with chronologically consistent theorems</p>
        </div>
        
        <div class="doctrine-selector">
            <label>Select Legal Doctrine:</label>
            <select id="doctrineSelect">
                <option value="">Choose a doctrine...</option>
                <option value="qualified_immunity">Qualified Immunity</option>
                <option value="civil_rights">Civil Rights</option>
                <option value="due_process">Due Process</option>
                <option value="equal_protection">Equal Protection</option>
                <option value="fourth_amendment">Fourth Amendment</option>
            </select>
            <button onclick="analyzeLogic()" class="analyze-btn">🔬 Analyze Logic</button>
        </div>
        
        <div id="loading" class="loading">
            <p>🧮 Processing temporal deontic logic conversion...</p>
            <p><small>Converting cases to first-order logic and verifying consistency...</small></p>
        </div>
        
        <div id="results" class="results" style="display: none;">
            <h2>📊 Analysis Results</h2>
            
            <div id="chronology">
                <h3>📅 Chronological Evolution</h3>
                <div id="chronologyContent"></div>
            </div>
            
            <div id="theorems">
                <h3>🧮 Generated Theorems</h3>
                <div id="theoremsContent"></div>
            </div>
            
            <div id="consistency">
                <h3>🔄 Consistency Analysis</h3>
                <div id="consistencyContent"></div>
            </div>
        </div>
    </div>

    <script>
        function analyzeLogic() {
            const doctrine = document.getElementById('doctrineSelect').value;
            if (!doctrine) {
                alert('Please select a legal doctrine');
                return;
            }
            
            document.getElementById('loading').style.display = 'block';
            document.getElementById('results').style.display = 'none';
            
            fetch(`/analyze/${doctrine}`)
                .then(response => response.json())
                .then(data => {
                    document.getElementById('loading').style.display = 'none';
                    
                    if (data.status === 'success') {
                        displayResults(data.analysis);
                        document.getElementById('results').style.display = 'block';
                    } else {
                        alert('Analysis failed: ' + data.message);
                    }
                })
                .catch(error => {
                    document.getElementById('loading').style.display = 'none';
                    alert('Error: ' + error);
                });
        }
        
        function displayResults(analysis) {
            // Display chronological evolution
            let chronologyHtml = '';
            if (analysis.temporal_patterns && analysis.temporal_patterns.chronological_evolution) {
                analysis.temporal_patterns.chronological_evolution.forEach(evolution => {
                    const year = evolution.date.substring(0, 4);
                    const caseId = evolution.case_id.replace(/_/g, ' ').replace(/\\b\\w/g, l => l.toUpperCase());
                    chronologyHtml += `
                        <div class="timeline-item">
                            <strong>${year}: ${caseId}</strong><br>
                            Obligations: ${evolution.new_obligations.length}, 
                            Permissions: ${evolution.new_permissions.length}, 
                            Prohibitions: ${evolution.new_prohibitions.length}
                        </div>
                    `;
                });
            }
            document.getElementById('chronologyContent').innerHTML = chronologyHtml;
            
            // Display theorems
            let theoremsHtml = '';
            if (analysis.generated_theorems) {
                analysis.generated_theorems.forEach((theorem, index) => {
                    theoremsHtml += `
                        <div class="theorem-card">
                            <h4>${theorem.name}</h4>
                            <div class="theorem-formal">
                                <strong>Formal Statement:</strong><br>
                                ${theorem.formal_statement.substring(0, 200)}...
                            </div>
                            <p><strong>Natural Language:</strong> ${theorem.natural_language}</p>
                            <p><strong>Supporting Cases:</strong> ${theorem.supporting_cases.length}</p>
                        </div>
                    `;
                });
            }
            document.getElementById('theoremsContent').innerHTML = theoremsHtml;
            
            // Display consistency
            let consistencyHtml = '';
            if (analysis.consistency_analysis) {
                const consistency = analysis.consistency_analysis;
                const status = consistency.overall_consistent ? 
                    '<span class="status-success">✅ CONSISTENT</span>' : 
                    '<span class="status-error">❌ CONFLICTS DETECTED</span>';
                
                consistencyHtml = `
                    <div class="consistency-status">${status}</div>
                    <p><strong>Conflicts Detected:</strong> ${consistency.conflicts_detected ? consistency.conflicts_detected.length : 0}</p>
                    <p><strong>Temporal Violations:</strong> ${consistency.temporal_violations ? consistency.temporal_violations.length : 0}</p>
                `;
            }
            document.getElementById('consistencyContent').innerHTML = consistencyHtml;
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/analyze/<doctrine>')
def analyze_doctrine(doctrine):
    try:
        # Sample cases for different doctrines
        cases_data = {
            'qualified_immunity': [
                {
                    "id": "pierson_v_ray_1967",
                    "case_name": "Pierson v. Ray", 
                    "citation": "386 U.S. 547 (1967)",
                    "date": "1967-01-15",
                    "court": "Supreme Court of the United States",
                    "content": "Police officers acting in good faith and with probable cause in arresting petitioners pursuant to an unconstitutional statute are not liable under 42 U.S.C. § 1983. Officers must have objectively reasonable belief that their conduct was lawful under clearly established law.",
                    "topic": "Civil Rights"
                },
                {
                    "id": "harlow_v_fitzgerald_1982",
                    "case_name": "Harlow v. Fitzgerald",
                    "citation": "457 U.S. 800 (1982)", 
                    "date": "1982-06-30",
                    "court": "Supreme Court of the United States",
                    "content": "Government officials performing discretionary functions generally are shielded from liability for civil damages insofar as their conduct does not violate clearly established statutory or constitutional rights of which a reasonable person would have known. Officials must show that their conduct was objectively reasonable.",
                    "topic": "Constitutional Law"
                }
            ],
            'civil_rights': [
                {
                    "id": "brown_v_board_1954",
                    "case_name": "Brown v. Board of Education",
                    "citation": "347 U.S. 483 (1954)",
                    "date": "1954-05-17",
                    "court": "Supreme Court of the United States",
                    "content": "Separate educational facilities are inherently unequal. States cannot maintain segregated public schools. All children must have equal access to education regardless of race.",
                    "topic": "Education"
                }
            ]
        }
        
        cases = cases_data.get(doctrine, [])
        if not cases:
            return jsonify({'status': 'error', 'message': f'No cases available for doctrine: {doctrine}'})
        
        # Process through temporal deontic logic
        processor = TemporalDeonticCaselawProcessor()
        
        # Run async analysis
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(processor.process_caselaw_lineage(cases, doctrine))
        loop.close()
        
        return jsonify({
            'status': 'success',
            'doctrine': doctrine,
            'analysis': result
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'message': str(e)
        })

if __name__ == '__main__':
    print("🚀 Starting Temporal Deontic Logic Demo Server...")
    print("📍 Visit http://localhost:5002 to test the functionality")
    app.run(host='0.0.0.0', port=5002, debug=True)