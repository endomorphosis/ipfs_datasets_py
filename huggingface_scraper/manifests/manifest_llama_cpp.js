import {complete, open_ended_question, multiple_choice_question, multiple_select_question, parse_templates, generate_template, generate_metadata_template, generate_hwrequirements_template} from '../utils.js'
import prompt_sync from 'prompt-sync'
import prompt_sync_history from 'prompt-sync-history'
import models_llama_cpp_generate from '../modeldata/generate_llama_cpp.json' assert { type: 'json' };
import fs from 'fs'
import path, { parse } from 'path'

export class Manifest_llama_cpp{
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
        let generation = llama_cpp_generate(generate)
        for (var key in generation){
            this[key] = generation[key]
        }
        return this
    }

    calc(){
        return llama_cpp_calc()
    }
}

export default function llama_cpp_calc(){

    let prompt = prompt_sync(({
        history: prompt_sync_history(),
        autocomplete: complete([]),
        sigint: true
    }))

    let modelName = open_ended_question("Enter a model name: ")

    let locations = ['local', 'huggingface', 'http', 's3']

    let location = multiple_choice_question("Where is the model located?", locations) 

    let source = open_ended_question("Enter a source from " + location + ": ")

    let formats = ["gguf", "ggml", "llama_fp16", "llama_fp32"]

    let format = multiple_choice_question("What is the model format?", formats)

    let quantization
    if (format == 'llama_fp16'){
        quantization = 'fp16'
    }

    if (format == 'llama_fp32'){
        quantization = 'fp32'
    }

    if (format == 'gguf' || format == 'ggml'){
        let quantizations = ['Q8_0', 'Q6_K', 'Q5_K_M','Q5_K_S', 'Q5_0', 'Q4_K_M' , 'Q4_K_S' ,'Q4_0', 'Q3_K_L' ,'Q3_K_S', 'Q3_K_M', 'Q2_K', ]
       
        quantization = multiple_choice_question("what is the model quantization?", quantizations)
    }

    console.log("quantization is: " + quantization)

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

    let results = llama_cpp_generate(generate)

    if (results == {}){
        console.log("Error generating metadata")
        return false
    }
    else{
        console.log(results)
        return results
    }
}


export function llama_cpp_generate_hw_requirements(generate){
    let results = generate_hwrequirements_template(generate)
    results["gpuCount"] = [0]
    results["minSpeed"] = 0
    results["gpuMemory"] = 0
    results["tokensPerSecond"] = 0
    results["flopsPerUnit"] = 0
    results["diskUsage"] = 0
    let model_padding = 1.1
    let flopsPerUnit = 0
    let tokensPerSecond = 0
    let gpuCount
    let cpuCount
    let minFlops
    let quantization = generate.quantization

    if(generate.parameters > 0){
        let bits = 0
        // update this from the ggml standard //
        // fix this //
        if (quantization == 'fp16'){
            bits = 16
        }
        if (quantization == 'fp32'){
            bits = 32
        }
        if (quantization == 'Q8_0'){
            bits = 8
        }
        if (quantization == 'Q6_K'){
            bits = 6.5625
        }
        if (quantization == 'Q5_K_S'){
            bits = 5.5
        }
        if (quantization == 'Q5_K_M'){
            bits = 5.5
        }
        if (quantization == 'Q5_0'){
            bits = 5.5
        }
        if (quantization == 'Q4_K_M'){
            bits = 4.5
        }
        if (quantization == 'Q4_K_S'){
            bits = 4.5
        }
        if (quantization == 'Q4_0'){
            bits = 4
        }
        if (quantization == 'Q3_K_S'){
            bits = 3.4375
        }
        if (quantization == 'Q3_K_L'){
            bits = 3.4375
        }
        if (quantization == 'Q3_K_M'){
            bits = 3.4375
        }
        if (quantization == 'Q2_K'){
            bits = 2.5625
        }

        results["gpuMemory"] = generate.parameters * bits / 8 * model_padding
        results["diskUsage"] = results["gpuMemory"] * model_padding

        if (quantization == 'Q2_K'){
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
        }
        else if (quantization == 'Q4_0' || quantization == 'Q4_K_S' || quantization == 'Q4_K_M'){
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
        }
        else if (quantization == 'Q3_K_M' || quantization == 'Q3_K_S' || quantization == 'Q3_K_L'){
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
        } else if (quantization == 'Q5_0' || quantization == 'Q5_K_S' || quantization == 'Q5_K_M'){
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
        }else if (quantization == 'Q6_K'){
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
        }else if (quantization == 'Q8_0'){
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
        }
        else{
            throw ("Failed to Generate, Invalid quantization, no stats for " + quantization + " quantization")
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

    results["minFlops"] = minFlops
    results["flopsPerUnit"] = flopsPerUnit
    results["tokensPerSecond"] = tokensPerSecond  
    results["gpuCount"] = gpuCount
    results["cpuCount"] = cpuCount
    results["minSpeed"] = minFlops["fp16"] / 35.58 

    return results
}

export function llama_cpp_generate_metadata(generate){
    let results = generate_metadata_template(generate)
    results.contextSize = generate.contextSize
    results.parameters = generate.parameters
    results.quantization = generate.quantization
    results.ropeScale = generate.ropeScale
    results.templates = generate.templates
    results.units = "tokens"
    results.skill = "llama_cpp"
    return results
}

export function llama_cpp_generate(generate){
    let results = generate_template(generate)
    //results.id = generate.modelName + '-' + (parseInt(generate.parameters) / 1000000000).toString() + 'b-' + generate.quantization
    results.id = generate.modelName + '-' + generate.quantization
    results.metadata = llama_cpp_generate_metadata(generate)
    results.hwRequirements = llama_cpp_generate_hw_requirements(generate)
    results.skill = "llama_cpp"
    return results
}

export function llama_cpp_add(generation){
    if (generation.modelName != undefined){
        models_llama_cpp_generate[generation.modelName] = generation
        fs.writeFileSync(path.resolve('../modeldata/generate_llama_cpp.json'), JSON.stringify(models_llama_cpp_generate, null, 2))       
        return Object.keys(models_llama_cpp_generate)
    }
    else{
        throw "model name is undefined"
    }      
}