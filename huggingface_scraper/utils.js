import child_process from 'child_process'
import crypto from 'crypto' 
import fs from 'fs'
import { type } from 'os'
import path from 'path'
import prompt_sync from 'prompt-sync'
import prompt_sync_history from 'prompt-sync-history'
import request from 'sync-request'
import {createClient, createUploadStream} from './s3.js'
import process from 'process'

export function open_ended_question(question){

    let prompt = prompt_sync(({
        history: prompt_sync_history(),
        autocomplete: complete([]),
        sigint: true
    }))

    let answer = prompt(question)

    console.log("confirm answer: " + answer)
    let confirm = prompt("Confirm? (y/n): ")
    if (confirm != 'y' && confirm != 'Y'){
        answer = open_ended_question(question)
    }

    return answer
}

export function prepare_source(generate){

}

export function extract_source(generate){

}

export function multiple_select_question(question,choices){
    let tmp_choices = choices
    let done = false
    let selections = []
    let selection = multiple_choice_question(question, tmp_choices)
    while(!done){
        if (selection == 'None' || selection == '' || selection == null){
            done = true
        }
        else{
            selections.push(selection)
            tmp_choices = tmp_choices.filter(function(value, index, arr){ return value != selection;})
            selection = multiple_choice_question(question, tmp_choices)
        }
    }
    return selections
}

export function folder_data(generate, manifest, build_path){
    let files 
    let parent_dir = path.dirname(build_path)
    if (!fs.existsSync(parent_dir)){
        fs.mkdirSync(parent_dir)
    }
    if (!fs.existsSync(build_path)){
        fs.mkdirSync(build_path)
    }
    else{
        files = fs.readdirSync(build_path)
    }
    let new_files = []
    for(var file in files){
        let this_file = "/" + files[file]
        new_files.push(this_file)
    }
    new_files.push("/")
    console.log("file_structure: " + files)
    let fileDict = {}
    for(var i = 0; i < new_files.length; i++){
        let this_file = new_files[i]
        if (fs.existsSync(path.join(build_path,this_file))){
            let this_md5 = generate_md5(this_file, build_path)
            let this_size = fs.statSync(path.join(build_path,this_file)).size
            fileDict[this_file] = {"md5": this_md5, "size": this_size}
        }
        else{
            console.log("error reading: " + this_file)
        }
    }
    delete fileDict["/.git"]
    delete fileDict["/.gitattributes"]
    return  fileDict   
}

export function multiple_choice_question(question, choices){

    let prompt = prompt_sync(({
        history: prompt_sync_history(),
        autocomplete: complete(choices),
        sigint: true
    }))

    let new_choices = []
    new_choices.push("None")
    for (var choice in choices){
        new_choices.push(choices[choice])
    }

    let index = 0
    console.log(question)

    for( var choice in new_choices){
        console.log(index + ". " + new_choices[choice])
        index += 1
    }

    let answer = prompt("Select:")

    if (!new_choices.includes(answer)){
        if (parseInt(answer) >= 0 && parseInt(answer) < new_choices.length){
            answer = new_choices[parseInt(answer)]
        }
        else{
            console.log("Invalid Selection")
            answer = multiple_choice_question(question, choices)
        }
    }

    if (answer == 'None'){
        answer = ''
    }
    return answer
}

export function generate_cache_paths(generate, local_path){

    let s3bucket_name = JSON.parse(process.env.s3_creds)["bucket"]
    let s3_path = 's3://' + s3bucket_name 
    let http_path = ''
    let ipfs_gateway = ''
    let ipfs_path = 'ipfs://' + ipfs_gateway 

    let dict = {
        "local" : "local://" + local_path + '/' + generate.id + '/',
        "s3" : "s3://" + s3_path + '/' + generate.id,
        "https" : "https://" + http_path + '/' + generate.id + '/',
        "ipfs": "ipfs://" + ipfs_path + '/' + generate.id + '/',
        "md5": generate_md5(generate.source)
    }
    return dict
}

export function complete(commands){
    return function (str) {
      var i;
      var ret = [];
      for (i=0; i< commands.length; i++) {
        if (commands[i].indexOf(str) == 0)
          ret.push(commands[i]);
      }
      return ret;
    };
};

