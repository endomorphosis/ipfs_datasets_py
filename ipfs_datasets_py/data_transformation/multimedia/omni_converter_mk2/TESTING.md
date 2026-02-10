# Omni-Converter - Testing Guidelines

## 1. Format Support Coverage

### Target
- 5 formats per category
- 80% use case coverage

### Formula
$\text{Coverage Factor} = \frac{\text{Number of Supported Formats}}{\text{Total Formats in Test Dataset}} \geq 0.8$

Constraint: $\text{Number of Supported Formats} \geq 5$ per category

Where:
- $\text{Supported Format}$ is any file type where the converter has the ability to successfully extract content without modifying the converter.

### Action Plan
- Create a standardized test dataset with 3-5 examples of each supported format
- Implement automated format detection tests that run against this dataset
- Include basic edge cases (password protection, non-English text) but limit scope
- Track format failures in early deployment to identify gaps in coverage

## 2. Processing Success Rate

### Target:
95% of valid files

### Formula
$\text{Success Rate} = \frac{\text{Number of Successfully Processed Files}}{\text{Number of Valid Files in Supported Formats}} \geq 0.95$

Where:
- $\text{Successfully Processed File}$ is:
    - 1. Completes the entire conversion pipeline without a critical error
    - 2. Meets the the quality thresholds as specified in Section 7. Text Quality for LLM Training
- $\text{Valid File}$ is:
    - 1. A file with a supported format.
    - 2. Non-corrupted as specified in Section 5. Error Handling Effectiveness
    - 3. Not empty
    - 4. Contains any sort of content that can be converted into human/LLM-readable text.

### Action Plan
- Build a simple batch testing framework that logs successes and failures
- Test with 50-100 varied files rather than thousands
- Include 10-15 deliberately corrupted files for error handling validation
- Use synthetic datasets initially, moving to real data when available

## 3. Resource Utilization

### Target
- < 6GB RAM
- < 80% CPU

### Formula
$\text{Peak Memory Usage} < 6\text{GB}$

$\text{CPU Utilization Percentage} < 0.8 \times \text{Total CPU Capacity}$

Where:
- $\text{Peak Memory Usage}$ is the maximum RAM consumption reached by the program during a test run.
- $\text{Total CPU capacity}$ is 100% utilization of all available physical cores.

### Action Plan
- Implement basic resource monitoring that logs memory and CPU usage during tests
- Include moderate stress tests (2x expected load) but not extreme cases initially
- Run shortened duration tests (1-2 hours) instead of 24+ hours
- Test primarily on development hardware, with limited tests on minimum spec machine

## 4. Processing Speed

### Target
- 100 text documents per minute
- 10 audio files per minute
- 10 video files per minute
- 10 application files per minute
- 1 video file per minute

### Formula
$\text{Processing Speed (Text)} \geq \frac{100\text{Files}}{\text{minute}}$ for Text Documents

$\text{Processing Speed (Images)} \geq \frac{10\text{Files}}{\text{minute}}$ for Image Files

$\text{Processing Speed (Audio)} \geq \frac{10\text{Files}}{\text{minute}}$ for Audio Files

$\text{Processing Speed (Video)} \geq \frac{1\text{Files}}{\text{minute}}$ for Video Files

$\text{Processing Speed (Application)} \geq \frac{10\text{Files}}{\text{minute}}$ for Application Files

Where:
- $\text{Files}$ are discrete units of data submitted for conversion, each with their own metadata, content structure, and processing requirements.
- $\text{Text Documents}$ are files that are categorized under the 'text' MIME type.
- $\text{Image Files}$ are files that are categorized under the 'image' MIME type.
- $\text{Audio Files}$ are files that are categorized under the 'audio' MIME type.
- $\text{Video Files}$ are files that are categorized under the 'video' MIME type.
- $\text{Application Files}$ are files that are categorized under the 'application' MIME type.

### Action Plan
- Create simple benchmarks with standardized 1MB text files, 10MB audio, image, and application files, and 100MB video files.
- Include basic scaling tests with 2-3 file sizes
- Test with a small mixed-format dataset (10-15 files of different types)
- Limit concurrent processing tests to what development hardware can support

## 5. Error Handling Effectiveness

### Target
- 100% reliability for 30% corrupt files

### Formula
$\text{Batch Reliability} = \frac{\text{Number of Batch Jobs Completed}}{\text{Total Number of Files in Batch}} = 1.0$ 

when $\frac{\text{Number of Corrupt Files}}{\text{Total Number of Files in Batch}} \leq 0.3$

Where:
- $\text{Batch}$ is a collection of files submitted for processing as a single discrete unit.
- $\text{Batch Job}$ is the complete processing lifecycle for a batch of files, from when they are first input into the program to when they produce text output.
- $\text{Corrupt Files}$ are files with a supported format that contain structural damage, invalid headers, incomplete data, or other integrity issues that prevent the file from being processed.

