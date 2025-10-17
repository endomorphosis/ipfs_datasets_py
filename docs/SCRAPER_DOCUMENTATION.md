# State Law Scraper Documentation

This document provides detailed information about each state's law scraper implementation, expected HTML structures, and troubleshooting tips.

## Failing States Overview

The following 11 states have custom scrapers but are currently failing to scrape data:

1. **Alabama (AL)** - Custom scraper
2. **Connecticut (CT)** - Custom scraper
3. **Delaware (DE)** - Custom scraper
4. **Georgia (GA)** - Custom scraper
5. **Hawaii (HI)** - Playwright (JavaScript rendering)
6. **Indiana (IN)** - Custom scraper
7. **Louisiana (LA)** - Playwright (JavaScript rendering)
8. **Missouri (MO)** - Custom scraper
9. **South Dakota (SD)** - Generic scraper
10. **Tennessee (TN)** - Playwright (JavaScript rendering)
11. **Wyoming (WY)** - Custom scraper

---

## Alabama (AL)

### Website Information
- **URL**: http://alisondb.legislature.state.al.us/alison/CodeOfAlabama/1975/coatoc.htm
- **Type**: Static HTML with nested TOC
- **Citation Format**: Ala. Code

### Expected HTML Structure
Alabama's legislative website uses a table of contents (TOC) with nested links:
- Top level: Titles (e.g., "Title 13A - Criminal Code")
- Second level: Chapters (e.g., "Chapter 6 - Homicide")
- Third level: Sections (e.g., "Section 13A-6-2")

### Filtering Logic
The scraper looks for links containing these keywords:
- title, section, chapter, §, article, code, statute, part, division

### Example Valid Links
```
Title 13A - Criminal Code
Chapter 6 - Homicide  
Section 13A-6-2 - Murder
Title 1 - General Provisions
```

### Common Issues
1. **Network timeout**: Site may be slow, increase timeout if needed
2. **Empty response**: Check if URL is accessible from your network
3. **No matching keywords**: Links may use different terminology

### Logging
Enable debug logging to see:
- Total links found on page
- Number of links skipped (too short, no keywords)
- Number of links accepted
- Full link text for debugging

---

## Connecticut (CT)

### Website Information
- **URL**: https://www.cga.ct.gov/current/pub/titles.htm
- **Type**: Static HTML with title listings
- **Citation Format**: Conn. Gen. Stat.

### Expected HTML Structure
Connecticut organizes statutes by numbered titles with chapters underneath:
- Titles are numbered (e.g., "Title 1", "Title 53a")
- Links may contain "CGS" abbreviation
- Sections use format like "Sec. 53a-54a"

### Filtering Logic
Very permissive - accepts links that either:
1. Contain numbers (most statute references have them)
2. Contain keywords: title, chapter, sec, §, part, article, statute, cgs, law

### Example Valid Links
```
Title 1 - Provisions of General Application
Title 53a - Penal Code
Sec. 53a-54a - Murder
Chapter 500 - Criminal Law
```

### Common Issues
1. **JavaScript requirements**: Some pages may require JavaScript
2. **Dynamic content**: Consider using Playwright if custom scraper fails

---

## Delaware (DE)

### Website Information
- **URL**: https://delcode.delaware.gov/index.html
- **Type**: Static HTML with title index
- **Citation Format**: Del. Code

### Expected HTML Structure
Delaware Code organized by titles (1-31):
- Title-based organization
- Chapters within titles
- Sections within chapters

### Filtering Logic
Accepts links with numbers OR keywords:
- title, chapter, §, section, part, code, statute, del, law

### Example Valid Links
```
Title 11 - Crimes and Criminal Procedure
Chapter 5 - Specific Offenses
§ 636 - Murder First Degree
```

---

## Georgia (GA)

### Website Information
- **URL**: http://www.legis.ga.gov/legislation/laws.html
- **Type**: Static HTML
- **Citation Format**: Ga. Code Ann.

