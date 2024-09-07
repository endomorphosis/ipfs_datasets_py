import time
import re
import os
import openai
from cloudkit_worker import dispatch_result
import tiktoken

text_complete_models = [
    "text-davinci-003"
]

edit_models = [
    "text-davinci-edit-001",
    "code-davinci-edit-001"
]

embedding_models = [
    "text-embedding-ada-002"
]

chat_templates = [
        {
            'models': ['gpt-3.5-turbo','gpt-4','gpt-3.5-turbo-16k'],
            'system_msg': 'A chat between a curious user and an artificial intelligence assistant. ' + \
            'The assistant gives helpful, detailed, and polite answers to the user\'s questions. <</SYS>> [/INST]',
		    'user_msg': 'USER: {text}',
            'user_sep': '\n',
		    'assistant_msg': 'ASSISTANT: {text}',
            'assistant_sep': '\n',
        }
    ]

class OpenAIAPI:
    def __init__(self, resources, meta=None):
        self.prompt = None
        self.messages = None
        self.instruct = None
        self.input = None
        self.method = None
        self.temperature = None
        self.api_key = None
        if meta is not None:
            if "openai_api_key" in meta:
                if meta['openai_api_key'] is not None:
                    self.openai_api_key = meta['openai_api_key']
        if self.openai_api_key is not None:
            openai.api_key = self.openai_api_key
            
        self.resources = resources
        self.meta = meta
        if resources is not None:
            self.model = resources['checkpoint'].split("@")[0].split("/")[-1]
        else:
            self.model = None

    def __call__(self, method, **kwargs):
        self.messages = None
        self.input = None
        if "openai_api_key" in kwargs:
            if kwargs['openai_api_key'] is not None:
                self.openai_api_key = kwargs['openai_api_key']
        if self.openai_api_key is not None:
            openai.api_key = self.openai_api_key
        else:
            raise Exception('bad api_key: %s' % self.openai_api_key)
        if self.model is not None:    
            kwargs['model'] = self.model
        if method == 'text_complete':
            return self.complete(**kwargs)
        elif method == 'chat':
            return self.chat(**kwargs)
        elif method == 'edit':
            return self.edit(**kwargs)
        elif method == 'embedding':
            return self.embedding(**kwargs)
        
    def embedding(self, model, input, **kwargs):
        self.model = model
        self.input = input
        self.messages = None
        self.prompt = None
        self.method = 'embedding'
        return self.text_complete(**kwargs, stream=False)
        
    def complete(self, model, prompt, temperature, max_tokens, **kwargs):
        self.model = model
        self.prompt = prompt
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.method = 'complete'
        return self.text_complete(**kwargs, stream=False)
        
    def edit(self, model, input, instruct, max_tokens, **kwargs):
        self.model = model
        self.input = input
        self.instruct = instruct
        self.max_tokens = max_tokens
        self.method = 'edit'
        return self.text_complete(**kwargs, stream=False)
    
    def tokenize(self, text , model, max_tokens, **kwargs):
        self.model = model
        self.text = text
        self.max_tokens = max_tokens
        self.method = 'tokenize'
        default_tokenizer_model = "gpt-3.5-turbo"
        if self.model is None:
            self.model = default_tokenizer_model
        encoding = tiktoken.encoding_for_model(default_tokenizer_model)
        encoding = encoding.encode(text)
        return encoding

    def detokenize(self, tokens, model, **kwargs):
        self.model = model
        self.tokens = tokens
        self.method = 'detokenize'
        default_tokenizer_model = "gpt-3.5-turbo"
        if self.model is None:
            self.model = default_tokenizer_model
        encoding = tiktoken.get_encoding("cl100k_base")
        encoding = tiktoken.encoding_for_model(self.model)
        return encoding.decode(tokens)

    def text_complete(self, stream, stopping_regex=None, **kwargs):
        template = chat_templates[0]
        if self.model is None or (self.model not in template['models'] and self.model not in text_complete_models and self.model not in edit_models and self.model not in embedding_models):
            raise Exception('bad model: %s' % self.model)
        
        if stopping_regex:
            try:
                stopping_regex = re.compile(stopping_regex)
            except Exception as e:
                raise Exception('bad "stopping_regex": %s' % str(e))
        openai_error = None
        response = None
        while openai_error == True or openai_error == None:
            openai_error = False
            try:
                if self.messages is not None:
                    response = openai.ChatCompletion.create(
                        model=self.model,
                        messages=self.messages,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        top_p=1,
                        frequency_penalty=0,
                        presence_penalty=0
                    )
                elif self.prompt is not None:
                    response = openai.Completion.create(
                        model=self.model,
                        prompt=self.prompt,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        top_p=1,
                        frequency_penalty=0,
                        presence_penalty=0
                    )
                elif self.instruct is not None and self.instruct is not None:
                    response = openai.Edit.create(
                        model=self.model,
                        input=self.input,
                        instruction=self.instruct,
                        temperature=self.temperature,
                        top_p=1
                    )
                elif self.input is not None and self.instruct is None:
                    response = openai.Embedding.create(
                        input=self.input,
                        model=self.model
                    )
                pass
                openai_error = False
            except Exception as e:
                openai_error = True
                print(e)
                #wait 1 second
                time.sleep(1)
                pass

        if not stream:
            if self.messages is not None:
                return {
                    'text': response.choices[0].message.content,
                    'done': True
                }
            if self.prompt is not None:
                return {
                    'text': response.choices[0].text,
                    'done': True
                }
            if self.input is not None and self.instruct is not None:
                return {
                    'text': response.choices[0].text,
                    'done': True
                }
            if self.input is not None and self.instruct is None:
                return {
                    'data': response['data'][0]['embedding'],
                    'done': True
                }
        else:
            ## todo ##
            return {
				'text': response.choices[0].text,
				'done': True
			}
		
    def chat(self, model, messages, system, temperature, max_tokens, **kwargs):
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.method = 'chat'
        template = chat_templates[0]
        self.model = model
        messagesList = []
        if system is not None:
            systemDict = {"role": "system", "content": system}
        else:
            systemDict = {"role": "system", "content": template['system_msg']}
        messagesList.append(systemDict)
        for m in messages:
            if m['role'] == 'user':
                if "text" in m:
                    userDict = {"role": "user", "content": m['text']}
                elif "content" in m:
                    userDict = {"role": "user", "content": m['content']}
                messagesList.append(userDict)
            elif m['role'] == 'assistant':
                if "text" in m:
                    assistantDict = {"role": "assistant", "content": m['content']}
                elif "content" in m:
                    assistantDict = {"role": "assistant", "content": m['content']}
                messagesList.append(assistantDict)

        if messages[-1]['role'] == 'user':
            self.messages = messagesList

        return self.text_complete(False, **kwargs)


def main():
    test_api_key = {
        "api_key": ""
    }
    test_model = 'gpt-3.5-turbo'
    test_complete_model = 'text-davinci-003'
    test_temperature = 0.5
    test_max_tokens = 100
    test_embedding_model = 'text-embedding-ada-002'
    test_prompt = 'This is a test prompt.'
    test_input = 'This is a test input.'
    test_messages = [
        {
            'role': 'user',
            'content': 'Hello, how are you?'
        },
        {
            'role': 'assistant',
            'content': 'I am doing well, how are you?'
        },
        {
            'role': 'user',
            'content': 'I am doing well, thank you.'
        }
    ]
    test_system = 'This is a test system message.'
    #openai_api_instance = OpenAIAPI(None, meta=test_api_key)
    #print(openai_api_instance.embedding(test_embedding_model, test_input))
    #print(openai_api_instance.chat(test_api_key, test_model, test_messages, test_system, test_temperature, test_max_tokens))
    #print(openai_api_instance.complete(test_api_key, test_complete_model, test_prompt, test_temperature, test_max_tokens))
if __name__ == '__main__':
    #main()
    pass
