"""Jurisdiction-ID abstraction for the world municipal-law program.

Every country in the program identifies its municipalities through its own
official registry. ``jurisdiction_id`` is always that registry's official
code serialized as a STRING (zero-padded where the registry zero-pads);
``jurisdiction_name`` is the registry's official name. One parquet file per
jurisdiction: ``{jurisdiction_id}_html.parquet``.

Add a new country by subclassing :class:`JurisdictionScheme` and registering
an instance in :data:`SCHEMES` keyed by ISO-2 country code.
"""

from __future__ import annotations

from typing import Dict, Optional, Union

Code = Union[str, int]


class JurisdictionScheme:
    """Normalization + validation for one country's municipality codes."""

    #: ISO-2 country code this scheme serves.
    country: str = ""
    #: Human name of the registry (e.g. "TERYT", "INE").
    scheme_name: str = ""

    def normalize(self, code: Code) -> str:
        """Return the canonical string form of a registry code.

        Raises ValueError on codes that cannot belong to this registry.
        """
        raise NotImplementedError

    def validate(self, code: Code) -> bool:
        """True when ``code`` normalizes without error."""
        try:
            self.normalize(code)
        except (ValueError, TypeError, AttributeError):
            return False
        return True

    def file_name(self, code: Code) -> str:
        """Parquet file name for a jurisdiction: ``{id}_html.parquet``."""
        return f"{self.normalize(code)}_html.parquet"

    def describe(self) -> str:
        return f"{self.country} via {self.scheme_name}"


class CBSScheme(JurisdictionScheme):
    """Netherlands: CBS gemeentecode, 4-digit string ("0363" for Amsterdam).

    The CBS registry sometimes prefixes "GM"; the prefix is stripped.
    """

    country = "NL"
    scheme_name = "CBS gemeentecode"

    def normalize(self, code: Code) -> str:
        s = str(code).strip().upper()
        if s.startswith("GM"):
            s = s[2:]
        if not s.isdigit():
            raise ValueError(f"not a CBS gemeentecode: {code!r}")
        return s.zfill(4)


class DicofreScheme(JurisdictionScheme):
    """Portugal: INE DICOFRE concelho code, 4 digits (district 2 + concelho 2)."""

    country = "PT"
    scheme_name = "DICOFRE"

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s.isdigit():
            raise ValueError(f"not a DICOFRE code: {code!r}")
        return s.zfill(4)


class INEMunicipioScheme(JurisdictionScheme):
    """Spain: INE 5-digit municipio code ("28079" for Madrid)."""

    country = "ES"
    scheme_name = "INE municipio"

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s.isdigit():
            raise ValueError(f"not an INE municipio code: {code!r}")
        return s.zfill(5)


class TerytScheme(JurisdictionScheme):
    """Poland: GUS TERYT codes (TERC/SIMC/ULIC). Uppercase alphanumeric."""

    country = "PL"
    scheme_name = "TERYT"

    def normalize(self, code: Code) -> str:
        s = str(code).strip().upper()
        if not s or not s.replace("-", "").isalnum():
            raise ValueError(f"not a TERYT code: {code!r}")
        return s


class MstScheme(JurisdictionScheme):
    """South Korea: NLIC ordinance MST identifiers."""

    country = "KR"
    scheme_name = "NLIC MST"

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s:
            raise ValueError(f"not an NLIC MST id: {code!r}")
        return s


class IbgeMunicipioScheme(JurisdictionScheme):
    """Brazil: IBGE 7-digit municipio code ("5208004" for Formosa, GO)."""

    country = "BR"
    scheme_name = "IBGE municipio"

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s.isdigit():
            raise ValueError(f"not an IBGE municipio code: {code!r}")
        return s.zfill(7)


class BpsScheme(JurisdictionScheme):
    """Indonesia: BPS/Kemendagri 4-digit region code ("3273" for Bandung)."""

    country = "ID"
    scheme_name = "BPS region"

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s.isdigit():
            raise ValueError(f"not a BPS region code: {code!r}")
        return s.zfill(4)


class NisGemeenteScheme(JurisdictionScheme):
    """Belgium: Statbel NIS 5-digit gemeente code ("24055" for Kortenberg)."""

    country = "BE"
    scheme_name = "NIS gemeente"

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s.isdigit():
            raise ValueError(f"not a NIS gemeente code: {code!r}")
        return s.zfill(5)


