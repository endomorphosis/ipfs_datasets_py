import {complete, open_ended_question, multiple_choice_question, parse_templates, generate_template, generate_metadata_template, generate_hwrequirements_template} from '../utils.js'
import prompt_sync from 'prompt-sync'
import prompt_sync_history from 'prompt-sync-history'
import models_generate_diffusion from '../modeldata/generate_diffusion.json' assert { type: 'json' };

export class Manifest_diffusion{
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
        let generation = diffusion_generate(generate)
        for (var key in generation){
            this[key] = generation[key]
        }
        return this
    }

    calc(){
        return diffusion_calc()
    }
}

export default function diffusion_calc(){

    let prompt = prompt_sync(({
        history: prompt_sync_history(),
        autocomplete: complete([]),
        sigint: true
    }))

    let modelName = open_ended_question("Enter a model name: ")

    let locations = ['local', 'huggingface', 'http', 's3']

    let location = multiple_choice_question("Where is the model located?", locations) 

    let source = open_ended_question("Enter a source from " + location + ": ")

    let formats = ["ckpt", "safetensors"]

    let format = multiple_choice_question("Select a format: ", formats)
    
    let quantizations = ["fp32", "fp16" ]

    let quantization = multiple_choice_question("what is the model quantization?", quantizations)

    let resolutions = [512, 1024, 2048, 4096]

    let resolution = prompt("Select a context size: ", resolutions)

    let controlnet_types = ["inpainting", "instructPix2Pix", "canny2img", "hed2img", "depth2img", "normal2img","pose2img","scribble2img","seg2img"]

    let controlnet = multiple_choice_question("Select a controlnet type: ", controlnet_types)

    if (controlnet != ''){
        console.log("controlnet is: " + controlnet)

        let dependency_options = ["yes", "no"]

        let dependency = open_ended_question('Are the depenencies bundled with the model? ', dependency_options)

        if (dependency == 'no'){

            console.log("dependencies are not bundled")

            let dependency_location = multiple_choice_question("What is the dependency source?", locations)
                        
            let dependency_source = open_ended_question("What is the dependency source?: ")

        }
    
    }

    let versions = ["v1.5", "v1.6","v2.0","v2.1"]

    let version = multiple_choice_question("Select a version: ", versions)

    let default_steps = open_ended_question("Enter a default number of steps: ")

    let default_noise = open_ended_question("Enter a default denoising strength: ")

    let default_cfgscale = open_ended_question("What is the default cfgscale?")

    let batch_size_options = [1,2,4]

    let batch_size = multiple_choice_question("Enter a batch size: ", batch_size_options)
    
    let generate = {}
    generate.modelName = modelName
    generate.location = location
    generate.source = source
    generate.format = format
    generate.quantization = quantization
    generate.resolution = resolution
    generate.controlnet = controlnet
    generate.version = version
    generate.default_steps = default_steps
    generate.default_noise = default_noise
    generate.default_cfgscale = default_cfgscale
    generate.batch_size = batch_size

    let results = diffusion_generate(generate)

    return results
}

export function diffusion_generate_hwrequirements(generate){
    let results = generate_hwrequirements_template(generate)
    results.cpu_count = [2,4]
    results.gpuCount = [1]
    let padding = 1.1
    if(generate.version == 'v1.5'){
        results.parameters = 1.5e9
        results.flopsPerUnit = 0
        minFlops = {
            "fp8": 0,
            "fp16": 10,
            "fp32": 0,
        }
        results.megapixel_steps_per_second = 0
    }
    if(generate.version == 'v1.6'){
        results.parameters = 1.5e9
        results.flopsPerUnit = 0
        minFlops = {
            "fp8": 0,
            "fp16": 10,
            "fp32": 0,
        }
        results.steps_per_second = 0
    }
    if(generate.version == 'v2.0'){
        results.parameters = 1.5e9
        results.flopsPerUnit = 0
        results.minFlops = {
            "fp8": 0,
            "fp16": 20,
            "fp32": 0,
        }
        results.megapixel_steps_per_second = 0
    }
    if(generate.version == 'v2.1'){
        results.parameters = 1.5e9
        results.flopsPerUnit = 0
        results.minFlops = {
            "fp8": 0,
            "fp16": 20,
            "fp32": 0,
        }
        results.megapixel_steps_per_second = 0
    }

    if (generate.quantization == 'fp16'){
        results.gpuMemory = results.parameters * 2 * padding
        results.disk_usage = results.parameters * 2 * padding
        results.cpu_memory = results.parameters * 2 * padding
    }
    if (generate.quantization == 'fp32'){
        results.gpuMemory = results.parameters * 4 * padding
        results.disk_usage = results.parameters * 4 * padding
        results.cpu_memory = results.parameters * 4 * padding
    }

    if (generate.controlnet != 'none'){
        if (generate.controlnet == 'inpainting'){

        }
        if (generate.controlnet == 'hed2img'){
            results.disk_usage = results.disk_usage + 1e9
            results.cpu_memory = results.cpu_memory + 1e9
            results.gpuMemory = results.gpuMemory + 1e9
        }
        if (generate.controlnet == 'depth2img'){
            results.disk_usage = results.disk_usage + 1e9
            results.cpu_memory = results.cpu_memory + 1e9
            results.gpuMemory = results.gpuMemory + 1e9
        }
        if (generate.controlnet == 'normal2img'){
            results.disk_usage = results.disk_usage + 1e9
            results.cpu_memory = results.cpu_memory + 1e9
            results.gpuMemory = results.gpuMemory + 1e9
        }
        if (generate.controlnet == 'pose2img'){
            results.disk_usage = results.disk_usage + 1e9
            results.cpu_memory = results.cpu_memory + 1e9
            results.gpuMemory = results.gpuMemory + 1e9
        }
        if (generate.controlnet == 'scribble2img'){
            results.disk_usage = results.disk_usage + 1e9
            results.cpu_memory = results.cpu_memory + 1e9
            results.gpuMemory = results.gpuMemory + 1e9
        }
        if (generate.controlnet == 'seg2img'){
            results.disk_usage = results.disk_usage + 1e9
            results.cpu_memory = results.cpu_memory + 1e9
            results.gpuMemory = results.gpuMemory + 1e9
        }
    }

    return results
}


