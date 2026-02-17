"""
Complaint Type Registration

Provides convenience functions for registering different complaint types
with their specific keywords, patterns, and scoring models.
"""

from typing import Any, Dict, List, Optional
from .keywords import register_keywords
from .legal_patterns import register_legal_terms


def register_housing_complaint():
    """Register keywords and patterns for housing complaints."""
    # Already registered in keywords.py, but this allows for programmatic registration
    pass


def register_employment_complaint():
    """Register keywords and patterns for employment complaints."""
    # Already registered in keywords.py
    pass


def register_civil_rights_complaint():
    """Register keywords and patterns for civil rights complaints."""
    # Additional civil rights specific keywords
    register_keywords('complaint', [
        'police brutality', 'excessive force',
        'unlawful search', 'unlawful seizure',
        'first amendment', 'freedom of speech',
        'freedom of assembly', 'voting rights',
    ], complaint_type='civil_rights')


def register_consumer_complaint():
    """Register keywords and patterns for consumer protection complaints."""
    register_keywords('complaint', [
        'fraud', 'deception', 'misrepresentation',
        'unfair practice', 'deceptive practice',
        'false advertising', 'bait and switch',
        'warranty breach', 'consumer protection',
        'ftc', 'federal trade commission',
    ], complaint_type='consumer')
    
    register_legal_terms('consumer', [
        r'\b(fraud|fraudulent)\b',
        r'\b(deceptive (practice|trade))\b',
        r'\b(false advertising)\b',
        r'\b(consumer protection)\b',
        r'\b(ftc|federal trade commission)\b',
    ])


def register_healthcare_complaint():
    """Register keywords and patterns for healthcare complaints."""
    register_keywords('complaint', [
        'medical malpractice', 'negligence',
        'hipaa', 'medical privacy',
        'patient rights', 'informed consent',
        'emergency medical', 'emtala',
    ], complaint_type='healthcare')


def register_free_speech_complaint():
    """Register keywords and patterns for censorship and free speech complaints."""
    register_keywords('complaint', [
        # First Amendment
        'first amendment', 'free speech', 'freedom of speech',
        'freedom of expression', 'freedom of the press',
        'prior restraint', 'viewpoint discrimination',
        'content-based restriction', 'content-neutral',
        
        # Censorship
        'censorship', 'censor', 'censored',
        'suppression', 'silenced', 'deplatformed',
        'banned', 'suspension', 'account termination',
        
        # Social media / platforms
        'content moderation', 'platform moderation',
        'community guidelines', 'terms of service violation',
        'shadowban', 'demonetized', 'demonetization',
        'algorithm bias', 'content suppression',
        
        # Public forum / government
        'public forum', 'limited public forum',
        'government censorship', 'state action',
        'chilling effect', 'prior restraint',
        
        # Academic / institutional
        'academic freedom', 'intellectual freedom',
        'library censorship', 'book ban',
        'curriculum restriction',
        
        # Whistleblower / retaliation
        'whistleblower', 'retaliation for speech',
        'protected speech', 'political speech',
    ], complaint_type='free_speech')
    
    register_legal_terms('free_speech', [
        r'\b(first amendment)\b',
        r'\b(free(dom of)? speech)\b',
        r'\b(free(dom of)? (expression|press))\b',
        r'\b(prior restraint)\b',
        r'\b(viewpoint discrimination)\b',
        r'\b(content[- ]based restriction)\b',
        r'\b(public forum)\b',
        r'\b(state action)\b',
        r'\b(chilling effect)\b',
        r'\b(censorship|censor(ed)?)\b',
    ])