export function parse_templates(templates){
    let results = {}

    let chat_templates = ["llama-2", "vicuna", "alpaca", "chatlm"]
    let instruct_templates = []

    for( var template in templates){
        this_template = templates[template]
        if(chat_templates.includes(this_template)){
            results["chat"] = this_template
        }
    }
    return results
}

export function folder_to_bytestream(folder){
    let files = fs.readdirSync(folder)
    let bytestream = []
    for (var file in files){
        let this_file = files[file]
        let file_path = path.join(folder, this_file)
        let this_file_bytes = fs.readFileSync(file_path)
        bytestream.push(this_file_bytes)
    }
    return bytestream
}



export function generate_md5(source, this_path){
    let md5_path = ''
    if(this_path != undefined){
        md5_path = path.join(this_path, source)
    }
    let digest = ''
    if(fs.existsSync(md5_path)){
        if(fs.statSync(md5_path).isDirectory()){
            console.log()
        }
        else if (fs.statSync(md5_path).isFile())
        {
            let hash_md5_bash_command = `md5sum "${md5_path}" | awk '{print $1}'`
            digest = child_process.execSync(hash_md5_bash_command).toString().trim()
        }
    }
    else if(typeof source == "string" && this_path == undefined){
        const hash = crypto.createHash('md5');
        hash.update(source);
        digest = hash.digest('hex');
    }

    return digest
}


export function upload_files_s3(files, this_s3_creds) {
    const s3_creds = this_s3_creds

    function uploadFile(fileDict, index) {
        if (index >= Object.keys(fileDict).length) {
            // All files have been processed
            return Promise.resolve();
        }
        let file = Object.keys(fileDict)[index]
        let filekey = fileDict[file]
        if (filekey.startsWith('/')){
            filekey = filekey.slice(1)
        }
        if(filekey.includes("@")){
            filekey = filekey.replace("@", "\\@")
        }
        if(bucket == undefined){
            if (s3_creds != undefined){
                bucket = s3_creds.bucket
            }
            else{
                bucket = JSON.parse(process.env.s3_creds)["bucket"]
            }
        }

        console.log(`fileDict ${filekey} to s3://${bucket}/`);
        let reader
        if(!fs.existsSync(file)){
            return uploadFile(fileDict, index + 1); // Recursive call for the next file
        }else if(fs.statSync(file).isDirectory()){
            return uploadFile(fileDict, index + 1); // Recursive call for the next file
        }
        else {
            reader = fs.createReadStream(file);

            let { stream, promise } = createUploadStream({
                s3,
                bucket,
                key: filekey
            });
    
            reader.pipe(stream);
   
            return promise
                .then(() => {
                    console.log(`upload of ${filekey} complete`);
                    return uploadFile(fileDict, index + 1); // Recursive call for the next file
                })
                .catch((error) => {
                    console.error(error);
                    throw error;
                });

        }
    }

    function uploadFileS3cmd(fileDict, index, this_s3_creds) {
        if (index >= Object.keys(fileDict).length) {
            // All files have been processed
            return Promise.resolve();
        }
        let file = Object.keys(fileDict)[index]
        let filekey = fileDict[file]
        let bucket
        if(bucket == undefined){
            bucket = JSON.parse(process.env.s3_creds)["bucket"]
        }
        if (this_s3_creds != undefined){
            if (s3_creds != undefined){
                this_s3_creds = s3_creds
            }
            else{
                this_s3_creds = JSON.parse(process.env.s3_creds)
            }
        }
        if (filekey.startsWith('/')){
            filekey = filekey.slice(1)
        }
        if(filekey.includes("@")){
            filekey = filekey.replace("@", "\\@")
        }
        // console.log("process.env")
        // console.log(process.env)
        // console.log(Object.keys(process.env))
        // console.log("process.env.s3_creds:")
        // console.log(JSON.parse(process.env.s3_creds))
        // console.log(Object.keys(JSON.parse(process.env.s3_creds)))
        // console.log("this_s3_creds:")
        // console.log(this_s3_creds)
        // console.log(Object.keys(this_s3_creds))

        console.log(`fileDict ${filekey} to s3://${bucket}/`);
        let reader
        if(!fs.existsSync(file)){
            return uploadFileS3cmd(fileDict, index + 1, this_s3_creds = this_s3_creds); // Recursive call for the next file
        }else if(fs.statSync(file).isDirectory()){
            return uploadFileS3cmd(fileDict, index + 1, this_s3_creds = this_s3_creds); // Recursive call for the next file
        }
        else {

            let command = "s3cmd "
            command += "--access_key="+this_s3_creds.accessKey + " "
            command += "--secret_key="+this_s3_creds.secretKey + " "
            command += "--host-bucket="+this_s3_creds.hostBucket.replace("(","\\(").replace(")","\\)") + " " + " "
            command += "--host="+this_s3_creds.endpoint + " "
            command += "put " + file + " s3://" + bucket + "/" + filekey
            console.log("command: ", command)
            let results
            if(s3_creds != undefined){
                try{
                    results = child_process.execSync(command);
                }
                catch(error){
                    console.log("error uploading file")
                    console.log(error)
                }
                finally{
                    console.log(`upload of ${filekey} complete`);
                    return uploadFileS3cmd(fileDict, index + 1,this_s3_creds = this_s3_creds); // Recursive call for the next file                        
                }
            }else{
                return Promise.resolve();
            }
        }
    }


    if (files == undefined){
        throw "files is undefined"
    }
    if (this_s3_creds != undefined){
        return uploadFileS3cmd(files, 0, this_s3_creds)
            .then(() => {
                console.log("All files uploaded");
                return files;
            })
            .catch((error) => {
                console.error("An error occurred during upload:", error);
                throw error;
            });
    }
    else{
        console.log("s3_creds is undefined")
        Promise.resolve() 
    }
}


