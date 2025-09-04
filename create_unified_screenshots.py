#!/usr/bin/env python3
"""
Generate screenshots of the unified investigation dashboard
"""

import os
import sys
from pathlib import Path

try:
    from html2image import Html2Image
except ImportError:
    print("html2image not available, trying alternative...")
    try:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "html2image"], check=True)
        from html2image import Html2Image
    except Exception as e:
        print(f"Could not install html2image: {e}")
        sys.exit(1)

def create_unified_dashboard_screenshots():
    """Create screenshots of the unified investigation dashboard."""
    
    # Create screenshots directory
    screenshots_dir = Path("/tmp/unified_dashboard_screenshots")
    screenshots_dir.mkdir(exist_ok=True)
    
    try:
        # Initialize HTML2Image
        hti = Html2Image(
            output_path=str(screenshots_dir),
            size=(1200, 800),
            temp_path="/tmp"
        )
        
        # Screenshot 1: Full Dashboard
        html_file = Path("/home/runner/work/ipfs_datasets_py/ipfs_datasets_py/unified_dashboard_screenshot.html")
        
        if html_file.exists():
            hti.screenshot(
                html_file=str(html_file),
                save_as="unified_dashboard_main.png"
            )
            print(f"✅ Created main dashboard screenshot: {screenshots_dir}/unified_dashboard_main.png")
        else:
            print(f"❌ HTML file not found: {html_file}")
        
        # Screenshot 2: Mobile View
        hti.size = (375, 812)  # iPhone size
        if html_file.exists():
            hti.screenshot(
                html_file=str(html_file),
                save_as="unified_dashboard_mobile.png"
            )
            print(f"✅ Created mobile dashboard screenshot: {screenshots_dir}/unified_dashboard_mobile.png")
        
        # Create a comparison HTML showing key improvements
        comparison_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Unified Dashboard - Key Improvements</title>
            <style>
                body { 
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                    margin: 2rem;
                    line-height: 1.6;
                    background: #f8fafc;
                }
                .improvement-card {
                    background: white;
                    border-radius: 12px;
                    padding: 2rem;
                    margin: 1rem 0;
                    border-left: 4px solid #1e40af;
                    box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
                }
                .before-after {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 2rem;
                    margin: 2rem 0;
                }
                .before, .after {
                    padding: 1rem;
                    border-radius: 8px;
                }
                .before {
                    background: #fef2f2;
                    border-left: 4px solid #dc2626;
                }
                .after {
                    background: #f0fdf4;
                    border-left: 4px solid #059669;
                }
                .title {
                    font-size: 2rem;
                    font-weight: 700;
                    color: #1e40af;
                    text-align: center;
                    margin-bottom: 2rem;
                }
                .key-feature {
                    background: #eff6ff;
                    padding: 1rem;
                    border-radius: 8px;
                    margin: 1rem 0;
                    border-left: 4px solid #3b82f6;
                }
                .entity-demo {
                    display: flex;
                    gap: 0.5rem;
                    flex-wrap: wrap;
                    margin: 1rem 0;
                }
                .entity-badge {
                    padding: 0.25rem 0.5rem;
                    border-radius: 1rem;
                    color: white;
                    font-size: 0.75rem;
                    font-weight: 600;
                }
                .entity-person { background: #8b5cf6; }
                .entity-org { background: #06b6d4; }
                .entity-location { background: #10b981; }
                .entity-event { background: #f59e0b; }
            </style>
        </head>
        <body>
            <div class="title">🔍 Unified Investigation Dashboard</div>
            <div class="title" style="font-size: 1.2rem; margin-top: -1rem;">Entity-Centric Analysis Platform</div>
            
            <div class="improvement-card">
                <h2>🎯 Key Improvements Implemented</h2>
                
                <div class="before-after">
                    <div class="before">
                        <h3>❌ Before: Role-Specific Design</h3>
                        <ul>
                            <li>Separate buttons for Data Scientist, Historian, Lawyer</li>
                            <li>Role-based themes and workflows</li>
                            <li>Fragmented user experience</li>
                            <li>Limited cross-disciplinary functionality</li>
                        </ul>
                    </div>
                    <div class="after">
                        <h3>✅ After: Unified Investigation Hub</h3>
                        <ul>
                            <li>Single entity-centric interface</li>
                            <li>Universal investigation workflows</li>
                            <li>Comprehensive analysis tools</li>
                            <li>Seamless cross-domain research</li>
                        </ul>
                    </div>
                </div>
                
                <div class="key-feature">
                    <h3>🎯 Entity-Centric Investigation</h3>
                    <p>Focus on entities and their relationships rather than user roles:</p>
                    <div class="entity-demo">
                        <span class="entity-badge entity-person">People</span>
                        <span class="entity-badge entity-org">Organizations</span>
                        <span class="entity-badge entity-location">Locations</span>
                        <span class="entity-badge entity-event">Events</span>
                    </div>
                </div>
                
                <div class="key-feature">
                    <h3>🕸️ Comprehensive Analysis Tools</h3>
                    <ul>
                        <li><strong>Entity Explorer</strong> - Deep dive into individual entities</li>
                        <li><strong>Relationship Mapping</strong> - Visualize connections and patterns</li>
                        <li><strong>Timeline Analysis</strong> - Track events across time</li>
                        <li><strong>Pattern Detection</strong> - Identify recurring themes</li>
                        <li><strong>Conflict Analysis</strong> - Find contradicting information</li>
                        <li><strong>Data Provenance</strong> - Track information lineage</li>
                    </ul>
                </div>
                
                <div class="key-feature">
                    <h3>📊 Universal Research Platform</h3>
                    <p>Designed for comprehensive investigation across disciplines:</p>
                    <ul>
                        <li>Data scientists can perform statistical analysis on entity networks</li>
                        <li>Historians can trace information evolution and source verification</li>
                        <li>Lawyers can maintain evidence chains and conflict detection</li>
                        <li>All users benefit from unified, powerful analysis capabilities</li>
                    </ul>
                </div>
                
                <div class="key-feature">
                    <h3>🚀 Enhanced User Experience</h3>
                    <ul>
                        <li>Streamlined navigation with investigation-focused sections</li>
                        <li>Real-time processing status and activity monitoring</li>
                        <li>Advanced search and filtering across entire corpus</li>
                        <li>Professional export formats for all analysis types</li>
                        <li>Responsive design optimized for research workflows</li>
                    </ul>
                </div>
            </div>
        </body>
        </html>
        """
        
        comparison_file = screenshots_dir / "improvements_summary.html"
        with open(comparison_file, "w") as f:
            f.write(comparison_html)
        
        # Screenshot the comparison
        hti.size = (1200, 1000)
        hti.screenshot(
            html_file=str(comparison_file),
            save_as="unified_dashboard_improvements.png"
        )
        print(f"✅ Created improvements summary: {screenshots_dir}/unified_dashboard_improvements.png")
        
        print(f"\n🎉 All screenshots created successfully in: {screenshots_dir}")
        print(f"📸 Files created:")
        for png_file in screenshots_dir.glob("*.png"):
            print(f"   - {png_file.name}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating screenshots: {e}")
        return False

if __name__ == "__main__":
    create_unified_dashboard_screenshots()