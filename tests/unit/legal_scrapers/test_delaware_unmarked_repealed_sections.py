"""Strict regressions for Delaware's unmarked repealed-section structure."""

from __future__ import annotations

import hashlib

import pytest
from bs4 import BeautifulSoup

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.delaware import (
    DelawareScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.delaware_chapter import (
    parse_delaware_chapter_html,
)

SOURCE_URL = "https://delcode.delaware.gov/title11/c085/sc05/index.html"
EXPIRED_PILOT_URL = "https://delcode.delaware.gov/title14/c017/index.html"
EXPIRED_DISTRIBUTION_URL = (
    "https://delcode.delaware.gov/title30/c054/sc01/index.html"
)
VACATED_SUBCHAPTER_URL = "https://delcode.delaware.gov/title12/c011/sc03/index.html"
TRANSFERRED_CHAPTER_URL = "https://delcode.delaware.gov/title14/c094/index.html"
TRANSFERRED_SECTION_URL = "https://delcode.delaware.gov/title18/c070/index.html"
TRANSFERRED_SECTION_TARGET_URL = (
    "https://delcode.delaware.gov/title6/c025i/index.html"
)
EMPTY_RELOCATED_CHAPTER_URL = (
    "https://delcode.delaware.gov/title19/c026/index.html"
)
EMPTY_RELOCATED_TARGET_URL = (
    "https://delcode.delaware.gov/title18/c026/index.html"
)
OMITTED_SECTION_URL = "https://delcode.delaware.gov/title21/c071/index.html"
EXPIRED_CHAPTER_URL = "https://delcode.delaware.gov/title30/c020d/index.html"
SUPERSEDED_CHAPTER_URL = "https://delcode.delaware.gov/title29/c102/index.html"
SUPERSEDING_CHAPTER_URL = (
    "https://delcode.delaware.gov/title29/c102_1/index.html"
)
OMITTED_CHAPTER_URL = "https://delcode.delaware.gov/title16/c009a/index.html"
RELOCATED_CHAPTER_URL = "https://delcode.delaware.gov/title16/c105/index.html"
RELOCATED_TARGET_URL = (
    "https://delcode.delaware.gov/title16/c011/sc08/index.html"
)
CURRENT_CHAPTER_8_URL = "https://delcode.delaware.gov/title13/c008_1/index.html"
FUTURE_CHAPTER_8_URL = "https://delcode.delaware.gov/title13/c008/index.html"
CURRENT_CHAPTER_8_LABEL = (
    "Chapter 8. Uniform Parentage Act [Effective until Dec. 6, 2026]."
)
CURRENT_CHAPTER_8_CHILDREN = (
    (
        "https://delcode.delaware.gov/title13/c008/sc01_1/index.html",
        "Subchapter I. General Provisions [Effective until Dec. 6, 2026].",
    ),
    (
        "https://delcode.delaware.gov/title13/c008/sc02_1/index.html",
        "Subchapter II. Parent-Child Relationship [Effective until Dec. 6, 2026].",
    ),
    (
        "https://delcode.delaware.gov/title13/c008/sc03_1/index.html",
        (
            "Subchapter III. Voluntary Acknowledgement of Paternity "
            "[Effective until Dec. 6, 2026]."
        ),
    ),
    (
        "https://delcode.delaware.gov/title13/c008/sc04_1/index.html",
        "Subchapter IV. Registry of Paternity [Effective until Dec. 6, 2026].",
    ),
    (
        "https://delcode.delaware.gov/title13/c008/sc05_1/index.html",
        "Subchapter V. Genetic Testing [Effective until Dec. 6, 2026].",
    ),
    (
        "https://delcode.delaware.gov/title13/c008/sc06_1/index.html",
        (
            "Subchapter VI. Proceeding to Adjudicate Parentage "
            "[Effective until Dec. 6, 2026]."
        ),
    ),
    (
        "https://delcode.delaware.gov/title13/c008/sc07_1/index.html",
        (
            "Subchapter VII. Child of Assisted Reproduction "
            "[Effective until Dec. 6, 2026]."
        ),
    ),
    (
        "https://delcode.delaware.gov/title13/c008/sc08_1/index.html",
        (
            "Subchapter VIII. Gestational Carrier Agreement Act "
            "[Effective until Dec. 6, 2026]."
        ),
    ),
    (
        "https://delcode.delaware.gov/title13/c008/sc09_1/index.html",
        (
            "Subchapter IX. Miscellaneous Provisions "
            "[Effective until Dec. 6, 2026]."
        ),
    ),
)

# Exact structural replay of the retained official 2026-08-24 response.  The
# live page exposes 8561 and 8562 in its navigation and leaves their headings
# unmarked, but supplies no enacted body paragraphs and ends each section with
# the same official repeal disposition.
RETAINED_SECTION_FRAGMENT = """
<div id="CodeBody">
  <div class="Section">
    <div class="SectionHead" id="8560">
      § 8560. Definitions [Repealed].
    </div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=80&amp;chapter=154">
      repealed by 80 Del. Laws, c. 154, § 2, eff. Apr. 7, 2016.
    </a>
  </div>
  <div class="Section">
    <div class="SectionHead" id="8561">
      § 8561. Information to be provided to child care providers.
    </div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=80&amp;chapter=154">
      repealed by 80 Del. Laws, c. 154, § 2, eff. Apr. 7, 2016.
    </a>
  </div>
  <div class="Section">
    <div class="SectionHead" id="8562">§ 8562. Penalties.</div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=80&amp;chapter=154">
      repealed by 80 Del. Laws, c. 154, § 2, eff. Apr. 7, 2016.
    </a>
  </div>
  <div class="Section">
    <div class="SectionHead" id="8563">
      § 8563. Child Protection Registry check for health care.
    </div>
    <p class="subsection">(a) An employer shall request a registry check.</p>
    <a href="https://legis.delaware.gov/SessionLaws?volume=80&amp;chapter=154">
      80 Del. Laws, c. 154, § 2
    </a>
  </div>
  <div class="Section">
    <div class="SectionHead" id="8564">
      § 8564. Adult Abuse Registry check.
    </div>
    <p class="subsection">(a) A covered provider shall obtain a check.</p>
  </div>
</div>
"""

# Exact statutory-content structure from retained official body SHA-256
# 026af7ed096136122d9eb1d0a5bcb425672ca1aed0c78d43b0ffd75daffeedc6.
RETAINED_VACATED_SUBCHAPTER_FRAGMENT = """
<ul class="chaptersections"></ul>
<div id="TitleHead">
  <h1>TITLE 12</h1>
  <h4>Decedents’ Estates and Fiduciary Relations</h4>
  <h2>Descent and Distribution; Escheat</h2>
  <h3>CHAPTER 11. Escheats</h3>
  <h4>Subchapter III. Unclaimed Life Insurance Funds</h4>
</div>
<div id="CodeBody"></div>
"""

# Exact statutory-content structure from retained official body SHA-256
# 231b794859b15e45b9b411f6bba713a665a835ae80a648b55fb6af6ca229e077.
# The retained Title 16 parent body SHA-256
# 69f25dd2e082c315cce285788108baeb8b74c20abd7bb2253a1636be4ec1c473
# independently catalogs this exact URL and omitted heading.
RETAINED_OMITTED_CHAPTER_FRAGMENT = """
<ul class="chaptersections"></ul>
<div id="TitleHead">
  <h1>TITLE 16</h1>
  <h4>Health and Safety</h4>
  <h2>Regulatory Provisions Concerning Public Health</h2>
  <h3>CHAPTER 9A. [Omitted.]</h3>
  <h4></h4>
</div>
<div id="CodeBody">
  <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=257">
    81 Del. Laws, c. 257, § 1
  </a>;
</div>
"""

# Exact statutory-content structure from retained official body SHA-256
# b157b2d0597eeed61813c8402beba2b4fe973ada658a037b0b22c8eeed1f961b.
# The retained Title 16 parent catalogs this URL (body SHA-256
# 69f25dd2e082c315cce285788108baeb8b74c20abd7bb2253a1636be4ec1c473),
# while the cited Chapter 11, Subchapter VIII target contains active
# §§ 1180-1183 (body SHA-256
# 9a778b1e17720a9cb0d3ca36cf4630d34bd0d22bf60aa2611165ec4230fc81c2).
RETAINED_RELOCATED_CHAPTER_FRAGMENT = """
<ul class="chaptersections"></ul>
<div id="TitleHead">
  <h1>TITLE 16</h1>
  <h4>Health and Safety</h4>
  <h2>Community Firearm Recovery Program</h2>
  <h3>CHAPTER 105. Nursing Facility Quality Assessment Fund</h3>
  <h4></h4>
</div>
<div id="CodeBody">
  <p class="subsection">See subchapter VIII of Chapter 11 of this title,
  §§ 1180 of this title et seq., for the Nursing Facility Quality Assessment
  Fund as enacted by 78 Del. Laws, c. 286, § 2, effective June 28, 2012.</p>
</div>
"""

# Exact Section DOM from retained official body SHA-256
# 632e38d30c6d19d9d6ade8da9a9b3951ceb56a0102646d40cc7b8a1a51a050d8.
# The cited destination publishes active § 2501I with the same enactment
# history (retained target body SHA-256
# 0cad2afd8d4cb7d39052f960c83a3f79f3cfff7aa7ad24e1faa6c6a7ba979f55).
RETAINED_TRANSFERRED_SECTION_FRAGMENT = """
<div id="CodeBody">
  <div class="Section">
    <div class="SectionHead" id="7001">
      § 7001. Sealed container defense in product liability
      [Transferred to § 2501I of Title 6].
    </div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=66&amp;chapter=45">
      66 Del. Laws, c. 45, § 1
    </a>;
    <a href="https://legis.delaware.gov/SessionLaws?volume=70&amp;chapter=186">
      70 Del. Laws, c. 186, § 1
    </a>;
  </div>
</div>
"""

# Exact statutory-content structure from retained official body SHA-256
# 4178618295fb5aa5b50bebcc4109b0d0c5cc9efeb788ec84a88e0c1c938d2e36.
# The authenticated Title 19 PDF independently publishes this heading with no
# provisions, while retained active Title 18, Chapter 26 body SHA-256
# ee9b6d54eb7fcad0272f90b7ec3ba866541366584bf5030d70dee62ddb2e36b4
# publishes 23 active sections through § 2624, with § 2622 repealed.
RETAINED_EMPTY_RELOCATED_CHAPTER_FRAGMENT = """
<ul class="chaptersections"></ul>
<div id="TitleHead">
  <h1>TITLE 19</h1>
  <h4>Labor</h4>
  <h2>Workers’ Compensation</h2>
  <h3>CHAPTER 26. Workmen’s Compensation Rating</h3>
  <h4></h4>
</div>
<div id="CodeBody"></div>
"""

# Exact Section DOM from retained official body SHA-256
# 3ea1009aa37ed527d9bd770aefabb7ce7ae4771c85a9d2a39348e0360224d2db.
# The authenticated Title 21 PDF independently prints the same omitted
# heading and sole enactment history with no provision text.
RETAINED_OMITTED_SECTION_FRAGMENT = """
<div id="CodeBody">
  <div class="Section">
    <div class="SectionHead" id="7102">§ 7102. [Omitted].</div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=72&amp;chapter=456">
      72 Del. Laws, c. 456, § 1
    </a>;
  </div>
</div>
"""

# Exact statutory-content structure from retained official body SHA-256
# 74269ed2f55864fb8004ca5fdacd65bbe749cf4c2c1c79e1b45cd5596e2c1fc8.
# The same immediate Title 29 frontier publishes c102_1 as the active amended
# chapter under 85 Del. Laws, c. 263.
RETAINED_SUPERSEDED_CHAPTER_FRAGMENT = """
<ul class="chaptersections"></ul>
<div id="TitleHead">
  <h1>TITLE 29</h1>
  <h4>State Government</h4>
  <h2>General Regulations for State Agencies</h2>
  <h3>CHAPTER 102. Delaware Legislative Oversight and Sunset Act</h3>
  <h4></h4>
</div>
<div id="CodeBody">
  <a href="https://legis.delaware.gov/SessionLaws?volume=85&amp;chapter=263">
    85 Del. Laws, c. 263, § 5
  </a>;
</div>
"""

SUPERSEDING_CHAPTER_FRAGMENT = """
<div id="CodeBody">
  <div class="Section">
    <div class="SectionHead" id="10201">§ 10201. Definitions.</div>
    <p class="subsection">As used in this chapter, Committee means the
    Joint Legislative Oversight Committee established by this chapter.</p>
  </div>
</div>
"""

RETAINED_TRANSFERRED_GROUP_FRAGMENT = """
<div id="CodeBody">
  <div class="Section">
    <div class="SectionHead" id="3527, 3527A">
      §§ 3527, 3527A. Total return unitrusts; express total return unitrusts.
    </div>
    <p class="subsection">
      Transferred by 77 Del. Laws, c. 330, § 10, effective Aug. 1, 2010,
      to §§ 61-106 and 61-107 of this title.
    </p>
  </div>
</div>
"""

# Exact Section DOM retained in the official Title 14, Chapter 19, Subchapter
# II body SHA-256 d39734a9687a3a7ae005b61efda6b162d394af9a1501dffb05e7b97143704e15.
# Delaware publishes this former range with no heading title and an exact
# one-word transfer disposition as its only direct paragraph.
RETAINED_BARE_TRANSFERRED_RANGE_FRAGMENT = """
<div id="CodeBody">
  <div class="Section">
    <div class="SectionHead" id="1930-1943">
      §§ 1930-1943.
    </div>
    <p class="subsection">Transferred.</p>
  </div>
</div>
"""

RETAINED_REPEALED_GROUP_FRAGMENT = """
<div id="CodeBody">
  <div class="Section">
    <div class="SectionHead" id="705, 706">
      §§ 705, 706. Charge and custody of minor child; care of children.
    </div>
    <p class="subsection">Repealed by 59 Del. Laws, c. 569, § 1.</p>
  </div>
</div>
"""

# Exact Section DOM retained in the official Title 14, Chapter 55, Subchapter
# III body SHA-256 db1059bbfcf74001a353d9634412ebea2ff0644ddebae7eb1b4ee14480cab2eb.
# The repeal disposition includes both its effective date and an editorial
# cross-reference to the current provision.
RETAINED_REPEALED_PRESENT_LAW_FRAGMENT = """
<div id="CodeBody">
  <div class="Section">
    <div class="SectionHead" id="5530, 5531">
      §§ 5530, 5531. Administration of program; advisory committee.
    </div>
    <p class="subsection">
      Repealed by 73 Del. Laws, c. 188, § 8, effective July 17, 2001.
      For present law, see § 3424 of this title.
    </p>
  </div>
</div>
"""

# Exact Section DOM retained in the official Title 14, Chapter 1, Subchapter
# II body SHA-256 3eb8ee5325cc0d62b79d852c59ea15339332f791bae1fc80ed69bc867d598319.
# Delaware uses "expired under" here rather than its other "expired by
# operation of" disposition wording.
RETAINED_EXPIRED_UNDER_FRAGMENT = """
<div id="CodeBody">
  <div class="Section">
    <div class="SectionHead" id="133">§ 133. Health Advisory Council.</div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=75&amp;chapter=330">
      75 Del. Laws, c. 330, § 1
    </a>;
    <a href="https://legis.delaware.gov/SessionLaws?volume=75&amp;chapter=330">
      expired under 75 Del. Laws, c. 330, § 3, eff. June 30, 2011
    </a>;
  </div>
</div>
"""

# Exact Section DOM retained in the official Title 14, Chapter 17 body
# SHA-256 159693e0c55e2d4cfcb6b440dc1154903e7b1a8f7d1f309f92849ca3d57f2cbc.
# The current publication has no enacted body and records the expiration in a
# separate official link after the pilot program's enactment citation.
RETAINED_EXPIRED_PILOT_FRAGMENT = """
<div id="CodeBody">
  <div class="Section">
    <div class="SectionHead" id="1724">
      § 1724. Academic Achievement Awards Pilot Program.
    </div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=77&amp;chapter=196">
      77 Del. Laws, c. 196, § 2
    </a>;
    <a href="https://legis.delaware.gov/SessionLaws?volume=1&amp;chapter=2011">
      expired, eff. Oct. 1, 2011
    </a>;
  </div>
</div>
"""

# Exact Section DOM retained in the official Title 30, Chapter 54,
# Subchapter I body SHA-256
# a8729f94aa04be556a69a69bccd166e0abeb3f2b5cfc9476f18504b845dc8e11.
# The provision has no enacted body, and its ordered official history
# expressly expired it effective July 1, 1988.
RETAINED_EXPIRED_DISTRIBUTION_FRAGMENT = """
<div id="CodeBody">
  <div class="Section">
    <div class="SectionHead" id="5415">
      § 5415. Distribution of tax receipts.
    </div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=66&amp;chapter=94">
      66 Del. Laws, c. 94, § 1
    </a>;
    <a href="https://legis.delaware.gov/SessionLaws?volume=66&amp;chapter=94">
      expired by 66 Del. Laws, c. 94, § 2, eff. July 1, 1988
    </a>;
  </div>
</div>
"""

# Exact legal frontier retained for Title 30, Chapter 20D body SHA-256
# a0473a14210c770b0c3fe71c3e3c616c9048971d915171ca934a8b5d6fddc4ff.
# The retained official Title 30 parent (body SHA-256
# 4a86a2f5a39568a6dad40f0d4a1552d894934055f6af2b268242c6c0a37fca5d)
# independently labels this chapter ``[Expired]``.  The chapter retains every
# former locator in navigation, but each section has no enacted paragraph and
# ends with the same Jan. 1, 2022 expiration history.
RETAINED_EXPIRED_CHAPTER_FRAGMENT = """
<ul class="chaptersections">
  <li><a href="#20D-101">§ 20D-101</a></li>
  <li><a href="#20D-102">§ 20D-102</a></li>
  <li><a href="#20D-103">§ 20D-103</a></li>
  <li><a href="#20D-104">§ 20D-104</a></li>
  <li><a href="#20D-105">§ 20D-105</a></li>
  <li><a href="#20D-106">§ 20D-106</a></li>
  <li><a href="#20D-107">§ 20D-107</a></li>
  <li><a href="#20D-108">§ 20D-108</a></li>
  <li><a href="#20D-109">§ 20D-109</a></li>
  <li><a href="#20D-110">§ 20D-110</a></li>
</ul>
<div id="TitleHead">
  <h1>TITLE 30</h1>
  <h4>State Taxes</h4>
  <h2>Income, Inheritance and Estate Taxes</h2>
  <h3>CHAPTER 20D. Angel Investor Job Creation and Innovation Act [Expired]</h3>
  <h4></h4>
</div>
<div id="CodeBody">
  <div class="Section">
    <div class="SectionHead" id="20D-101">§ 20D-101. Definitions.</div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      81 Del. Laws, c. 244, § 3
    </a>;
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=374">
      81 Del. Laws, c. 374, § 53
    </a>;
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      expired by 81 Del. Laws, c. 244, § 5, eff. Jan. 1, 2022
    </a>;
  </div>
  <div class="Section">
    <div class="SectionHead" id="20D-102">
      § 20D-102. Certification of qualified small businesses.
    </div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      81 Del. Laws, c. 244, § 3
    </a>;
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      expired by 81 Del. Laws, c. 244, § 5, eff. Jan. 1, 2022
    </a>;
  </div>
  <div class="Section">
    <div class="SectionHead" id="20D-103">
      § 20D-103. Certification of qualified investors.
    </div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      81 Del. Laws, c. 244, § 3
    </a>;
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      expired by 81 Del. Laws, c. 244, § 5, eff. Jan. 1, 2022
    </a>;
  </div>
  <div class="Section">
    <div class="SectionHead" id="20D-104">
      § 20D-104. Certification of qualified funds.
    </div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      81 Del. Laws, c. 244, § 3
    </a>;
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      expired by 81 Del. Laws, c. 244, § 5, eff. Jan. 1, 2022
    </a>;
  </div>
  <div class="Section">
    <div class="SectionHead" id="20D-105">§ 20D-105. Tax credit allowed.</div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      81 Del. Laws, c. 244, § 3
    </a>;
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      expired by 81 Del. Laws, c. 244, § 5, eff. Jan. 1, 2022
    </a>;
  </div>
  <div class="Section">
    <div class="SectionHead" id="20D-106">
      § 20D-106. Issuance of tentative and final tax credit certificates.
    </div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      81 Del. Laws, c. 244, § 3
    </a>;
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      expired by 81 Del. Laws, c. 244, § 5, eff. Jan. 1, 2022
    </a>;
  </div>
  <div class="Section">
    <div class="SectionHead" id="20D-107">§ 20D-107. Required reports.</div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      81 Del. Laws, c. 244, § 3
    </a>;
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      expired by 81 Del. Laws, c. 244, § 5, eff. Jan. 1, 2022
    </a>;
  </div>
  <div class="Section">
    <div class="SectionHead" id="20D-108">
      § 20D-108. Revocation of tax credits.
    </div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      81 Del. Laws, c. 244, § 3
    </a>;
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      expired by 81 Del. Laws, c. 244, § 5, eff. Jan. 1, 2022
    </a>;
  </div>
  <div class="Section">
    <div class="SectionHead" id="20D-109">§ 20D-109. Data privacy.</div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      81 Del. Laws, c. 244, § 3
    </a>;
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      expired by 81 Del. Laws, c. 244, § 5, eff. Jan. 1, 2022
    </a>;
  </div>
  <div class="Section">
    <div class="SectionHead" id="20D-110">
      § 20D-110. Angel Investor Job Creation and Innovation Act
      Administration Fund.
    </div>
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      81 Del. Laws, c. 244, § 3
    </a>;
    <a href="https://legis.delaware.gov/SessionLaws?volume=81&amp;chapter=244">
      expired by 81 Del. Laws, c. 244, § 5, eff. Jan. 1, 2022
    </a>;
  </div>
</div>
"""

# Exact legal-frontier structure retained for body SHA-256
# bab3168f7b0bb102e35092420768613144d53f7a882153bf74dab155b739ccf0.
# The editorial root is c008_1, while each current-version child is physically
# published under c008/scNN_1.  This is an active descendant frontier, not an
# empty or repealed locator.
RETAINED_REDIRECTED_CHAPTER_FRAGMENT = """
<div id="content">
  <span class="breadcrumb delcrumb"><a href="../index.html">Title 13</a>
    &gt; Chapter 8</span>
  <span class="breadcrumb delcrumb pull-right text-right">
    <a href="../Title13.pdf">Authenticated PDF</a></span>
  <h2>Uniform Parentage Act [Effective until Dec. 6, 2026].</h2>
  <div>
    <div class="title-links"><a href="../../title13/c008/sc01_1/index.html">
      Subchapter I. General Provisions [Effective until Dec. 6, 2026].</a></div>
    <div class="title-links"><a href="../../title13/c008/sc02_1/index.html">
      Subchapter II. Parent-Child Relationship [Effective until Dec. 6, 2026].</a></div>
    <div class="title-links"><a href="../../title13/c008/sc03_1/index.html">
      Subchapter III. Voluntary Acknowledgement of Paternity [Effective until Dec. 6, 2026].</a></div>
    <div class="title-links"><a href="../../title13/c008/sc04_1/index.html">
      Subchapter IV. Registry of Paternity [Effective until Dec. 6, 2026].</a></div>
    <div class="title-links"><a href="../../title13/c008/sc05_1/index.html">
      Subchapter V. Genetic Testing [Effective until Dec. 6, 2026].</a></div>
    <div class="title-links"><a href="../../title13/c008/sc06_1/index.html">
      Subchapter VI. Proceeding to Adjudicate Parentage [Effective until Dec. 6, 2026].</a></div>
    <div class="title-links"><a href="../../title13/c008/sc07_1/index.html">
      Subchapter VII. Child of Assisted Reproduction [Effective until Dec. 6, 2026].</a></div>
    <div class="title-links"><a href="../../title13/c008/sc08_1/index.html">
      Subchapter VIII. Gestational Carrier Agreement Act [Effective until Dec. 6, 2026].</a></div>
    <div class="title-links"><a href="../../title13/c008/sc09_1/index.html">
      Subchapter IX. Miscellaneous Provisions [Effective until Dec. 6, 2026].</a></div>
  </div>
</div>
"""

# Exact concurrent-section structure retained in the official Title 9,
# Chapter 69, Subchapter I response (body SHA-256
# cffaff378e705bec64a88c51892fb4a96b7d435476794f648ff82644741fb975).
# Delaware deliberately publishes both versions under the same section number
# and duplicate HTML id.  Neither record may be discarded or guessed current.
CONCURRENT_SECTION_URL = (
    "https://delcode.delaware.gov/title9/c069/sc01/index.html"
)
RETAINED_CONCURRENT_SECTION_FRAGMENT = """
<div id="CodeBody">
  <div class="Section">
    <div class="SectionHead" id="6927">
      § 6927. Emergency Communication Systems [Effective until Feb. 1, 2027].
    </div>
    <p class="subsection">The zoning ordinance and regulations adopted
    pursuant to this chapter shall provide that newly constructed buildings
    of 25,000 square feet of gross floor area or more shall comply with
    § 2616 of this title.</p>
  </div>
  <div class="Section">
    <div class="SectionHead" id="6927">
      § 6927. Emergency Communication Systems [Effective Feb. 1, 2027].
    </div>
    <p class="subsection">The zoning ordinance and regulations adopted
    pursuant to this chapter shall provide that newly constructed, modified,
    or renovated buildings of 25,000 square feet of gross floor area or more
    shall comply with § 2616 of this title.</p>
  </div>
</div>
"""


def _concurrent_rows(
    html: str = RETAINED_CONCURRENT_SECTION_FRAGMENT,
) -> list[NormalizedStatute]:
    rows = parse_delaware_chapter_html(
        html,
        source_url=CONCURRENT_SECTION_URL,
        code_name="Delaware Code",
        title_number="9",
        chapter_number="69",
    )
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
    receipt = {
        "content_sha256": digest,
        "official_url": CONCURRENT_SECTION_URL,
        "source_transport": "direct",
    }
    for row in rows:
        structured_data = dict(row.structured_data or {})
        structured_data.update(
            {
                "content_sha256": digest,
                "transport_receipt": dict(receipt),
            }
        )
        row.structured_data = structured_data
    return rows


def test_retained_frontier_and_parser_agree_on_current_active_sections() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    soup = BeautifulSoup(RETAINED_SECTION_FRAGMENT, "html.parser")
    section_nodes = soup.select("div.Section")
    rows = parse_delaware_chapter_html(
        RETAINED_SECTION_FRAGMENT,
        source_url=SOURCE_URL,
        title_number="11",
        chapter_number="85",
    )

    parity = scraper._delaware_section_frontier_parity(section_nodes, rows)

    assert [row.section_number for row in rows] == ["8563", "8564"]
    assert parity == {
        "active_sections": ["8563", "8564"],
        "parsed_sections": ["8563", "8564"],
        "missing_sections": [],
        "unexpected_sections": [],
    }


def test_official_unmarked_repeal_allows_delaware_missing_comma_style() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    html = """
    <div class="Section">
      <div class="SectionHead" id="5516">
        § 5516. Procedure if requests or ballots sent to wrong official;
        absentee ballots received by election officers.
      </div>
      <a href="https://legis.delaware.gov/SessionLaws?volume=79&amp;chapter=275">
        repealed by 79 Del. Laws, c. 275 § 93, eff. July 1, 2015.
      </a>
    </div>
    """
    section = BeautifulSoup(html, "html.parser").select_one("div.Section")
    assert section is not None

    assert scraper._official_section_is_inactive_without_body(
        section,
        heading=(
            "§ 5516. Procedure if requests or ballots sent to wrong official; "
            "absentee ballots received by election officers."
        ),
        page_url="https://delcode.delaware.gov/title15/c055/index.html",
    )


def test_missing_comma_repeal_style_cannot_hide_enacted_body() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    html = """
    <div class="Section">
      <div class="SectionHead" id="5516">§ 5516. Procedure.</div>
      <p>This enacted paragraph remains operative.</p>
      <a href="https://legis.delaware.gov/SessionLaws?volume=79&amp;chapter=275">
        repealed by 79 Del. Laws, c. 275 § 93, eff. July 1, 2015.
      </a>
    </div>
    """
    section = BeautifulSoup(html, "html.parser").select_one("div.Section")
    assert section is not None

    assert not scraper._official_section_is_inactive_without_body(
        section,
        heading="§ 5516. Procedure.",
        page_url="https://delcode.delaware.gov/title15/c055/index.html",
    )


def test_retained_transfer_only_group_is_an_inactive_locator() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    soup = BeautifulSoup(RETAINED_TRANSFERRED_GROUP_FRAGMENT, "html.parser")
    section_nodes = soup.select("div.Section")

    rows = parse_delaware_chapter_html(
        RETAINED_TRANSFERRED_GROUP_FRAGMENT,
        source_url="https://delcode.delaware.gov/title12/c035/sc02/index.html",
        title_number="12",
        chapter_number="35",
    )

    assert rows == []
    assert scraper._official_section_is_inactive_without_body(
        section_nodes[0],
        heading="§§ 3527, 3527A. Total return unitrusts.",
    )
    assert scraper._delaware_section_frontier_parity(section_nodes, rows) == {
        "active_sections": [],
        "parsed_sections": [],
        "missing_sections": [],
        "unexpected_sections": [],
    }


def test_retained_bare_transferred_range_is_an_inactive_locator() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    source_url = "https://delcode.delaware.gov/title14/c019/sc02/index.html"
    soup = BeautifulSoup(RETAINED_BARE_TRANSFERRED_RANGE_FRAGMENT, "html.parser")
    section_nodes = soup.select("div.Section")

    rows = parse_delaware_chapter_html(
        RETAINED_BARE_TRANSFERRED_RANGE_FRAGMENT,
        source_url=source_url,
        title_number="14",
        chapter_number="19",
    )

    assert rows == []
    assert scraper._official_section_is_inactive_without_body(
        section_nodes[0],
        heading="§§ 1930-1943.",
        page_url=source_url,
    )
    assert scraper._delaware_section_frontier_parity(
        section_nodes,
        rows,
        page_url=source_url,
    ) == {
        "active_sections": [],
        "parsed_sections": [],
        "missing_sections": [],
        "unexpected_sections": [],
    }


@pytest.mark.parametrize(
    "replacement",
    [
        "Transferred",
        "Transferred conditionally.",
        "Funds transferred to the district remain appropriated.",
        "Transferred.</p><p>This range remains enacted.",
    ],
)
def test_bare_transfer_rule_cannot_hide_drift_or_enacted_text(
    replacement: str,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    source_url = "https://delcode.delaware.gov/title14/c019/sc02/index.html"
    html = RETAINED_BARE_TRANSFERRED_RANGE_FRAGMENT.replace(
        "Transferred.",
        replacement,
        1,
    )
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("div.Section")
    assert section is not None

    rows = parse_delaware_chapter_html(
        html,
        source_url=source_url,
        title_number="14",
        chapter_number="19",
    )

    assert [row.section_number for row in rows] == ["1930-1943"]
    assert not scraper._official_section_is_inactive_without_body(
        section,
        heading="§§ 1930-1943.",
        page_url=source_url,
    )


def test_retained_repeal_only_group_is_an_inactive_locator() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    soup = BeautifulSoup(RETAINED_REPEALED_GROUP_FRAGMENT, "html.parser")
    section_nodes = soup.select("div.Section")

    rows = parse_delaware_chapter_html(
        RETAINED_REPEALED_GROUP_FRAGMENT,
        source_url="https://delcode.delaware.gov/title13/c007/sc01/index.html",
        title_number="13",
        chapter_number="7",
    )

    assert rows == []
    assert scraper._official_section_is_inactive_without_body(
        section_nodes[0],
        heading="§§ 705, 706. Charge and custody of minor child.",
    )
    assert scraper._delaware_section_frontier_parity(section_nodes, rows) == {
        "active_sections": [],
        "parsed_sections": [],
        "missing_sections": [],
        "unexpected_sections": [],
    }


def test_retained_repeal_with_present_law_is_an_inactive_locator() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    source_url = "https://delcode.delaware.gov/title14/c055/sc03/index.html"
    soup = BeautifulSoup(RETAINED_REPEALED_PRESENT_LAW_FRAGMENT, "html.parser")
    section_nodes = soup.select("div.Section")

    rows = parse_delaware_chapter_html(
        RETAINED_REPEALED_PRESENT_LAW_FRAGMENT,
        source_url=source_url,
        title_number="14",
        chapter_number="55",
    )

    assert rows == []
    assert scraper._official_section_is_inactive_without_body(
        section_nodes[0],
        heading=(
            "§§ 5530, 5531. Administration of program; advisory committee."
        ),
        page_url=source_url,
    )
    assert scraper._delaware_section_frontier_parity(
        section_nodes,
        rows,
        page_url=source_url,
    ) == {
        "active_sections": [],
        "parsed_sections": [],
        "missing_sections": [],
        "unexpected_sections": [],
    }


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("§ 8, effective", "section 8, effective"),
        ("effective July 17, 2001", "effective sometime in 2001"),
        ("For present law, see", "For present law, consult"),
        (
            "For present law, see § 3424 of this title.",
            (
                "For present law, see § 3424 of this title. "
                "This program remains active."
            ),
        ),
        (
            "</p>\n  </div>",
            "</p><p>This program remains active.</p>\n  </div>",
        ),
    ],
)
def test_present_law_repeal_rule_rejects_drift_or_enacted_text(
    old: str,
    new: str,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    source_url = "https://delcode.delaware.gov/title14/c055/sc03/index.html"
    html = RETAINED_REPEALED_PRESENT_LAW_FRAGMENT.replace(old, new, 1)
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("div.Section")
    assert section is not None

    rows = parse_delaware_chapter_html(
        html,
        source_url=source_url,
        title_number="14",
        chapter_number="55",
    )

    assert [row.section_number for row in rows] == ["5530- 5531"]
    assert not scraper._official_section_is_inactive_without_body(
        section,
        heading=(
            "§§ 5530, 5531. Administration of program; advisory committee."
        ),
        page_url=source_url,
    )


def test_retained_expired_under_section_is_an_inactive_locator() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    soup = BeautifulSoup(RETAINED_EXPIRED_UNDER_FRAGMENT, "html.parser")
    section_nodes = soup.select("div.Section")

    rows = parse_delaware_chapter_html(
        RETAINED_EXPIRED_UNDER_FRAGMENT,
        source_url="https://delcode.delaware.gov/title14/c001/sc02/index.html",
        title_number="14",
        chapter_number="1",
    )

    assert rows == []
    assert scraper._official_section_is_inactive_without_body(
        section_nodes[0],
        heading="§ 133. Health Advisory Council.",
    )
    assert scraper._delaware_section_frontier_parity(section_nodes, rows) == {
        "active_sections": [],
        "parsed_sections": [],
        "missing_sections": [],
        "unexpected_sections": [],
    }


def test_retained_split_expiration_history_is_an_inactive_locator() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    soup = BeautifulSoup(RETAINED_EXPIRED_PILOT_FRAGMENT, "html.parser")
    section_nodes = soup.select("div.Section")

    rows = parse_delaware_chapter_html(
        RETAINED_EXPIRED_PILOT_FRAGMENT,
        source_url=EXPIRED_PILOT_URL,
        title_number="14",
        chapter_number="17",
    )

    assert rows == []
    assert scraper._official_section_is_inactive_without_body(
        section_nodes[0],
        heading="§ 1724. Academic Achievement Awards Pilot Program.",
        page_url=EXPIRED_PILOT_URL,
    )
    assert scraper._delaware_section_frontier_parity(
        section_nodes,
        rows,
        page_url=EXPIRED_PILOT_URL,
    ) == {
        "active_sections": [],
        "parsed_sections": [],
        "missing_sections": [],
        "unexpected_sections": [],
    }


@pytest.mark.anyio
async def test_retained_expired_distribution_history_closes_exact_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    soup = BeautifulSoup(RETAINED_EXPIRED_DISTRIBUTION_FRAGMENT, "html.parser")
    section_nodes = soup.select("div.Section")
    heading = section_nodes[0].select_one(".SectionHead")
    assert heading is not None

    rows = parse_delaware_chapter_html(
        RETAINED_EXPIRED_DISTRIBUTION_FRAGMENT,
        source_url=EXPIRED_DISTRIBUTION_URL,
        title_number="30",
        chapter_number="54",
    )

    assert rows == []
    assert scraper._official_section_is_inactive_without_body(
        section_nodes[0],
        heading=heading.get_text(" ", strip=True),
        page_url=EXPIRED_DISTRIBUTION_URL,
    )
    assert scraper._delaware_section_frontier_parity(
        section_nodes,
        rows,
        page_url=EXPIRED_DISTRIBUTION_URL,
    ) == {
        "active_sections": [],
        "parsed_sections": [],
        "missing_sections": [],
        "unexpected_sections": [],
    }

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == EXPIRED_DISTRIBUTION_URL
        scraper._record_fetch_event(
            provider="retained_exact_evidence",
            success=True,
        )
        return RETAINED_EXPIRED_DISTRIBUTION_FRAGMENT

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)
    assert await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url=EXPIRED_DISTRIBUTION_URL,
        chapter_label="Subchapter I. Realty Transfer Tax",
        max_statutes=None,
        _sibling_frontier_urls={EXPIRED_DISTRIBUTION_URL},
    ) == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("old", "new", "page_url"),
    [
        ('id="5415"', 'id="5415A"', EXPIRED_DISTRIBUTION_URL),
        (
            "Distribution of tax receipts",
            "Distribution of transfer tax receipts",
            EXPIRED_DISTRIBUTION_URL,
        ),
        (
            "volume=66&amp;chapter=94",
            "volume=66&amp;chapter=95",
            EXPIRED_DISTRIBUTION_URL,
        ),
        (
            "66 Del. Laws, c. 94, § 1",
            "66 Del. Laws, c. 94, § 2",
            EXPIRED_DISTRIBUTION_URL,
        ),
        (
            "c. 94, § 2, eff. July 1, 1988",
            "c. 94, § 3, eff. July 1, 1988",
            EXPIRED_DISTRIBUTION_URL,
        ),
        (
            "eff. July 1, 1988",
            "eff. July 2, 1988",
            EXPIRED_DISTRIBUTION_URL,
        ),
        (
            "</a>;\n  </div>",
            (
                "</a><a href='https://legis.delaware.gov/SessionLaws?"
                "volume=66&amp;chapter=95'>66 Del. Laws, c. 95, § 1</a>;"
                "\n  </div>"
            ),
            EXPIRED_DISTRIBUTION_URL,
        ),
        (
            "Distribution of tax receipts",
            "Distribution of tax receipts",
            f"{EXPIRED_DISTRIBUTION_URL}?revision=1",
        ),
        (
            "Distribution of tax receipts",
            "Distribution of tax receipts",
            "https://example.test/title30/c054/sc01/index.html",
        ),
        (
            "Distribution of tax receipts",
            "Distribution of tax receipts",
            "https://delcode.delaware.gov/title30/c054/sc02/index.html",
        ),
    ],
)
async def test_expired_distribution_history_rejects_boundary_drift(
    monkeypatch: pytest.MonkeyPatch,
    old: str,
    new: str,
    page_url: str,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    html = RETAINED_EXPIRED_DISTRIBUTION_FRAGMENT.replace(old, new, 1)
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("div.Section")
    heading = soup.select_one(".SectionHead")
    assert section is not None
    assert heading is not None
    assert not scraper._official_section_is_inactive_without_body(
        section,
        heading=heading.get_text(" ", strip=True),
        page_url=page_url,
    )

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == page_url
        scraper._record_fetch_event(
            provider="retained_exact_evidence",
            success=True,
        )
        return html

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)
    with pytest.raises(RuntimeError, match="omitted active official sections"):
        await scraper._parse_chapter_sections(
            code_name="Delaware Code",
            chapter_url=page_url,
            chapter_label="Subchapter I. Realty Transfer Tax",
            max_statutes=None,
            _sibling_frontier_urls={page_url},
        )


