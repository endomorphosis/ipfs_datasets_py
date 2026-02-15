# TODO

## Designated Worker: Worker 55

## Description:
Your task is to implement ability processors for the content extractor. These processors are responsible for handling specialized content extraction tasks, such as audio transcription, content summarization (e.g. VLLM descriptions of images), and optical character recognition (OCR). Each processor should be designed to work with the functions located in the `processors/by_dependency/` directory, or utilities in the `utils/` directory. The processors are expected to orchestrate the use of these functions to perform their respective tasks.

Note that some ability processors can use other ability processors as dependencies. For example, the `ocr_processor` can use 


, and the `image_processor` can use the `video_processor` to extract frames from videos.

## TODO

## WIP

## COMPLETE