B="https://www.courts.delaware.gov/forms/download.aspx?id="
J={"classes":["district"]};S_={"classes":["supreme"]};ALL={"classes":["supreme","district","justice"]}
def s(i,name,abbr,fam,sc,extra=None):
    o={"kind":"pdf","titlewrap":True,"dropempty":True,"longestdup":True,"dropbracket":True};o.update(extra or {})
    return (B+str(i),name,abbr,fam,"statewide",sc,o)
SETS=[s(304488,"Delaware Superior Court Civil Rules","DESCCIV","civil_procedure",J),
 s(304498,"Delaware Superior Court Criminal Rules","DESCCRIM","criminal_procedure",J),
 s(174928,"Delaware Supreme Court Rules","DESUPCT","civil_and_criminal_procedure",S_),
 s(160908,"Delaware Court of Chancery Rules","DECHAN","civil_procedure",J),
 s(39308,"Delaware Family Court Civil Rules","DEFCCIV","civil_procedure",J),
 s(39318,"Delaware Family Court Criminal Rules","DEFCCRIM","criminal_procedure",J),
 s(176248,"Delaware Court of Common Pleas Civil Rules","DECCPCIV","civil_procedure",J),
 s(174058,"Delaware Court of Common Pleas Criminal Rules","DECCPCRIM","criminal_procedure",J)]
