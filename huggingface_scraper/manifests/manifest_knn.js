import {complete, open_ended_question, multiple_choice_question, parse_templates, generate_template, generate_metadata_template, generate_hwrequirements_template} from '../utils.js'
import prompt_sync from 'prompt-sync'
import prompt_sync_history from 'prompt-sync-history'
import models_generate_knn from '../modeldata/generate_knn.json' assert { type: 'json' };

export class Manifest_knn{

    constructor(){
        this.metadata = {}
        this.hwRequirements = {}
        this.folderData = {}
        this.cache = {}
        this.format = ""
        this.id = ""
        this.source = ""
    }

    main(generate){
        let generation = knn_generate(generate)
        for (var key in generation){
            this[key] = generation[key]
        }
        return this
    }

    calc(){
        return knn_calc()
    }
}

export default function knn_calc(){

    let prompt = prompt_sync(({
        history: prompt_sync_history(),
        autocomplete: complete([]),
        sigint: true
    }))

    let modelName = open_ended_question("Enter a model name: ")

    let locations = ['local', 'huggingface', 'http', 's3']

    let location = multiple_choice_question("Where is the model located?", locations) 

    let source = open_ended_question("enter a source from " + location + ": ")

    let content_types = ['text', 'image', 'audio', 'video']

    let content_type = multiple_choice_question("Select a content type: ", content_types)

    let input_types = ['text', 'image', 'audio', 'video']

    let input_type = multiple_choice_question("Select an input type: ", input_types)

    let text_embedding_models = [
        "text-embedding-ada-002",
        "gte-large",
        "gte-base",
        "bge-base-en-v1.5",
        "bge-large-en-v1.5",
        "instructor",
        "instructor-large",
        "instructor-xl"
    ]

    let image_embedding_models = [
        "clip-vit-base",
        "clip-vit-large",
        "openclip-vit-base",    
        "visualbert",
        "visualbert-vqa-coco-pre",
        "blip2",
        "instructblip",
        "CLIP-ViT-L-14-laion2B-s32B-b82K",
        "CLIP-ViT-bigG-14-laion2B-39B-b160k",
        "CLIP-ViT-H-14-laion2B-s32B-b79K",
        "CLIP-ViT-L-14-DataComp.XL-s13B-b90K"
    ]

    let audio_embedding_models = [
        "clap-htsat-fused",
        "larger_clap_music",
        "larger_clap_music_and_speech",
        "clap-htsat-fused",
        "larger_clap_general"
    ]
    let text_embedding_model
    let image_embedding_model
    let audio_embedding_model
    let video_embedding_model

    if (content_type == 'text'){
        let primary_text_model = "text-embedding-ada-002"
        text_embedding_model = multiple_choice_question("Select a text embedding model: ", text_embedding_models)
    }

    if (content_type == 'audio'){
        audio_embedding_model = multiple_choice_question("Select an audio embedding model: ", audio_embedding_models)
    }

    if (content_type == 'image'){
        image_embedding_model = multiple_choice_question("Select an image embedding model: ", image_embedding_models)
    }

    if (content_type == 'video'){
        throw "video not implemented"
    }

    console.log("how many samples are there?")

    let samples = open_ended_question("Enter a number: ")

    console.log("how many dimensions are there?")

    let dimensions = open_ended_question("Enter a number: ")

    console.log("Quantization of the embeddings?")
    let quantization_options = ['fp16', 'fp32']

    let quantization = multiple_choice_question("Select a quantization: ", quantization_options)
    
    results.quantization = quantization
    results.samples = samples
    results.dimensions = dimensions
    results.content_type = content_type
    results.input_type = input_type
    results.location = location
    results.source = source
    results.modelName = modelName
    results.text_embedding_model = text_embedding_model
    results.image_embedding_model = image_embedding_model
    results.audio_embedding_model = audio_embedding_model
    results.video_embedding_model = video_embedding_model
    results.units = "samples"
    
    return results
}

export function knn_generate_hwrequirements(){
    let results = generate_hwrequirements_template(generate)
    let bytes_per_dimensions
    if (generate.quantization == 'fp16'){
        bytes_per_dimensions = 2
    }
    if (generate.quantization == 'fp32'){
        bytes_per_dimensions = 4
    }

    let filename_length = 2048
    let filename_id = 64
    let vector_id = 64
    let metadata_size = 2048
    let dimension_size = generate.dimensions * bytes_per_dimensions
    let size_per_sample = filename_length + filename_id + vector_id + metadata_size + dimension_size
    let total_size = size_per_sample * generate.samples
    let minFlops = {
        "fp8": 0,
        "fp16": 10,
        "fp32": 0,
    }
    
    results.samples_per_second = 0
    results.gpuCount = [1]
    results.cpu_count = [2,4]
    results.flopsPerUnit = 0
    results.minFlops = minFlops
    results.minSpeed = results.minFlops.fp16 / 35.58 
    results.gpuMemory = total_size
    results.disk_usage = total_size
    results.cpu_memory = total_size
    results.memory = total_size

    return results
}

export function knn_generate_metadata(){
    let results = generate_metadata_template(generate)
    results.content_type = generate.content_type
    results.input_type = generate.input_type
    results.text_embedding_model = generate.text_embedding_model
    results.image_embedding_model = generate.image_embedding_model
    results.audio_embedding_model = generate.audio_embedding_model
    results.video_embedding_model = generate.video_embedding_model
    results.samples = generate.samples
    results.dimensions = generate.dimensions
    results.quantization = generate.quantization
    results.templates = generate.templates
    return results
}

export function knn_generate(generate){
    let results = generate_template(generate)
    results.metadata = knn_generate_metadata(generate)
    results.hwRequirements = knn_generate_hwrequirements(generate)
    results.skill = "knn"
    results.id = "knn-" + generate.modelName + "-" + generate.samples + "-" + generate.dimensions + "-" + generate.quantization
    return results
}

export function knn_add(generation){
    if (generation.modelName != undefined){
        models_generate_knn[generation.modelName] = generation
        fs.writeFileSync(path.resolve('../modeldata/generate_knn.json'), JSON.stringify(models_generate_knn, null, 2))       
        return Object.keys(models_generate_knn)
    }
    else{
        throw "model name is undefined"
    }      
}