def register_immigration_complaint():
    """Register keywords and patterns for immigration law complaints."""
    register_keywords('complaint', [
        # Immigration status
        'immigration', 'immigrant', 'undocumented',
        'visa', 'green card', 'permanent resident',
        'naturalization', 'citizenship',
        'asylum', 'refugee', 'asylee',
        'temporary protected status', 'tps',
        'daca', 'dreamer', 'deferred action',
        
        # Agencies and processes
        'uscis', 'ice', 'cbp', 'immigration and customs enforcement',
        'customs and border protection',
        'immigration court', 'eoir', 'deportation',
        'removal proceedings', 'detention',
        'immigration detention', 'bond hearing',
        
        # Employment immigration
        'h-1b', 'h-2a', 'h-2b', 'l-1', 'o-1',
        'employment-based visa', 'labor certification',
        'perm', 'prevailing wage',
        
        # Family immigration
        'family-based immigration', 'family petition',
        'i-130', 'marriage-based green card',
        'adjustment of status', 'consular processing',
        
        # Immigration violations
        'immigration fraud', 'unlawful presence',
        'visa overstay', 'bars to admission',
        'inadmissibility', 'removal order',
        
        # Rights and remedies
        'withholding of removal', 'cancellation of removal',
        'relief from removal', 'stay of removal',
        'travel document', 'advance parole',
        'employment authorization', 'work permit',
    ], complaint_type='immigration')
    
    register_legal_terms('immigration', [
        r'\b(immigration|immigrant)\b',
        r'\b(visa|green card)\b',
        r'\b(asylum|refugee|asylee)\b',
        r'\b(deportation|removal)\b',
        r'\b(uscis|ice|cbp|eoir)\b',
        r'\b(daca|dreamer)\b',
        r'\b(h-?1b|h-?2[ab]|l-?1|o-?1)\b',
        r'\b(adjustment of status)\b',
        r'\b(withholding of removal)\b',
        r'\b(cancellation of removal)\b',
    ])


def register_family_law_complaint():
    """Register keywords and patterns for family law complaints."""
    register_keywords('complaint', [
        # Divorce / dissolution
        'divorce', 'dissolution of marriage',
        'legal separation', 'annulment',
        'marital property', 'community property',
        'equitable distribution', 'property division',
        
        # Child custody
        'child custody', 'parenting time', 'visitation',
        'sole custody', 'joint custody', 'shared custody',
        'physical custody', 'legal custody',
        'custodial parent', 'non-custodial parent',
        'parenting plan', 'custody order',
        
        # Child support
        'child support', 'support obligation',
        'child support arrears', 'support enforcement',
        'support modification',
        
        # Spousal support
        'alimony', 'spousal support', 'maintenance',
        'temporary support', 'rehabilitative support',
        'permanent support',
        
        # Domestic violence
        'domestic violence', 'domestic abuse',
        'protective order', 'restraining order',
        'order of protection', 'no-contact order',
        
        # Adoption / guardianship
        'adoption', 'guardianship', 'foster care',
        'termination of parental rights',
        
        # Paternity
        'paternity', 'parentage', 'genetic testing',
    ], complaint_type='family_law')
    
    register_legal_terms('family_law', [
        r'\b(divorce|dissolution)\b',
        r'\b(child custody|parenting time)\b',
        r'\b(child support)\b',
        r'\b(alimony|spousal support)\b',
        r'\b(domestic (violence|abuse))\b',
        r'\b((protective|restraining) order)\b',
        r'\b(adoption|guardianship)\b',
        r'\b(paternity|parentage)\b',
    ])


