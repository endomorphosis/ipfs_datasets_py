import {complete, open_ended_question, multiple_choice_question, parse_templates, generate_template, generate_metadata_template, generate_hwrequirements_template} from '../utils.js'
import prompt_sync from 'prompt-sync'
import prompt_sync_history from 'prompt-sync-history'
import models_generate_dataset from '../modeldata/generate_diffusion.json' assert { type: 'json' };

export class Manifest_dataset{
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
        let generation = dataset_generate(generate)
        for (var key in generation){
            this[key] = generation[key]
        }
        return this
    }

    calc(){
        return dataset_calc()
    }
}

export default function dataset_calc(){

    let prompt = prompt_sync(({
        history: prompt_sync_history(),
        autocomplete: complete([]),
        sigint: true
    }))

    let modelName = open_ended_question("Enter a model name: ")

    let locations = ['local', 'huggingface', 'http', 's3']

    let location = multiple_choice_question("Where is the model located?", locations) 

    let source = open_ended_question("Enter a source from " + location + ": ")

    let formats = [ "parquet", "text", "json", "csv", "tsv"]

    let format = multiple_choice_question("Select a format: ", formats)
   
    let samples = open_ended_question("Enter the number of samples: ")

    let size = open_ended_question("Enter the size of the dataset in MB: ")
    
    let generate = {}
    generate.modelName = modelName
    generate.location = location
    generate.source = source
    generate.format = format
    generate.samples = samples
    generate.size = size

    let results = dataset_generate(generate)

    return results
}

export function dataset_generate_hwrequirements(generate){
    let results = generate_hwrequirements_template(generate)
    results.cpuCount = [1]
    results.gpuCount = [0]
    let padding = 1.1
    results.gpuMemory = 0
    results.diskUsage = results.size * 1024 * 1024 * padding
    results.cpuMemory = results.size * 1024 * 1024 * padding
    return results
}


export function dataset_generate_metadata(generate){
    let results = generate_metadata_template(generate)
    results.format = generate.format
    results.location = generate.location
    results.modelName = generate.modelName
    results.model_type = 'dataset'
    results.units = "MB"
    results.samples = generate.samples
    results.size = generate.size
    return results
}


export function dataset_generate(generate){
    let results = generate_template(generate)
    results.id = generate.modelName;
    results.hwRequirements = dataset_generate_hwrequirements(generate)
    results.metadata = dataset_generate_metadata(generate)
    results.skill = "dataset"
    return results
}

export function dataset_add(generation){
    if (generation.modelName != undefined){
        models_generate_dataset[generation.modelName] = generation
        fs.writeFileSync(path.resolve('../modeldata/generate_dataset.json'), JSON.stringify(models_generate_dataset, null, 2))       
        return Object.keys(models_generate_dataset)
    }
    else{
        throw "model name is undefined"
    }      
}