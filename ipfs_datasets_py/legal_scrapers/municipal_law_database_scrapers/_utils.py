
from pydantic import BaseModel, Field
from pydantic import BaseModel, ConfigDict
from typing import Optional

from pathlib import Path

from typing import Annotated as Ann, Any, List, LiteralString, Pattern, Optional


from pydantic import BaseModel, Field

import re


from pydantic import AfterValidator as AV, BaseModel, field_validator



class MunicodeDoc(BaseModel):
    DocType: int
    IsAmended: bool
    IsUpdated: bool
    CompareStatus: int
    DocOrderId: int
    ChunkGroupStartingNodeId: str
    NodeDepth: int
    title_html: str = Field(..., alias="TitleHtml")
    id: str = Field(..., alias="Id")
    title: str = Field(..., alias="Title")
    content: str = Field(..., alias="Content")
    AmendedBy: Optional[list[dict]] = None
    Notes: Optional[list[str]] = None
    Drafts: Optional[list[str]] = None
    SortDate: Optional[str] = None
    Footnotes: Optional[str] = None


class MunicodeData(BaseModel):
    """
    Example:
        "Data": {
            "NodeKey": null,
            "IsUpdated": false,
            "IsAmended": false,
            "HasAmendedDescendant": false,
            "CompareStatus": 2,
            "DocType": 1,
            "DepthOverride": null,
            "ChunkGroupStartingId": null
        }
    """
    NodeKey: Optional[str] = None
    IsUpdated: bool
    IsAmended: bool
    HasAmendedDescendant: bool
    CompareStatus: int
    DocType: int
    DepthOverride: Optional[int] = None
    ChunkGroupStartingId: Optional[str] = None


class MunicodeChild(BaseModel):
    """
    Example:
        {
            "Id": "COMUCO1987",
            "Heading": "COTTONWOOD MUNICIPAL CODE 1987",
            "NodeDepth": 1,
            "HasChildren": false,
            "ParentId": "16298",
            "DocOrderId": 1,
            "Children": [],
            "Data": {
               ...
            }
        },
    """
    Id: str # NOTE Id needed for API call
    Heading: str
    NodeDepth: int
    HasChildren: bool
    ParentId: str
    DocOrderId: int
    Children: List['MunicodeChild'] = Field(default_factory=list)
    Data: MunicodeData


MunicodeChild.model_rebuild()  # This is needed for the recursive type reference


class MunicodeCodesToc(BaseModel):
    """
    Example API Call:
        https://api.municode.com/codesToc?jobId=462716&productId=16298

    Example Return:
        {
            "Id": "16298",
            "Heading": "Code of Ordinances",
            "NodeDepth": -1,
            "HasChildren": true,
            "ParentId": null,
            "DocOrderId": -1,
            "Children": [
                ...
            ],
            "Data": {
                ...
            }
        }
    """
    Id: str
    Heading: str
    NodeDepth: int
    HasChildren: bool
    ParentId: Optional[str] = None
    DocOrderId: int
    Children: List[MunicodeChild]
    Data: MunicodeData

MunicodeCodesToc.model_rebuild()  # This is needed for the recursive type reference


class MunicodeContentType(BaseModel):
    """
    Identifying information about a Municode content type.

    Example:
        "ContentType": {
            "Id": "CODES",
            "Name": "Codes",
            "DefaultOrder": 10,
            "IsSearchable": true
        },
    """
    Id: Optional[str]
    Name: Optional[str]
    DefaultOrder: Optional[int]
    IsSearchable: Optional[bool]