def test_expired_distribution_rule_cannot_hide_substantive_text() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    html = RETAINED_EXPIRED_DISTRIBUTION_FRAGMENT.replace(
        "</div>\n    <a href=",
        "</div><p>This distribution remains enacted.</p>\n    <a href=",
        1,
    )
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("div.Section")
    heading = soup.select_one(".SectionHead")
    assert section is not None
    assert heading is not None

    rows = parse_delaware_chapter_html(
        html,
        source_url=EXPIRED_DISTRIBUTION_URL,
        title_number="30",
        chapter_number="54",
    )

    assert [row.section_number for row in rows] == ["5415"]
    assert rows[0].full_text == "This distribution remains enacted."
    assert not scraper._official_section_is_inactive_without_body(
        section,
        heading=heading.get_text(" ", strip=True),
        page_url=EXPIRED_DISTRIBUTION_URL,
    )


@pytest.mark.anyio
async def test_retained_expired_chapter_closes_exact_history_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    soup = BeautifulSoup(RETAINED_EXPIRED_CHAPTER_FRAGMENT, "html.parser")
    section_nodes = soup.select("div.Section")
    rows = parse_delaware_chapter_html(
        RETAINED_EXPIRED_CHAPTER_FRAGMENT,
        source_url=EXPIRED_CHAPTER_URL,
        title_number="30",
        chapter_number="20D",
    )

    assert rows == []
    assert len(section_nodes) == 10
    assert all(
        scraper._official_section_is_inactive_without_body(
            section,
            heading=section.select_one(".SectionHead").get_text(" ", strip=True),
            page_url=EXPIRED_CHAPTER_URL,
        )
        for section in section_nodes
    )
    assert scraper._delaware_section_frontier_parity(
        section_nodes,
        rows,
        page_url=EXPIRED_CHAPTER_URL,
    ) == {
        "active_sections": [],
        "parsed_sections": [],
        "missing_sections": [],
        "unexpected_sections": [],
    }

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == EXPIRED_CHAPTER_URL
        scraper._record_fetch_event(
            provider="retained_exact_evidence",
            success=True,
        )
        return RETAINED_EXPIRED_CHAPTER_FRAGMENT

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)
    assert await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url=EXPIRED_CHAPTER_URL,
        chapter_label=(
            "Chapter 20D. Angel Investor Job Creation and Innovation Act "
            "[Expired]"
        ),
        max_statutes=None,
        _sibling_frontier_urls={EXPIRED_CHAPTER_URL},
    ) == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("html", "page_url"),
    [
        (
            RETAINED_EXPIRED_CHAPTER_FRAGMENT.replace(
                "Innovation Act [Expired]",
                "Innovation Act [Current]",
                1,
            ),
            EXPIRED_CHAPTER_URL,
        ),
        (
            RETAINED_EXPIRED_CHAPTER_FRAGMENT.replace(
                '<li><a href="#20D-110">§ 20D-110</a></li>',
                "",
                1,
            ),
            EXPIRED_CHAPTER_URL,
        ),
        (
            RETAINED_EXPIRED_CHAPTER_FRAGMENT.replace(
                "§ 20D-106. Issuance",
                "§ 20D-106. Administration",
                1,
            ),
            EXPIRED_CHAPTER_URL,
        ),
        (
            RETAINED_EXPIRED_CHAPTER_FRAGMENT.replace(
                "chapter=374",
                "chapter=375",
                1,
            ),
            EXPIRED_CHAPTER_URL,
        ),
        (
            RETAINED_EXPIRED_CHAPTER_FRAGMENT.replace(
                "§ 5, eff. Jan. 1, 2022",
                "§ 6, eff. Jan. 1, 2022",
                1,
            ),
            EXPIRED_CHAPTER_URL,
        ),
        (
            RETAINED_EXPIRED_CHAPTER_FRAGMENT.replace(
                "</div>\n    <a href=",
                "</div><p>This provision remains enacted.</p>\n    <a href=",
                1,
            ),
            EXPIRED_CHAPTER_URL,
        ),
        (
            RETAINED_EXPIRED_CHAPTER_FRAGMENT.replace(
                'class="Section"',
                'class="FormerSection"',
                1,
            ),
            EXPIRED_CHAPTER_URL,
        ),
        (
            RETAINED_EXPIRED_CHAPTER_FRAGMENT,
            f"{EXPIRED_CHAPTER_URL}?version=expired",
        ),
        (
            RETAINED_EXPIRED_CHAPTER_FRAGMENT,
            "https://delcode.delaware.gov/title30/c020e/index.html",
        ),
    ],
)
async def test_expired_chapter_history_rejects_any_boundary_drift(
    monkeypatch: pytest.MonkeyPatch,
    html: str,
    page_url: str,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == page_url
        scraper._record_fetch_event(
            provider="retained_exact_evidence",
            success=True,
        )
        return html

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)
    with pytest.raises(RuntimeError, match="omitted active official sections"):
        await scraper._parse_chapter_sections(
            code_name="Delaware Code",
            chapter_url=page_url,
            chapter_label=(
                "Chapter 20D. Angel Investor Job Creation and Innovation Act "
                "[Expired]"
            ),
            max_statutes=None,
            _sibling_frontier_urls={page_url},
        )


