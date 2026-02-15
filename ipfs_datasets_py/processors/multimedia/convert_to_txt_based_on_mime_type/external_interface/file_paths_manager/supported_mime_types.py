from enum import Enum


class SupportedApplicationTypes(str, Enum):
    """Supported application types"""
    PDF = ".pdf"
    DOCX = ".docx"
    DOC = ".doc"
    XLS = ".xls"
    XLSX = ".xlsx"
    PPT = ".ppt"
    PPTX = ".pptx"
    ZIP = ".zip"
    RAR = ".rar"
    TXT = ".txt"
    RTF = ".rtf"
    ODT = ".odt"
    ODS = ".ods"
    ODP = ".odp"
    CSV = ".csv"
    JSON = ".json"
    XML = ".xml"
    EXE = ".exe"
    DMG = ".dmg"


class SupportedImageTypes(str, Enum):
    """Supported image types"""
    JPEG = ".jpeg"
    JPG = ".jpg"
    PNG = ".png"
    TIFF = ".tiff"
    GIF = ".gif"
    BMP = ".bmp"
    WEBP = ".webp"
    SVG = ".svg"
    ICO = ".ico"
    HEIC = ".heic"
    RAW = ".raw"


class SupportedVideoTypes(str, Enum):
    """Supported video types"""
    MP4 = ".mp4"
    AVI = ".avi"
    MOV = ".mov"
    WMV = ".wmv"
    FLV = ".flv"
    MKV = ".mkv"
    WEBM = ".webm"
    M4V = ".m4v"
    MPG = ".mpg"
    MPEG = ".mpeg"
    _3GP = ".3gp"
    TS = ".ts"
    VOB = ".vob"
    OGV = ".ogv"
    MTS = ".mts"
    M2TS = ".m2ts"


class SupportedAudioTypes(str, Enum):
    """Supported audio types"""
    MP3 = ".mp3"
    WAV = ".wav"
    AAC = ".aac"
    OGG = ".ogg"
    FLAC = ".flac"
    M4A = ".m4a"
    WMA = ".wma"
    AIFF = ".aiff"
    ALAC = ".alac"
    AMR = ".amr"
    AU = ".au"
    MID = ".mid"
    MIDI = ".midi"
    RA = ".ra"
    RM = ".rm"


class SupportedTextTypes(str, Enum):
    """Supported text types"""
    TXT = ".txt"
    RTF = ".rtf"
    HTML = ".html"
    HTM = ".htm"
    XML = ".xml"
    JSON = ".json"
    YAML = ".yaml"
    YML = ".yml"
    CSV = ".csv"
    TSV = ".tsv"
    MD = ".md"
    MARKDOWN = ".markdown"
    INI = ".ini"
    CFG = ".cfg"
    LOG = ".log"
    SQL = ".sql"
    PY = ".py"
    JS = ".js"
    CSS = ".css"
    SH = ".sh"
    BAT = ".bat"


SupportedMimeTypes: set = (
    *SupportedApplicationTypes, 
    *SupportedImageTypes, 
    *SupportedVideoTypes, 
    *SupportedAudioTypes, 
    *SupportedTextTypes
)