export function import_source(collection, generate, manifest, build_path, this_mysql_creds){

    function get_mysql_by_id(id, this_mysql_creds){
        return registry.db.checkpoints.selectOne({id: id})
    }

    function folderData(id, this_mysql_creds){
        let results = {}
        try {
            results = get_mysql_by_id(id)["folderData"]
        }
        catch(error){
            console.log("error getting mysql data")
            console.log(error)
            results = collection[id]["folderData"]
            return results
        }
        finally{
            return results
        }
    }

    function checkFolderData(folderPath, index, this_mysql_creds){
        if (this_mysql_creds == undefined){
            this_mysql_creds = mysql_creds
        }

        return folderData(manifest.id).then((fileDict) => {

            if (index >= Object.keys(fileDict).length) {
                // All files have been processed
                return Promise.resolve();
            }

            for (file in Object.keys(fileDict)){
                let this_file = fileDict[file]
                let this_path = path.join(build_path, this_file)
                if (!fs.existsSync(this_path)){
                    return false
                }
                else{
                    let this_size = fs.statSync(this_path).size
                    if (this_size != fileDict[file]["size"]){
                        return false
                    }
                }
            }})
        }

    if (this_mysql_creds != undefined){
        return checkFolderData(folderPath, 0)
            .then(() => {
                console.log("All files checked");
                return files;
            })
            .catch((error) => {
                console.error("An error occurred during upload:", error);
                throw error;
            });
    }
    else{
        Promise.resolve() 
    }

}


export function generate_template(generate){
    let results = {}
    results.id = ''
    results.source = ''
    results.metadata = {}
    results.hwRequirements = {}
    results.format = generate.format
    results.location = generate.location
    results.source = generate.source


    return results
}

export function generate_metadata_template(generate){
    let results = {}
    //results.cache = generate_cache_paths(generate)
    results.modelName = generate.modelName
    results.metadata = {}
    return results
}

export function find_id(generate){
    return false
}

export function generate_metadata_test(generate){
    let results = false

    // check for identitical model ids
    if (find_id(generate)){
        throw new Error("Invalid metadata", "identical model ids")
    }

    //let dicts = ["cache", "modelName", "units"]
    let dicts = ["modelName", "units"]

    let metadata = generate.metadata

    for (var dict in dicts){
        let this_dict = dicts[dict]
        if (!Object.keys(metadata).includes(this_dict)){
            throw new Error("Invalid metadata "+ this_dict + " not in metadata")
        }
    }

    if (!find_id(generate))
    {
        results = true
    }

    return results
}

