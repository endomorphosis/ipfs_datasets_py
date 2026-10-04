"""Standard benchmark datasets for GraphRAG optimization testing

Provides 8 curated datasets across 4 domains (legal, medical, technical, general)
for consistent and reproducible benchmarking.
"""

from .benchmark_harness import BenchmarkDataset, DataDomain


# LEGAL DOMAIN

LEGAL_CONTRACT_EXCERPT = BenchmarkDataset(
    domain=DataDomain.LEGAL,
    name="Legal Contract Excerpt",
    description="Standard commercial contract with multiple parties and obligations",
    texts=[
        "AGREEMENT BETWEEN COMPANY A AND COMPANY B. This comprehensive Agreement is entered into on January 15, 2024, "
        "between Company A (hereinafter 'Service Provider') and Company B (hereinafter 'Client'). "
        "Service Provider agrees to provide comprehensive consulting services as outlined in Exhibit A attached hereto. "
        "Client agrees to pay Service Provider a monthly retainer of $10,000 USD plus reasonable expenses. "
        "All services shall be performed in accordance with industry standards and best practices. "
        "The term of this agreement shall be for one (1) year from the effective date, "
        "with automatic renewal unless terminated by either party with 30 days written notice. "
        "Service Provider shall maintain strict confidentiality of all Client information and proprietary data. "
        "Service Provider shall not disclose any Client information to third parties without prior written consent. "
        "Any disputes arising shall be governed by the laws of Delaware and resolved through binding arbitration. "
        "The arbitration shall be conducted by an impartial arbitrator selected from the American Arbitration Association. "
        "This Agreement constitutes the entire agreement between the parties and supersedes all prior negotiations. "
        "Neither party may assign this agreement without written consent. Modifications must be in writing and signed. "
        "Payment terms: Net 30 days from invoice date. Late payments accrue interest at 1.5% per month. "
        "Service Provider provides basic liability insurance of $1M. Client maintains professional liability insurance. "
        "Either party may terminate for cause with 15 days written notice if the other breaches material terms."
    ],
    expected_entity_count=15,
    expected_relationship_count=12,
    quality_baseline=0.72,
)


LEGAL_LITIGATION_SUMMARY = BenchmarkDataset(
    domain=DataDomain.LEGAL,
    name="Legal Litigation Summary",
    description="Summary of litigation case with claims, damages, and court proceedings",
    texts=[
        "CASE NO. 2023-CV-45678. Plaintiff John Smith filed suit against Defendant Tech Corp Inc. "
        "for alleged breach of contract and negligent misrepresentation. "
        "The Complaint alleges that Defendant promised to deliver software within 90 days "
        "but failed to deliver for 180 days, causing plaintiff damages of $500,000. "
        "Plaintiff also claims Defendant misrepresented the software capabilities and performance metrics. "
        "Specifically, Defendant represented the software could process 1 million transactions per second, "
        "but the actual performance was only 100,000 transactions per second. "
        "The product was also missing critical security features that were promised in the contract. "
        "The Court denied Defendant's motion to dismiss on all counts on September 1, 2023. "
        "Discovery is ongoing with both parties exchanging documents and conducting depositions. "
        "The case is scheduled for trial on September 1, 2024, in the Federal District Court. "
        "Defendant has filed a counterclaim for alleged non-payment of invoices totaling $150,000. "
        "Plaintiff disputes the counterclaim stating partial payment of $80,000 was already made. "
        "The remaining balance was allegedly withheld due to the product defects. "
        "Both parties have retained expert witnesses to testify regarding software capabilities. "
        "A settlement conference is scheduled for May 15, 2024, before Judge Patricia Martinez."
    ],
    expected_entity_count=12,
    expected_relationship_count=14,
    quality_baseline=0.68,
)


# MEDICAL DOMAIN

MEDICAL_DIAGNOSIS_REPORT = BenchmarkDataset(
    domain=DataDomain.MEDICAL,
    name="Medical Diagnosis Report",
    description="Clinical diagnosis report with symptoms, observations, and treatment plan",
    texts=[
        "PATIENT: Robert Johnson, DOB: 05/12/1965, Age: 58, Sex: Male. "
        "CHIEF COMPLAINT: Chest pain and shortness of breath for 3 days. "
        "HISTORY OF PRESENT ILLNESS: Patient reports onset of mild chest discomfort two weeks ago "
        "that has worsened to moderate substernal pain. Associated with dyspnea on exertion and diaphoresis. "
        "Pain is worse with activity and partially relieved by rest. Denies syncope or palpitations. "
        "PAST MEDICAL HISTORY: Hypertension (diagnosed 1998), Diabetes Type 2 (diagnosed 2010), "
        "High cholesterol (diagnosed 2005), GERD (diagnosed 2015). FAMILY HISTORY: Father had MI at age 62. "
        "MEDICATIONS: Lisinopril 10mg daily, Metformin 1000mg twice daily, Simvastatin 40mg daily, Ranitidine PRN. "
        "ALLERGIES: NKDA (No Known Drug Allergies). SOCIAL: Tobacco 1 pack-year, quit 5 years ago. "
        "PHYSICAL EXAMINATION: BP 148/92, HR 86, RR 20, Temp 98.6F, Weight 240 lbs. "
        "General: Obese male in mild distress. Cardiac exam: Regular rate and rhythm, no murmurs, S1 and S2 normal. "
        "Lungs: Clear bilaterally, no rales or wheezes. Extremities: No edema, pedal pulses 2+ bilaterally. "
        "Abdominal: Soft, obese, no rebound or guarding. ASSESSMENT: Acute coronary syndrome suspected. "
        "Rule out myocardial infarction. PLAN: Admit to cardiac telemetry unit for monitoring. "
        "EKG, Troponin levels, Chest X-ray ordered stat. Cardiology consult requested."
    ],
    expected_entity_count=18,
    expected_relationship_count=15,
    quality_baseline=0.70,
)