def register_criminal_defense_complaint():
    """Register keywords and patterns for criminal defense complaints."""
    register_keywords('complaint', [
        # Constitutional rights
        'fourth amendment', 'unreasonable search',
        'illegal search', 'warrantless search',
        'fifth amendment', 'self-incrimination',
        'miranda rights', 'right to remain silent',
        'sixth amendment', 'right to counsel',
        'effective assistance of counsel',
        'speedy trial', 'jury trial',
        'eighth amendment', 'cruel and unusual punishment',
        'excessive bail', 'excessive fine',
        
        # Due process
        'due process', 'procedural due process',
        'substantive due process', 'fundamental fairness',
        
        # Criminal procedure
        'arrest', 'detention', 'probable cause',
        'search warrant', 'arrest warrant',
        'suppression of evidence', 'exclusionary rule',
        'fruit of the poisonous tree',
        'interrogation', 'confession', 'coerced confession',
        
        # Criminal charges
        'criminal charge', 'indictment', 'information',
        'misdemeanor', 'felony', 'infraction',
        
        # Trial rights
        'jury selection', 'voir dire', 'peremptory challenge',
        'confrontation clause', 'cross-examination',
        'prosecutorial misconduct', 'brady violation',
        'exculpatory evidence',
        
        # Sentencing
        'sentencing', 'sentence enhancement',
        'three strikes', 'mandatory minimum',
        'parole', 'probation', 'supervised release',
        
        # Post-conviction
        'habeas corpus', 'post-conviction relief',
        'ineffective assistance', 'actual innocence',
        'wrongful conviction',
    ], complaint_type='criminal_defense')
    
    register_legal_terms('criminal_defense', [
        r'\b((fourth|fifth|sixth|eighth) amendment)\b',
        r'\b(miranda (rights|warning))\b',
        r'\b(right to (counsel|remain silent|jury trial))\b',
        r'\b(due process)\b',
        r'\b(unreasonable search)\b',
        r'\b(probable cause)\b',
        r'\b(exclusionary rule)\b',
        r'\b(brady violation)\b',
        r'\b(habeas corpus)\b',
        r'\b(ineffective assistance)\b',
    ])


def register_tax_law_complaint():
    """Register keywords and patterns for tax law complaints."""
    register_keywords('complaint', [
        # Tax agencies
        'irs', 'internal revenue service',
        'tax court', 'u.s. tax court',
        'state tax', 'state department of revenue',
        
        # Tax types
        'income tax', 'corporate tax', 'estate tax',
        'gift tax', 'payroll tax', 'employment tax',
        'excise tax', 'sales tax', 'property tax',
        
        # Tax processes
        'tax audit', 'examination', 'revenue agent',
        'notice of deficiency', 'statutory notice',
        'tax assessment', 'tax liability',
        'collection due process', 'cdp hearing',
        
        # Tax penalties
        'tax penalty', 'accuracy penalty',
        'fraud penalty', 'failure to file',
        'failure to pay', 'estimated tax penalty',
        
        # Tax remedies
        'innocent spouse relief', 'offer in compromise',
        'installment agreement', 'currently not collectible',
        'penalty abatement', 'interest abatement',
        
        # Tax collection
        'tax levy', 'tax lien', 'wage garnishment',
        'bank levy', 'seizure', 'collection action',
        
        # Tax procedure
        'tax return', 'amended return', 'refund claim',
        'statute of limitations', 'collection statute',
        'assessment statute',
    ], complaint_type='tax_law')
    
    register_legal_terms('tax_law', [
        r'\b(irs|internal revenue service)\b',
        r'\b(tax court)\b',
        r'\b(tax (audit|assessment|liability))\b',
        r'\b(notice of deficiency)\b',
        r'\b(tax (penalty|levy|lien))\b',
        r'\b(innocent spouse)\b',
        r'\b(offer in compromise)\b',
        r'\b(collection due process)\b',
    ])


def register_intellectual_property_complaint():
    """Register keywords and patterns for intellectual property complaints."""
    register_keywords('complaint', [
        # Patents
        'patent', 'patent infringement',
        'utility patent', 'design patent',
        'patent pending', 'prior art',
        'obviousness', 'enablement',
        'patent claim', 'patent prosecution',
        
        # Trademarks
        'trademark', 'service mark', 'trade name',
        'trademark infringement', 'likelihood of confusion',
        'trademark dilution', 'famous mark',
        'generic mark', 'descriptive mark',
        'suggestive mark', 'arbitrary mark',
        'trade dress', 'secondary meaning',
        
        # Copyrights
        'copyright', 'copyright infringement',
        'fair use', 'transformative use',
        'derivative work', 'copyright registration',
        'dmca', 'digital millennium copyright act',
        'takedown notice', 'counter-notice',
        
        # Trade secrets
        'trade secret', 'confidential information',
        'misappropriation', 'utsa',
        'non-disclosure agreement', 'nda',
        'non-compete agreement',
        
        # General IP
        'intellectual property', 'ip', 'licensing',
        'royalty', 'license agreement',
        'infringement', 'cease and desist',
        'damages', 'injunctive relief',
    ], complaint_type='intellectual_property')
    
    register_legal_terms('intellectual_property', [
        r'\b(patent( infringement)?)\b',
        r'\b(trademark( infringement)?)\b',
        r'\b(copyright( infringement)?)\b',
        r'\b(trade secret)\b',
        r'\b(fair use)\b',
        r'\b(dmca)\b',
        r'\b(likelihood of confusion)\b',
        r'\b(trade dress)\b',
    ])


