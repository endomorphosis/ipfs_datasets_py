"""Unit tests for the jurisdiction-ID abstraction."""

import pytest


def test_nl_cbs(wm):
    s = wm.jurisdiction.get_scheme("NL")
    assert s.normalize("GM0363") == "0363"
    assert s.normalize(363) == "0363"
    assert s.normalize("0363") == "0363"
    assert s.file_name("0363") == "0363_html.parquet"
    assert not s.validate("abc")


def test_pt_dicofre(wm):
    s = wm.jurisdiction.get_scheme("PT")
    assert s.normalize("1106") == "1106"
    assert s.normalize(1106) == "1106"
    assert s.file_name(1106) == "1106_html.parquet"
    assert not s.validate("11A6")


def test_es_ine(wm):
    s = wm.jurisdiction.get_scheme("ES")
    assert s.normalize("28079") == "28079"
    assert s.normalize(28079) == "28079"
    assert s.file_name("28079") == "28079_html.parquet"
    assert not s.validate("")


def test_pl_teryt(wm):
    s = wm.jurisdiction.get_scheme("PL")
    assert s.normalize("1465011") == "1465011"
    assert s.normalize(" 1465011 ") == "1465011"
    assert not s.validate("")


def test_kr_mst(wm):
    s = wm.jurisdiction.get_scheme("KR")
    assert s.normalize(" 1234567 ") == "1234567"
    assert not s.validate("   ")


def test_br_ibge(wm):
    s = wm.jurisdiction.get_scheme("BR")
    assert s.normalize("5208004") == "5208004"
    assert s.normalize(5208004) == "5208004"
    assert s.normalize("1505536") == "1505536"
    assert s.normalize("4104501") == "4104501"
    assert s.normalize("4208450") == "4208450"
    assert s.file_name("5208004") == "5208004_html.parquet"
    assert not s.validate("")
    assert not s.validate("52080A4")


def test_id_bps(wm):
    s = wm.jurisdiction.get_scheme("ID")
    assert s.normalize("3273") == "3273"
    assert s.normalize(3273) == "3273"
    assert s.normalize("3578") == "3578"
    assert s.normalize("3374") == "3374"
    assert s.normalize("3507") == "3507"
    assert s.file_name("3273") == "3273_html.parquet"
    assert not s.validate("")
    assert not s.validate("327A")


def test_be_nis(wm):
    s = wm.jurisdiction.get_scheme("BE")
    assert s.normalize("24055") == "24055"
    assert s.normalize(24055) == "24055"
    assert s.normalize("11016") == "11016"
    assert s.normalize("73042") == "73042"
    assert s.normalize("23100") == "23100"
    assert s.normalize("24011") == "24011"
    assert s.file_name("24055") == "24055_html.parquet"
    assert not s.validate("")
    assert not s.validate("2405A")


def test_ca_sgc(wm):
    s = wm.jurisdiction.get_scheme("CA")
    # SGC census subdivision codes: PR(2) + CD(2) + CSD(3), verified
    # against Statistics Canada SGC 2021.
    assert s.normalize("3520005") == "3520005"   # Toronto, ON
    assert s.normalize(3520005) == "3520005"
    assert s.normalize("5915022") == "5915022"   # Vancouver, BC
    assert s.normalize("4806016") == "4806016"   # Calgary, AB
    assert s.normalize("2466023") == "2466023"   # Montréal, QC
    assert s.normalize("3516010") == "3516010"   # Kawartha Lakes, ON
    assert s.normalize("1209034") == "1209034"   # Halifax, NS
    assert s.normalize(" 3520005 ") == "3520005"
    assert s.file_name("3520005") == "3520005_html.parquet"
    assert not s.validate("")
    assert not s.validate("35200A5")
    assert not s.validate("9999999")     # no such SGC province prefix
    assert not s.validate("35200050")    # 8 digits: not a CSD code


def test_au_abs_lga(wm):
    s = wm.jurisdiction.get_scheme("AU")
    # ABS ASGS Ed.3 LGA 2025: state digit + 4, zero-padded to 5
    assert s.normalize("10050") == "10050"   # Albury, NSW (1)
    assert s.normalize(31000) == "31000"     # Brisbane, Qld (3)
    assert s.normalize("24600") == "24600"   # Melbourne, Vic (2)
    assert s.normalize(" 54170 ") == "54170"  # Joondalup, WA (5)
    assert s.normalize("40070") == "40070"   # Adelaide, SA (4)
    assert s.file_name("10050") == "10050_html.parquet"
    assert not s.validate("")
    assert not s.validate("ZZZZZ")      # ABS "Outside Australia" pseudo code
    assert not s.validate("09499")      # "No usual address" pseudo shape (state 0)
    assert not s.validate("100500")     # 6 digits: not an LGA code
    assert not s.validate("Albury")


