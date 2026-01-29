# Municode API Output - JSON Schema
## Author: Kyle Rose
## Date: 3-17-2025

## Definitions
### General
- Document: A chunk of legal text. Can be standalone or part of a larger law chunk. Ex: "Chapter 3, Section 10, Sub-section 5".
- Node Tree: Shorthand for the nested JSON structure of Municode's API output.
- Node ID: Municode's ID for a chunk of legal text. Appears to be an abbreviation of the document's name. Ex: "COOR_CH1GEPR"

### API-Specific
- DocType: Municode's categorization of the document. Documents are all 1.
- IsAmended: Whether the document has been amended since it was first written.
- IsUpdated: Whether the document has been updated in Municode as compared to current municipal law.
- CompareStatus: Unknown.
- DocOrderId: The ascending order of the document in the municipalities law corpus, starting at 1.
- ChunkGroupStartingNodeId: The top-level node ID of the node tree where the current document is located.
- NodeDepth: How deep in the node tree the current document is located. Higher numbers mean the document is deeper in the nested JSON.
- TitleHtml: The title of the current document in HTML
- Id: The node id of the document.
- Title: The tile of the current document in plain text.
- Content: The legal text itself in HTML.
- AmendedBy: Unknown
- Drafts: Unknown
- SortDate: Unknown
- Footnotes: List of footnotes that the document references

## Pydantic Schema
```python
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
```

# Example JSON
```json
"{\n  \"DocType\": 1,\n  \"IsAmended\": false,\n  \"IsUpdated\": false,\n  \"CompareStatus\": 4,\n  \"DocOrderId\": 18,\n  \"ChunkGroupStartingNodeId\": \"COOR_CH1GEPR\",\n  \"NodeDepth\": 2,\n  \"TitleHtml\": \"<div class=\\\"chunk-title\\\">Sec. 1-14. - Supplementation of Code.</div>\",\n  \"Id\": \"COOR_CH1GEPR_S1-14SUCO\",\n  \"Title\": \"Sec. 1-14. - Supplementation of Code.\",\n  \"Content\": \"<div class=\\\"chunk-content\\\">\\n            <p class=\\\"incr0\\\">\\n               (a)\\n               </p>\\n            \\t\\t\\n            <p class=\\\"content1\\\">\\n               By contract or by town personnel, supplements to this Code shall be prepared and printed\\n               whenever authorized or directed by the board of trustees. A supplement to this Code\\n               shall include all substantive permanent and general parts of ordinances adopted during\\n               the period covered by the supplement and all changes made thereby in this Code. The\\n               pages of a supplement shall be so numbered that they will fit properly in this Code\\n               and will, where necessary, replace pages which have become obsolete or partially obsolete,\\n               and the new pages shall be so prepared that, when they have been inserted, this Code\\n               will be current through the date of the adoption of the latest ordinance included\\n               in the supplement.\\n               </p>\\n            \\t\\t\\n            <p class=\\\"incr0\\\">\\n               (b)\\n               </p>\\n            \\t\\t\\n            <p class=\\\"content1\\\">\\n               In preparing a supplement to this Code, all portions of this Code which have been\\n               repealed shall be excluded from this Code by the omission thereof from reprinted pages.\\n               </p>\\n            \\t\\t\\n            <p class=\\\"incr0\\\">\\n               (c)\\n               </p>\\n            \\t\\t\\n            <p class=\\\"content1\\\">\\n               When preparing a supplement to this Code, the codifier (meaning the person, agency\\n               or organization authorized to prepare the supplement) may make formal, nonsubstantive\\n               changes in ordinances and parts of ordinances included in the supplement, insofar\\n               as it is necessary to do so to embody them into a unified Code. For example, the codifier\\n               may:\\n               </p>\\n            \\t\\t\\n            <p class=\\\"incr1\\\">\\n               (1)\\n               </p>\\n            \\t\\t\\n            <p class=\\\"content2\\\">\\n               Organize the ordinance material into appropriate subdivisions.\\n               </p>\\n            \\t\\t\\n            <p class=\\\"incr1\\\">\\n               (2)\\n               </p>\\n            \\t\\t\\n            <p class=\\\"content2\\\">\\n               Provide appropriate catchlines, headings and titles for sections and other subdivisions\\n               of the Code printed in the supplement, and make changes in such catchlines, headings\\n               and titles.\\n               </p>\\n            \\t\\t\\n            <p class=\\\"incr1\\\">\\n               (3)\\n               </p>\\n            \\t\\t\\n            <p class=\\\"content2\\\">\\n               Assign appropriate numbers to sections and other subdivisions to be inserted in the\\n               Code and, where necessary to accommodate new material, change existing section or\\n               other subdivision numbers.\\n               </p>\\n            \\t\\t\\n            <p class=\\\"incr1\\\">\\n               (4)\\n               </p>\\n            \\t\\t\\n            <p class=\\\"content2\\\">\\n               Change the words \\\"this ordinance\\\" or words of the same meaning to \\\"this chapter,\\\"\\n               \\\"this article,\\\" \\\"this division,\\\" etc., as the case may be, or to \\\"sections _____ to\\n               _____ \\\" (inserting section numbers to indicate the sections of the Code which embody\\n               the substantive sections of the ordinance incorporated into the Code).\\n               </p>\\n            \\t\\t\\n            <p class=\\\"incr1\\\">\\n               (5)\\n               </p>\\n            \\t\\t\\n            <p class=\\\"content2\\\">\\n               Make other nonsubstantive changes necessary to preserve the original meaning of ordinance\\n               sections inserted into the Code; but in no case shall the codifier make any change\\n               in the meaning or effect of ordinance material included in the supplement or already\\n               embodied in the Code.\\n               </p>\\n            \\t\\t\\n            <p class=\\\"historynote0\\\">\\n               (Prior Code, § 1-177(2))\\n               </p></div>\",\n  \"AmendedBy\": [],\n  \"Notes\": [],\n  \"Drafts\": [],\n  \"SortDate\": null,\n  \"Footnotes\": null\n}"
```