class MdbScheme(JurisdictionScheme):
    """South Africa: Municipal Demarcation Board (MDB) municipality codes.

    Three shapes, all uppercase alphanumeric, kept verbatim (no padding —
    district codes are NOT zero-padded in the official list):
    - metropolitan (Category A): 3 letters ("CPT", "JHB", "ETH", "BUF",
      "EKU", "TSH", "MAN", "NMA");
    - district (Category C): "DC" + 1-2 digits ("DC2", "DC44");
    - local (Category B): province prefix (EC/WC/KZN/MP/NW/LIM/GT/FS/NC)
      + 3 digits ("WC013", "EC443", "KZN292").
    The Laws.Africa / OpenByLaws AKN place is "za-" + the lowercased code
    (za-cpt, za-wc013) — provenance only, not the jurisdiction_id.
    """

    country = "ZA"
    scheme_name = "MDB municipality code"

    _METROS = {"BUF", "CPT", "EKU", "ETH", "JHB", "MAN", "NMA", "TSH"}
    _PROVINCES = ("EC", "WC", "KZN", "MP", "NW", "LIM", "GT", "FS", "NC")

    def normalize(self, code: Code) -> str:
        s = str(code).strip().upper()
        if s in self._METROS:
            return s
        if s.startswith("DC") and s[2:].isdigit() and 1 <= len(s[2:]) <= 2:
            return s
        for prov in self._PROVINCES:
            if s.startswith(prov) and s[len(prov):].isdigit() and len(s) == len(prov) + 3:
                return s
        raise ValueError(f"not an MDB municipality code: {code!r}")


class SgcScheme(JurisdictionScheme):
    """Canada: Statistics Canada SGC census subdivision (CSD) code.

    7 digits, telescoping: province/territory (2) + census division (2)
    + census subdivision (3) — "3520005" for Toronto, "5915022" for
    Vancouver, "2466023" for Montréal. The 2-digit prefix must be a real
    SGC province/territory code; codes are never zero-padded beyond the
    canonical 7 digits in the official list.
    """

    country = "CA"
    scheme_name = "SGC census subdivision"

    _PROVINCES = {
        "10", "11", "12", "13",  # Atlantic
        "24",                    # Quebec
        "35",                    # Ontario
        "46", "47", "48",        # Prairies
        "59",                    # British Columbia
        "60", "61", "62",        # Territories
    }

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s.isdigit() or len(s) > 7:
            raise ValueError(f"not an SGC census subdivision code: {code!r}")
        s = s.zfill(7)
        if s[:2] not in self._PROVINCES:
            raise ValueError(f"not an SGC census subdivision code: {code!r}")
        return s


class NzStatsScheme(JurisdictionScheme):
    """New Zealand: Stats NZ geographic classification codes.

    Two shapes, disjoint by construction:
    - territorial authorities (TA2023): 3-digit Stats NZ territorial
      authority code, zero-padded ("047" for Wellington City, "016" for
      Hamilton City, "076" for Auckland Council). The TA2023 classification
      spans 001-076 (68 categories incl. 999 "Area Outside Territorial
      Authority", excluded here); abolished codes (004-010, 014, 061)
      fall inside the numeric range and are shape-valid but unused.
    - regional councils: "R" + the region's ISO 3166-2:NZ subdivision
      code ("RNTL" Northland, "RWGN" Wellington, "RCAN" Canterbury) for
      the 11 regional councils that are not unitary authorities. The
      unitary authorities (Auckland, Gisborne, Nelson, Tasman,
      Marlborough, Chatham Islands) are registered once, as TAs.
    """

    country = "NZ"
    scheme_name = "Stats NZ TA2023 / ISO 3166-2:NZ region"

    _REGIONS = {
        "NTL", "WKO", "BOP", "HKB", "TKI",
        "MWT", "WGN", "WTC", "CAN", "OTA", "STL",
    }

    def normalize(self, code: Code) -> str:
        s = str(code).strip().upper()
        if s.startswith("R") and s[1:] in self._REGIONS:
            return s
        if s.isdigit():
            n = int(s)
            if 1 <= n <= 76:
                return s.zfill(3)
        raise ValueError(f"not a Stats NZ NZ jurisdiction code: {code!r}")


