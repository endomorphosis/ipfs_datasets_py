import fs from 'fs'
import { folder_data, generate_md5, synchronousHttpGet, upload_files_s3} from './utils.js'
import { ipfsClusterCtl } from "./ipfs.js"
import { convert_model } from './convert.js'
import { generate_readme } from './readme-generate.js'
import child_process, { exec } from 'child_process'
import process from 'process'
import path, { relative } from 'path'

const cwd = path.dirname(new URL(import.meta.url).pathname)

export class process_manifest
{
    constructor(s3_creds, hf_creds, mysql_creds, local_model_path, ipfs_path, collection_path){
        this.env = process.env
        if (s3_creds != undefined){
            process.env.s3_creds = JSON.stringify(s3_creds)
            this.s3_creds = s3_creds
        }
        if (hf_creds != undefined){
            process.env.hf_creds = JSON.stringify(hf_creds)
            this.hf_creds = hf_creds
        }
        if (mysql_creds != undefined){
            process.env.mysql_creds = JSON.stringify(mysql_creds)
            this.mysql_creds = mysql_creds
        }
        if (local_model_path != undefined){
            process.env.local_model_path = local_model_path
            this.local_model_path = local_model_path
        }
        if (ipfs_path != undefined){
            process.env.ipfs_path = ipfs_path
            this.ipfs_path = ipfs_path
        }
        if (collection_path != undefined){
            process.env.collection_path = collection_path
            this.collection_path = collection_path
        }
        this.manifest = {}
        this.generate = {}
        this.build_path = ""
        this.dest_path = ""
        if (!fs.existsSync(this.collection_path)){
            fs.writeFileSync(this.collection_path, "{}")
        }
        if(!fs.existsSync(this.local_model_path)){
            fs.mkdirSync(this.local_model_path)
        }
        if(!fs.existsSync(this.ipfs_path)){
            fs.mkdirSync(this.ipfs_path)
        }
        if(!fs.existsSync("/tmp/build")){
            fs.mkdirSync("/tmp/build")
        }
    }

    process_prompted_manifest(manifest, folder){
        // console.log("process_manifest")
        // console.log("main(generate, manifest, folder)")
        // console.log("manifest: ", manifest)
        // console.log("folder: ", folder)
        let collection_path = this.collection_path
        this.manifest = manifest
        let generate = manifest
        this.folder = folder
        let local_model_path = process.env.local_model_path
        let build_path 
        let dest_path
        let s3_creds = this.s3_creds
        let hf_creds = this.hf_creds
        let mysql_creds = this.mysql_creds
        delete manifest["s3_creds"];
        delete manifest["hf_creds"];
        delete manifest["mysql_creds"];
        generate.s3_creds = s3_creds
        generate.hf_creds = hf_creds
        generate.mysql_creds = mysql_creds

        console.log("local_model_path: ", local_model_path)
        console.log("process.env.local_model_path: ", process.env.local_model_path)

        if(manifest.metadata.quantization != undefined && !manifest.id.includes(manifest.metadata.quantization)){
            build_path = path.join("/tmp/build/", manifest.id + "-" + manifest.metadata.quantization) 
            generate.build_path = path.join("/tmp/build/", manifest.id + "-" + manifest.metadata.quantization)
        }
        else{
            build_path = path.join("/tmp/build/" , manifest.id) 
            generate.build_path = path.join("/tmp/build/" , manifest.id)
        }
        if (manifest.format != undefined){
            //this.build_path = this.build_path + "@" + this.generate.format
        }
        build_path = path.resolve(build_path)
        generate.build_path = path.resolve(generate.build_path)
        if(!fs.existsSync(build_path)){
            fs.mkdirSync(build_path)
        }

        generate.destPath = local_model_path + manifest.id
        this.generrate = generate
        let manifest_file = path.join(build_path, "manifest.json")
        let collection = load_local_collection(this.collection_path)
        this.ipfsCluster = new ipfsClusterStatus(collection)
        if (Object.keys(generate).includes("build_path")){
            build_path = generate.build_path
        }
        if(Object.keys(generate).includes("destPath")){
            dest_path = generate.destPath
        }
        fs.writeFileSync(path.join(build_path, "manifest.json"), JSON.stringify(manifest))
        let file_dict = package_model_data(generate, manifest, collection)
        delete manifest["s3_creds"];
        delete manifest["hf_creds"];
        delete manifest["mysql_creds"];
        console.log("process_prompted_manifest")
        console.log("generate: ", generate)
        manifest.folderData = generate.folderData
        //delete this.manifest.skill
        fs.writeFileSync(path.join(build_path, "manifest.json"), JSON.stringify(manifest))
        let cache = export_cache_locations(manifest, generate, file_dict)
        manifest.folderData = folder_data(generate, manifest, build_path)
        fs.writeFileSync(path.join(build_path, "manifest.json"), JSON.stringify(manifest))
        let manifest_data = upload_manifest_files(manifest, generate, local_model_path, this.ipfsCluster)
        manifest.folderData = folder_data(generate, manifest, dest_path)
        fs.writeFileSync(path.join(dest_path, "manifest.json"), JSON.stringify(manifest))
        let new_collection = update_collection(manifest, generate, manifest_data, collection_path)
        fs.writeFileSync(path.join(dest_path, "manifest.json"), JSON.stringify(manifest))
        this.collection = collection
        return this            
    }

    main(generate, manifest, folder){
        console.log("process_manifest")
        console.log("main(generate, manifest, folder)")
        console.log("generate: ", generate)
        console.log("manifest: ", manifest)
        console.log("folder: ", folder)
        let collection_path = this.collection_path
        this.generate = generate
        this.manifest = manifest
        this.folder = folder
        if(generate.quantization != undefined && !generate.id.includes(generate.quantization)){
            this.build_path = "/tmp/build/" + generate.id + "-" + generate.quantization 
        }
        else{
            this.build_path = "/tmp/build/" + generate.id 
        }
        if (generate.format != undefined){
            //this.build_path = this.build_path + "@" + this.generate.format
        }
        this.build_path = path.resolve(this.build_path)
        if(!fs.existsSync(this.build_path)){
            fs.mkdirSync(this.build_path)
        }
        let manifest_file = path.join(this.build_path, "manifest.json")
        let collection
        collection = load_local_collection(collection_path)
        this.ipfsCluster = new ipfsClusterStatus(collection)
        fs.writeFileSync(path.join(this.build_path, "manifest.json"), JSON.stringify(this.manifest))
        let file_dict = package_model_data(this.generate, this.manifest, collection)
        if (Object.keys(generate).includes("build_path")){
            this.build_path = generate.build_path
        }
        if(Object.keys(generate).includes("destPath")){
            this.dest_path = generate.destPath
        }
        //delete this.manifest.skill
        fs.writeFileSync(path.join(this.build_path, "manifest.json"), JSON.stringify(this.manifest))
        let cache = export_cache_locations(this.manifest, this.generate, file_dict)
        manifest.cache = cache
        manifest.folderData = folder_data(this.generate, this.manifest, this.build_path)
        fs.writeFileSync(path.join(this.build_path, "manifest.json"), JSON.stringify(this.manifest))
        let manifest_data = upload_manifest_files(this.manifest, this.generate, local_model_path, this.ipfsCluster)
        manifest.folderData = folder_data(this.generate, this.manifest, this.dest_path)
        fs.writeFileSync(path.join(this.dest_path, "manifest.json"), JSON.stringify(this.manifest))
        let new_collection = update_collection(this.manifest, this.generate, manifest_data, collection_path)
        fs.writeFileSync(path.join(this.dest_path, "manifest.json"), JSON.stringify(this.manifest))
        this.collection = collection
        return this        
    }
}