def register_environmental_law_complaint():
    """Register keywords and patterns for environmental law complaints."""
    register_keywords('complaint', [
        # Environmental agencies
        'epa', 'environmental protection agency',
        'clean air act', 'clean water act',
        'safe drinking water act',
        
        # Environmental issues
        'pollution', 'contamination',
        'air pollution', 'water pollution',
        'soil contamination', 'groundwater contamination',
        'toxic waste', 'hazardous waste',
        'hazardous substance', 'pollutant',
        
        # Environmental laws
        'cercla', 'superfund', 'rcra',
        'resource conservation and recovery act',
        'comprehensive environmental response',
        'nepa', 'environmental impact statement',
        'endangered species act', 'esa',
        
        # Environmental violations
        'environmental violation', 'permit violation',
        'discharge violation', 'emission violation',
        'npdes', 'national pollutant discharge',
        
        # Environmental liability
        'environmental liability', 'cleanup cost',
        'remediation', 'natural resource damage',
        'citizen suit', 'environmental enforcement',
        
        # Climate
        'greenhouse gas', 'carbon emission',
        'climate change', 'global warming',
    ], complaint_type='environmental_law')
    
    register_legal_terms('environmental_law', [
        r'\b(epa|environmental protection agency)\b',
        r'\b(clean (air|water) act)\b',
        r'\b(cercla|superfund)\b',
        r'\b(rcra)\b',
        r'\b(nepa)\b',
        r'\b(endangered species act)\b',
        r'\b((air|water) pollution)\b',
        r'\b((toxic|hazardous) waste)\b',
        r'\b(contamination|remediation)\b',
    ])


