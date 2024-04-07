import * as huggingface_scraper from './huggingface_scraper/main.js';
import * as path from 'path';
import * as process from 'process';
let local_model_path
let collection_path
let ipfs_path
let uid 
let operating_system
// detect operating sysem
let s3_bucket = "huggingface-models"
let s3_secret_key = "H1osbJRy3903PTMqyOAGD6MIohi4wLXGscnvMEduh10"
let s3_access_key = "OVEXCZJJQPUGXZOV"
let s3_endpoint = "https://object.ord1.coreweave.com"
let s3_host_bucket = "%(bucket)s.object.ord1.coreweave.com"

let hf_account_name = "endomorphosis"
let hf_user_key = "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"
let hf_org_key = "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"
let hf_org_name = "publicus"

let mysql_host = "swissknife.mwni.io"
let mysql_user = "swissknife"
let mysql_password = "W5!LIGO[pRPO0SdH"
let mysql_database = "swissknife"

let mysql_creds = {
    "host": mysql_host,
    "user": mysql_user,
    "password": mysql_password,
    "database": mysql_database
}

let s3_creds = {
    "accessKey": s3_access_key,
    "secretKey": s3_secret_key,
    "endpoint": s3_endpoint,
    "bucket": s3_bucket,
    "hostBucket": s3_host_bucket
}

let hf_creds = {
    "account_name": hf_account_name,
    "user_key": hf_user_key,
    "org_key": hf_org_key,
    "org_name": hf_org_name
}


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



process.env.mysql_creds = JSON.stringify(mysql_creds)
process.env.s3_creds = JSON.stringify(s3_creds)
process.env.hf_creds = JSON.stringify(hf_creds)
process.env.local_model_path = local_model_path
process.env.collection_path = collection_path
process.env.ipfs_path = ipfs_path

const scraper = new huggingface_scraper.Scraper(
    s3_creds = s3_creds,
    hf_creds = hf_creds,
    mysql_creds = mysql_creds,
    local_model_path = local_model_path,
    ipfs_path = ipfs_path,
    collection_path = collection_path
);

scraper.main();