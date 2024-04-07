import fs from 'fs'
import path from 'path'
import os from 'os'

export function convert_fp32_to_gguf(path){
    let this_file = __filename  
    let this_dir = path.dirname(this_file)
    dest_path = path.replace(".ggml", ".gguf")
    let command = "python3 " + this_dir + "/libllama/avx2/convert-ggml-gguf.py " + path + " " + dest_path
    console.log("command is: " + command)
    let results = os.system(command)
}

export function convert_fp16_to_gguf(path){
    let this_file = __filename  
    let this_dir = path.dirname(this_file)
    dest_path = path.replace(".ggml", ".gguf")
    let command = "python3 "+ this_dir + "/libllama/avx2/convert-ggml-gguf.py " + path + " " + dest_path
    console.log("command is: " + command)
    let results = os.system(command)
}

export function convert_ggml_to_gguf(path){
    let this_file = __filename  
    let this_dir = path.dirname(this_file)
    dest_path = path.replace(".ggml", ".gguf")
    let command = "python3 "+ this_dir + "/libllama/avx2/convert-ggml-gguf.py " + path + " " + dest_path
    console.log("command is: " + command)
    let results = os.system(command)
}
