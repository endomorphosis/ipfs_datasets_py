import * as child_process from 'child_process';
import * as fs from 'fs';
import path from 'path'
import { generate_md5, folder_data } from './utils.js';
const cwd = path.dirname(new URL(import.meta.url).pathname)

export function convert_gguf(generate, manifest){
    let executable_path = path.join(cwd,"libllama")
    executable_path = path.join(executable_path, "convert.py")
    let files = fs.readdirSync(generate.build_path)
    let new_files = []
    for(var file in files){
        let this_file = "/" + files[file]
        new_files.push(this_file)
    }
    generate.format = "gguf"
    return new_files
}

export function convert_ggml(generate, manifest){
    let executable_path = path.join(cwd,"libllama")
    executable_path = path.join(executable_path, "convert.py")
    let files 
    if (Object.keys(generate).includes("build_path")){
        let files = fs.readdirSync(generate.build_path)
    }
    let new_files = []
    for(var file in files){
        let this_file = "/" + files[file]
        new_files.push(this_file)
    }
    generate.format = "gguf"
    return new_files
}

export function convert_llama_fp16_bak(generate, manifest, this_path){
    let executable_path = path.join(cwd,"libllama")
    executable_path = path.join(executable_path, "convert.py")
    let quantization = generate.quantization
    let ctx_length = generate.ctx_length
    let source_dir = path.dirname(this_path)
    let model_name = this_path.replace(source_dir,"").replace("/","").replace("/","")
    let f16_model_name = model_name + "-f16"
    let dest_path = path.join(source_dir, model_name + "-" + quantization + "/" + model_name + "-" + quantization +  ".gguf")
    let f16_dest_path = path.join(source_dir, model_name + "-" + quantization + "/" + f16_model_name + ".gguf")
    if(!fs.existsSync(path.join(source_dir, model_name))){
        fs.mkdirSync(path.join(source_dir, model_name))
    }
    let command
    if (ctx_length != undefined){ 
        command = "python3 " + executable_path + " --outfile " + f16_dest_path + " --ctx + " + ctx_length  + " " + this_path + quantization + "/"
    }
    else{
        command = "python3 " + executable_path + " --outfile " + f16_dest_path  + " " + this_path +"/"
    }
    console.log("command: " + command)
    let results = child_process.execSync(command, {stdio: 'ignore'})
    if (quantization != "f16"){
        let executable_path = path.join(cwd,"libllama")
        executable_path = path.join(executable_path, "quantize")
        let command2 =  executable_path + " " + f16_dest_path + " " + dest_path + " " + quantization
        console.log("command2: " + command2)
        //let results2 = child_process.execSync(command2, {stdio: 'ignore'})
        let command3 = "rm -rf " + f16_dest_path
        console.log("command3: " + command3)
        let results3 = child_process.execSync(command3, {stdio: 'ignore'})
    }
    let files = fs.readdirSync(generate.build_path)
    let new_files = []
    for(var file in files){
        let this_file = "/" + files[file]
        new_files.push(this_file)
    }
    generate.format = "gguf"
    return new_files
}



