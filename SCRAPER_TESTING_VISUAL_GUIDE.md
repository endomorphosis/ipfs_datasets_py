# Scraper Testing Framework - Visual Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   MCP DASHBOARD SCRAPER TESTING FRAMEWORK                   │
│                                                                             │
│  Ensures scraped data is clean, coherent, and free from web artifacts      │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          FOUR MCP DASHBOARDS                                │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│   📚 CASELAW     │  │   💰 FINANCE     │  │   ⚕️  MEDICINE   │  │   💻 SOFTWARE    │
│                  │  │                  │  │                  │  │                  │
│  localhost:8899/ │  │  localhost:8899/ │  │  localhost:8899/ │  │  localhost:8899/ │
│  mcp/caselaw     │  │  mcp/finance     │  │  mcp/medicine    │  │  mcp/software    │
│                  │  │                  │  │                  │  │                  │
│  5 Scrapers:     │  │  2 Scrapers:     │  │  2 Scrapers:     │  │  1 Scraper:      │
│  • US Code       │  │  • Stock Data    │  │  • Clinical      │  │  • GitHub Repos  │
│  • Fed Register  │  │  • Finance News  │  │    Trials        │  │                  │
│  • State Laws    │  │                  │  │  • PubMed        │  │                  │
│  • Municipal     │  │                  │  │                  │  │                  │
│  • RECAP         │  │                  │  │                  │  │                  │
└──────────────────┘  └──────────────────┘  └──────────────────┘  └──────────────────┘
        │                     │                     │                     │
        └─────────────────────┴─────────────────────┴─────────────────────┘
                                      │
                            ┌─────────▼─────────┐
                            │  TEST FRAMEWORK   │
                            │                   │
                            │  Validates:       │
                            │  ✓ No HTML/DOM    │
                            │  ✓ No menus       │
                            │  ✓ Coherent data  │
                            │  ✓ No duplicates  │
                            └───────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          TESTING WORKFLOW                                   │
└─────────────────────────────────────────────────────────────────────────────┘

Trigger:                        Process:                         Output:
┌──────────────┐              ┌──────────────┐              ┌──────────────┐
│ • Git Push   │─────────────▶│ GitHub       │─────────────▶│ Test Results │
│ • Pull Req   │              │ Actions      │              │ • Pass/Fail  │
│ • Schedule   │              │              │              │ • Quality    │
│ • Manual     │              │  ┌────────┐  │              │   Score      │
└──────────────┘              │  │ Docker │  │              │ • Issues     │
                              │  │ Matrix │  │              │   Found      │
                              │  └────────┘  │              │ • Samples    │
                              │              │              └──────────────┘
                              │  Parallel    │                     │
                              │  Testing:    │                     ▼
                              │  • Caselaw   │              ┌──────────────┐
                              │  • Finance   │              │  Artifacts   │
                              │  • Medicine  │              │  • JSON      │
                              │  • Software  │              │  • XML       │
                              └──────────────┘              │  • Reports   │
                                                            └──────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                        DATA QUALITY CHECKS                                  │
└─────────────────────────────────────────────────────────────────────────────┘

❌ BAD DATA (Caught by Framework):          ✅ GOOD DATA (Passes Validation):
                                        
┌─────────────────────────────────┐      ┌─────────────────────────────────┐
│ <div class="content">           │      │ {                               │
│   <h1>Title</h1>                │      │   "title": "Legal Document",    │
│   <p>Text</p>                   │      │   "text": "Clean statute...",   │
│ </div>                          │      │   "citation": "1 U.S.C. § 101"  │
│                                 │      │ }                               │
│ Issues:                         │      │                                 │
│ • HTML tags                     │      │ Quality: 95/100 ✓              │
│ • DOM structure                 │      │ Issues: 0                       │
│ Quality: 35/100 ✗              │      └─────────────────────────────────┘
└─────────────────────────────────┘

┌─────────────────────────────────┐      ┌─────────────────────────────────┐
│ "Home | About | Contact |       │      │ {                               │
│  Statute text here |            │      │   "title": "Title 1, Sec 101",  │
│  Back to top"                   │      │   "text": "This establishes..." │
│                                 │      │ }                               │
│ Issues:                         │      │                                 │
│ • Navigation menus              │      │ Quality: 90/100 ✓              │
│ • Disconnected content          │      │ Issues: 0                       │
│ Quality: 45/100 ✗              │      └─────────────────────────────────┘
└─────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          USAGE QUICK REFERENCE                              │
└─────────────────────────────────────────────────────────────────────────────┘