def test_retained_transferred_section_is_an_inactive_locator() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    soup = BeautifulSoup(RETAINED_TRANSFERRED_SECTION_FRAGMENT, "html.parser")
    section_nodes = soup.select("div.Section")
    heading = section_nodes[0].select_one(".SectionHead")
    assert heading is not None

    rows = parse_delaware_chapter_html(
        RETAINED_TRANSFERRED_SECTION_FRAGMENT,
        source_url=TRANSFERRED_SECTION_URL,
        title_number="18",
        chapter_number="70",
    )

    assert rows == []
    assert scraper._official_section_is_inactive_without_body(
        section_nodes[0],
        heading=heading.get_text(" ", strip=True),
        page_url=TRANSFERRED_SECTION_URL,
    )
    assert scraper._delaware_section_frontier_parity(
        section_nodes,
        rows,
        page_url=TRANSFERRED_SECTION_URL,
    ) == {
        "active_sections": [],
        "parsed_sections": [],
        "missing_sections": [],
        "unexpected_sections": [],
    }
    assert TRANSFERRED_SECTION_TARGET_URL.endswith("/title6/c025i/index.html")


@pytest.mark.parametrize(
    ("old", "new", "page_url"),
    [
        ('id="7001"', 'id="7001A"', TRANSFERRED_SECTION_URL),
        ("§ 2501I of Title 6", "§ 2502I of Title 6", TRANSFERRED_SECTION_URL),
        ("§ 2501I of Title 6", "§ 2501I of Title 7", TRANSFERRED_SECTION_URL),
        (
            "volume=70&amp;chapter=186",
            "volume=70&amp;chapter=187",
            TRANSFERRED_SECTION_URL,
        ),
        (
            "70 Del. Laws, c. 186, § 1",
            "70 Del. Laws, c. 186, § 2",
            TRANSFERRED_SECTION_URL,
        ),
        (
            "</div>\n    <a href=",
            "</div><p>This section remains enacted.</p>\n    <a href=",
            TRANSFERRED_SECTION_URL,
        ),
        ("§ 2501I of Title 6", "§ 2501I of Title 6", ""),
    ],
)
def test_transferred_section_history_rejects_any_evidence_drift(
    old: str,
    new: str,
    page_url: str,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    html = RETAINED_TRANSFERRED_SECTION_FRAGMENT.replace(old, new, 1)
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("div.Section")
    heading = soup.select_one(".SectionHead")
    assert section is not None
    assert heading is not None

    assert not scraper._official_section_is_inactive_without_body(
        section,
        heading=heading.get_text(" ", strip=True),
        page_url=page_url,
    )


def test_retained_omitted_section_is_an_inactive_locator() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    soup = BeautifulSoup(RETAINED_OMITTED_SECTION_FRAGMENT, "html.parser")
    section_nodes = soup.select("div.Section")
    heading = section_nodes[0].select_one(".SectionHead")
    assert heading is not None

    rows = parse_delaware_chapter_html(
        RETAINED_OMITTED_SECTION_FRAGMENT,
        source_url=OMITTED_SECTION_URL,
        title_number="21",
        chapter_number="71",
    )

    assert rows == []
    assert scraper._official_section_is_inactive_without_body(
        section_nodes[0],
        heading=heading.get_text(" ", strip=True),
        page_url=OMITTED_SECTION_URL,
    )
    assert scraper._delaware_section_frontier_parity(
        section_nodes,
        rows,
        page_url=OMITTED_SECTION_URL,
    ) == {
        "active_sections": [],
        "parsed_sections": [],
        "missing_sections": [],
        "unexpected_sections": [],
    }


@pytest.mark.parametrize(
    ("old", "new", "page_url"),
    [
        ('id="7102"', 'id="7102A"', OMITTED_SECTION_URL),
        ("§ 7102. [Omitted].", "§ 7102. [Omission].", OMITTED_SECTION_URL),
        (
            "volume=72&amp;chapter=456",
            "volume=72&amp;chapter=457",
            OMITTED_SECTION_URL,
        ),
        (
            "72 Del. Laws, c. 456, § 1",
            "72 Del. Laws, c. 456, § 2",
            OMITTED_SECTION_URL,
        ),
        (
            "</a>;",
            (
                "</a><a href='https://legis.delaware.gov/SessionLaws?"
                "volume=72&amp;chapter=457'>72 Del. Laws, c. 457, § 1</a>;"
            ),
            OMITTED_SECTION_URL,
        ),
        (
            "</div>\n    <a href=",
            "</div><p>This section remains enacted.</p>\n    <a href=",
            OMITTED_SECTION_URL,
        ),
        ("§ 7102. [Omitted].", "§ 7102. [Omitted].", ""),
    ],
)
def test_omitted_section_history_rejects_any_evidence_drift(
    old: str,
    new: str,
    page_url: str,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    html = RETAINED_OMITTED_SECTION_FRAGMENT.replace(old, new, 1)
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("div.Section")
    heading = soup.select_one(".SectionHead")
    assert section is not None
    assert heading is not None

    assert not scraper._official_section_is_inactive_without_body(
        section,
        heading=heading.get_text(" ", strip=True),
        page_url=page_url,
    )


@pytest.mark.parametrize(
    ("old", "new", "page_url"),
    [
        ("id=\"1724\"", "id=\"1724A\"", EXPIRED_PILOT_URL),
        (
            "77 Del. Laws, c. 196, § 2",
            "77 Del. Laws, c. 196, § 3",
            EXPIRED_PILOT_URL,
        ),
        (
            "volume=1&amp;chapter=2011",
            "volume=1&amp;chapter=2012",
            EXPIRED_PILOT_URL,
        ),
        (
            "expired, eff. Oct. 1, 2011",
            "expired, eff. Oct. 2, 2011",
            EXPIRED_PILOT_URL,
        ),
        (
            "</div>\n    <a href=",
            "</div><p>This pilot remains enacted.</p>\n    <a href=",
            EXPIRED_PILOT_URL,
        ),
        ("Academic Achievement", "Academic Progress", EXPIRED_PILOT_URL),
        ("Academic Achievement", "Academic Achievement", ""),
        (
            "Academic Achievement",
            "Academic Achievement",
            "https://example.test/title14/c017/index.html",
        ),
    ],
)
def test_split_expiration_history_rejects_any_evidence_drift(
    old: str,
    new: str,
    page_url: str,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    html = RETAINED_EXPIRED_PILOT_FRAGMENT.replace(old, new, 1)
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("div.Section")
    assert section is not None
    heading = section.select_one(".SectionHead")
    assert heading is not None

    assert not scraper._official_section_is_inactive_without_body(
        section,
        heading=heading.get_text(" ", strip=True),
        page_url=page_url,
    )


@pytest.mark.parametrize(
    ("href", "body"),
    [
        (
            "https://example.test/SessionLaws?volume=75&amp;chapter=330",
            "",
        ),
        (
            "https://legis.delaware.gov/SessionLaws?volume=75&amp;chapter=330",
            "<p>This council remains established.</p>",
        ),
    ],
)
def test_expired_under_disposition_cannot_hide_unverified_or_enacted_body(
    href: str,
    body: str,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    soup = BeautifulSoup(
        "<div class='Section'><div class='SectionHead'>"
        "§ 133. Health Advisory Council.</div>"
        f"{body}<a href='{href}'>expired under 75 Del. Laws, c. 330, § 3, "
        "eff. June 30, 2011</a></div>",
        "html.parser",
    )
    section = soup.select_one("div.Section")
    assert section is not None

    assert not scraper._official_section_is_inactive_without_body(
        section,
        heading="§ 133. Health Advisory Council.",
    )


def test_transfer_disposition_cannot_hide_enacted_body() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    html = RETAINED_TRANSFERRED_GROUP_FRAGMENT.replace(
        "</p>\n  </div>",
        "</p><p class='subsection'>(a) This section remains enacted.</p>\n  </div>",
    )
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("div.Section")
    assert section is not None

    rows = parse_delaware_chapter_html(
        html,
        source_url="https://delcode.delaware.gov/title12/c035/sc02/index.html",
        title_number="12",
        chapter_number="35",
    )

    assert [row.section_number for row in rows] == ["3527- 3527A"]
    assert not scraper._official_section_is_inactive_without_body(
        section,
        heading="§§ 3527, 3527A. Total return unitrusts.",
    )


@pytest.mark.anyio
async def test_retained_current_chapter_redirect_traverses_exact_child_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    pages = {CURRENT_CHAPTER_8_URL: RETAINED_REDIRECTED_CHAPTER_FRAGMENT}
    for position, (child_url, _label) in enumerate(
        CURRENT_CHAPTER_8_CHILDREN,
        start=1,
    ):
        section_number = f"8{position:02d}"
        pages[child_url] = (
            "<div id='CodeBody'><div class='Section'>"
            f"<div class='SectionHead' id='{section_number}'>"
            f"§ {section_number}. Current provision.</div>"
            "<p>This provision remains effective.</p></div></div>"
        )

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url in pages
        scraper._record_fetch_event(provider="retained_exact_evidence", success=True)
        return pages[url]

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    rows = await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url=CURRENT_CHAPTER_8_URL,
        chapter_label=CURRENT_CHAPTER_8_LABEL,
        max_statutes=None,
        _sibling_frontier_urls={CURRENT_CHAPTER_8_URL, FUTURE_CHAPTER_8_URL},
    )

    assert [row.section_number for row in rows] == [
        f"8{position:02d}" for position in range(1, 10)
    ]
    assert [row.source_url.split("#", 1)[0] for row in rows] == [
        url for url, _label in CURRENT_CHAPTER_8_CHILDREN
    ]
    assert all(
        row.structured_data["official_parent_chapter_url"]
        == CURRENT_CHAPTER_8_URL
        for row in rows
    )
    assert all(
        row.structured_data["official_descendant_pages_visited"] == 9
        for row in rows
    )


@pytest.mark.anyio
async def test_current_chapter_redirect_requires_complete_parent_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == CURRENT_CHAPTER_8_URL
        scraper._record_fetch_event(provider="retained_exact_evidence", success=True)
        return RETAINED_REDIRECTED_CHAPTER_FRAGMENT

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    with pytest.raises(RuntimeError, match="redirected descendant frontier did not close"):
        await scraper._parse_chapter_sections(
            code_name="Delaware Code",
            chapter_url=CURRENT_CHAPTER_8_URL,
            chapter_label=CURRENT_CHAPTER_8_LABEL,
            max_statutes=None,
            _sibling_frontier_urls={CURRENT_CHAPTER_8_URL},
        )


@pytest.mark.parametrize(
    ("html", "chapter_label"),
    [
        (
            RETAINED_REDIRECTED_CHAPTER_FRAGMENT.replace(
                "Subchapter IX. Miscellaneous Provisions",
                "Subchapter IX. Unknown Provisions",
            ),
            CURRENT_CHAPTER_8_LABEL,
        ),
        (
            RETAINED_REDIRECTED_CHAPTER_FRAGMENT.replace(
                "Uniform Parentage Act [Effective until Dec. 6, 2026].</h2>",
                "Unknown Act [Effective until Dec. 6, 2026].</h2>",
            ),
            CURRENT_CHAPTER_8_LABEL,
        ),
        (
            RETAINED_REDIRECTED_CHAPTER_FRAGMENT,
            "Chapter 8. Uniform Parentage Act [Effective Dec. 6, 2026].",
        ),
    ],
)
def test_current_chapter_redirect_rejects_heading_or_child_drift(
    html: str,
    chapter_label: str,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    assert scraper._verified_redirected_descendant_index_links(
        BeautifulSoup(html, "html.parser"),
        page_url=CURRENT_CHAPTER_8_URL,
        chapter_label=chapter_label,
        sibling_frontier_urls={CURRENT_CHAPTER_8_URL, FUTURE_CHAPTER_8_URL},
    ) == []


@pytest.mark.anyio
async def test_strict_runtime_accepts_retained_unmarked_repeal_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == SOURCE_URL
        scraper._record_fetch_event(provider="requests_direct", success=True)
        return RETAINED_SECTION_FRAGMENT

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    rows = await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url=SOURCE_URL,
        chapter_label="Subchapter V",
        max_statutes=None,
    )

    assert [row.section_number for row in rows] == ["8563", "8564"]


@pytest.mark.parametrize(
    ("href", "body"),
    [
        (
            "https://example.test/SessionLaws?volume=80&amp;chapter=154",
            "",
        ),
        (
            "https://legis.delaware.gov/SessionLaws?volume=80&amp;chapter=154",
            "<p>This section remains enacted.</p>",
        ),
    ],
)
def test_repeal_disposition_requires_official_history_and_no_enacted_body(
    href: str,
    body: str,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    soup = BeautifulSoup(
        "<div class='Section'><div class='SectionHead'>§ 9000. Example.</div>"
        f"{body}<a href='{href}'>repealed by 80 Del. Laws, c. 154, § 2</a>"
        "</div>",
        "html.parser",
    )
    section = soup.select_one("div.Section")
    assert section is not None

    assert not scraper._official_section_is_inactive_without_body(
        section,
        heading="§ 9000. Example.",
    )


@pytest.mark.anyio
async def test_retained_vacated_subchapter_is_a_closed_empty_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == VACATED_SUBCHAPTER_URL
        scraper._record_fetch_event(provider="retained_exact_evidence", success=True)
        return RETAINED_VACATED_SUBCHAPTER_FRAGMENT

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    rows = await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url=VACATED_SUBCHAPTER_URL,
        chapter_label="Subchapter III. Unclaimed Life Insurance Funds",
        max_statutes=None,
        _sibling_frontier_urls={VACATED_SUBCHAPTER_URL},
    )

    assert rows == []


@pytest.mark.anyio
async def test_retained_omitted_chapter_is_a_closed_empty_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == OMITTED_CHAPTER_URL
        scraper._record_fetch_event(
            provider="retained_exact_evidence",
            success=True,
        )
        return RETAINED_OMITTED_CHAPTER_FRAGMENT

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    rows = await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url=OMITTED_CHAPTER_URL,
        chapter_label="Chapter 9A. [Omitted.]",
        max_statutes=None,
        _sibling_frontier_urls={OMITTED_CHAPTER_URL},
    )

    assert rows == []
    assert scraper._verified_omitted_citation_only_index(
        BeautifulSoup(RETAINED_OMITTED_CHAPTER_FRAGMENT, "html.parser"),
        page_url=OMITTED_CHAPTER_URL,
        chapter_label="Chapter 9A. [Omitted.]",
        sibling_frontier_urls={OMITTED_CHAPTER_URL},
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("html", "chapter_label", "siblings"),
    [
        (
            RETAINED_OMITTED_CHAPTER_FRAGMENT.replace(
                "CHAPTER 9A. [Omitted.]",
                "CHAPTER 9A. [Reserved.]",
            ),
            "Chapter 9A. [Omitted.]",
            {OMITTED_CHAPTER_URL},
        ),
        (
            RETAINED_OMITTED_CHAPTER_FRAGMENT.replace(
                "volume=81&amp;chapter=257",
                "volume=81&amp;chapter=258",
            ),
            "Chapter 9A. [Omitted.]",
            {OMITTED_CHAPTER_URL},
        ),
        (
            RETAINED_OMITTED_CHAPTER_FRAGMENT.replace(
                "81 Del. Laws, c. 257, § 1",
                "81 Del. Laws, c. 257, § 2",
            ),
            "Chapter 9A. [Omitted.]",
            {OMITTED_CHAPTER_URL},
        ),
        (
            RETAINED_OMITTED_CHAPTER_FRAGMENT.replace(
                "</a>;",
                "</a>;<p>This chapter remains enacted.</p>",
            ),
            "Chapter 9A. [Omitted.]",
            {OMITTED_CHAPTER_URL},
        ),
        (
            RETAINED_OMITTED_CHAPTER_FRAGMENT,
            "Chapter 9A. Current Provisions",
            {OMITTED_CHAPTER_URL},
        ),
        (
            RETAINED_OMITTED_CHAPTER_FRAGMENT,
            "Chapter 9A. [Omitted.]",
            set(),
        ),
    ],
)
async def test_omitted_chapter_boundary_rejects_any_evidence_drift(
    monkeypatch: pytest.MonkeyPatch,
    html: str,
    chapter_label: str,
    siblings: set[str],
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == OMITTED_CHAPTER_URL
        scraper._record_fetch_event(
            provider="retained_exact_evidence",
            success=True,
        )
        return html

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    assert not scraper._verified_omitted_citation_only_index(
        BeautifulSoup(html, "html.parser"),
        page_url=OMITTED_CHAPTER_URL,
        chapter_label=chapter_label,
        sibling_frontier_urls=siblings,
    )
    with pytest.raises(RuntimeError, match="exposed no section frontier"):
        await scraper._parse_chapter_sections(
            code_name="Delaware Code",
            chapter_url=OMITTED_CHAPTER_URL,
            chapter_label=chapter_label,
            max_statutes=None,
            _sibling_frontier_urls=siblings,
        )


@pytest.mark.anyio
async def test_retained_relocated_chapter_is_a_closed_empty_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == RELOCATED_CHAPTER_URL
        scraper._record_fetch_event(
            provider="retained_exact_evidence",
            success=True,
        )
        return RETAINED_RELOCATED_CHAPTER_FRAGMENT

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    rows = await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url=RELOCATED_CHAPTER_URL,
        chapter_label=(
            "Chapter 105. Nursing Facility Quality Assessment Fund"
        ),
        max_statutes=None,
        _sibling_frontier_urls={RELOCATED_CHAPTER_URL},
    )

    assert rows == []
    assert scraper._verified_relocated_citation_only_index(
        BeautifulSoup(RETAINED_RELOCATED_CHAPTER_FRAGMENT, "html.parser"),
        page_url=RELOCATED_CHAPTER_URL,
        chapter_label=(
            "Chapter 105. Nursing Facility Quality Assessment Fund"
        ),
        sibling_frontier_urls={RELOCATED_CHAPTER_URL},
    )
    assert (
        scraper._DE_RELOCATED_CITATION_ONLY_INDEXES[
            "/title16/c105/index.html"
        ]["target_url"]
        == RELOCATED_TARGET_URL
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("html", "chapter_label", "siblings"),
    [
        (
            RETAINED_RELOCATED_CHAPTER_FRAGMENT.replace(
                "Community Firearm Recovery Program",
                "Nursing Facility Regulation",
            ),
            "Chapter 105. Nursing Facility Quality Assessment Fund",
            {RELOCATED_CHAPTER_URL},
        ),
        (
            RETAINED_RELOCATED_CHAPTER_FRAGMENT.replace(
                "§§ 1180 of this title et seq.",
                "§§ 1181 of this title et seq.",
            ),
            "Chapter 105. Nursing Facility Quality Assessment Fund",
            {RELOCATED_CHAPTER_URL},
        ),
        (
            RETAINED_RELOCATED_CHAPTER_FRAGMENT.replace(
                "c. 286, § 2",
                "c. 286, § 3",
            ),
            "Chapter 105. Nursing Facility Quality Assessment Fund",
            {RELOCATED_CHAPTER_URL},
        ),
        (
            RETAINED_RELOCATED_CHAPTER_FRAGMENT.replace(
                "</p>\n</div>",
                "</p><p>This chapter remains enacted.</p>\n</div>",
            ),
            "Chapter 105. Nursing Facility Quality Assessment Fund",
            {RELOCATED_CHAPTER_URL},
        ),
        (
            RETAINED_RELOCATED_CHAPTER_FRAGMENT,
            "Chapter 105. Current Nursing Facility Provisions",
            {RELOCATED_CHAPTER_URL},
        ),
        (
            RETAINED_RELOCATED_CHAPTER_FRAGMENT,
            "Chapter 105. Nursing Facility Quality Assessment Fund",
            set(),
        ),
    ],
)
async def test_relocated_chapter_boundary_rejects_any_evidence_drift(
    monkeypatch: pytest.MonkeyPatch,
    html: str,
    chapter_label: str,
    siblings: set[str],
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == RELOCATED_CHAPTER_URL
        scraper._record_fetch_event(
            provider="retained_exact_evidence",
            success=True,
        )
        return html

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    assert not scraper._verified_relocated_citation_only_index(
        BeautifulSoup(html, "html.parser"),
        page_url=RELOCATED_CHAPTER_URL,
        chapter_label=chapter_label,
        sibling_frontier_urls=siblings,
    )
    with pytest.raises(RuntimeError, match="exposed no section frontier"):
        await scraper._parse_chapter_sections(
            code_name="Delaware Code",
            chapter_url=RELOCATED_CHAPTER_URL,
            chapter_label=chapter_label,
            max_statutes=None,
            _sibling_frontier_urls=siblings,
        )


@pytest.mark.anyio
async def test_retained_authenticated_empty_relocated_chapter_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == EMPTY_RELOCATED_CHAPTER_URL
        scraper._record_fetch_event(
            provider="retained_exact_evidence",
            success=True,
        )
        return RETAINED_EMPTY_RELOCATED_CHAPTER_FRAGMENT

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    rows = await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url=EMPTY_RELOCATED_CHAPTER_URL,
        chapter_label="Chapter 26. Workmen’s Compensation Rating",
        max_statutes=None,
        _sibling_frontier_urls={EMPTY_RELOCATED_CHAPTER_URL},
    )

    assert rows == []
    assert scraper._verified_authenticated_empty_relocated_index(
        BeautifulSoup(
            RETAINED_EMPTY_RELOCATED_CHAPTER_FRAGMENT,
            "html.parser",
        ),
        page_url=EMPTY_RELOCATED_CHAPTER_URL,
        chapter_label="Chapter 26. Workmen’s Compensation Rating",
        sibling_frontier_urls={EMPTY_RELOCATED_CHAPTER_URL},
    )
    assert (
        scraper._DE_AUTHENTICATED_EMPTY_RELOCATED_INDEXES[
            "/title19/c026/index.html"
        ]["target_url"]
        == EMPTY_RELOCATED_TARGET_URL
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("html", "chapter_label", "siblings", "page_url"),
    [
        (
            RETAINED_EMPTY_RELOCATED_CHAPTER_FRAGMENT.replace(
                "Workers’ Compensation",
                "Workplace Compensation",
            ),
            "Chapter 26. Workmen’s Compensation Rating",
            {EMPTY_RELOCATED_CHAPTER_URL},
            EMPTY_RELOCATED_CHAPTER_URL,
        ),
        (
            RETAINED_EMPTY_RELOCATED_CHAPTER_FRAGMENT.replace(
                "CHAPTER 26. Workmen’s Compensation Rating",
                "CHAPTER 26. Current Compensation Rating",
            ),
            "Chapter 26. Workmen’s Compensation Rating",
            {EMPTY_RELOCATED_CHAPTER_URL},
            EMPTY_RELOCATED_CHAPTER_URL,
        ),
        (
            RETAINED_EMPTY_RELOCATED_CHAPTER_FRAGMENT.replace(
                '<ul class="chaptersections"></ul>',
                '<ul class="chaptersections"><li>§ 2601</li></ul>',
            ),
            "Chapter 26. Workmen’s Compensation Rating",
            {EMPTY_RELOCATED_CHAPTER_URL},
            EMPTY_RELOCATED_CHAPTER_URL,
        ),
        (
            RETAINED_EMPTY_RELOCATED_CHAPTER_FRAGMENT.replace(
                '<div id="CodeBody"></div>',
                '<div id="CodeBody"><p>Current law remains.</p></div>',
            ),
            "Chapter 26. Workmen’s Compensation Rating",
            {EMPTY_RELOCATED_CHAPTER_URL},
            EMPTY_RELOCATED_CHAPTER_URL,
        ),
        (
            RETAINED_EMPTY_RELOCATED_CHAPTER_FRAGMENT,
            "Chapter 26. Current Compensation Rating",
            {EMPTY_RELOCATED_CHAPTER_URL},
            EMPTY_RELOCATED_CHAPTER_URL,
        ),
        (
            RETAINED_EMPTY_RELOCATED_CHAPTER_FRAGMENT,
            "Chapter 26. Workmen’s Compensation Rating",
            set(),
            EMPTY_RELOCATED_CHAPTER_URL,
        ),
        (
            RETAINED_EMPTY_RELOCATED_CHAPTER_FRAGMENT,
            "Chapter 26. Workmen’s Compensation Rating",
            {EMPTY_RELOCATED_CHAPTER_URL},
            f"{EMPTY_RELOCATED_CHAPTER_URL}?current=1",
        ),
    ],
)
async def test_authenticated_empty_relocation_rejects_evidence_drift(
    monkeypatch: pytest.MonkeyPatch,
    html: str,
    chapter_label: str,
    siblings: set[str],
    page_url: str,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == page_url
        scraper._record_fetch_event(
            provider="retained_exact_evidence",
            success=True,
        )
        return html

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    assert not scraper._verified_authenticated_empty_relocated_index(
        BeautifulSoup(html, "html.parser"),
        page_url=page_url,
        chapter_label=chapter_label,
        sibling_frontier_urls=siblings,
    )
    with pytest.raises(RuntimeError, match="exposed no section frontier"):
        await scraper._parse_chapter_sections(
            code_name="Delaware Code",
            chapter_url=page_url,
            chapter_label=chapter_label,
            max_statutes=None,
            _sibling_frontier_urls=siblings,
        )


@pytest.mark.anyio
async def test_retained_superseded_chapter_requires_active_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == SUPERSEDED_CHAPTER_URL
        scraper._record_fetch_event(
            provider="retained_exact_evidence",
            success=True,
        )
        return RETAINED_SUPERSEDED_CHAPTER_FRAGMENT

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)
    sibling_frontier = {SUPERSEDED_CHAPTER_URL, SUPERSEDING_CHAPTER_URL}

    rows = await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url=SUPERSEDED_CHAPTER_URL,
        chapter_label="Chapter 102. Delaware Legislative Oversight and Sunset Act",
        max_statutes=None,
        _sibling_frontier_urls=sibling_frontier,
    )

    assert rows == []
    assert (
        scraper._verified_superseding_index_url(
            BeautifulSoup(
                RETAINED_SUPERSEDED_CHAPTER_FRAGMENT,
                "html.parser",
            ),
            page_url=SUPERSEDED_CHAPTER_URL,
            sibling_frontier_urls=sibling_frontier,
        )
        == SUPERSEDING_CHAPTER_URL
    )
    target_rows = parse_delaware_chapter_html(
        SUPERSEDING_CHAPTER_FRAGMENT,
        source_url=SUPERSEDING_CHAPTER_URL,
        title_number="29",
        chapter_number="102",
    )
    assert [row.section_number for row in target_rows] == ["10201"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("html", "siblings", "page_url"),
    [
        (
            RETAINED_SUPERSEDED_CHAPTER_FRAGMENT.replace(
                "Delaware Legislative Oversight and Sunset Act",
                "Former Oversight Act",
            ),
            {SUPERSEDED_CHAPTER_URL, SUPERSEDING_CHAPTER_URL},
            SUPERSEDED_CHAPTER_URL,
        ),
        (
            RETAINED_SUPERSEDED_CHAPTER_FRAGMENT.replace(
                "volume=85&amp;chapter=263",
                "volume=85&amp;chapter=264",
            ),
            {SUPERSEDED_CHAPTER_URL, SUPERSEDING_CHAPTER_URL},
            SUPERSEDED_CHAPTER_URL,
        ),
        (
            RETAINED_SUPERSEDED_CHAPTER_FRAGMENT.replace(
                "85 Del. Laws, c. 263, § 5",
                "85 Del. Laws, c. 263, § 6",
            ),
            {SUPERSEDED_CHAPTER_URL, SUPERSEDING_CHAPTER_URL},
            SUPERSEDED_CHAPTER_URL,
        ),
        (
            RETAINED_SUPERSEDED_CHAPTER_FRAGMENT.replace(
                '<ul class="chaptersections"></ul>',
                '<ul class="chaptersections"><li>§ 10201</li></ul>',
            ),
            {SUPERSEDED_CHAPTER_URL, SUPERSEDING_CHAPTER_URL},
            SUPERSEDED_CHAPTER_URL,
        ),
        (
            RETAINED_SUPERSEDED_CHAPTER_FRAGMENT.replace(
                "</a>;\n</div>",
                "</a>;<p>Current provisions remain here.</p>\n</div>",
            ),
            {SUPERSEDED_CHAPTER_URL, SUPERSEDING_CHAPTER_URL},
            SUPERSEDED_CHAPTER_URL,
        ),
        (
            RETAINED_SUPERSEDED_CHAPTER_FRAGMENT,
            {SUPERSEDED_CHAPTER_URL},
            SUPERSEDED_CHAPTER_URL,
        ),
        (
            RETAINED_SUPERSEDED_CHAPTER_FRAGMENT,
            {SUPERSEDING_CHAPTER_URL},
            SUPERSEDED_CHAPTER_URL,
        ),
        (
            RETAINED_SUPERSEDED_CHAPTER_FRAGMENT,
            {SUPERSEDED_CHAPTER_URL, SUPERSEDING_CHAPTER_URL},
            f"{SUPERSEDED_CHAPTER_URL}?current=1",
        ),
    ],
)
async def test_superseded_chapter_rejects_any_boundary_drift(
    monkeypatch: pytest.MonkeyPatch,
    html: str,
    siblings: set[str],
    page_url: str,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == page_url
        scraper._record_fetch_event(
            provider="retained_exact_evidence",
            success=True,
        )
        return html

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    assert not scraper._verified_superseding_index_url(
        BeautifulSoup(html, "html.parser"),
        page_url=page_url,
        sibling_frontier_urls=siblings,
    )
    with pytest.raises(RuntimeError, match="exposed no section frontier"):
        await scraper._parse_chapter_sections(
            code_name="Delaware Code",
            chapter_url=page_url,
            chapter_label=(
                "Chapter 102. Delaware Legislative Oversight and Sunset Act"
            ),
            max_statutes=None,
            _sibling_frontier_urls=siblings,
        )


@pytest.mark.anyio
async def test_exact_transferred_chapter_is_a_closed_empty_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    html = """
    <div id="TitleHead">
      <h1>TITLE 14</h1><h4>Education</h4><h2>Hazing</h2>
      <h3>CHAPTER 94. Education Privacy Act
      [Transferred to Chapter 81 of this title.]</h3><h4></h4>
    </div>
    <div id="CodeBody"></div>
    """

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == TRANSFERRED_CHAPTER_URL
        scraper._record_fetch_event(provider="retained_exact_evidence", success=True)
        return html

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    rows = await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url=TRANSFERRED_CHAPTER_URL,
        chapter_label=(
            "Chapter 94. Education Privacy Act "
            "[Transferred to Chapter 81 of this title.]"
        ),
        max_statutes=None,
        _sibling_frontier_urls={TRANSFERRED_CHAPTER_URL},
    )

    assert rows == []


@pytest.mark.parametrize(
    ("html", "siblings"),
    [
        (
            """
            <div id="TitleHead"><h1>TITLE 14</h1><h4>Education</h4>
            <h2>Hazing</h2><h3>CHAPTER 94. Education Privacy Act</h3><h4></h4></div>
            <div id="CodeBody"></div>
            """,
            {TRANSFERRED_CHAPTER_URL},
        ),
        (
            """
            <div id="TitleHead"><h1>TITLE 14</h1><h4>Education</h4>
            <h2>Hazing</h2><h3>CHAPTER 94. Education Privacy Act
            [Transferred to Chapter 81 of this title.]</h3><h4></h4></div>
            <div id="CodeBody"><p>Substantive text remains.</p></div>
            """,
            {TRANSFERRED_CHAPTER_URL},
        ),
        (
            """
            <div id="TitleHead"><h1>TITLE 14</h1><h4>Education</h4>
            <h2>Hazing</h2><h3>CHAPTER 94. Education Privacy Act
            [Transferred to Chapter 81 of this title.]</h3><h4></h4></div>
            <div id="CodeBody"></div>
            """,
            set(),
        ),
    ],
)
def test_transferred_chapter_marker_remains_exact_and_fail_closed(
    html: str,
    siblings: set[str],
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    assert not scraper._verified_legislatively_vacated_index(
        BeautifulSoup(html, "html.parser"),
        page_url=TRANSFERRED_CHAPTER_URL,
        sibling_frontier_urls=siblings,
    )


def test_related_subchapter_iv_stub_matches_the_same_vacating_act() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    page_url = "https://delcode.delaware.gov/title12/c011/sc04/index.html"
    html = RETAINED_VACATED_SUBCHAPTER_FRAGMENT.replace(
        "Subchapter III. Unclaimed Life Insurance Funds",
        "Subchapter IV. Other Unclaimed Property",
    )

    assert scraper._verified_legislatively_vacated_index(
        BeautifulSoup(html, "html.parser"),
        page_url=page_url,
        sibling_frontier_urls={page_url},
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("html", "siblings"),
    [
        (RETAINED_VACATED_SUBCHAPTER_FRAGMENT, set()),
        (
            RETAINED_VACATED_SUBCHAPTER_FRAGMENT.replace(
                '<div id="CodeBody"></div>',
                '<div id="CodeBody">Unexpected text.</div>',
            ),
            {VACATED_SUBCHAPTER_URL},
        ),
        (
            RETAINED_VACATED_SUBCHAPTER_FRAGMENT.replace(
                "Subchapter III. Unclaimed Life Insurance Funds",
                "Subchapter III. Unknown subject",
            ),
            {VACATED_SUBCHAPTER_URL},
        ),
    ],
)
async def test_vacated_subchapter_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    html: str,
    siblings: set[str],
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        scraper._record_fetch_event(provider="retained_exact_evidence", success=True)
        return html

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)

    with pytest.raises(RuntimeError, match="exposed no section frontier"):
        await scraper._parse_chapter_sections(
            code_name="Delaware Code",
            chapter_url=VACATED_SUBCHAPTER_URL,
            chapter_label="Subchapter III. Unclaimed Life Insurance Funds",
            max_statutes=None,
            _sibling_frontier_urls=siblings,
        )


@pytest.mark.anyio
async def test_concurrent_official_sections_keep_exact_byte_bound_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    digest = hashlib.sha256(
        RETAINED_CONCURRENT_SECTION_FRAGMENT.encode("utf-8")
    ).hexdigest()

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == CONCURRENT_SECTION_URL
        scraper._last_page_fetch_transport_evidence = {
            "content_sha256": digest,
            "official_url": url,
            "source_transport": "direct",
        }
        scraper._record_fetch_event(
            provider="retained_acquisition_replay",
            success=True,
        )
        return RETAINED_CONCURRENT_SECTION_FRAGMENT

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)
    # A non-None ledger activates the same fail-closed row-byte check as the
    # strict acquisition runner.  The fetch itself is an exact retained replay.
    scraper._state_law_acquisition_ledger = object()

    rows = await scraper._parse_chapter_sections(
        code_name="Delaware Code",
        chapter_url=CONCURRENT_SECTION_URL,
        chapter_label="Subchapter I. Zoning",
        max_statutes=None,
        _sibling_frontier_urls={CONCURRENT_SECTION_URL},
    )

    assert [row.statute_id for row in rows] == ["DE-9-6927", "DE-9-6927"]
    assert all(row.structured_data["content_sha256"] == digest for row in rows)
    assert all(
        row.structured_data["transport_receipt"]["official_url"]
        == CONCURRENT_SECTION_URL
        for row in rows
    )

    qualified = scraper._qualify_concurrent_source_records(rows)

    assert len({row.statute_id for row in qualified}) == 2
    assert len(
        {row.structured_data["source_record_id"] for row in qualified}
    ) == 2
    assert all(
        row.structured_data["printed_statute_id"] == "DE-9-6927"
        for row in qualified
    )
    assert all(
        row.structured_data["concurrent_source_record_count"] == 2
        for row in qualified
    )
    assert all(row.section_number == "6927" for row in qualified)
    assert all(
        row.official_cite == "9 Del. C. § 6927" for row in qualified
    )
    assert all(
        row.source_url == f"{CONCURRENT_SECTION_URL}#6927"
        for row in qualified
    )
    for row in qualified:
        scraper._enrich_statute_structure(row)
    projection = build_canonical_state_law_output_projection(
        qualified,
        jurisdiction="DE",
    )
    assert projection["canonical_row_count"] == 2
    assert len(set(projection["canonical_keys"])) == 2