export function convert_llama_fp16(generate, manifest, this_path){
    let executable_path = path.join(cwd,"libllama")
    executable_path = path.join(executable_path, "convert.py")
    let quantization = generate.quantization
    let ctx_length = generate.ctx_length
    let source_dir = path.dirname(this_path)
    let model_name = generate.modelName
    let f16_model_name = model_name + "-f16"
    let dest_path = path.join(source_dir, model_name + "-" + quantization + "@gguf")
    dest_path = path.join(dest_path, model_name + "-" + quantization +  ".gguf")
    let f16_dest_path = path.join(source_dir,generate.id + "@gguf")
    f16_dest_path = path.join(f16_dest_path, f16_model_name + ".gguf")
    //if(!fs.existsSync(path.join(source_dir, model_name + "-" + quantization))){
        //fs.mkdirSync(path.join(source_dir, model_name + "-" + quantization))
    //}
    let command
    if (ctx_length != undefined){ 
        command = "python3 " + executable_path + " --outfile " + f16_dest_path + " --ctx + " + ctx_length  + " " + this_path
    }
    else{
        command = "python3 " + executable_path + " --outfile " + f16_dest_path  + " " + this_path
    }
    console.log("command: " + command)
    if(!fs.existsSync(path.dirname(f16_dest_path))){
        fs.mkdirSync(path.dirname(f16_dest_path))
    }
    let results = child_process.execSync(command, {stdio: 'ignore'})
    let new_path = path.dirname(f16_dest_path)
    let command_1 = "rm -rf " + this_path
    console.log("command_1: " + command_1)
    if (quantization != "f32"){
        let executable_path = path.join(cwd,"libllama")
        executable_path = path.join(executable_path, "quantize")
        let command2 =  executable_path + " " + f16_dest_path + " " + dest_path + " " + quantization
        console.log("command2: " + command2)
        let results2 = child_process.execSync(command2, {stdio: 'ignore'})
        let command3 = "rm -rf " + this_path
        console.log("command3: " + command3)
        let results3 = child_process.execSync(command3, {stdio: 'ignore'})
        let command4 = "rm " + f16_dest_path
        console.log("command4: " + command4)
        let results4 = child_process.execSync(command4, {stdio: 'ignore'})
    }
    try {
        const stats = fs.statSync(dest_path);
    
        if (stats.isDirectory()) {
            console.log(`${dest_path} is a directory.`);
        } 
        else if (stats.isFile()) {
            console.log(`${dest_path} is a file.`);
            dest_path = path.dirname(dest_path)
        }
    } catch (err) {
        console.error(err);
    }

    let command4 = "cd " + dest_path + " ; find *"
    console.log("command4: " + command4)
    let file_structure = child_process.execSync(command4)
    file_structure = file_structure.toString().split("\n")
    for (var i = 0; i < file_structure.length; i++){
        file_structure[i] = "/" + file_structure[i]
    }
    console.log("file_structure: " + file_structure)
    let files = fs.readdirSync(new_path)
    let new_files = []
    for(var file in files){
        let this_file = "/" + files[file]
        new_files.push(this_file)
    }
    generate.format = "gguf"
    return new_files
}

export function convert_llama_fp32(generate, manifest, this_path){
    let executable_path = path.join(cwd,"libllama")
    executable_path = path.join(executable_path, "convert.py")
    let quantization = generate.quantization
    let ctx_length = generate.ctx_length
    let source_dir = path.dirname(this_path)
    let model_name = generate.modelName
    let f32_model_name = model_name + "-f32"
    let dest_path = path.join(source_dir, model_name + "-" + quantization)
    dest_path = path.join(dest_path, model_name + "-" + quantization +  ".gguf")
    let f32_dest_path = path.join(source_dir,generate.id)
    f32_dest_path = path.join(f32_dest_path, f32_model_name + ".gguf")
    //if(!fs.existsSync(path.join(source_dir, model_name + "-" + quantization))){
        //fs.mkdirSync(path.join(source_dir, model_name + "-" + quantization))
    //}
    let command
    if (ctx_length != undefined){ 
        command = "python3 " + executable_path + " --outfile " + f32_dest_path + " --ctx + " + ctx_length  + " " + this_path
    }
    else{
        command = "python3 " + executable_path + " --outfile " + f32_dest_path  + " " + this_path
    }
    console.log("command: " + command)
    if(!fs.existsSync(path.dirname(f32_dest_path))){
        fs.mkdirSync(path.dirname(f32_dest_path))
    }
    let results = child_process.execSync(command, {stdio: 'ignore'})
    let new_path = path.dirname(f32_dest_path)
    let command_1 = "rm -rf " + this_path
    console.log("command_1: " + command_1)
    if (quantization != "f32"){
        let executable_path = path.join(cwd,"libllama")
        executable_path = path.join(executable_path, "quantize")
        let command2 =  executable_path + " " + f32_dest_path + " " + dest_path + " " + quantization
        console.log("command2: " + command2)
        let results2 = child_process.execSync(command2, {stdio: 'ignore'})
        let command3 = "rm -rf " + this_path
        console.log("command3: " + command3)
        let results3 = child_process.execSync(command3, {stdio: 'ignore'})
        let command4 = "rm " + f32_dest_path
        console.log("command4: " + command4)
        let results4 = child_process.execSync(command4, {stdio: 'ignore'})
    }
    try {
        const stats = fs.statSync(dest_path);
    
        if (stats.isDirectory()) {
            console.log(`${dest_path} is a directory.`);
        } 
        else if (stats.isFile()) {
            console.log(`${dest_path} is a file.`);
            dest_path = path.dirname(dest_path)
        }
    } catch (err) {
        console.error(err);
    }

    let command4 = "cd " + dest_path + " ; find *"
    console.log("command4: " + command4)
    let file_structure = child_process.execSync(command4)
    file_structure = file_structure.toString().split("\n")
    for (var i = 0; i < file_structure.length; i++){
        file_structure[i] = "/" + file_structure[i]
    }
    console.log("file_structure: " + file_structure)
    let files = fs.readdirSync(new_path)
    let new_files = []
    for(var file in files){
        let this_file = "/" + files[file]
        new_files.push(this_file)
    }
    generate.format = "gguf"
    return new_files
}

