from diffusers import StableDiffusionPipeline
import safetensors
import torch
import sys 

def main(source_file, output_folder):
    pipe = StableDiffusionPipeline.from_single_file(
        source_file,
    )
    pipe.save_pretrained(output_folder)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

