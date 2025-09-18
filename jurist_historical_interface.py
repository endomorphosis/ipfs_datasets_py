#!/usr/bin/env python3
"""
Jurist-Focused Historical Legal Research Interface
Implementation of "text as informed by history" approach using GraphRAG and temporal deontic logic

Phase 1: Historical Context Integration
- Historical timeline visualization
- Era-based case filtering and organization  
- Historical context annotations
- Precedential genealogy visualization
"""

import os
import sys
import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from flask import Flask, render_template, request, jsonify
from dataclasses import dataclass, asdict

# Add the package to the path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from ipfs_datasets_py.deontic_logic.converter import DeonticLogicConverter
    from ipfs_datasets_py.deontic_logic.database import DeonticLogicDatabase
except ImportError:
    # Fallback imports for standalone operation
    from deontic_logic_database import DeonticLogicDatabase
    
@dataclass
class HistoricalEra:
    """Represents a historical legal era with context"""
    name: str
    start_year: int
    end_year: int
    description: str
    key_themes: List[str]
    major_cases: List[str]
    social_context: str
    
@dataclass  
class LegalCase:
    """Enhanced case representation with historical context"""
    id: str
    title: str
    citation: str
    year: int
    court: str
    era: str
    historical_significance: float
    precedential_strength: float
    legal_doctrines: List[str]
    historical_context: str
    social_impact: str
    subsequent_influence: List[str]

