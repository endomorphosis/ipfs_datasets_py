#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simple GUI Screenshot Testing for News Analysis Dashboard

Since the full dashboard requires many dependencies, this script will:
1. Use the existing HTML templates to create static screenshots
2. Analyze the GUI for common issues
3. Generate improvement recommendations
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from html2image import Html2Image
import webbrowser

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

class SimpleGUIScreenshotTester:
    """Simple GUI testing using existing HTML templates."""
    
    def __init__(self):
        self.screenshots_dir = Path("gui_analysis_screenshots")
        self.screenshots_dir.mkdir(exist_ok=True)
        
        self.hti = Html2Image(output_path=str(self.screenshots_dir))
        
        self.analysis_results = {
            "timestamp": datetime.now().isoformat(),
            "screenshots": [],
            "gui_issues": [],
            "improvements": [],
            "template_analysis": {}
        }
        
    def find_html_templates(self):
        """Find all HTML templates in the project."""
        html_files = []
        
        # Look for templates in the project
        template_dirs = [
            "ipfs_datasets_py/templates",
            "gui_screenshots",
            "final_gui_screenshots",
            "dashboard_screenshots"
        ]
        
        for template_dir in template_dirs:
            template_path = Path(template_dir)
            if template_path.exists():
                html_files.extend(list(template_path.glob("*.html")))
        
        # Also look for any HTML files in the root
        html_files.extend(list(Path(".").glob("*.html")))
        
        return html_files
    
    def analyze_html_template(self, html_file: Path):
        """Analyze an HTML template for common GUI issues."""
        issues = []
        
        try:
            with open(html_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for missing alt attributes in img tags
            if '<img' in content:
                import re
                img_tags = re.findall(r'<img[^>]*>', content)
                for img_tag in img_tags:
                    if 'alt=' not in img_tag:
                        issues.append({
                            "type": "accessibility",
                            "severity": "high",
                            "element": "img",
                            "issue": "Image missing alt attribute",
                            "location": img_tag[:100] + "..." if len(img_tag) > 100 else img_tag
                        })
            
            # Check for missing labels on form inputs
            if '<input' in content:
                import re
                input_tags = re.findall(r'<input[^>]*>', content)
                for input_tag in input_tags:
                    if 'id=' in input_tag:
                        input_id = re.search(r'id=["\']([^"\']*)["\']', input_tag)
                        if input_id:
                            label_pattern = f'<label[^>]*for=["\']?{input_id.group(1)}["\']?[^>]*>'
                            if not re.search(label_pattern, content):
                                issues.append({
                                    "type": "accessibility",
                                    "severity": "medium",
                                    "element": "input",
                                    "issue": "Input without associated label",
                                    "location": input_id.group(1)
                                })
            
            # Check for buttons without accessible text
            if '<button' in content:
                import re
                button_tags = re.findall(r'<button[^>]*>.*?</button>', content, re.DOTALL)
                for button_tag in button_tags:
                    if 'aria-label=' not in button_tag and '>' in button_tag and '<' in button_tag:
                        button_content = re.search(r'>(.*?)</button>', button_tag, re.DOTALL)
                        if button_content and not button_content.group(1).strip():
                            issues.append({
                                "type": "accessibility",
                                "severity": "medium",
                                "element": "button",
                                "issue": "Button without accessible text or aria-label",
                                "location": button_tag[:50] + "..."
                            })
            
            # Check for missing viewport meta tag
            if '<meta name="viewport"' not in content:
                issues.append({
                    "type": "mobile_responsiveness",
                    "severity": "high",
                    "element": "meta",
                    "issue": "Missing viewport meta tag for mobile responsiveness",
                    "location": "head section"
                })
            
            # Check for inline styles (should use CSS classes)
            if 'style=' in content:
                import re
                inline_styles = re.findall(r'style=["\'][^"\']*["\']', content)
                if len(inline_styles) > 10:  # More than 10 inline styles is problematic
                    issues.append({
                        "type": "maintainability",
                        "severity": "low",
                        "element": "style",
                        "issue": f"Excessive inline styles found ({len(inline_styles)} instances)",
                        "location": "throughout template"
                    })
            
            # Check for proper heading hierarchy
            headings = []
            for i in range(1, 7):
                import re
                h_tags = re.findall(f'<h{i}[^>]*>.*?</h{i}>', content, re.DOTALL)
                for tag in h_tags:
                    headings.append((i, tag))
            
            if headings:
                headings.sort(key=lambda x: content.find(x[1]))
                last_level = 0
                for level, tag in headings:
                    if level > last_level + 1:
                        issues.append({
                            "type": "accessibility",
                            "severity": "low",
                            "element": f"h{level}",
                            "issue": f"Heading level skipped from h{last_level} to h{level}",
                            "location": tag[:50] + "..."
                        })
                    last_level = level
            
        except Exception as e:
            print(f"Error analyzing {html_file}: {e}")
        
        return issues
    
    def capture_template_screenshot(self, html_file: Path):
        """Capture screenshot of an HTML template."""
        try:
            print(f"Capturing screenshot of: {html_file.name}")
            
            # Create screenshot filename
            screenshot_name = f"{html_file.stem}_screenshot"
            
            # Use html2image to capture screenshot
            self.hti.screenshot(
                url=str(html_file.absolute()),
                save_as=f"{screenshot_name}.png",
                size=(1200, 800)
            )
            
            screenshot_path = self.screenshots_dir / f"{screenshot_name}.png"
            
            # Record screenshot info
            self.analysis_results["screenshots"].append({
                "filename": f"{screenshot_name}.png", 
                "source_template": str(html_file),
                "description": f"Screenshot of {html_file.stem}",
                "timestamp": datetime.now().isoformat(),
                "path": str(screenshot_path)
            })
            
            print(f"✓ Screenshot saved: {screenshot_path}")
            return screenshot_path
            
        except Exception as e:
            print(f"✗ Failed to capture screenshot of {html_file}: {e}")
            return None
    
    def create_enhanced_template(self, original_template: Path, improvements: List[Dict]):
        """Create an enhanced version of a template with improvements applied."""
        try:
            with open(original_template, 'r', encoding='utf-8') as f:
                content = f.read()
            
            enhanced_content = content
            
            # Apply accessibility improvements
            for improvement in improvements:
                if improvement["type"] == "accessibility":
                    if "missing alt" in improvement["issue"].lower():
                        # Add alt attributes to images
                        import re
                        enhanced_content = re.sub(
                            r'(<img[^>]*?)(/?>)',
                            r'\1 alt="Descriptive image text"\2',
                            enhanced_content
                        )
                    
                    elif "missing viewport" in improvement["issue"].lower():
                        # Add viewport meta tag
                        if '<head>' in enhanced_content:
                            enhanced_content = enhanced_content.replace(
                                '<head>',
                                '<head>\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">'
                            )
                    
                    elif "button without" in improvement["issue"].lower():
                        # Add aria-labels to buttons without text
                        import re
                        enhanced_content = re.sub(
                            r'(<button[^>]*?)(>[\s]*</button>)',
                            r'\1 aria-label="Button action">\2',
                            enhanced_content
                        )
            
            # Save enhanced template
            enhanced_file = self.screenshots_dir / f"enhanced_{original_template.name}"
            with open(enhanced_file, 'w', encoding='utf-8') as f:
                f.write(enhanced_content)
            
            return enhanced_file
            
        except Exception as e:
            print(f"Error creating enhanced template: {e}")
            return None
    
    def run_comprehensive_analysis(self):
        """Run comprehensive GUI analysis on available templates."""
        print("Starting simple GUI screenshot and analysis...")
        
        # Find HTML templates
        html_files = self.find_html_templates()
        print(f"Found {len(html_files)} HTML templates to analyze")
        
        if not html_files:
            print("No HTML templates found. Creating a sample dashboard template...")
            self.create_sample_dashboard_template()
            html_files = self.find_html_templates()
        
        all_issues = []
        
        # Process each template
        for html_file in html_files[:5]:  # Limit to first 5 templates
            print(f"\nProcessing: {html_file}")
            
            # Capture screenshot
            screenshot_path = self.capture_template_screenshot(html_file)
            
            # Analyze template
            template_issues = self.analyze_html_template(html_file)
            all_issues.extend(template_issues)
            
            # Record template analysis
            self.analysis_results["template_analysis"][str(html_file)] = {
                "issues_found": len(template_issues),
                "issues": template_issues,
                "screenshot": str(screenshot_path) if screenshot_path else None
            }
            
            # Create enhanced version if issues found
            if template_issues:
                enhanced_template = self.create_enhanced_template(html_file, template_issues)
                if enhanced_template:
                    enhanced_screenshot = self.capture_template_screenshot(enhanced_template)
                    print(f"✓ Enhanced template created: {enhanced_template}")
        
        self.analysis_results["gui_issues"] = all_issues
        
        # Generate recommendations
        self.generate_improvement_recommendations()
        
        # Save results
        self.save_analysis_results()
        
        print(f"\n✓ GUI analysis completed!")
        print(f"Screenshots saved in: {self.screenshots_dir}")
        print(f"Found {len(all_issues)} GUI issues across {len(html_files)} templates")
        
        return self.analysis_results
    
    def create_sample_dashboard_template(self):
        """Create a sample dashboard template for testing."""
        sample_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>News Analysis Dashboard - Sample</title>
    <style>
        body { 
            font-family: Arial, sans-serif; 
            margin: 0; 
            padding: 20px; 
            background: #f5f5f5;
        }
        .header { 
            background: #2563eb; 
            color: white; 
            padding: 20px; 
            border-radius: 8px; 
            margin-bottom: 20px;
        }
        .nav-tabs { 
            display: flex; 
            gap: 10px; 
            margin-bottom: 20px;
        }
        .tab { 
            padding: 10px 20px; 
            background: white; 
            border: 1px solid #ddd; 
            border-radius: 4px; 
            cursor: pointer;
        }
        .tab.active { 
            background: #2563eb; 
            color: white;
        }
        .content { 
            background: white; 
            padding: 20px; 
            border-radius: 8px; 
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .stats-card { 
            background: #f8fafc; 
            padding: 15px; 
            border-radius: 6px; 
            margin: 10px 0;
        }
        .form-group { 
            margin: 15px 0;
        }
        label { 
            display: block; 
            margin-bottom: 5px; 
            font-weight: bold;
        }
        input, textarea, select { 
            width: 100%; 
            padding: 8px; 
            border: 1px solid #ddd; 
            border-radius: 4px;
        }
        button { 
            background: #2563eb; 
            color: white; 
            padding: 10px 20px; 
            border: none; 
            border-radius: 4px; 
            cursor: pointer;
        }
        button:hover { 
            background: #1d4ed8;
        }
        @media (max-width: 768px) {
            .nav-tabs { 
                flex-direction: column;
            }
            .tab { 
                text-align: center;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>News Analysis Dashboard</h1>
        <p>Professional news analysis for data scientists, historians, and lawyers</p>
    </div>

    <nav class="nav-tabs">
        <div class="tab active" onclick="showTab('overview')">Overview</div>
        <div class="tab" onclick="showTab('ingest')">Ingest</div>
        <div class="tab" onclick="showTab('timeline')">Timeline</div>
        <div class="tab" onclick="showTab('query')">Query</div>
        <div class="tab" onclick="showTab('graph')">Graph Explorer</div>
        <div class="tab" onclick="showTab('export')">Export</div>
    </nav>

    <div id="overview" class="content">
        <h2>Dashboard Overview</h2>
        
        <div class="stats-card">
            <h3>Processing Statistics</h3>
            <p>Articles Processed: <strong>1,247</strong></p>
            <p>Entities Extracted: <strong>3,891</strong></p>
            <p>Active Workflows: <strong>5</strong></p>
        </div>

        <div class="stats-card">
            <h3>Recent Activity</h3>
            <ul>
                <li>Processed 15 Reuters articles on economic policy</li>
                <li>Generated timeline analysis for election coverage</li>
                <li>Extracted 127 entities from government documents</li>
            </ul>
        </div>

        <img src="placeholder-chart.png" width="400" height="200">
    </div>

    <div id="ingest" class="content" style="display: none;">
        <h2>Article Ingestion</h2>
        
        <form>
            <div class="form-group">
                <label for="article-url">Article URL</label>
                <input type="url" id="article-url" placeholder="https://example.com/news-article">
            </div>
            
            <div class="form-group">
                <label for="source-type">Source Type</label>
                <select id="source-type">
                    <option>News Website</option>
                    <option>Government Document</option>
                    <option>Academic Paper</option>
                </select>
            </div>
            
            <div class="form-group">
                <label for="analysis-type">Analysis Type</label>
                <select>
                    <option>Full Analysis</option>
                    <option>Entity Extraction Only</option>
                    <option>Timeline Analysis</option>
                </select>
            </div>
            
            <button type="submit">Process Article</button>
        </form>
    </div>

    <div id="timeline" class="content" style="display: none;">
        <h2>Timeline Analysis</h2>
        
        <div class="form-group">
            <label for="timeline-query">Topic or Query</label>
            <input type="text" id="timeline-query" placeholder="Enter topic to analyze over time">
        </div>
        
        <div class="form-group">
            <label for="date-range">Date Range</label>
            <input type="date" style="width: 48%; display: inline-block;">
            <input type="date" style="width: 48%; display: inline-block; float: right;">
        </div>
        
        <button>Generate Timeline</button>
        
        <div class="stats-card" style="margin-top: 20px;">
            <h3>Timeline Preview</h3>
            <p>Sample timeline visualization would appear here</p>
        </div>
    </div>

    <script>
        function showTab(tabName) {
            // Hide all content divs
            const contents = document.querySelectorAll('.content');
            contents.forEach(content => content.style.display = 'none');
            
            // Remove active class from all tabs
            const tabs = document.querySelectorAll('.tab');
            tabs.forEach(tab => tab.classList.remove('active'));
            
            // Show selected content
            document.getElementById(tabName).style.display = 'block';
            
            // Add active class to clicked tab
            event.target.classList.add('active');
        }
    </script>
</body>
</html>"""
        
        sample_file = Path("sample_news_dashboard.html")
        with open(sample_file, 'w', encoding='utf-8') as f:
            f.write(sample_html)
        
        print(f"✓ Created sample dashboard template: {sample_file}")
    
    def generate_improvement_recommendations(self):
        """Generate improvement recommendations based on analysis."""
        issues_by_type = {}
        for issue in self.analysis_results["gui_issues"]:
            issue_type = issue["type"]
            if issue_type not in issues_by_type:
                issues_by_type[issue_type] = []
            issues_by_type[issue_type].append(issue)
        
        recommendations = []
        
        # Accessibility improvements
        if "accessibility" in issues_by_type:
            accessibility_issues = issues_by_type["accessibility"]
            high_priority = [i for i in accessibility_issues if i["severity"] == "high"]
            
            recommendations.append({
                "priority": "high",
                "category": "Accessibility",
                "recommendation": "Improve accessibility compliance",
                "details": [
                    "Add alt attributes to all images",
                    "Associate labels with form inputs",
                    "Ensure proper heading hierarchy",
                    "Add ARIA labels to interactive elements"
                ],
                "affected_elements": len(accessibility_issues),
                "implementation": "Update HTML templates with proper accessibility attributes"
            })
        
        # Mobile responsiveness
        if "mobile_responsiveness" in issues_by_type:
            mobile_issues = issues_by_type["mobile_responsiveness"]
            recommendations.append({
                "priority": "high",
                "category": "Mobile Responsiveness",
                "recommendation": "Improve mobile device compatibility",
                "details": [
                    "Add viewport meta tag to all pages",
                    "Implement responsive CSS media queries",
                    "Ensure touch targets are at least 44x44px",
                    "Test on various screen sizes"
                ],
                "affected_elements": len(mobile_issues),
                "implementation": "Add responsive design patterns and mobile-first approach"
            })
        
        # Maintainability improvements
        if "maintainability" in issues_by_type:
            maintainability_issues = issues_by_type["maintainability"]
            recommendations.append({
                "priority": "medium",
                "category": "Code Maintainability", 
                "recommendation": "Improve code organization and maintainability",
                "details": [
                    "Move inline styles to external CSS files",
                    "Organize CSS with proper naming conventions",
                    "Use consistent design patterns",
                    "Minimize code duplication"
                ],
                "affected_elements": len(maintainability_issues),
                "implementation": "Refactor templates to use external stylesheets and design system"
            })
        
        # Performance improvements
        recommendations.append({
            "priority": "medium",
            "category": "Performance",
            "recommendation": "Optimize dashboard performance",
            "details": [
                "Implement lazy loading for large datasets",
                "Use virtual scrolling for long lists",
                "Optimize image loading and sizing",
                "Minimize JavaScript bundle size",
                "Add loading states and progress indicators"
            ],
            "affected_elements": 0,
            "implementation": "Add performance optimization techniques and monitoring"
        })
        
        self.analysis_results["improvements"] = recommendations
    
    def save_analysis_results(self):
        """Save analysis results and create summary."""
        # Save JSON results
        results_file = "simple_gui_analysis_results.json"
        with open(results_file, 'w') as f:
            json.dump(self.analysis_results, f, indent=2)
        
        # Create markdown summary
        summary_file = "simple_gui_analysis_summary.md"
        with open(summary_file, 'w') as f:
            f.write("# Simple GUI Analysis Summary\n\n")
            f.write(f"**Analysis Date:** {self.analysis_results['timestamp']}\n")
            f.write(f"**Templates Analyzed:** {len(self.analysis_results['template_analysis'])}\n")
            f.write(f"**Screenshots Captured:** {len(self.analysis_results['screenshots'])}\n")
            f.write(f"**Total Issues Found:** {len(self.analysis_results['gui_issues'])}\n\n")
            
            # Screenshots section
            f.write("## Screenshots\n\n")
            for screenshot in self.analysis_results['screenshots']:
                f.write(f"![{screenshot['description']}]({screenshot['path']})\n")
                f.write(f"*{screenshot['description']}*\n\n")
            
            # Issues by severity
            issues_by_severity = {"high": [], "medium": [], "low": []}
            for issue in self.analysis_results['gui_issues']:
                severity = issue.get('severity', 'low')
                if severity in issues_by_severity:
                    issues_by_severity[severity].append(issue)
            
            f.write("## Issues Found\n\n")
            for severity in ['high', 'medium', 'low']:
                if issues_by_severity[severity]:
                    f.write(f"### {severity.title()} Priority ({len(issues_by_severity[severity])} issues)\n\n")
                    for issue in issues_by_severity[severity]:
                        f.write(f"- **{issue['element']}**: {issue['issue']}\n")
                        f.write(f"  - *Location: {issue['location']}*\n\n")
            
            # Recommendations
            f.write("## Improvement Recommendations\n\n")
            for rec in self.analysis_results['improvements']:
                f.write(f"### {rec['category']} ({rec['priority']} priority)\n\n")
                f.write(f"{rec['recommendation']}\n\n")
                if 'details' in rec:
                    f.write("**Specific improvements:**\n")
                    for detail in rec['details']:
                        f.write(f"- {detail}\n")
                    f.write("\n")
                f.write(f"**Implementation:** {rec['implementation']}\n\n")

if __name__ == "__main__":
    tester = SimpleGUIScreenshotTester()
    results = tester.run_comprehensive_analysis()
    
    print("\n" + "="*60)
    print("SIMPLE GUI ANALYSIS COMPLETED")
    print("="*60)
    print(f"Templates analyzed: {len(results['template_analysis'])}")
    print(f"Screenshots captured: {len(results['screenshots'])}")
    print(f"Issues found: {len(results['gui_issues'])}")
    print(f"Recommendations: {len(results['improvements'])}")
    print("="*60)