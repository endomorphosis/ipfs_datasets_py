import {complete, open_ended_question, multiple_choice_question, parse_templates, generate_template, generate_metadata_template, generate_hwrequirements_template} from '../utils.js'
import prompt_sync from 'prompt-sync'
import prompt_sync_history from 'prompt-sync-history'
import models_generate_hf_embed from '../modeldata/generate_hf_embed.json' assert { type: 'json' };
import fs from 'fs'
import path, { parse } from 'path'

export class Manifest_hf_embed{
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
        let generation = hf_embed_generate(generate)
        for (var key in generation){
            this[key] = generation[key]
        }
        return this
    }

    calc(){
        return hf_embed_calc()
    }
}




export default function hf_embed_calc(){
    
    let model_name = open_ended_question("Enter a model name: ")

    let locations = ['local', 'huggingface', 'http', 's3']

    let location = multiple_choice_question("Where is the model located?", locations) 

    let source = open_ended_question("enter a source from " + location + ": ")

    let formats = ["fp16", "fp32"]

    let format = multiple_choice_question("Select a format: ", formats)

    console.log("format is: " + format)

    let quantization
    if (format == 'fp16'){
        quantization = 'fp16'
    }

    if (format == 'fp32'){
        quantization = 'fp32'
    }

    let parameters = open_ended_question("Enter the number of parameters: ")
    
    let contextSize_options = [384,512,1024,2048,4096,8192]

    let contextSize = multiple_choice_question("Enter a the context size length: ", contextSize_options)

    let dimensions_options = [128,256,512,1024,2048,4096]
    
    let dimensions = multiple_choice_question("how many dimensions are there?", dimensions_options)

    let model_size_options = []

    let embedding_template_options = ['embed', "instruct-embed"]

    let embedding_template = multiple_choice_question("Select default prompt template: ", embedding_template_options)

    let content_type_options = ['text', 'image', 'audio', 'video']

    let content_type = multiple_choice_question("Enter the content type: ", content_type_options)

    let generate = {}
    generate.parameters = parameters
    generate.contextSize = contextSize
    generate.quantization = quantization
    generate.dimensions = dimensions
    generate.embedding_template = embedding_template
    generate.content_type = content_type
    generate.format = format
    generate.location = location
    generate.source = source
    generate.modelName = model_name
    let results = hf_embed_generate(generate)
    return results
}

export function hf_embed_generate_metadata(generate){
    let results = generate_metadata_template(generate)
    results.metadata.parameters = generate.parameters
    results.metadata.dimensions = generate.dimensions
    results.metadata.contentType = generate.content_type
    results.metadata.contextSize = generate.contextSize
    results.metadata.embeddingTemplate = generate.embedding_template
    results.metadata.dimensions = generate.dimensions
    results.metadata.quantization = generate.quantization
    results.metadata.modelName = generate.modelName
    results.metadata.skill = "hf_embed"
    results.units = "vectors"
    return results
}

export function hf_embed_generate_hwrequirements(generate){
    console.log("generate")
    console.log(generate)
    let results = generate_hwrequirements_template(generate)
    let flopsPerUnit
    let tokensPerSecond
    let gpuCount
    let cpuCount
    let minFlops
    let total_size 
    let model_padding = 1.1

    if (generate.parameters > 13 * 1000000000){
        throw "Model is too large"
    }
    
    if(generate.parameters <= 13 * 1000000000 && generate.parameters >= 7 * 1000000000){
        flopsPerUnit = 35.58 / 85
        tokensPerSecond = 85
        gpuCount = [1]
        cpuCount = [2,4]
        minFlops = {
            "fp8": 0,
            "fp16": 10,
            "fp32": 0,
        }				
    }

    if(generate.parameters <= 7 * 1000000000 && generate.parameters >= 3.5 * 1000000000){
        flopsPerUnit = 35.58 / 100
        tokensPerSecond = 100
        gpuCount = [1]
        cpuCount = [2,4]
        minFlops = {
            "fp8": 0,
            "fp16": 10,
            "fp32": 0,
        }
    }
    if(generate.parameters <= 3.5 * 1000000000 && generate.parameters >= 1 * 1000000000){
        flopsPerUnit = 35.58 / 100
        tokensPerSecond = 100
        gpuCount = [1]
        cpuCount = [2,4]
        minFlops = {
            "fp8": 0,
            "fp16": 10,
            "fp32": 0,
        }
    }
    
    if(generate.parameters <= 1 * 1000000000){
        flopsPerUnit = 35.58 / 100
        tokensPerSecond = 100
        gpuCount = [1]
        cpuCount = [2,4]
        minFlops = {
            "fp8": 0,
            "fp16": 10,
            "fp32": 0,
        }
    }

    if(parseFloat(generate.experts) > 0){
        results["diskUsage"] = results["diskUsage"] * generate.experts
        results["gpuMemory"] = results["gpuMemory"] * generate.experts
        results["cpuMemory"] = results["gpuMemory"] * generate.experts
    }
    else{
        results["diskUsage"] = results["diskUsage"]
        results["gpuMemory"] = results["gpuMemory"]
        results["cpuMemory"] = results["gpuMemory"]
    }
    results.samples_per_second = 0
    results.gpuCount = gpuCount
    results.cpuCount = cpuCount
    results.flopsPerUnit = flopsPerUnit
    if (Object.keys(minFlops).length != 0){
        results.minFlops = minFlops
    } 
    else{
        throw "minFlops is not defined"
    }
    if (generate.format == "fp16"){
        results.minSpeed = results.minFlops["fp16"] / 35.58
    }
    else{
        results.minSpeed = results.minFlops["fp32"] / 35.58
    }
    results["cpuMemory"] = generate.parameters * 2 * model_padding
    results["gpuMemory"] = generate.parameters * 2 * model_padding
    results["diskUsage"] = results["gpuMemory"] * model_padding
    return results
}

export function hf_embed_generate(generate){
    let results = generate_template(generate)
    results.hwRequirements  = hf_embed_generate_hwrequirements(generate)
    results.metadata = hf_embed_generate_metadata(generate)
    results.id = generate.modelName 
    results.skill = "hf_embed"
    return results
}

export function hf_embed_add(generation){
    if (generation.modelName != undefined){
        models_generate_hf_embed[generation.modelName] = generation
        fs.writeFileSync(path.resolve('../modeldata/generate_hf_embed.json'), JSON.stringify(models_generate_hf_embed, null, 2))       
        return Object.keys(models_generate_hf_embed)
    }
    else{
        throw "model name is undefined"
    }      
}