class HistoricalLegalContextProcessor:
    """Processes and analyzes legal cases with historical context"""
    
    def __init__(self):
        self.historical_eras = self._initialize_historical_eras()
        self.legal_cases = self._load_enhanced_case_data()
        self.deontic_db = DeonticLogicDatabase()
        
    def _initialize_historical_eras(self) -> Dict[str, HistoricalEra]:
        """Initialize major historical legal eras"""
        eras = {
            "founding_era": HistoricalEra(
                name="Founding Era",
                start_year=1787,
                end_year=1820,
                description="Constitutional foundation and early republic interpretation",
                key_themes=["Constitutional interpretation", "Federalism", "Individual rights", "Commerce regulation"],
                major_cases=["Marbury v. Madison", "McCulloch v. Maryland", "Gibbons v. Ogden"],
                social_context="Nation-building period with debates over federal vs state power and individual liberties"
            ),
            "antebellum": HistoricalEra(
                name="Antebellum Period", 
                start_year=1820,
                end_year=1861,
                description="Pre-Civil War tensions over slavery, states' rights, and federal authority",
                key_themes=["Slavery", "States' rights", "Property rights", "Commerce expansion"],
                major_cases=["Dred Scott v. Sandford", "Prigg v. Pennsylvania"],
                social_context="Growing sectional tensions over slavery and economic development"
            ),
            "reconstruction": HistoricalEra(
                name="Reconstruction Era",
                start_year=1865,
                end_year=1877,
                description="Post-Civil War constitutional amendments and civil rights",
                key_themes=["Civil rights", "Equal protection", "Federal enforcement", "Racial equality"],
                major_cases=["Civil Rights Cases", "Slaughter-House Cases"],
                social_context="Attempts to guarantee civil rights for freed slaves amid resistance"
            ),
            "gilded_age": HistoricalEra(
                name="Gilded Age",
                start_year=1877,
                end_year=1900,
                description="Industrial expansion and corporate power growth",
                key_themes=["Corporate regulation", "Labor rights", "Due process", "Interstate commerce"],
                major_cases=["Plessy v. Ferguson", "Lochner Era begins"],
                social_context="Rapid industrialization with growing wealth inequality and labor unrest"
            ),
            "progressive_era": HistoricalEra(
                name="Progressive Era",
                start_year=1900,
                end_year=1920,
                description="Reform movement addressing industrial excesses",
                key_themes=["Social reform", "Government regulation", "Women's suffrage", "Consumer protection"],
                major_cases=["Muller v. Oregon", "Schenck v. United States"],
                social_context="Reform movement responding to industrialization's social problems"
            ),
            "new_deal": HistoricalEra(
                name="New Deal Era",
                start_year=1933,
                end_year=1945,
                description="Expansion of federal government role in economy and society",
                key_themes=["Federal power expansion", "Economic regulation", "Social welfare", "Administrative law"],
                major_cases=["West Coast Hotel v. Parrish", "Wickard v. Filburn"],
                social_context="Great Depression and World War II driving federal government expansion"
            ),
            "warren_court": HistoricalEra(
                name="Warren Court Era",
                start_year=1953,
                end_year=1969,
                description="Civil rights revolution and individual liberties expansion",
                key_themes=["Civil rights", "Individual liberties", "Criminal procedure", "Equal protection"],
                major_cases=["Brown v. Board", "Miranda v. Arizona", "Gideon v. Wainwright"],
                social_context="Civil rights movement and social upheaval of the 1960s"
            ),
            "modern_era": HistoricalEra(
                name="Modern Era",
                start_year=1970,
                end_year=2024,
                description="Conservative legal movement and originalist interpretation",
                key_themes=["Originalism", "Federalism revival", "Privacy rights", "Technology law"],
                major_cases=["Roe v. Wade", "District of Columbia v. Heller", "Obergefell v. Hodges"],
                social_context="Political polarization and debates over judicial philosophy"
            )
        }
        return eras
        
    def _load_enhanced_case_data(self) -> List[LegalCase]:
        """Load comprehensive case data with historical context"""
        cases = [
            LegalCase(
                id="brown_v_board_1954",
                title="Oliver L. Brown, et al. v. Board of Education of Topeka, et al.",
                citation="347 U.S. 483 (1954)",
                year=1954,
                court="Supreme Court of the United States",
                era="warren_court",
                historical_significance=1.0,
                precedential_strength=1.0,
                legal_doctrines=["Equal Protection", "Civil Rights", "Education Law"],
                historical_context="Decided during the early Civil Rights Movement, this case challenged the 'separate but equal' doctrine established in Plessy v. Ferguson (1896). The decision came at a time of growing civil rights activism and represented a fundamental shift in constitutional interpretation.",
                social_impact="Catalyzed the modern Civil Rights Movement and led to massive resistance in the South. Changed American society by mandating school integration and challenging institutionalized racism.",
                subsequent_influence=["Griffin v. County School Board (1964)", "Green v. County School Board (1968)", "Swann v. Charlotte-Mecklenburg Board of Education (1971)"]
            ),
            LegalCase(
                id="plessy_v_ferguson_1896",
                title="Plessy v. Ferguson",
                citation="163 U.S. 537 (1896)",
                year=1896,
                court="Supreme Court of the United States", 
                era="gilded_age",
                historical_significance=0.9,
                precedential_strength=0.0,  # Overruled
                legal_doctrines=["Equal Protection", "Civil Rights", "Racial Segregation"],
                historical_context="Decided during the nadir of American race relations, this case legitimized Jim Crow laws in the post-Reconstruction South. The decision came as federal troops withdrew from the South and white supremacist governments regained control.",
                social_impact="Provided legal justification for racial segregation for nearly 60 years. Enabled systematic oppression of African Americans through 'separate but equal' facilities that were never truly equal.",
                subsequent_influence=["Cumming v. Richmond County Board of Education (1899)", "Gong Lum v. Rice (1927)", "Overruled by Brown v. Board (1954)"]
            ),
            LegalCase(
                id="miranda_v_arizona_1966",
                title="Miranda v. Arizona", 
                citation="384 U.S. 436 (1966)",
                year=1966,
                court="Supreme Court of the United States",
                era="warren_court",
                historical_significance=0.95,
                precedential_strength=0.9,
                legal_doctrines=["Criminal Procedure", "Fifth Amendment", "Sixth Amendment", "Due Process"],
                historical_context="Decided during the height of the Warren Court's criminal justice revolution. This case reflected growing concern about police interrogation practices and the need to protect individual rights against state power.",
                social_impact="Fundamentally changed police procedures and created the famous 'Miranda Rights' that must be read to suspects. Became a cultural touchstone for individual rights vs. law enforcement.",
                subsequent_influence=["Dickerson v. United States (2000)", "Berghuis v. Thompkins (2010)", "Vega v. Tekoh (2022)"]
            ),
            LegalCase(
                id="marbury_v_madison_1803",
                title="Marbury v. Madison",
                citation="5 U.S. (1 Cranch) 137 (1803)",
                year=1803,
                court="Supreme Court of the United States",
                era="founding_era", 
                historical_significance=1.0,
                precedential_strength=1.0,
                legal_doctrines=["Judicial Review", "Separation of Powers", "Constitutional Interpretation"],
                historical_context="Decided during the early republic when the role of the federal judiciary was still being defined. Chief Justice Marshall's decision established judicial review while avoiding direct confrontation with President Jefferson.",
                social_impact="Established the Supreme Court as co-equal branch of government with power to declare laws unconstitutional. Created the foundation of American constitutional law.",
                subsequent_influence=["McCulloch v. Maryland (1819)", "Cooper v. Aaron (1958)", "Fundamental to all subsequent constitutional law"]
            ),
            LegalCase(
                id="roe_v_wade_1973",
                title="Roe v. Wade",
                citation="410 U.S. 113 (1973)",
                year=1973,
                court="Supreme Court of the United States",
                era="modern_era",
                historical_significance=0.95,
                precedential_strength=0.0,  # Overruled by Dobbs
                legal_doctrines=["Privacy Rights", "Due Process", "Reproductive Rights", "Substantive Due Process"],
                historical_context="Decided during the feminist movement of the 1970s when women's rights were expanding. The decision built on earlier privacy cases like Griswold v. Connecticut (1965).",
                social_impact="Legalized abortion nationwide and became one of the most controversial decisions in American law. Shaped American politics for 50 years and energized both pro-choice and pro-life movements.",
                subsequent_influence=["Planned Parenthood v. Casey (1992)", "Gonzales v. Carhart (2007)", "Overruled by Dobbs v. Jackson (2022)"]
            )
        ]
        return cases
        
    def get_cases_by_era(self, era_name: str) -> List[LegalCase]:
        """Get all cases from a specific historical era"""
        return [case for case in self.legal_cases if case.era == era_name]
        
    def get_era_timeline(self) -> List[Dict]:
        """Generate timeline data for visualization"""
        timeline = []
        for era_key, era in self.historical_eras.items():
            cases_in_era = self.get_cases_by_era(era_key)
            timeline.append({
                'era': era.name,
                'start_year': era.start_year,
                'end_year': era.end_year,
                'description': era.description,
                'key_themes': era.key_themes,
                'case_count': len(cases_in_era),
                'major_cases': era.major_cases,
                'social_context': era.social_context
            })
        return sorted(timeline, key=lambda x: x['start_year'])
        
    def analyze_precedential_genealogy(self, case_id: str) -> Dict:
        """Analyze the precedential lineage of a case"""
        case = next((c for c in self.legal_cases if c.id == case_id), None)
        if not case:
            return {}
            
        # Find predecessor cases (cases this case cites/overrules)
        predecessors = []
        for other_case in self.legal_cases:
            if other_case.year < case.year and any(doctrine in case.legal_doctrines for doctrine in other_case.legal_doctrines):
                predecessors.append({
                    'id': other_case.id,
                    'title': other_case.title,
                    'citation': other_case.citation,
                    'year': other_case.year,
                    'relationship': 'builds_on' if other_case.precedential_strength > 0 else 'overrules'
                })
                
        # Find successor cases (cases that cite this case)
        successors = []
        for other_case in self.legal_cases:
            if other_case.year > case.year and case.title in other_case.subsequent_influence:
                successors.append({
                    'id': other_case.id,
                    'title': other_case.title,
                    'citation': other_case.citation,
                    'year': other_case.year,
                    'relationship': 'follows'
                })
                
        return {
            'case': asdict(case),
            'predecessors': predecessors,
            'successors': successors,
            'lineage_depth': len(predecessors) + len(successors),
            'historical_position': case.year - min(c.year for c in self.legal_cases)
        }
        
    def get_historical_significance_ranking(self) -> List[Dict]:
        """Rank cases by historical significance"""
        ranked_cases = sorted(self.legal_cases, key=lambda x: x.historical_significance, reverse=True)
        return [
            {
                'rank': i + 1,
                'id': case.id,
                'title': case.title,
                'citation': case.citation,
                'year': case.year,
                'era': case.era,
                'significance': case.historical_significance,
                'precedential_strength': case.precedential_strength,
                'social_impact': case.social_impact
            }
            for i, case in enumerate(ranked_cases)
        ]

