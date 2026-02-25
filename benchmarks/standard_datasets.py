"""Standard benchmark datasets for reproducible GraphRAG performance testing.

Provides curated test cases across multiple domains with known characteristics
(token counts, expected entity counts, complexity levels). Use these datasets
to ensure benchmark consistency across time and environments.

Domains:
- Legal: Employment law, contracts, case summaries
- Medical: Patient notes, clinical trials, research papers
- Business: Org charts, financial reports, product descriptions
- Technical: API docs, system architectures, code repositories
- News: Press releases, investigative journalism, breaking news

Each dataset includes:
- Text content
- Expected entity count (±10% tolerance)
- Expected relationship count (±15% tolerance)
- Token count (approximate, using tiktoken gpt-4 encoding)
- Complexity level (simple, moderate, complex)
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class Domain(str, Enum):
    """Dataset domain categories."""
    LEGAL = "legal"
    MEDICAL = "medical"
    BUSINESS = "business"
    TECHNICAL = "technical"
    NEWS = "news"
    GENERAL = "general"


class Complexity(str, Enum):
    """Text complexity levels."""
    SIMPLE = "simple"  # <10 entities, <15 relationships, clear structure
    MODERATE = "moderate"  # 10-30 entities, 15-50 relationships, some ambiguity
    COMPLEX = "complex"  # >30 entities, >50 relationships, high ambiguity


@dataclass
class BenchmarkDataset:
    """A single benchmark dataset with expected results."""
    
    name: str
    domain: Domain
    text: str
    complexity: Complexity
    approx_tokens: int
    expected_entities: int
    expected_relationships: int
    description: str
    entity_tolerance: float = 0.10  # ±10%
    relationship_tolerance: float = 0.15  # ±15%


# ============================================================================
# LEGAL DOMAIN DATASETS
# ============================================================================

LEGAL_EMPLOYMENT_SIMPLE = BenchmarkDataset(
    name="legal_employment_simple",
    domain=Domain.LEGAL,
    complexity=Complexity.SIMPLE,
    approx_tokens=150,
    expected_entities=6,
    expected_relationships=8,
    description="Simple employment agreement excerpt",
    text="""
EMPLOYMENT AGREEMENT

This Employment Agreement ("Agreement") is entered into on January 15, 2024, 
between TechCorp Inc. ("Employer"), a Delaware corporation, and Jane Smith 
("Employee"), an individual residing in California.

The Employee shall serve as Senior Software Engineer reporting to the 
VP of Engineering, Alice Johnson. The Employee's annual base salary shall 
be $150,000, payable bi-weekly.

The term of this Agreement shall commence on February 1, 2024, and continue 
until terminated in accordance with Section 8. Either party may terminate 
this Agreement with 30 days written notice.
""",
)

LEGAL_CONTRACT_MODERATE = BenchmarkDataset(
    name="legal_contract_moderate",
    domain=Domain.LEGAL,
    complexity=Complexity.MODERATE,
    approx_tokens=400,
    expected_entities=15,
    expected_relationships=25,
    description="Software licensing agreement with multiple parties",
    text="""
SOFTWARE LICENSE AGREEMENT

This Software License Agreement ("Agreement") effective as of March 1, 2024,
is between DataSystems Corp ("Licensor"), a California corporation with 
principal offices at 123 Market St, San Francisco, CA 94102, and Global 
Finance Inc ("Licensee"), a New York corporation.

WHEREAS, Licensor has developed proprietary software known as "DataVault 
Enterprise Edition" (the "Software"); and WHEREAS, Licensee desires to 
license the Software for use in its financial operations;

NOW THEREFORE, the parties agree:

1. Grant of License: Licensor grants Licensee a non-exclusive, 
   non-transferable license to use the Software at up to 50 workstations.

2. License Fee: Licensee shall pay $100,000 annually, due on the anniversary 
   date. Payment shall be made to Licensor's account at Wells Fargo Bank.

3. Support: Licensor shall provide technical support through its Support Team,
   led by Michael Chen, Chief Support Engineer. Response time shall be 4 hours
   for critical issues and 24 hours for non-critical issues.

4. Restrictions: Licensee shall not reverse engineer, decompile, or 
   disassemble the Software. Licensee may not sublicense the Software to 
   any third party without prior written consent from Licensor's Legal 
   Department, headed by Sarah Williams, General Counsel.

5. Term: Initial term is 3 years, automatically renewing for successive 
   1-year periods unless either party provides 90 days written notice.

