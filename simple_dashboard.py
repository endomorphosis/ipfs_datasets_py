#!/usr/bin/env python3

from flask import Flask, render_template_string
import sys
from pathlib import Path

# Add the project directory to the path
project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))

app = Flask(__name__)

@app.route('/')
def index():
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <title>Caselaw Access Project - Legal Research Platform</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body { 
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
            margin: 0; padding: 0; background: #f8fafc; color: #1e293b; line-height: 1.6;
            font-size: 14px;
        }
        
        .header { 
            background: #1e293b; color: white; padding: 20px 0; border-bottom: 3px solid #0f172a;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        
        .header .container {
            display: flex; justify-content: space-between; align-items: center;
            max-width: 1400px; margin: 0 auto; padding: 0 24px;
        }
        
        .header h1 { 
            font-size: 1.75rem; font-weight: 600; margin: 0;
            display: flex; align-items: center; gap: 12px;
        }
        
        .legal-badge {
            background: #dc2626; color: white; padding: 4px 8px;
            border-radius: 4px; font-size: 0.75rem; font-weight: 500;
            text-transform: uppercase; letter-spacing: 0.5px;
        }
        
        .container { max-width: 1400px; margin: 0 auto; padding: 24px; }
        
        .metrics-grid { 
            display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 24px; margin-bottom: 32px;
        }
        
        .metric-card {
            background: white; border-radius: 8px; padding: 24px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            border: 1px solid #e2e8f0;
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        
        .metric-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        
        .metric-header { display: flex; justify-content: space-between; align-items: flex-start; }
        .metric-title { font-size: 0.875rem; color: #64748b; font-weight: 500; }
        .metric-value { font-size: 2.25rem; font-weight: 700; color: #1e293b; margin: 8px 0 4px; }
        .metric-change { font-size: 0.75rem; color: #22c55e; font-weight: 500; }
        .metric-icon { font-size: 2rem; opacity: 0.8; }
        
        .nav-tabs {
            background: white; border-radius: 8px; padding: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            border: 1px solid #e2e8f0; margin-bottom: 24px;
        }
        
        .nav-tabs-list { display: flex; gap: 4px; }
        
        .nav-tab {
            flex: 1; padding: 12px 20px; border: none; background: transparent;
            color: #64748b; font-weight: 500; cursor: pointer;
            border-radius: 6px; transition: all 0.2s ease;
        }
        
        .nav-tab:hover { background: #f8fafc; color: #1e293b; }
        
        .nav-tab.active {
            background: #3b82f6; color: white;
            box-shadow: 0 2px 4px rgba(59, 130, 246, 0.3);
        }
        
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        .search-section {
            background: white; border-radius: 8px; padding: 32px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            border: 1px solid #e2e8f0;
        }
        
        .search-header { text-align: center; margin-bottom: 32px; }
        .search-header h2 { font-size: 1.5rem; font-weight: 600; color: #1e293b; margin-bottom: 8px; }
        .search-header p { color: #64748b; font-size: 1rem; }
        
        .search-form { display: flex; gap: 16px; margin-bottom: 24px; }
        .search-input {
            flex: 1; padding: 12px 16px; border: 1px solid #d1d5db;
            border-radius: 6px; font-size: 1rem;
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
        }
        .search-input:focus {
            outline: none; border-color: #3b82f6;
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
        }
        
        .search-button {
            padding: 12px 24px; background: #3b82f6; color: white;
            border: none; border-radius: 6px; font-weight: 500;
            cursor: pointer; transition: background 0.2s ease;
        }
        .search-button:hover { background: #2563eb; }
        
        .search-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
        .filter-tag {
            padding: 6px 12px; background: #f1f5f9; color: #475569;
            border-radius: 20px; font-size: 0.875rem; cursor: pointer;
            transition: all 0.2s ease;
        }
        .filter-tag:hover { background: #e2e8f0; color: #1e293b; }
        
        .results-section { margin-top: 32px; }
        .results-header { margin-bottom: 24px; }
        .results-title { font-size: 1.25rem; font-weight: 600; color: #1e293b; }
        .results-count { color: #64748b; font-size: 0.875rem; margin-top: 4px; }
        
        .case-result {
            background: white; border: 1px solid #e2e8f0; border-radius: 8px;
            padding: 20px; margin-bottom: 16px; cursor: pointer;
            transition: all 0.2s ease;
        }
        .case-result:hover {
            border-color: #3b82f6; box-shadow: 0 2px 8px rgba(59, 130, 246, 0.1);
        }
        
        .case-title { font-size: 1.125rem; font-weight: 600; color: #1e293b; margin-bottom: 8px; }
        .case-citation {
            font-family: 'SF Mono', Consolas, monospace; font-size: 0.875rem;
            color: #3b82f6; font-weight: 500; margin-bottom: 12px;
            padding: 4px 8px; background: #f0f9ff; border-radius: 4px;
            border-left: 3px solid #3b82f6; display: inline-block;
        }
        .case-summary { color: #475569; line-height: 1.6; margin-bottom: 12px; }
        .case-meta { display: flex; align-items: center; gap: 16px; }
        .meta-item { font-size: 0.75rem; color: #64748b; }
        
        .footer {
            background: #f1f5f9; border-top: 1px solid #e2e8f0; 
            padding: 24px; text-align: center; margin-top: 48px;
        }
        .footer-text { font-size: 0.75rem; color: #64748b; }
    </style>
</head>
<body>
    <!-- Professional Legal Research Platform Header -->
    <div class="header">
        <div class="container">
            <h1>
                ⚖️ Caselaw Access Project
                <span class="legal-badge">Legal Research</span>
            </h1>
            <div class="user-info">
                <span>Legal Research Platform</span>
                <span>•</span>
                <span>131 Total Resources</span>
            </div>
        </div>
    </div>
    
    <!-- Main Container -->
    <div class="container">
        <!-- Key Metrics -->
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-header">
                    <div>
                        <div class="metric-title">Legal Cases</div>
                        <div class="metric-value">100</div>
                        <div class="metric-change">+50 available</div>
                    </div>
                    <div class="metric-icon">⚖️</div>
                </div>
            </div>
            <div class="metric-card">
                <div class="metric-header">
                    <div>
                        <div class="metric-title">Knowledge Entities</div>
                        <div class="metric-value">131</div>
                        <div class="metric-change">Linked resources</div>
                    </div>
                    <div class="metric-icon">🏛️</div>
                </div>
            </div>
            <div class="metric-card">
                <div class="metric-header">
                    <div>
                        <div class="metric-title">Legal Relationships</div>
                        <div class="metric-value">772</div>
                        <div class="metric-change">Precedent connections</div>
                    </div>
                    <div class="metric-icon">🔗</div>
                </div>
            </div>
            <div class="metric-card">
                <div class="metric-header">
                    <div>
                        <div class="metric-title">Temporal Coverage</div>
                        <div class="metric-value">219</div>
                        <div class="metric-change">Years of jurisprudence</div>
                    </div>
                    <div class="metric-icon">📅</div>
                </div>
            </div>
        </div>
        
        <!-- Professional Navigation Tabs -->
        <div class="nav-tabs">
            <div class="nav-tabs-list">
                <button class="nav-tab active" onclick="showTab('search')">🔍 Case Search</button>
                <button class="nav-tab" onclick="showTab('doctrines')">🏷️ Legal Doctrines</button>
                <button class="nav-tab" onclick="showTab('temporal')">⚖️ Temporal Logic</button>
                <button class="nav-tab" onclick="showTab('analytics')">📊 Analytics</button>
            </div>
        </div>
        
        <!-- Tab Content -->
        <div class="tab-content-container">
            <!-- Case Search Tab -->
            <div id="search-tab" class="tab-content active">
                <div class="search-section">
                    <div class="search-header">
                        <h2>Legal Case Research</h2>
                        <p>Search through comprehensive caselaw database using advanced GraphRAG technology for legal precedent analysis</p>
                    </div>
                    <div class="search-form">
                        <input type="text" class="search-input" id="searchQuery" placeholder="Enter case name, citation, legal doctrine, or search terms..." />
                        <button class="search-button" onclick="performSearch()">Search Cases</button>
                    </div>
                    <div class="search-filters">
                        <div class="filter-tag" onclick="setSearchQuery('civil rights')">Civil Rights</div>
                        <div class="filter-tag" onclick="setSearchQuery('Supreme Court')">Supreme Court</div>
                        <div class="filter-tag" onclick="setSearchQuery('constitutional law')">Constitutional Law</div>
                        <div class="filter-tag" onclick="setSearchQuery('criminal procedure')">Criminal Procedure</div>
                        <div class="filter-tag" onclick="setSearchQuery('qualified immunity')">Qualified Immunity</div>
                        <div class="filter-tag" onclick="setSearchQuery('due process')">Due Process</div>
                    </div>
                    
                    <!-- Search Results -->
                    <div id="searchResults" class="results-section" style="display: none;">
                        <div class="results-header">
                            <div class="results-title" id="resultsCount">Search Results</div>
                        </div>
                        <div id="casesList">
                            <!-- Cases will be populated by JavaScript -->
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Legal Doctrines Tab -->
            <div id="doctrines-tab" class="tab-content">
                <div class="search-section">
                    <div class="search-header">
                        <h2>🏷️ Legal Doctrines Explorer</h2>
                        <p>Explore legal doctrines through intelligent clustering and case relationship analysis</p>
                    </div>
                    <div class="search-form">
                        <input type="text" class="search-input" placeholder="Filter legal doctrines..." />
                        <button class="search-button">🔍 Filter</button>
                    </div>
                    <div style="text-align: center; padding: 60px; color: #64748b;">
                        <h3>Tag Cloud with K-means Clustering</h3>
                        <p>Interactive doctrine exploration coming soon...</p>
                    </div>
                </div>
            </div>
            
            <!-- Temporal Logic Tab -->
            <div id="temporal-tab" class="tab-content">
                <div class="search-section">
                    <div class="search-header">
                        <h2>⚖️ Temporal Deontic Logic Analysis</h2>
                        <p>Convert legal precedents into formal temporal deontic logic and analyze chronological consistency</p>
                    </div>
                    <div class="search-form">
                        <select class="search-input">
                            <option>Select a legal doctrine...</option>
                            <option>Qualified Immunity</option>
                            <option>Civil Rights</option>
                            <option>Due Process</option>
                        </select>
                        <button class="search-button">🔬 Analyze Logic</button>
                    </div>
                    <div style="text-align: center; padding: 60px; color: #64748b;">
                        <h3>Temporal Deontic Logic Processor</h3>
                        <p>Formal logic analysis and theorem generation...</p>
                    </div>
                </div>
            </div>
            
            <!-- Analytics Tab -->
            <div id="analytics-tab" class="tab-content">
                <div class="search-section">
                    <div class="search-header">
                        <h2>📊 Dataset Analytics</h2>
                        <p>Comprehensive statistical analysis of legal case dataset</p>
                    </div>
                    <div style="text-align: center; padding: 60px; color: #64748b;">
                        <h3>Analytics Dashboard</h3>
                        <p>Statistical insights and data visualization...</p>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Professional Footer -->
    <div class="footer">
        <div class="footer-text">
            © 2024 Caselaw Access Project GraphRAG Dashboard | Powered by IPFS Datasets Python
        </div>
    </div>
    
    <script>
        // Tab management
        function showTab(tabName) {
            // Hide all tabs
            document.querySelectorAll('.tab-content').forEach(tab => {
                tab.classList.remove('active');
            });
            document.querySelectorAll('.nav-tab').forEach(tab => {
                tab.classList.remove('active');
            });
            
            // Show selected tab
            document.getElementById(tabName + '-tab').classList.add('active');
            event.target.classList.add('active');
        }
        
        // Search functionality
        function performSearch() {
            const query = document.getElementById('searchQuery').value.trim();
            if (!query) return;
            
            // Mock search results for demonstration
            const mockResults = [
                {
                    id: 'brown_v_board_1954',
                    title: 'Brown v. Board of Education of Topeka',
                    citation: '347 U.S. 483 (1954)',
                    summary: 'Landmark Supreme Court case that declared racial segregation in public schools unconstitutional, overturning Plessy v. Ferguson.',
                    court: 'Supreme Court of the United States',
                    year: 1954,
                    relevance: 0.95
                },
                {
                    id: 'miranda_v_arizona_1966',
                    title: 'Miranda v. Arizona',
                    citation: '384 U.S. 436 (1966)',
                    summary: 'Supreme Court ruling establishing that defendants must be informed of their rights before police interrogation.',
                    court: 'Supreme Court of the United States',
                    year: 1966,
                    relevance: 0.87
                }
            ];
            
            displayResults({ results: mockResults, query: query });
        }
        
        function setSearchQuery(query) {
            document.getElementById('searchQuery').value = query;
            performSearch();
        }
        
        function displayResults(data) {
            const resultsDiv = document.getElementById('searchResults');
            const countDiv = document.getElementById('resultsCount');
            const listDiv = document.getElementById('casesList');
            
            if (data.results && data.results.length > 0) {
                countDiv.textContent = data.results.length + ' cases found for "' + data.query + '"';
                
                const casesHTML = data.results.map(caseItem => `
                    <div class="case-result">
                        <div class="case-title">${caseItem.title}</div>
                        <div class="case-citation">${caseItem.citation}</div>
                        <div class="case-summary">${caseItem.summary}</div>
                        <div class="case-meta">
                            <div class="meta-item"><strong>${caseItem.court}</strong> • ${caseItem.year}</div>
                            <div class="meta-item">Relevance: ${(caseItem.relevance * 100).toFixed(1)}%</div>
                        </div>
                    </div>
                `).join('');
                
                listDiv.innerHTML = casesHTML;
                resultsDiv.style.display = 'block';
            } else {
                countDiv.textContent = 'No cases found for "' + (data.query || 'your search') + '"';
                listDiv.innerHTML = '<div style="text-align: center; padding: 40px; color: #64748b;">No matching cases found. Try different search terms.</div>';
                resultsDiv.style.display = 'block';
            }
        }
        
        // Initialize with demo search
        document.addEventListener('DOMContentLoaded', function() {
            setSearchQuery('civil rights');
        });
    </script>
</body>
</html>
    ''')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)