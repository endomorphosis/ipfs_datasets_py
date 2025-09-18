#!/usr/bin/env python3
"""
Historical Timeline Interface for Jurists
Implements "text as informed by history" approach with chronological case visualization
and era-based legal analysis for professional legal research.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from flask import Flask, render_template, jsonify, request
import logging

@dataclass
class HistoricalCase:
    """Represents a legal case with historical context"""
    case_id: str
    name: str
    citation: str
    court: str
    decision_date: datetime
    era: str
    legal_topics: List[str]
    precedential_strength: float
    historical_significance: int
    summary: str
    deontic_logic: Optional[str] = None

@dataclass
class LegalEra:
    """Represents a historical legal era"""
    name: str
    start_year: int
    end_year: int
    description: str
    key_characteristics: List[str]
    major_cases: List[str]

class HistoricalTimelineProcessor:
    """
    Processes legal cases for historical timeline visualization
    Implements chronological analysis with era-based categorization
    """
    
    def __init__(self, database_path: str = "historical_timeline.db"):
        self.database_path = database_path
        self.logger = logging.getLogger(__name__)
        self.legal_eras = self._initialize_legal_eras()
        self._initialize_database()
    
    def _initialize_legal_eras(self) -> List[LegalEra]:
        """Initialize major historical legal eras"""
        return [
            LegalEra(
                name="Founding Era",
                start_year=1789,
                end_year=1820,
                description="Constitutional foundation and early republic",
                key_characteristics=[
                    "Original constitutional interpretation",
                    "Federalism establishment", 
                    "Bill of Rights implementation"
                ],
                major_cases=["Marbury v. Madison", "McCulloch v. Maryland"]
            ),
            LegalEra(
                name="Antebellum Period",
                start_year=1821,
                end_year=1860,
                description="Pre-Civil War constitutional development",
                key_characteristics=[
                    "Slavery legal framework",
                    "Commerce Clause expansion",
                    "States' rights tensions"
                ],
                major_cases=["Dred Scott v. Sandford", "Gibbons v. Ogden"]
            ),
            LegalEra(
                name="Reconstruction Era",
                start_year=1861,
                end_year=1890,
                description="Post-Civil War constitutional transformation",
                key_characteristics=[
                    "14th and 15th Amendments",
                    "Civil rights legislation",
                    "Federal supremacy"
                ],
                major_cases=["The Slaughter-House Cases", "Civil Rights Cases"]
            ),
            LegalEra(
                name="Lochner Era",
                start_year=1891,
                end_year=1936,
                description="Economic due process and substantive due process",
                key_characteristics=[
                    "Economic liberty protection",
                    "Substantive due process",
                    "Limited government regulation"
                ],
                major_cases=["Lochner v. New York", "Adkins v. Children's Hospital"]
            ),
            LegalEra(
                name="New Deal Era",
                start_year=1937,
                end_year=1952,
                description="Constitutional revolution and expanded federal power",
                key_characteristics=[
                    "Commerce Clause expansion",
                    "Federal regulatory power",
                    "Economic regulation acceptance"
                ],
                major_cases=["NLRB v. Jones & Laughlin Steel Corp.", "Wickard v. Filburn"]
            ),
            LegalEra(
                name="Warren Court Era",
                start_year=1953,
                end_year=1969,
                description="Civil rights expansion and individual liberties",
                key_characteristics=[
                    "Civil rights revolution",
                    "Criminal procedure rights",
                    "Equal protection expansion"
                ],
                major_cases=["Brown v. Board of Education", "Miranda v. Arizona", "Gideon v. Wainwright"]
            ),
            LegalEra(
                name="Burger Court Era", 
                start_year=1970,
                end_year=1985,
                description="Conservative shift with continued rights expansion",
                key_characteristics=[
                    "Law and order emphasis",
                    "Privacy rights development",
                    "Administrative law growth"
                ],
                major_cases=["Roe v. Wade", "Chevron U.S.A. v. NRDC"]
            ),
            LegalEra(
                name="Modern Era",
                start_year=1986,
                end_year=datetime.now().year,
                description="Contemporary constitutional interpretation",
                key_characteristics=[
                    "Originalism vs. Living Constitution",
                    "Technology and privacy",
                    "Globalization impacts"
                ],
                major_cases=["District of Columbia v. Heller", "Obergefell v. Hodges"]
            )
        ]
    
    def _initialize_database(self):
        """Initialize SQLite database for historical timeline data"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        # Create tables for historical analysis
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS historical_cases (
                case_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                citation TEXT,
                court TEXT,
                decision_date DATE,
                era TEXT,
                legal_topics TEXT,  -- JSON array
                precedential_strength REAL,
                historical_significance INTEGER,
                summary TEXT,
                deontic_logic TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS legal_eras (
                era_name TEXT PRIMARY KEY,
                start_year INTEGER,
                end_year INTEGER,
                description TEXT,
                key_characteristics TEXT,  -- JSON array
                major_cases TEXT  -- JSON array
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS precedent_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                citing_case TEXT,
                cited_case TEXT,
                relationship_type TEXT,
                strength REAL,
                temporal_distance INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (citing_case) REFERENCES historical_cases (case_id),
                FOREIGN KEY (cited_case) REFERENCES historical_cases (case_id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS historical_annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT,
                annotation_type TEXT,
                content TEXT,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (case_id) REFERENCES historical_cases (case_id)
            )
        ''')
        
        conn.commit()
        conn.close()
        
        # Populate legal eras
        self._populate_legal_eras()
    
    def _populate_legal_eras(self):
        """Populate the legal eras table"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        for era in self.legal_eras:
            cursor.execute('''
                INSERT OR REPLACE INTO legal_eras 
                (era_name, start_year, end_year, description, key_characteristics, major_cases)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                era.name,
                era.start_year,
                era.end_year,
                era.description,
                json.dumps(era.key_characteristics),
                json.dumps(era.major_cases)
            ))
        
        conn.commit()
        conn.close()
    
    def determine_legal_era(self, decision_date: datetime) -> str:
        """Determine which legal era a case belongs to"""
        year = decision_date.year
        for era in self.legal_eras:
            if era.start_year <= year <= era.end_year:
                return era.name
        return "Unknown Era"
    
    def add_historical_case(self, case: HistoricalCase) -> bool:
        """Add a case to the historical timeline database"""
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            # Determine era if not provided
            if not case.era:
                case.era = self.determine_legal_era(case.decision_date)
            
            cursor.execute('''
                INSERT OR REPLACE INTO historical_cases
                (case_id, name, citation, court, decision_date, era, legal_topics,
                 precedential_strength, historical_significance, summary, deontic_logic)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                case.case_id,
                case.name,
                case.citation,
                case.court,
                case.decision_date.isoformat(),
                case.era,
                json.dumps(case.legal_topics),
                case.precedential_strength,
                case.historical_significance,
                case.summary,
                case.deontic_logic
            ))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            self.logger.error(f"Error adding case {case.case_id}: {e}")
            return False
    
    def get_timeline_data(self, start_year: int = 1789, end_year: int = None) -> Dict[str, Any]:
        """Get timeline data for visualization"""
        if end_year is None:
            end_year = datetime.now().year
        
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        # Get cases in date range
        cursor.execute('''
            SELECT case_id, name, citation, court, decision_date, era, 
                   legal_topics, precedential_strength, historical_significance, summary
            FROM historical_cases
            WHERE strftime('%Y', decision_date) BETWEEN ? AND ?
            ORDER BY decision_date
        ''', (str(start_year), str(end_year)))
        
        cases = []
        for row in cursor.fetchall():
            cases.append({
                'case_id': row[0],
                'name': row[1],
                'citation': row[2],
                'court': row[3],
                'decision_date': row[4],
                'era': row[5],
                'legal_topics': json.loads(row[6]) if row[6] else [],
                'precedential_strength': row[7],
                'historical_significance': row[8],
                'summary': row[9]
            })
        
        # Get era information
        cursor.execute('SELECT * FROM legal_eras ORDER BY start_year')
        eras = []
        for row in cursor.fetchall():
            eras.append({
                'name': row[0],
                'start_year': row[1],
                'end_year': row[2],
                'description': row[3],
                'key_characteristics': json.loads(row[4]) if row[4] else [],
                'major_cases': json.loads(row[5]) if row[5] else []
            })
        
        conn.close()
        
        return {
            'cases': cases,
            'eras': eras,
            'timeline_range': {'start': start_year, 'end': end_year},
            'total_cases': len(cases)
        }
    
    def get_era_analysis(self, era_name: str) -> Dict[str, Any]:
        """Get detailed analysis for a specific era"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        # Get era details
        cursor.execute('SELECT * FROM legal_eras WHERE era_name = ?', (era_name,))
        era_row = cursor.fetchone()
        
        if not era_row:
            return {}
        
        # Get cases from this era
        cursor.execute('''
            SELECT case_id, name, citation, court, decision_date, 
                   legal_topics, precedential_strength, historical_significance, summary
            FROM historical_cases
            WHERE era = ?
            ORDER BY historical_significance DESC, decision_date
        ''', (era_name,))
        
        cases = []
        for row in cursor.fetchall():
            cases.append({
                'case_id': row[0],
                'name': row[1],
                'citation': row[2],
                'court': row[3],
                'decision_date': row[4],
                'legal_topics': json.loads(row[5]) if row[5] else [],
                'precedential_strength': row[6],
                'historical_significance': row[7],
                'summary': row[8]
            })
        
        conn.close()
        
        return {
            'era': {
                'name': era_row[0],
                'start_year': era_row[1],
                'end_year': era_row[2],
                'description': era_row[3],
                'key_characteristics': json.loads(era_row[4]) if era_row[4] else [],
                'major_cases': json.loads(era_row[5]) if era_row[5] else []
            },
            'cases': cases,
            'case_count': len(cases),
            'avg_precedential_strength': sum(c['precedential_strength'] for c in cases) / len(cases) if cases else 0
        }
    
    def add_precedent_relationship(self, citing_case: str, cited_case: str, 
                                 relationship_type: str, strength: float) -> bool:
        """Add precedent relationship between cases"""
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            # Calculate temporal distance
            cursor.execute('''
                SELECT 
                    strftime('%Y', citing.decision_date) - strftime('%Y', cited.decision_date) as temporal_distance
                FROM historical_cases citing, historical_cases cited
                WHERE citing.case_id = ? AND cited.case_id = ?
            ''', (citing_case, cited_case))
            
            temporal_distance = cursor.fetchone()
            temporal_distance = temporal_distance[0] if temporal_distance else 0
            
            cursor.execute('''
                INSERT OR REPLACE INTO precedent_relationships
                (citing_case, cited_case, relationship_type, strength, temporal_distance)
                VALUES (?, ?, ?, ?, ?)
            ''', (citing_case, cited_case, relationship_type, strength, temporal_distance))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            self.logger.error(f"Error adding precedent relationship: {e}")
            return False
    
    def get_precedent_genealogy(self, case_id: str, depth: int = 3) -> Dict[str, Any]:
        """Get precedent genealogy for a case (both forward and backward citations)"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        def get_citations(case_id: str, direction: str, current_depth: int = 0) -> List[Dict]:
            if current_depth >= depth:
                return []
            
            if direction == 'backward':  # Cases this case cites
                query = '''
                    SELECT cited.case_id, cited.name, cited.citation, cited.decision_date,
                           pr.relationship_type, pr.strength, pr.temporal_distance
                    FROM precedent_relationships pr
                    JOIN historical_cases cited ON pr.cited_case = cited.case_id
                    WHERE pr.citing_case = ?
                    ORDER BY pr.strength DESC
                '''
            else:  # Cases that cite this case
                query = '''
                    SELECT citing.case_id, citing.name, citing.citation, citing.decision_date,
                           pr.relationship_type, pr.strength, pr.temporal_distance
                    FROM precedent_relationships pr
                    JOIN historical_cases citing ON pr.citing_case = citing.case_id
                    WHERE pr.cited_case = ?
                    ORDER BY pr.strength DESC
                '''
            
            cursor.execute(query, (case_id,))
            results = []
            
            for row in cursor.fetchall():
                result = {
                    'case_id': row[0],
                    'name': row[1],
                    'citation': row[2],
                    'decision_date': row[3],
                    'relationship_type': row[4],
                    'strength': row[5],
                    'temporal_distance': row[6],
                    'depth': current_depth + 1
                }
                
                # Recursively get citations for this case
                if current_depth < depth - 1:
                    result['citations'] = get_citations(row[0], direction, current_depth + 1)
                
                results.append(result)
            
            return results
        
        # Get the main case details
        cursor.execute('SELECT * FROM historical_cases WHERE case_id = ?', (case_id,))
        main_case = cursor.fetchone()
        
        if not main_case:
            conn.close()
            return {}
        
        # Get precedent genealogy
        backward_citations = get_citations(case_id, 'backward')
        forward_citations = get_citations(case_id, 'forward')
        
        conn.close()
        
        return {
            'main_case': {
                'case_id': main_case[0],
                'name': main_case[1],
                'citation': main_case[2],
                'court': main_case[3],
                'decision_date': main_case[4],
                'era': main_case[5],
                'legal_topics': json.loads(main_case[6]) if main_case[6] else [],
                'precedential_strength': main_case[7],
                'historical_significance': main_case[8],
                'summary': main_case[9]
            },
            'precedents_cited': backward_citations,  # Cases this case relies on
            'subsequent_citations': forward_citations,  # Cases that rely on this case
            'genealogy_depth': depth
        }

class HistoricalTimelineApp:
    """Flask application for historical timeline interface"""
    
    def __init__(self):
        self.app = Flask(__name__)
        self.processor = HistoricalTimelineProcessor()
        self._setup_routes()
        self._populate_sample_data()
    
    def _setup_routes(self):
        """Setup Flask routes for the historical timeline interface"""
        
        @self.app.route('/')
        def index():
            return render_template('historical_timeline.html')
        
        @self.app.route('/api/timeline/data')
        def get_timeline_data():
            start_year = request.args.get('start_year', 1789, type=int)
            end_year = request.args.get('end_year', datetime.now().year, type=int)
            return jsonify(self.processor.get_timeline_data(start_year, end_year))
        
        @self.app.route('/api/era/<era_name>')
        def get_era_analysis(era_name):
            return jsonify(self.processor.get_era_analysis(era_name))
        
        @self.app.route('/api/case/<case_id>/genealogy')
        def get_precedent_genealogy(case_id):
            depth = request.args.get('depth', 3, type=int)
            return jsonify(self.processor.get_precedent_genealogy(case_id, depth))
        
        @self.app.route('/api/eras')
        def get_legal_eras():
            return jsonify([{
                'name': era.name,
                'start_year': era.start_year,
                'end_year': era.end_year,
                'description': era.description,
                'key_characteristics': era.key_characteristics,
                'major_cases': era.major_cases
            } for era in self.processor.legal_eras])
    
    def _populate_sample_data(self):
        """Populate with sample historical cases"""
        sample_cases = [
            HistoricalCase(
                case_id="marbury_v_madison_1803",
                name="Marbury v. Madison",
                citation="5 U.S. 137 (1803)",
                court="Supreme Court",
                decision_date=datetime(1803, 2, 24),
                era="Founding Era",
                legal_topics=["Constitutional Law", "Judicial Review"],
                precedential_strength=1.0,
                historical_significance=10,
                summary="Established judicial review and the principle that the Constitution is the supreme law.",
                deontic_logic="O(judiciary(review_constitutionality)) ∧ F(enforce_unconstitutional_laws)"
            ),
            HistoricalCase(
                case_id="brown_v_board_1954",
                name="Brown v. Board of Education",
                citation="347 U.S. 483 (1954)",
                court="Supreme Court", 
                decision_date=datetime(1954, 5, 17),
                era="Warren Court Era",
                legal_topics=["Civil Rights", "Equal Protection", "Education"],
                precedential_strength=1.0,
                historical_significance=10,
                summary="Declared racial segregation in public schools unconstitutional.",
                deontic_logic="F(separate_educational_facilities_based_on_race) ∧ O(provide_equal_educational_opportunities)"
            ),
            HistoricalCase(
                case_id="miranda_v_arizona_1966",
                name="Miranda v. Arizona", 
                citation="384 U.S. 436 (1966)",
                court="Supreme Court",
                decision_date=datetime(1966, 6, 13),
                era="Warren Court Era",
                legal_topics=["Criminal Procedure", "Fifth Amendment", "Self-Incrimination"],
                precedential_strength=0.9,
                historical_significance=9,
                summary="Required police to inform suspects of their constitutional rights before interrogation.",
                deontic_logic="O(inform_suspects_of_rights) ∧ T(before_interrogation) ∧ F(use_unwarned_statements)"
            )
        ]
        
        for case in sample_cases:
            self.processor.add_historical_case(case)
        
        # Add some precedent relationships
        self.processor.add_precedent_relationship(
            "brown_v_board_1954", "marbury_v_madison_1803", "relies_on", 0.7
        )
    
    def run(self, host='0.0.0.0', port=5001, debug=True):
        """Run the Flask application"""
        self.app.run(host=host, port=port, debug=debug)

if __name__ == "__main__":
    app = HistoricalTimelineApp()
    print("Starting Historical Timeline Interface for Jurists...")
    print("Access the interface at: http://localhost:5001")
    app.run()