def test_mx_inegi(wm):
    s = wm.jurisdiction.get_scheme("MX")
    # INEGI clave geoestadistica: entidad (2) + municipio (3), zero-padded to 5
    assert s.normalize("14039") == "14039"   # Guadalajara, Jalisco (14)
    assert s.normalize(19039) == "19039"     # Monterrey, Nuevo Leon (19)
    assert s.normalize("01001") == "01001"   # Aguascalientes, Ags. (01)
    assert s.normalize(" 21114 ") == "21114"  # Puebla, Puebla (21)
    assert s.normalize(2004) == "02004"      # Tijuana, BC (02) — int loses the pad
    assert s.file_name("14039") == "14039_html.parquet"
    assert not s.validate("")
    assert not s.validate("33001")      # entidad 33 does not exist (01-32)
    assert not s.validate("00001")      # entidad 00 does not exist
    assert not s.validate("140390")     # 6 digits: not a municipio code
    assert not s.validate("Guadalajara")


def test_at_gkz(wm):
    s = wm.jurisdiction.get_scheme("AT")
    assert s.normalize("20402") == "20402"
    assert s.normalize(20402) == "20402"
    assert s.normalize("20101") == "20101"
    assert s.file_name("20402") == "20402_html.parquet"
    assert not s.validate("")
    assert not s.validate("2040A")
    assert not s.validate("00402")
    assert not s.validate("204021")


def test_de_ags(wm):
    s = wm.jurisdiction.get_scheme("DE")
    # AGS: Land (2) + RB (1) + Kreis (2) + Gemeinde (3), 8 digits
    assert s.normalize("01001000") == "01001000"   # Flensburg (SH)
    assert s.normalize("09162000") == "09162000"   # München (BY)
    assert s.normalize(11000000) == "11000000"     # Berlin (Stadtstaat)
    assert s.normalize(" 02000000 ") == "02000000"  # Hamburg
    assert s.normalize("14612000") == "14612000"   # Dresden (SN)
    assert s.file_name("01001000") == "01001000_html.parquet"
    assert not s.validate("")
    assert not s.validate("17001000")      # Land 17 does not exist
    assert not s.validate("00001000")      # Land 00 does not exist
    assert not s.validate("0100100A")
    assert not s.validate("010010000000")  # 12-digit ARS is not the AGS
    assert not s.validate("Flensburg")


def test_unknown_country_raises(wm):
    with pytest.raises(KeyError):
        wm.jurisdiction.get_scheme("XX")


def test_convenience_helpers(wm):
    assert wm.jurisdiction.normalize_jurisdiction_id("NL", "GM0363") == "0363"
    assert wm.jurisdiction.jurisdiction_file_name("ES", 28079) == "28079_html.parquet"


def test_za_mdb(wm):
    s = wm.jurisdiction.get_scheme("ZA")
    # metropolitan (Category A) letter codes
    assert s.normalize("CPT") == "CPT"
    assert s.normalize("jhb") == "JHB"
    assert s.normalize(" ETH ") == "ETH"
    assert s.normalize("NMA") == "NMA"
    # district (Category C): DC + 1-2 digits, never zero-padded
    assert s.normalize("DC44") == "DC44"
    assert s.normalize("DC2") == "DC2"
    # local (Category B): province prefix + 3 digits
    assert s.normalize("WC013") == "WC013"
    assert s.normalize("wc033") == "WC033"
    assert s.normalize("EC443") == "EC443"
    assert s.normalize("KZN292") == "KZN292"
    assert s.file_name("WC013") == "WC013_html.parquet"
    assert s.file_name("CPT") == "CPT_html.parquet"
    assert not s.validate("")
    assert not s.validate("WC13")      # local codes carry exactly 3 digits
    assert not s.validate("XX123")
    assert not s.validate("DC123")
    assert not s.validate("Johannesburg")


def test_nz_stats(wm):
    s = wm.jurisdiction.get_scheme("NZ")
    # territorial authorities: Stats NZ TA2023 3-digit codes
    assert s.normalize("047") == "047"     # Wellington City
    assert s.normalize(16) == "016"        # Hamilton City
    assert s.normalize(" 76 ") == "076"    # Auckland Council
    assert s.normalize("001") == "001"     # Far North District
    # regional councils: "R" + ISO 3166-2:NZ region code
    assert s.normalize("RNTL") == "RNTL"   # Northland
    assert s.normalize("rwgn") == "RWGN"   # Wellington
    assert s.normalize("RCAN") == "RCAN"   # Canterbury
    assert s.file_name("047") == "047_html.parquet"
    assert s.file_name("RNTL") == "RNTL_html.parquet"
    assert not s.validate("")
    assert not s.validate("077")      # TA2023 tops out at 076 (Auckland)
    assert not s.validate("999")      # Area Outside Territorial Authority
    assert not s.validate("RAUK")     # Auckland is a TA (076), not an RC entry
    assert not s.validate("Wellington")