Authorized signatories:
- For Licensor: David Park, CEO, DataSystems Corp
- For Licensee: Jennifer Martinez, CFO, Global Finance Inc
""",
)

# ============================================================================
# MEDICAL DOMAIN DATASETS
# ============================================================================

MEDICAL_CLINICAL_NOTE_SIMPLE = BenchmarkDataset(
    name="medical_clinical_note_simple",
    domain=Domain.MEDICAL,
    complexity=Complexity.SIMPLE,
    approx_tokens=180,
    expected_entities=8,
    expected_relationships=10,
    description="Simple patient clinical note",
    text="""
PATIENT CLINICAL NOTE

Patient: John Doe (MRN: 123456)
Date: 2024-02-15
Provider: Dr. Sarah Johnson, MD (Internal Medicine)

Chief Complaint: Persistent headache for 2 weeks.

History of Present Illness:
Patient reports onset of frontal headaches 14 days ago. Pain is 6/10 severity,
worse in the morning, relieved by ibuprofen. No visual changes, nausea, or fever.

Past Medical History:
- Hypertension (diagnosed 2018), controlled on Lisinopril 10mg daily
- Type 2 Diabetes (diagnosed 2020), managed by Dr. Robert Lee (Endocrinology)

Physical Examination:
Blood pressure 135/82, pulse 72, temperature 98.6°F. 
Neurological exam normal.

Assessment & Plan:
1. Tension headache - likely stress-related
2. Continue current medications
3. Follow-up in 2 weeks
4. Refer to Neurology (Dr. Emily Chen) if symptoms persist
""",
)

MEDICAL_TRIAL_COMPLEX = BenchmarkDataset(
    name="medical_trial_complex",
    domain=Domain.MEDICAL,
    complexity=Complexity.COMPLEX,
    approx_tokens=600,
    expected_entities=35,
    expected_relationships=55,
    description="Clinical trial design with multiple arms and endpoints",
    text="""
CLINICAL TRIAL PROTOCOL: NCT05234567

Title: Phase III Randomized Double-Blind Trial of Drug XYZ-101 versus 
Placebo for Treatment of Moderate to Severe Rheumatoid Arthritis

Principal Investigator: Dr. Amanda Rodriguez, MD, PhD
Co-Investigators: Dr. Michael Chang (Rheumatology), Dr. Lisa Thompson (Biostatistics)
Sponsor: BioPharma Solutions Inc.
CRO: Clinical Research Associates LLC

Study Design:
- 500 patients randomized 1:1 to XYZ-101 (250mg twice daily) or placebo
- 24-week treatment period with 12-week follow-up
- Multi-center: 25 sites across USA, Canada, and Europe
- Stratified by disease severity (DAS28 score) and prior biologic use

Key Inclusion Criteria:
- Age 18-75 years
- Diagnosis of RA per ACR/EULAR 2010 criteria for ≥6 months
- DAS28-ESR ≥3.2 at screening
- Inadequate response to methotrexate (15-25mg/week)

Key Exclusion Criteria:
- Prior exposure to JAK inhibitors (tofacitinib, baricitinib, upadacitinib)
- Active infection or history of tuberculosis
- Hepatic impairment (ALT/AST >2x ULN)
- Estimated GFR <40 mL/min/1.73m²

Primary Endpoint:
ACR20 response at Week 12 (defined as ≥20% improvement in tender and 
swollen joint counts plus ≥20% improvement in 3 of 5 additional measures)

Secondary Endpoints:
1. ACR50 and ACR70 response at Week 12 and Week 24
2. Change from baseline in DAS28-ESR at Weeks 4, 8, 12, 24
3. HAQ-DI score change at Week 24
4. Radiographic progression (modified Total Sharp Score) at Week 24
5. Duration to first ACR20 response

Safety Assessments:
- Adverse events monitored by Safety Committee (Dr. James Wilson, chair)
- Laboratory monitoring: CBC, CMP, lipids at baseline and Weeks 4, 12, 24
- Serious infections reviewed by Independent Data Monitoring Committee
- Integration with FDA FAERS database via safety coordinator Karen Smith

Statistical Analysis:
- Sample size: 250 per arm (90% power, alpha=0.05) to detect 15% difference
- Primary analysis: Chi-square test for ACR20 at Week 12
- Secondary analyses: Mixed-effects models for continuous endpoints
- Interim analysis at 50% enrollment (reviewed by IDMC)
- Statistician: Dr. Lisa Thompson, collaborating with Dr. Robert Kim (Stanford)

