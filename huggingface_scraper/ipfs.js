import fs from 'fs'
import path from 'path'
import child_process, { exec } from 'child_process'

export class ipfsClusterCtl {
    constructor(){
        this.pinset = get_pinset()
        this.exec = {}
        this.stats = {}
        this.queue = []
    }

    main(){
        return this
    }

    check_collection(collection){
        let status = {}
        let collection_keys = Object.keys(collection)
        let pinset_keys = Object.keys(this.pinset)
        let orphan_models = []
        let orphan_pins = []
        let active_pins = []
        let active_models = []
        for(var i = 0; i < collection_keys.length; i++){
            let this_model = collection_keys[i]
            if(this_model != "cache"){
                let this_manifest = collection[this_model]
                let this_id = this_manifest.id
                let this_cache = this_manifest.cache
                let this_ipfs_cache = this_cache.ipfs
                let this_ipfs_cache_keys = Object.keys(this_ipfs_cache)
                let found_all = true
                for (var j = 0; j < this_ipfs_cache_keys.length ; j++){
                    let this_cache_basename = this_ipfs_cache_keys[j]
                    let this_cache_item = this_ipfs_cache[this_cache_basename]
                    let this_cache_item_path = this_cache_item.path
                    let this_cache_item_url = this_cache_item.url
                    if(pinset_keys.includes(this_cache_item_path)){
                        active_pins.push(this_cache_item_path)
                    }
                    else{
                        found_all = false
                    }
                }
                if (found_all == true){
                    active_models.push(this_model)
                }
                else{
                    orphan_models.push(this_model)
                }
            }
        }

        for (var i = 0; i < pinset_keys.length; i++){
            let this_pin = pinset_keys[i]
            if(active_pins.includes(this_pin)){
                //pass
            }   
            else{
                orphan_pins.push(this_pin)
            }
        }

        status["orphan_models"] = orphan_models
        status["orphan_pins"] = orphan_pins
        status["active_pins"] = active_pins
        status["active_models"] = active_models

        return status
    }

    execute(args){
        let command
        let executable = "ipfs-cluster-ctl "

        let options = ["add", "pin", "unpin", "status", "sync", "pinset"]

        if (args.command == "add"){
            command = executable + "add " + args.file
        }

        if (args.command == "pin"){
            command = executable + "pin add " + args.hash
        }

        if (args.command == "unpin"){
            command = executable + "pin rm " + args.hash
        }

        if (args.command == "status"){
            command = executable + "status " + args.hash
        }

        if (args.command == "sync"){
            command = executable + "sync " + args.hash
        }

        if (args.command == "pinset"){
            command = executable + "pin ls " + args.hash
        }

        if (options.includes(args.command)){
            this.exec = command
            child_process.execSync(command, (error, stdout, stderr) => {
                    if (error) {
                        console.log(`error: ${error.message}`);
                        return;
                    }
                    if (stderr) {
                        console.log(`stderr: ${stderr}`);
                        return;
                    }
                    console.log(`stdout: ${stdout}`);
                }
            )
            return this
        }
        else{
            console.log("command not found")
            return this
        }
    }

}



export function get_pinset(){

    let pinset_file = "/tmp/build/ipfs_pinset.txt"
    let pinset_file_mtime = 0
    if(fs.existsSync(pinset_file)){
        pinset_file_mtime = fs.statSync(pinset_file).mtimeMs
    }
    let now = Date.now()
    let ten_minutes_ago  = now - 600000

    let command = "ipfs-cluster-ctl pin ls > /tmp/build/ipfs_pinset.txt"
    let results
    try{
        if(pinset_file_mtime < ten_minutes_ago){
            results = child_process.execSync(command)
        }
        results = fs.readFileSync("/tmp/build/ipfs_pinset.txt")
        //let command_2 = "rm /tmp/build/ipfs_pinset.txt"
        //let results_2 = child_process.execSync(command_2)
    }
    catch(error){
        console.log("command failed")
        console.log(command)
        console.log(error)
    }
    finally{
        results = results.toString().split("\n")
        let results_matrix = []
        let results_dict = {}
        for(var i = 0; i < results.length; i++){
            results_matrix.push(results[i].split(" | "))
        }
        for(var i = 0; i < results_matrix.length; i++){
            let this_line = results_matrix[i]
            if(this_line.length > 8){
                let ipfs_url = this_line[0].replace(" ","")
                let unknown_value = this_line[1]
                let pin = this_line[2].replace(" ","")
                let repl_factor = parseFloat(this_line[3].split(":")[1].replace(" ","").replace(" ",""))
                let allocations = this_line[4].split(":")[1].replace(" ","").replace(" ","")
                let recursive = this_line[5].includes("Recursive")
                let metadata = this_line[6].split(":")[1].replace(" ","").replace(" ","")
                let expiration = this_line[7].split(":")[1].replace(" ","").replace(" ","")
                let added = this_line[8].split(":")[1].replace(" ","")+ ":" + this_line[8].split(":")[2 ].replace(" ","")

                results_dict[ipfs_url] = {
                    "unknown_value": unknown_value,
                    "repl_factor": repl_factor,
                    "allocations": allocations,
                    "recursive": recursive,
                    "metadata": metadata,
                    "expiration": expiration,
                    "added": added
                }
            }
        }

        return results_dict
    }
    
}