class ScbKommunkodScheme(JurisdictionScheme):
    """Sweden: SCB kommunkod (municipality code), 4 digits.

    Telescoping: län (county) code (2) + kommun code within the län (2) —
    "0180" for Stockholm, "1480" for Göteborg, "1280" for Malmö. The
    2-digit prefix must be one of the 21 real länskoder; SCB zero-pads
    to the canonical 4 digits. All 290 kommuner carry a code in this
    registry (Regioner och kommuner, SCB regional divisions).
    """

    country = "SE"
    scheme_name = "SCB kommunkod"

    _LAN = {
        "01",  # Stockholm
        "03",  # Uppsala
        "04",  # Södermanland
        "05",  # Östergötland
        "06",  # Jönköping
        "07",  # Kronoberg
        "08",  # Kalmar
        "09",  # Gotland
        "10",  # Blekinge
        "12",  # Skåne
        "13",  # Halland
        "14",  # Västra Götaland
        "17",  # Värmland
        "18",  # Örebro
        "19",  # Västmanland
        "20",  # Dalarna
        "21",  # Gävleborg
        "22",  # Västernorrland
        "23",  # Jämtland
        "24",  # Västerbotten
        "25",  # Norrbotten
    }

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s.isdigit() or len(s) > 4:
            raise ValueError(f"not an SCB kommunkod: {code!r}")
        s = s.zfill(4)
        if s[:2] not in self._LAN:
            raise ValueError(f"not an SCB kommunkod: {code!r}")
        return s


class AbsLgaScheme(JurisdictionScheme):
    """Australia: ABS ASGS Edition 3 LGA 2025 codes, 5 digits.

    Telescoping: state/territory code (1 digit) + LGA code within the
    state (4) — "10050" for Albury (NSW), "31000" for Brisbane (Qld),
    "24600" for Melbourne (Vic). The first digit must be a real ABS
    state code (1 NSW, 2 Vic, 3 Qld, 4 SA, 5 WA, 6 Tas, 7 NT, 8 ACT,
    9 Other Territories). The ABS file's non-geographic pseudo codes
    ("ZZZZZ" Outside Australia, xx499 "No usual address", xx799
    "Migratory - Offshore - Shipping") are not jurisdictions and fail
    the digit check.
    """

    country = "AU"
    scheme_name = "ABS LGA 2025"

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s.isdigit() or len(s) > 5:
            raise ValueError(f"not an ABS LGA code: {code!r}")
        s = s.zfill(5)
        if s[0] not in "123456789":
            raise ValueError(f"not an ABS LGA code: {code!r}")
        return s


class GkzScheme(JurisdictionScheme):
    """Austria: Statistik Austria Gemeindekennziffer (GKZ), 5 digits.

    Telescoping: Bundesland code (1 digit: 1 Burgenland, 2 Kärnten,
    3 Niederösterreich, 4 Oberösterreich, 5 Salzburg, 6 Steiermark,
    7 Tirol, 8 Vorarlberg, 9 Wien) + politischer Bezirk (2) + Gemeinde
    within the Bezirk (2) — "20402" for Ebenthal in Kärnten,
    "20101" for Klagenfurt am Wörthersee. Source: Statistik Austria,
    Regionales Gemeindeverzeichnis (RegGemVZ).
    """

    country = "AT"
    scheme_name = "Statistik Austria GKZ"

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s.isdigit() or len(s) > 5:
            raise ValueError(f"not a GKZ code: {code!r}")
        s = s.zfill(5)
        if s[0] not in "123456789":
            raise ValueError(f"not a GKZ code: {code!r}")
        return s


class AgsScheme(JurisdictionScheme):
    """Germany: Amtlicher Gemeindeschlüssel (AGS), 8 digits.

    Telescoping: Land (2) + Regierungsbezirk (1) + Kreis (2) +
    Gemeinde (3) — "01001000" for Flensburg, "09162000" for München,
    "11000000" for Berlin, "02000000" for Hamburg. The 2-digit Land
    prefix must be a real Land code (01–16). Source: Destatis
    Gemeindeverzeichnis (GV100). The 12-digit Amtlicher
    Regionalschlüssel (ARS) additionally embeds the Gemeindeverband
    key and is NOT the AGS — inputs longer than 8 digits are rejected.
    """

    country = "DE"
    scheme_name = "Destatis AGS"

    _LAENDER = {f"{n:02d}" for n in range(1, 17)}

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s.isdigit() or len(s) > 8:
            raise ValueError(f"not an AGS code: {code!r}")
        s = s.zfill(8)
        if s[:2] not in self._LAENDER:
            raise ValueError(f"not an AGS code: {code!r}")
        return s


