import os
import torch.nn.functional as F
from torch import inference_mode, float16, Tensor
from transformers import AutoTokenizer, AutoModelForCausalLM, StoppingCriteriaList
from transformers.generation.streamers import TextStreamer
from cloudkit_worker import dispatch_result
from sentence_transformers import SentenceTransformer
from InstructorEmbedding import INSTRUCTOR
from FlagEmbedding import FlagModel

embedding_models = [
    "text-embedding-ada-002",
    "gte-large",
    "gte-base",
    "bge-base-en-v1.5",
    "bge-large-en-v1.5",
    "instructor",
    "instructor-large",
    "instructor-xl"
    ]

class HFEmbed:

    def __init__(self, resources, meta):
        if  "gte" in resources['checkpoint']:
            self.tokenizer = AutoTokenizer.from_pretrained(resources['checkpoint'])
        if "instructor" in resources['checkpoint']:
            self.model = INSTRUCTOR(resources['checkpoint'])
        elif "gte" in resources['checkpoint']:
            self.model = SentenceTransformer(
                resources['checkpoint']
                )
        elif "bge" in resources['checkpoint']:
            self.model = None
            
    def __call__(self, method, **kwargs):
        if method == 'embed':
            return self.embed(**kwargs)
	
    def embed(self, modelName, instruction, input, **kwargs):
        if "modelName" not in embedding_models:
            Exception("Model not found")
        self.input = input
        self.method = 'embed'
        embeddings = None
        if "instructor" in modelName:
            embeddings = self.model.encode([[instruction,input]])
            print(embeddings)
        if "gte" in modelName:
            embeddings = self.model.encode([input])
        if "bge" in modelName:
            if self.model == None:
                self.model = FlagModel(
                    'BAAI/'+modelName, query_instruction_for_retrieval=instruction,
                    use_fp16=True
                )
            embeddings = self.model.encode(str(input))
            print(embeddings)

        return embeddings
        #return self.complete(**kwargs, stream=False)

    def average_pool(last_hidden_states: Tensor, attention_mask: Tensor) -> Tensor:
        last_hidden = last_hidden_states.masked_fill(~attention_mask[..., None].bool(), 0.0)
        return last_hidden.sum(dim=1) / attention_mask.sum(dim=1)[..., None]


def main():
    cwd = os.getcwd()
    dir = os.path.dirname(__file__)
    grandparent = os.path.dirname(dir)
    models = os.path.join(grandparent, "models")
    checkpoint = 'bge-base-en-v1.5'
    resources = {}
    resources['checkpoint'] = models + "/" + checkpoint + "@hf"
    meta = {"name":"bge-base-en-v1.5"}
    text = "sample text to embed"
    model = "bge-base-en-v1.5"
    instruction = "Represent this sentence for searching relevant passages:"
    embed = HFEmbed(resources, meta)
    results = embed.embed(model, instruction, text)
    print(results)
    return results

if __name__ == '__main__':
    #main()
    pass