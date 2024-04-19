
import fs from 'fs/promises';
import path from 'path';
import generate_hf_transformers from './modeldata/generate_hf_transformers.json' assert { type: 'json' };
import generate_llama_cpp from './modeldata/generate_llama_cpp.json' assert { type: 'json' };
import generate_hf_embed from './modeldata/generate_hf_embed.json' assert { type: 'json' };
import generate_hf_faster_whisper from './modeldata/generate_hf_faster_whisper.json' assert { type: 'json' };
import generate_hf_lm from './modeldata/generate_hf_lm.json' assert { type: 'json' };
import generate_hf_t5 from './modeldata/generate_hf_t5.json' assert { type: 'json' };
import generate_hf_diffusion from './modeldata/generate_diffusion.json' assert { type: 'json' };
import generate_api from './modeldata/generate_api.json' assert { type: 'json' };
import generate_knn from './modeldata/generate_knn.json' assert { type: 'json' };
import generate_dataset from './modeldata/generate_dataset.json' assert { type: 'json' };
import { setFlagsFromString } from 'v8';

export function template_llama_cpp(local_model_path, collection_path){
    let results = []
    let generate
    let models = Object.keys(generate_llama_cpp)
    let local = local_model_path
    let quantizations = ['Q8_0', 'Q6_K', 'Q5_K_M','Q5_K_S', 'Q5_0', 'Q4_K_M' , 'Q4_K_S' ,'Q4_0', 'Q3_K_L' ,'Q3_K_S', 'Q3_K_M', 'Q2_K', ]
    let quantiizations = quantizations.reverse()
    for (var model in models){
        let this_model = models[model]
        for(var quantization in quantizations){
            let this_quanitization = quantizations[quantization]
            generate = {}
            generate.modelName = this_model
            generate.skill = "llama_cpp"
            generate.quantization = this_quanitization
            generate.format = generate_llama_cpp[this_model].format
            generate.id = this_model + "-" + generate.quantization
            generate.parameters = generate_llama_cpp[this_model].parameters
            generate.source = generate_llama_cpp[this_model].source
            generate.ropeScale = generate_llama_cpp[this_model].ropeScale
            generate.contextSize = generate_llama_cpp[this_model].contextSize
            generate.units = "tokens"
            generate.destPath = local + this_model + "-" + generate.quantization
            results.push(generate)
        }
    }
    return results
}

export function template_hf_transformers(local_model_path, collection_path){
    let results = []
    let generate
    let models = Object.keys(generate_hf_transformers)
    let local = local_model_path
    for (var model in models){
        let this_model = models[model]
        generate = {}
        generate.modelName = this_model
        generate.skill = "hf_t5"
        generate.format = generate_hf_transformers[this_model].format
        generate.id = this_model 
        generate.parameters = generate_hf_transformers[this_model].parameters
        generate.source = generate_hf_transformers[this_model].source
        generate.contextSize = generate_hf_transformers[this_model].contextSize
        generate.location = "huggingface"
        generate.units = "tokens"
        //generate.destPath = local
        generate.destPath = local + "/" + this_model 
        results.push(generate)
    }
    return results
}

export function template_hf_faster_whisper(local_model_path, collection_path){
    let results = []
    let generate
    let models = Object.keys(generate_hf_faster_whisper)
    let local = local_model_path
    for (var model in models){
        let this_model = models[model]
        generate = {}
        generate.modelName = this_model
        generate.skill = "hf_faster_whisper"
        generate.format = generate_hf_faster_whisper[this_model].format
        generate.id = this_model 
        generate.parameters = generate_hf_faster_whisper[this_model].parameters
        generate.source = generate_hf_faster_whisper[this_model].source
        generate.contextSize = generate_hf_faster_whisper[this_model].contextSize
        generate.location = "huggingface"
        generate.units = "seconds"
        //generate.destPath = local
        generate.destPath = local + "/" + this_model 
        results.push(generate)
    }
    return results
}

export function template_hf_embed(local_model_path, collection_path){
    let results = []
    let generate
    let models = Object.keys(generate_hf_embed)
    let local = local_model_path
    for (var model in models){
        let this_model = models[model]
        generate = {}
        generate.modelName = this_model
        generate.skill = "hf_embed"
        generate.format = generate_hf_embed[this_model].format
        generate.id = this_model 
        generate.parameters = generate_hf_embed[this_model].parameters
        generate.source = generate_hf_embed[this_model].source
        generate.contextSize = generate_hf_embed[this_model].contextSize
        generate.dimensions = generate_hf_embed[this_model].dimensions
        generate.content_type = generate_hf_embed[this_model].content_type
        generate.location = "huggingface"
        generate.units = "vectors"
        //generate.destPath = local
        generate.destPath = local + "/" + this_model 
        results.push(generate)
    }
    return results
}