@pytest.mark.anyio
async def test_concurrent_section_parse_rejects_missing_exact_row_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")

    async def _fetch(url: str, timeout_seconds: int = 6) -> str:
        assert url == CONCURRENT_SECTION_URL
        scraper._record_fetch_event(provider="retained_acquisition_replay", success=True)
        return RETAINED_CONCURRENT_SECTION_FRAGMENT

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_official_de_html", _fetch)
    scraper._state_law_acquisition_ledger = object()

    with pytest.raises(
        RuntimeError,
        match="chapter rows lack an exact official-byte binding",
    ):
        await scraper._parse_chapter_sections(
            code_name="Delaware Code",
            chapter_url=CONCURRENT_SECTION_URL,
            chapter_label="Subchapter I. Zoning",
            max_statutes=None,
            _sibling_frontier_urls={CONCURRENT_SECTION_URL},
        )


def _apply_concurrent_identity_drift(
    rows: list[NormalizedStatute],
    drift: str,
) -> None:
    row = rows[0]
    structured_data = dict(row.structured_data or {})
    receipt = dict(structured_data.get("transport_receipt") or {})
    if drift == "http_scheme":
        row.source_url = row.source_url.replace("https://", "http://", 1)
        receipt["official_url"] = receipt["official_url"].replace(
            "https://", "http://", 1
        )
    elif drift == "host":
        row.source_url = row.source_url.replace(
            "delcode.delaware.gov", "example.gov", 1
        )
        receipt["official_url"] = receipt["official_url"].replace(
            "delcode.delaware.gov", "example.gov", 1
        )
    elif drift == "userinfo":
        row.source_url = row.source_url.replace(
            "https://", "https://reader@", 1
        )
        receipt["official_url"] = receipt["official_url"].replace(
            "https://", "https://reader@", 1
        )
    elif drift == "port":
        row.source_url = row.source_url.replace(
            "delcode.delaware.gov", "delcode.delaware.gov:443", 1
        )
        receipt["official_url"] = receipt["official_url"].replace(
            "delcode.delaware.gov", "delcode.delaware.gov:443", 1
        )
    elif drift == "query":
        row.source_url = row.source_url.replace("#", "?view=current#", 1)
        receipt["official_url"] = f"{receipt['official_url']}?view=current"
    elif drift == "missing_fragment":
        row.source_url = row.source_url.split("#", 1)[0]
    elif drift == "source_kind":
        structured_data["source_kind"] = "official_delaware_code_html"
    elif drift == "missing_digest":
        structured_data.pop("content_sha256", None)
    elif drift == "malformed_digest":
        structured_data["content_sha256"] = "ab" * 31
        receipt["content_sha256"] = "ab" * 31
    elif drift == "receipt_url_path":
        receipt["official_url"] = receipt["official_url"].replace(
            "/sc01/", "/sc02/", 1
        )
    elif drift == "receipt_url_query":
        receipt["official_url"] = f"{receipt['official_url']}?view=current"
    elif drift == "receipt_url_trailing_slash":
        receipt["official_url"] = f"{receipt['official_url']}/"
    elif drift == "receipt_digest":
        receipt["content_sha256"] = "cd" * 32
    elif drift == "missing_transport_kind":
        receipt.pop("source_transport", None)
    elif drift == "generic_transport_kind":
        receipt["source_transport"] = "archive"
    elif drift == "direct_archive_claim":
        receipt["archive_url"] = (
            "https://web.archive.org/web/20260824000000id_/"
            + CONCURRENT_SECTION_URL
        )
        receipt["archive_timestamp"] = "20260824000000"
    elif drift == "cache_without_origin":
        receipt["source_transport"] = "durable_cache"
    else:
        raise AssertionError(f"unknown drift case: {drift}")
    structured_data["transport_receipt"] = receipt
    row.structured_data = structured_data


