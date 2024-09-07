import os
import torch.nn.functional as F
from torch import inference_mode, float16, Tensor
from transformers import AutoTokenizer, AutoModelForCausalLM, StoppingCriteriaList
from transformers.generation.streamers import TextStreamer
from cloudkit_worker import dispatch_result
from sentence_transformers import SentenceTransformer
from InstructorEmbedding import INSTRUCTOR
from FlagEmbedding import FlagModel
import json

embedding_models = [
	"text-embedding-ada-002",
	"gte-large",
	"gte-base",
	"gte-small",
	"gte-tiny",
	"bge-small-en-v1.5",
	"bge-base-en-v1.5",
	"bge-large-en-v1.5",
	"instructor-base",
	"instructor-large",
	"instructor-xl",
	"UAE-Large-V1"
]

class hf_embed:

	def __init__(self, resources, meta):
		self.modelName = meta['modelName']
		self.hf_embed = self.embed
		self.instruct_embed = self.embed
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
		if method == 'hf_embed':
			return self.embed(**kwargs)
		elif method == 'instruct_embed':
			return self.embed(**kwargs)
		else:
			raise Exception('unknown method: %s' % method)
	
	def embed(self, instruction, text , **kwargs):
		self.input = text
		self.method = 'embed'
		embeddings = None
		if "instructor" in self.modelName:
			embeddings = self.model.encode([[instruction,self.input]])
			print(embeddings)
		if "gte" in self.modelName:
			embeddings = self.model.encode([self.input])
			print(embeddings)
		if "bge" in self.modelName:
			if self.model == None:
				self.model = FlagModel(
					'BAAI/'+self.modelName, query_instruction_for_retrieval=instruction,
					use_fp16=True
				)
			embeddings = self.model.encode(str(self.input))
			print(embeddings)

		if type(embeddings) != str:
			embeddings = json.dumps(embeddings.tolist())

		return {
			'text': embeddings, 
			'done': True
		}
		
	def average_pool(last_hidden_states: Tensor, attention_mask: Tensor) -> Tensor:
		last_hidden = last_hidden_states.masked_fill(~attention_mask[..., None].bool(), 0.0)
		return last_hidden.sum(dim=1) / attention_mask.sum(dim=1)[..., None]



def test():
	cwd = os.getcwd()
	dir = os.path.dirname(__file__)
	grandparent = os.path.dirname(dir)
	models = os.path.join(grandparent, "models")
	checkpoint = 'bge-base-en-v1.5'
	resources = {}
	resources['checkpoint'] = models + "/" + checkpoint + "@hf"
	
	print(resources["checkpoint"])
	meta = {"modelName":"bge-base-en-v1.5"}
	text = "sample text to embed"
	model = "bge-base-en-v1.5"
	instruction = "Represent this sentence for searching relevant passages:"
	embed = hf_embed(resources, meta)
	results = embed.embed(instruction, text)
	print(results)
	return results

if __name__ == '__main__':
	test()
	# pass