export function template_hf_lm(local_model_path, collection_path){
    let results = []
    let generate
    let models = Object.keys(generate_hf_lm)
    let local = local_model_path
    for (var model in models){
        let this_model = models[model]
        generate = {}
        generate.modelName = this_model
        generate.skill = "hf_lm"
        generate.format = generate_hf_lm[this_model].format
        generate.id = this_model 
        generate.parameters = generate_hf_lm[this_model].parameters
        generate.source = generate_hf_lm[this_model].source
        generate.contextSize = generate_hf_lm[this_model].contextSize
        generate.location = "huggingface"
        generate.units = "tokens"
        generate.destPath = local + "/" + this_model 
        results.push(generate)
    }
    return results
}

export function template_hf_t5(local_model_path, collection_path){
    let results = []
    let generate
    let models = Object.keys(generate_hf_t5)
    let local = local_model_path
    for (var model in models){
        let this_model = models[model]
        generate = {}
        generate.modelName = this_model
        generate.skill = "hf_t5"
        generate.format = generate_hf_t5[this_model].format
        generate.id = this_model 
        generate.parameters = generate_hf_t5[this_model].parameters
        generate.source = generate_hf_t5[this_model].source
        generate.contextSize = generate_hf_t5[this_model].contextSize
        generate.location = "huggingface"
        generate.units = "tokens"
        generate.destPath = local + "/" + this_model 
        results.push(generate)
    }
    return results
}

export function template_hf_diffusion(local_model_path, collection_path){
    let results = []
    let generate
    let models = Object.keys(generate_hf_diffusion)
    let local = local_model_path
    for (var model in models){
        let this_model = models[model]
        generate = {}
        generate.modelName = this_model
        generate.skill = "hf_diffusion"
        generate.format = generate_hf_diffusion[this_model].format
        generate.id = this_model 
        generate.parameters = generate_hf_diffusion[this_model].parameters
        generate.source = generate_hf_diffusion[this_model].source
        generate.contextSize = generate_hf_diffusion[this_model].contextSize
        generate.location = "huggingface"
        generate.units = "tokens"
        generate.destPath = local + "/" + this_model 
        results.push(generate)
    }
    return results
}

export function template_knn(local_model_path, collection_path){
    let results = []
    let generate
    let models = Object.keys(generate_knn)
    let local = local_model_path
    for (var model in models){
        let this_model = models[model]
        generate = {}
        generate.modelName = this_model
        generate.skill = "knn"
        generate.format = generate_knn[this_model].format
        generate.id = this_model 
        generate.parameters = generate_knn[this_model].parameters
        generate.source = generate_knn[this_model].source
        generate.contextSize = generate_knn[this_model].contextSize
        generate.location = "huggingface"
        generate.units = "tokens"
        generate.destPath = local + "/" + this_model 
        results.push(generate)
    }
    return results
}

export function template_api(local_model_path, collection_path){
    let results = []
    let generate
    let models = Object.keys(generate_api)
    let local = local_model_path
    for (var model in models){
        let this_model = models[model]
        generate = {}
        generate.modelName = this_model
        generate.skill = "api"
        generate.format = generate_api[this_model].format
        generate.id = this_model 
        generate.parameters = generate_api[this_model].parameters
        generate.source = generate_api[this_model].source
        generate.contextSize = generate_api[this_model].contextSize
        generate.location = "huggingface"
        generate.units = "tokens"
        generate.destPath = local + "/" + this_model 
        results.push(generate)
    }
    return results
}


export function template_dataset(local_model_path, collection_path){
    let results = []
    let generate
    let models = Object.keys(generate_api)
    let local = local_model_path
    for (var model in models){
        let this_model = models[model]
        generate = {}
        generate.modelName = this_model
        generate.skill = "dataset"
        generate.format = generate_template[this_model].format
        generate.id = this_model 
        generate.samples = generate_template[this_model].samples
        generate.size = generate_template[this_model].size
        generate.location = "huggingface"
        generate.units = "MB"
        generate.destPath = local + "/" + this_model 
        results.push(generate)
    }
    return results
}


export class Generator{
    constructor(local_model_path, collection_path){
        this.llama_cpp = {}
        this.diffusion = {}
        this.hf_transformers = {}
        this.hf_embed = {}
        this.knn = {}
        this.api = {}
        this.custom = {}
        this.hf_lm = {}
        this.hf_t5 = {}
        this.hf_diffusion = {}
        this.dataset = {}
        this.local_model_path = local_model_path
        this.collection_path = collection_path
    }

    main(){
        this
        this.llama_cpp = template_llama_cpp(this.local_model_path, this.collection_path)
        this.hf_transformers = template_hf_transformers(this.local_model_path, this.collection_path)
        this.hf_embed = template_hf_embed(this.local_model_path, this.collection_path)
        this.hf_faster_whisper = template_hf_faster_whisper(this.local_model_path, this.collection_path)
        this.hf_lm = template_hf_lm(this.local_model_path, this.collection_path)
        this.hf_t5 = template_hf_t5(this.local_model_path, this.collection_path)
        this.hf_diffusion = template_hf_diffusion(this.local_model_path, this.collection_path)
        this.api = template_api(this.local_model_path, this.collection_path)
        this.knn = template_knn(this.local_model_path, this.collection_path)
        this.dataset = template_dataset(this.local_model_path, this.collection_path)
        return this 
    }
}