def test_jp_jisx0402(wm):
    s = wm.jurisdiction.get_scheme("JP")
    # JIS X 0402: prefecture (2, 01-47) + municipality (3), 5-digit canonical
    assert s.normalize("01100") == "01100"     # Sapporo
    assert s.normalize(14100) == "14100"       # Yokohama
    assert s.normalize(" 40130 ") == "40130"   # Fukuoka
    assert s.normalize("13000") == "13000"     # Tokyo Metropolis (prefecture)
    assert s.normalize("13101") == "13101"     # Chiyoda (special ward)
    # MIC 6-digit form: check digit verified, then dropped
    assert s.normalize("011002") == "01100"    # Sapporo, check digit 2
    assert s.normalize("012131") == "01213"    # Tomakomai, 11 -> 1 rule
    assert s.normalize("472018") == "47201"    # Naha
    assert s.file_name("01100") == "01100_html.parquet"
    assert not s.validate("")
    assert not s.validate("011003")     # bad check digit
    assert not s.validate("48100")      # prefecture 48 does not exist
    assert not s.validate("00100")      # prefecture 00 does not exist
    assert not s.validate("0110A")
    assert not s.validate("Sapporo")


def test_fr_code_insee(wm):
    s = wm.jurisdiction.get_scheme("FR")
    # INSEE COG: département (2) + commune (3), 5 chars canonical
    assert s.normalize("75056") == "75056"     # Paris
    assert s.normalize("69123") == "69123"     # Lyon
    assert s.normalize(13055) == "13055"       # Marseille
    assert s.normalize(" 35238 ") == "35238"   # Rennes
    assert s.normalize("01053") == "01053"     # Bourg-en-Bresse (Ain)
    assert s.normalize(1053) == "01053"         # short numeric input zero-pads
    # Corse: alphanumeric départements 2A / 2B (old dept 20 is gone)
    assert s.normalize("2A004") == "2A004"     # Ajaccio
    assert s.normalize("2b033") == "2B033"     # Bastia (uppercased)
    # Outre-mer: 3-digit département + 2-digit commune
    assert s.normalize("97101") == "97101"     # Les Abymes (Guadeloupe)
    assert s.normalize("97302") == "97302"     # Cayenne (Guyane)
    assert s.normalize("97411") == "97411"     # Saint-Denis (La Réunion)
    assert s.file_name("75056") == "75056_html.parquet"
    assert s.file_name("2A004") == "2A004_html.parquet"
    assert not s.validate("")
    assert not s.validate("20001")       # département 20 no longer exists
    assert not s.validate("96001")       # département 96 does not exist
    assert not s.validate("97901")       # outre-mer départements stop at 978
    assert not s.validate("2C001")       # only 2A/2B in Corse
    assert not s.validate("750567")      # too long
    assert not s.validate("Paris")


def test_se_scb_kommunkod(wm):
    s = wm.jurisdiction.get_scheme("SE")
    # SCB kommunkod: län (2) + kommun (2), zero-padded to 4 digits
    assert s.normalize("0180") == "0180"     # Stockholm (län 01)
    assert s.normalize(1480) == "1480"       # Göteborg (län 14)
    assert s.normalize(" 1280 ") == "1280"   # Malmö (län 12)
    assert s.normalize("0380") == "0380"     # Uppsala (län 03)
    assert s.normalize("2584") == "2584"     # Kiruna (län 25)
    assert s.normalize("0920") == "0920"     # Gotland (län 09)
    assert s.file_name("0180") == "0180_html.parquet"
    assert not s.validate("")
    assert not s.validate("0280")       # län 02 does not exist
    assert not s.validate("1180")       # län 11 was merged into Skåne (12)
    assert s.normalize("180") == "0180"      # short input zero-pads (SGC/NZ pattern)
    assert not s.validate("12345")           # too long
    assert not s.validate("Stockholm")


def test_it_istat(wm):
    s = wm.jurisdiction.get_scheme("IT")
    # ISTAT codice comune: provincia (3) + comune (3), zero-padded to 6
    assert s.normalize("058091") == "058091"   # Roma (provincia 058)
    assert s.normalize("015146") == "015146"   # Milano (015)
    assert s.normalize(15146) == "015146"      # int loses the leading zero
    assert s.normalize(" 082053 ") == "082053"  # Palermo (082)
    assert s.normalize("001001") == "001001"   # Aglie (Torino 001)
    assert s.normalize("111005") == "111005"   # Sud Sardegna (111, post-2016)
    assert s.normalize("108004") == "108004"   # Monza e della Brianza (108)
    assert s.file_name("058091") == "058091_html.parquet"
    assert not s.validate("")
    assert not s.validate("104001")      # provincia 104 does not exist
    assert not s.validate("107001")      # provincia 107 does not exist
    assert not s.validate("112001")      # provincia 112 does not exist
    assert not s.validate("000001")      # provincia 000 does not exist
    assert not s.validate("0580911")     # 7 digits: not a codice comune
    assert not s.validate("Roma")