def register_probate_complaint():
    """Register keywords and patterns for probate and estate law complaints."""
    register_keywords('complaint', [
        # Probate process
        'probate', 'probate court', 'probate proceeding',
        'estate administration', 'estate proceeding',
        'surrogate court', 'orphans court',
        
        # Parties
        'decedent', 'deceased', 'testator', 'testatrix',
        'estate', 'estate of', 'probate estate',
        'executor', 'executrix', 'personal representative',
        'administrator', 'administratrix',
        'beneficiary', 'heir', 'legatee', 'devisee',
        'guardian', 'conservator', 'ward',
        'trustee', 'trust beneficiary', 'settlor', 'grantor',
        
        # Documents
        'will', 'last will and testament', 'testament',
        'codicil', 'holographic will', 'nuncupative will',
        'living will', 'advance directive',
        'trust', 'living trust', 'testamentary trust',
        'revocable trust', 'irrevocable trust',
        'trust agreement', 'trust instrument',
        'letters testamentary', 'letters of administration',
        
        # Estate types
        'testate', 'intestate', 'intestacy',
        'partial intestacy',
        
        # Assets and property
        'estate asset', 'probate asset', 'non-probate asset',
        'real property', 'personal property',
        'tangible property', 'intangible property',
        'estate inventory', 'asset appraisal',
        'estate account', 'estate accounting',
        
        # Inheritance and distribution
        'inheritance', 'inherit', 'heir',
        'intestate succession', 'statutory share',
        'elective share', 'forced share',
        'distribution', 'final distribution',
        'per stirpes', 'per capita',
        'right of survivorship', 'joint tenancy',
        'payable on death', 'pod', 'transfer on death', 'tod',
        
        # Debts and taxes
        'estate debt', 'estate claim', 'creditor claim',
        'claim against estate', 'notice to creditors',
        'estate tax', 'inheritance tax', 'death tax',
        'estate expenses', 'administration expenses',
        
        # Guardianship and conservatorship
        'guardianship', 'guardian of the person',
        'guardian of the estate', 'guardian ad litem',
        'conservatorship', 'conservator',
        'incapacitated person', 'protected person',
        'ward', 'minor', 'adult guardianship',
        'guardianship proceeding',
        
        # Disputes and litigation
        'will contest', 'challenge will', 'contested will',
        'undue influence', 'lack of capacity',
        'testamentary capacity', 'sound mind',
        'fraud', 'forgery', 'duress', 'coercion',
        'trust dispute', 'trust litigation',
        'breach of fiduciary duty', 'fiduciary duty',
        'removal of executor', 'removal of trustee',
        'surcharge', 'accounting dispute',
        'construction of will', 'interpretation of will',
        
        # Trust types and issues
        'charitable trust', 'special needs trust',
        'spendthrift trust', 'discretionary trust',
        'marital trust', 'bypass trust', 'credit shelter trust',
        'qualified terminable interest property', 'qtip trust',
        'trust modification', 'trust termination',
        'trust reformation', 'trust amendment',
        
        # Powers and authority
        'power of attorney', 'durable power of attorney',
        'springing power of attorney',
        'healthcare power of attorney',
        'attorney in fact', 'agent',
        
        # Estate planning
        'estate plan', 'estate planning',
        'succession plan', 'wealth transfer',
        'gift', 'inter vivos gift', 'gift causa mortis',
        
        # Marital property
        'community property', 'separate property',
        'marital property', 'quasi-community property',
        'surviving spouse', 'widow', 'widower',
        
        # Small estate procedures
        'small estate affidavit', 'summary administration',
        'affidavit of heirship', 'muniment of title',
        
        # Appeals and review
        'probate appeal', 'estate litigation',
        'accounting review', 'estate audit',
    ], complaint_type='probate')
    
    register_legal_terms('probate', [
        r'\b(probate( court| proceeding)?)\b',
        r'\b(estate (administration|proceeding))\b',
        r'\b(surrogate court|orphans court)\b',
        r'\b(executor|executrix|personal representative)\b',
        r'\b(administrator|administratrix)\b',
        r'\b((last )?will and testament|testament)\b',
        r'\b(codicil)\b',
        r'\b(living trust|testamentary trust)\b',
        r'\b(revocable trust|irrevocable trust)\b',
        r'\b(letters testamentary)\b',
        r'\b(letters of administration)\b',
        r'\b(testate|intestate|intestacy)\b',
        r'\b(beneficiary|heir|legatee|devisee)\b',
        r'\b(guardianship|conservatorship)\b',
        r'\b(guardian|conservator)\b',
        r'\b(will contest)\b',
        r'\b(undue influence)\b',
        r'\b(testamentary capacity)\b',
        r'\b(breach of fiduciary duty)\b',
        r'\b(estate (tax|debt|claim))\b',
        r'\b(inheritance tax)\b',
        r'\b(per stirpes|per capita)\b',
        r'\b(elective share|forced share)\b',
        r'\b(power of attorney)\b',
        r'\b(trust (dispute|litigation|modification|termination))\b',
        r'\b(charitable trust|special needs trust)\b',
        r'\b(small estate affidavit)\b',
        r'\b(summary administration)\b',
    ])


