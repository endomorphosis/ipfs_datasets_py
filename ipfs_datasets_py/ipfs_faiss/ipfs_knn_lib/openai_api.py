import time
import re
import os
import openai
from cloudkit_worker import dispatch_result
import tiktoken
import tempfile
import base64
import requests
import tempfile
import json
import subprocess
from datetime import datetime

assistants_models = [
    "gpt-4",
    "gpt-4-32k",
    "gpt-4-1106-preview",
    "gpt-4-vision-preview",
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-16k",
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-1106"
]


tools_models = [
    "gpt-4-1106-preview",
    "gpt-3.5-turbo-1106"
]

embedding_models = [
    "text-embedding-ada-002"
]

vision_models = [
    "gpt-4-vision-preview"
]

text_to_speech = [
    "tts-1",
    "tts-1-hd",
]

completions = [
    "gpt-3.5-turbo-instruct",
]

chat_completion_models =[
    "gpt-4",
    "gpt-4-32k",
    "gpt-4-1106-preview",
    "gpt-4-vision-preview",
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-16k",
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-1106"
]

speech_to_text = [
    "whisper-1"
]

image_models = [
    "dall-e-3",
    "dall-e-2"
]

moderation_models = [
    "text-moderation-latest",
    "text-moderation-stable"
]

