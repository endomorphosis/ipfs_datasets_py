import {complete, open_ended_question, multiple_choice_question, parse_templates, generate_template, generate_metadata_template, generate_hwrequirements_template} from '../utils.js'
import prompt_sync from 'prompt-sync'
import prompt_sync_history from 'prompt-sync-history'
import models_generate_hf_transformers from '../modeldata/generate_hf_transformers.json' assert { type: 'json' };
import fs from 'fs'
import path, { parse } from 'path'

export class Manifest_hf_transformers{
    constructor(){
        this.metadata = {}
        this.hwRequirements = {}
        this.folderData = {}
        this.cache = {}
        this.format = ""
        this.id = ""
        this.source = ""
        this.skill = ""
    }

    main(generate){
        let generation = hf_transformers_generate(generate)
        for (var key in generation){
            this[key] = generation[key]
        }
        return this
    }

    calc(){
        return hf_transformers_calc()
    }
}


export default function hf_transformers_calc(){

    let prompt = prompt_sync(({
        history: prompt_sync_history(),
        autocomplete: complete([]),
        sigint: true
    }))

    let modelName = open_ended_question("Enter a model name: ")

    let locations = ['local', 'huggingface', 'http', 's3']

    let location = multiple_choice_question("Where is the model located?", locations) 

    let source = open_ended_question("enter a source from " + location + ": ")

    let generate = {}
    generate.modelName = modelName
    generate.location = location
    generate.source = source

    let results = hf_transformers_generate(generate)
    return results
}

export function hf_transformers_generate(generate){
    let results = generate_template(generate)
    results.hwRequirements = hf_transformers_generate_hwrequirements(generate)
    results.metadata = hf_transformers_generate_metadata(generate)
    results.skill = "hf_transformers"
    results.id = generate.modelName 
    return results
}

export function hf_transformers_generate_metadata(generate){
    let results = generate_metadata_template(generate)

    return results
}

export function hf_transformers_generate_hwrequirements(generate){
    let results = generate_hwrequirements_template(generate)
    let flopsPerUnit
    let tokensPerSecond
    let gpuCount
    let cpuCount
    let minFlops
    let total_size 
    let model_padding = 1.1

    if (generate.parameters >= 180 * 1000000000){
        throw "Model is too large"
    }
    if(generate.parameters <= 180 * 1000000000 && generate.parameters >= 70 * 1000000000){
        flopsPerUnit = 35.58 / 12
        tokensPerSecond = 12
        gpuCount = [2,4]
        cpuCount = [2,4]
        minFlops =  {
            "fp8": 0,
            "fp16": 75,
            "fp32": 0,
        }
    }
    if(generate.parameters <= 70 * 1000000000 && generate.parameters >= 65 * 1000000000){
        flopsPerUnit = 35.58 / 12
        tokensPerSecond = 12
        gpuCount = [1,2]
        cpuCount = [2,4]
        minFlops =	 {
            "fp8": 0,
            "fp16": 75,
            "fp32": 0,
        }
    }
    if(generate.parameters <= 65 * 1000000000 && generate.parameters >= 40 * 1000000000){
        flopsPerUnit = 35.58 / 15
        tokensPerSecond = 15
        gpuCount = [1,2]
        cpuCount = [2,4]
        minFlops =	 {
            "fp8": 0,
            "fp16": 75,
            "fp32": 0,
        }
    }
    if(generate.parameters <= 40 * 1000000000 && generate.parameters >= 33 * 1000000000){
        flopsPerUnit = 35.58 / 15
        tokensPerSecond = 15
        gpuCount = [1,2]
        cpuCount = [2,4]
        minFlops =	 {
            "fp8": 0,
            "fp16": 50,
            "fp32": 0,
        }
    }
    if(generate.parameters <= 33 * 1000000000 && generate.parameters >= 30 * 1000000000){
        flopsPerUnit = 35.58 / 29
        tokensPerSecond = 29
        gpuCount = [1,2]
        cpuCount = [2,4]
        minFlops = {
            "fp8": 0,
            "fp16": 35,
            "fp32": 0,
        }		
    }
    if(generate.parameters <= 30 * 1000000000 && generate.parameters >= 13 * 1000000000){
        flopsPerUnit = 35.58 / 60
        tokensPerSecond = 60
        gpuCount = [1,2]
        cpuCount = [2,4]
        minFlops = {
            "fp8": 0,
            "fp16": 20,
            "fp32": 0,
        }			
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
    results.minFlops = minFlops
    results.minSpeed = results.minFlops.fp16 / 35.58 
    results["cpuMemory"] = generate.parameters * 2 * model_padding
    results["gpuMemory"] = generate.parameters * 2 * model_padding
    results["diskUsage"] = results["gpuMemory"] * model_padding

    return results
}

export function hf_transformers_add(generation){
    if (generation.modelName != undefined){
        models_generate_hf_transformers[generation.modelName] = generation
        fs.writeFileSync(path.resolve('../modeldata/generate_hf_transformers.json'), JSON.stringify(models_generate_hf_transformers, null, 2))       
        return Object.keys(models_generate_hf_transformers)
    }
    else{
        throw "model name is undefined"
    }      
}