Key Collaborators:
- Imaging Core Lab: Dr. Peter Anderson, Johns Hopkins University
- Central Laboratory: Quest Diagnostics (contact: Dr. Maria Garcia)
- Pharmacokinetics: Dr. Sophia Lee, Clinical Pharmacology Associates
- Patient Advocacy: Arthritis Foundation (liaison: Nancy Davis)
""",
)

# ============================================================================
# BUSINESS DOMAIN DATASETS
# ============================================================================

BUSINESS_ORGCHART_MODERATE = BenchmarkDataset(
    name="business_orgchart_moderate",
    domain=Domain.BUSINESS,
    complexity=Complexity.MODERATE,
    approx_tokens=320,
    expected_entities=18,
    expected_relationships=22,
    description="Corporate organization chart with departments",
    text="""
TECHCORP INC. - ORGANIZATIONAL STRUCTURE (Q1 2024)

Executive Leadership:
- CEO: Jennifer Martinez (reports to Board of Directors)
- COO: David Kim (reports to CEO)
- CFO: Lisa Anderson (reports to CEO)
- CTO: Michael Chen (reports to CEO)

Engineering Division (under CTO Michael Chen):
- VP Engineering: Sarah Williams
  - Director of Backend: Robert Taylor (5 engineers)
  - Director of Frontend: Emily Johnson (4 engineers)
  - Director of DevOps: James Wilson (3 engineers)

Product Division (under COO David Kim):
- VP Product: Amanda Rodriguez
  - Senior PM - Enterprise: Kevin Lee
  - Senior PM - SMB: Nancy Davis
  - Product Designer: Maria Garcia

Finance & Operations (under CFO Lisa Anderson):
- Controller: Thomas Brown
- Finance Manager: Patricia Martinez
- HR Manager: Susan Miller (manages recruitment team of 2)

Sales & Marketing (under COO David Kim):
- VP Sales: Christopher Lee
  - Enterprise Sales Lead: Jessica Taylor (team of 6)
  - SMB Sales Lead: Daniel Park (team of 4)
- VP Marketing: Rebecca Johnson
  - Content Marketing Manager: Andrew Wilson
  - Growth Marketing Manager: Karen Smith

Notable Partnerships:
- TechCorp has a strategic partnership with DataSystems Inc (CEO: John Davis)
- Cloud infrastructure provided by AWS (account manager: Mark Thompson)
- Payment processing through Stripe (integration managed by Robert Taylor)
""",
)

BUSINESS_ACQUISITION_COMPLEX = BenchmarkDataset(
    name="business_acquisition_complex",
    domain=Domain.BUSINESS,
    complexity=Complexity.COMPLEX,
    approx_tokens=750,
    expected_entities=42,
    expected_relationships=68,
    description="M&A transaction with multiple parties and advisors",
    text="""
CONFIDENTIAL - ACQUISITION SUMMARY

Transaction: Acquisition of CloudTech Solutions, Inc. by Global Enterprise Corp.

Parties:
Acquirer: Global Enterprise Corp. (GEC)
- Headquarters: New York, NY
- CEO: Richard Anderson
- CFO: Laura Mitchell  
- General Counsel: David Park
- Corporate Development VP: Jennifer Lee

Target: CloudTech Solutions, Inc.
- Headquarters: Austin, TX
- Founded: 2015 by founders Emily Rodriguez and Michael Zhang
- CEO: Emily Rodriguez (founder, 45% equity)
- CTO: Michael Zhang (founder, 35% equity)
- CFO: Thomas Wilson (10% equity)
- Board: Emily Rodriguez, Michael Zhang, VC rep Sarah Chen (Sequoia Capital)

Financial advisors:
- GEC advised by Goldman Sachs (lead: James Patterson, MD)
- CloudTech advised by Morgan Stanley (lead: Lisa Thompson, MD)
- Fairness opinion from Lazard (prepared by Robert Kim, Managing Director)

Legal advisors:
- GEC: Wilson Sonsini Goodrich & Rosati
  - M&A lead: Partner Amanda Stevens
  - Tax lead: Partner Christopher Lee
- CloudTech: Cooley LLP
  - M&A lead: Partner Daniel Martinez
  - IP lead: Partner Karen Johnson

Due diligence teams:
- Financial DD: Deloitte (lead: Susan Miller, Partner)
  - Revenue verification team led by Kevin Brown, Senior Manager
  - EBITDA adjustments by Patricia Garcia, Manager
