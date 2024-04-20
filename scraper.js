import * as huggingface_scraper from './huggingface_scraper/main.js';
import * as path from 'path';
import * as process from 'process';
import { loadConfig, requireConfig } from './config/config.js'

let config = requireConfig("./config/config.toml")
let local_model_path
let collection_path
let ipfs_path
let uid 
let operating_system
// detect operating sysem

if (process.platform === 'win32') {
    operating_system = 'windows'
} else if (process.platform === 'linux') {
    operating_system = 'linux'
} else if (process.platform === 'darwin') {
    operating_system = 'mac'
} else {
    operating_system = 'unknown'
}

// detect if user is admin
if (process.getuid && process.getuid() === 0) {
    uid = 'root'
} else {
    // grab username
    uid = process.env.USER
}

if (operating_system == 'linux' && uid == 'root') {
    local_model_path = "/cloudkit-models/"
    collection_path = "/cloudkit-models/collection.json"
    ipfs_path = "/ipfs/"
} else if (operating_system == 'linux' && uid != 'root') {
    local_model_path = path.join(process.env.HOME, ".cache/huggingface/")
    collection_path = path.join(process.env.HOME, ".cache/huggingface/collection.json")
    ipfs_path = path.join(process.env.HOME, ".cache/ipfs/")
}

config.ipfs_path = ipfs_path
config.local_model_path = local_model_path
config.collection_path = collection_path

process.env.mysql_creds = JSON.stringify(config.mysql)
process.env.s3_creds = JSON.stringify(config.s3)
process.env.hf_creds = JSON.stringify(config.hf)
process.env.local_model_path = config.local_model_path
process.env.collection_path = config.collection_path
process.env.ipfs_path = config.ipfs_path

const scraper = new huggingface_scraper.Scraper(
    config.s3,
    config.hf,
    config.mysql,
    config.local_model_path,
    config.ipfs_path,
    config.collection_path
);

scraper.main();