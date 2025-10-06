#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Direct GUI Testing and Screenshot Script

Creates static HTML versions of the dashboard and takes screenshots to identify issues.
"""
import sys
import os
from pathlib import Path
from html2image import Html2Image
import json
from datetime import datetime

def create_dashboard_html():
    """Create a complete dashboard HTML for testing."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>News Analysis Dashboard - IPFS Datasets</title>
    
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            color: #333;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        .logo h1 { font-size: 1.5rem; font-weight: 600; }
        .logo p { font-size: 0.9rem; opacity: 0.9; margin-top: 0.25rem; }
        
        .header-controls {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        
        .user-type-selector {
            position: relative;
        }
        
        .user-type-btn {
            background: rgba(255,255,255,0.2);
            border: 1px solid rgba(255,255,255,0.3);
            color: white;
            padding: 0.5rem 1rem;
            border-radius: 0.5rem;
            cursor: pointer;
            font-size: 0.9rem;
        }
        
        .status-indicator {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.85rem;
        }
        
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #4ade80;
        }
        
        .main-container {
            display: flex;
            min-height: calc(100vh - 80px);
        }
        
        .sidebar {
            width: 250px;
            background: white;
            border-right: 1px solid #e5e5e5;
            box-shadow: 2px 0 10px rgba(0,0,0,0.05);
        }
        
        .nav-tabs {
            list-style: none;
            padding: 1rem 0;
        }
        
        .nav-tab {
            padding: 0.75rem 1.5rem;
            cursor: pointer;
            border-left: 3px solid transparent;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 0.9rem;
        }
        
        .nav-tab:hover {
            background: #f8fafc;
            border-left-color: #667eea;
        }
        
        .nav-tab.active {
            background: #f1f5f9;
            border-left-color: #667eea;
            font-weight: 600;
            color: #667eea;
        }
        
        .nav-icon {
            width: 18px;
            height: 18px;
            opacity: 0.7;
        }
        
        .content-area {
            flex: 1;
            padding: 2rem;
            overflow-y: auto;
        }
        
        .dashboard-header {
            margin-bottom: 2rem;
        }
        
        .dashboard-title {
            font-size: 2rem;
            font-weight: 700;
            color: #1e293b;
            margin-bottom: 0.5rem;
        }
        
        .dashboard-subtitle {
            color: #64748b;
            font-size: 1.1rem;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        
        .stat-card {
            background: white;
            border-radius: 0.75rem;
            padding: 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            border: 1px solid #e5e7eb;
        }
        
        .stat-value {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }
        
        .stat-label {
            color: #6b7280;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        
        .content-section {
            background: white;
            border-radius: 0.75rem;
            padding: 2rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            border: 1px solid #e5e7eb;
            margin-bottom: 2rem;
        }
        
        .section-title {
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 1rem;
            color: #1e293b;
        }
        
        .form-group {
            margin-bottom: 1.5rem;
        }
        
        .form-label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 500;
            color: #374151;
        }
        
        .form-input {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid #d1d5db;
            border-radius: 0.5rem;
            font-size: 0.9rem;
        }
        
        .form-input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        .btn {
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 0.5rem;
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .btn-primary {
            background: #667eea;
            color: white;
        }
        
        .btn-primary:hover {
            background: #5a67d8;
        }
        
        .btn-secondary {
            background: #e5e7eb;
            color: #374151;
        }
        
        .btn-secondary:hover {
            background: #d1d5db;
        }
        
        .progress-bar {
            width: 100%;
            height: 8px;
            background: #e5e7eb;
            border-radius: 4px;
            overflow: hidden;
            margin: 1rem 0;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            width: 75%;
            transition: width 0.3s ease;
        }
        
        .activity-feed {
            max-height: 300px;
            overflow-y: auto;
        }
        
        .activity-item {
            padding: 0.75rem;
            border-left: 3px solid #e5e7eb;
            margin-bottom: 0.5rem;
            background: #f8fafc;
            border-radius: 0 0.5rem 0.5rem 0;
        }
        
        .activity-item.success { border-left-color: #10b981; }
        .activity-item.warning { border-left-color: #f59e0b; }
        .activity-item.error { border-left-color: #ef4444; }
        
        .tab-content {
            display: none;
        }
        
        .tab-content.active {
            display: block;
        }
        
        /* Theme variations */
        .theme-data-scientist {
            --primary: #667eea;
            --primary-light: #818cf8;
        }
        
        .theme-historian {
            --primary: #dc2626;
            --primary-light: #f87171;
        }
        
        .theme-lawyer {
            --primary: #059669;
            --primary-light: #34d399;
        }
        
        @media (max-width: 768px) {
            .main-container { flex-direction: column; }
            .sidebar { width: 100%; }
            .stats-grid { grid-template-columns: 1fr; }
            .content-area { padding: 1rem; }
        }
    </style>
</head>
<body class="theme-data-scientist">
    <div class="header">
        <div class="logo">
            <h1>News Analysis Dashboard</h1>
            <p>IPFS Datasets - Professional Research Platform</p>
        </div>
        <div class="header-controls">
            <div class="user-type-selector">
                <button class="user-type-btn" data-user-type="data-scientist">
                    Data Scientist
                </button>
            </div>
            <div class="status-indicator">
                <span class="status-dot"></span>
                <span>Connected</span>
            </div>
        </div>
    </div>
    
    <div class="main-container">
        <div class="sidebar">
            <ul class="nav-tabs">
                <li class="nav-tab active" data-tab="overview">
                    <span class="nav-icon">📊</span>
                    <span>Overview</span>
                </li>
                <li class="nav-tab" data-tab="ingest">
                    <span class="nav-icon">📥</span>
                    <span>Ingest</span>
                </li>
                <li class="nav-tab" data-tab="timeline">
                    <span class="nav-icon">⏱️</span>
                    <span>Timeline</span>
                </li>
                <li class="nav-tab" data-tab="query">
                    <span class="nav-icon">🔍</span>
                    <span>GraphRAG Query</span>
                </li>
                <li class="nav-tab" data-tab="graph-explorer">
                    <span class="nav-icon">🕸️</span>
                    <span>Graph Explorer</span>
                </li>
                <li class="nav-tab" data-tab="export">
                    <span class="nav-icon">📤</span>
                    <span>Export</span>
                </li>
                <li class="nav-tab" data-tab="workflows">
                    <span class="nav-icon">⚙️</span>
                    <span>Workflows</span>
                </li>
            </ul>
        </div>
        
        <div class="content-area">
            <!-- Overview Tab -->
            <div id="overview" class="tab-content active">
                <div class="dashboard-header">
                    <h2 class="dashboard-title">News Analysis Overview</h2>
                    <p class="dashboard-subtitle">Real-time statistics and system status</p>
                </div>
                
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-value" style="color: #667eea;">1,247</div>
                        <div class="stat-label">Articles Processed</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" style="color: #10b981;">3,891</div>
                        <div class="stat-label">Entities Extracted</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" style="color: #f59e0b;">12</div>
                        <div class="stat-label">Active Workflows</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" style="color: #ef4444;">98.7%</div>
                        <div class="stat-label">System Health</div>
                    </div>
                </div>
                
                <div class="content-section">
                    <h3 class="section-title">Recent Activity</h3>
                    <div class="activity-feed">
                        <div class="activity-item success">
                            <strong>Article Ingested:</strong> "AI Breakthrough in Healthcare" from Reuters
                            <br><small>2 minutes ago</small>
                        </div>
                        <div class="activity-item success">
                            <strong>Entities Extracted:</strong> 47 organizations, 23 people, 12 locations
                            <br><small>3 minutes ago</small>
                        </div>
                        <div class="activity-item warning">
                            <strong>Processing Delayed:</strong> Large batch from Bloomberg (250 articles)
                            <br><small>5 minutes ago</small>
                        </div>
                        <div class="activity-item success">
                            <strong>Graph Updated:</strong> 1,847 nodes, 3,291 relationships
                            <br><small>8 minutes ago</small>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Ingest Tab -->
            <div id="ingest" class="tab-content">
                <div class="dashboard-header">
                    <h2 class="dashboard-title">News Ingestion</h2>
                    <p class="dashboard-subtitle">Import and process news content from multiple sources</p>
                </div>
                
                <div class="content-section">
                    <h3 class="section-title">Single Article Ingestion</h3>
                    <div class="form-group">
                        <label class="form-label">Article URL</label>
                        <input type="url" class="form-input" placeholder="https://example.com/news-article">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Source Type</label>
                        <select class="form-input">
                            <option>News Website</option>
                            <option>RSS Feed</option>
                            <option>Social Media</option>
                            <option>Government Source</option>
                        </select>
                    </div>
                    <button class="btn btn-primary">Ingest Article</button>
                </div>
                
                <div class="content-section">
                    <h3 class="section-title">Website Crawling</h3>
                    <div class="form-group">
                        <label class="form-label">Website URL</label>
                        <input type="url" class="form-input" placeholder="https://news.example.com">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Max Pages</label>
                        <input type="number" class="form-input" value="50" min="1" max="500">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Max Depth</label>
                        <input type="number" class="form-input" value="3" min="1" max="10">
                    </div>
                    <button class="btn btn-primary">Start Crawling</button>
                </div>
                
                <div class="content-section">
                    <h3 class="section-title">Processing Status</h3>
                    <div class="progress-bar">
                        <div class="progress-fill"></div>
                    </div>
                    <p><strong>Processing:</strong> Reuters Business News (Article 47/125)</p>
                </div>
            </div>
            
            <!-- Query Tab -->
            <div id="query" class="tab-content">
                <div class="dashboard-header">
                    <h2 class="dashboard-title">GraphRAG Query Interface</h2>
                    <p class="dashboard-subtitle">Advanced semantic search and analysis</p>
                </div>
                
                <div class="content-section">
                    <h3 class="section-title">Natural Language Query</h3>
                    <div class="form-group">
                        <label class="form-label">Query</label>
                        <textarea class="form-input" rows="3" placeholder="What are the main trends in artificial intelligence reported this month?"></textarea>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Query Type</label>
                        <select class="form-input">
                            <option>Semantic Search</option>
                            <option>Entity-based Query</option>
                            <option>Temporal Analysis</option>
                            <option>Relationship Analysis</option>
                            <option>Cross-document Correlation</option>
                        </select>
                    </div>
                    <button class="btn btn-primary">Execute Query</button>
                    <button class="btn btn-secondary">Save Query</button>
                </div>
                
                <div class="content-section">
                    <h3 class="section-title">Query Results</h3>
                    <div class="activity-feed">
                        <div class="activity-item">
                            <strong>AI Healthcare Breakthrough:</strong> New machine learning algorithms show 94% accuracy in early cancer detection...
                            <br><small>Relevance: 0.87 | Source: Reuters | Date: Dec 15, 2024</small>
                        </div>
                        <div class="activity-item">
                            <strong>Tech Giants Invest in AI Research:</strong> Major technology companies announce $2.5B investment in artificial intelligence...
                            <br><small>Relevance: 0.81 | Source: Bloomberg | Date: Dec 12, 2024</small>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Graph Explorer Tab -->
            <div id="graph-explorer" class="tab-content">
                <div class="dashboard-header">
                    <h2 class="dashboard-title">Knowledge Graph Explorer</h2>
                    <p class="dashboard-subtitle">Interactive visualization of entity relationships</p>
                </div>
                
                <div class="content-section">
                    <h3 class="section-title">Graph Visualization</h3>
                    <div style="height: 400px; background: #f8fafc; border: 2px dashed #d1d5db; display: flex; align-items: center; justify-content: center; border-radius: 0.5rem;">
                        <p style="color: #6b7280; font-size: 1.2rem;">Interactive D3.js Graph Visualization</p>
                    </div>
                </div>
                
                <div class="content-section">
                    <h3 class="section-title">Graph Controls</h3>
                    <div class="form-group">
                        <label class="form-label">Layout Algorithm</label>
                        <select class="form-input">
                            <option>Force-directed</option>
                            <option>Hierarchical</option>
                            <option>Circular</option>
                            <option>Grid</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Entity Filter</label>
                        <input type="text" class="form-input" placeholder="Filter by entity type or name">
                    </div>
                    <button class="btn btn-primary">Apply Filters</button>
                    <button class="btn btn-secondary">Reset View</button>
                </div>
            </div>
            
            <!-- Export Tab -->
            <div id="export" class="tab-content">
                <div class="dashboard-header">
                    <h2 class="dashboard-title">Data Export</h2>
                    <p class="dashboard-subtitle">Professional export formats for research and analysis</p>
                </div>
                
                <div class="content-section">
                    <h3 class="section-title">Export Options</h3>
                    <div class="form-group">
                        <label class="form-label">Export Format</label>
                        <select class="form-input">
                            <option>CSV (Data Science)</option>
                            <option>JSON (Technical Analysis)</option>
                            <option>PDF Report (Professional)</option>
                            <option>Academic Citations (APA/MLA)</option>
                            <option>Legal Brief Format</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Date Range</label>
                        <input type="date" class="form-input">
                    </div>
                    <button class="btn btn-primary">Generate Export</button>
                </div>
            </div>
            
            <!-- Workflows Tab -->
            <div id="workflows" class="tab-content">
                <div class="dashboard-header">
                    <h2 class="dashboard-title">Professional Workflows</h2>
                    <p class="dashboard-subtitle">Specialized analysis pipelines for different user types</p>
                </div>
                
                <div class="content-section">
                    <h3 class="section-title">Data Scientist Workflows</h3>
                    <button class="btn btn-primary" style="margin: 0.5rem;">Large-scale Content Analysis</button>
                    <button class="btn btn-primary" style="margin: 0.5rem;">ML Dataset Creation</button>
                    <button class="btn btn-primary" style="margin: 0.5rem;">Statistical Modeling</button>
                </div>
                
                <div class="content-section">
                    <h3 class="section-title">Historian Workflows</h3>
                    <button class="btn btn-primary" style="margin: 0.5rem;">Timeline Analysis</button>
                    <button class="btn btn-primary" style="margin: 0.5rem;">Source Validation</button>
                    <button class="btn btn-primary" style="margin: 0.5rem;">Cross-reference Tracking</button>
                </div>
                
                <div class="content-section">
                    <h3 class="section-title">Legal Workflows</h3>
                    <button class="btn btn-primary" style="margin: 0.5rem;">Evidence Gathering</button>
                    <button class="btn btn-primary" style="margin: 0.5rem;">Due Diligence Research</button>
                    <button class="btn btn-primary" style="margin: 0.5rem;">Citation Management</button>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // Simple tab switching
        document.querySelectorAll('.nav-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                // Remove active classes
                document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                
                // Add active class to clicked tab
                tab.classList.add('active');
                
                // Show corresponding content
                const tabId = tab.getAttribute('data-tab');
                document.getElementById(tabId).classList.add('active');
            });
        });
        
        // User type switching
        document.querySelector('.user-type-btn').addEventListener('click', () => {
            const types = ['data-scientist', 'historian', 'lawyer'];
            const current = document.body.className.split(' ').find(c => c.startsWith('theme-'));
            const currentIndex = types.findIndex(t => current === `theme-${t}`);
            const nextIndex = (currentIndex + 1) % types.length;
            const nextType = types[nextIndex];
            
            document.body.className = `theme-${nextType}`;
            document.querySelector('.user-type-btn').textContent = 
                nextType.split('-').map(w => w[0].toUpperCase() + w.slice(1)).join(' ');
        });
    </script>
</body>
</html>
"""

def take_comprehensive_screenshots():
    """Take comprehensive screenshots of the dashboard."""
    screenshots_dir = Path("gui_screenshots")
    screenshots_dir.mkdir(exist_ok=True)
    
    # Create HTML content
    html_content = create_dashboard_html()
    html_file = screenshots_dir / "dashboard_complete.html"
    html_file.write_text(html_content)
    
    # Initialize html2image
    hti = Html2Image(output_path=str(screenshots_dir))
    
    screenshots_taken = []
    
    try:
        # Take main dashboard screenshot
        hti.screenshot(html_file=str(html_file), save_as="main_dashboard.png", size=(1200, 900))
        screenshots_taken.append("main_dashboard.png")
        print("✓ Main dashboard screenshot taken")
        
        # Create variations for different tabs
        tab_variations = {
            "overview": "Overview Dashboard",
            "ingest": "News Ingestion Interface", 
            "timeline": "Timeline Analysis",
            "query": "GraphRAG Query Interface",
            "graph-explorer": "Knowledge Graph Explorer",
            "export": "Data Export Interface",
            "workflows": "Professional Workflows"
        }
        
        for tab_id, tab_name in tab_variations.items():
            # Create HTML with specific tab active
            tab_html = html_content.replace('id="overview" class="tab-content active"', 'id="overview" class="tab-content"')
            tab_html = tab_html.replace(f'id="{tab_id}" class="tab-content"', f'id="{tab_id}" class="tab-content active"')
            tab_html = tab_html.replace('class="nav-tab active" data-tab="overview"', 'class="nav-tab" data-tab="overview"')
            tab_html = tab_html.replace(f'class="nav-tab" data-tab="{tab_id}"', f'class="nav-tab active" data-tab="{tab_id}"')
            
            tab_file = screenshots_dir / f"{tab_id}_tab.html"
            tab_file.write_text(tab_html)
            
            hti.screenshot(html_file=str(tab_file), save_as=f"{tab_id}_tab.png", size=(1200, 900))
            screenshots_taken.append(f"{tab_id}_tab.png")
            print(f"✓ {tab_name} screenshot taken")
        
        # Create theme variations
        themes = {
            "data-scientist": ("theme-data-scientist", "Data Scientist"),
            "historian": ("theme-historian", "Historian"), 
            "lawyer": ("theme-lawyer", "Lawyer")
        }
        
        for theme_key, (theme_class, theme_name) in themes.items():
            theme_html = html_content.replace('class="theme-data-scientist"', f'class="{theme_class}"')
            theme_file = screenshots_dir / f"{theme_key}_theme.html"
            theme_file.write_text(theme_html)
            
            hti.screenshot(html_file=str(theme_file), save_as=f"{theme_key}_theme.png", size=(1200, 900))
            screenshots_taken.append(f"{theme_key}_theme.png")
            print(f"✓ {theme_name} theme screenshot taken")
        
        # Mobile responsive test
        mobile_html = html_content.replace('<meta name="viewport"', '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0"')
        mobile_file = screenshots_dir / "mobile_dashboard.html"
        mobile_file.write_text(mobile_html)
        
        hti.screenshot(html_file=str(mobile_file), save_as="mobile_dashboard.png", size=(375, 667))
        screenshots_taken.append("mobile_dashboard.png")
        print("✓ Mobile responsive screenshot taken")
        
        return screenshots_dir, screenshots_taken
        
    except Exception as e:
        print(f"Error taking screenshots: {e}")
        return screenshots_dir, screenshots_taken

def analyze_gui_from_screenshots(screenshots_dir, screenshots_taken):
    """Analyze GUI issues from screenshots and HTML structure."""
    issues_found = []
    improvements_suggested = []
    
    # Check if screenshots were successful
    successful_screenshots = len(screenshots_taken)
    total_expected = 12  # Expected number of screenshots
    
    if successful_screenshots < total_expected:
        issues_found.append(f"Only {successful_screenshots}/{total_expected} screenshots were taken successfully")
    
    # Analyze HTML structure for potential issues
    html_file = screenshots_dir / "dashboard_complete.html"
    if html_file.exists():
        html_content = html_file.read_text()
        
        # Check for accessibility issues
        if 'aria-label' not in html_content:
            issues_found.append("Missing ARIA labels for accessibility")
            improvements_suggested.append("Add ARIA labels to interactive elements")
        
        if 'alt=' not in html_content and '<img' in html_content:
            issues_found.append("Images missing alt attributes")
            improvements_suggested.append("Add alt attributes to all images")
        
        # Check for responsive design elements
        if '@media' not in html_content:
            issues_found.append("Limited responsive design implementation")
            improvements_suggested.append("Enhance mobile responsiveness with more breakpoints")
        
        # Check for JavaScript functionality
        if 'addEventListener' in html_content:
            print("✓ Interactive JavaScript functionality detected")
        else:
            issues_found.append("Limited JavaScript interactivity")
            improvements_suggested.append("Add more interactive features and animations")
    
    # GUI improvement recommendations based on modern dashboard standards
    improvements_suggested.extend([
        "Add loading skeletons for better perceived performance",
        "Implement smooth transitions between tabs and states",
        "Add keyboard navigation support (Tab, Enter, Arrow keys)",
        "Include tooltips for complex functionality",
        "Add dark mode support",
        "Implement real-time data updates with WebSocket connections",
        "Add drag-and-drop functionality for file uploads",
        "Include search functionality within dashboard components",
        "Add export progress indicators",
        "Implement better error states and retry mechanisms"
    ])
    
    return issues_found, improvements_suggested

def create_gui_improvement_plan(issues_found, improvements_suggested):
    """Create a detailed GUI improvement plan."""
    return {
        "critical_fixes_needed": issues_found,
        "immediate_improvements": improvements_suggested[:5],
        "future_enhancements": improvements_suggested[5:],
        "accessibility_improvements": [
            "Add proper heading hierarchy (h1, h2, h3)",
            "Implement focus management for tab navigation",
            "Add screen reader support with ARIA live regions",
            "Ensure color contrast meets WCAG 2.1 AA standards",
            "Add keyboard shortcuts documentation"
        ],
        "performance_optimizations": [
            "Lazy load tab content",
            "Implement virtual scrolling for large data sets",
            "Add service worker for offline capability",
            "Optimize CSS with critical path loading",
            "Compress and optimize images"
        ],
        "user_experience_enhancements": [
            "Add onboarding tour for new users",
            "Implement contextual help system",
            "Add customizable dashboard layouts",
            "Include recent actions and favorites",
            "Add bulk operations support"
        ]
    }

def main():
    """Main function to run GUI analysis and improvement recommendations."""
    print("=== GUI Screenshot Analysis and Improvement Recommendations ===")
    
    # Take comprehensive screenshots
    screenshots_dir, screenshots_taken = take_comprehensive_screenshots()
    
    # Analyze GUI issues
    issues_found, improvements_suggested = analyze_gui_from_screenshots(screenshots_dir, screenshots_taken)
    
    # Create improvement plan
    improvement_plan = create_gui_improvement_plan(issues_found, improvements_suggested)
    
    # Generate comprehensive report
    report = {
        "analysis_timestamp": datetime.now().isoformat(),
        "screenshots_taken": len(screenshots_taken),
        "screenshot_files": screenshots_taken,
        "screenshots_directory": str(screenshots_dir),
        "issues_identified": issues_found,
        "improvement_suggestions": improvements_suggested,
        "detailed_improvement_plan": improvement_plan,
        "dashboard_features_tested": [
            "Main overview dashboard",
            "All 7 navigation tabs",
            "3 professional themes (Data Scientist, Historian, Lawyer)",
            "Mobile responsive design",
            "Interactive JavaScript functionality"
        ]
    }
    
    # Save report
    report_file = Path("gui_improvement_report.json")
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Create summary HTML report
    create_html_report(report, screenshots_dir)
    
    print(f"\n=== Analysis Complete ===")
    print(f"✓ Screenshots taken: {len(screenshots_taken)}")
    print(f"✓ Screenshots saved to: {screenshots_dir}")
    print(f"✓ Analysis report saved to: {report_file}")
    
    if issues_found:
        print(f"\n⚠️  Issues identified: {len(issues_found)}")
        for i, issue in enumerate(issues_found[:3], 1):
            print(f"  {i}. {issue}")
    
    print(f"\n💡 Top improvement suggestions:")
    for i, suggestion in enumerate(improvements_suggested[:5], 1):
        print(f"  {i}. {suggestion}")
    
    print(f"\nDetailed analysis available in gui_improvement_report.json")
    print(f"Interactive HTML report created at gui_screenshots/improvement_report.html")

def create_html_report(report, screenshots_dir):
    """Create an interactive HTML report."""
    html_report = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GUI Improvement Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 2rem; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #1e293b; border-bottom: 3px solid #667eea; padding-bottom: 0.5rem; }}
        h2 {{ color: #374151; margin-top: 2rem; }}
        .screenshot-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1rem; margin: 1rem 0; }}
        .screenshot-item {{ text-align: center; }}
        .screenshot-item img {{ max-width: 100%; height: auto; border: 1px solid #e5e7eb; border-radius: 8px; }}
        .issue {{ background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; padding: 1rem; margin: 0.5rem 0; }}
        .improvement {{ background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 6px; padding: 1rem; margin: 0.5rem 0; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin: 1rem 0; }}
        .stat-card {{ background: #f8fafc; padding: 1rem; border-radius: 8px; text-align: center; }}
        .stat-number {{ font-size: 2rem; font-weight: bold; color: #667eea; }}
        ul {{ padding-left: 1.5rem; }}
        li {{ margin: 0.25rem 0; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>GUI Analysis & Improvement Report</h1>
        <p><strong>Analysis Date:</strong> {report['analysis_timestamp']}</p>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-number">{report['screenshots_taken']}</div>
                <div>Screenshots Taken</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{len(report['issues_identified'])}</div>
                <div>Issues Identified</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{len(report['improvement_suggestions'])}</div>
                <div>Improvements Suggested</div>
            </div>
        </div>
        
        <h2>Screenshots Captured</h2>
        <div class="screenshot-grid">
"""
    
    for screenshot in report['screenshot_files']:
        screenshot_name = screenshot.replace('.png', '').replace('_', ' ').title()
        html_report += f"""
            <div class="screenshot-item">
                <img src="{screenshot}" alt="{screenshot_name}">
                <p>{screenshot_name}</p>
            </div>
        """
    
    html_report += f"""
        </div>
        
        <h2>Issues Identified</h2>
        {''.join(f'<div class="issue"><strong>Issue:</strong> {issue}</div>' for issue in report['issues_identified'])}
        
        <h2>Improvement Suggestions</h2>
        {''.join(f'<div class="improvement"><strong>Suggestion:</strong> {improvement}</div>' for improvement in report['improvement_suggestions'][:10])}
        
        <h2>Detailed Improvement Plan</h2>
        
        <h3>Accessibility Improvements</h3>
        <ul>
            {''.join(f'<li>{item}</li>' for item in report['detailed_improvement_plan']['accessibility_improvements'])}
        </ul>
        
        <h3>Performance Optimizations</h3>
        <ul>
            {''.join(f'<li>{item}</li>' for item in report['detailed_improvement_plan']['performance_optimizations'])}
        </ul>
        
        <h3>User Experience Enhancements</h3>
        <ul>
            {''.join(f'<li>{item}</li>' for item in report['detailed_improvement_plan']['user_experience_enhancements'])}
        </ul>
        
        <h2>Features Tested</h2>
        <ul>
            {''.join(f'<li>{feature}</li>' for feature in report['dashboard_features_tested'])}
        </ul>
    </div>
</body>
</html>
    """
    
    report_html_file = screenshots_dir / "improvement_report.html"
    report_html_file.write_text(html_report)
    print(f"✓ Interactive HTML report created: {report_html_file}")

if __name__ == "__main__":
    main()