export function load_local_collection(collection_path){
    let collection = {}
    if(fs.existsSync(collection_path)){
        collection = JSON.parse(fs.readFileSync(collection_path, 'utf-8'))
    }
    else{
        collection = {}
    }
    return collection
}

export function ipfsClusterStatus(collection){
    let this_cluster = new ipfsClusterCtl()
    let status = this_cluster.check_collection(collection)
    return status
}

export function update_collection(manifest, generate, manifest_data, collection_path){
    let this_mysql_creds
    if (this_mysql_creds == undefined){
        if (generate.mysql_creds != undefined){
            this_mysql_creds = generate.mysql_creds
        }
        else{
            this_mysql_creds = JSON.parse(process.env.mysql_creds)
        }
    }
    let this_s3_creds
    if (this_s3_creds == undefined){
        if (generate.s3_creds != undefined){
            this_s3_creds = generate.s3_creds
        }
        else{
            this_s3_creds = JSON.parse(process.env.s3_creds)
        }
    }
    let s3_bucket
    if(s3_bucket == undefined){
        if (this_s3_creds.bucket != undefined){
            s3_bucket = this_s3_creds.bucket
        }
    }

    let collection 
    collection = load_local_collection(collection_path)
    let collection_type = typeof collection
    let collection_keys = Object.keys(collection)

    if (typeof collection == "string" || typeof collection == "list"){
        collection = {}
    }
    for (var i = 0; i < collection_keys.length; i++){
        let this_key = collection_keys[i]
        let this_key_type = typeof parseFloat(this_key)
        let this_key_value = parseFloat(this_key)
        if(typeof this_key_value >= 0 || this_key_type <= 0 ){
            delete(collection[this_key])
        }
    }

    if(Object.keys(generate).includes("id")){
        collection[generate.id] = manifest
    }
    else{
        try{
            delete(collection[undefined])
        }
        catch
        {
            console.log("cant delete undefined")
        }
    }
    if (!Object.keys(collection).includes("cache")){
        collection["cache"] = {}
    }
    collection["cache"]["local"] = collection_path
    collection["cache"]["s3"] = "s3://"+ s3_bucket + "/collection.json"
    collection["cache"]["ipfs"] = ""
    collection["cache"]["https"] = "https://huggingface.co/endomorphosis/cloudkit-collection/resolve/main/collection.json"
    let update_0
    let update_1
    let update_2
    let update_3
    let update_4

    try{
        update_0 = update_collection_ipfs(collection, collection_path)
    }
    catch(error){
        console.log("update_collection_ipfs failed")
        console.log(error)
    }
    try{
        update_1 = update_collection_local(collection, collection_path)
    }
    catch(error){
        console.log("update_collection_local failed")
        console.log(error)
    }
    try{
        update_2 = update_collection_s3(collection, collection_path, this_s3_creds)
    }
    catch(error){
        console.log("update_collection_s3 failed")
        console.log(error)
    }
    try{
        update_3 = update_collection_https(collection, collection_path)
    }
    catch(error){
        console.log("update_collection_https failed")
        console.log(error)
    }
    try{
        let mysql_update = update_collection_mysql(collection, collection_path, this_mysql_creds)
    }
    catch(error){
        console.log("update_collection_mysql failed")
        console.log(error)
    }
  

}


export function get_mysql_table(this_mysql_creds, table) {
    if (this_mysql_creds == undefined) {
        if (Object.keys(process.env).includes("mysql_creds")) {
            this_mysql_creds = JSON.parse(process.env.mysql_creds);
        }
    }
    let host = this_mysql_creds.host;
    let user = this_mysql_creds.user;
    let password = this_mysql_creds.password;
    let database = this_mysql_creds.database;

 
    var connection = new mysql({
        host: host,
        user: user,
        password: password,
        database: database
      });
    // Perform synchronous MySQL query
    const results = connection.query('SELECT * FROM ' + table);
    connection.dispose()
;

    return results
}