class InegiMunicipioScheme(JurisdictionScheme):
    """Mexico: INEGI clave geoestadística municipal, 5 digits.

    Telescoping: entidad federativa (2) + municipio within the entidad
    (3) — "14039" for Guadalajara (Jalisco 14), "19039" for Monterrey
    (Nuevo León 19), "01001" for Aguascalientes. The 2-digit prefix must
    be a real entidad code (01–32) in the Catálogo Único de Claves de
    Áreas Geoestadísticas (AGEEML). The 16 CDMX alcaldías carry municipio
    codes under entidad 09 in the same catalog and are in scope as
    demarcaciones territoriales.
    """

    country = "MX"
    scheme_name = "INEGI clave geoestadistica"

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s.isdigit() or len(s) > 5:
            raise ValueError(f"not an INEGI municipio code: {code!r}")
        s = s.zfill(5)
        if not (1 <= int(s[:2]) <= 32):
            raise ValueError(f"not an INEGI municipio code: {code!r}")
        return s


class JisX0402Scheme(JurisdictionScheme):
    """Japan: JIS X 0402 / MIC 全国地方公共団体コード (local government code).

    Canonical form is the 5-digit code: prefecture (2 digits, 01-47) +
    municipality (3) — "01100" for Sapporo, "14100" for Yokohama,
    "40130" for Fukuoka. Prefectures themselves end in 000 ("13000" for
    Tokyo Metropolis); Tokyo's 23 special wards are 13101-13123, and the
    wards of designated cities carry their own codes in the registry
    (they do not enact ordinances independently — the city does).

    The MIC publishes the code with a 6th check digit appended
    ("011002" for Sapporo). A 6-digit input is accepted only when its
    check digit verifies: weights 6,5,4,3,2 over the five digits,
    check = 11 - (sum mod 11), with 10 mapping to 0 and 11 to 1
    (verified against all 1,794 rows of the MIC 2024-01-01 list in the
    Japan pilot). The check digit is then dropped.
    """

    country = "JP"
    scheme_name = "JIS X 0402"

    @staticmethod
    def _check_digit(code5: str) -> int:
        s = sum(int(d) * w for d, w in zip(code5, (6, 5, 4, 3, 2)))
        c = 11 - (s % 11)
        if c == 10:
            return 0
        if c == 11:
            return 1
        return c

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s.isdigit() or len(s) > 6:
            raise ValueError(f"not a JIS X 0402 code: {code!r}")
        s = s.zfill(5) if len(s) <= 5 else s
        if len(s) == 6:
            if self._check_digit(s[:5]) != int(s[5]):
                raise ValueError(f"JIS X 0402 check digit mismatch: {code!r}")
            s = s[:5]
        if not (1 <= int(s[:2]) <= 47):
            raise ValueError(f"not a JIS X 0402 code: {code!r}")
        return s


class CodeInseeScheme(JurisdictionScheme):
    """France: INSEE Code Officiel Géographique (COG) commune code.

    5 characters: département (2) + commune within the département (3) —
    "75056" for Paris, "69123" for Lyon, "13055" for Marseille. Two
    non-numeric département codes exist: Corse is split into "2A"
    (Corse-du-Sud, "2A004" Ajaccio) and "2B" (Haute-Corse, "2B033"
    Bastia); the old département 20 no longer exists. Outre-mer
    départements are 3 digits (971 Guadeloupe … 976 Mayotte, plus 977
    Saint-Barthélemy / 978 Saint-Martin) followed by a 2-digit commune
    ("97101" Les Abymes, "97302" Cayenne, "97411" Saint-Denis).
    Arrondissements municipaux (Paris 75101–75120 etc.) carry their own
    COG codes but are not communes and are excluded from the registry.
    """

    country = "FR"
    scheme_name = "INSEE COG commune"

    def normalize(self, code: Code) -> str:
        s = str(code).strip().upper()
        if s.startswith("2A") or s.startswith("2B"):
            if len(s) == 5 and s[2:].isdigit():
                return s
            raise ValueError(f"not an INSEE commune code: {code!r}")
        if not s.isdigit() or len(s) > 5:
            raise ValueError(f"not an INSEE commune code: {code!r}")
        s = s.zfill(5)
        dept2 = int(s[:2])
        if dept2 in (97, 98):
            if 971 <= int(s[:3]) <= 978:
                return s
            raise ValueError(f"not an INSEE commune code: {code!r}")
        if 1 <= dept2 <= 95 and dept2 != 20:
            return s
        raise ValueError(f"not an INSEE commune code: {code!r}")