### Action Plan
- Create a small set of corrupt files (5-10) covering major error scenarios
- Test representative error types (e.g., malformed headers, truncated files, invalid encodings)
- Include basic recovery testing for the most common failure scenarios
- Verify batch processing continues after encountering corrupt files

## 6. Security Effectiveness 

### Target
100% prevention of code execution

### Formula
$\text{Security Effectiveness} = \frac{\text{Number of Prevented Execution Attempts}}{\text{Number of Malicious Execution Attempts}} = 1.0$

Where:
- $\text{Execution Attempt}$ is where processed content contains code, scripts, macros, or executable instructions that could run on the host system if not properly contained.
- $\text{Malicious Executed Attempt}$ is an execution attempt designed with harmful intent. These include but are not limited to shellcode, buffer overflows, and command injection.
- $\text{Prevented Execution Attempt}$ is the successful interception and blocking of potentially executable code.

### Action Plan
- Create a basic security test suite with common exploit patterns
- Include simplified penetration tests focused on common attack vectors
- Implement fundamental sandbox validation
- Focus on file type validation and content sanitization testing

## 7. Text Quality for LLM Training

### Target
90% text preservation

### Formula
$\text{Text Quality Factor (Text)} = \alpha \cdot {BLEU_{text}} + \beta \cdot {ROUGE\text{-}L_{text}} + \gamma \cdot {\text{Structural Preservation}_{text}} \geq 0.9$

$\text{Text Quality Factor (Image)} = \alpha \cdot {BLEU_{image}} + \beta \cdot {ROUGE\text{-}L_{image}} \geq 0.9$

$\text{Text Quality Factor (Audio)} = \alpha \cdot {BLEU_{audio}} + \beta \cdot {ROUGE\text{-}L_{audio}} \geq 0.9$

$\text{Text Quality Factor (Video)} = \alpha \cdot {BLEU_{video}} + \beta \cdot {ROUGE\text{-}L_{video}} \geq 0.9$

$\text{Text Quality Factor (Application)} = \alpha \cdot {BLEU_{application}} + \beta \cdot {ROUGE\text{-}L_{application}} + \gamma \cdot {\text{Structural Preservation}_{application}} \geq 0.9$

Where:
- $\alpha$, $\beta$, and $\gamma$ are weighting parameters. Initially, $\alpha = 0.5$, $\beta = 0.3$, and $\gamma = 0.2$ for text and applications, and $\alpha = 0.6$ and $\beta = 0.4$ for images, audio, and video.
- ${BLEU_{text}}$ is the Bilingual Evaluation Understudy (BLEU) score comparing n-gram matches between extracted and reference text for text documents.
- ${BLEU_{image}}$ is the BLEU score comparing n-gram matches between a text summary of an image and a reference summary of the image.
- ${BLEU_{audio}}$ is the BLEU score comparing n-gram matches between transcribed audio and a reference transcription.
- ${BLEU_{video}}$ is the BLEU score comparing n-gram matches between a text summary of the video and a reference summary of the video.
- ${BLEU_{application}}$ is the BLEU score comparing n-gram matches between text extracted from application files and reference text.
- ${ROUGE\text{-}L_{text}}$ is the Longest Common Subsequence (ROUGE-L) score between the converted text and reference text.
- ${ROUGE\text{-}L_{image}}$ is the ROUGE-L score for a text summary of an image compared to a reference summary of the image.
- ${ROUGE\text{-}L_{audio}}$ is the ROUGE-L score for transcribed audio compared to a reference transcription.
- ${ROUGE\text{-}L_{video}}$ is the ROUGE-L score for a text summary of the video compared to a reference summary of the video.
- ${ROUGE\text{-}L_{application}}$ is the ROUGE-L score for text extracted from application files compared to a reference text.
- ${\text{Structural Preservation}_{text}}$ measure the number of preserved structural elements (e.g., paragraphs, sections, lists, tables) between extracted and reference text documents.
- ${\text{Structural Preservation}_{application}}$ measure the number of preserved structural elements (e.g., paragraphs, sections, lists, tables) between extracted and reference text documents.

### Action Plan
- Prioritize tests for text documents, then expand to audio, image, video, and application files in that order.
- Create a small set (5-10 documents) of manually extracted reference texts for each file type.
- Implement automated metrics for BLEU, ROUGE-L, and structural preservation.
- Compare key sections of documents for content and structural preservation.
- Test preservation of document structure, including paragraphs, sections, and metadata.
- Adjust $\alpha$, $\beta$, and $\gamma$ based on early test results to optimize quality assessment.
- Document findings and iterate on the formula as needed.