@pytest.mark.parametrize(
    "drift",
    [
        "http_scheme",
        "host",
        "userinfo",
        "port",
        "query",
        "missing_fragment",
        "source_kind",
        "missing_digest",
        "malformed_digest",
        "receipt_url_path",
        "receipt_url_query",
        "receipt_url_trailing_slash",
        "receipt_digest",
        "missing_transport_kind",
        "generic_transport_kind",
        "direct_archive_claim",
        "cache_without_origin",
    ],
)
def test_concurrent_source_identity_rejects_official_evidence_drift(
    drift: str,
) -> None:
    scraper = DelawareScraper("DE", "Delaware")
    rows = _concurrent_rows()
    _apply_concurrent_identity_drift(rows, drift)

    with pytest.raises(
        RuntimeError,
        match="concurrent source record lacks exact official evidence",
    ):
        scraper._qualify_concurrent_source_records(rows)


def test_concurrent_source_identity_rejects_predeclared_identity() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    rows = _concurrent_rows()
    rows[0].structured_data["source_record_id"] = "producer-guessed-id"

    with pytest.raises(RuntimeError, match="identity was already declared"):
        scraper._qualify_concurrent_source_records(rows)


def test_concurrent_source_identity_rejects_indistinguishable_records() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    rows = _concurrent_rows()
    rows[1].section_name = rows[0].section_name
    rows[1].full_text = rows[0].full_text

    with pytest.raises(RuntimeError, match="not distinguishable"):
        scraper._qualify_concurrent_source_records(rows)