export function convert_safetensor_hf(generate, manifest, this_path){
    let executable_path = path.join(cwd,"huggingface")
    executable_path = path.join(executable_path, "convert_safetensor_hf.py")
    let dest_path =  this_path.replace(".safetensor", "/")
    let command = "python3 " + executable_path + " " + this_path + " " + dest_path 
    console.log("command: " + command)
    let results = child_process.execSync(command, {stdio: 'ignore'})
    let files = fs.readdirSync(generate.build_path)
    let new_files = []
    for(var file in files){
        let this_file = "/" + files[file]
        new_files.push(this_file)
    }
    return new_files
}

export function convert_ckpt_hf(generate, manifest, this_path){
    let executable_path = path.join(cwd,"huggingface")
    executable_path = path.join(executable_path, "convert_ckpt_hf.py")
    let dest_path =  this_path.replace(".ckpt", "/")
    let command = "python3 " + executable_path + " " + this_path + " " + dest_path 
    console.log("command: " + command)
    let results = child_process.execSync(command, {stdio: 'ignore'})
    let files = fs.readdirSync(generate.build_path)
    let new_files = []
    for(var file in files){
        let this_file = "/" + files[file]
        new_files.push(this_file)
    }
    return new_files
}

export function convert_safetensor_ckpt(generate, manifest, this_path){
    let command
    let executable_path = path.join(cwd,"huggingface")
    executable_path = path.join(executable_path, "convert_original_stable_diffusion_to_diffusers.py")
    let source_dir = path.dirname(this_path)
    let model_name = this_path.replace(source_dir,"")
    let dest_path =  source_dir + model_name.replace(".safetensors","") + "/"
    command = "python3 " + executable_path + " --checkpoint_path " + this_path + " --dump_path " + dest_path +
    console.log("command: " + command)
    let results = child_process.execSync(command, {stdio: 'ignore'})
    convert_hf_ckpt(generate, manifest, dest_path)
    let command_2 = "rm -rf " + dest_path
    results = child_process.execSync(command_2, {stdio: 'ignore'})
    let files = fs.readdirSync(generate.build_path)
    let new_files = []
    for(var file in files){
        let this_file = "/" + files[file]
        new_files.push(this_file)
    }
    return new_files
}