export function generate_hwrequirements_template(generate){
    let results = {}
    results["minFlops"] = parseFloat(0)
    results["flopsPerUnit"] = parseFloat(0)
    results["minSpeed"] = parseFloat(0)
    results["gpuCount"] = []
    results["cpuCount"] = []
    results["minSpeed"] = parseFloat(0)
    results["gpuMemory"] = parseInt(0)
    results["cpuMemory"] = parseInt(0)
    results["minBandwidth"] = parseInt(0)
    results["minDiskIO"] = parseInt(0)
    results["diskUsage"] = parseInt(0)
    return results
}


export function test_if_https_file_exists(url) {
    try {
      const response = synchronousHttpGet(url);
      // Check if the response status code indicates success (e.g., 200)
      return response.statusCode === 200;
    } catch (error) {
      console.error('Error:', error);
      return false; // Return false in case of an error
    }
}
  

export function synchronousHttpGet(url) {
// Perform the GET request synchronously
return request('GET', url);
}

export function test_if_s3_file_exists(url){
    let results = false
    let s3 = require('s3')
    let client = s3.createClient()
    let params = {
        Bucket: url,
        Key: url
    }
    let downloader = client.downloadFile(params)
    downloader.on('error', function(err) {
        return false
    });
    downloader.on('progress', function() {
        return true
    });
    downloader.on('end', function() {
        return false
    });
}

export function test_if_hf_file_exists(url){
    let results = false
    let hf = require('@huggingface/node-hf-api')
    let model = hf.Model.fromPretrained(url)
    return results
}

export function test_source(generate){
    let results = false
    let prefixes = ["https://", "http://", "s3://", "local://", "hf://"]
    if (generate.location == "local"){
        if (fs.existsSync(generate.source)){
            results = true
        }
    }
    if (generate.location == "huggingface"){
        if(!generate.source.startsWith("https://")){
            throw new Error("Invalid source", "huggingface source must start with https://")
        }
        if(!generate.source.includes("huggingface.co")){
            throw new Error("Invalid source", "huggingface source must be from huggingface.co")
        }
        let test = test_if_https_file_exists(generate.source)
        if (test == true){
            results = true
        }
    }
    if (generate.location.includes("http")){            
        let test = test_if_https_file_exists(generate.source)
        if (test == true){
            results = true
        }
    }
    if (generate.source.startsWith("s3://")){
        if (test_if_s3_file_exists(generate.source)){
            results = true
        }
    }
    return results
}

export function generate_test(generate){
    let results = false
    let metadata = generate_metadata_test(generate)
    if (!metadata){
        throw new Error("Invalid metadata")
    }
    let hwRequirements = generate_hwrequrements_test(generate)
    if (!hwRequirements){
        throw new Error("Invalid hwRequirements")
    }
    let source = test_source(generate)
    if (source != true){
        console.log("source is: " + source)
        throw new Error("Invalid source")
    }
    let required_dicts = ["id", "source", "metadata", "hwRequirements", "format", "location", "source", "timestamp", "md5"]
    for (var dict in required_dicts){
        let this_dict = required_dicts[dict]
        if(this_dict.includes(results)){
            throw new Error("Invalid test", this_dict, "not in results")
        }
    }
    if (source && hwRequirements && metadata){
        results = true
    }
    return results
}


export function generate_hwrequrements_test(generate){
    let results = false

    //let dicts = ["cache", "modelName", "units"]
    let dicts =[ "minFlops", "flopsPerUnit", "minSpeed", "gpuCount", "minSpeed", "gpuMemory",  "diskUsage", "cpuMemory", "minBandwidth", "minDiskIO", "cpuCount"]

    let types = {
        "minFlops": "object",
        "flopsPerUnit": "number",
        "minSpeed": "number",
        "gpuCount": "object",
        "minSpeed": "number",
        "gpuMemory": "number",
        "diskUsage": "number",
        "cpuMemory": "number",
        "minBandwidth": "number",
        "minDiskIO": "number",
        "cpuCount": "object"
    }

    let hwRequirements = generate.hwRequirements

    for (var dict in dicts){
        let this_dict = dicts[dict]
        if (!Object.keys(hwRequirements).includes(this_dict)){
            throw new Error("Invalid hwRequirements "+ this_dict + " not in hwRequirements")
        }
        if (types[this_dict] != typeof(hwRequirements[this_dict])){
            throw new Error("Invalid hwRequirements "+ this_dict + " incorrect type, expected " + types[this_dict] + " but instead got " + typeof(hwRequirements[this_dict]))
        }
    }

    results = true

    return results
}