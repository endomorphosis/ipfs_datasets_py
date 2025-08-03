# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_info.py'

Files last updated: 1751408933.7564564

Stub file last updated: 2025-07-07 01:10:14

## _analyze_audio_quality

```python
async def _analyze_audio_quality(input_path: str, sample_duration: Optional[str] = None) -> Dict[str, Any]:
    """
    Analyze audio quality metrics.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _analyze_compression

```python
def _analyze_compression(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze compression efficiency.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _analyze_performance

```python
async def _analyze_performance(input_path: str) -> Dict[str, Any]:
    """
    Analyze encoding/decoding performance.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _analyze_video_quality

```python
async def _analyze_video_quality(input_path: str, sample_duration: Optional[str] = None) -> Dict[str, Any]:
    """
    Analyze video quality metrics.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _generate_analysis_summary

```python
def _generate_analysis_summary(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate analysis summary.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _save_analysis_report

```python
async def _save_analysis_report(analysis: Dict[str, Any], output_path: str) -> None:
    """
    Save analysis report to file.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## ffmpeg_analyze

```python
async def ffmpeg_analyze(input_file: Union[str, Dict[str, Any]], analysis_type: str = "comprehensive", video_analysis: bool = True, audio_analysis: bool = True, quality_metrics: bool = True, performance_metrics: bool = True, sample_duration: Optional[str] = None, output_report: Optional[str] = None) -> Dict[str, Any]:
    """
    Perform comprehensive analysis of media file quality and characteristics.

This tool provides advanced analysis including:
- Video quality metrics (PSNR, SSIM, VMAF)
- Audio quality analysis
- Compression efficiency
- Stream synchronization
- Error detection
- Performance benchmarks

Args:
    input_file: Input media file path or dataset
    analysis_type: Type of analysis ('basic', 'comprehensive', 'quality', 'performance')
    video_analysis: Include video stream analysis
    audio_analysis: Include audio stream analysis
    quality_metrics: Calculate quality metrics
    performance_metrics: Calculate performance metrics
    sample_duration: Duration of sample to analyze (e.g., '00:01:00')
    output_report: Path to save detailed report
    
Returns:
    Dict containing comprehensive analysis results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## ffmpeg_probe

```python
async def ffmpeg_probe(input_file: Union[str, Dict[str, Any]], show_format: bool = True, show_streams: bool = True, show_chapters: bool = False, show_frames: bool = False, frame_count: Optional[int] = None, select_streams: Optional[str] = None, include_metadata: bool = True) -> Dict[str, Any]:
    """
    Probe media file for detailed information using FFprobe.

This tool extracts comprehensive metadata including:
- Container format information
- Video/audio/subtitle stream details
- Codec information and parameters
- Duration, bitrate, and quality metrics
- Chapter information
- Frame-level analysis (optional)

Args:
    input_file: Input media file path or dataset
    show_format: Include format/container information
    show_streams: Include stream information
    show_chapters: Include chapter information
    show_frames: Include frame-level information
    frame_count: Number of frames to analyze (if show_frames=True)
    select_streams: Stream selector (e.g., 'v:0', 'a', 's:0')
    include_metadata: Include metadata tags
    
Returns:
    Dict containing detailed media information
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## main

```python
async def main() -> Dict[str, Any]:
    """
    Main function for MCP tool registration.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
