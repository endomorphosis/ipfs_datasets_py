import {complete, open_ended_question, multiple_choice_question, parse_templates, generate_template, generate_metadata_template, generate_hwrequirements_template} from '../utils.js'
import prompt_sync from 'prompt-sync'
import prompt_sync_history from 'prompt-sync-history'
import models_generate_hf_lm from '../modeldata/generate_hf_lm.json' assert { type: 'json' };
import fs from 'fs'
import path, { parse } from 'path'

export class Manifest_hf_lm{
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
        let generation = hf_lm_generate(generate)
        for (var key in generation){
            this[key] = generation[key]
        }
        return this
    }

    calc(){
        return hf_lm_calc()
    }
}

export default function hf_lm_calc(){

    let prompt = prompt_sync(({
        history: prompt_sync_history(),
        autocomplete: complete([]),
        sigint: true
    }))

    let modelName = open_ended_question("Enter a model name: ")

    let locations = ['local', 'huggingface', 'http', 's3']

    let location = multiple_choice_question("Where is the model located?", locations) 

    let source = open_ended_question("enter a source from " + location + ": ")

    let parameters_options = [3.5,7,13,30,33,40,65,70,180]

    let parameters = multiple_choice_question("how many billions of parameters are there?", parameters_options)

    parameters = parseInt(parameters) * 1000000000

    let contextSizes = [2048, 4096, 8192, 16384]
    
    let contextSize = multiple_choice_question("what is the length of the context size?", contextSizes)

    let ropeScale = 0
    if (contextSize => 2048){
        let ropeScales = ['1x', '2x', '4x', '8x']

        ropeScale = multiple_choice_question("what is the rope scale?", ropeScales)
    }

    let prompt_templates = ['llama-2', 'vicuna', 'alpaca', 'chatlm', "mistral-lite"]
    let chat_templates = ["llama-2", "vicuna", "alpaca", "chatlm", "mistral-lite"]
    
    let default_template = multiple_choice_question("Select default prompt template: ", prompt_templates)
    
    let tmp_templates = prompt_templates
    let templates = []
    templates.push(default_template)
    tmp_templates.splice(tmp_templates.indexOf(default_template), 1)

    let additional_templates = multiple_select_question("Select additional prompt templates: ", tmp_templates)
    for (var this_template in additional_templates){
        templates.push(this_template)
    }
    
    console.log("chosen templates")
    console.log(templates)

    let generate = {}
    generate.parameters = parameters
    generate.contextSize = contextSize
    generate.ropeScale = ropeScale
    generate.quantization = quantization
    generate.format = format
    generate.location = location
    generate.source = source
    generate.templates = templates
    generate.modelName = modelName
    generate.templates = templates

    let results = hf_t5_generate(generate)
    return results
}

export function hf_lm_generate(generate){
    let results = generate_template(generate)
    results.hwRequirements = hf_lm_generate_hwrequirements(generate)
    results.metadata = hf_lm_generate_metadata(generate)
    results.skill = "hf_lm"
    results.id = generate.modelName 
    return results
}

export function hf_lm_generate_metadata(generate){
    let results = generate_metadata_template(generate)

    return results
}

export function hf_lm_generate_hwrequirements(generate){
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

export function hf_lm_add(generation){
    if (generation.modelName != undefined){
        models_generate_hf_lm[generation.modelName] = generation
        fs.writeFileSync(path.resolve('../modeldata/generate_hf_lm.json'), JSON.stringify(models_generate_hf_lm, null, 2))       
        return Object.keys(models_generate_hf_lm)
    }
    else{
        throw "model name is undefined"
    }      
}