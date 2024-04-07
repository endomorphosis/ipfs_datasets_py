import fs from 'fs'
import path, { parse } from 'path'
import prompt_sync from 'prompt-sync'
import prompt_sync_history from 'prompt-sync-history'
import hf_embed_calc from './manifests/manifest_hf_embed.js'
import hf_embed_add from './manifests/manifest_hf_embed.js'
import llama_cpp_calc from './manifests/manifest_llama_cpp.js'
import llama_cpp_add from './manifests/manifest_llama_cpp.js'
import hf_lm_calc from './manifests/manifest_hf_lm.js'
import hf_lm_add from './manifests/manifest_hf_lm.js'
import hf_t5_calc from './manifests/manifest_hf_t5.js'
import hf_t5_add from './manifests/manifest_hf_t5.js'
import knn_calc from './manifests/manifest_knn.js'
import knn_add from './manifests/manifest_knn.js'
import api_calc from './manifests/manifest_api.js'
import api_add from './manifests/manifest_api.js'
import hf_faster_whisper_calc from './manifests/manifest_hf_faster_whisper.js'
import hf_faster_whisper_add from './manifests/manifest_hf_faster_whisper.js'
import hf_transformers_calc from './manifests/manifest_hf_transformers.js'
import hf_transformers_add from './manifests/manifest_hf_transformers.js'
import diffusion_calc from './manifests/manifest_diffusion.js'
import {complete, parse_templates, generate_test} from './utils.js'

export class Generate_Manifest{
    constructor(){
        this.metadata = {}
        this.hwRequirements = {}
    }


    generate_from_prompt(generate){
        let generation = this.generate(generate)
        let test_generation = false
        if (test_generation){
            let add_generation = this.add_generator_to_model_data(this, generation)
        }
        return generation
    }

    main(generate){
        let generation = this.generate(generate)
        let test_generation = false
        if (test_generation){
            let add_generation = this.add_generator_to_model_data(this, generation)
        }
        return generation
    }

    add_generator_to_model_data(generation){
        if (generation.skill == undefined){
            throw("skill is undefined")
        }
        else if (generation.skill == 'hf_transformers'){
            results = hf_transformers_add(this)
        }
        else if (generation.skill == 'hf_embed'){
            results = hf_embed_add(this)
        }
        else if (generation.skill == 'llama_cpp'){
            results = llama_cpp_add(this)
        }
        else if (generation.skill == 'diffusion'){
            results = diffusion_add(this)
        }
        else if (generation.skill == 'knn'){
            results = knn_add(this)
        }
        else if (generation.skill == 'api'){
            results = api_add(this)
        }
        else if (generation.skill == 'custom'){
            results = custom_add(this)
        }
        else if (generation.skill == 'hf_faster_whisper'){
            results = hf_faster_whisper_add(this)
        }
        else if (generation.skill == 'hf_lm'){
            results = hf_lm_add(this)
        }
        else if (generation.skill == 'hf_t5'){
            results = hf_t5_add(this)
        }
        else{
            throw("skill is not defined")
        }
        

        return results
    }

    generate(generate){
        let metadata = this.metadata
        let hwRequirements = this.hwRequirements
        let results
        let model_types = ['hf_transformers', 'hf_embed', 'llama_cpp', 'diffusion', 'knn', 'api', 'whisper', 'hf_lm', 'hf_t5']
        // prompt the user for input
        console.log("1. hf_transformers")
        console.log("2. hf_embed")
        console.log("3. llama_cpp")
        console.log("4. diffusion")
        console.log("5. knn")
        console.log("6. api")
        console.log("7. whisper")
        console.log("8. hf_lm")
        console.log("9. hf_t5")
        // request console input
        let prompt = prompt_sync(({
            history: prompt_sync_history(),
            autocomplete: complete(model_types),
            sigint: true
        }))
    
        let model_type = prompt("Select a model type: ")
        // check if the input is valid
        console.log("confirm model type: " + model_type)
        if (!model_types.includes(model_type)){
            if (parseInt(model_type) > 0 && parseInt(model_type) < 8){
                model_type = model_types[parseInt(model_type) - 1]
            }
            else{
                console.log("Invalid model type")
                return
            }
        }
    
        this.skill = model_type
    
        if (model_type == 'hf_transformers'){
            results = hf_transformers_calc(this)
        }

        if (model_type == 'hf_faster_whisper'){
            results = hf_faster_whisper_calc(this)
        }

        if (model_type == 'hf_lm'){
            results = hf_lm_calc(this)
        }

        if (model_type == "hf_t5"){
            results = hf_t5_calc(this)
        }
    
        if (model_type == 'hf_embed'){
            results = hf_embed_calc(this)
        }
    
        if (model_type == 'llama_cpp'){
            results = llama_cpp_calc(this)
        }
    
        if (model_type == 'diffusion'){
            results = diffusion_calc(this)
        }
    
        if (model_type == 'knn'){
            results = knn_calc(this)
        }
    
        if (model_type == 'api'){
            results = api_calc(this)
        }
    
        if (model_type == 'custom'){
            results = custom_calc(this)
        }

        try{
           let test = generate_test(results)
        }
        catch(err){
            console.log(err)
//            throw("Error in testing the manifest " +  model_type)
        }
        finally{
            return results
        }
    
    }
    
    custom_calc(){
        throw("custom is not yet supported")
    }

}