def test_concurrent_source_identity_is_order_independent_and_collision_scoped() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    forward = _concurrent_rows()
    singleton = _concurrent_rows()[0]
    singleton.statute_id = "DE-9-6928"
    singleton.section_number = "6928"
    singleton.source_url = f"{CONCURRENT_SECTION_URL}#6928"
    forward.append(singleton)
    reverse = list(reversed(_concurrent_rows()))

    scraper._qualify_concurrent_source_records(forward)
    scraper._qualify_concurrent_source_records(reverse)

    forward_by_heading = {
        row.section_name: (
            row.statute_id,
            row.structured_data.get("source_record_id"),
        )
        for row in forward
        if row.section_number == "6927"
    }
    reverse_by_heading = {
        row.section_name: (
            row.statute_id,
            row.structured_data.get("source_record_id"),
        )
        for row in reverse
    }
    assert forward_by_heading == reverse_by_heading
    assert singleton.statute_id == "DE-9-6928"
    assert "source_record_id" not in singleton.structured_data


def test_substantive_concurrent_record_change_changes_only_that_identity() -> None:
    scraper = DelawareScraper("DE", "Delaware")
    baseline = _concurrent_rows()
    changed_html = RETAINED_CONCURRENT_SECTION_FRAGMENT.replace(
        "modified,\n    or renovated buildings",
        "expanded, modified,\n    or renovated buildings",
        1,
    )
    assert changed_html != RETAINED_CONCURRENT_SECTION_FRAGMENT
    changed = _concurrent_rows(changed_html)

    scraper._qualify_concurrent_source_records(baseline)
    scraper._qualify_concurrent_source_records(changed)

    baseline_ids = {
        row.section_name: row.structured_data["source_record_id"]
        for row in baseline
    }
    changed_ids = {
        row.section_name: row.structured_data["source_record_id"]
        for row in changed
    }
    current_heading = next(
        heading for heading in baseline_ids if "Effective until" in heading
    )
    future_heading = next(
        heading for heading in baseline_ids if "Effective Feb." in heading
    )
    assert baseline_ids[current_heading] == changed_ids[current_heading]
    assert baseline_ids[future_heading] != changed_ids[future_heading]