### Expected HTML Structure
Official Code of Georgia Annotated:
- Title-based organization
- Chapters and sections
- May use "O.C.G.A." abbreviation

### Filtering Logic
Keywords: title, chapter, §, section, part, code, statute, article, ga.

### Example Valid Links
```
Title 16 - Crimes and Offenses
Chapter 5 - Crimes Against the Person
Section 16-5-1 - Murder
```

---

## Hawaii (HI)

### Website Information
- **URL**: https://www.capitol.hawaii.gov/hrscurrent/
- **Type**: **JavaScript-rendered** (requires Playwright)
- **Citation Format**: Haw. Rev. Stat.

### Expected HTML Structure
Hawaii Revised Statutes (HRS):
- Organized by volumes and chapters
- Heavy use of JavaScript for navigation
- Links may be dynamically loaded

### Playwright Configuration
- Wait selector: `a[href*='Vol'], .statute-link, a[href*='hrs']`
- Timeout: 45000ms (45 seconds)
- Falls back to generic scraper if Playwright unavailable

### Example Valid Links
```
Volume 1
Chapter 701 - Penal Code
Section 701-109
HRS § 707-701 - Murder
```

### Common Issues
1. **Playwright not installed**: Install with `pip install playwright && playwright install chromium`
2. **Timeout errors**: Increase timeout for slow connections
3. **JavaScript errors**: Check browser console for errors

---

## Indiana (IN)

### Website Information
- **URL**: http://iga.in.gov/legislative/laws/2024/ic/titles/
- **Type**: Static HTML with year-specific URLs
- **Citation Format**: Ind. Code

### Expected HTML Structure
Indiana Code organized by titles and articles:
- Title-based (e.g., "Title 35 - Criminal Law")
- Articles within titles
- Chapters within articles

### Filtering Logic
Keywords: title, article, chapter, ic, §, section, part, code, ind.

### Example Valid Links
```
Title 35 - Criminal Law and Procedure
Article 42 - Offenses Against the Person
IC 35-42-1-1 - Murder
```

### Common Issues
1. **Year-specific URLs**: URL includes year (2024), may need updating
2. **Multiple levels**: Deep nesting may require multiple page loads

---

## Louisiana (LA)

### Website Information
- **URL**: https://legis.la.gov/legis/Laws.aspx
- **Type**: **JavaScript-rendered** (requires Playwright)
- **Citation Format**: La. Rev. Stat.

### Expected HTML Structure
Louisiana Revised Statutes:
- Uses "RS" abbreviation (Revised Statutes)
- JavaScript-heavy interface
- Links format: "RS 14:30" (Title:Section)

### Playwright Configuration
- Wait selector: `a[href*='RS'], .law-link`
- Timeout: 45000ms
- Falls back to generic if unavailable

### Example Valid Links
```
Title 14 - Criminal Law
RS 14:30 - First Degree Murder
RS 14:30.1 - Second Degree Murder
```

### Common Issues
1. **RS format**: Section numbers use colon separator (14:30)
2. **JavaScript required**: Must use Playwright
3. **Session state**: Site may require maintaining session

---

## Missouri (MO)

### Website Information
- **URL**: http://www.moga.mo.gov/main/Home.aspx
- **Type**: ASP.NET application
- **Citation Format**: Mo. Rev. Stat.

### Expected HTML Structure
Missouri Revised Statutes (RSMo):
- Chapter-based organization
- Uses "RSMo" abbreviation
- ASP.NET postback for navigation

### Filtering Logic
Keywords: chapter, rsmo, §, section, title, part, code, statute, mo.

### Example Valid Links
```
Chapter 565 - Offenses Against the Person
RSMo 565.020 - First Degree Murder
Section 565.021 - Second Degree Murder
```

### Common Issues
1. **ASP.NET postbacks**: May need to handle form submissions
2. **ViewState**: ASP.NET pages use ViewState for navigation
3. **Session management**: Site may track user session

---

## South Dakota (SD)

### Website Information
- **URL**: https://sdlegislature.gov/
- **Type**: Static HTML (uses generic scraper)
- **Citation Format**: S.D. Codified Laws