class MunicodeFeatures(BaseModel):
    """
    Features available to a given client.

    Example:
        "Features": {
            "CodeBank": true,
            "NOW": false,
            "OrdBank": false,
            "AutomatedOrdLink": false,
            "CodeBankCompare": true,
            "HideInLibrary": false,
            "IntegratedSearch": true,
            "PublicationNotifications": true,
            "ShowGoogleTranslate": true
        },
    """
    CodeBank: Optional[bool] = None
    NOW: Optional[bool] = None 
    OrdBank: Optional[bool] = None
    AutomatedOrdLink: Optional[bool] = None
    CodeBankCompare: Optional[bool] = None
    HideInLibrary: Optional[bool] = None
    IntegratedSearch: Optional[bool] = None
    PublicationNotifications: Optional[bool] = None
    ShowGoogleTranslate: Optional[bool] = None


class MunicodeState(BaseModel):
    """
    Identifying information about a US state.

    Example:
        "State": {
            "StateID": 3,
            "StateName": "Arizona",
            "StateAbbreviation": "AZ"
        },
    """
    StateID: int
    StateName: str
    StateAbbreviation: str


class MunicodeClient(BaseModel):
    """
    Identifying information about a given Municode client.

    Example:
        "Client": {
            "PopRangeId": "5",
            "ClassificationId": "2",
            "Phone": "6345526",
            "ClientID": 1789,
            "ClientName": "Cottonwood",
            "State": {
                "StateID": 3,
                "StateName": "Arizona",
                "StateAbbreviation": "AZ"
            },
            "Address": "824 N. Main St",
            "Address2": "",
            "City": "Cottonwood",
            "ZipCode": 86326,
            "Website": "cottonwoodaz.gov/",
            "ShowAdvanceSheet": true,
            "LibraryHomePageTemplateName": "default",
            "LibraryMobileHomePageTemplateName": "default",
            "Meetings": null
        },
    """
    PopRangeId: Optional[str] = None
    ClassificationId: Optional[str] = None
    Phone: Optional[str] = None           
    ClientID: int               # NOTE Necessary Field
    ClientName: str             # NOTE Necessary Field
    State: MunicodeState        # NOTE Necessary Field
    Address: str                # NOTE Necessary Field
    Address2: Optional[str] = None
    City: str                   # NOTE Necessary Field
    ZipCode: int                # NOTE Necessary Field
    Website: str                # NOTE Necessary Field
    ShowAdvanceSheet: Optional[bool] = None
    LibraryHomePageTemplateName: Optional[str] = None
    LibraryMobileHomePageTemplateName: Optional[str] = None
    Meetings: Optional[str] = None


class MunicodeProduct(BaseModel):
    """
    Identifying information about a given Municode product.

    Example:
        "Product": {
            "ContentType": {
                ...
            },
            "Features": {
                ...  
            },
            "Client": {
                ...
            },
            "ProductID": 16298,
            "ProductName": "Code of Ordinances",
            "HasNOW": false,
            "Disclaimer": "This Code of Ordinances and/or any other documents that appear...",
            "WebIntro": "The listing below includes all legislation received by Municipal Code...",
            "BannerText": null,
            "PaddedProductId": "16298",
            "LandingPageID": 1,
            "ExternalCodeLink": null,
            "SearchIntegrationTypeId": 2,
            "SearchIntegrationBaseUrl": "cottonwoodaz.gov/"
        },
    """
    ContentType: MunicodeContentType
    Features: MunicodeFeatures
    Client: MunicodeClient
    ProductID: int      # NOTE Necessary field
    ProductName: str    # NOTE Necessary field
    HasNOW: Optional[bool] = None
    Disclaimer: Optional[str] = None
    WebIntro: Optional[str] = None
    BannerText: Optional[str] = None
    PaddedProductId: Optional[str] = None
    LandingPageID: Optional[int] = None
    ExternalCodeLink: Optional[str] = None
    SearchIntegrationTypeId: Optional[int] = None
    SearchIntegrationBaseUrl: Optional[str] = None


