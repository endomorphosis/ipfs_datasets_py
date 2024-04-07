import { ipfsClusterCtl } from "./ipfs.js"
import fs from 'fs'


export function test1(){
    let collection_path = "/storage/cloudkit-models/collection.json"
    let collection = fs.readFileSync(collection_path)
    collection = JSON.parse(collection)
    let this_cluster = new ipfsClusterCtl()
    let status = this_cluster.check_collection(collection)
    return status
}


export function ipfsClusterStatus(collection){
    let this_cluster = new ipfsClusterCtl()
    let status = this_cluster.check_collection(collection)
    return status
}

let results = test1()
console.log(results)