translation_models = [
    "whisper-1"
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
    def __init__(self, resources, meta):
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
                    self.api_key = meta['openai_api_key']
        dir_self = list(dir(self))
        properties = list(self.__dict__.keys())
        if("api_key" in dir_self):
            if self.api_key is not None:
                openai.api_key = self.api_key

        if self.api_key is not None:
            pass
        #else:
        #    raise Exception('bad api_key: %s' % self.api_key)
            
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
                self.meta["openai_api_key"] = kwargs['openai_api_key']
        print(self.meta)
        if ("openai_api_key" in list(self.meta.keys())):
            if self.meta["openai_api_key"] is not None:
                openai.api_key = self.meta["openai_api_key"]
            else:
                raise Exception('bad api_key: %s' % self.meta["openai_api_key"])
        else:
            raise Exception('no key found in meta: %s' % self.meta)
        if self.model is not None:    
            kwargs['model'] = self.model
        if method == 'chat':
            return self.chat(**kwargs)
        elif method == 'embedding':
            return self.embedding(**kwargs)
        elif method == 'text_to_image':
            return self.text_to_image(**kwargs)
        elif method == 'image_to_text':
            return self.image_to_text(**kwargs)
        elif method == 'text_to_speech':
            return self.text_to_speech(**kwargs)
        elif method == 'speech_to_text':
            return self.speech_to_text(**kwargs)
        elif method == 'moderation':
            return self.moderation(**kwargs)
        elif method == 'audio_chat':
            return self.audio_chat(**kwargs)
        elif method == 'assistant':
            return self.assistant(**kwargs)
        else:
            print(self)
            raise Exception('bad method in __call__: %s' % method)

    def embedding(self, model, input, **kwargs):
        if model not in embedding_models:
            raise Exception('bad model: %s' % model)
        self.model = model
        self.input = input
        self.method = 'embedding'
        embedding = openai.embeddings.create(
            input=input,
            model=model
        )
        return {
            'text': embedding,
            'done': True
        }

    def moderation(self, model, text, **kwargs):
        if model not in moderation_models:
            raise Exception('bad model: %s' % model)
        self.model = model
        self.text = text
        self.method = 'moderation'
        moderation = openai.moderations.create(input=text)
        return moderation
    
    def speech_to_text(self, model, audio, **kwargs):
        if model not in speech_to_text:
            raise Exception('bad model: %s' % model)
        self.model = model
        self.audio = audio
        self.method = 'speech_to_text'
        audio_file = open(audio, "rb")
        transcript = openai.audio.transcriptions.create(
            model=model,
            file=audio_file
        )
        return {
            'text': transcript,
            'done': True
        }

    
    def text_to_image(self, model, size, n, prompt, **kwargs):
        sizes = {
            "dall-e-3":
            [
                "1024x1024",
                "1792x1024",
                "1024x1792"
            ],
            "dall-e-2":
            [
                "256x256",
                "512x512",
                "1024x1024",
            ]
        }
        if model not in image_models:
            raise Exception('bad model: %s' % model)
        if size not in sizes[model]:
            raise Exception('bad size: %s' % size)
        
        if n is None:
            n = 1
        if int(n):
            n = int(n)
        if n < 1:
            raise Exception('bad n: %s' % n)
        if n > 1:
            if model == "dall-e-3":
                raise Exception('bad n: %s' % n)
        if n > 10:
            if model == "dall-e-2":
                raise Exception('bad n: %s' % n)
            raise Exception('bad n: %s' % n)
        
        self.model = model
        self.prompt = prompt
        self.n = n
        self.size = size
        self.method = 'text_to_image'

        image = self.moderated_text_to_image(self.model, self.size, self.n, self.prompt)
        
        return image

    
    def moderated_text_to_image(self, model, size, n, prompt, **kwargs):
        json_messages = json.dumps(prompt)
        requested_model = self.model
        original_method = self.method
        moderation_model = 'text-moderation-stable'
        check_messages = self.moderation(moderation_model, json_messages)
        self.method = original_method
        self.model = requested_model
        if len(check_messages.results) > 0:
            results_keys = list(check_messages.results[0].__dict__.keys())
            if "flagged" in results_keys:
                if check_messages.results[0].flagged == True:
                    raise Exception('bad messages: %s' % self.messages)
                else:
                    image = openai.images.generate(
                        model=model,
                        n=n,
                        size=size,
                        prompt=prompt
                    )

                    data = image.data
                    images = []
                    for i in range(len(data)):
                        this_data = data[i]
                        this_image = {}
                        this_image['url'] = this_data.url
                        this_image['revised_prompt'] = this_data.revised_prompt
                        images.append(this_image)
                        
                    return {
                        'text': json.dumps(images),
                        'done': True
                    }

    def text_to_speech(self, model, text, voice, response_format="mp3", speed=1, **kwargs):

        voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
        response_formats = ["mp3", "opus", "aac" "flac"]
        speeds = [ 0.25, 4 ]
        max_length = 4096

        if(voice is None):
            voice = "fable"
        if(response_format is None):
            response_format = "mp3"
        if(speed is None):
            speed = 1

        if(len(text) > max_length):
            raise Exception('bad text: %s' % text)
        if(voice not in voices):
            raise Exception('bad voice: %s' % voice)
        if(response_format not in response_formats):
            raise Exception('bad response_format: %s' % response_format)
        if(speed < 0.25 or speed > 4):
            raise Exception('bad speed: %s' % speed)

        self.model = model
        self.text = text
        self.method = 'text_to_speech'
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.close()
            speech_file_path = temp_file.name
            #response = openai.audio.speech.create(
            #    model=model,
            #    voice=voice,
            #    input=text
            #)
            response = self.moderated_text_to_speech(model, text, voice, response_format, speed)["text"].text
            return {
                'audio': response,
                'done': True
            }
        
    def embedding(self, model, input, format, **kwargs):
        encoding_formats = [
            "float",
            "base64"
        ]
        self.model = model
        self.input = input
        self.messages = None
        self.prompt = None
        self.method = 'embedding',
        self.encoding_format = format
        embedding = openai.embeddings.create(
            input=input,
            model=model,
            encoding_format=format
        )

        data = embedding.data
        embeddings = []
        for i in range(len(data)):
            this_data = data[i]
            this_image = {}
            this_image['embedding'] = this_data.embedding
            embeddings.append(this_image)
            
        return {
            'text': json.dumps(embeddings[0]),
            'done': True
        }


    
    
    def tokenize(self, text , model, **kwargs):
        self.model = model
        self.text = text
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
    
    def moderated_chat_complete(self, stopping_regex=None, **kwargs):
        json_messages = json.dumps(self.messages)
        requested_model = self.model
        original_method = self.method
        moderation_model = 'text-moderation-stable'
        check_messages = self.moderation(moderation_model, json_messages)
        self.method = original_method
        self.model = requested_model
        if len(check_messages.results) > 0:
            results_keys = list(check_messages.results[0].__dict__.keys())
            if "flagged" in results_keys:
                if check_messages.results[0].flagged == True:
                    raise Exception('bad messages: %s' % self.messages)
                else:
                    response = openai.chat.completions.create(
                        model=self.model,
                        messages=self.messages,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        top_p=1,
                        frequency_penalty=0,
                        presence_penalty=0
                    )
                    return {
                        'text': response,
                        'done': True
                    }

    def moderated_text_to_speech(self, model, text, voice, response_format, speed):
        json_messages = json.dumps(self.messages)
        requested_model = model
        original_method = self.method
        moderation_model = 'text-moderation-stable'
        check_messages = self.moderation(moderation_model, json_messages)
        self.method = original_method
        self.model = requested_model
        if len(check_messages.results) > 0:
            results_keys = list(check_messages.results[0].__dict__.keys())
            if "flagged" in results_keys:
                if check_messages.results[0].flagged == True:
                    raise Exception('bad messages: %s' % self.messages)
                else:
                    response = openai.audio.speech.create(
                        model=self.model,
                        voice=voice,
                        input=text,
                        speed=speed,
                        response_format=response_format
                    )
                    
                    return {
                        'text': response,
                        'done': True
                    }            


    def request_complete(self, stopping_regex=None, **kwargs):

        all_models = vision_models + tools_models + chat_completion_models

        if self.model is None or self.model not in all_models:
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
                if self.method is not None and self.method == 'image_to_text':
    
                    response = self.moderated_chat_complete(stopping_regex)

                elif self.method is not None and self.method == 'chat':

                    response = self.moderated_chat_complete(stopping_regex)
                    
                else:
                    raise Exception('bad method in request_complete: %s' % self.method)
                
                openai_error = False
            except Exception as e:
                openai_error = True
                print(e)
                #wait 1 second
                time.sleep(1)
                pass
        # if stream is undefined
        if "stream" not in list(self.__dict__.keys()):
            if self.method is not None and ( self.method == 'chat' or self.method == 'image_to_text' ):
                response = response["text"]
                return {
                    'text': response.choices[0].message.content,
                    'done': True
                }
            elif self.input is not None and self.instruct is not None:
                return {
                    'text': response.choices[0].text,
                    'done': True
                }
            else:
                ## todo ##
                return {
                    'text': response.choices[0].text,
                    'done': True
                }
        
    def image_to_text(self, model, prompt, images, max_tokens, system, **kwargs):
        qualities  = ["low", "high", "auto"]
        self.images = images
        self.model = model
        self.prompt = prompt
        self.max_tokens = max_tokens
        messages = {}
        self.messages = {}
        self.system = system
        this_messages = self.process_messages(messages, prompt, images, system)
        self.messages = this_messages
        self.method = 'image_to_text'
        for image in self.images:
            if image['detail'] not in qualities:
                raise Exception('bad quality: %s' % image['quality'])

        return self.request_complete(**kwargs) 
    
    def chat(self, model, messages, prompt, system, temperature, max_tokens, **kwargs):
        self.max_tokens = max_tokens
        if ("files" in kwargs):
            files = kwargs['files']
        else:
            files = None
        messages = self.process_messages(messages, prompt, files, system)
        model = self.determine_model(model, messages)
        self.messages = messages
        self.model = model
        self.prompt = prompt
        self.system = system
        self.temperature = temperature
        self.model = model
        self.files = files
        self.method = 'chat'
        return self.request_complete( **kwargs)
    


    def audio_chat(self, model, messages, voice, system, temperature, max_tokens, **kwargs):
        self.max_tokens = max_tokens

        if ("prompt" in kwargs):
            prompt = kwargs['prompt']
            if prompt == "":
                prompt = None
        else:
            prompt = None
            pass
        if ("audio" in kwargs):
            audio = kwargs['audio']
            if audio == "":
                audio = None
        else:
            audio = None
            pass
        if prompt is None and audio is None:
            raise Exception('no prompt or audio: %s' % prompt)
        
        if prompt is not None and audio is not None:
            raise Exception('you have both prompt and audio: %s' % prompt)
        file_types = ['flac', 'm4a', 'mp3', 'mp4', 'mpeg', 'mpga', 'oga', 'ogg', 'wav', 'webm']
        self.messages = messages
        self.model = model
        if prompt is not None:
            self.prompt = prompt
        if audio is not None:
            if "http" in audio:
                file_type = audio.split(".")[-1]
                if file_type not in file_types:
                    raise Exception('bad file_type: %s' % file_type)
                else:
                    file_type = "." + file_type
                with tempfile.NamedTemporaryFile(suffix=file_type, delete=False) as temp_file:
                    audio_file_path = temp_file.name
                    print("audio_file_path")
                    print(audio_file_path)
                    print("file_type")
                    print(file_type)
                    subprocess.run(["wget", "-O", audio_file_path, audio])
                    audio = audio_file_path
            self.prompt = self.speech_to_text("whisper-1", audio)["text"]
            prompt = self.prompt
            pass
        
        messages = self.process_messages(messages, prompt.text, None, system)
        model = self.determine_model(model, messages)
        self.method = 'chat'
        self.prompt = prompt
        self.system = system
        self.temperature = temperature
        self.model = model
        self.files = None
        self.method = 'chat'
        results = self.request_complete( **kwargs)
        audio = self.text_to_speech("tts-1-hd", results['text'], voice, "mp3", 1)
        return {
            'text': audio["audio"],
            'done': True
        }
        
    def determine_model(self, model, messages):
        model_type = ""
        this_max_tokens = self.max_tokens

        if "gpt-4" in model:
            model_type = "gpt-4"
        elif "gpt-3" in model:
            model_type = "gpt-3"

        if "instruct" in model:
            model_type = "instruct"
        
        if "vision" in model:
            model_type = "vision"

        chosen_model = None
        max_tokens = {
            "gpt-4": 8192,
            "gpt-4-32k":32768,
            "gpt-4-1106-preview": 128000,
            "gpt-4-vision-preview": 128000,
            "gpt-3.5-turbo": 4096,
            "gpt-3.5-turbo-instruct": 4096,
            "gpt-3.5-turbo-16k": 16385,
            "gpt-3.5-turbo-1106": 16385,
        }
        stringifed_messages = ""
        stringified_messages = json.dumps(messages)
        if "image_url" in stringified_messages:
            model_type = "vision"
            pass
        message_tokens = self.tokenize(stringifed_messages, model)
        num_tokens = len(message_tokens) + this_max_tokens
        if model_type != "vision" and model_type != "instruct":

            if model_type == "gpt-3":
                for model in max_tokens:
                    if "gpt-3" in model:
                        if num_tokens < max_tokens[model]:
                            chosen_model = model
                            model_type = "chosen"
                            break
                    else:
                        pass
                if chosen_model is None:
                    model_type = "gpt-4"    
                pass
            if model_type == "gpt-4":
                for model in max_tokens:
                    if "gpt-4" in model:
                        if num_tokens < max_tokens[model]:
                            chosen_model = model
                            model_type = "chosen"
                            break
                    else:
                        pass
                if chosen_model is None:
                    raise Exception("bad model: %s" % model)
                pass
        else:
            if model_type == "instruct":
                for model in max_tokens:
                    if "instruct" in model:
                        if num_tokens < max_tokens[model]:
                            chosen_model = model
                            model_type = "chosen"
                            break
                        else:
                            pass
                if chosen_model is None:
                    raise Exception("bad model: %s" % model)
                pass
            elif model_type == "vision":
                for model in max_tokens:
                    if "vision" in model:
                        if num_tokens < max_tokens[model]:
                            chosen_model = model
                            model_type = "chosen"
                            break
                        else:
                            pass
                if chosen_model is None:
                    raise Exception("bad model: %s" % model)
                pass
            else:
                raise Exception("bad model: %s" % model)
                pass

        return chosen_model


    def process_messages(self, messages, prompt, files, system):
        messagesList = []
        new_files = []
        if files is not None:
            if type(files) is not list:
                raise Exception('bad files: %s' % files)
            for image in files:
                if "url" not in image:
                    raise Exception('bad url: %s' % image)
                if "detail" not in image:
                    this_detail = "auto"
                this_url = image['url']
                this_detail = image['detail']
                #this_url = convert_image_base64(this_url)
                image['url'] = this_url
                image['detail'] = this_detail
                new_files.append(image)
            pass
 
        template = chat_templates[0]

        if system is not None:
            if system != "":
                systemDict = {"role": "system", "content": system}
            else:
                systemDict = {"role": "system", "content": template['system_msg']}
                pass
            messagesList.append(systemDict)
            pass

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
            elif m['role'] == 'system':
                if "text" in m:
                    systemDict = {"role": "system", "content": m['content']}
                elif "content" in m:
                    systemDict = {"role": "system", "content": m['content']}
                messagesList.append(systemDict)
            else:
                raise Exception('bad role: %s' % m['role'])

        addToMessages = False
        if (files is not None or prompt is not None):
            if files is not None:
                if (len(files) > 0):
                    addToMessages = True
                    pass
                pass
            if prompt is not None:
                if len(prompt) > 0:
                    addToMessages = True
                    pass
                pass
            pass
        if len(messages) == 0:
            addToMessages = True
            pass
        elif messages[-1]['role'] == 'assistant':
            if addToMessages == False:
                raise Exception("bad prompt: %s" % prompt)
                pass
    
            if messages[-1]['role'] == 'user':
                if addToMessages == False:
                    self.messages = messagesList
                    pass
            pass
        if addToMessages == True:
            lastMessages = {}
            lastMessages['role'] = 'user'
            if (files is not None and len(files) > 0):
                lastMessages['content'] = []
                lastMessages['content'].append({"type": "text", "text": prompt})
                for image in files:
                    lastMessages['content'].append({"type": "image_url", "image_url": {"url": image['url'], "detail": image['detail']}})

            else:
                lastMessages['content'] = prompt
                pass

            messagesList.append(lastMessages)
            self.messages = messagesList
        return messagesList

if __name__ == '__main__':
    #main()
    pass