def register_dei_complaint():
    """
    Register keywords and patterns for DEI (Diversity, Equity, and Inclusion) complaints.
    
    This encompasses discrimination, harassment, and civil rights violations across
    multiple domains including housing, employment, and public accommodations.
    Integrates comprehensive DEI keywords from HACC repository for policy analysis.
    """
    # Core DEI keywords from HACC's index_and_tag.py
    register_keywords('complaint', [
        # Core DEI terms
        'diversity', 'diverse', 'equity', 'equitable', 'inclusion', 'inclusive',
        'dei', 'deia', 'deib', 'deij',
        
        # Justice frameworks
        'racial justice', 'social justice', 'environmental justice',
        'justice-centered', 'justice oriented',
        'anti-racist', 'anti discrimination',
        
        # Community descriptors
        'marginalized', 'minority', 'minorities',
        'bipoc', 'people of color',
        'underrepresented', 'underrepresented groups',
        'underserved', 'underserviced',
        'historically underrepresented', 'marginalized communities',
        'socially disadvantaged', 'economically disadvantaged',
        
        # Equity frameworks
        'equity lens', 'equity framework', 'equity initiatives',
        'equity plan', 'cultural humility', 'cultural responsiveness',
        'accessibility', 'barrier reduction', 'inclusive environment',
        
        # Discrimination types
        'discrimination', 'discriminate', 'discriminatory',
        'harassment', 'hostile environment',
        'retaliation', 'retaliate', 'retaliatory',
        
        # Fair housing
        'fair housing', 'housing discrimination',
        'reasonable accommodation', 'reasonable modification',
        'familial status', 'source of income',
        
        # Protected classes
        'protected class', 'protected classes',
        'race', 'racial', 'color',
        'national origin', 'nationality',
        'religion', 'religious',
        'sex', 'gender',
        'disability', 'disabled', 'handicap',
        'age', 'elderly',
        'sexual orientation', 'gender identity',
        
        # Legal impact
        'disparate impact', 'disparate treatment',
        'intentional discrimination', 'unintentional discrimination',
        'adverse impact', 'adverse effect',
        
        # Housing specific
        'section 8', 'housing choice voucher',
        'public housing', 'affordable housing',
        'tenant', 'landlord', 'lease', 'rental',
        'eviction', 'housing authority',
        
        # Employment specific
        'employment discrimination', 'workplace discrimination',
        'equal employment opportunity', 'eeoc',
        'title vii', 'ada', 'adea', 'fmla',
        
        # Civil rights
        'civil rights', 'equal protection', 'due process',
        'constitutional rights', 'constitutional violation',
        
        # Complaint process
        'complainant', 'respondent', 'charging party',
        'aggrieved person', 'complaint', 'charge',
        
        # Community benefits
        'community benefit', 'community benefits',
        'section 3', 'equal opportunity',
    ], complaint_type='dei')
    
    # DEI proxy keywords from HACC (euphemisms and indirect references)
    register_keywords('dei_proxy', [
        'cultural competence', 'cultural competency',
        'lived experience',
        'diversity statement',
        'safe space',
        'minority-only',
        'first-generation',
        'low-income targeting',
        'overcoming obstacles',
        'implicit bias', 'unconscious bias',
        'affirmative action',
    ], complaint_type='dei')
    
    # Evidence-related keywords
    register_keywords('evidence', [
        'evidence', 'proof', 'documentation',
        'witness', 'testimony', 'statement',
        'document', 'record', 'file',
        'exhibit', 'attachment', 'appendix',
        'correspondence', 'email', 'letter',
        'notice', 'communication',
        'photograph', 'image', 'video',
        'recording', 'audio',
        'contract', 'agreement', 'lease',
        'policy', 'procedure', 'manual',
        'complaint form', 'intake form',
        'medical record', 'doctor note',
        'police report', 'incident report',
    ], complaint_type='dei')
    
    # Legal authority keywords
    register_keywords('legal', [
        'statute', 'law', 'code', 'regulation',
        'ordinance', 'rule', 'act',
        'u.s.c.', 'c.f.r.', 'federal register',
        'case law', 'precedent', 'holding',
        'opinion', 'decision', 'ruling',
        'court order', 'judgment', 'decree',
        'constitution', 'constitutional',
        'amendment', 'provision', 'section',
        'subsection', 'clause', 'paragraph',
        'title', 'chapter', 'article',
    ], complaint_type='dei')
    
    # Binding/enforceable indicators
    register_keywords('binding', [
        'policy', 'ordinance', 'statewide', 'model policy',
        'contract', 'agreement', 'standard',
        'required', 'must', 'shall', 'mandatory',
        'applicable to', 'applicability', 'enforceable',
        'governing', 'binding', 'regulation', 'rule',
        'directive', 'compliance', 'obligated', 'stipulation',
    ], complaint_type='dei')
    
    # Severity/risk indicators
    register_keywords('severity_high', [
        'systemic', 'pattern', 'practice',
        'intentional', 'willful', 'deliberate',
        'egregious', 'severe', 'pervasive',
        'ongoing', 'repeated', 'continuous',
        'punitive damages', 'injunctive relief',
    ], complaint_type='dei')
    
    register_keywords('severity_medium', [
        'violation', 'breach', 'failure',
        'inadequate', 'insufficient',
        'disparate impact', 'adverse effect',
        'compensatory damages',
    ], complaint_type='dei')
    
    register_keywords('severity_low', [
        'potential', 'possible', 'may',
        'unintentional', 'inadvertent',
        'technical', 'procedural',
        'correctable', 'remediable',
    ], complaint_type='dei')
    
    # Applicability keywords - DEI context covers these domains
    register_keywords('applicability_housing', [
        'housing', 'lease', 'tenant', 'landlord', 'rental',
        'dwelling', 'residence', 'apartment', 'unit',
        'eviction', 'termination', 'nonrenewal',
        'affordable', 'public housing', 'section 8',
        'housing authority', 'housing choice voucher',
        'reasonable accommodation', 'accessibility',
    ], complaint_type='dei')
    
    register_keywords('applicability_employment', [
        'employment', 'workplace', 'job', 'work',
        'hire', 'hiring', 'recruit', 'recruitment',
        'fire', 'firing', 'terminate', 'termination',
        'promote', 'promotion', 'demote', 'demotion',
        'employee', 'employer', 'supervisor',
        'wages', 'salary', 'compensation', 'benefits',
        'fmla', 'leave', 'accommodation',
    ], complaint_type='dei')
    
    register_keywords('applicability_public_accommodation', [
        'public accommodation', 'place of public accommodation',
        'service', 'facility', 'establishment',
        'access', 'accessibility', 'barrier',
        'restaurant', 'hotel', 'store', 'shop',
        'theater', 'stadium', 'park',
        'transportation', 'bus', 'train',
    ], complaint_type='dei')
    
    register_keywords('applicability_lending', [
        'lending', 'loan', 'mortgage', 'credit',
        'financing', 'financial', 'bank', 'lender',
        'interest rate', 'terms', 'approval',
        'denial', 'redlining', 'appraisal',
    ], complaint_type='dei')
    
    register_keywords('applicability_education', [
        'education', 'school', 'university', 'college',
        'student', 'enrollment', 'admission',
        'classroom', 'teacher', 'faculty',
        'curriculum', 'program', 'degree',
        'disability services', 'accommodations',
    ], complaint_type='dei')
    
    register_keywords('applicability_government_services', [
        'government', 'agency', 'department',
        'public service', 'benefits', 'assistance',
        'program', 'eligibility', 'application',
        'permit', 'license', 'approval',
    ], complaint_type='dei')
    
    # Procurement and contracting (from HACC DEI research)
    register_keywords('applicability_procurement', [
        'procurement', 'contract', 'contracting',
        'vendor', 'supplier', 'bid', 'bidding',
        'rfp', 'request for proposal', 'award',
        'purchase', 'purchasing',
        'disadvantaged business enterprise', 'dbe',
        'minority-owned business', 'mbe',
        'women-owned business', 'wbe',
        'mwesb', 'esb',
        'socially disadvantaged', 'economically disadvantaged',
        'small business', 'certification',
        'subcontractor', 'subcontracting',
    ], complaint_type='dei')
    
    # Training and development (from HACC index_and_tag.py)
    register_keywords('applicability_training', [
        'training', 'workshop', 'course', 'curriculum',
        'education', 'seminar', 'professional development',
        'orientation', 'onboarding', 'certification',
        'cultural competency training', 'implicit bias training',
        'diversity training', 'sensitivity training',
    ], complaint_type='dei')
    
    # Community engagement (from HACC)
    register_keywords('applicability_community_engagement', [
        'community engagement', 'public input',
        'stakeholder', 'outreach', 'consultation',
        'community participation', 'public comment',
        'engagement plan', 'community benefits',
    ], complaint_type='dei')
    
    # DEI-specific legal patterns
    # DEI-specific legal patterns (unique patterns only, avoiding duplicates)
    # Note: Common patterns like "discrimination", "fair housing", etc. are already
    # registered in other categories and will be loaded by LegalPatternExtractor
    register_legal_terms('dei', [
        # DEI Core Terms (unique to DEI taxonomy)
        r"\b(diversity|diverse)\b",
        r"\b(equity|equitable)\b",
        r"\b(inclusion|inclusive)\b",
        r"\b(underrepresented minorit(y|ies))\b",
        r"\b(underserved communit(y|ies))\b",
        r"\b(disadvantaged business enterprise|DBE)\b",
        r"\b(minority[- ]owned business|MBE)\b",
        r"\b(wom[ae]n[- ]owned business|WBE)\b",
        r"\b(MWESB|ESB)\b",
        r"\b(affirmative action)\b",
        r"\b(cultural competen(cy|ce))\b",
        r"\b(implicit bias|unconscious bias)\b",
        r"\b(racial equity)\b",
        r"\b(social equity)\b",
        r"\b(environmental justice)\b",
        r"\b(historically underrepresented)\b",
        r"\b(marginalized communit(y|ies))\b",
        r"\b(BIPOC)\b",
        r"\b(equal opportunity)\b",
        r"\b(Section 3)\b",
        r"\b(community benefit(s)?)\b",
        r"\b(socially disadvantaged)\b",
        r"\b(economically disadvantaged)\b",
        r"\b(racial justice)\b",
        r"\b(social justice)\b",
        r"\b(people of color)\b",
        r"\b(underserved|underserviced)\b",
        r"\b(equity (lens|framework|initiative))\b",
        r"\b(cultural (humility|responsiveness))\b",
        r"\b(justice[- ]centered|justice[- ]oriented)\b",
        r"\b(anti[- ]racist)\b",
        r"\b(lived experience)\b",
        r"\b(safe space)\b",
        r"\b(first[- ]generation)\b",
    ])