class IstatCodiceScheme(JurisdictionScheme):
    """Italy: ISTAT codice comune, 6 digits.

    Telescoping: provincia (3) + comune within the provincia (3) —
    "058091" for Roma, "015146" for Milano, "082053" for Palermo,
    "001001" for Agliè (Torino). The 3-digit prefix must be one of the
    107 province / autonomous-province / metropolitan-city codes in
    ISTAT's official Elenco comuni (verified against the 2026 registry:
    7,896 comuni; prefixes run 001-103 — with 104-107 unused — plus
    108 Monza e della Brianza, 109 Fermo, 110 Barletta-Andria-Trani,
    111 Sud Sardegna). ISTAT also serializes the code numerically
    (dropping leading zeros); the canonical form here is the registry's
    6-digit alphanumeric form.
    """

    country = "IT"
    scheme_name = "ISTAT codice comune"

    _PROVINCES = frozenset(
        [f"{n:03d}" for n in range(1, 104)]
        + ["108", "109", "110", "111"]
    )

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s.isdigit() or len(s) > 6:
            raise ValueError(f"not an ISTAT codice comune: {code!r}")
        s = s.zfill(6)
        if s[:3] not in self._PROVINCES:
            raise ValueError(f"not an ISTAT codice comune: {code!r}")
        return s


class LauScheme(JurisdictionScheme):
    """EU: Eurostat LAU codes (uniform registry for EU member states)."""

    country = "EU"
    scheme_name = "Eurostat LAU"

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s:
            raise ValueError(f"not a LAU code: {code!r}")
        return s


class GnisScheme(JurisdictionScheme):
    """US reference: GNIS feature ID (the US municipal program's key)."""

    country = "US"
    scheme_name = "GNIS"

    def normalize(self, code: Code) -> str:
        s = str(code).strip()
        if not s.isdigit():
            raise ValueError(f"not a GNIS id: {code!r}")
        return s


SCHEMES: Dict[str, JurisdictionScheme] = {
    "NL": CBSScheme(),
    "PT": DicofreScheme(),
    "ES": INEMunicipioScheme(),
    "PL": TerytScheme(),
    "KR": MstScheme(),
    "BR": IbgeMunicipioScheme(),
    "ID": BpsScheme(),
    "BE": NisGemeenteScheme(),
    "ZA": MdbScheme(),
    "CA": SgcScheme(),
    "NZ": NzStatsScheme(),
    "SE": ScbKommunkodScheme(),
    "AU": AbsLgaScheme(),
    "AT": GkzScheme(),
    "DE": AgsScheme(),
    "MX": InegiMunicipioScheme(),
    "JP": JisX0402Scheme(),
    "FR": CodeInseeScheme(),
    "IT": IstatCodiceScheme(),
    "EU": LauScheme(),
    "US": GnisScheme(),
}


def get_scheme(country: str) -> JurisdictionScheme:
    """Return the jurisdiction scheme for an ISO-2 country code (or "EU"/"US").

    Raises KeyError for countries without a registered scheme — register one
    before harvesting that country.
    """
    key = (country or "").strip().upper()
    try:
        return SCHEMES[key]
    except KeyError:
        raise KeyError(
            f"no jurisdiction scheme registered for {country!r}; "
            f"registered: {sorted(SCHEMES)}"
        ) from None


def normalize_jurisdiction_id(country: str, code: Code) -> str:
    """Convenience: normalize a registry code for a country in one call."""
    return get_scheme(country).normalize(code)


def jurisdiction_file_name(country: str, code: Code) -> str:
    """Convenience: ``{jurisdiction_id}_html.parquet`` for a country + code."""
    return get_scheme(country).file_name(code)