### Expected HTML Structure
South Dakota Codified Laws:
- Title-based organization
- Simple link structure
- Generic scraper should work

### Filtering Logic
Uses base scraper generic filtering (no custom logic)

### Example Valid Links
```
Title 22 - Crimes
Chapter 16 - Homicide
22-16-4 - First Degree Murder
```

### Common Issues
1. **Generic scraper limitations**: May need custom scraper
2. **Link format**: May use different patterns than expected

---

## Tennessee (TN)

### Website Information
- **URL**: https://www.tn.gov/tga/statutes.html
- **Type**: **JavaScript-rendered** (requires Playwright)
- **Citation Format**: Tenn. Code Ann.

### Expected HTML Structure
Tennessee Code Annotated (TCA):
- Title-based organization
- JavaScript for statute display
- May use frames or iframes

### Playwright Configuration
- Wait selector: `a[href*='title'], .code-link, a[href*='tca']`
- Timeout: 45000ms
- Falls back to generic if unavailable

### Example Valid Links
```
Title 39 - Criminal Offenses
Chapter 13 - Homicide
TCA § 39-13-202 - First Degree Murder
```

### Common Issues
1. **JavaScript required**: Must use Playwright
2. **Frames**: May use frames for content display
3. **Complex navigation**: Multi-step navigation may be required

---

## Wyoming (WY)

### Website Information
- **URL**: https://www.wyoleg.gov/statutes/statutesintro.aspx
- **Type**: ASP.NET application
- **Citation Format**: Wyo. Stat.

### Expected HTML Structure
Wyoming Statutes:
- Title-based organization
- ASP.NET application
- Uses .aspx pages

### Filtering Logic
Keywords: title, chapter, §, section, part, code, statute, article, wyo.

### Example Valid Links
```
Title 6 - Crimes and Offenses
Chapter 2 - Offenses Against the Person
§ 6-2-101 - First Degree Murder
```

### Common Issues
1. **ASP.NET complexity**: May need special handling for postbacks
2. **Session management**: Site may require maintaining session state

---

## General Troubleshooting

### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Test Individual Scraper

```python
from state_scrapers import get_scraper_for_state

scraper = get_scraper_for_state("AL", "Alabama")
codes = scraper.get_code_list()
statutes = await scraper.scrape_code(codes[0]['name'], codes[0]['url'])
```

### Common Error Messages

1. **"No data scraped"**
   - Check if URL is accessible
   - Enable debug logging to see filtering details
   - Verify keyword matching is working

2. **"Required library not available"**
   - Install missing packages: `pip install requests beautifulsoup4`
   - For Playwright: `pip install playwright && playwright install chromium`

3. **"Request timeout"**
   - Increase timeout value
   - Check network connectivity
   - Try accessing URL in browser first

4. **"HTTP error 403/404"**
   - URL may have changed
   - Check if site blocks automated access
   - Try with different User-Agent header

### Testing Checklist

For each failing state:
1. [ ] Verify URL is accessible in browser
2. [ ] Check HTML structure matches expectations
3. [ ] Enable debug logging and review output
4. [ ] Test with small max_sections (e.g., 10)
5. [ ] Verify at least some links match keywords
6. [ ] Check for JavaScript requirements
7. [ ] Review error messages and stack traces

---

## Implementation Notes

### All Custom Scrapers Include
- Enhanced error handling with specific exceptions
- Detailed logging at INFO and DEBUG levels
- Filtering statistics (skipped vs accepted)
- Automatic fallback to generic scraper
- Timeout handling
- HTTP error handling

### Playwright Scrapers (HI, LA, TN) Require
- Playwright library installed
- Chromium browser installed
- Longer timeouts (45s default)
- Specific wait selectors for each state
- Fallback to generic scraper if Playwright fails

### Testing Without Network Access
- Mock HTML responses for unit tests
- Test filtering logic separately
- Verify error handling paths
- Test fallback mechanisms
