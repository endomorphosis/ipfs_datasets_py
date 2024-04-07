import fs from 'fs'
import path from 'path'
import * as process_manifest from './process_manifest.js'
import * as generate_manifest from './generate_manifest.js'
import * as generator from './generator.js'
import * as manifest_llama_cpp from './manifests/manifest_llama_cpp.js'
import * as manifest_hf_transformers from './manifests/manifest_hf_transformers.js'
import * as manifest_hf_embed from './manifests/manifest_hf_embed.js'
import * as manifest_hf_faster_whisper from './manifests/manifest_hf_faster_whisper.js'
import * as manifest_hf_t5 from './manifests/manifest_hf_t5.js'
import * as manifest_hf_lm from './manifests/manifest_hf_lm.js'
import * as manifest_knn from './manifests/manifest_knn.js'
import * as manifest_diffusion from './manifests/manifest_diffusion.js'
import * as manifest_api from './manifests/manifest_api.js'
import {complete, parse_templates, generate_test} from './utils.js'
import process from 'process'

export class Manifest{
    constructor(s3_creds, hf_creds, mysql_creds, local_model_path, ipfs_path, collection_path){
        this.id = ""
        this.format = ""
        this.hwRequirements = {}
        this.metadata = {}
        this.env = process.env
        if (s3_creds != undefined){
            this.env.s3_creds = s3_creds
            this.s3_creds = s3_creds
        }
        if (hf_creds != undefined){
            this.env.hf_creds = hf_creds
            this.hf_creds = hf_creds
        }
        if (mysql_creds != undefined){
            this.env.mysql_creds = mysql_creds
            this.mysql_creds = mysql_creds
        }
        if (ipfs_path != undefined){
            this.env.ipfs_path = ipfs_path
            this.ipfs_path = ipfs_path
        }
        if (local_model_path != undefined){
            this.env.local_model_path = local_model_path
            this.local_model_path = local_model_path
        }
        if (collection_path != undefined){
            this.env.collection_path = collection_path
            this.collection_path = collection_path
        }
    }

    main(generated_manifest){
        // depricated for the time being
    }

    process_prompted_manifest(generated_manifest){
        let folder = path.join(this.local_model_path, generated_manifest["id"])
        console.log("manifest.js")
        console.log("process_generated_manifest(generate)")
        console.log(generated_manifest)
        console.log("folder")
        console.log(folder)
        let this_process_manifest = new process_manifest.process_manifest(
            this.s3_creds,
            this.hf_creds,
            this.mysql_creds,
            this.local_model_path,
            this.ipfs_path,
            this.collection_path
        )
        let processing = this_process_manifest.process_prompted_manifest(generated_manifest, folder)
        return processing
    }

    create_generator(){
        let generator = []
        generator.push(generate)
        return generator
    }

    manifest_from_generator(this_generator){
        let generate = this_generator
        if (generate.skill == "hf_transformers"){
            return manifest_hf_transformers.hf_transformers_generate(generate)
        }
        if (generate.skill == "hf_embed"){
            return manifest_hf_embed.hf_embed_generate(generate)
        }
        if (generate.skill == "llama_cpp"){
            return manifest_llama_cpp.llama_cpp_generate(generate)
        }
        if (generate.skill == "diffusion"){
            return manifest_diffusion.diffusion_generate(generate)
        }
        if (generate.skill == "knn"){
            return manifest_knn.knn_generate(generate)
        }
        if (generate.skill == "hf_lm"){
            return manifest_hf_lm.hf_lm_generate(generate)
        }
        if (generate.skill == "hf_t5"){
            return manifest_hf_t5.hf_t5_generate(generate)
        }
        if (generate.skill == "api"){
            return manifest_api.api_generate(generate)
        }
        if (generate.skill == "custom"){
            return manifest_custom.custom_generate(generate)
        }
    }

