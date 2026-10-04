# Processors Architecture Diagram

## High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER INPUT                              │
│    (URL / File / Folder / Text / Binary / Any Content)         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   UniversalProcessor                            │
│            "Single Entry Point for Everything"                  │
│                                                                 │
│  Methods:                                                       │
│  • process(input) → ProcessingResult                            │
│  • process_batch([inputs]) → [ProcessingResult]                 │
│  • process_folder(path) → [ProcessingResult]                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      InputDetector                              │
│         "What type of input is this?"                           │
│                                                                 │
│  Detects:                                                       │
│  ✓ URLs (http/https/ipfs/file://)                              │
│  ✓ File paths + formats (PDF/DOCX/MP4/JPG/etc)                 │
│  ✓ Folders (directories)                                        │
│  ✓ Text content                                                 │
│  ✓ Binary data                                                  │
│                                                                 │
│  Output: ProcessingContext with metadata                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   ProcessorRegistry                             │
│         "Which processor can handle this?"                      │
│                                                                 │
│  • Maintains list of all processors                             │
│  • Checks each processor's can_handle(context)                  │
│  • Returns best match based on priority                         │
│  • Supports pluggable processors                                │
└──────────────────────────┬──────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
         ▼                 ▼                 ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│  PDFAdapter    │  │ GraphRAGAdapter│  │ MediaAdapter   │
│   Priority: 40 │  │  Priority: 50  │  │  Priority: 60  │
└────────┬───────┘  └────────┬───────┘  └────────┬───────┘
         │                   │                   │
         ▼                   ▼                   ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│ PDFProcessor   │  │UnifiedGraphRAG │  │FFmpegWrapper   │
│ + OCR engines  │  │ + Entity Ext.  │  │+ yt-dlp        │
└────────┬───────┘  └────────┬───────┘  └────────┬───────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             ▼
         ┌───────────────────────────────────────┐
         │    Knowledge Graph Builder            │
         │    + Vector Embeddings Generator      │
         └───────────────────┬───────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   ProcessingResult                              │
│              (Standardized Output Format)                       │
│                                                                 │
│  • success: bool                                                │
│  • knowledge_graph: {entities, relationships, properties}       │
│  • vectors: [[float]] (embeddings)                              │
│  • metadata: {format, size, processing_time, etc}               │
│  • errors: [str]                                                │
│  • warnings: [str]                                              │
└─────────────────────────────────────────────────────────────────┘
```

## Detailed Adapter Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    ProcessorProtocol                            │
│              (Interface all adapters implement)                 │
│                                                                 │
│  def can_handle(context: ProcessingContext) -> bool            │
│  def process(context: ProcessingContext) -> ProcessingResult   │
│  def get_capabilities() -> Dict[str, Any]                      │
└─────────────────────────────────────────────────────────────────┘
                             │
                             │ implements
                             ▼
      ┌──────────────────────────────────────────────┐
      │                                              │
      ▼                  ▼                  ▼        ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ PDFAdapter   │  │GraphRAGAdptr │  │ MediaAdapter │  │ LegalAdapter │
│              │  │              │  │              │  │              │
│ Handles:     │  │ Handles:     │  │ Handles:     │  │ Handles:     │
│ • .pdf       │  │ • URLs       │  │ • .mp4       │  │ • Legal URLs │
│ • .ps        │  │ • .html      │  │ • .mp3       │  │ • .law docs  │
│              │  │ • .txt       │  │ • .jpg       │  │              │
│ Priority: 40 │  │ Priority: 50 │  │ Priority: 60 │  │ Priority: 45 │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
      │                  │                  │                  │
      ▼                  ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│PDFProcessor  │  │UnifiedGraphRAG│ │FFmpegWrapper │  │LegalScraper  │
│+ Tesseract   │  │+ Entity Extract│ │+ yt-dlp      │  │+ Case Extract│
│+ Surya OCR   │  │+ Relationship │  │+ Media Utils │  │+ Citation    │
│+ EasyOCR     │  │+ SPARQL       │  │+ Transcribe  │  │  Parser      │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
```

## Input Detection Logic

```
┌─────────────────────────────────────────────────────────────────┐
│                         INPUT                                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ Is it a URL? │
                    └──────┬───────┘
                           │
                    Yes ┌──┴──┐ No
                        │     │
                        ▼     ▼
                   ┌─────┐  ┌──────────────────┐
                   │ URL │  │ Is it a path?    │
                   └─────┘  └────────┬─────────┘
                      │               │
                      │        Yes ┌──┴──┐ No
                      │            │     │
                      │            ▼     ▼
                      │      ┌─────────┐ ┌──────────────┐
                      │      │ File/   │ │ Is it text?  │
                      │      │ Folder  │ └──────┬───────┘
                      │      └────┬────┘        │
                      │           │      Yes ┌──┴──┐ No
                      │           │          │     │
                      │           ▼          ▼     ▼
                      │      ┌─────────┐ ┌─────┐ ┌──────┐
                      │      │ Format  │ │Text │ │Binary│
                      │      │Detection│ └─────┘ └──────┘
                      │      └────┬────┘
                      │           │
                      └───────────┼───────────────────────┘
                                  ▼
                     ┌───────────────────────────┐
                     │   ProcessingContext       │
                     │                           │
                     │ • input_type              │
                     │ • source                  │
                     │ • format (PDF/MP4/etc)    │
                     │ • metadata                │
                     │ • options                 │
                     └───────────────────────────┘
```

## Processor Selection Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                   ProcessingContext                             │
│  (input_type=FILE, format=PDF, source="doc.pdf")               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              ProcessorRegistry.find_processor()                 │
│                                                                 │
│  Step 1: Get all processors sorted by priority                  │
│  Step 2: For each processor, check can_handle(context)          │
│  Step 3: Return first processor that returns True               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ Priority-sorted List:  │
              │                        │
              │ 1. LegalAdapter (45)   │ ✗ can_handle = False
              │ 2. PDFAdapter (40)     │ ✓ can_handle = True ← SELECTED
              │ 3. GraphRAGAdapter(50) │ (not checked)
              │ 4. MediaAdapter (60)   │ (not checked)
              └────────────────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  PDFAdapter  │
                    │  processes   │
                    │  the input   │
                    └──────────────┘
```

## Knowledge Graph & Vector Generation

```
┌─────────────────────────────────────────────────────────────────┐
│                 Specialized Processor                           │
│              (e.g., PDFProcessor)                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
         ┌─────────────────┴──────────────────┐
         │                                    │
         ▼                                    ▼
┌────────────────────┐              ┌────────────────────┐
│  Content Extraction│              │ Metadata Extraction│
│                    │              │                    │
│ • Text from PDF    │              │ • Author           │
│ • OCR if needed    │              │ • Date             │
│ • Structure parse  │              │ • Title            │
└──────────┬─────────┘              └─────────┬──────────┘
           │                                  │
           └──────────────┬───────────────────┘
                          ▼
         ┌────────────────────────────────┐
         │   Knowledge Graph Builder      │
         │                                │
         │ 1. Entity Extraction           │
         │    • People                    │
         │    • Organizations             │
         │    • Locations                 │
         │    • Concepts                  │
         │                                │
         │ 2. Relationship Extraction     │
         │    • works_at                  │
         │    • mentions                  │
         │    • located_in                │
         │    • related_to                │
         │                                │
         │ 3. Property Extraction         │
         │    • Attributes                │
         │    • Values                    │
         └────────────┬───────────────────┘
                      │
                      ▼
         ┌────────────────────────────────┐
         │  Vector Embeddings Generator   │
         │                                │
         │ • Chunk text                   │
         │ • Generate embeddings          │
         │ • Create vector index          │
         └────────────┬───────────────────┘
                      │
                      ▼
         ┌────────────────────────────────┐
         │      ProcessingResult          │
         │                                │
         │ knowledge_graph = {            │
         │   "entities": [...],           │
         │   "relationships": [...],      │
         │   "properties": {...}          │
         │ }                              │
         │                                │
         │ vectors = [[0.1, 0.2, ...]]    │
         └────────────────────────────────┘
```

## Batch Processing Flow

```
┌─────────────────────────────────────────────────────────────────┐
│              UniversalProcessor.process_batch()                 │
│                 [file1, file2, file3, ...]                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
         ┌─────────────────────────────────────┐
         │      ParallelProcessor               │
         │   (ThreadPoolExecutor/asyncio)       │
         └─────────────┬───────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         │             │             │
         ▼             ▼             ▼
    ┌────────┐   ┌────────┐   ┌────────┐
    │Worker 1│   │Worker 2│   │Worker 3│
    │        │   │        │   │        │
    │process │   │process │   │process │
    │(file1) │   │(file2) │   │(file3) │
    └────┬───┘   └────┬───┘   └────┬───┘
         │            │            │
         └────────────┼────────────┘
                      ▼
         ┌────────────────────────┐
         │   Aggregate Results    │
         │                        │
         │ [result1, result2,     │
         │  result3, ...]         │
         └────────────────────────┘
```

## Extension: Adding Custom Processor

```
┌─────────────────────────────────────────────────────────────────┐
│                  1. Create Custom Processor                     │
│                                                                 │
│  class MyCustomProcessor:                                       │
│      def can_handle(self, context):                             │
│          return context.format == 'my_format'                   │
│                                                                 │
│      def process(self, context):                                │
│          # Your processing logic                                │
│          return ProcessingResult(...)                           │
│                                                                 │
│      def get_capabilities(self):                                │
│          return {"name": "MyProcessor", ...}                    │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                  2. Register Processor                          │
│                                                                 │
│  processor = UniversalProcessor()                               │
│  processor.registry.register(                                   │
│      "my_processor",                                            │
│      MyCustomProcessor(),                                       │
│      priority=45                                                │
│  )                                                              │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                  3. Use Automatically                           │
│                                                                 │
│  result = processor.process("my_file.my_format")                │
│  # Automatically routes to MyCustomProcessor                    │
└─────────────────────────────────────────────────────────────────┘
```

## Caching Layer

```
┌─────────────────────────────────────────────────────────────────┐
│              UniversalProcessor.process(input)                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
         ┌─────────────────────────────────┐
         │        ProcessingCache          │
         │     (Memory/Redis/File)         │
         └──────────────┬──────────────────┘
                        │
              ┌─────────┴─────────┐
              │ Cache Key:        │
              │ hash(input)       │
              └─────────┬─────────┘
                        │
                 ┌──────┴──────┐
                 │ Hit?        │
                 └──────┬──────┘
                        │
                Yes ┌───┴───┐ No
                    │       │
                    ▼       ▼
           ┌────────────┐  ┌───────────────┐
           │ Return     │  │ Process &     │
           │ Cached     │  │ Cache Result  │
           │ Result     │  └───────────────┘
           └────────────┘
```

---

**Legend:**
- `→` Flow direction
- `┌─┐` Component boundary
- `▼` Process step
- `✓` Success/Selected
- `✗` Rejected/Not selected

**Colors (conceptual):**
- Input/Output: Blue
- Processing: Green
- Decision: Yellow
- Cache/Optimization: Orange

---

See `PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` for detailed implementation.
