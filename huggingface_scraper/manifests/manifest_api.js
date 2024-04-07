import {complete, open_ended_question, multiple_choice_question, parse_templates, generate_template, generate_metadata_template, generate_hwrequirements_template} from '../utils.js'
import prompt_sync from 'prompt-sync'
import prompt_sync_history from 'prompt-sync-history'
import models_generate_api from '../modeldata/generate_api.json' assert { type: 'json' };

export class Manifest_api{
    constructor(){
        this.metadata = {}
        this.hwRequirements = {}
        this.folderData = {}
        this.cache = {}
        this.format = ""
        this.id = ""
        this.source = ""
        this.skill = ""
    }

    main(generate){
        let generation = api_generate(generate)
        for (var key in generation){
            this[key] = generation[key]
        }
        return this
    }

    calc(){
        return api_calc_calc()
    }
}

export default function api_calc(){
    let providers = ["openai","huggingface","custom"]

    let provider = multiple_choice_question("Select a provider: ", providers)

    let api_key = open_ended_question("Enter an API key: ")

    let secret_key = open_ended_question("Enter a secret key: ")

    let results = api_generate(generate)

    return results

}

export function api_generate_hwrequirements(){
    let results = generate_hwrequirements_template(generate)
    results.gpuCount = 0
    results.cpu_count = [1]
    results.memory = 2048
    results.disk_space = 1024
    return results
}

export function api_generate_metadata(){
    let results = generate_metadata_template(generate)
    if (generate.provider == 'openai'){
        results['openai_api_key'] = generate.api_key
        results['openai_secret_key'] = generate.secret_key
        results.templates = [
            "assistant","chat","embed","edit","complete"
        ]
    }
    if (generate.provider == 'huggingface'){
        results['huggingface_api_key'] = generate.api_key
        results['huggingface_secret_key'] = generate.secret_key
    }

    return results
}

export function api_generate(generate){
    let results = generate_template(generate)
    results.metadata = api_generate_metadata(generate)
    results.hwRequirements = api_generate_hwrequirements(generate)
    results.id = "api-" + generate.provider
    results.skill = "api"
    return results
}

export function api_add(generation){
    if (generation.modelName != undefined){
        models_generate_api[generation.modelName] = generation
        fs.writeFileSync(path.resolve('../modeldata/generate_api.json'), JSON.stringify(models_generate_api, null, 2))       
        return Object.keys(models_generate_api)
    }
    else{
        throw "model name is undefined"
    }      
}