class JuristHistoricalInterface:
    """Main Flask application for jurist-focused historical legal research"""
    
    def __init__(self):
        self.app = Flask(__name__, template_folder='templates')
        self.processor = HistoricalLegalContextProcessor()
        self.setup_routes()
        
    def setup_routes(self):
        """Set up Flask routes for the historical interface"""
        
        @self.app.route('/')
        def index():
            """Main dashboard with historical timeline"""
            timeline = self.processor.get_era_timeline()
            significance_ranking = self.processor.get_historical_significance_ranking()[:10]
            
            return render_template('jurist_historical_dashboard.html',
                                 timeline=timeline,
                                 significance_ranking=significance_ranking)
                                 
        @self.app.route('/api/era/<era_name>')
        def get_era_cases(era_name):
            """Get cases from specific era"""
            cases = self.processor.get_cases_by_era(era_name)
            return jsonify([asdict(case) for case in cases])
            
        @self.app.route('/api/genealogy/<case_id>')  
        def get_case_genealogy(case_id):
            """Get precedential genealogy for a case"""
            genealogy = self.processor.analyze_precedential_genealogy(case_id)
            return jsonify(genealogy)
            
        @self.app.route('/api/timeline')
        def get_timeline_data():
            """Get timeline data for visualization"""
            return jsonify(self.processor.get_era_timeline())
            
        @self.app.route('/api/significance-ranking')
        def get_significance_ranking():
            """Get historical significance ranking"""
            return jsonify(self.processor.get_historical_significance_ranking())
            
        @self.app.route('/case/<case_id>')
        def case_detail(case_id):
            """Detailed case view with historical context"""
            genealogy = self.processor.analyze_precedential_genealogy(case_id)
            return render_template('historical_case_detail.html', genealogy=genealogy)
            
    def run(self, host='0.0.0.0', port=5001, debug=True):
        """Run the Flask application"""
        print(f"Starting Jurist Historical Interface on http://{host}:{port}")
        self.app.run(host=host, port=port, debug=debug)

if __name__ == "__main__":
    # Create and run the jurist historical interface
    interface = JuristHistoricalInterface()
    interface.run()