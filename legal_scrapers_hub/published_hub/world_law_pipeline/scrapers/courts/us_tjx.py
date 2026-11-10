import sys,re;sys.path.insert(0,'/workspace/world_courts/scrapers/courts');import us_directory_extract as de
NM=r"(?P<name>[A-Z][a-zA-Z'\-]+\.?(?:\s+(?:[A-Z][a-zA-Z'\-]*\.?|\"[A-Za-z]+\"|de|la|van|von|Mc[A-Z][a-z]+)){1,4}(?:,?\s+(?:Jr\.?|Sr\.?|II|III|IV))?)"
PAT=re.compile(r"^(?:The\s+)?(?:(?P<title>(?:(?:Presiding|Resident|Chief|President|Senior|Associate|Administrative|Supervising|Magisterial District|District|Circuit|County|Juvenile|Probate|Associate Circuit)\s+)*Judge|Hon\.|Honorable|Magistrate)\s+)"+NAME if False else r"^(?:The\s+)?(?P<title>(?:(?:Presiding|Resident|Chief|President|Senior|Associate|Administrative|Supervising|Magisterial District|District|Circuit|County|Juvenile|Probate)\s+)*Judge|Hon\.|Honorable|Magistrate|Judicial Magistrate)\s+"+NM+r"$")
BAD=re.compile(r"(?i)\b(court|county|district|profile|directory|judges|view|appointed|division|office|vacan|clerk|staff)\b")
def names(h):
    out=[]
    for l in de.totext(h).split("\n"):
        l=re.sub(r"\s+"," ",l).strip()
        m=PAT.match(l)
        if m and not BAD.search(m.group("name")) and len(m.group("name"))<45: out.append((m.group("title"),m.group("name")))
    return list(dict.fromkeys(out))
if __name__=="__main__":
    import glob
    for f in sorted(glob.glob("/tmp/tj/*.html")):
        n=names(open(f).read());print(f.split("/")[-1],len(n),n[:4])