def get_registered_types() -> List[str]:
    """
    Get all registered complaint types.
    
    Returns:
        List of complaint type names
    """
    from .keywords import _global_registry
    return _global_registry.get_complaint_types()


def get_complaint_type(complaint_type: str) -> Optional[Dict[str, Any]]:
    """Return basic metadata for a registered complaint type.

    This is used by mediator hooks (e.g., LegalCorpusRAGHook) to retrieve
    type-scoped keyword categories.

    Returns None when the type is unknown.
    """

    if not isinstance(complaint_type, str):
        return None

    name = complaint_type.strip()
    if not name:
        return None

    from .keywords import _global_registry

    if name not in _global_registry.get_complaint_types():
        return None

    categories = _global_registry.get_all_categories(name)
    primary_category = "complaint"
    if categories:
        primary_category = "complaint" if "complaint" in categories else categories[0]

    return {
        "name": name,
        "category": primary_category,
        "categories": categories,
    }


# Register default types on module import
register_housing_complaint()
register_employment_complaint()
register_civil_rights_complaint()
register_consumer_complaint()
register_healthcare_complaint()
register_free_speech_complaint()
register_immigration_complaint()
register_family_law_complaint()
register_criminal_defense_complaint()
register_tax_law_complaint()
register_intellectual_property_complaint()
register_environmental_law_complaint()
register_probate_complaint()  # Probate and estate law
register_dei_complaint()  # DEI taxonomy (formerly hacc_integration)
