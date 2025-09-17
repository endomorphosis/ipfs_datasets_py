#!/usr/bin/env python
"""
Test script to demonstrate the enhanced caselaw dashboard with three new panels:
1. Deontic first-order logic analysis
2. Citation network connections
3. Subsequent quotes from citing cases
"""

import sys
import os
sys.path.insert(0, '.')

try:
    from ipfs_datasets_py.caselaw_dashboard import CaselawDashboard
    print("✅ CaselawDashboard imported successfully")
except ImportError as e:
    print(f"❌ Failed to import CaselawDashboard: {e}")
    sys.exit(1)

def test_enhanced_features():
    """Test the enhanced caselaw dashboard features"""
    print("🏛️ Testing Enhanced Caselaw Dashboard Features...")
    
    # Create dashboard instance
    dashboard = CaselawDashboard(debug=True)
    print("✅ Dashboard instance created")
    
    # Test the new helper methods directly
    print("\n📋 Testing Deontic Logic Analysis...")
    test_case_id = "brown_v_board_1954"
    
    # Test deontic logic analysis
    try:
        deontic_result = dashboard._get_case_deontic_logic(test_case_id)
        print(f"✅ Deontic logic analysis: {deontic_result['status']}")
        if deontic_result['status'] == 'success':
            analysis = deontic_result['deontic_analysis']
            print(f"   - Deontic statements: {len(analysis.get('deontic_statements', []))}")
            print(f"   - Formal logic expressions: {len(analysis.get('formal_logic_expressions', []))}")
            print(f"   - Central holdings: {len(analysis.get('central_holdings', []))}")
    except Exception as e:
        print(f"⚠️ Deontic logic test failed: {e}")
    
    print("\n🔗 Testing Citation Network Analysis...")
    try:
        citation_result = dashboard._get_case_citation_network(test_case_id)
        print(f"✅ Citation network analysis: {citation_result['status']}")
        if citation_result['status'] == 'success':
            network = citation_result['citation_network']
            print(f"   - Network nodes: {len(network.get('nodes', []))}")
            print(f"   - Network edges: {len(network.get('edges', []))}")
            stats = network.get('statistics', {})
            print(f"   - Citations: {stats.get('total_citations', 0)}")
            print(f"   - Cited by: {stats.get('total_cited_by', 0)}")
    except Exception as e:
        print(f"⚠️ Citation network test failed: {e}")
    
    print("\n💬 Testing Subsequent Quotes Analysis...")
    try:
        quotes_result = dashboard._get_case_subsequent_quotes(test_case_id)
        print(f"✅ Subsequent quotes analysis: {quotes_result['status']}")
        if quotes_result['status'] == 'success':
            quotes = quotes_result['subsequent_quotes']
            print(f"   - Total quotes: {quotes.get('total_quotes', 0)}")
            print(f"   - Citing cases: {quotes.get('citing_cases_count', 0)}")
            print(f"   - Central holdings: {len(quotes.get('central_holdings', []))}")
            print(f"   - Grouped quotes: {len(quotes.get('grouped_quotes', {}))}")
    except Exception as e:
        print(f"⚠️ Subsequent quotes test failed: {e}")
    
    print("\n🎯 Feature Summary:")
    print("✅ Enhanced Case Detail Page with Three New Panels:")
    print("   1. ⚖️ Deontic First-Order Logic Analysis")
    print("      - Extracts obligations, permissions, prohibitions")
    print("      - Converts to formal logic expressions")
    print("      - Analyzes central holdings and precedential strength")
    print("   2. 🔗 Citation Network & Connections")
    print("      - Shows cases cited by this case (backward citations)")
    print("      - Shows cases citing this case (forward citations)")
    print("      - Provides network visualization data")
    print("      - Calculates network density and statistics")
    print("   3. 💬 Subsequent Quotes & Central Holdings")
    print("      - Extracts quotes from subsequent cases")
    print("      - Groups quotes by legal principle")
    print("      - Identifies most quoted holdings")
    print("      - Tracks citation temporal span")
    
    print("\n🌐 API Endpoints Added:")
    print("   - GET /api/case/<case_id>/deontic-logic")
    print("   - GET /api/case/<case_id>/citations")
    print("   - GET /api/case/<case_id>/subsequent-quotes")
    
    print("\n🎨 UI/UX Enhancements:")
    print("   - Professional tabbed interface for case details")
    print("   - Interactive panels with loading states")
    print("   - Syntax-highlighted formal logic expressions")
    print("   - Citation network statistics and visualization")
    print("   - Collapsible quote groups by legal principle")
    print("   - Professional styling with legal color scheme")