🌐 GitHub Actions (Recommended):
   1. Go to Actions tab → "Scraper Validation and Testing"
   2. Click "Run workflow"
   3. Select domain (all/caselaw/finance/medicine/software)
   4. View results in workflow summary

💻 Command Line:
   # List scrapers
   python scraper_management.py list --domain all
   
   # Test specific domain
   python scraper_management.py test --domain caselaw
   
   # Test all (comprehensive)
   python scraper_management.py test --domain all --comprehensive

🧪 Pytest:
   # One domain
   pytest tests/scraper_tests/test_caselaw_scrapers.py -v
   
   # All domains
   pytest tests/scraper_tests/ -v

┌─────────────────────────────────────────────────────────────────────────────┐
│                         QUALITY SCORE GUIDE                                 │
└─────────────────────────────────────────────────────────────────────────────┘

90-100  ████████████████████  Excellent  Production-ready
70-89   ███████████████░░░░░  Good       Minor issues, acceptable
50-69   ███████████░░░░░░░░░  Fair       Needs improvement
0-49    ████░░░░░░░░░░░░░░░░  Poor       Major problems

┌─────────────────────────────────────────────────────────────────────────────┐
│                           FILE STRUCTURE                                    │
└─────────────────────────────────────────────────────────────────────────────┘

ipfs_datasets_py/
├── ipfs_datasets_py/
│   ├── scraper_testing_framework.py  ← Core framework (580 lines)
│   └── mcp_server/tools/
│       ├── legal_dataset_tools/      ← Caselaw scrapers
│       ├── finance_data_tools/       ← Finance scrapers
│       ├── medical_research_scrapers/← Medicine scrapers
│       └── software_engineering_tools/← Software scrapers
├── tests/
│   └── scraper_tests/
│       ├── test_caselaw_scrapers.py  ← Caselaw tests
│       ├── test_finance_scrapers.py  ← Finance tests
│       ├── test_medicine_scrapers.py ← Medicine tests
│       └── test_software_scrapers.py ← Software tests
├── .github/workflows/
│   └── scraper-validation.yml        ← CI/CD workflow
├── scraper_management.py             ← CLI tool
├── docs/
│   └── SCRAPER_TESTING_FRAMEWORK.md  ← Full docs
└── SCRAPER_TESTING_QUICKSTART.md     ← Quick guide

┌─────────────────────────────────────────────────────────────────────────────┐
│                         AUTOMATIC TRIGGERS                                  │
└─────────────────────────────────────────────────────────────────────────────┘

🔄 Push to main/develop (when scraper files change)
🔄 Pull Request to main/develop
🔄 Schedule: Daily at 3 AM UTC
🔄 Manual: Via workflow_dispatch button

┌─────────────────────────────────────────────────────────────────────────────┐
│                         ADDING NEW SCRAPERS                                 │
└─────────────────────────────────────────────────────────────────────────────┘

1. Implement scraper in appropriate tools/ directory
2. Add test case to relevant test_*_scrapers.py file:
   
   @pytest.mark.asyncio
   async def test_my_scraper(self, test_runner):
       result = await test_runner.run_scraper_test(
           scraper_func=my_scraper,
           scraper_name="my_scraper",
           domain=ScraperDomain.CASELAW,
           test_args={'param': 'value'}
       )
       assert result.data_quality_score >= 70

3. Update scraper_management.py SCRAPERS list
4. Run: python scraper_management.py test --domain your_domain
5. Commit and push - CI will automatically test!

┌─────────────────────────────────────────────────────────────────────────────┐
│                              SUPPORT                                        │
└─────────────────────────────────────────────────────────────────────────────┘

📖 Full Docs:      docs/SCRAPER_TESTING_FRAMEWORK.md
🚀 Quick Start:    SCRAPER_TESTING_QUICKSTART.md
💡 Example:        example_scraper_validation.py
🐛 Issues:         Check test artifacts for details
📊 Reports:        Download from workflow artifacts

═══════════════════════════════════════════════════════════════════════════════
```