    import_from_hf(model){
        if (model != undefined){
            console.log("Importing model from manifest definition .json file")
            let this_generator = new generator.Generator(

                local_model_path = this.local_model_path,
                collection_path = this.collection_path
            )
            this_generator.main()
            let llama_cpp = this_generator.llama_cpp
            let hf_transformers = this_generator.hf_transformers
            let hf_embed = this_generator.hf_embed
            let hf_faster_whisper = this_generator.hf_faster_whisper
            let hf_lm = this_generator.hf_lm
            let hf_t5 = this_generator.hf_t5
            let knn = this_generator.knn
            let diffusion = this_generator.diffusion
            let api = this_generator.api

            let all_models = {}
            llama_cpp.forEach(model => all_models[model.modelName] = model)
            hf_transformers.forEach(model => all_models[model.modelName] = model)
            hf_embed.forEach(model => all_models[model.modelName] = model)
            hf_faster_whisper.forEach(model => all_models[model.modelName] = model)
            hf_lm.forEach(model => all_models[model.modelName] = model)
            hf_t5.forEach(model => all_models[model.modelName] = model)
            knn.forEach(model => all_models[model.modelName] = model)
            diffusion.forEach(model => all_models[model.modelName] = model)
            api.forEach(model => all_models[model.modelName] = model)

            if (model in all_models){
                let this_generate = all_models[model]
                let this_manifest = new manifest_from_generator(this_generate)
                let this_process = new process_manifest.process_manifest(
                    s3_creds = this.s3_creds,
                    hf_creds = this.hf_creds,
                    mysql_creds = this.mysql_creds,
                    local_model_path = this.local_model_path,
                    collection_path = this.collection_path
                )
                this_process.main(this_generate, this_manifest)
            }
            else{
                let this_generate
                for (this_model in all_models){
                    this_model_source = this_model.source
                    if (model in this_model_source){
                        this_generate = all_models[this_model]
                        let this_manifest = new manifest_from_generator(this_generate)
                        let this_process = new process_manifest.process_manifest(
                            s3_creds = this.s3_creds,
                            hf_creds = this.hf_creds,
                            mysql_creds = this.mysql_creds,
                            local_model_path = this.local_model_path,
                            collection_path = this.collection_path
                        )
                        this_process.main(this_generate, this_manifest)
                    }
                }
                if (this_generate == undefined){
                    console.log("Model not found")
                    let this_generate_manifest = new generate_manifest.Generate_Manifest();
                    let this_manifest = this_generate_manifest.main();
                    let this_process_manifest = new manifest.Manifest(
                        s3_creds = this.s3_creds,
                        hf_creds = this.hf_creds,
                        mysql_creds = this.mysql_creds,
                        local_model_path = this.local_model_path,
                        collection_path = this.collection_path
                    );
                    this_process_manifest.main();
                }
            }
        }
        if (model == undefined){
            console.log("Importing / rebuilding all models from manifest definition .json files")
            console.log("This might take a while")
            for (var generate in llama_cpp){
                let this_generate = llama_cpp[generate]
                let this_manifest =  new manifest_llama_cpp.Manifest_llama_cpp()
                this_manifest.main(this_generate)
                let this_process = new process_manifest.process_manifest(
                    s3_creds = this.s3_creds,
                    hf_creds = this.hf_creds,
                    mysql_creds = this.mysql_creds,
                    local_model_path = this.local_model_path,
                    collection_path = this.collection_path
                )
                this_process.main(this_generate, this_manifest)
            }        

            for (var generate in hf_embed){
                let this_generate = hf_embed[generate]
                let this_manifest = new manifest_hf_embed.Manifest_hf_embed()
                this_manifest.main(this_generate)
                let this_process = new process_manifest.process_manifest(
                    s3_creds = this.s3_creds,
                    hf_creds = this.hf_creds,
                    mysql_creds = this.mysql_creds,
                    local_model_path = this.local_model_path,
                    collection_path = this.collection_path
                )
                this_process.main(this_generate, this_manifest)
            }

            for (var generate in hf_faster_whisper){
                let this_generate = hf_faster_whisper[generate]
                let this_manifest = new manifest_hf_faster_whisper.Manifest_hf_faster_whisper()
                this_manifest.main(this_generate)
                let this_process = new process_manifest.process_manifest(
                    s3_creds = this.s3_creds,
                    hf_creds = this.hf_creds,
                    mysql_creds = this.mysql_creds,
                    local_model_path = this.local_model_path,
                    collection_path = this.collection_path
                )
                this_process.main(this_generate, this_manifest)
            }

            for (var generate in hf_transformers){
                let this_generate = hf_transformers[generate]
                let this_manifest = new manifest_hf_transformers.Manifest_hf_transformers()
                this_manifest.main(this_generate)
                let this_process = new process_manifest.process_manifest(
                    s3_creds = this.s3_creds,
                    hf_creds = this.hf_creds,
                    mysql_creds = this.mysql_creds,
                    local_model_path = this.local_model_path,
                    collection_path = this.collection_path
                )
                this_process.main(this_generate, this_manifest)
            }

            for (var generate in hf_lm){
                let this_generate = hf_lm[generate]
                let this_manifest = new manifest_hf_lm.Manifest_hf_lm()
                this_manifest.main(this_generate)
                let this_process = new process_manifest.process_manifest(
                    s3_creds = this.s3_creds,
                    hf_creds = this.hf_creds,
                    mysql_creds = this.mysql_creds,
                    local_model_path = this.local_model_path,
                    collection_path = this.collection_path
                )
                this_process.main(this_generate, this_manifest)
            }

            for (var generate in hf_t5){
                let this_generate = hf_t5[generate]
                let this_manifest = new manifest_hf_t5.Manifest_hf_t5()
                this_manifest.main(this_generate)
                let this_process = new process_manifest.process_manifest(
                    s3_creds = this.s3_creds,
                    hf_creds = this.hf_creds,
                    mysql_creds = this.mysql_creds,
                    local_model_path = this.local_model_path,
                    collection_path = this.collection_path
                )
                this_process.main(this_generate, this_manifest)
            }

            for (var generate in knn){
                let this_generate = knn[generate]
                let this_manifest = new manifest_knn.Manifest_knn()
                this_manifest.main(this_generate)
                let this_process = new process_manifest.process_manifest(
                    s3_creds = this.s3_creds,
                    hf_creds = this.hf_creds,
                    mysql_creds = this.mysql_creds,
                    local_model_path = this.local_model_path,
                    collection_path = this.collection_path
                )
                this_process.main(this_generate, this_manifest)
            }

            for (var generate in diffusion){
                let this_generate = diffusion[generate]
                let this_manifest = new manifest_diffusion.Manifest_diffusion()
                this_manifest.main(this_generate)
                let this_process = new process_manifest.process_manifest(
                    s3_creds = this.s3_creds,
                    hf_creds = this.hf_creds,
                    mysql_creds = this.mysql_creds,
                    local_model_path = this.local_model_path,
                    collection_path = this.collection_path
                )
                this_process.main(this_generate, this_manifest)
            }

            for (var generate in api){
                let this_generate = api[generate]
                let this_manifest = new manifest_api.Manifest_api()
                this_manifest.main(this_generate)
                let this_process = new process_manifest.process_manifest(
                    s3_creds = this.s3_creds,
                    hf_creds = this.hf_creds,
                    mysql_creds = this.mysql_creds,
                    local_model_path = this.local_model_path,
                    collection_path = this.collection_path
                )
                this_process.main(this_generate, this_manifest)
            }
        }
    }
}


