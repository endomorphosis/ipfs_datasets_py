#!/usr/bin/env python3
"""
Enhanced GitHub Actions Workflow Validator
Validates all workflow files against best practices.
Usage: python validate_workflows.py [--report-json output.json]
"""
import argparse, json, sys, yaml
from pathlib import Path

class WorkflowValidator:
    def __init__(self, workflows_dir=None):
        self.workflows_dir = workflows_dir or Path('.github/workflows')
        self.stats = {'total_files': 0, 'valid_files': 0, 'files_with_errors': 0, 'total_issues': 0}
    
    def validate_all(self):
        files = [f for f in self.workflows_dir.glob('*.yml') if not f.name.endswith(('.backup', '.disabled'))]
        self.stats['total_files'] = len(files)
        results = []
        for f in sorted(files):
            result = self.validate_file(f)
            results.append(result)
            if result['valid']: self.stats['valid_files'] += 1
            if [i for i in result['issues'] if i['severity'] == 'error']:
                self.stats['files_with_errors'] += 1
            self.stats['total_issues'] += len(result['issues'])
        return {'results': results, 'stats': self.stats}
    
    def validate_file(self, filepath):
        result = {'file': str(filepath.name), 'valid': True, 'issues': []}
        try:
            content = filepath.read_text()
            workflow = yaml.safe_load(content)
            if not workflow: 
                result['issues'].append({'severity': 'error', 'message': 'Empty file'})
                return result
            if not workflow.get('name'):
                result['issues'].append({'severity': 'error', 'message': 'Missing name'})
            if 'permissions' not in workflow:
                result['issues'].append({'severity': 'warning', 'message': 'Missing permissions'})
            if 'concurrency' not in workflow:
                result['issues'].append({'severity': 'info', 'message': 'No concurrency control'})
        except Exception as e:
            result['valid'] = False
            result['issues'].append({'severity': 'error', 'message': str(e)})
        return result
    
    def generate_report(self, results):
        lines = ["="*70, "Workflow Validation Report", "="*70, "", 
                 f"Total: {results['stats']['total_files']}", 
                 f"Valid: {results['stats']['valid_files']}", 
                 f"Errors: {results['stats']['files_with_errors']}", 
                 f"Issues: {results['stats']['total_issues']}", ""]
        for r in results['results']:
            if r['issues']:
                lines.append(f"📄 {r['file']}")
                for i in r['issues']:
                    lines.append(f"  {i['severity'].upper()}: {i['message']}")
                lines.append("")
        return "\n".join(lines)

validator = WorkflowValidator()
results = validator.validate_all()
print(validator.generate_report(results))
sys.exit(1 if results['stats']['files_with_errors'] > 0 else 0)
