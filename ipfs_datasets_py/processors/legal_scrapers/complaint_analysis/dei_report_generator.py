"""
DEI Report Generator

Generate findings reports and summaries from DEI policy analysis.
Based on HACC's report_generator.py for creating executive summaries
and detailed technical reports of DEI compliance issues.

This module produces:
- One-page executive summaries for stakeholders
- Detailed technical reports with methodology
- CSV exports for further analysis
- Risk-prioritized findings lists
"""

from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
import json
import csv


class DEIReportGenerator:
    """
    Generate comprehensive reports from DEI policy analysis.
    
    Based on HACC's report generation methodology, this class creates
    both executive summaries and detailed technical reports suitable for
    legal review, compliance assessment, and stakeholder communication.
    
    Example:
        >>> generator = DEIReportGenerator()
        >>> generator.add_document_analysis(risk_result, provisions, metadata)
        >>> report = generator.generate_executive_summary()
        >>> generator.save_reports('output_dir/')
    """
    
    def __init__(self, project_name: str = "DEI Policy Analysis"):
        """
        Initialize report generator.
        
        Args:
            project_name: Name of the analysis project
        """
        self.project_name = project_name
        self.documents = []
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    def add_document_analysis(self, 
                            risk_result: Dict[str, Any],
                            provisions: List[Dict[str, Any]],
                            metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Add a document analysis to the report.
        
        Args:
            risk_result: Risk analysis result from DEIRiskScorer
            provisions: Provisions extracted by DEIProvisionExtractor
            metadata: Additional document metadata (source, date, type, etc.)
        """
        doc_entry = {
            'risk': risk_result,
            'provisions': provisions,
            'metadata': metadata or {},
            'added_at': datetime.now().isoformat()
        }
        self.documents.append(doc_entry)
    
    def generate_executive_summary(self) -> str:
        """
        Generate one-page executive summary.
        
        Returns:
            Formatted executive summary text
        """
        high_risk = self._get_high_risk_documents()
        medium_risk = self._get_medium_risk_documents()
        low_risk = self._get_low_risk_documents()
        
        summary = f"""
{'=' * 80}
{self.project_name} - EXECUTIVE SUMMARY
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'=' * 80}

SCOPE
-----
Analysis of {len(self.documents)} document(s) for DEI (Diversity, Equity, 
Inclusion) policy language that may create legal or compliance risks.

Search methodology:
- Direct DEI terms (diversity, equity, inclusion, etc.)
- Proxy terms/euphemisms (cultural competence, lived experience, etc.)
- Binding indicators (shall, must, required, mandatory, policy, etc.)
- Applicability assessment across domains

RISK ASSESSMENT SUMMARY
-----------------------
• HIGH RISK (Score 3):      {len(high_risk)} document(s)
  Clear DEI mandates with binding language - immediate legal review required

• MEDIUM RISK (Score 2):    {len(medium_risk)} document(s)
  Probable DEI requirements - detailed analysis recommended

• LOW RISK (Score 1):       {len(low_risk)} document(s)
  Possible DEI language - monitoring suggested

• COMPLIANT (Score 0):      {len(self._get_compliant_documents())} document(s)
  No problematic DEI language detected

HIGH-RISK DOCUMENTS
-------------------
{self._format_document_list(high_risk, max_items=10)}

MEDIUM-RISK DOCUMENTS
---------------------
{self._format_document_list(medium_risk, max_items=5)}

KEY FINDINGS
------------
{self._summarize_key_findings()}

APPLICABILITY ANALYSIS
----------------------
{self._summarize_applicability()}

IMMEDIATE ACTIONS REQUIRED
--------------------------
{self._generate_action_items(high_risk, medium_risk)}

NEXT STEPS
----------
1. Review all high-risk documents with legal counsel
2. Assess enforceability and applicability to your organization
3. Document compliance posture and potential exemptions
4. Monitor for policy changes and enforcement actions
5. Consider proactive engagement with policy makers

For detailed analysis, see:
  - Technical Report: {self.project_name}_detailed_{self.timestamp}.txt
  - CSV Export: {self.project_name}_findings_{self.timestamp}.csv
  - JSON Data: {self.project_name}_data_{self.timestamp}.json