- Technical DD: Accenture (lead: Mark Wilson, Managing Director)
  - Architecture review by Dr. Nancy Davis, Principal
  - Security audit by Andrew Thompson, Senior Manager
- Legal DD: GEC internal team (senior counsel Rebecca Taylor)

Transaction terms:
- Purchase price: $250M (75% cash, 25% GEC stock)
- Cash component: $187.5M funded by:
  - $100M from GEC cash reserves
  - $87.5M bridge financing from JPMorgan Chase (lead: Peter Anderson, VP)
- Stock component: 625,000 shares GEC common stock (valued at $100/share)
- Earnout provision: up to $50M over 3 years based on revenue targets
  - Administered by escrow agent Wells Fargo (contact: Maria Lopez, AVP)

Key employees retention packages:
- Emily Rodriguez (CEO): 4-year retention as GM of Cloud Division
  - Reports to GEC COO Jessica Martinez
  - Retention bonus: $5M over 4 years
- Michael Zhang (CTO): 3-year retention as SVP Engineering
  - Reports to GEC CTO Robert Johnson
  - Retention bonus: $3M over 3 years

Integration team:
- Integration PMO lead: GEC Director Sarah Williams
- HR integration: Lisa Anderson (GEC) and Thomas Brown (CloudTech)
- IT systems integration: James Lee (GEC IT Director)
- Product roadmap alignment: Christopher Davis (GEC VP Product)

Regulatory and approvals:
- Hart-Scott-Rodino filing prepared by Wilson Sonsini (lead: Partner Amanda Stevens)
- Antitrust review coordination by FTC contact David Wilson, Assistant Director
- CFIUS filing (foreign investor consideration due to CloudTech investor 
  SoftBank via Partner Kenji Tanaka) - coordinated by Cooley (lead: Daniel Martinez)
- International filings: EU (DG Comp), UK (CMA), Canada (Competition Bureau)

Customer transition:
- Top 10 customers notified by Emily Rodriguez and Richard Anderson jointly
- Key accounts:
  - Acme Corp (CSM: Kevin Smith)
  - Global Finance Inc (CSM: Nancy Johnson)
  - StartupXYZ (CSM: Andrew Miller)

Employee communication:
- Town halls scheduled by HR leads Lisa Anderson and Susan Davis
- Equity compensation FAQ prepared by Finance teams
- Benefits transition managed by Mercer (consultant: Mark Garcia)

Timeline:
- Signing: April 1, 2024
- HSR clearance expected: June 2024 (antitrust counsel: Amanda Stevens)
- Closing target: July 15, 2024
- Integration complete: Q4 2024

Post-closing board composition:
- Richard Anderson (GEC CEO) - Chairman
- Laura Mitchell (GEC CFO)
- Jennifer Lee (GEC Corp Dev VP)
- Emily Rodriguez (CloudTech CEO) - Board observer
- Two independent directors: Dr. Robert Thompson (Stanford professor) 
  and Patricia Kim (former Oracle executive)
""",
)

# ============================================================================
# TECHNICAL DOMAIN DATASETS
# ============================================================================

TECHNICAL_API_SIMPLE = BenchmarkDataset(
    name="technical_api_simple",
    domain=Domain.TECHNICAL,
    complexity=Complexity.SIMPLE,
    approx_tokens=200,
    expected_entities=10,
    expected_relationships=12,
    description="REST API documentation excerpt",
    text="""
USER AUTHENTICATION API

The UserService provides authentication endpoints for the TechCorp platform.

Endpoint: POST /api/v2/auth/login
Authentication: None required
Request body:
{
  "email": "user@example.com",
  "password": "encrypted_password"
}

Response (200 OK):
{
  "user_id": "uuid",
  "access_token": "jwt_token",
  "refresh_token": "refresh_jwt",
  "expires_in": 3600
}

The access_token should be included in subsequent requests as Bearer token 
in the Authorization header. Tokens are managed by the TokenService and 
stored in Redis for fast validation.

Endpoint: POST /api/v2/auth/refresh
Authentication: Bearer refresh_token

Response (200 OK):
{
  "access_token": "new_jwt_token",
  "expires_in": 3600
}

Error codes:
- 401: Invalid credentials (handled by AuthenticationMiddleware)
- 429: Rate limit exceeded (managed by RateLimitService)
- 500: Internal server error (logged to ErrorTrackingService)