export function create_mysql_table_id(manifest, this_mysql_creds, table) {
    if (this_mysql_creds == undefined) {
        if (Object.keys(process.env).includes("mysql_creds")) {
            this_mysql_creds = JSON.parse(process.env.mysql_creds);
        }
    }
    let host = this_mysql_creds.host;
    let user = this_mysql_creds.user;
    let password = this_mysql_creds.password;
    let database = this_mysql_creds.database;
 
    var connection = new mysql({
        host: host,
        user: user,
        password: password,
        database: database
      });
    // Perform synchronous MySQL query
    let mysql_set_values = []
    if (!Object.keys(manifest).includes("key")){
        if(Object.keys(manifest).includes("id")){
            manifest["key"] = manifest.id
        }
    }

    for (var i = 0; i < Object.keys(manifest).length; i++){
        let insert_value = manifest[Object.keys(manifest)[i]]
        if (typeof insert_value == "string"){
            let test_json
            try {
                test_json = JSON.parse(insert_value)
            }
            catch{
                //console.log("not json")
            }
            finally{
                // prepare json for mysql insert and escape single and double quotes
                if(test_json != undefined && typeof test_json == "object"){
                    insert_value = JSON.parse(insert_value)
                    insert_value = JSON.stringify(insert_value)
                    insert_value = insert_value.replace(/'/g, "\\'")
                    insert_value = insert_value.replace(/"/g, '\\"')
                }
            }
            manifest[Object.keys(manifest)[i]] = insert_value

        }        
        mysql_set_values.push("`" + Object.keys(manifest)[i] + "` = \"" + manifest[Object.keys(manifest)[i]] + "\"")
    }
    let query = 'INSERT INTO ' + table + ' SET ' + mysql_set_values.join(", ");
    const results = connection.query(query);
    connection.dispose();
    return results
}

export function update_mysql_table_id(manifest, this_mysql_creds, table) {
    if (this_mysql_creds == undefined) {
        if (Object.keys(process.env).includes("mysql_creds")) {
            this_mysql_creds = JSON.parse(process.env.mysql_creds);
        }
    }
    let host = this_mysql_creds.host;
    let user = this_mysql_creds.user;
    let password = this_mysql_creds.password;
    let database = this_mysql_creds.database;
 
    var connection = new mysql({
        host: host,
        user: user,
        password: password,
        database: database
    });
    // Perform synchronous MySQL query
    let mysql_set_values = []

    for (var i = 0; i < Object.keys(manifest).length; i++){
        let insert_value = manifest[Object.keys(manifest)[i]]
        if (typeof insert_value == "string"){
            let test_json
            try {
                test_json = JSON.parse(insert_value)
            }
            catch{
                //console.log("not json")
            }
            finally{
                // prepare json for mysql insert and escape single and double quotes
                if(test_json != undefined && typeof test_json == "object"){
                    insert_value = JSON.parse(insert_value)
                    insert_value = JSON.stringify(insert_value)
                    insert_value = insert_value.replace(/'/g, "\\'")
                    insert_value = insert_value.replace(/"/g, '\\"')
                }
            }
            manifest[Object.keys(manifest)[i]] = insert_value

        }        
        mysql_set_values.push("`" + Object.keys(manifest)[i] + "` = \"" + manifest[Object.keys(manifest)[i]] + "\"")
    }

    let query = 'UPDATE ' + table + ' SET ' + mysql_set_values.join(", ") + ' WHERE `key` = \'' + manifest.id + "@" + manifest.format + '\'';
    const results = connection.query(query);
    //const results = connection.query('UPDATE ' + table + ' SET ' + mysql_set_values.join(", ") + ' WHERE id = ' + collection.id);
    connection.dispose()
;
    return results
}



export function collection_mysql_check(collection_model, mysql_model){
    let this_model = collection_model
    let this_model_serialized = collection_model
    this_model_serialized.hwRequirements = JSON.stringify(collection_model.hwRequirements)
    this_model_serialized.metadata = JSON.stringify(collection_model.metadata)
    this_model_serialized.folderData = JSON.stringify(collection_model.folderData)
    this_model_serialized.cache = JSON.stringify(collection_model.cache)
    this_model_serialized.skill = this_model.skill
    this_model_serialized.key = this_model.id

    let this_mysql_model_unserialized = mysql_model
    if(this_mysql_model_unserialized != undefined){
        this_mysql_model_unserialized.key = mysql_model.id
        if(this_mysql_model_unserialized.hwRequirements != undefined){
            if (typeof mysql_model.hwRequirements == "string"){
                this_mysql_model_unserialized.hwRequirements = JSON.parse(mysql_model.hwRequirements)
            }
            else{
                this_mysql_model_unserialized.hwRequirements = mysql_model.hwRequirements
            }
        }
        if(this_mysql_model_unserialized.metadata != undefined){
            if (typeof mysql_model.metadata == "string"){
                this_mysql_model_unserialized.metadata = JSON.parse(mysql_model.metadata)
            }
            else{
                this_mysql_model_unserialized.metadata = mysql_model.metadata
            }
        }
        if(this_mysql_model_unserialized.folderData != undefined){
            if (typeof mysql_model.folderData == "string"){
                this_mysql_model_unserialized.folderData = JSON.parse(mysql_model.folderData)
            }
            else{
                this_mysql_model_unserialized.folderData = mysql_model.folderData
            }
        }
        if(this_mysql_model_unserialized.cache != undefined){
            if (typeof mysql_model.cache == "string"){
                this_mysql_model_unserialized.cache = JSON.parse(mysql_model.cache)
            }
            else{
                this_mysql_model_unserialized.cache = mysql_model.cache
            }
        }
    }
    

    let this_mysql_model_serialized = JSON.stringify(mysql_model)
    let this_collection_model_serialized = JSON.stringify(this_model)
    let this_mysql_model_md5 = generate_md5(this_mysql_model_serialized)
    let this_collection_model_md5 = generate_md5(this_collection_model_serialized)
    if (this_collection_model_serialized != this_mysql_model_serialized || this_mysql_model_md5 != this_collection_model_md5){
        return false
    }
    else{
        return true
    }
    
}

export function update_collection_s3(collection, this_collection_path, this_s3_creds){
    let file_list = {}
    file_list[this_collection_path] = '/collection.json'
    let results
    try{
        results = upload_files_s3(file_list , this_s3_creds)
    }
    catch (error){
        console.log("upload_files_s3 failed")
        console.log(error)
    }
    finally{
        return results
    }
}

export function update_collection_https(collection, this_collection_path, this_hf_creds){

    if(this_hf_creds == undefined){
        this_hf_creds = hf_creds
    }

    if(this_collection_path == undefined){
        this_collection_path = collection_path
    }
    let https_path = "https://huggingface.co/" + this_hf_creds.account_name+"/cloudkit-collection/resolve/main/collection.json"
    let huggingface_collection = synchronousHttpGet(https_path).body.toString()
    let local_collection = fs.readFileSync(this_collection_path)
    local_collection = JSON.parse(local_collection)
    local_collection = JSON.stringify(local_collection)
    let local_collection_md5
    if (local_collection == undefined){
        local_collection_md5 = generate_md5(local_collection)
    }
    else{
        local_collection_md5 = generate_md5(JSON.stringify(collection))
    }
    let huggingface_collecion_md5 = generate_md5(huggingface_collection)
    let huggingface_collection_length = huggingface_collection.length
    let local_collection_length = local_collection.length

    if (huggingface_collecion_md5 != local_collection_md5 && huggingface_collection_length != local_collection_length){
        if(Object.keys(collection).includes("cache")){
            collection["cache"]["https"] = https_path
        }
        else{
            collection["cache"] = {}
            collection["cache"]["https"] = https_path
        }
        let executable_path = path.join(cwd,"huggingface")
        executable_path = path.join(executable_path, "huggingface_hub_upload.py")

        let folder_path = path.dirname(this_collection_path)
        let repo_name = "cloudkit-collection"
        let hf_username = this_hf_creds.account_name
        let hf_token = this_hf_creds.user_key
        let this_organization = this_hf_creds.org_name

        let args = [folder_path, repo_name, hf_username, hf_token, this_organization]

        let command_1 = "python " + executable_path + " " + args.join(" ")
        console.log("command_1: " + command_1)
        let results_1
        try{
            results_1 = child_process.execSync(command_1, {stdio: 'ignore'})
        }
        catch(error){
            console.log("command_1 failed")
            console.log(command_1)
            console.log(error)
        }
        finally{
            return results_1
        }
    }
    else{
        console.log("huggingface collection.json is the same")
    }
}

export function update_collection_local(collection, this_collection_path){
    let old_collection = JSON.parse(fs.readFileSync(this_collection_path))
    if(this_collection_path == undefined){
        this_collection_path = collection_path
    }
    let new_collection = {}
    let collection_keys = Object.keys(old_collection)
    for(var i = 0; i < collection_keys.length; i++){
        let this_key = collection_keys[i]
        new_collection[this_key] = collection[this_key]
    }
    for(var i = 0; i < Object.keys(collection).length; i++){
        let this_key = Object.keys(collection)[i]
        new_collection[this_key] = collection[this_key]
    }
    fs.writeFileSync(this_collection_path, JSON.stringify(collection))
    return new_collection
}

export function update_collection_ipfs(collection, this_collection_path){
    let this_collection_ipfs
    if(this_collection_path == undefined){
        this_collection_path = collection_path
    }
    let command_1 = "ipfs add -r " + this_collection_path 
    let results_1
    try{
        results_1 = child_process.execSync(command_1)
    }
    catch(error){
        console.log("ipfs add failed")
        console.log(command_1)
        console.log(error)
    }
    finally{
        results_1 = results_1
        if (results_1 != undefined){
            console.log("results_1: ", results_1.toString())
            console.log("ipfs add succeeded")
            results_1 = results_1.toString().split("\n")

            let results_matrix = []
            for(var i = 0; i < results_1.length; i++){
                results_matrix.push(results_1[i].split(" "))
            }
            if (results_matrix.length = 2){
                this_collection_ipfs = results_matrix[results_matrix.length - 2][1]
            }
            let metadata = ["path=/collection.json"]
            let argstring = ""
            for (var i = 0; i < metadata.length; i++){
                argstring = argstring + "  " + metadata[i]
            }
            let command_2 = "ipfs-cluster-ctl pin add " + this_collection_ipfs + argstring
            let results_2 = child_process.execSync(command_2)

            if(Object.keys(collection).includes("cache")){
                collection["cache"]["ipfs"] = this_collection_ipfs
            }
            else{
                collection["cache"] = {}
                collection["cache"]["ipfs"] = this_collection_ipfs
            }
            return this_collection_ipfs
        }
        return false
    }
    return false
}

export function update_collection_mysql(collection, this_collection_path, this_mysql_creds) {
    if (this_mysql_creds == undefined) {
        if (Object.keys(process.env).includes("mysql_creds")) {
            this_mysql_creds = JSON.parse(process.env.mysql_creds);
        }
    }

    let host = this_mysql_creds.host;
    let user = this_mysql_creds.user;
    let password = this_mysql_creds.password;
    let database = this_mysql_creds.database;
    let this_registry = registry({
        host: host,
        user: user,
        password: password,
        database: database
    });
    delete collection.cache;
    let collection_keys = Object.keys(collection);
    let promises = [];

    let mysql_models = get_mysql_table(this_mysql_creds, "Checkpoint")
    let this_mysql_models = {}
    
    mysql_models.map((model) => {
        let this_model = model
        delete this_model.key
        this_mysql_models[this_model.id] = this_model
    })

    for (let model of collection_keys) {
        let this_model = collection[model];
        let this_model_collection = collection[model];
        let this_model_mysql = this_mysql_models[model];
        if (this_model_mysql != undefined){
        let check_same = collection_mysql_check(this_model_collection, this_model_mysql);
            if (check_same == false) {
                //this_model_collection.skill = this_model_mysql.skill
                this_model_collection.key = this_model_collection.id + "@" + this_model_collection.format;
                if (typeof this_model_collection.hwRequirements != "string"){
                    this_model_collection.hwRequirements = JSON.stringify(this_model_collection.hwRequirements);
                }
                if (typeof this_model_collection.metadata != "string"){
                    this_model_collection.metadata = JSON.stringify(this_model_collection.metadata);
                }
                if (typeof this_model_collection.folderData != "string"){
                    this_model_collection.folderData = JSON.stringify(this_model_collection.folderData);
                }
                if (typeof this_model_collection.cache != "string"){
                    this_model_collection.cache = JSON.stringify(this_model_collection.cache);
                }

                if (this_model_mysql != undefined){
                    delete this_model_mysql.key;
                    delete this_model_collection.location
            
                    if (!Object.keys(this_model_collection).includes("local")) {
                        update_mysql_table_id(this_model_collection, this_mysql_creds, "Checkpoint")
                    }
                    else {
                        console.log("not updating cache data");
                    }
                }
            }
        }
        else{
            this_model_collection.key = this_model_collection.id;
            if (typeof this_model_collection.hwRequirements != "string"){
                this_model_collection.hwRequirements = JSON.stringify(this_model_collection.hwRequirements);
            }
            if (typeof this_model_collection.metadata != "string"){
                this_model_collection.metadata = JSON.stringify(this_model_collection.metadata);
            }
            if (typeof this_model_collection.folderData != "string"){
                this_model_collection.folderData = JSON.stringify(this_model_collection.folderData);
            }
            if (typeof this_model_collection.cache != "string"){
                this_model_collection.cache = JSON.stringify(this_model_collection.cache);
            }
            if (Object.keys(this_model_collection).includes("location")) {
                delete this_model_collection.location 
            }
            if (!Object.keys(this_model_collection).includes("local")) {
                create_mysql_table_id(this_model_collection, this_mysql_creds, "Checkpoint")
            }
            else{
                console.log("not updating cache data")
            }
        }
    }
    return mysql_models
}


export function update_collection_mysql_bak(collection, this_collection_path, this_mysql_creds) {
    if (this_mysql_creds == undefined) {
        if (Object.keys(process.env).includes("mysql_creds")) {
            this_mysql_creds = JSON.parse(process.env.mysql_creds);
        }
    }

    let host = this_mysql_creds.host;
    let user = this_mysql_creds.user;
    let password = this_mysql_creds.password;
    let database = this_mysql_creds.database;
    let this_registry = registry({
        host: host,
        user: user,
        password: password,
        database: database
    });
    delete collection.cache;
    let collection_keys = Object.keys(collection);
    let promises = [];

    for (let model of collection_keys) {
        let this_model_collection = collection[model];
        let keyfound = false;

        promises.push(
            this_registry.models().then(models => {
                for (let this_model_mysql of models) {
                    if (this_model_mysql.key == model) {
                        keyfound = true;
                        let check_same = collection_mysql_check(this_model_collection, this_model_mysql);
                        if (check_same == false) {
                            this_model_collection.key = this_model_collection.id;
                            this_model_collection.hwRequirements = JSON.stringify(this_model_collection.hwRequirements);
                            this_model_collection.metadata = JSON.stringify(this_model_collection.metadata);
                            this_model_collection.folderData = JSON.stringify(this_model_collection.folderData);
                            this_model_collection.cache = JSON.stringify(this_model_collection.cache);

                            if (!Object.keys(this_model_collection).includes("local")) {
                                return this_registry.updateModel(this_model_collection).then(result => {
                                    console.log("updated cache data");
                                });
                            } else {
                                console.log("not updating cache data");
                            }
                        }
                    }
                }

                if (keyfound == false) {
                    this_model_collection.key = this_model_collection.id;
                    this_model_collection.hwRequirements = JSON.stringify(this_model_collection.hwRequirements);
                    this_model_collection.metadata = JSON.stringify(this_model_collection.metadata);
                    this_model_collection.folderData = JSON.stringify(this_model_collection.folderData);
                    this_model_collection.cache = JSON.stringify(this_model_collection.cache);

                    if (!Object.keys(this_model_collection).includes("local")) {
                        return this_registry.updateModel(this_model_collection).then(result => {
                            console.log("updating cache data");
                        });
                    } else {
                        console.log("not updating cache data");
                    }
                }

                console.log("model: " + model);
                return Promise.resolve(); // Resolve the promise for the current model
            })
        );
    }

    return Promise.all(promises)
        .then(() => {
            console.log("All models updated or created successfully");
            return true;
        })
        .catch(error => {
            console.log(error);
            return false;
        });
    
}

export function export_cache_locations( manifest, generate, file_dict){
    let cache = {}
    cache["ipfs"] = {}
    cache["s3"] = {}
    cache["local"] = {}
    cache["https"] = {}

    let https = {}
    let ipfs = {}
    let s3 = {}
    let local = {}

    for(var i = 0; i < Object.keys(file_dict).length; i++){
        let this_file = Object.keys(file_dict)[i]
        let this_md5 = file_dict[this_file].md5
        let this_size = file_dict[this_file].size
        let this_url
        let s3_creds = JSON.parse(process.env.s3_creds)
        console.log("s3_creds: ", s3_creds)
        let s3_bucket = JSON.parse(process.env.s3_creds)["bucket"]

        if (generate.converted == true ){
            this_url = "https://huggingface.co/endomorphosis/" + generate.id + "/resolve/main/" + this_file
        }
        else{
            this_url = manifest.source + "/resolve/main/" + this_file.replace("/","")
        }
        let this_local
        if (generate.quantization != undefined){
            this_local = generate.id + "-" + generate.quantization + this_file
        }
        else{
            this_local = generate.id + this_file
        }
        let this_s3
        if (generate.quantization != undefined){
            this_s3 = "s3://" + s3_bucket + "/" + generate.id + "/" + this_file.replace("/","")
        }
        else{
            this_s3 = "s3://" + s3_bucket + "/" + generate.id + "/" + this_file.replace("/","")
        }
        https[this_file] = {"path": this_file, "url": this_url}
        local[this_file] = {"path": this_file, "url": this_local}
        s3[this_file] = {"path": this_file , "url": this_s3}
    }

    cache["https"] = https
    cache["local"] = local
    cache["s3"] = s3
    manifest.cache = cache
    return manifest.cache
}


export function upload_manifest_files_s3(manifest, generate, file_list, this_s3_creds) {
    if (this_s3_creds == undefined) {
        //check for global s3 creds
        if(Object.keys(process.env).includes("s3_creds")){
            this_s3_creds = JSON.parse(process.env.s3_creds)
        }
    }

    let files 
    let new_files = {}

    if(file_list != undefined){
        files = file_list
    }else if (Object.keys(manifest).includes("folderData")){
        let build_dir = generate.build_path
        files = manifest.folderData
        let file_keys = Object.keys(files)
        let relative_path = path.dirname(build_dir)
        relative_path = build_dir.replace(relative_path, "")
        for(var this_file in file_keys){
            let filename = file_keys[this_file]
            let filekey = path.join(build_dir, filename)
            if(fs.existsSync(filekey)){
                new_files[filekey] = relative_path + filename
            }
        }

        files = new_files
    }
    if(this_s3_creds == undefined){
        return true
    }
    else{
        return upload_files_s3(files, this_s3_creds)
    }
}


export function upload_manifest_files_local(manifest, generate, dest_path){
    let files = manifest.folderData
    let build_path = generate.build_path
    build_path = path.dirname(build_path)

    if(dest_path == undefined){
        dest_path = local_model_path
    }
    if( path.resolve(build_path) != path.resolve(dest_path)){
        for(var file in Object.keys(files)){
            var file = Object.keys(files)[file]
            let relativePath = path.relative(generate.build_path, file)
            let fileKey
            if(generate.modelName != undefined){
                fileKey = generate.modelName
                if (generate.quantization != undefined){
                    fileKey = fileKey + "-" + generate.quantization
                }
                if (generate.format != undefined){
                    //fileKey = fileKey + "@" + generate.format
                }
                fileKey = fileKey + "/" + file
            }
            else{
                fileKey = generate.id
            }

            let destKey = path.join(dest_path, fileKey)
            let buildKey = path.join(build_path, fileKey).replace("@", "\@")

            buildKey = path.resolve(buildKey)

            if (!fs.existsSync(path.dirname(destKey))){
                fs.mkdirSync(path.dirname(destKey))
            }

            if(!fs.existsSync('/tmp/build')){
                fs.mkdirSync('/tmp/build')
            }

            try{
                if(path.resolve(buildKey) != path.resolve(build_path) && buildKey != destKey ){
                    //fs.copyFileSync(buildKey, destKey)
                    console.log(`uploading ${buildKey} to ${destKey}`)
                    child_process.execSync(`cp -rf ${buildKey} ${destKey}`)
                }
            }
            catch(error){
                console.log(error)
                throw error
            }

        }
    }
    return manifest
}


export function upload_manifest_files_hf(manifest,  generate, this_hf_creds){
    if(this_hf_creds == undefined){
        this_hf_creds = hf_creds
    }

    console.log("upload_manifest_files_hf")
    let executable_path = path.join(cwd,"huggingface")
    executable_path = path.join(executable_path, "huggingface_hub_upload.py")
    let foldername = path.basename(generate.build_path)
    let folder_path = path.join(local_model_path, foldername)
    let repo_name = generate.id
    let hf_username = this_hf_creds.account_name
    let hf_token = this_hf_creds.user_key
    let this_organization = this_hf_creds.org_name

    let args = [folder_path, repo_name, hf_username, hf_token, this_organization]

    let command_1 = "python " + executable_path + " " + args.join(" ")
    console.log("command_1: " + command_1)
    let results_1 = child_process.execSync(command_1, {stdio: 'ignore'})
}


export function upload_manifest_files_ipfs(manifest, generate, ipfsCluster){
    let ipfs = {}
    if(ipfsCluster.active_models.includes(manifest.id) == false || Object.keys(manifest.cache.ipfs) == 0){
        let command1 = "cd " + generate.build_path + " ; ipfs add -r " + generate.build_path + "/ --progress=false"
        console.log("command1: " + command1)
        let results1
        try{
            results1 = child_process.execSync(command1)
            console.log("results 1: " + results1)
        }
        catch(error){
            console.log("ipfs add failed")
            console.log(command1)
            console.log(error)
        }
        finally{
            results1 = results1.toString().split("\n")
            console.log("results1: " + results1)
            console.log("ipfs add succeeded")
        }
        let results_matrix = []
        for(var i = 0; i < results1.length; i++){
            results_matrix.push(results1[i].split(" "))
        }
        let results_files = {}
        let results_files2 = {}
        let model_folder = generate.build_path.replace(path.dirname(generate.build_path), "")
        for (var results_list in results_matrix){
            let this_list = results_matrix[results_list]
            if (this_list.length > 2){
                let this_key = this_list[2]
                if(this_key != undefined){
                    this_key = "/" + this_key.replace(model_folder.replace("/",""), "").replace("/","")
                }
                results_files[this_key] =  this_list[1]
            }
        }
        let metadata = {}
        // console.log("manifest.folderData")
        // console.log(manifest.folderData)
        // console.log("manifest.cache")
        // console.log(manifest.cache)
        for (var file in Object.keys(manifest.folderData)){
            let this_file = Object.keys(manifest.folderData)[file]
            if (Object.keys(results_files).includes(this_file)){
                let this_ipfs = results_files[this_file]
                let this_url = "https://ipfs.io/ipfs/" + this_ipfs
                metadata[this_file] = "path=" + manifest.cache.local[this_file]["url"]
                ipfs[this_file] = { "path" : this_ipfs, "url": this_url}
            }
        }
        manifest.cache["ipfs"] = ipfs

        let command2 = "ipfs-cluster-ctl pin add "

        let file_structure = manifest.folderData
        for (var file in manifest.folderData){
            let this_file = manifest.folderData[file]
            let this_ipfs = manifest.cache["ipfs"][file]["path"]
            let argstring = ""
            if(Object.keys(metadata).includes(file)){
                    argstring = argstring + " --metadata " + metadata[file]
            }
            let this_command = command2 + this_ipfs + argstring
            console.log("this_command: " + this_command)
            let this_command_process = child_process.execSync(this_command, { stdio: 'ignore' })
        }
        return manifest
    }
    else{
        console.log("either ipfs is empty or ipfs cache address is missing")
        let collection = load_local_collection(collection_path)
        let this_manifest = collection[generate.id]
        let this_manifest_cache = this_manifest.cache
        let this_manifest_cache_ipfs = this_manifest_cache.ipfs
        manifest.cache["ipfs"] = this_manifest_cache_ipfs
    }
}

export function upload_manifest_files(manifest, generate, local_path, ipfsCluster){
    if(local_path == undefined){
        local_path = local_model_path
    }
    let test
    try{
        console.log("ipfs")
        let ipfs_upload = upload_manifest_files_ipfs(manifest, generate, ipfsCluster)
    }
    catch(error){
        console.log("ipfs upload failed")
        throw error
    }
    try{
        let s3_upload = upload_manifest_files_s3(manifest, generate)
    }
    catch(error){
        console.log("s3 upload failed")
        throw error
    }
    try{
        let local_upload = upload_manifest_files_local(manifest, generate, local_path)
    }
    catch(error){
        console.log("local upload failed")
        throw error
    }
    try{
        if (!generate.source.includes("huggingface.co") || generate.converted == true){
            let hf_upload = upload_manifest_files_hf(manifest, generate)
        }
    }
    catch(error){
        console.log("hf upload failed")
        throw error
    }
    if(generate.build_path != generate.destPath){
        let rm_command = "rm -rf " + generate.build_path
        console.log("rm_command: " + rm_command)
        let rm_results
        try{
            rm_results = child_process.execSync(rm_command)
        }
        catch(error){
            console.log("rm failed")
            console.log(error)
        }
        finally{
            console.log("rm succeeded")
        }
    }

    return manifest
}

export function import_hf(generate, manifest, build_path){
    console.log("import_hf")
    console.log("generate: ")
    console.log(generate)

    let source_path = generate.source
    let dest_path = build_path
    console.log("build_path: " + build_path)
    if (build_path == undefined){
        build_path = "/tmp/build/" + generate.id + "/"
    }
    build_path = path.resolve(build_path)
    let readme_source
    let file_structure = []
    let tree_source
    let canonincal_source
    let config_source
    let blob_source 

    if(source_path.includes("tree/main")){
        canonincal_source = dest_source.split("tree/main")[0]
        files_source = dest_souce

    }
    else if (source_path.includes("blob/main")){
        canonincal_source = dest_source.split("blob/main")[0]
        tree_source = dest_source.split("blob/main")[0] + "tree/main"
    }
    else{
        canonincal_source = source_path
        tree_source = source_path + "tree/main"
    }
    let hf_model_uuid = canonincal_source.replace("https://huggingface.co/", "")
    let hf_username = hf_model_uuid.split("/")[0]
    let hf_model_name = hf_model_uuid.split("/")[1]

    let formats = [hf_model_name, generate.id ]
    if(hf_model_name != undefined){
        generate.id = hf_model_name
    }
    if(generate.quantization != undefined){
        generate.id = generate.id + "-" + generate.quantization
    }
    build_path = "/tmp/build/" + generate.id 
    let clone_path = "/tmp/build/" + hf_model_name
    //if(generate.format != undefined){
    //    build_path = build_path + "@" + generate.format + "/" 
    //}
    generate.build_path = build_path

    blob_source = canonincal_source + "/blob/main/"
    readme_source = canonincal_source + "/blob/main/README.md"
    config_source = canonincal_source + "/blob/main/config.json"
    let resolve_main = canonincal_source + "/resolve/main/"
    let manifest_path = path.join( build_path , 'manifest.json')

    file_structure.push("/")

    let get_tree_https = synchronousHttpGet(tree_source)
    let get_readme_https = synchronousHttpGet(readme_source)
    let get_config_https = synchronousHttpGet(config_source)
    if (generate.format == "ggml" | generate.format == "gguf"){
        let command_1 = 'git lfs install --skip-smudge ; git clone --depth 1 '
        let command_2 = 'git config --global --add safe.directory \'*\' ; git ls-files'
        let command_3 = 'rm -rf ' + build_path + '/*'
        if (!fs.existsSync("/tmp/build/")){
            child_process.execSync("mkdir /tmp/build")
        }
        if (fs.existsSync(build_path)){
            child_process.execSync("rm -rf "+ build_path)
            fs.mkdirSync(build_path)
            fs.writeFileSync(manifest_path, JSON.stringify(manifest))
        }
        if (!fs.existsSync(clone_path)){
            //console.log("/tmp/build/" + hf_model_name)
            console.log("cd " + "/tmp/build/ ; " + command_1 + canonincal_source  )
            let results_1
            try{
                let results_1 = child_process.execSync("cd " + "/tmp/build/ ; " + command_1 + canonincal_source )
            }
            catch(error){
                console.log("command_1 failed")
                console.log(command_1)
                console.log(error)
            }
            finally{
                if(results_1 != undefined){
                    results_1 =  results_1.toString()
                }
            }
        }
        let results_2
        try{
            results_2 = child_process.execSync("cd " + clone_path + "/ ; " + command_2)
        }
        catch{
            console.log("command_2 failed")
            console.log(command_2)
            console.log(error)
        }
        finally{
            results_2 = results_2.toString()
        }
        let results_3
        try{
            results_3 = child_process.execSync("cd /tmp/build/" + hf_model_name + "/ ; " + command_3)
        }
        catch(error){
            console.log("command_3 failed")
            console.log(command_3)
            console.log(error)
        }
        finally{
            results_3 = results_3.toString()
        }
        fs.writeFileSync(manifest_path, JSON.stringify(manifest))
        let tree_files2 = results_2.split("\n")
        let filter_files = tree_files2

        if (generate.quantization != undefined && (generate.format == "gguf" || generate.format == "ggml")){
            filter_files = filter_files.filter(function (el) {
                return (el.includes(generate.quantization) || el.includes(generate.quantization.toUpperCase()) || el.includes(generate.quantization.toLowerCase())); 
            })
        }

        if (generate.format == "gguf" || generate.format == "ggml"){
            filter_files = filter_files.filter(function (el) {
                return (el.includes(generate.format) || el.includes(generate.format.toUpperCase()) || el.includes(generate.format.toLowerCase()));
            })
        }
        else if(generate.format == "llama_fp32" || generate.format == "llama_fp16"){  
            console.log()
        }
        if (!fs.existsSync(build_path)){
            fs.mkdirSync(build_path)
        }
        let tree_objects = {}
        for( var i = 0; i < filter_files.length; i++){
            tree_objects[filter_files[i]] = resolve_main + filter_files[i]
        }
        let tree_file_names = Object.keys(tree_objects)
        for(var i = 0; i < tree_file_names.length; i++){
            file_structure.push("/" + tree_file_names[i])
            let this_download_url = tree_objects[tree_file_names[i]]
            let this_dest_path = path.join(build_path, tree_file_names[i])
            let this_command = "wget -O " + this_dest_path + " " + this_download_url 
            console.log("this_command: " + this_command )
            let this_command_process = child_process.execSync(this_command, { stdio: 'ignore' })
        }
        let this_download_url
        let this_dest_path
        let this_command
        let this_command_process
        if(tree_files2.includes("README.md")){
            try{
                this_download_url = readme_source
                this_dest_path = path.join(build_path, "/README.md")
                this_command = "wget -O " + this_dest_path + " " + this_download_url
                console.log("this_command: " + this_command )
                this_command_process = child_process.execSync(this_command, { stdio: 'ignore' })
            }
            catch(error){
                console.log ("no readme")
                console.log(error)
            }
            finally{
                file_structure.push("/README.md")
                tree_objects["/README.md"] = readme_source
                tree_file_names.push("/README.md")
            }
        }
        if(tree_files2.includes("config.json")){
            try{
                this_download_url = config_source
                this_dest_path = build_path + "config.json"
                this_command = "wget -O " + this_dest_path + " " + this_download_url
                console.log("this_command: " + this_command )
                this_command_process = child_process.execSync(this_command, { stdio: 'ignore' })
            }
            catch(error){
                console.log ("no readme")
                console.log(error)
            }    
            finally{
                file_structure.push("/config.json")
                tree_objects["/README.md"] = readme_source
                tree_file_names.push("/config.json")
            }
        }
        manifest.metadata.folderData = folder_data(generate, manifest , build_path)
        console.log("tree_objects: " + JSON.stringify(tree_objects))
        console.log(manifest.metadata.folderData)
        let command_4 = "rm -rf " + clone_path
        console.log("command_4: " + command_4)  
        let results_4
        try {
            results_4 = child_process.execSync(command_4)
        }catch(error){
            console.log("command_4 failed")
            console.log(command_4)
            console.log(error)
        }
        finally{
            results_4 = results_4.toString()
        }
    }
    else if(generate.format == "llama_fp32" || generate.format == "llama_fp16" || generate.format == "hf" || generate.format == "fp16" || generate.format == "fp32"){
        let command_1 = 'git lfs install ; git clone --depth 1 '
        let command_2 = 'git config --global --add safe.directory \'*\' ; git ls-files'
        let build_path = "/tmp/build/" + hf_model_name 
        //generate.build_path = build_path

        if (fs.existsSync(build_path)){
            child_process.execSync("rm -rf " + build_path)
        }
        if (!fs.existsSync(build_path)){
            console.log("cd " + "/tmp/build/ ; " + command_1 + canonincal_source )
            let results_1
            try{
                results_1 = child_process.execSync("cd " + "/tmp/build/ ; " + command_1 + canonincal_source )
            }
            catch(error){
                console.log("command_1 failed")
                console.log(command_1)
                console.log(error)
            }
            finally{
                results_1 =  results_1.toString()
            }
        }
        let results_2
        try{
            results_2 = child_process.execSync("cd " + clone_path + " ; " + command_2)
        }
        catch(error){
            console.log("command_2 failed")
            console.log(command_2)
            console.log(error)
        }
        finally{
            console.log("command_2: cd " + clone_path + " ; " + command_2)
            results_2 = results_2.toString()
            results_2 = results_2.split("\n")
        }
        for(var files in results_2){
            let this_file = "/" + results_2[files]
            file_structure.push(this_file)
        }
        if (clone_path != build_path){
            if (!fs.existsSync(build_path)){
                fs.mkdirSync(build_path)
            }

            let command_3 = "mv " + clone_path + "/* " + build_path + "/; rm -rf " + clone_path  
            console.log("command_3: " + command_3)
            let results_3
            try{
                results_3 = child_process.execSync(command_3)
            }
            catch(error){
                console.log("command_3 failed")
                console.log(command_3)
                console.log(error)
            }
            finally{
                results_3 = results_3.toString()
            }    
        }
    }
    if(!fs.existsSync(build_path)){
        fs.mkdirSync(build_path)
    }

    manifest.folderData = folder_data(manifest, generate, build_path)
    manifest_path = path.join( build_path , 'manifest.json')
    fs.writeFileSync(manifest_path, JSON.stringify(manifest))
    return file_structure
}

export function import_civitai(generate, manifest, build_path){
    let source_path = generate.source
    let dest_path = build_path
    // detect if file or directory
    if (fs.existsDir(source_path)){
        // copy directory
        fs.copyDir(source_path, dest_path)
    }
    else{
        // copy file
        fs.copyFile(source_path, dest_path)
    }
    // write manifest as json
    let manifest_path = build_path + 'manifest.json'
    fs.writeFileSync(manifest_path, JSON.stringify(manifest))
}

export function import_local(generate, manifest, build_path){
    let source_path = generate.source
    let dest_path = build_path
    let file_structure = []
    // detect if file or directory
    if (fs.existsDir(source_path)){
        // copy directory
        file_structure.push("/")
        fs.copyDir(source_path, dest_path)
        let this_directory_tree = fs.walkDir(source_path)
        for(var i = 0; i < this_directory_tree.length; i++){
            file_structure.push(this_directory_tree[i])
        }
    }
    else{
        // copy file
        fs.copyFile(source_path, dest_path)
        file_structure.push("/")
        file_structure.push("/" + dest_path)
    }

    if (!fs.existsSync(build_path + "README.md")){
        fs.writeFileSync(build_path + "README.md", generate_readme(generate, manifest))
    }
    file_structure.push("README.md")
    if(fs.existsSync(build_path + "config.json")){
        file_structure.push("/config.json")
    }
    file_structure.push("/manifest.json")
    let manifest_path = build_path + 'manifest.json'
    let folderDict = {}
    for (var i = 0; i < file_structure.length; i++){
        let this_file = file_structure[i]
        let this_md5 = generate_md5(this_file, build_path)
        let this_size = fs.statSync(path.join(build_path,this_file)).size
        folderDict[this_file] = {"md5": this_md5, "size": this_size}
    }

    manifest.metadata.folderData = folderDict
    fs.writeFileSync(manifest_path, JSON.stringify(manifest))
    return file_structure
}

export function import_s3(generate, manifest, build_path, s3bucket_name, secret_key, access_key, hostname){
    let source_path = generate.source
    let dest_path = build_path
    // detect if file or directory
    if (fs.existsDir(source_path)){
        // copy directory
        fs.copyDir(source_path, dest_path)
    }
    else{
        // copy file
        fs.copyFile(source_path, dest_path)
    }
    // write manifest as json
    let manifest_path = build_path + 'manifest.json'
    fs.writeFileSync(manifest_path, JSON.stringify(manifest))     
}


export function generate_file_list(generate, manifest, file_list){
    let this_path
    let file_dict = {}
    if(generate.build_path != undefined){
        this_path = generate.build_path
    }

    for(var i =  0; i < file_list.length; i++){
        file_dict[file_list[i]] = {"md5": generate_md5(file_list[i], this_path), "size": fs.statSync(path.join(this_path,file_list[i])).size}
    }
    manifest.folderData = file_dict
    return file_dict
}

export function import_source(generate, manifest, collection){
    console.log("import source")
    console.log("generate")
    console.log(generate)
    console.log("manifest")
    console.log(manifest)
    console.log("collection")
    console.log(Object.keys(collection))

    let check_id = generate.id
    let check_pass = true
    let destPath = generate.destPath
    let collection_keys = Object.keys(collection)
    if (Object.keys(collection).includes(check_id)){
        let check_folder = collection[check_id].folderData
        let check_folder_keys = Object.keys(check_folder)
        for( var i = 0; i < check_folder_keys.length; i++){
            let this_file = check_folder_keys[i]
            let this_file_path = path.join(destPath, this_file)
            if(fs.existsSync(this_file_path)){
                let this_file_size = fs.statSync(this_file_path).size
                let check_folder_size = check_folder[this_file].size
                if(!this_file.includes("manifest.json")){
                    if (this_file_size != check_folder_size){
                        check_pass = false
                    }    
                }
            }else{
                check_pass = false
            }
        }
    }
    else{
        check_pass = false
    }
    // force import
    // TODO: add fix this logic when prompting.
    check_pass = false
    if (check_pass == false){
        if (generate.id == undefined){
            if (generate.modelName != undefined){
                if (generate.quantization != undefined && generate.quantization != "none" && generate.quantization != undefined){
                    generate.id = generate.modelName + "-" + generate.parameters + "-" + generate.quantization
                }
                else{
                    if (generate.parameters != undefined){
                        generate.id = generate.modelName + "-" + generate.parameters
                    }
                    else if(generate.quantization != undefined && generate.quantization != "none"){
                        generate.id = generate.modelName + "-" + generate.quantization 
                    }
                }
            }
            else{
                console.log(generate)

                throw("generate.id is undefined and generate.modelName is undefined")
            }
        }
        let build_path = "/tmp/build/" + generate.id
        if (generate.format != undefined){
            //build_path = build_path + "@" + generate.format
        }
        build_path = build_path + "/"
        generate.build_path = build_path
        if (generate.location == 'local'){
            import_local(generate, manifest, build_path)
        }
        if (generate.location == 's3'){
            import_s3(generate, manifest, build_path)
        }
        if (generate.location == 'huggingface'){
            import_hf(generate, manifest, build_path)
        }
        if (generate.location == 'civitai'){
            import_civitai(generate, manifest, build_path)
        }
        return build_path
    }
    else{
        generate.build_path = generate.destPath
        return true
    }
}


export function package_model_data(generate, manifest, collection){
    let this_path = import_source(generate, manifest, collection)
    //let this_path = path.join("/tmp/build",generate.modelName)
    //generate.build_path = this_path + "-" + generate.quantization + "@" + "gguf"
    let file_list = [] 
    let converted_list = convert_model(generate, manifest, this_path)
    file_list = file_list.concat(converted_list)
    //let file_list = ["/README.md", "/cinematika-7b-v0.1-Q4_K_M.gguf", "/manifest.json", "/"]
    let readme_path = path.join(generate.build_path, "README.md")
    if (!fs.existsSync(readme_path)){
        let readme = generate_readme(generate, manifest)
        if(readme != undefined){
            fs.writeFileSync(readme_path, readme)
        }
    }
    else{
        if (fs.statSync(readme_path).size < 8){
            let readme = generate_readme(generate, manifest)
            fs.writeFileSync(readme_path, readme)    
        }
    }
    file_list.push("/README.md")
    let file_dict = generate_file_list(generate, manifest, file_list)
    return file_dict
}