class MunicodeJob(BaseModel):
    """
    This API call returns metadata about a specific job, 
        which is Municode's term for the codes and other documents that this city/place has contracted them to store.

    Example API Call:
        https://api.municode.com/Jobs/latest/16298

    Example Return:
        {
            "Id": 462716,
            "Name": "Supplement 24 Update 2",
            "ProductId": 16298,
            "Product": {
                ...  
            },
            "PublishDate": "2024-09-17T04:00:00",
            "MaxTrackingDate": "2024-11-15T11:36:59",
            "OnlinePostDate": "2024-11-15T13:14:47.659236",
            "IsLatest": true,
            "BannerText": "COTTONWOOD\r\nMUNICIPAL CODE\r\n\r\nCodified through\r\nOrdinance No. 749, passed July 16, 2024.\r\n(Supp. No. 24 (11/24) Update 2)",
            "OnlineDate": "2024-11-15T11:36:59"
        }
    """
    Id: int                     # NOTE Jobid needed for API call
    Name: str
    ProductId: int              # NOTE productid needed for API call
    Product: MunicodeProduct
    PublishDate: str            # NOTE Necessary Field
    MaxTrackingDate: Optional[str] = None
    OnlinePostDate: Optional[str] = None
    IsLatest: Optional[bool] = None
    BannerText: str             # NOTE Necessary Field
    OnlineDate: Optional[str] = None


class ECodeDoc(BaseModel):
    """ECode360 Document Information"""
    id: int = Field(..., description="Unique identifier for the document")
    title: str = Field(..., description="The title of the document")
    content: str = Field(..., description="The content of the document")

class Charter(BaseModel):
    """AM Legal Charter Information"""
    code_slug: str
    destinations: dict

class CodeLookup(BaseModel):
    """AM Legal Code Lookup Information"""
    charter: Charter

class AmLegalDoc(BaseModel):
    """AM Legal Document Information"""
    id: int
    doc_id: str
    orig_doc_id: str
    orig_doc_idx: int
    title: str
    code_lookup: CodeLookup


########## URL Pattern Models ##########


def _compile_pattern(v: str) -> Pattern:
    """Compile a string pattern into a regex Pattern object."""
    try:
        return re.compile(v)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern: {v}. Error: {e}")




class AmLegalUrlPatterns(BaseModel):
    """
    A class representing URL patterns for American Legal API endpoints.

    Attributes:
        API_URL (Pattern): Compiled regex pattern for the base API URL.
        CODES_TOC (Pattern): Compiled regex pattern for the codes table of contents endpoint.
        JOBS (Pattern): Compiled regex pattern for the jobs endpoint.

    """
    API_URL: LiteralString |Pattern = r"https://api\.amlegal\.com"


class MunicodeUrlPatterns(BaseModel):
    """
    A class representing URL patterns for Municode API endpoints.

    Attributes:
        API_URL (Pattern): Compiled regex pattern for the base API URL.
        CODES_TOC (Pattern): Compiled regex pattern for the codes table of contents endpoint.
        JOBS (Pattern): Compiled regex pattern for the jobs endpoint.
    """
    API_URL: LiteralString |Pattern = r"https://api\.municode\.com"
    CODES_TOC: LiteralString | Pattern = r"https://api\.municode\.com/codesToc\?"
    JOBS: LiteralString | Pattern = r'https://api\.municode\.com/Jobs/latest'


########## Output Models ##########

class MetaData(BaseModel):
    """
    A Pydantic model representing metadata for an API call.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    gnis: str
    job_id: str
    product_id: str
    json_filepath: Path
    csv_filepath: Path 

class MunicodeOutput(BaseModel):
    """
    A Pydantic model representing the output of a Municode API call.
    
    Attributes:
        metadata (MetaData): Metadata associated with the output.
        api_url_dict (dict[str, Any]): A dictionary containing API URLs and related information.
        docs (list[MunicodeDoc]): A list of MunicodeDoc objects. Defaults to an empty list.

    """
    metadata: MetaData
    api_url_dict: dict[str, Any]
    docs: list[MunicodeDoc] = Field(default_factory=list)