{'=' * 80}
"""
        return summary.strip()
    
    def generate_detailed_report(self) -> str:
        """
        Generate detailed technical report.
        
        Returns:
            Formatted detailed report text
        """
        report = f"""
{'=' * 80}
{self.project_name} - DETAILED TECHNICAL REPORT
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'=' * 80}

METHODOLOGY
-----------
Documents Analyzed: {len(self.documents)}
Analysis Date: {self.timestamp}

Keyword Analysis:
- DEI Terms: Core diversity, equity, inclusion terminology
- Proxy Terms: Euphemisms and indirect references to DEI
- Binding Terms: Mandatory language indicators

Risk Scoring Rubric:
- Score 0: No DEI/proxy language (compliant)
- Score 1: DEI/proxy present, weak binding (possible issue)
- Score 2: DEI/proxy + binding indicators (probable issue)
- Score 3: DEI + proxy + binding (clear issue/violation)

DOCUMENT BREAKDOWN
------------------
"""
        # Group by risk score
        by_score = {0: [], 1: [], 2: [], 3: []}
        for doc in self.documents:
            score = doc['risk']['score']
            by_score[score].append(doc)
        
        for score in [3, 2, 1, 0]:
            docs = by_score[score]
            report += f"\nRisk Score {score}: {len(docs)} document(s)\n"
            
            for doc in docs:
                report += self._format_document_details(doc)
        
        report += f"\n\nPROVISION ANALYSIS\n{'-' * 80}\n"
        report += self._analyze_provisions()
        
        report += f"\n\nTERM FREQUENCY ANALYSIS\n{'-' * 80}\n"
        report += self._analyze_term_frequency()
        
        report += f"\n\nRECOMMENDATIONS\n{'-' * 80}\n"
        report += self._generate_detailed_recommendations()
        
        report += f"\n{'=' * 80}\n"
        return report
    
    def save_reports(self, output_dir: str) -> Dict[str, str]:
        """
        Save all report formats to directory.
        
        Args:
            output_dir: Directory to save reports
            
        Returns:
            Dictionary mapping format to file path
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        saved_files = {}
        
        # Executive summary
        summary_file = output_path / f"{self.project_name}_executive_{self.timestamp}.txt"
        with open(summary_file, 'w') as f:
            f.write(self.generate_executive_summary())
        saved_files['executive_summary'] = str(summary_file)
        
        # Detailed report
        detailed_file = output_path / f"{self.project_name}_detailed_{self.timestamp}.txt"
        with open(detailed_file, 'w') as f:
            f.write(self.generate_detailed_report())
        saved_files['detailed_report'] = str(detailed_file)
        
        # CSV export
        csv_file = output_path / f"{self.project_name}_findings_{self.timestamp}.csv"
        self._save_csv(csv_file)
        saved_files['csv_export'] = str(csv_file)
        
        # JSON data
        json_file = output_path / f"{self.project_name}_data_{self.timestamp}.json"
        self._save_json(json_file)
        saved_files['json_data'] = str(json_file)
        
        return saved_files
    
    def _get_high_risk_documents(self) -> List[Dict]:
        """Get documents with score >= 3."""
        return [d for d in self.documents if d['risk']['score'] >= 3]
    
    def _get_medium_risk_documents(self) -> List[Dict]:
        """Get documents with score == 2."""
        return [d for d in self.documents if d['risk']['score'] == 2]
    
    def _get_low_risk_documents(self) -> List[Dict]:
        """Get documents with score == 1."""
        return [d for d in self.documents if d['risk']['score'] == 1]
    
    def _get_compliant_documents(self) -> List[Dict]:
        """Get documents with score == 0."""
        return [d for d in self.documents if d['risk']['score'] == 0]
    
    def _format_document_list(self, docs: List[Dict], max_items: int = 10) -> str:
        """Format list of documents for display."""
        if not docs:
            return "  (None)"
        
        lines = []
        for i, doc in enumerate(docs[:max_items], 1):
            metadata = doc['metadata']
            doc_id = metadata.get('id', metadata.get('source', f'Document {i}'))
            risk = doc['risk']
            
            lines.append(f"\n{i}. {doc_id}")
            lines.append(f"   Risk: {risk['level'].upper()} (score: {risk['score']}/3)")
            
            # Show DEI terms found
            dei_terms = risk['flagged_keywords']['dei'][:5]
            if dei_terms:
                lines.append(f"   DEI Terms: {', '.join(dei_terms)}")
            
            # Show binding terms
            binding_terms = risk['flagged_keywords']['binding'][:3]
            if binding_terms:
                lines.append(f"   Binding: {', '.join(binding_terms)}")
            
            # Show provision count
            prov_count = len(doc['provisions'])
            if prov_count > 0:
                lines.append(f"   Provisions: {prov_count} DEI provision(s) identified")
        
        if len(docs) > max_items:
            lines.append(f"\n  ... and {len(docs) - max_items} more")
        
        return '\n'.join(lines)
    
    def _format_document_details(self, doc: Dict) -> str:
        """Format detailed document information."""
        metadata = doc['metadata']
        risk = doc['risk']
        provisions = doc['provisions']
        
        doc_id = metadata.get('id', metadata.get('source', 'Unknown'))
        
        details = f"\n  {doc_id}\n"
        details += f"    Score: {risk['score']} ({risk['level']})\n"
        details += f"    DEI Keywords: {risk['dei_count']}, "
        details += f"Proxy: {risk['proxy_count']}, "
        details += f"Binding: {risk['binding_count']}\n"
        details += f"    Provisions: {len(provisions)}\n"
        
        if provisions:
            binding_provs = sum(1 for p in provisions if p.get('is_binding', False))
            details += f"    Binding Provisions: {binding_provs}\n"
        
        return details
    
    def _summarize_key_findings(self) -> str:
        """Summarize key findings across all documents."""
        if not self.documents:
            return "  No documents analyzed"
        
        # Aggregate statistics
        total_provisions = sum(len(d['provisions']) for d in self.documents)
        binding_provisions = sum(
            sum(1 for p in d['provisions'] if p.get('is_binding', False))
            for d in self.documents
        )
        
        # Count documents with each risk level
        high = len(self._get_high_risk_documents())
        medium = len(self._get_medium_risk_documents())
        
        findings = []
        
        if high > 0:
            findings.append(f"• {high} document(s) contain CLEAR DEI MANDATES with enforcement language")
            findings.append("  These require immediate legal review and compliance assessment")
        
        if medium > 0:
            findings.append(f"• {medium} document(s) contain PROBABLE DEI REQUIREMENTS")
            findings.append("  These should be analyzed for applicability and enforceability")
        
        if total_provisions > 0:
            findings.append(f"• {total_provisions} total DEI provisions identified across all documents")
            findings.append(f"• {binding_provisions} provisions contain binding/mandatory language")
        
        return '\n'.join(findings) if findings else "  No significant DEI requirements identified"
    
    def _summarize_applicability(self) -> str:
        """Summarize applicability areas across documents."""
        from complaint_analysis import DEIRiskScorer
        
        scorer = DEIRiskScorer()
        all_tags = []
        
        for doc in self.documents:
            # Would need to store document text or re-tag
            # For now, aggregate from risk results if available
            if 'applicability_tags' in doc['metadata']:
                all_tags.extend(doc['metadata']['applicability_tags'])
        
        if not all_tags:
            return "  Applicability analysis not available"
        
        # Count by area
        area_counts = {}
        for tag in all_tags:
            area_counts[tag] = area_counts.get(tag, 0) + 1
        
        lines = []
        for area, count in sorted(area_counts.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"• {area.replace('_', ' ').title()}: {count} document(s)")
        
        return '\n'.join(lines)
    
    def _generate_action_items(self, high_risk: List[Dict], medium_risk: List[Dict]) -> str:
        """Generate prioritized action items."""
        items = []
        
        if high_risk:
            items.append(f"1. URGENT: Legal review of {len(high_risk)} high-risk document(s)")
            items.append("   - Assess enforceability and legal implications")
            items.append("   - Determine applicability to your organization")
            items.append("   - Document compliance posture")
        
        if medium_risk:
            items.append(f"2. HIGH PRIORITY: Analysis of {len(medium_risk)} medium-risk document(s)")
            items.append("   - Review policy language and requirements")
            items.append("   - Assess compliance obligations")
            items.append("   - Consider requesting clarifications")
        
        if not items:
            items.append("1. Continue monitoring policies for changes")
            items.append("2. Maintain documented compliance posture")
        
        return '\n'.join(items)
    
    def _analyze_provisions(self) -> str:
        """Analyze provisions across all documents."""
        all_provisions = []
        for doc in self.documents:
            all_provisions.extend(doc['provisions'])
        
        if not all_provisions:
            return "No DEI provisions identified"
        
        binding = sum(1 for p in all_provisions if p.get('is_binding', False))
        
        analysis = f"Total Provisions: {len(all_provisions)}\n"
        analysis += f"Binding: {binding}\n"
        analysis += f"Non-Binding: {len(all_provisions) - binding}\n"
        
        return analysis
    
    def _analyze_term_frequency(self) -> str:
        """Analyze term frequency across all documents."""
        all_terms = []
        
        for doc in self.documents:
            risk = doc['risk']
            all_terms.extend(risk['flagged_keywords']['dei'])
            all_terms.extend(risk['flagged_keywords']['proxy'])
        
        if not all_terms:
            return "No terms identified"
        
        # Count frequency
        term_counts = {}
        for term in all_terms:
            term_counts[term] = term_counts.get(term, 0) + 1
        
        # Sort by frequency
        sorted_terms = sorted(term_counts.items(), key=lambda x: x[1], reverse=True)
        
        lines = [f"{term}: {count}" for term, count in sorted_terms[:20]]
        return '\n'.join(lines)
    
    def _generate_detailed_recommendations(self) -> str:
        """Generate detailed recommendations."""
        high = len(self._get_high_risk_documents())
        medium = len(self._get_medium_risk_documents())
        
        recs = []
        
        if high > 0:
            recs.append("High-Risk Documents:")
            recs.append("- Immediate legal consultation required")
            recs.append("- Review all related policies and contracts")
            recs.append("- Document potential discrimination issues")
            recs.append("- Consider policy challenge or exemption request")
            recs.append("")
        
        if medium > 0:
            recs.append("Medium-Risk Documents:")
            recs.append("- Detailed policy analysis recommended")
            recs.append("- Request clarification on requirements")
            recs.append("- Monitor for enforcement actions")
            recs.append("- Maintain compliance documentation")
            recs.append("")
        
        recs.append("General Recommendations:")
        recs.append("- Establish ongoing policy monitoring system")
        recs.append("- Train staff on compliance requirements")
        recs.append("- Document all DEI-related requests and communications")
        recs.append("- Maintain neutral, merit-based policies and practices")
        
        return '\n'.join(recs)
    
    def _save_csv(self, filepath: Path) -> None:
        """Save findings to CSV file."""
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Document ID', 'Risk Score', 'Risk Level',
                'DEI Keywords', 'Proxy Keywords', 'Binding Keywords',
                'Provisions', 'Binding Provisions'
            ])
            
            for doc in self.documents:
                metadata = doc['metadata']
                risk = doc['risk']
                provisions = doc['provisions']
                
                doc_id = metadata.get('id', metadata.get('source', 'Unknown'))
                binding_provs = sum(1 for p in provisions if p.get('is_binding', False))
                
                writer.writerow([
                    doc_id,
                    risk['score'],
                    risk['level'],
                    risk['dei_count'],
                    risk['proxy_count'],
                    risk['binding_count'],
                    len(provisions),
                    binding_provs
                ])
    
    def _save_json(self, filepath: Path) -> None:
        """Save all data to JSON file."""
        with open(filepath, 'w') as f:
            json.dump({
                'project': self.project_name,
                'generated_at': datetime.now().isoformat(),
                'document_count': len(self.documents),
                'documents': self.documents
            }, f, indent=2)