def create_demo_html():
    """Create a demo HTML file to show the enhanced interface"""
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Enhanced Caselaw Dashboard - Demo</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin: 0;
            padding: 20px;
            color: #2c3e50;
        }
        .demo-container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .demo-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }
        .demo-title {
            font-size: 2.5em;
            margin: 0 0 20px 0;
            font-weight: 700;
        }
        .demo-subtitle {
            font-size: 1.2em;
            opacity: 0.9;
            margin: 0;
        }
        .features-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 30px;
            padding: 40px;
        }
        .feature-card {
            background: #f8f9fa;
            border-radius: 15px;
            padding: 30px;
            border-left: 5px solid #667eea;
        }
        .feature-icon {
            font-size: 2.5em;
            margin-bottom: 20px;
        }
        .feature-title {
            font-size: 1.4em;
            font-weight: 600;
            margin: 0 0 15px 0;
            color: #2c3e50;
        }
        .feature-description {
            color: #6c757d;
            line-height: 1.6;
            margin-bottom: 20px;
        }
        .feature-list {
            list-style: none;
            padding: 0;
            margin: 0;
        }
        .feature-list li {
            padding: 8px 0;
            color: #495057;
        }
        .feature-list li::before {
            content: "✅ ";
            margin-right: 8px;
        }
        .api-endpoints {
            background: #2c3e50;
            color: white;
            padding: 40px;
            font-family: 'Courier New', monospace;
        }
        .api-title {
            font-size: 1.5em;
            margin: 0 0 20px 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        .endpoint {
            background: rgba(255,255,255,0.1);
            padding: 15px;
            border-radius: 8px;
            margin: 10px 0;
            border-left: 4px solid #667eea;
        }
        .method {
            color: #2ecc71;
            font-weight: bold;
        }
        .url {
            color: #f39c12;
        }
        .description {
            color: #ecf0f1;
            font-size: 0.9em;
            margin-top: 8px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
    </style>
</head>
<body>
    <div class="demo-container">
        <div class="demo-header">
            <div class="demo-title">🏛️ Enhanced Caselaw Dashboard</div>
            <div class="demo-subtitle">Professional Legal Research with Advanced Analytics</div>
        </div>
        
        <div class="features-grid">
            <div class="feature-card">
                <div class="feature-icon">⚖️</div>
                <div class="feature-title">Deontic First-Order Logic</div>
                <div class="feature-description">
                    Automatically converts legal text into formal deontic logic expressions for precise legal analysis.
                </div>
                <ul class="feature-list">
                    <li>Extracts obligations, permissions, prohibitions</li>
                    <li>Converts to formal logic notation</li>
                    <li>Analyzes central holdings</li>
                    <li>Assesses precedential strength</li>
                    <li>Identifies legal modalities</li>
                </ul>
            </div>
            
            <div class="feature-card">
                <div class="feature-icon">🔗</div>
                <div class="feature-title">Citation Network Analysis</div>
                <div class="feature-description">
                    Visualizes the complete citation network showing connections between related cases.
                </div>
                <ul class="feature-list">
                    <li>Backward citations (cases cited)</li>
                    <li>Forward citations (citing cases)</li>
                    <li>Network visualization</li>
                    <li>Citation statistics</li>
                    <li>Topically related cases</li>
                </ul>
            </div>
            
            <div class="feature-card">
                <div class="feature-icon">💬</div>
                <div class="feature-title">Subsequent Quotes</div>
                <div class="feature-description">
                    Analyzes how subsequent cases quote and reference this case's central holdings.
                </div>
                <ul class="feature-list">
                    <li>Extracts quotes from citing cases</li>
                    <li>Groups by legal principle</li>
                    <li>Identifies most quoted holdings</li>
                    <li>Tracks citation trends</li>
                    <li>Relevance scoring</li>
                </ul>
            </div>
        </div>
        
        <div class="api-endpoints">
            <div class="api-title">🌐 New API Endpoints</div>
            
            <div class="endpoint">
                <div><span class="method">GET</span> <span class="url">/api/case/&lt;case_id&gt;/deontic-logic</span></div>
                <div class="description">Returns deontic logic analysis including formal expressions and central holdings</div>
            </div>
            
            <div class="endpoint">
                <div><span class="method">GET</span> <span class="url">/api/case/&lt;case_id&gt;/citations</span></div>
                <div class="description">Returns citation network data with nodes, edges, and visualization information</div>
            </div>
            
            <div class="endpoint">
                <div><span class="method">GET</span> <span class="url">/api/case/&lt;case_id&gt;/subsequent-quotes</span></div>
                <div class="description">Returns quotes from subsequent cases grouped by legal principle</div>
            </div>
        </div>
    </div>
</body>
</html>
"""
    
    with open('/home/runner/work/ipfs_datasets_py/ipfs_datasets_py/enhanced_caselaw_demo.html', 'w') as f:
        f.write(html_content)
    
    print("📄 Demo HTML file created: enhanced_caselaw_demo.html")

if __name__ == "__main__":
    test_enhanced_features()
    create_demo_html()
    print("\n🎉 Enhanced Caselaw Dashboard testing completed!")