export function diffusion_generate_metadata(generate){
    let results = generate_metadata_template(generate)
    results.default_cfgscale = generate.default_cfgscale
    results.default_noise = generate.default_noise
    results.default_steps = generate.default_steps
    results.controlnet = generate.controlnet
    results.resolution = generate.resolution
    results.format = generate.format
    results.location = generate.location
    results.modelName = generate.modelName
    results.model_type = 'diffusion'
    results.quantization = generate.quantization
    results.version = generate.version
    let controlnet_types = ["canny2img", "hed2img", "depth2img", "normal2img","pose2img","scribble2img","seg2img"]
    let special_types = ["inpainting", "instruct"]
    if (generate.controlnet != 'none'){
        results.id = generate.modelName + '-' + (parseInt(generate.parameters) / 1000000000).toString() + 'b-' + generate.quantization + '-' + generate.controlnet
    }
    if(generate.version == 'v1.5'){
        if (generate.controlnet != 'none'){
            generate.templates = ['sd1_canny2img', 'sd1_hed2img', 'sd1_depth2img', 'sd1_normal2img','sd1_pose2img','sd1_scribble2img','sd1_seg2img']
        }
        else{
            generate.templates = ['sd1_txt2img', 'sd1_img2img', 'sd1_img2txt']
        }
    }
    if(generate.version == 'v1.6'){
        if (generate.controlnet != 'none'){
            generate.templates = ['sd1_canny2img', 'sd1_hed2img', 'sd1_depth2img', 'sd1_normal2img','sd1_pose2img','sd1_scribble2img','sd1_seg2img']
        }
        else{
            generate.templates = ['sd1_txt2img', 'sd1_img2img', 'sd1_img2txt']
        }
    }
    if(generate.version == 'v2.0'){
        if (generate.controlnet != 'none'){
            generate.templates = ['sd2_canny2img', 'sd2_hed2img', 'sd2_depth2img', 'sd2_normal2img','sd2_pose2img','sd2_scribble2img','sd2_seg2img']
        }
        else{
            generate.templates = ['sd2_txt2img', 'sd2_img2img', 'sd2_img2txt']
        }
    }
    if(generate.version == 'v2.1'){
        if (generate.controlnet != 'none'){
            generate.templates = ['sd2_canny2img', 'sd2_hed2img', 'sd2_depth2img', 'sd2_normal2img','sd2_pose2img','sd2_scribble2img','sd2_seg2img']
        }
        else{
            generate.templates = ['sd2_txt2img', 'sd2_img2img', 'sd2_img2txt']
        }
    }
    if(generate.version == 'sdxl'){
        if (generate.controlnet != 'none'){
            generate.templates = ['sdxl_canny2img', 'sdxl_hed2img', 'sdxl_depth2img', 'sdxl_normal2img','sdxl_pose2img','sdxl_scribble2img','sdxl_seg2img']
        }
        else{
            generate.templates = ['sdxl_txt2img', 'sdxl_img2img', 'sdxl_img2txt']
        }
    }
    results.units = "megapixel_steps"
    return results
}


export function diffusion_generate(generate){
    let results = generate_template(generate)
    results.id = generate.modelName + '-' + (parseInt(generate.parameters) / 1000000000).toString() + 'b-' + generate.quantization
    results.hwRequirements = diffusion_generate_hwrequirements(generate)
    results.metadata = diffusion_generate_metadata(generate)
    results.skill = "diffusion"
    return results
}

export function diffusion_add(generation){
    if (generation.modelName != undefined){
        models_generate_diffusion[generation.modelName] = generation
        fs.writeFileSync(path.resolve('../modeldata/generate_diffusion.json'), JSON.stringify(models_generate_diffusion, null, 2))       
        return Object.keys(models_generate_diffusion)
    }
    else{
        throw "model name is undefined"
    }      
}