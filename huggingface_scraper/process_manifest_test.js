import fs from 'fs'
import path from 'path'
import * as process_manifest from './process_manifest.js'

let manifest = {
    
}

let generate = {

}


//process_manifest.main();
function test1(){
    let huggingface_dl_source = "https://huggingface.co/TheBloke/zephyr-7B-beta-GGUF/"
    let generate = {}
    generate.id = "zephyr-7B-beta-GGUF"
    generate.source = huggingface_dl_source
    generate.format = "gguf"
    generate.quantization = "Q4_K_M"
    let build_path = "/tmp/test/"
    build_path  = path.resolve(build_path)
    import_hf(generate, manifest, build_path, 1)    
}

function test2(){
    let generate ={}
    let path = "/storage/civitai-models/civitai-1093.ckpt"
    generate.skill = "diffusion"
    generate.format = "ckpt"
    convert_model(generate, manifest, path)
}

function test3(){
    let generate ={}
    let folder = "/storage/civitai-models/"
    generate.skill = "diffusion"
    generate.format = "ckpt"
    let file_list = fs.readdirSync(folder)
    for(var file in file_list){
        let this_file = file_list[file]
        let this_path = path.join(folder, this_file)
        if(this_path.endsWith(".ckpt")){
            try{
                convert_model(generate, manifest, this_path)
            }
            catch(error){
                console.log(error)
            }
            finally{
                console.log("done")
                // do we need to remove the file?
            }
        }
    }
} 

export function test4(){
    let generate = {}
    let manifest = {}
    generate.skill = "llama_cpp"
    generate.format = "llama_fp32"
    generate.quantization = "Q4_K_M"
    let folder = "/storage/cloudkit-models/airoboros-l2-13b-3.1.1/"
    convert_model(generate, manifest, folder)
}


export function test5(){
    generate.modelName = "cinematika-7b-v0.1"
    generate.skill = "llama_cpp"
    generate.format = "llama_fp32"
    generate.quantization = "Q4_K_M"
    generate.id = "cinematika-7b-v0.1-" + generate.quantization 
    manifest.id = "cinematika-7b-v0.1-" + generate.quantization
    manifest.format = generate.format
    manifest.hwRequirements = {}
    manifest.metadata = {}
    generate.parameters = 7 * 1024 * 1024 * 1024
    generate.location = 'huggingface'
    generate.source = "https://huggingface.co/jondurbin/cinematika-7b-v0.1"
    let folder = "/storage/cloudkit-models/cinematika-7b-v0.1/"
    var process = new process_manifest.process_manifest()
    process.__init__()
    process.main(generate, manifest, folder)
    console.log(process)
}

function test6(){
    let collection_path = "/storage/cloudkit-models/collection.json"
    let mysql_creds = {
        host: "swissknife.mwni.io",
        user: "swissknife",
        password: "W5!LIGO[pRPO0SdH",
        database: "swissknife",
    }
    let collection = fs.readFileSync(collection_path)
    collection = JSON.parse(collection)
    let models = process_manifest.get_mysql_table(mysql_creds,"Checkpoint_bak")
    process_manifest.update_collection_mysql(collection, collection_path, mysql_creds)
    return collection
}


//let test = process_manifest.get_pinset()


test6()

//test5()

//test4()

//test3()