export function convert_ckpt_safetensor(generate, manifest, this_path){
    let command
    let executable_path = path.join(cwd,"huggingface")
    executable_path = path.join(executable_path, "convert_original_stable_diffusion_to_diffusers.py")
    let source_dir = path.dirname(this_path)
    let model_name = this_path.replace(source_dir,"")
    let dest_path =  source_dir + model_name.replace(".ckpt","") + "/"
    command = "python3 " + executable_path + " --checkpoint_path " + this_path + " --dump_path " + dest_path 
    console.log("command: " + command)
    let results = child_process.execSync(command, {stdio: 'ignore'})
    convert_hf_safetensor(generate, manifest, dest_path)
    let command_2 = "rm -rf " + dest_path
    console.log("command_2: " + command_2)
    results = child_process.execSync(command_2, {stdio: 'ignore'})
    //let command_3 = "rm -rf " + this_path
    //console.log("command_3: " + command_3)
    //results = child_process.execSync(command_3, {stdio: 'ignore'})
    let files = fs.readdirSync(generate.build_path)
    let new_files = []
    for(var file in files){
        let this_file = "/" + files[file]
        new_files.push(this_file)
    }
    return new_files
}

export function convert_hf_ckpt(generate, manifest, source_path){
    let executable_path = path.join(cwd,"huggingface")
    executable_path = path.join(executable_path, "convert_diffusers_to_original_stable_diffusion.py")
    let source_dir = path.dirname(source_path)
    let model_name = source_path.replace(source_dir,"").replace("/","")
    let dest_path = path.join(source_dir, model_name + ".ckpt")
    let command = "python3 " + executable_path + " --model_path " + this_path + " --checkpoint_path " + dest_path 
    console.log("command: " + command)
    let results = child_process.execSync(command, {stdio: 'ignore'})
    let files = fs.readdirSync(generate.build_path)
    let new_files = []
    for(var file in files){
        let this_file = "/" + files[file]
        new_files.push(this_file)
    }
    return new_files
}

export function convert_hf_safetensor(generate, manifest, source_path){
    let executable_path = path.join(cwd,"huggingface")
    executable_path = path.join(executable_path, "convert_diffusers_to_original_stable_diffusion.py")
    let source_dir = path.dirname(source_path)
    let model_name = source_path.replace(source_dir,"").replace("/","").replace("/","")
    let dest_path = path.join(source_dir, model_name + ".safetensors") 
    let command = "python3 " + executable_path + " --model_path " + source_path + " --checkpoint_path " + dest_path + " --use_safetensors"
    console.log("command: " + command)
    let results = child_process.execSync(command, {stdio: 'ignore'})
    let files = fs.readdirSync(generate.build_path)
    let new_files = []
    for(var file in files){
        let this_file = "/" + files[file]
        new_files.push(this_file)
    }
    return new_files
}

export function convert_model(generate, manifest, this_path){
    let results = ""

    function convert(generate, manifest, this_path){
        if(generate.skill == "llama_cpp"){
            if (generate.format == 'gguf'){
                return convert_ggml(generate, manifest, this_path)
            }
            if (generate.format == 'ggml'){
                return convert_ggml(generate, manifest, this_path)
            }
            if (generate.format == 'llama_fp16'){
                return convert_llama_fp16(generate, manifest, this_path)
            }
            if (generate.format == 'llama_fp32'){
                return convert_llama_fp32(generate, manifest, this_path)
            }
        }
        if(generate.skill == "diffusion"){
            if (generate.format == 'safetensor'){
                console.log()
            }
            if (generate.format == 'ckpt'){
                return convert_ckpt_safetensor(generate, manifest, this_path)
            }
            if (generate.format == 'hf'){
                return convert_hf_safetensor(generate, manifest, this_path)
            }
        }
    }

    function convert_and_move(generate, manifest, this_path){
        let old_format = generate.format
        convert(generate, manifest, this_path)
        let new_format = generate.format
        if (old_format != new_format){
            generate.converted = true
        }

        //let build_path_split = generate.build_path.split("@")
        //build_path_split[1] = generate.format
        //let new_build_path = build_path_split.join("@")
        //let command = "rm " + generate.build_path + " " + new_build_path
        //let results = child_process.execSync(command, {stdio: 'ignore'})

        //generate.build_path = new_build_path
        manifest.folderData = folder_data(generate, manifest, generate.build_path)
        return Object.keys(manifest.folderData)    
    }

    return convert_and_move(generate, manifest, this_path)

}