Dependencies:
- Database: PostgreSQL (managed by DatabaseConnectionPool)
- Cache: Redis Cluster (managed by CacheService)
- Logging: Datadog APM (configured by MonitoringService)
""",
)

# ============================================================================
# NEWS DOMAIN DATASETS
# ============================================================================

NEWS_PRESS_RELEASE_SIMPLE = BenchmarkDataset(
    name="news_press_release_simple",
    domain=Domain.NEWS,
    complexity=Complexity.SIMPLE,
    approx_tokens=180,
    expected_entities=9,
    expected_relationships=11,
    description="Simple corporate press release",
    text="""
FOR IMMEDIATE RELEASE

TechCorp Announces Partnership with DataSystems Inc.

SAN FRANCISCO, CA - March 15, 2024 - TechCorp Inc., a leading provider of 
cloud-based data solutions, today announced a strategic partnership with 
DataSystems Inc. to deliver enhanced analytics capabilities to enterprise 
customers.

Under the partnership, TechCorp's CloudSync platform will integrate with 
DataSystems' DataVault Enterprise Edition, enabling customers to securely 
synchronize and analyze data across multiple cloud environments.

"This partnership represents a significant milestone for TechCorp," said 
Jennifer Martinez, CEO of TechCorp. "By combining our synchronization 
technology with DataSystems' analytics capabilities, we're delivering 
unprecedented value to our customers."

The integration is expected to launch in Q2 2024, with early access available 
to select enterprise customers including Acme Corp and Global Finance Inc.

About TechCorp:
TechCorp Inc. is a San Francisco-based technology company founded in 2015. 
The company serves over 500 enterprise customers globally.

About DataSystems:
DataSystems Inc., headquartered in Austin, TX, provides enterprise data 
analytics solutions. CEO David Park founded the company in 2012.

Media Contact:
Sarah Williams, VP Marketing, TechCorp
sarah.williams@techcorp.com
""",
)

# ============================================================================
# DATASET REGISTRY
# ============================================================================

ALL_DATASETS = [
    # Legal
    LEGAL_EMPLOYMENT_SIMPLE,
    LEGAL_CONTRACT_MODERATE,
    
    # Medical
    MEDICAL_CLINICAL_NOTE_SIMPLE,
    MEDICAL_TRIAL_COMPLEX,
    
    # Business
    BUSINESS_ORGCHART_MODERATE,
    BUSINESS_ACQUISITION_COMPLEX,
    
    # Technical
    TECHNICAL_API_SIMPLE,
    
    # News
    NEWS_PRESS_RELEASE_SIMPLE,
]


def get_dataset(name: str) -> Optional[BenchmarkDataset]:
    """Get dataset by name.
    
    Args:
        name: Dataset name (e.g., "legal_employment_simple")
        
    Returns:
        BenchmarkDataset or None if not found
    """
    for dataset in ALL_DATASETS:
        if dataset.name == name:
            return dataset
    return None


def get_datasets_by_domain(domain: Domain) -> List[BenchmarkDataset]:
    """Get all datasets for a specific domain.
    
    Args:
        domain: Domain to filter by
        
    Returns:
        List of benchmark datasets
    """
    return [ds for ds in ALL_DATASETS if ds.domain == domain]


def get_datasets_by_complexity(complexity: Complexity) -> List[BenchmarkDataset]:
    """Get all datasets with specific complexity.
    
    Args:
        complexity: Complexity level to filter by
        
    Returns:
        List of benchmark datasets
    """
    return [ds for ds in ALL_DATASETS if ds.complexity == complexity]


if __name__ == "__main__":
    """Print dataset catalog."""
    print("=" * 70)
    print("STANDARD BENCHMARK DATASETS CATALOG")
    print("=" * 70)
    print()
    
    by_domain = {}
    for dataset in ALL_DATASETS:
        by_domain.setdefault(dataset.domain, []).append(dataset)
    
    for domain, datasets in sorted(by_domain.items()):
        print(f"\n{domain.value.upper()} ({len(datasets)} datasets):")
        print("-" * 70)
        
        for ds in datasets:
            print(f"\n  {ds.name}")
            print(f"  Complexity: {ds.complexity.value}")
            print(f"  Tokens: ~{ds.approx_tokens}")
            print(f"  Expected: {ds.expected_entities} entities, {ds.expected_relationships} relationships")
            print(f"  Description: {ds.description}")
    
    print(f"\n{'='*70}")
    print(f"Total: {len(ALL_DATASETS)} datasets")
    print("=" * 70)