MEDICAL_PATHOLOGY_REPORT = BenchmarkDataset(
    domain=DataDomain.MEDICAL,
    name="Medical Pathology Report",
    description="Pathology lab results with specimen analysis and findings",
    texts=[
        "SPECIMEN: Tissue biopsy from right breast, upper outer quadrant. Case # P24-56789. "
        "CLINICAL INFORMATION: 62-year-old female presenting with palpable mass in right breast. "
        "Imaging: Mammography showed 2.5 cm irregular mass with microcalcifications. Ultrasound confirmed solid lesion. "
        "SPECIMEN DESCRIPTION: Received in formalin 4 tissue fragments, total dimensions 2.5 x 1.8 x 0.8 cm. "
        "Tan to white color, firm to hard consistency. Specimen submitted with appropriate demographic labels. "
        "MICROSCOPIC EXAMINATION: Sections show infiltrating ductal carcinoma with moderate differentiation. "
        "Nuclear grade 2 (Nottingham scale), prominent mitotic rate 8 per 10 high-power fields. "
        "Margins are involved bilaterally raising concerns for incomplete excision. No lymph node involvement identified. "
        "Estrogen receptor: Positive (90% of cells). Progesterone receptor: Positive (75% of cells). "
        "HER2: Negative (score 0 by immunohistochemistry). Ki-67 proliferation index: 25%. "
        "Lymphatic invasion: Present. Perineural invasion: Negative. DIAGNOSIS: Infiltrating Ductal Carcinoma with Nuclear Grade 2. "
        "STAGE: T2 N0 M0 (Stage IIA per AJCC 8th edition). RECOMMENDATION: Oncology consultation recommended. "
        "Consider adjuvant hormonal therapy and possible radiation therapy. Clinical correlation advised."
    ],
    expected_entity_count=16,
    expected_relationship_count=13,
    quality_baseline=0.71,
)


# TECHNICAL DOMAIN

TECHNICAL_SOFTWARE_ARCHITECTURE = BenchmarkDataset(
    domain=DataDomain.TECHNICAL,
    name="Technical Software Architecture",
    description="Software architecture documentation with components and data flow",
    texts=[
        "SOFTWARE ARCHITECTURE: Distributed Event-Driven System (Version 2.0). COMPONENTS: "
        "API Gateway (nginx) routes requests to one of three microservices: User Service, Product Service, Inventory Service. "
        "Each microservice is deployed independently and connects to its own PostgreSQL database for data persistence. "
        "A message queue (RabbitMQ) handles asynchronous communication between services ensuring eventual consistency. "
        "Cache layer (Redis) stores frequently accessed data with 15-minute TTL to reduce database load. "
        "Authentication handled by OAuth2 via external Identity Provider (Keycloak). "
        "All services implement circuit breaker pattern with Hystrix library for resilience. "
        "Monitoring and alerting via Prometheus collecting metrics from all services. "
        "Visualizations and dashboards in Grafana for real-time system observation. "
        "Deployment on Kubernetes cluster with auto-scaling based on CPU usage (target 70%). "
        "Data flows from API Gateway through message queue to downstream services for event sourcing. "
        "Service-to-service communication uses gRPC for low-latency interactions. "
        "API Gateway provides rate limiting (1000 req/sec) and request validation. "
        "Configuration management via Spring Cloud Config. Logging centralized with ELK stack."
    ],
    expected_entity_count=20,
    expected_relationship_count=18,
    quality_baseline=0.74,
)


