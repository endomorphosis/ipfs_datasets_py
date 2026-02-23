"""Standard benchmark datasets for GraphRAG optimization testing.

This module provides curated datasets across multiple domains (legal, medical,
technical, financial) at various complexity levels for consistent benchmarking.

Usage::

    from benchmark_datasets import BenchmarkDataset
    
    Legal domain, complex:
    dataset = BenchmarkDataset.load("legal", complexity="complex")
    text, metadata = dataset.text, dataset.metadata
    
    Medical domain, simple:
    simple = BenchmarkDataset.load("medical", complexity="simple")
    
    All datasets:
    for name in BenchmarkDataset.AVAILABLE_DATASETS:
        ds = BenchmarkDataset.load(name)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Dict, Any
import textwrap


@dataclass
class BenchmarkDataset:
    """Container for benchmark dataset text and metadata."""
    
    domain: str
    complexity: Literal["simple", "medium", "complex"]
    text: str
    metadata: Dict[str, Any]
    
    @property
    def token_count(self) -> int:
        """Approximate token count (splits on whitespace)."""
        return len(self.text.split())
    
    @property
    def char_count(self) -> int:
        """Character count."""
        return len(self.text)
    
    AVAILABLE_DATASETS = ["legal", "medical", "technical", "financial"]
    
    @classmethod
    def load(
        cls,
        domain: str,
        complexity: Literal["simple", "medium", "complex"] = "medium",
    ) -> "BenchmarkDataset":
        """Load a benchmark dataset by domain and complexity.
        
        Args:
            domain: One of "legal", "medical", "technical", "financial"
            complexity: One of "simple" (~500 tokens), "medium" (~2K tokens), "complex" (~5K tokens)
            
        Returns:
            BenchmarkDataset instance with text and metadata
            
        Raises:
            ValueError: If domain or complexity not supported
        """
        if domain not in cls.AVAILABLE_DATASETS:
            raise ValueError(
                f"Unknown domain: {domain}. Supported: {cls.AVAILABLE_DATASETS}"
            )
        
        valid_complexities = ["simple", "medium", "complex"]
        if complexity not in valid_complexities:
            raise ValueError(
                f"Unknown complexity: {complexity}. Supported: {valid_complexities}"
            )
        
        # Dispatch to specific loader
        loader = _DATASET_LOADERS.get((domain, complexity))
        if not loader:
            raise ValueError(f"No dataset for {domain}/{complexity}")
        
        return loader()


# ============================================================================
# Legal Domain Datasets
# ============================================================================

def _load_legal_simple() -> BenchmarkDataset:
    """Simple legal document (~500 tokens): Contract excerpt."""
    text = textwrap.dedent("""\
        ENGAGEMENT LETTER
        
        This Engagement Letter ("Agreement") is entered into as of January 15, 2024,
        between Acme Legal Services, Inc. (the "Firm") and Smith Manufacturing Corp.
        (the "Client").
        
        1. SCOPE OF SERVICES
        The Firm agrees to provide legal representation for the Client in matters related
        to contract negotiation and employment law. Services shall include document review,
        legal analysis, and negotiation support as requested by the Client.
        
        2. COMPENSATION AND FEES
        Client agrees to pay the Firm at the rate of $300 per hour for attorney services
        and $150 per hour for paralegal services. Retainer fee of $5,000 is due upon
        execution of this Agreement, with final billing upon completion of engagement.
        
        3. CONFIDENTIALITY
        The Firm agrees to maintain strict confidentiality of all Client communications
        and documents. Legal privilege is asserted over all attorney-client communications.
        
        SIGNATURES
        By: James Anderson, Managing Partner
        Acme Legal Services, Inc.
        
        Date: January 15, 2024
        Acknowledged by: Robert Smith, CEO
        Smith Manufacturing Corp.
        """)
    
    metadata = {
        "document_type": "engagement_letter",
        "jurisdiction": "US",
        "expected_entities": [
            "Acme Legal Services, Inc.",
            "Smith Manufacturing Corp.",
            "James Anderson",
            "Robert Smith",
            "$300",
            "$150",
            "$5,000",
        ],
        "expected_entity_types": ["Organization", "Person", "Money", "Date"],
        "expected_relationships": [
            ("James Anderson", "Acme Legal Services, Inc.", "works_for"),
            ("Robert Smith", "Smith Manufacturing Corp.", "works_for"),
        ],
    }
    
    return BenchmarkDataset(
        domain="legal",
        complexity="simple",
        text=text,
        metadata=metadata,
    )


def _load_legal_medium() -> BenchmarkDataset:
    """Medium legal document (~2K tokens): Contract with multiple clauses."""
    text = textwrap.dedent("""\
        SERVICE AGREEMENT
        
        This Service Agreement ("Agreement") is made and entered into on March 10, 2024,
        between Dynamic Technology Solutions LLC ("Service Provider") and Global Finance
        Holdings, Inc. ("Client").
        
        RECITALS
        WHEREAS, the Service Provider possesses specialized expertise in enterprise software
        integration and data analytics; and
        WHEREAS, the Client desires to engage the Service Provider to provide such services;
        NOW, THEREFORE, in consideration of mutual covenants and agreements, the parties
        agree as follows:
        
        1. SERVICES
        The Service Provider shall provide the following services:
        (a) System architecture review and recommendations
        (b) Database optimization and performance tuning
        (c) Security audit and compliance assessment
        (d) Technical documentation and knowledge transfer
        (e) 24/7 technical support with 4-hour SLA for critical issues
        
        2. TERM AND TERMINATION
        This Agreement shall commence on April 1, 2024, and continue for twelve (12) months
        unless earlier terminated. Either party may terminate with thirty (30) days written
        notice. Upon termination, all Client data shall be returned within five (5) business days.
        
        3. COMPENSATION
        Client shall pay Service Provider $12,500 monthly for the services described above.
        Payment is due within fifteen (15) days of invoice. Late payments accrue interest
        at 1.5% per month. Additional services beyond scope are billed at $200 per hour.
        
        4. INTELLECTUAL PROPERTY
        All work product, documentation, and deliverables created under this Agreement shall
        be the exclusive property of the Client. Service Provider retains rights to pre-existing
        IP and reusable components developed outside this engagement.
        
        5. CONFIDENTIALITY AND NON-DISCLOSURE
        Both parties agree to maintain confidentiality of proprietary information for a period
        of three (3) years following termination. This includes client data, system architecture,
        performance metrics, and business processes discovered during the engagement.
        
        6. LIABILITY LIMITATION
        IN NO EVENT SHALL EITHER PARTY BE LIABLE FOR INDIRECT, INCIDENTAL, CONSEQUENTIAL,
        SPECIAL, OR PUNITIVE DAMAGES, INCLUDING LOSS OF PROFITS OR BUSINESS INTERRUPTION,
        EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.
        
        7. GOVERNING LAW
        This Agreement shall be governed by and construed in accordance with the laws of
        the State of New York, without regard to its conflict of law principles.
        
        EXECUTED as of the date first written above:
        
        SERVICE PROVIDER:
        By: Patricia Johnson, President
        Dynamic Technology Solutions LLC
        100 Tech Boulevard, San Francisco, CA 94105
        
        CLIENT:
        By: Michael Chen, Chief Technology Officer
        Global Finance Holdings, Inc.
        500 Fifth Avenue, New York, NY 10110
        """)
    
    metadata = {
        "document_type": "service_agreement",
        "jurisdiction": "New York",
        "expected_entities": [
            "Dynamic Technology Solutions LLC",
            "Global Finance Holdings, Inc.",
            "Patricia Johnson",
            "Michael Chen",
            "April 1, 2024",
            "$12,500",
            "$200",
            "San Francisco, CA",
            "New York, NY",
        ],
        "expected_entity_types": ["Organization", "Person", "Money", "Date", "Location"],
        "expected_relationships": [
            ("Patricia Johnson", "Dynamic Technology Solutions LLC", "employment"),
            ("Michael Chen", "Global Finance Holdings, Inc.", "employment"),
        ],
    }
    
    return BenchmarkDataset(
        domain="legal",
        complexity="medium",
        text=text,
        metadata=metadata,
    )


def _load_legal_complex() -> BenchmarkDataset:
    """Complex legal document (~5K tokens): Multi-section contract."""
    text = textwrap.dedent("""\
        MASTER DEVELOPMENT AND LICENSING AGREEMENT
        
        AGREEMENT dated as of June 1, 2024 ("Effective Date"), between:
        
        NORTHERN BIOTECH RESEARCH INC., a Delaware corporation with principal offices at
        2500 Sandhill Road, Menlo Park, California 94025 ("Licensor"), and
        
        PACIFIC PHARMACEUTICAL CORPORATION, a Delaware corporation with principal offices
        at 1 Biotech Drive, San Jose, California 95110 ("Licensee")
        
        RECITALS:
        
        A. Licensor has developed certain patented technologies for drug delivery systems
        and therapeutic monitoring, and wishes to license certain rights therein to Licensee.
        
        B. Licensee desires to obtain such licenses on the terms and conditions set forth herein.
        
        C. Licensor and Licensee have previously entered into a Research Collaboration Agreement
        dated January 15, 2023 (the "Collaboration Agreement"), and wish to expand their
        relationship through this Development and Licensing Agreement.
        
        NOW THEREFORE, in consideration of the mutual covenants and agreements herein contained,
        and for other good and valuable consideration, the receipt and sufficiency of which are
        hereby acknowledged, the parties agree as follows:
        
        1. DEFINITIONS AND INTERPRETATIONS
        
        1.1 "Licensed Patents" means all patents and patent applications owned or controlled by
        Licensor covering the Licensed Products, including those in the following patent families:
        (a) U.S. Patent Application 16/234,567 filed March 10, 2019
        (b) International Patent Application PCT/US2019/026789
        (c) Japanese Patent Application 2019-506789
        
        1.2 "Licensed Products" means any pharmaceutical composition, medical device, or therapeutic
        treatment incorporating or arising from the Licensed Technology.
        
        1.3 "Effective Technology" means the technology described in Schedule A attached hereto,
        including:
        - Sustained Release Formulation (SRF) system
        - Real-Time Biomarker Monitoring (RTBM) platform
        - Adaptive Therapy Response (ATR) algorithm
        
        1.4 "Territory" means the United States, Canada, Mexico, and the European Union.
        
        1.5 "Royalty Rate" means:
        (a) 3.5% for sales less than $100 million annually
        (b) 3.0% for sales from $100-500 million annually
        (c) 2.5% for sales exceeding $500 million annually
        
        2. GRANT OF LICENSES
        
        2.1 Subject to the terms and conditions of this Agreement, including receipt of the
        upfront payment specified in Section 3.1, Licensor hereby grants to Licensee:
        
        (a) A non-exclusive, worldwide license (except as limited by Territory definition)
        (b) The right to develop, manufacture, use, and sell Licensed Products
        (c) The right to sublicense such rights to third parties with prior written approval
        (d) The right to commercialize Licensed Products through approved marketing channels
        
        2.2 Licensor reserves all rights not expressly granted herein.
        
        3. FINANCIAL TERMS
        
        3.1 Upfront Payment
        Within ten (10) business days of the Effective Date, Licensee shall pay Licensor
        the sum of $5,000,000 (five million U.S. dollars) as a non-refundable upfront payment.
        
        3.2 Milestone Payments
        Upon achievement of the following development milestones, Licensee shall pay Licensor:
        
        (a) Successful IND Application filing: $2,000,000
        (b) Phase I trial initiation: $3,000,000
        (c) Phase II trial initiation: $5,000,000
        (d) Phase III trial initiation: $7,500,000
        (e) FDA approval for first indication: $10,000,000
        (f) FDA approval for second indication: $7,500,000
        
        3.3 Royalty Payments
        Licensee shall pay Licensor royalties on Net Sales of Licensed Products at the Royalty
        Rate specified in Section 1.5, payable quarterly within thirty (30) days of quarter end.
        Minimum annual royalty of $500,000 applies beginning Year 3 after first commercial sale.
        
        3.4 Sublicense Fees
        For any sublicenses granted by Licensee, it shall pay Licensor 30% of all fees, royalties,
        and milestone payments received from the sublicensee.
        
        4. DEVELOPMENT OBLIGATIONS
        
        4.1 Licensee shall use commercially reasonable efforts to:
        (a) Develop the Licensed Products for therapeutic indications
        (b) Seek regulatory approval from FDA and equivalent foreign authorities
        (c) Commercialize approved Licensed Products
        (d) Achieve the following development timeline:
           - IND Application by December 31, 2025
           - Phase I initiation by June 30, 2026
           - Phase II initiation by June 30, 2027
        
        4.2 Licensee shall provide Licensor with written progress reports quarterly, including
        development status, preclinical results, regulatory interactions, and clinical trial data.
        
        5. INTELLECTUAL PROPERTY
        
        5.1 IP Ownership
        - Licensed Patents remain the sole property of Licensor
        - Any modifications to Licensed Technology created by Licensee shall be owned by Licensee
        - Co-owned improvements may result from collaborative efforts (address in detail)
        
        5.2 Patent Maintenance
        Licensor shall be responsible for initial prosecution and maintenance of Licensed Patents.
        After first commercial sale, Licensee shall reimburse 50% of patent costs in Territory.
        
        5.3 Patent Defense
        Should Licensed Patents be challenged, parties shall cooperate in defense. Each party
        shall bear its own legal costs unless agreement provides otherwise.
        
        6. CONFIDENTIALITY
        
        6.1 Each party shall maintain confidentiality of the other's proprietary information
        for a period of five (5) years from disclosure.
        
        6.2 Exceptions include information that is:
        (a) Publicly available or becomes so through no breach of this Agreement
        (b) Previously known without obligation of confidentiality
        (c) Independently developed without reference to the other party's information
        (d) Required to be disclosed by law or regulatory authority
        
        6.3 Public disclosures and publications require 30 days prior written notice and
        opportunity for review.
        
        7. REPRESENTATIONS AND WARRANTIES
        
        7.1 Licensor represents and warrants:
        (a) It owns or controls the Licensed Patents
        (b) It has the right to grant the licenses herein
        (c) Licensed Patents do not infringe third-party rights (with exceptions in Schedule B)
        (d) It is aware of no infringement claims
        
        7.2 Licensee represents and warrants:
        (a) It has authority to enter into this Agreement
        (b) It has adequate financial and technical resources to perform obligations
        (c) It shall comply with all applicable laws and regulations
        
        8. TERM AND TERMINATION
        
        8.1 Initial Term
        This Agreement shall commence on the Effective Date and continue until the expiration
        of the last Licensed Patent, unless earlier terminated.
        
        8.2 Termination for Cause
        Either party may terminate if the other breaches a material term and fails to cure
        within sixty (60) days of written notice; in case of bankruptcy, immediately.
        
        8.3 Termination for Convenience
        Licensee may terminate with ninety (90) days written notice after the first anniversary.
        Licensor may not terminate except for material breach.
        
        8.4 Effects of Termination
        - All rights granted herein cease
        - Licensee shall pay royalties for 12 months after termination
        - Licensee shall return or destroy all proprietary documents
        - Surviving obligations (confidentiality, indemnification) continue
        
        9. INDEMNIFICATION
        
        9.1 Licensee shall indemnify Licensor against claims arising from:
        (a) Licensee's use or sale of Licensed Products
        (b) Licensee's breach of this Agreement
        (c) Licensee's product liability or regulatory violations
        (d) Licensee's sublicensees' actions
        
        9.2 Licensor shall indemnify Licensee against claims that Licensed Patents, as
        provided by Licensor, infringe valid third-party intellectual property rights.
        
        10. DISPUTE RESOLUTION
        
        10.1 Disputes shall first be addressed through good faith negotiation between
        senior executives of both parties, within thirty (30) days of dispute notice.
        
        10.2 If negotiation fails, disputes shall be submitted to binding arbitration
        under JAMS rules, conducted in San Francisco, California, with one arbitrator.
        
        10.3 Each party shall bear its own legal costs, except arbitrator may award costs
        and attorney fees to prevailing party.
        
        11. GOVERNING LAW
        
        This Agreement shall be governed by California law without regard to conflict of laws.
        The United Nations Convention on Contracts for the International Sale of Goods shall
        not apply.
        
        IN WITNESS WHEREOF, the parties have executed this Agreement as of the date first
        written above:
        
        NORTHERN BIOTECH RESEARCH INC.
        
        By: Dr. Sarah Williams
        Name: Dr. Sarah Williams
        Title: Chief Executive Officer and President
        Date: June 1, 2024
        
        PACIFIC PHARMACEUTICAL CORPORATION
        
        By: David Thompson
        Name: David Thompson
        Title: President and Chief Business Officer
        Date: June 1, 2024
        """)
    
    metadata = {
        "document_type": "development_licensing_agreement",
        "jurisdiction": "California",
        "expected_entities": [
            "Northern BioTech Research Inc.",
            "Pacific Pharmaceutical Corporation",
            "Dr. Sarah Williams",
            "David Thompson",
            "Delaware",
            "June 1, 2024",
            "FDA",
            "$5,000,000",
            "$2,000,000",
            "$3,000,000",
            "Menlo Park, California",
            "San Jose, California",
        ],
        "expected_entity_types": ["Organization", "Person", "Location", "Money", "Date"],
        "expected_relationships": [
            ("Dr. Sarah Williams", "Northern BioTech Research Inc.", "ceo"),
            ("David Thompson", "Pacific Pharmaceutical Corporation", "president"),
        ],
    }
    
    return BenchmarkDataset(
        domain="legal",
        complexity="complex",
        text=text,
        metadata=metadata,
    )


# ============================================================================
# Medical Domain Datasets
# ============================================================================

def _load_medical_simple() -> BenchmarkDataset:
    """Simple medical document (~500 tokens): Clinical note excerpt."""
    text = textwrap.dedent("""\
        CLINICAL PROGRESS NOTE
        
        Patient: Jane Doe, DOB: 03/15/1978
        MRN: 456789012
        Date of Visit: February 20, 2024
        Provider: Dr. Michael Chen, MD
        
        CHIEF COMPLAINT:
        Patient presents with persistent cough and fatigue for the past two weeks.
        
        HISTORY OF PRESENT ILLNESS:
        45-year-old female with no significant past medical history reports onset of dry cough
        approximately 14 days ago. Cough is worse in evening and is associated with mild dyspnea.
        Denies fever, chest pain, or hemoptysis. Has had associated fatigue affecting work productivity.
        
        PHYSICAL EXAMINATION:
        Vital Signs: BP 118/76, HR 78, RR 16, T 98.6°F
        General: Alert, no acute distress
        Lungs: Clear to auscultation bilaterally
        
        ASSESSMENT:
        Likely viral upper respiratory infection, rule out acute bronchitis.
        
        PLAN:
        1. Order chest X-ray and CBC to rule out pneumonia
        2. Prescribe prednisone 20mg daily for 5 days
        3. Recommend rest, hydration, and over-the-counter cough suppressant
        4. Follow-up in 2 weeks if symptoms persist
        5. Patient counseled on warning signs requiring emergency evaluation
        
        By: Michael Chen, MD
        Date: February 20, 2024
        """)
    
    metadata = {
        "document_type": "clinical_note",
        "medical_specialty": "Internal Medicine",
        "expected_entities": [
            "Jane Doe",
            "Dr. Michael Chen",
            "February 20, 2024",
            "prednisone",
            "20mg",
        ],
        "expected_entity_types": ["Person", "Date", "Medication", "Dosage"],
        "expected_relationships": [
            ("Jane Doe", "Dr. Michael Chen", "patient_of"),
        ],
    }
    
    return BenchmarkDataset(
        domain="medical",
        complexity="simple",
        text=text,
        metadata=metadata,
    )


def _load_medical_medium() -> BenchmarkDataset:
    """Medium medical document (~2K tokens): Discharge summary."""
    text = textwrap.dedent("""\
        HOSPITAL DISCHARGE SUMMARY
        
        PATIENT: Robert Johnson
        DATE OF ADMISSION: January 5, 2024
        DATE OF DISCHARGE: January 12, 2024
        ATTENDING PHYSICIAN: Dr. Catherine Martinez, MD, FACP
        HOSPITALIZATION: 7 days
        
        ADMISSION DIAGNOSIS:
        Acute myocardial infarction (AMI), anterior wall STEMI
        
        DISCHARGE DIAGNOSIS:
        1. Acute myocardial infarction, anterior wall, status post percutaneous coronary
           intervention (PCI) to left anterior descending (LAD) artery
        2. Hypertension, controlled
        3. Hyperlipidemia
        4. Type 2 diabetes mellitus
        
        HISTORY OF PRESENT ILLNESS:
        Patient is a 62-year-old male who presented to the emergency department with acute
        substernal chest pain radiating to left arm, diaphoresis, and shortness of breath.
        EKG demonstrated ST elevation in leads V1-V4 consistent with anterior STEMI. Emergent
        cardiac catheterization revealed 95% lesion in LAD with acute thrombosis. Drug-eluting
        stent (Abbott DES) was deployed successfully with TIMI 3 flow restored.
        
        HOSPITAL COURSE:
        Patient was transferred to CCU for continuous cardiac monitoring and hemodynamic support.
        Troponin peaked at 45.2 ng/mL on day 2. Transthoracic echocardiogram showed anterior wall
        hypokinesis with ejection fraction of 35-40%. Patient received dual antiplatelet therapy
        (aspirin 325mg daily, ticagrelor 90mg bid) and anticoagulation (IV heparin). ACE inhibitor
        (lisinopril 5mg daily) and beta-blocker (metoprolol 25mg daily) were initiated.
        
        PROCEDURES PERFORMED:
        1. Emergency cardiac catheterization via right femoral approach
        2. PCI to LAD with drug-eluting stent placement
        3. Transthoracic echocardiogram
        4. Serial EKG monitoring
        
        DISCHARGE MEDICATIONS:
        1. Aspirin 325mg daily
        2. Ticagrelor 90mg twice daily
        3. Lisinopril 5mg daily
        4. Metoprolol succinate 25mg daily
        5. Atorvastatin 80mg daily
        6. Omeprazole 20mg daily (gastroprotection)
        
        FOLLOW-UP:
        - Cardiology follow-up in 2 weeks with Dr. Martinez
        - PCP follow-up in 1 week
        - Stress test scheduled for 6 weeks post-discharge
        - Cardiac rehabilitation program enrollment recommended
        
        ACTIVITY:
        Light activity only, no heavy lifting exceeding 10 lbs for 4 weeks
        
        DIET:
        Low sodium diet, fluid restriction 2L daily
        
        Discharge Summary prepared by:
        Catherine Martinez, MD
        Date: January 12, 2024
        """)
    
    metadata = {
        "document_type": "discharge_summary",
        "medical_specialty": "Cardiology",
        "expected_entities": [
            "Robert Johnson",
            "Dr. Catherine Martinez",
            "January 5, 2024",
            "January 12, 2024",
            "aspirin",
            "ticagrelor",
            "lisinopril",
            "metoprolol",
            "atorvastatin",
            "LAD",
            "35-40%",
        ],
        "expected_entity_types": ["Person", "Date", "Medication", "Anatomy", "Measurement"],
        "expected_relationships": [
            ("Robert Johnson", "Dr. Catherine Martinez", "patient_of"),
        ],
    }
    
    return BenchmarkDataset(
        domain="medical",
        complexity="medium",
        text=text,
        metadata=metadata,
    )


def _load_medical_complex() -> BenchmarkDataset:
    """Complex medical document (~5K tokens): Comprehensive pathology report."""
    text = textwrap.dedent("""\
        COMPREHENSIVE PATHOLOGY REPORT
        
        SPECIMEN TYPE: Breast tissue, sentinel lymph node, axillary dissection
        PATIENT: Susan Adams
        MRN: 789456123
        DOB: 07/22/1965
        DATE RECEIVED: December 15, 2023
        DATE SIGNED: December 20, 2023
        PATHOLOGIST: Dr. James Richardson, MD, PhD, FCAP
        
        CLINICAL HISTORY:
        64-year-old female with palpable left breast mass detected on self-examination.
        Mammography and ultrasound reveal a 2.4-cm solid hypoechoic mass in left upper
        outer quadrant. Biopsy performed showing invasive ductal carcinoma, grade 2.
        Patient referred for modified radical mastectomy with sentinel lymph node biopsy
        and axillary lymph node dissection.
        
        GROSS PATHOLOGY DESCRIPTION:
        
        A. Breast Tissue:
        Specimen consists of left breast measuring 18 x 15 x 8 cm weighing 380 grams. Skin
        overlying specimen is intact, measuring 18 x 12 cm. On sectioning, a firm gray-white
        mass is identified measuring 2.4 x 2.0 x 2.2 cm located in the upper outer quadrant.
        Mass is pale, infiltrative, with indistinct margins. The remaining breast parenchyma
        shows normal adipose tissue with scattered fibrotic areas. No other lesions identified.
        Distance from mass to surgical margins: Superficial margin 2.8 cm, deep margin 4.1 cm,
        lateral margin 2.2 cm, medial margin 8.5 cm.
        
        B. Sentinel Lymph Node:
        Two lymph nodes received, tan-brown, aggregate measuring 1.8 x 1.5 cm.
        
        C. Axillary Lymph Node Dissection:
        Specimen consists of fatty tissue containing multiple lymph nodes, measuring aggregately
        8 x 6 x 4 cm. Twenty-two lymph nodes are isolated and examined.
        
        MICROSCOPIC PATHOLOGY FINDINGS:
        
        A. Primary Tumor Assessment:
        Invasive ductal carcinoma (IDC), not otherwise specified (NOS)
        - Histologic Grade: 2 (Modified Bloom-Richardson score: 7/9)
        - Tubule formation: 2/3 (moderate)
        - Nuclear pleomorphism: 2/3 (moderate)
        - Mitotic rate: 2/3 (moderate)
        
        Tumor demonstrates relatively uniform nuclei with prominent nucleoli and moderate
        mitotic activity, approximately 8-10 mitoses per 10 high-power fields.
        
        B. Estrogen Receptor (ER) Status:
        Positive by immunohistochemistry (IHC), approximately 75% of tumor cells staining.
        Rating: 3+ strong, diffuse nuclear staining.
        
        C. Progesterone Receptor (PR) Status:
        Positive by IHC, approximately 60% of tumor cells demonstrating nuclear positivity.
        Rating: 2+ moderate staining.
        
        D. HER2/neu Status:
        Negative by IHC (0-1+ staining pattern). FISH analysis not needed based on
        IHC scoring criteria.
        
        E. Ki-67 Proliferation Index:
        Approximately 18% by IHC, consistent with histologic grade 2 carcinoma.
        
        F. Margins:
        All surgical margins are negative for malignancy. Closest margin is lateral at 2.2 cm.
        
        G. Lymphovascular Invasion:
        Present. Small nests of tumor cells identified within vascular spaces in several
        high-power fields immediately adjacent to primary tumor.
        
        H. Intraductal Component:
        Ductal carcinoma in situ (DCIS) is present at the periphery of the invasive tumor,
        occupying approximately 15% of the cross-sectional area of the lesion.
        Grade 2 (intermediate grade) with cribriform pattern.
        
        I. Sentinel Lymph Node Evaluation:
        Two sentinel lymph nodes are negative for malignancy. No metastatic carcinoma identified
        by routine H&E sections or immunohistochemical staining.
        
        J. Axillary Lymph Node Dissection:
        Twenty-two lymph nodes are identified and examined. Twenty nodes are negative for
        malignancy. Two lymph nodes show metastatic carcinoma:
        
        - Node 1 (Level I): 1.2 cm metastatic deposit with extranodal extension (ENE)
        - Node 2 (Level I): 0.8 cm metastatic focus, without ENE
        
        Remaining twenty nodes are negative.
        
        PATHOLOGIC STAGING (TNM - AJCC 8th Edition):
        T: T2 (2.4 cm with lymphovascular invasion)
        N: N1mi (Micrometastasis in sentinel lymph node does not apply; involved axillary nodes
           present = N1)
           
        CLINICAL STAGE: Stage IIIA (T2N1)
        
        MOLECULAR SUBTYPE:
        Luminal A (ER+, PR+, HER2-, Ki-67 <20%)
        
        RECOMMENDATIONS FOR TREATMENT:
        1. Adjuvant chemotherapy recommended (AC-T regimen or equivalent)
        2. Hormonal therapy (tamoxifen or aromatase inhibitor) for minimum 5 years
        3. Radiation therapy to chest wall and regional nodes recommended
        4. Gene-expression testing (Oncotype Dx or MammaPrint) recommended to refine
           chemotherapy benefit estimation
        
        ADDITIONAL STUDIES PERFORMED:
        - Immunohistochemical studies (ER, PR, HER2, Ki-67)
        - FISH analysis not required (IHC HER2 0-1+)
        
        REPORT SIGNED:
        Dr. James Richardson, MD, PhD, FCAP
        Surgical Pathology
        Date: December 20, 2023
        """)
    
    metadata = {
        "document_type": "pathology_report",
        "medical_specialty": "Surgical Pathology/Oncology",
        "expected_entities": [
            "Susan Adams",
            "Dr. James Richardson",
            "December 15, 2023",
            "December 20, 2023",
            "2.4 cm",
            "18 x 15 x 8 cm",
            "75%",
            "60%",
            "18%",
        ],
        "expected_entity_types": ["Person", "Date", "Measurement", "Percentage", "Finding"],
        "expected_relationships": [
            ("Susan Adams", "Dr. James Richardson", "patient_of"),
        ],
    }
    
    return BenchmarkDataset(
        domain="medical",
        complexity="complex",
        text=text,
        metadata=metadata,
    )


# ============================================================================
# Technical Domain Datasets
# ============================================================================

def _load_technical_simple() -> BenchmarkDataset:
    """Simple technical document (~500 tokens): API documentation."""
    text = textwrap.dedent("""\
        REST API Documentation
        Version 2.0
        
        BASE URL: https://api.example.com/v2
        
        AUTHENTICATION
        All requests require Bearer token authentication. Include the Authorization header:
        Authorization: Bearer YOUR_API_KEY
        
        Obtain API keys from: https://developers.example.com/keys
        
        ENDPOINTS
        
        1. GET /users/{id}
        Returns user profile information.
        
        Parameters:
        - id (string): User identifier
        
        Response:
        {
          "id": "user_123",
          "name": "John Developer",
          "email": "john@example.com",
          "created": "2023-06-15T10:30:00Z"
        }
        
        2. POST /projects
        Create a new project.
        
        Request Body:
        {
          "name": "My Project",
          "description": "Project description",
          "visibility": "private"
        }
        
        Response: 201 Created
        Returns: Project object with generated ID
        
        3. DELETE /projects/{id}
        Delete a project. Requires admin permissions.
        
        Response: 204 No Content
        
        ERROR CODES
        - 400 Bad Request: Invalid parameters
        - 401 Unauthorized: Authentication failed
        - 403 Forbidden: Insufficient permissions
        - 404 Not Found: Resource not found
        - 429 Too Many Requests: Rate limit exceeded (100 req/min)
        """)
    
    metadata = {
        "document_type": "api_documentation",
        "technology": "REST API",
        "expected_entities": [
            "https://api.example.com/v2",
            "user_123",
            "John Developer",
            "POST",
            "GET",
            "DELETE",
        ],
        "expected_entity_types": ["URL", "ID", "Person", "HTTPMethod"],
        "expected_relationships": [],
    }
    
    return BenchmarkDataset(
        domain="technical",
        complexity="simple",
        text=text,
        metadata=metadata,
    )


def _load_technical_medium() -> BenchmarkDataset:
    """Medium technical document (~2K tokens): System architecture."""
    text = textwrap.dedent("""\
        SYSTEM ARCHITECTURE DESIGN DOCUMENT
        Project: CloudDataProcessor v3.0
        Author: Alice Chen, Lead Architect
        Date: February 2024
        
        EXECUTIVE SUMMARY
        CloudDataProcessor is a distributed data processing platform designed to handle
        petabyte-scale analytics workloads. The system processes data from multiple sources
        using Apache Spark, Kubernetes orchestration, and PostgreSQL data warehousing.
        
        1. SYSTEM COMPONENTS
        
        1.1 Data Ingestion Layer
        - Kafka brokers (cluster of 5 nodes) handle streaming data ingestion
        - Apache NiFi processes batch data with retry logic and error handling
        - Data validation framework checks schema compliance before persistence
        
        1.2 Processing Layer
        - Apache Spark cluster (3 master, 12 worker nodes)
        - Jobs submitted via YARN job scheduler
        - Intermediate data stored in HDFS with replication factor of 3
        - Processing pipelines orchestrated by Apache Airflow
        
        1.3 Storage Layer
        - Primary: PostgreSQL 14 (3-node streaming replication)
        - Cache: Redis cluster with Sentinel for high availability
        - Archive: S3-compatible object storage with Glacier lifecycle
        
        1.4 Serving Layer
        - REST API (FastAPI) with OpenAPI/Swagger documentation
        - GraphQL endpoint for flexible queries
        - WebSocket connections for real-time subscriptions
        
        2. DEPLOYMENT ARCHITECTURE
        
        2.1 Kubernetes Infrastructure
        - Kuberenetes 1.27 cluster running on AWS EKS
        - Master nodes: 3 (AWS c5.4xlarge instances)
        - Worker nodes: 20 (AWS r5.2xlarge auto-scaling)
        - Container registry: AWS ECR
        
        2.2 High Availability
        - Multi-AZ deployment across us-east-1a, us-east-1b, us-east-1c
        - Load balancer: AWS ALB with health checks (30s interval)
        - RTO: 15 minutes, RPO: 5 minutes
        
        2.3 Network Architecture
        - VPC spanning three subnets (10.0.1.0/24, 10.0.2.0/24, 10.0.3.0/24)
        - VPN gateway for on-premises connectivity
        - Security groups restrict access: SSH (22), HTTP (80), HTTPS (443), Kafka (9092)
        
        3. PERFORMANCE SPECIFICATIONS
        
        3.1 Throughput
        - Batch processing: 10TB/hour sustained, 15TB/hour peak
        - Streaming: 1M events/second sustained, 2M events/second peak
        - Query latency: <100ms p95 for aggregations on <1B rows
        
        3.2 Resource Allocation
        - Compute: 256 vCPUs across worker pool
        - Memory: 1.5TB total RAM (avg utilization 65%)
        - Storage: 50TB hot (HDFS), 500TB warm (S3 standard), 5PB cold (Glacier)
        
        4. MONITORING AND OBSERVABILITY
        
        4.1 Metrics Collection
        - Prometheus scrapes metrics from all components (15s interval)
        - Metric retention: 30 days at high resolution, 1 year at daily resolution
        
        4.2 Logging
        - ELK Stack (Elasticsearch, Logstash, Kibana) for centralized logging
        - Log retention: 90 days in hot index, 1 year in warm index
        - Daily log volume: ~500GB across all services
        
        4.3 Alerting
        - AlertManager routes alerts by severity
        - Critical alerts (page on-call engineer via PagerDuty)
        - Runbooks available for common incidents
        
        5. SECURITY CONSIDERATIONS
        
        5.1 Authentication & Authorization
        - OAuth 2.0 with integrated identity provider
        - Role-based access control (RBAC) for data access
        - API key rotation every 90 days
        
        5.2 Data Protection
        - Encryption in transit: TLS 1.3 for all connections
        - Encryption at rest: AES-256 for S3, encrypted EBS volumes
        - Data classification by sensitivity level
        
        6. DISASTER RECOVERY
        
        6.1 Backup Strategy
        - Automated PostgreSQL backups every 6 hours
        - HDFS snapshots created daily
        - Cross-region replication to us-west-2
        
        6.2 Recovery Procedures
        - RTO 15 minutes, RPO 5 minutes for critical systems
        - Quarterly disaster recovery drills
        - Recovery runbooks tested and verified
        
        Document prepared by:
        Alice Chen, Lead Architect
        """)
    
    metadata = {
        "document_type": "architecture_design",
        "technology": "Cloud Infrastructure",
        "expected_entities": [
            "CloudDataProcessor",
            "Alice Chen",
            "Apache Spark",
            "Kubernetes",
            "PostgreSQL",
            "AWS",
            "AWS EKS",
            "256 vCPUs",
            "1.5TB",
        ],
        "expected_entity_types": ["Product", "Person", "Technology", "Cloud Provider", "Resource"],
        "expected_relationships": [
            ("Alice Chen", "CloudDataProcessor", "architect"),
        ],
    }
    
    return BenchmarkDataset(
        domain="technical",
        complexity="medium",
        text=text,
        metadata=metadata,
    )


def _load_technical_complex() -> BenchmarkDataset:
    """Complex technical document (~5K tokens): Software specification."""
    text = textwrap.dedent("""\
        SOFTWARE REQUIREMENTS SPECIFICATION (SRS)
        Document Type: Technical Specification
        Version: 3.0
        Status: Final Review
        Prepared By: Dr. Robert Williams, Senior Software Architect
        Date: February 2024
        Review: Michael Torres, Technical Lead Review completed February 19, 2024
        
        1. PRODUCT OVERVIEW AND OBJECTIVES
        
        1.1 Product Description
        The Real-Time Event Processing Engine (TREPE v3.0) is a distributed, fault-tolerant
        system designed to process, correlate, and respond to events in real-time with
        sub-second latencies. The system ingests events from multiple sources (sensors,
        applications, APIs), applies complex event processing rules, and triggers actions.
        
        1.2 Project Objectives
        - Process 10M+ events/second with <100ms end-to-end latency (p99)
        - Support deployment on Kubernetes clusters (1,000+ nodes)
        - Enable users to define CEP (Complex Event Processing) rules via visual UI
        - Provide 99.99% availability SLA with automatic failover
        - Integrate with Apache Kafka, RabbitMQ, Redis, and proprietary message systems
        - Support machine learning model inference for anomaly detection
        
        1.3 Target Users
        - DevOps engineers (system deployment and monitoring)
        - Data engineers (rule definition and pipeline management)
        - Security operations (real-time threat detection)
        - Business analysts (KPI monitoring and alerting)
        
        2. FUNCTIONAL REQUIREMENTS
        
        2.1 Event Ingestion (FR-1)
        
        FR-1.1: The system SHALL support Kafka as primary event source
           - Accept events from multiple Kafka topics
           - Maintain order within a partition
           - Support Avro, JSON, Protobuf, and custom serialization formats
           - Handle retries with exponential backoff
           
        FR-1.2: Support multiple message queue backends
           - RabbitMQ: Support direct exchange, topic, and fanout patterns
           - Redis Streams: Support stream groups and consumer offsets
           - Custom HTTP endpoint for webhook-style ingestion
           - SQS integration via AWS SDK
           
        FR-1.3: Data validation on ingestion
           - Validate events against schema (AVSC files or JSON Schema)
           - Reject malformed events and log for audit trail
           - Support optional fields and default value injection
        
        2.2 Rule Processing Engine (FR-2)
        
        FR-2.1: Complex event pattern matching
           - Support temporal operators (WITHIN, FOLLOWED BY, NOT WITHIN)
           - Pattern definition in Esper EPL (Event Processing Language)
           - Context for stateful processing (event context, session context)
           - Event aggregation (sliding/tumbling windows)
           
        FR-2.2: State management
           - In-memory state store for pattern matching (Koa RocksDB)
           - Distributed state across cluster with replication
           - TTL support for state cleanup (default: 24 hours)
           - Optional external state (Redis, PostgreSQL)
           
        FR-2.3: User-defined functions (UDFs)
           - Support Java, Python 3.10+, and JavaScript UDFs
           - UDF versioning and deployment without system restart
           - Sandboxed execution environment with resource limits
             - Memory limit: 512MB per UDF instance
             - CPU limit: 1 vCPU core per UDF
             - Execution timeout: 5 seconds
        
        2.3 Output Routing (FR-3)
        
        FR-3.1: Multi-destination output
           - Kafka producer (partitioning options by key or round-robin)
           - HTTP POST webhooks with retry policy (exponential backoff, max 5 retries)
           - Database writes (SQL or NoSQL)
           - File system (S3, GCS, local HDFS)
           - Elasticsearch for indexed storage
           
        FR-3.2: Output transformation
           - Template-based message formatting (Jinja2 syntax)
           - Field mapping and aggregation
           - Compression (GZIP, Snappy) for large payloads
        
        2.4 Rule Management (FR-4)
        
        FR-4.1: Rule lifecycle
           - Create, read, update, delete rules (CRUD operations)
           - Dry-run mode to test rules before deployment
           - Versioning of rules (automatic version increments)
           - Deployment scheduling (immediate or scheduled for specific time)
           
        FR-4.2: Rule organization
           - Group rules into applications (logical namespaces)
           - Enable/disable rules individually or by application
           - Import/export rule sets (JSON or YAML format)
           - Rule dependency management and impact analysis
        
        3. NON-FUNCTIONAL REQUIREMENTS
        
        3.1 Performance (NFR-1)
        
        NFR-1.1: Throughput
           - Minimum 10M events/second sustained processing
           - Peak burst capacity 15M events/second (duration: 30 seconds)
           - Latency (p99): <100ms end-to-end (ingestion → processing → output)
           - Latency (p99.9): <500ms
        
        NFR-1.2: Resource efficiency
           - Memory usage: <2GB per 1M events/sec (with 1000-entry patterns)
           - CPU usage: 15-20% per million events/sec on 2-GHz processor
           - Network: <2Gbps for 10M events/sec (assuming 200-byte average)
           - Disk I/O: Minimized (stateless processing preferred)
        
        3.2 Availability (NFR-2)
        
        NFR-2.1: Service availability
           - Target SLA: 99.99% (4.4 minutes/month downtime)
           - Active-active deployment across 3+ availability zones
           - Automatic failover for failed nodes (<10 second detection/failover)
           - Rolling updates without service interruption
           
        NFR-2.2: Data durability
           - Event loss threshold: 0 events for committed state
           - Graceful degradation: If output fails, retry before dropping
           - Backup checkpointing every 30 seconds
        
        3.3 Scalability (NFR-3)
        
        NFR-3.1: Horizontal scaling
           - Linear scaling up to 1,000+ Kubernetes nodes
           - Auto-scaling based on:
             - Event queue depth (lag >10000 events → scale up)
             - CPU utilization (>70% → scale up, <30% → scale down)
             - Memory pressure (>85% → scale up)
           - Minimum 3 replicas, maximum 100 replicas per rule group
        
        3.4 Security (NFR-4)
        
        NFR-4.1: Authentication and authorization
           - OAuth 2.0 for API access
           - Service-to-service auth (mTLS certificates)
           - RBAC for rule management (admin, editor, viewer roles)
           - Audit logging for all rule changes
           
        NFR-4.2: Data protection
           - TLS 1.3 for all network communication
           - Encryption at rest for state storage
           - PII masking in logs (credit cards, SSN patterns)
           - Data retention policies by data classification
        
        3.5 Reliability (NFR-5)
        
        NFR-5.1: Error handling and recovery
           - Automatic circuit breaker for failing outputs
           - Dead-letter queue for unprocessable events
           - Poison message detection and alerting
           - Graceful degradation when dependencies unavailable
           
        NFR-5.2: Observability
           - Distributed tracing (OpenTelemetry integration)
           - Prometheus metrics for all subsystems
           - Structured logging (JSON format with context)
           - Health checks with detailed diagnostics
        
        4. SYSTEM ARCHITECTURE
        
        4.1 High-level Components
        
        ┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
        │  Kafka Topics   │────▶│  Event Grouper   │────▶│  CEP Engine      │
        │  RabbitMQ       │     │  (Kafka Consumer)│     │  (Esper EPL)     │
        │  Redis Streams  │     │                  │     │                  │
        └─────────────────┘     └──────────────────┘     └──────────────────┘
                                                                  │
                                                                  ▼
                                        ┌─────────────────────────────────────┐
                                        │     Output Router / Actions         │
                                        │  (Templates, Destinations, UDFs)    │
                                        └─────────────────────────────────────┘
                                                          │
                        ┌─────────────┬──────────────┬────┼────┬──────────────┐
                        ▼             ▼              ▼    ▼    ▼              ▼
                    ┌────────┐   ┌─────────┐   ┌──────┐ │ ┌──────┐   ┌──────────┐
                    │ Kafka  │   │ Webhooks│   │ Database   │Elasticsearch│File│
                    │(Output)│   │(Retries)│   │            │            │Store│
                    └────────┘   └─────────┘   └──────┘ │ └──────┘   └──────────┘
        
        4.2 Technology Stack
        
        Core Engine:
        - Language: Java 17 with Spring Boot 3.0
        - CEP: Esper v8.10 with custom extensions
        - Message Streaming: Apache Kafka 3.4, Flink SQL for advanced queries
        
        Deployment:
        - Container: Docker OCI image (minimal Alpine base, <200MB)
        - Orchestration: Kubernetes 1.27+ with Helm charts
        - Monitoring: Prometheus 2.40, Grafana 9.4, Jaeger for tracing
        
        Dependencies:
        - Spring Cloud Netflix for service discovery
        - PostgreSQL 15 for metadata/configuration
        - Redis 7.0 for caching and state store
        - Vault for secrets management
        
        5. ACCEPTANCE CRITERIA
        
        - All 25 functional requirements (FR-1 through FR-4.2) MUST be implemented
        - All non-functional requirements (NFR) MUST pass load tests
        - Code coverage MUST exceed 85% for critical paths
        - Documentation MUST be complete (API docs, deployment guide, troubleshooting)
        - Security review MUST be passed by InfoSec team
        - Performance benchmarks MUST meet p99 latency targets
        
        Approved by:
        Dr. Robert Williams, Senior Software Architect
        Michael Torres, Technical Lead
        Date: February 2024
        """)
    
    metadata = {
        "document_type": "software_requirements_specification",
        "technology": "Event Processing",
        "expected_entities": [
            "TREPE v3.0",
            "Dr. Robert Williams",
            "Michael Torres",
            "Kubernetes",
            "Apache Kafka",
            "Esper EPL",
            "10M+ events/second",
            "99.99%",
        ],
        "expected_entity_types": ["Product", "Person", "Technology", "Metric"],
        "expected_relationships": [
            ("Dr. Robert Williams", "TREPE v3.0", "architect"),
            ("Michael Torres", "TREPE v3.0", "technical_lead"),
        ],
    }
    
    return BenchmarkDataset(
        domain="technical",
        complexity="complex",
        text=text,
        metadata=metadata,
    )


# ============================================================================
# Financial Domain Datasets
# ============================================================================

def _load_financial_simple() -> BenchmarkDataset:
    """Simple financial document (~500 tokens): Transaction summary."""
    text = textwrap.dedent("""\
        MONTHLY TRANSACTION STATEMENT
        
        Account Holder: Emily Rodriguez
        Account Number: 4567-8901-2345-6789
        Statement Period: January 1-31, 2024
        
        ACCOUNT SUMMARY
        Previous Balance: $12,450.32
        Total Deposits: $3,850.00
        Total Withdrawals: $2,145.67
        Ending Balance: $14,154.65
        
        TRANSACTIONS
        
        01/02/2024  Payroll Deposit        +$2,500.00    Balance: $14,950.32
        01/05/2024  Amazon Purchase         -$87.45     Balance: $14,862.87
        01/10/2024  Electric Bill           -$145.23    Balance: $14,717.64
        01/12/2024  ATM Withdrawal          -$200.00    Balance: $14,517.64
        01/15/2024  Rent Payment           -$1,200.00   Balance: $13,317.64
        01/20/2024  Freelance Payment      +$1,350.00   Balance: $14,667.64
        01/25/2024  Grocery Store            -$63.99    Balance: $14,603.65
        01/28/2024  Interest Deposit          +$0.01     Balance: $14,603.66
        
        ACCOUNT FEATURES
        - Interest Rate: 0.02% APY
        - No monthly maintenance fee
        - Free transfers to linked accounts
        - FDIC insured up to $250,000
        
        Questions? Contact support@bank.com or call 1-800-BANKING
        """)
    
    metadata = {
        "document_type": "transaction_statement",
        "financial_product": "Checking Account",
        "expected_entities": [
            "Emily Rodriguez",
            "4567-8901-2345-6789",
            "$12,450.32",
            "$3,850.00",
            "$2,145.67",
            "$14,154.65",
            "January 1-31, 2024",
        ],
        "expected_entity_types": ["Person", "AccountNumber", "Money", "Date"],
        "expected_relationships": [
            ("Emily Rodriguez", "4567-8901-2345-6789", "account_holder"),
        ],
    }
    
    return BenchmarkDataset(
        domain="financial",
        complexity="simple",
        text=text,
        metadata=metadata,
    )


def _load_financial_medium() -> BenchmarkDataset:
    """Medium financial document (~2K tokens): Investment portfolio report."""
    text = textwrap.dedent("""\
        INVESTMENT PORTFOLIO QUARTERLY REPORT
        
        Client: David Patel and Priya Patel
        Account Manager: Jennifer Walsh, CFP®
        Portfolio Manager: Goldman Sachs Asset Management
        Reporting Period: Q4 2023 (October 1 - December 31, 2023)
        Report Date: January 15, 2024
        
        PORTFOLIO SUMMARY
        
        Beginning Market Value (Oct 1):        $1,250,000.00
        Contributions During Period:              $50,000.00
        Investment Gains/(Losses):                $87,350.25
        Ending Market Value (Dec 31):         $1,387,350.25
        
        Total Return (Quarter):                     7.5%
        YTD Return 2023:                           15.2%
        3-Year Annualized Return:                 8.1%
        
        ASSET ALLOCATION
        
        Equities (65%):                         $901,777.66
        - U.S. Large Cap (35%):   $485,372.59
          - SPY (S&P 500 ETF):                 $245,000.00
          - MSFT (Microsoft):                  $125,000.00
          - AAPL (Apple):                      $115,372.59
        - U.S. Mid Cap (15%):     $207,857.54
          - MDYG (iShares Core S&P Mid-Cap):  $207,857.54
        - Emerging Markets (10%): $139,238.36
          - IEMG (iShares MSCI EAFE):         $139,238.36
        - International (5%):      $69,308.77
          - IEFA (iShares Core Developed):    $69,308.77
        
        Fixed Income (30%):                     $416,205.08
        - Bonds Investment Grade (25%):        $346,837.56
          - BND (Total US Bond):              $180,000.00
          - LQD (Investment Grade):           $166,837.56
        - High Yield Bonds (5%):   $69,367.51
          - HYG (iShares High Yield):         $69,367.51
        
        Cash & Equivalents (5%):                 $69,367.51
        - Money Market Fund:                     $40,000.00
        - Treasury Bill (3-month):               $29,367.51
        
        PERFORMANCE ATTRIBUTION
        
        Contribution by Asset Class:
        - Equities:        +$68,200.15   (78% of gains)
        - Fixed Income:    +$15,300.00   (17% of gains)
        - Cash:              +$1,850.10    (2% of gains)
        - Fees & Expenses:   -$2,000.00   (-2% adjustment)
        
        TRANSACTIONS DURING PERIOD
        
        10/10/2023   Contribution (wire transfer):    +$50,000.00
        10/15/2023   Rebalancing: Bought MSFT:       -$125,000.00
        10/15/2023   Rebalancing: Sold VTSAX:        +$120,000.00
        11/01/2023   Dividend reinvestment (SPY):     +$1,245.30
        11/15/2023   Dividend reinvestment (BND):       +$875.50
        12/15/2023   Quarterly distribution (HYG):    +$1,230.45
        
        FEES & EXPENSES
        
        Advisory Fee (0.60%):                  -$6,900.00
        Custodian Fee (0.05%):                   -$575.00
        Mutual Fund Expense Ratios:            -$920.00
        ETF Expense Ratios:                    -$405.00
        Total Fees Charged:                  -$8,800.00
        
        Performance vs. Benchmarks:
        Total Portfolio (7.5%) vs. 60/40 Blend (6.8%): Outperformance: 0.7%
        Equity Portion (8.2%) vs. S&P 500 (8.1%): Outperformance: 0.1%
        Fixed Income (3.5%) vs. Bloomberg Agg (4.2%): Underperformance: -0.7%
        
        RECOMMENDATIONS
        
        1. Consider increasing international equity allocation to recommended 20% from current 15%
        2. Weight-based rebalancing recommended in Q1 2024 (target: 65/30/5 split)
        3. Review tax-loss harvesting opportunities before year-end
        4. Maintain emergency fund of 6-12 months expenses in cash (currently 5%)
        
        Report Prepared By:
        Jennifer Walsh, CFP®
        Senior Investment Advisor
        Wealth Management Division
        Client Services: 1-800-WEALTH-1
        
        Disclaimer: This report is for informational purposes only and does not constitute
        investment advice. Actual results may differ from projections. Past performance does
        not guarantee future results.
        """)
    
    metadata = {
        "document_type": "portfolio_report",
        "financial_product": "Investment Account",
        "expected_entities": [
            "David Patel",
            "Priya Patel",
            "Jennifer Walsh",
            "Goldman Sachs",
            "$1,250,000.00",
            "$1,387,350.25",
            "Q4 2023",
            "MSFT",
            "AAPL",
            "SPY",
        ],
        "expected_entity_types": ["Person", "Company", "Money", "Date", "StockTicker"],
        "expected_relationships": [
            ("David Patel", "jennifer walsh", "client_of"),
            ("Priya Patel", "jennifer walsh", "client_of"),
        ],
    }
    
    return BenchmarkDataset(
        domain="financial",
        complexity="medium",
        text=text,
        metadata=metadata,
    )


def _load_financial_complex() -> BenchmarkDataset:
    """Complex financial document (~5K tokens): M&A transaction document."""
    text = textwrap.dedent("""\
        CONFIDENTIAL MERGER & ACQUISITION AGREEMENT
        
        AGREEMENT AND PLAN OF REORGANIZATION
        
        Agreement dated as of March 1, 2024, among:
        
        1. NORTHSTAR TECHNOLOGY HOLDINGS, INC., a Delaware corporation ("Acquirer")
        2. VANTAGE ANALYTICS SYSTEMS, INC., a Delaware corporation ("Target")
        3. MICHAEL CHEN and SUSAN ROBINSON, as representatives ("Stockholder Representatives")
        
        RECITALS
        
        WHEREAS, the Board of Directors of Acquirer has approved this Agreement and the merger
        contemplated hereby, and determined that such merger is in the best interests of Acquirer
        and its stockholders;
        
        WHEREAS, the Board of Directors of Target has approved this Agreement and has determined
        that this Agreement and the merger are fair to, and in the best interests of, the Target
        and its stockholders;
        
        WHEREAS, the stockholders of both Acquirer and Target have approved this Agreement as
        required by law and their respective corporate bylaws;
        
        NOW, THEREFORE, in consideration of the mutual covenants and agreements herein contained:
        
        ARTICLE 1 - THE MERGER
        
        1.1 Merger
        Upon the terms and conditions set forth in this Agreement, and in accordance with the
        General Corporation Law of the State of Delaware, at the Effective Time (the "Merger"),
        Target shall merge with and into Acquirer, with Acquirer being the surviving corporation
        (the "Surviving Corporation"), and Target shall cease to exist.
        
        1.2 Certificate and Bylaws
        The Certificate of Incorporation of Acquirer, as in effect immediately prior to the
        Effective Time, shall be the Certificate of the Surviving Corporation. The Bylaws of
        Acquirer shall be the Bylaws of the Surviving Corporation.
        
        ARTICLE 2 - PURCHASE PRICE AND CONSIDERATION
        
        2.1 Purchase Price
        Acquirer shall pay the Target stockholders and stakeholders an aggregate purchase price
        of Eight Hundred Fifty Million U.S. Dollars ($850,000,000.00) (the "Base Purchase Price").
        
        Payment shall be made as follows:
        (a) Cash at Closing: $600,000,000.00
        (b) Acquirer Stock: 5,000,000 shares valued at $50.00/share = $250,000,000.00
        
        2.2 Adjustments to Purchase Price
        
        2.2.1 Working Capital Adjustment
        The purchase price shall be adjusted dollar-for-dollar based on closing net working capital:
        
        Target Operating Statement (as of Feb 28, 2024):
        - Current Assets:             $125,000,000
        - Current Liabilities:         $45,000,000
        - Assumed Debt:                $80,000,000
        Target Working Capital:         $  0,000,000
        
        Post-closing true-up applies within 90 days of closing. Target may escrow up to
        $25,000,000 as security for adjustment obligations.
        
        2.2.2 Earnout Provisions
        Additional payments based on 24-month performance:
        - If EBITDA 2025 > $180M:   +$50,000,000 earnout (paid 50% cash, 50% stock)
        - If EBITDA 2025 > $220M:   +$75,000,000 earnout (paid 75% cash, 25% stock)
        - If Revenue Growth > 35%:  +$25,000,000 earnout (all cash)
        
        Maximum earnout: $100,000,000 (if all conditions met)
        
        2.3 Payment Mechanics and Allocation
        
        Total Consideration to be allocated among stockholders as follows:
        
        Equity Holders:
        - Common stockholders (1,200,000 shares):           $520,000,000
        - Preferred Series A holders (400,000 shares):      $200,000,000
        - Preferred Series B holders (100,000 shares):       $50,000,000
        
        Management & Employee Options:
        - Unvested options conversion:                       $40,000,000
        - Fully accelerated at 1x velocity upon change of control
        
        Debt Holders:
        - Assumed Debt repayment:                           $80,000,000
        - Unamortized debt discount write-off:             -$20,000,000
        
        2.4 Escrow Arrangements
        - Escrow Agent: Bank of New York Mellon
        - Escrow Amount: $85,000,000 (10% of Base Purchase Price)
        - Escrow Period: 18 months post-closing
        - Holdback for indemnification claims and working capital adjustments
        - Stockholder Representative directed to handle claiming procedures
        
        ARTICLE 3 - CONDITIONS TO CLOSING
        
        3.1 Conditions Precedent
        The obligation to close is conditional upon:
        
        (a) Regulatory Approvals:
            - FTC Hart-Scott-Rodino Act filing and approval
            - Committee on Foreign Investment in the United States (CFIUS) clearance
            - ASPARA compliance review
            - State AG antitrust approval (if triggered over thresholds)
        
        (b) Third-Party Consents:
            - Top 10 Customer contracts (>$10M annual) transferability consents
            - Supplier agreements >$50M annually
            - Bank lender consents for debt assumption modifications
            - Landlord consents for material leases
        
        (c) Representations and Warranties:
            - All representations shall be true and correct in all material respects
            - No Material Adverse Effect (MAE) shall have occurred
            
        Definition of MAE: Any event, change, condition, or effect that, individually or
        in aggregate, materially adversely affects the business, assets, liabilities, or
        financial condition of Target, with exceptions for:
        - General economic conditions (unless disproportionate impact)
        - Industry-wide changes
        - Events in public knowledge
        
        (d) Financing:
            - Committed debt financing from Goldman Sachs (commitment obtained January 15, 2024)
            - $400M term facility at SOFR + 2.50% (mature 7 years)
            - $50M revolving credit facility ($10M commitment fee)
            - No financing conditions or material adverse changes trigger
        
        3.2 Closing Action Items
        Scheduled to occur at Wilmington, Delaware registered agent offices:
        
        Closing Date: 60 calendar days after last regulatory approval (or earlier by mutual consent)
        Outside Date: June 30, 2024 (automatic termination if closing hasn't occurred)
        
        ARTICLE 4 - REPRESENTATIONS AND WARRANTIES
        
        4.1 Target Representations (Seller Reps)
        
        4.1.1 Organization, Standing, and Authority
        - Target is a Delaware corporation, duly organized and valid
        - All authority and corporate power to execute this Agreement and perform obligations
        - This Agreement is the valid and binding obligation of Target, enforceable in accordance
        
        4.1.2 Capitalization
        - Authorized: 10M common, 2M Series A preference
        - Outstanding as of Feb 28, 2024:
          * Common: 1,200,000 shares
          * Series A: 400,000 shares
          * Series B: 100,000 shares
        - No other securities outstanding (preferred stock, warrants, conversion rights)
        - All shares validly issued, fully paid, non-assessable
        - No preemptive or anti-dilution rights
        
        4.1.3 Financial Information
        - Audited financial statements (prepared by Deloitte) as of December 31, 2023
          represent Target's financial position fairly in all material respects
        - Reviewed financial statements for Jan 31 and Feb 28, 2024 prepared by CFO
        - Year-to-date revenue: $142,000,000 (63% of $225M FY2023 revenue)
        - Operating EBITDA margin: 22% (target: 24%)
        - Cash on hand (excluding restricted): $50,000,000
        - No off-balance-sheet liabilities beyond operating leases $25M annually
        
        4.1.4 Intellectual Property
        - Target owns or validly licenses all IP material to its operations:
          * Patents: 47 US patents, 23 international patents (all in good standing)
          * Trademarks: 12 registered marks (US, EU, APAC)
          * Copyrights: All software and source code owned by Target
          * Trade Secrets: Following reasonable security procedures
        - No pending IP litigation or challenges
        - All employee IP assignment agreements in place
        - Third-party licenses material to operations identified in Schedule 4.1.4B
        
        4.1.5 Material Contracts
        - Top 10 customers represent $420M sales (59% of annual revenue)
          - Customer 1 Pharma Corp: $120M (contract expires 12/31/2025, auto-renews)
          - Customer 2 Bank Holdings: $85M (contract expires 6/30/2026)
          - Customer 3 Insurance Coop: $75M (contract expires 3/31/2026, termination for convenience 30 days notice)
        - Supplier concentration < 5% any single supplier
        - Financing arrangements with Wells Fargo ($80M credit facility)
        
        4.1.6 Litigation and Compliance
        - No pending or threatened litigation>$1M
        - No agency investigations or pending regulatory actions
        - Full compliance with SOX, securities laws, FCPA, antitrust regulations
        - No environmental liabilities exceeding $5M estimated remediation
        - All employee classifications correct (wages, benefits, tax withholding)
        - All data privacy agreements comply with GDPR, CCPA (Privacy Officer: Sarah Chen)
        
        4.2 Acquirer Representations (Buyer Reps)
        
        4.2.1 Authority and Standing
        - Acquirer has full authority to execute this Agreement
        - Financing is committed and not subject to conditions
        - Board approval obtained March 1, 2024
        - Stockholder vote: 87.3% approval (March 15, 2024 shareholder meeting)
        
        4.2.2 Financial Capacity
        - Committed financing for full purchase price and closing costs
        - Access to $600M cash (confirmed by Goldman Sachs commitment letter, dated January 15)
        - No material adverse change in financial condition since financing commitment
        
        ARTICLE 5 - COVENANTS AND OBLIGATIONS
        
        5.1 Conduct of Target Business
        Target shall operate in ordinary course consistent with past practice until Closing:
        
        (a) No extraordinary capital expenditures (>$10M annual maintenance budget without consent)
        (b) Sales and compensation within published salary plans (no outside hired at >15% premium)
        (c) No new debt beyond operating credit, no guarantees
        (d) No dividend payments or other distributions
        (e) Maintain insurance (no cancellations without replacement)
        (f) Not to acquire businesses or dispose of material assets
        (g) Preserve use of data, trade secrets, business relationships
        
        5.2 Regulatory and Third-Party Approvals
        
        5.2.1 HSR Filing
        - Acquirer shall file Hart-Scott-Rodino Act notice with FTC/DOJ within 5 business days
        - Fee: $525,000 (Acquirer responsibility)
        - Both parties cooperate in responding to information requests
        - Estimated decision timeline: 30-day initial review period
        
        5.2.2 CFIUS Filing
        - Review required due to technology sensitivity (data analytics sector)
        - Estimated 45-day review period
        - Acquirer maintains control of strategic technology (IP compartmentalization)
        
        5.2.3 Customer/Supplier Consents
        - Target responsible for identifying material consents needed
        - Acquirer to sign required customer comfort letters
        
        5.3 Representations Survival
        - Reps survive closing 18 months (indemnification period)
        - Fundamental reps (authority, ownership) survive 24 months
        - Fraud survival period: 3 years (no cap)
        - Individual claim threshold: $50,000 (basket)
        - Aggregate claim threshold: $2,000,000 (deductible)
        - Cap on liability: $100,000,000 (70% of purchase price)
        
        ARTICLE 6 - INDEMNIFICATION
        
        6.1 Indemnification by Target
        Target (through Stockholder Representatives) shall indemnify Acquirer against:
        
        (a) Breach of any Target representation or warranty
        (b) Failure to comply with Target covenants
        (c) Excluded liabilities (pre-closing taxes, undisclosed litigation, environmental)
        (d) Assumed debt payments
        (e) Employee-related claims (pre-closing period)
        
        Claim procedures require written notice within 30 days of discovery (but not exceeding
        rep survival period), opportunity for Target to defend/settle, and cooperation.
        
        6.2 Indemnification by Acquirer
        Acquirer shall indemnify Target stockholders for assumed liabilities and Acquirer's
        breach of representations or covenants.
        
        ARTICLE 7 - TERMINATION
        
        7.1 Grounds for Termination
        
        Either party may terminate if:
        - Regulatory approval is denied or conditioned in material manner
        - Outside date (June 30, 2024) passes without closing
        - Closing conditions cannot be satisfied by outside date
        - Other party materially breaches and fails to cure within 20 days
        - Mutual written consent
        
        Target may terminate for Acquirer failure to:
        - Secure financing (Financing Condition waived by Acquirer - cannot assert)
        - Appear to proceed with closing in good faith
        
        7.2 Termination Fees and Reverse Termination Fees
        
        If Acquirer terminates without cause or due to Financing Failure:
        - Reverse Termination Fee: $50,000,000 (6% of equity consideration)
        - Payment due within 5 business days
        
        If Target terminates for Superior Proposal:
        - Termination Fee: $30,000,000 (4% of equity consideration) to Acquirer
        - Applies only if Target solicited superior bids
        
        ARTICLE 8 - CLOSING AND POST-CLOSING
        
        8.1 Closing Date Requirements
        
        At closing:
        - Deliver share certificates/book-entry transfers to Acquirer
        - Execute assumption agreements for Target contracts/liabilities
        - Deliver officer certificates re-confirming reps and warranties
        - Deliver legal opinions, financing documentation, insurance representations
        - Employees notified; unvested awards accelerated
        - Key employee retention agreements executed (see Schedule 8.1D)
        
        8.2 Post-Closing Conduct
        
        (a) Integration - Acquirer to integrate Target within 12 months (transition services agreement)
        (b) Benefits - Target employees receive enhanced severance package (1.5x standard)
        (c) Trademarks - Target brand maintained for 24 months in customer communications
        (d) Management - Acquisition President position offered to Target COO David Martinez
        
        8.3 Transition Services
        - Acquirer to provide certain services for 90 days (data center, HR, finance)
        - Fee: $500,000/month; reimbursable costs additional
        - Services detailed in Schedule 8.3
        
        ARTICLE 9 - GENERAL PROVISIONS
        
        9.1 Governing Law and Jurisdiction
        This Agreement shall be governed by Delaware law and enforced in Delaware Chancery Court.
        
        9.2 Amendment and Waiver
        Amendments require written consent of all parties. No waiver unless in writing signed
        by waiving party.
        
        9.3 Entire Agreement
        This Agreement, together with Exhibits and Schedules, constitutes entire agreement and
        supersedes all prior negotiations, understandings, and agreements.
        
        9.4 Confidentiality
        All terms remain confidential except:
        - To parties' legal counsel, accountants, lenders, stockholders (who must agree to confidentiality)
        - Public announcement permitted after closing
        - Required SEC filings, regulatory submissions, or legal proceedings
        
        AUTHORIZED SIGNATURES:
        
        NORTHSTAR TECHNOLOGY HOLDINGS, INC.
        By: _____________________________
        Name: Richard Martinez
        Title: Chief Executive Officer
        Date: March 1, 2024
        
        VANTAGE ANALYTICS SYSTEMS, INC.
        By: _____________________________
        Name: Andrew Foster
        Title: Chief Executive Officer
        Date: March 1, 2024
        
        STOCKHOLDER REPRESENTATIVES:
        By: _____________________________
        Name: Michael Chen
        Date: March 1, 2024
        
        By: _____________________________
        Name: Susan Robinson
        Date: March 1, 2024
        """)
    
    metadata = {
        "document_type": "merger_agreement",
        "financial_product": "M&A Transaction",
        "expected_entities": [
            "Northstar Technology Holdings",
            "Vantage Analytics Systems",
            "Michael Chen",
            "Susan Robinson",
            "Goldman Sachs",
            "Delaware",
            "$850,000,000",
            "$600,000,000",
            "Richard Martinez",
            "Andrew Foster",
        ],
        "expected_entity_types": ["Organization", "Person", "Location", "Money"],
        "expected_relationships": [
            ("Richard Martinez", "Northstar Technology Holdings", "ceo"),
            ("Andrew Foster", "Vantage Analytics Systems", "ceo"),
        ],
    }
    
    return BenchmarkDataset(
        domain="financial",
        complexity="complex",
        text=text,
        metadata=metadata,
    )


# ============================================================================
# Dataset Loader Registry
# ============================================================================

_DATASET_LOADERS = {
    ("legal", "simple"): _load_legal_simple,
    ("legal", "medium"): _load_legal_medium,
    ("legal", "complex"): _load_legal_complex,
    ("medical", "simple"): _load_medical_simple,
    ("medical", "medium"): _load_medical_medium,
    ("medical", "complex"): _load_medical_complex,
    ("technical", "simple"): _load_technical_simple,
    ("technical", "medium"): _load_technical_medium,
    ("technical", "complex"): _load_technical_complex,
    ("financial", "simple"): _load_financial_simple,
    ("financial", "medium"): _load_financial_medium,
    ("financial", "complex"): _load_financial_complex,
}
