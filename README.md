# Semi-Agentic Knowledge Base

This app helps you curate your knowledge base by leveraging third-party Large Language Models to organize and classify your documents. It is dubbed "semi-agentic" as you can directly edit, delete and just create documents manually. But if you want to rely on AI, all you need to do is to paste URLs of HTML or PDF documents, and the model will do the heavy-lifting for you. 

This project is written in django with a small amount of vanilla javascript. It can currently use two OpenAI models using the openai python library, or any local model running on a separate llama.cpp server.  

[Visit our project page](https://www.pitti.io/projects/semi-agentic-knowledge-base) to learn more about the background, the motivations and the approach we took for this project.

Important warning : this is a demo app meant to experiment with information extraction automation. It is fit to run on device but giving access to third-parties would require material changes around authentication and, more generally, security features, even on a local network. 

## Installation
1. `python3 -m venv venv`
2. `source venv/bin/activate`
3. `pip install -r requirements.txt`
4. `cp .env.example .env`
5. `python manage.py migrate`

The last phase will create a brand new local database and seed some tables with information that is necessary for the app to work (e.g OpenAI models names or chat formats for local models)

## Running
1. First, set-up the .env file.    
If the .env file was copied from the .env.example as per the above, default values for the OpenAI endpoint and Llama.cpp server should be correct but you should take a minute to double-check.  
This app does not require an OpenAi API key to work, it can perfectly run entirely on local models, albeit it is materially slower. The SECRET_KEY is not necessary for Llama.cpp server but OpenAI will only work if you add a valid LLM_API_KEY to your .env file. In that case, make sure you have enough credits on your API billing plan.

2. Start the app with   
`python manage.py runserver`  
The app is typically accessible http://127.0.0.1:8000, check your terminal for more information. After that stage, the rest should be straight-forward.   

3. Optional but recommended: set-up a superuser account to access the admin console (typically available at http://127.0.0.1:8000/admin). 
`python manage.py createsuperuser`  
You will be able to see the LLM tasks log and change tables or fields that are not directly accessible through the app UI.  

## Working with LLMs
This app relies on LLMs' ability to return outputs in a JSON format. It does not leverage function calling. If the output format is incorrect, an entry may be added to the database so you can make manual adjustments but the fields may not be pre-populated. All processing tasks and LLM outputs for each url are logged and visible through the admin console.

- OpenAI  models  
gpt-3.5-turbo-1106 or gpt-4-1106-preview are the only models that return JSON objects without function calling. Make sure you have your API credentials appropriately set-up in the .env file and that you have enough credits on your API billing plan. Parameters for the OpenAI API call are available [here](newdocs/doc_processing.py#L351).
  
- Local models with Llama.cpp server  
You can use any model running on an active Llama.cpp server (i.e. actual server of Llama.cpp not from the llama_cpp-python library). By default, the llama.cpp server runs on port 8080 which is the default value in the .env.example file. Double-check that it is correct and, if not, that it does not conflict with the port where this app is running (by default 8000).  
This app leverages [GBNF grammars](newdocs/doc_processing.py#L302) to force local models to return outputs in a JSON format. Output format is not guaranteed and a feedback loop helps mitigating errors so, in theory, any model would work. However experiments show that larger models tend to perform significantly better than smaller ones. We also recommend using models with a context window of at least 16k if you plan to process rather long documents. Be aware that, if your local model processes input tokens at 100tokens/second, a 10k-token document will require over 1 minute and 40 seconds to process your prompt. Parameters for the Llama.cpp server call are available [here](newdocs/doc_processing.py#L380).    


Irrespective of the solution you choose, the document-processing script will truncate the content extracted from the document (HTML or PDF) to make sure it does not exceed 25k characters. Although there may be better ways to do this, setting this arbitrary number was a quick-but-effective solution to ensure that content would not exceed the context window. This leaves plenty of headroom if you work with a 16k-context-window model, but it may be tight for 8k. In any case, you can adjust this number [here](newdocs/doc_processing.py#L877).  
  

## Contributing  
If you go through the code, you will find out that it was written by someone with ideas for a product (some better and others) but limited talent in terms of actual software writing. Opportunities for improvement are everywhere, both on the idea-side or on the programming-side, so please contribute !


## Currently on TODO 
- Next iteration should include embeddings for summaries, notes and categories to enable semantic search.  
  
Other envisaged features include:
- Removing tags unicode blocks from scraped text to prevent prompt injection
- Supporting vision models to select the best image to use as thumbnail given a summary (particularly relevant for pdf extraction which sometimes yields random shapes)
- Supporting other models via the OpenAi library (or other methods alongside OpenAi and Llama.cpp) and combine with other tools to force JSON outputs (e.g pydantic-based approaches)  
  

## Credits and acknowledgements
A number of projects have inspired this one in some way, but [this one](https://github.com/Nearcyan/papers.day) has been particularly instrumental.     
Also, even if it's not really the spirit of this section, it would only be fair to thank OpenAi given how much work GPT4 has done on this project... 



