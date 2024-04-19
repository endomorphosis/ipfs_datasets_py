import * as manifest from './manifest.js'
import process from 'process'
import * as generate_manifest from './generate_manifest.js'

export class Scraper {
    constructor(s3_creds, hf_creds, mysql_creds, local_model_path, ipfs_path, collection_path) {
        this.env = process.env;
        if (s3_creds != undefined) {
            process.env.s3_creds = JSON.stringify(s3_creds);
            this.s3_creds = s3_creds;
        }
        if (hf_creds != undefined) {
            process.env.hf_creds = JSON.stringify(hf_creds);
            this.hf_creds = hf_creds;
        }
        if (mysql_creds != undefined) {
            process.env.mysql_creds = JSON.stringify(mysql_creds);
            this.mysql_creds = mysql_creds;
        }
        if (local_model_path != undefined) {
            process.env.local_model_path = local_model_path;
            this.local_model_path = local_model_path;
        }
        if (ipfs_path != undefined) {
            process.env.ipfs_path = ipfs_path;
            this.ipfsPath = ipfs_path;
        }
        if (collection_path != undefined) {
            process.env.collection_path = collection_path;
            this.collection_path = collection_path;
        }
    }

    main() {
        let args = process.argv.slice(2);
        let command;
        let source;
        let model;

        if (args.length > 1) {
            command = args[0];
        }
        if (args.length > 2) {
            source = args[1];
        }
        if (args.length > 3) {
            model = args[2];
        }

        if (command == "-h" || command == "--help") {
            console.log("Usage: node main.js [command] [source] [model]");
            console.log("command: import");
            console.log("source: hf");
            console.log("model: model name");
            process.exit(0);
        }

        if (command == undefined) {
            //console.log("No command specified try -h or --help for help");
            let this_generate_manifest = new generate_manifest.Generate_Manifest();
            let this_manifest = this_generate_manifest.generate_from_prompt()
            //remove keys
            console.log("--this_manifest--");
            console.log(this_manifest);
            let this_process_manifest = new manifest.Manifest(
                this.s3_creds,
                this.hf_creds,
                this.mysql_creds,
                this.local_model_path,
                this.ipfsPath,
                this.collection_path
            );
            let processed_manifest = this_process_manifest.process_prompted_manifest(this_manifest);
        }
        if (command == 'import' && source != "hf") {
            throw new Error("Only hf is supported as a source");
        }

        if (command == "import" && source == "hf" && model == undefined) {
            let this_manifest = new manifest.Manifest(
                this.s3_creds,
                this.hf_creds,
                this.mysql_creds,
                this.local_model_path,
                this.ipfsPath,
                this.collection_path
            );
            this_manifest.import_from_hf();
        }

        if (command == "import" && source == "hf" && model != undefined) {
            let this_manifest = new manifest.Manifest(
                this.s3_creds,
                this.hf_creds,
                this.mysql_creds,
                this.local_model_path,
                this.ipfsPath,
                this.collection_path
            );
            this_manifest.import_from_hf(model);
        }
    }
}