TECHNICAL_DATABASE_SCHEMA = BenchmarkDataset(
    domain=DataDomain.TECHNICAL,
    name="Technical Database Schema",
    description="Database schema definition with tables, relationships, and constraints",
    texts=[
        "DATABASE: PostgreSQL 13+. SCHEMA: e_commerce. TABLE Users: id (BIGINT PRIMARY KEY AUTO INCREMENT), "
        "username (VARCHAR(255) UNIQUE NOT NULL), email (VARCHAR(255) UNIQUE NOT NULL), "
        "password_hash (VARCHAR(255) NOT NULL), created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP), "
        "updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP). "
        "TABLE Products: id (BIGINT PRIMARY KEY), product_name (VARCHAR(255) NOT NULL), "
        "category (ENUM: 'electronics', 'clothing', 'books'), price (DECIMAL(10,2) NOT NULL CHECK price > 0), "
        "stock_count (INTEGER DEFAULT 0), supplier_id (BIGINT FOREIGN KEY references Suppliers.id). "
        "TABLE Orders: id (BIGINT PRIMARY KEY), user_id (BIGINT FOREIGN KEY references Users.id), "
        "created_at (TIMESTAMP), status (ENUM: 'pending','shipped','delivered','cancelled'). "
        "TABLE OrderItems: id (BIGINT PRIMARY KEY), order_id (BIGINT FOREIGN KEY references Orders.id ON DELETE CASCADE), "
        "product_id (BIGINT FOREIGN KEY references Products.id), quantity (INTEGER NOT NULL CHECK quantity > 0), "
        "unit_price (DECIMAL(10,2) NOT NULL). TABLE Suppliers: id (BIGINT PRIMARY KEY), "
        "supplier_name (VARCHAR(255) NOT NULL), contact_email (VARCHAR(255)), phone (VARCHAR(20)). "
        "INDEXES: Users.username, Products.category, Orders.user_id, OrderItems.order_id. "
        "CONSTRAINTS: Foreign key integrity, CASCADE Delete on order items, CHECK constraints on prices.",
    ],
    expected_entity_count=14,
    expected_relationship_count=11,
    quality_baseline=0.76,
)


# GENERAL DOMAIN

GENERAL_NEWS_ARTICLE = BenchmarkDataset(
    domain=DataDomain.GENERAL,
    name="General News Article",
    description="News article with multiple locations, people, and events",
    texts=[
        "MAJOR EARTHQUAKE STRIKES PACIFIC REGION. A magnitude 7.8 earthquake struck off the coast "
        "of Japan at 2:15 AM JST on March 15, 2024, creating tsunami warnings across the Pacific region. "
        "The U.S. Geological Survey reported the epicenter was 120 miles northeast of Tokyo at a depth of 25 km. "
        "Japanese Prime Minister Yoshida Shigeru declared a state of emergency and activated the Self-Defense Forces. "
        "Authorities evacuated over 500,000 residents from coastal areas in Hokkaido and Honshu prefectures. "
        "The Pacific Tsunami Warning Center issued tsunami alerts for California, Hawaii, Alaska,  and other Pacific nations. "
        "Preliminary reports indicate 23 confirmed deaths and hundreds injured across affected regions. "
        "Train service was suspended throughout central and northern Japan affecting 5 million commuters. "
        "Power outages affected 2 million households across Tokyo and surrounding areas. International aid is being coordinated. "
        "The United Nations activated emergency protocols, French President confirmed support. "
        "American Red Cross deployed teams to assist with disaster relief efforts in Tokyo."
    ],
    expected_entity_count=13,
    expected_relationship_count=10,
    quality_baseline=0.65,
)


GENERAL_BIOGRAPHY = BenchmarkDataset(
    domain=DataDomain.GENERAL,
    name="General Biography",
    description="Biography of notable person with education, career, and achievements",
    texts=[
        "MARIE CURIE (1867-1934) was a Polish-born physicist and chemist who conducted pioneering research "
        "on radioactivity, fundamentally changing our understanding of atomic physics. She was born Maria Skipodowska "
        "in Warsaw, Poland, and later moved to Paris, France to pursue advanced education at the Sorbonne University. "
        "In Paris, she met Pierre Curie, a fellow physicist and scientist, and they married in 1895, collaborating on research. "
        "Together they discovered the elements polonium and radium in 1896-1898 through systematic chemical analysis. "
        "Marie became the first woman to win a Nobel Prize in 1903 for Physics, shared with Pierre Curie and Henri Becquerel. "
        "After Pierre's tragic death in a street accident in 1906, she took over his professorship at the Sorbonne, "
        "becoming the first female professor at the University of Paris. She won a second Nobel Prize in 1911 for Chemistry, "
        "making her the first person to win Nobel Prizes in two different scientific fields. "
        "She established the Radium Institute to advance research on radioactivity and its applications in medicine. "
        "Prolonged exposure to radiation affected her health significantly and she died of leukemia in 1934."
    ],
    expected_entity_count=14,
    expected_relationship_count=11,
    quality_baseline=0.66,
)


def get_all_datasets() -> list:
    """Get all 8 standard datasets"""
    return [
        LEGAL_CONTRACT_EXCERPT,
        LEGAL_LITIGATION_SUMMARY,
        MEDICAL_DIAGNOSIS_REPORT,
        MEDICAL_PATHOLOGY_REPORT,
        TECHNICAL_SOFTWARE_ARCHITECTURE,
        TECHNICAL_DATABASE_SCHEMA,
        GENERAL_NEWS_ARTICLE,
        GENERAL_BIOGRAPHY,
    ]


def get_datasets_by_domain(domain: DataDomain) -> list:
    """Get datasets filtered by domain"""
    all_datasets = get_all_datasets()
    return [d for d in all_datasets if d.domain == domain]
