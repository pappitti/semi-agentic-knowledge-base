import json
from bs4 import BeautifulSoup
import requests
from openai import OpenAI
from datetime import datetime
import re
import os
import fitz
import django
import random
from django.utils.text import slugify
from django.core.cache import cache

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 's_a_k_b.settings')
django.setup()

from django.conf import settings

LLM_API_KEY=settings.LLM_API_KEY
LLM_API_URL=settings.LLM_API_URL
LLAMA_CPP_SERVER_URL=settings.LLAMA_CPP_SERVER_URL
MEDIA_ROOT=settings.MEDIA_ROOT

from backend.models import LoggedDoc, Author, Category, DocImage, Country, ProcessingLog
from articles.forms import AuthorFormset, CategoryFormset, CountryFormset, LoggedDocForm


class OutputTemplate:
    '''
    Model template for reference. If you adjust to your model, 
    make sure to adjust the grammars and json formats accordingly in 
    generate_llm, generate_short_llm and check_llm functions below
    '''
    def __init__(self):
        self.url = None
        self.authors = []
        self.title = None
        self.slug = None
        self.overview = None
        self.summary = None
        self.summary_type = None
        self.categories = []
        self.countries = []
        self.date_published = None
        self.model_used = None
        self.thumbnail = []

    def to_dict(self):
        '''removing any attributes that may be added to the object 
        during the pipeline but that we do not want to return in the JSON'''
        
        return {
            "url": self.url,
            "authors": self.authors,
            "title": self.title,
            "slug": self.slug,
            "overview": self.overview,
            "summary": self.summary,
            "summary_type": self.summary_type,
            "categories": self.categories,
            "countries": self.countries,
            "date_published": self.date_published,
            "model_used": self.model_used,
            "thumbnail": self.thumbnail
        }

## UTILS

def url_to_slug(url): #couldn't be sure that Django's slugify function would work with all URLs
        ''' Converts a URL to a slug. This is the last resort if scraping fails 
        or LLM can't handle it. Slugs are used to identify articles in the DB and are essential for routing '''
        
        # Lowercase the url
        slug = url.lower()
        # Removes http
        slug = slug.replace("http", "")
        # Remove special characters using slugify or, if outside Django, regular expression : re.sub(r'[^a-z0-9-]', '', slug) 
        slug = slugify(slug)
        
        return slug

def date_reformat(date_string): #LLM sometimes returns dates separated by wrong special characters. This function fixes it

    # Extract year, month, and day using regular expressions
    match = re.match(r'(\d{4}).(\d{2}).(\d{2})', date_string)
    if not match:
        raise ValueError("Invalid date format")

    year, month, day = match.groups()

    # Convert to datetime to validate the date and format it
    try:
        formatted_date = datetime(int(year), int(month), int(day)).strftime('%Y/%m/%d')
        return formatted_date
    except ValueError as e:
        raise ValueError(f"Invalid date: {e}")

## SCRAPING

def get_soup(url):
    ''' Getting the HTML content of a page '''

    new_article = OutputTemplate()
    new_article.url = url

    # Make a request to the URL. 
    r = requests.get(url)

    # If the request failed, an entry will still be created in the DB so users can manually add the data
    # but the rest of the pipeline will not be executed
    if r.status_code != 200:
        new_article.overview = "Could not retrieve article (url could not be parsed)"
        new_article.summary = "Could not retrieve article (url could not be parsed)"
        # add an attribute to the object to indicate that the request failed
        new_article.error = True
    
    #if request is successful and doc is a pdf
    elif r.headers.get('Content-Type') == 'application/pdf':
        # Parse the PDF
        doc = fitz.open(stream=r.content, filetype="pdf")

        text = ""   
        # get the metadata and append the text from the PDF
        metadata = doc.metadata
        for key, value in metadata.items():
            text += f"{key}: {value}\n"

        for page in range(min(5,len(doc))): #only the first 5 pages, more will likely be too much for the LLM
            text += doc[page].get_text()
            image_list = doc[page].get_images(full=True)

            for img in range(min(2,len(image_list))): #only the first 2 images per page
                xref = image_list[img][0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                new_article.thumbnail.append(image_bytes)

        # add an attribute to the object to pass the text
        new_article.pdf = text 
    
        doc.close()
 
    
    #if request is successful and doc is not a pdf
    else:
        # Parse the HTML
        soup = BeautifulSoup(r.content, 'html.parser')
        # add an attribute to the object to pass the parsed HTML
        new_article.soup = soup
        
        try:
            # get thumbnail url in header if any
            page_head = soup.select_one('head')
            illustration=page_head.find("meta",attrs={'property':'og:image'})

            # stores the image if any
            if illustration:
                new_r=requests.get(illustration.get("content"))
                if new_r.status_code==200:
                    new_article.thumbnail.append(new_r.content)
        
        except:
            pass

    # Return the pre-filled dictionary including the BeautifulSoup object or pdf text
    return new_article

def arxiv_soup(soup):
    ''' 
    Extracting data from an arxiv page.
    If this specific usecase is what you are interested in,
    checkout, this arxiv-focussed project : https://github.com/Nearcyan/papers.day
    '''

    page_content = soup.select_one('div.leftcolumn')
    authors = [author.get_text(strip=True) for author in page_content.select('div.authors a')]
    title = page_content.select_one('h1.title').get_text(strip=True)
    #title can be null or blank in theory (according to the model) but it is not practical for the admin interface
    if not title:
        title = "_" 

    categories = [category.get_text(strip=True) for category in page_content.select('.tablecell.subjects .primary-subject')]
    publication_dates =page_content.select_one('div.submission-history').get_text(strip=True)
    position=publication_dates.find("[v1]")
    
    if position!=-1:
        publication_date=publication_dates[position+len("[v1]"):position+len("[v1]")+18]
    
    else:
        publication_date=publication_dates
    
    match=re.search(r'\w\w\w, \d+ \w\w\w \d\d\d\d', publication_date)
    
    if match:
        date_part = match.group()

        # Parsing the date
        date_obj = datetime.strptime(date_part, '%a, %d %b %Y')

        # Formatting the date as YYYY/MM/DD
        formatted_date = date_obj.strftime('%Y/%m/%d')
        publication_date=formatted_date

    abstract_with_links = page_content.select_one('blockquote.abstract')
    
    #voluntarily keeping the links but changing the attributes to reuse the entire HTML tag withthe app's css
    # for link in abstract_with_links.find_all('a'):
    #     link['class'] = ['external-link']
    #     link['target'] = '_blank'
    #     link['rel'] = 'noopener noreferrer nofollow'
    
    #commented-out the above out of security concerns. should be fine for Arxiv but activate it at your own risk
    # you would need to add |safe in the articles:document_details template {{document.summary}} to render the HTML with tags
    # in the meantime, we just extract the text
    abstract_with_links=abstract_with_links.get_text(strip=True)

    match=re.search(r'Abstract:</span>(.*?)</blockquote>', str(abstract_with_links), re.DOTALL)
    
    if match:
        abstract_with_links = match.group(1).strip()
    
    else:
        abstract_with_links = str(abstract_with_links)
    
    output={
        'title': title[6:],
        'authors': authors,
        'publication_date': publication_date,
        'categories': categories,
        'abstract_with_links': abstract_with_links
    }

    # Return the extracted data
    return output

def youtube_soup(soup):
    ''' Extracting the data from a youtube page '''

    page_head = soup.select_one('head')
    title=page_head.find("title").get_text(strip=True)
    #title can be null or blank in theory (according to the model) but it is not practical for the admin interface
    if not title:
        title = "_"

    description=page_head.find("meta",attrs={'name': 'description'}).get("content")
    categories=page_head.find("meta",attrs={'name': 'keywords'}).get("content")
    publication_date=soup.select_one(".ytd-watch-metadata #date-text")
    
    if publication_date:
        publication_date=publication_date.get_text(strip=True)
    
    
    #author not working, to be investigated
    author=soup.find("ytd-channel-name", id="channel-name")
    
    if author:
        author=[author.get_text(strip=True)]

    output={
        'title': title,
        'authors': author,
        'abstract': description,
        'publication_date': publication_date,
        'categories':categories.split(", ")
    }

    return output

## LLM UTILS

def chat_params(chat_format, prompt):
    '''simplification of chat templates used by Transformers (we do not really need jinja templating here 
    given we are just doing a completion). Templating may be an overkill for this use case (large models tend 
    to handle different chat formats very well) but we stick to it.In case of doubt, pick ChatML'''
    
    if chat_format=="chatml":
        return {"stop_token":'<|im_end|>',
                "prompt_format" : f"""<|im_start|> system \n
                                    {prompt[0]["content"]} <|im_end|> \n
                                    <|im_start|> {prompt[1]["content"]} <|im_end|> \n
                                    <|im_start|> assistant
                                    """
                }
    elif chat_format=="llama-chat":
        return {"stop_token":"</s>", #not sure about bos_token and eos_token for LLama
                "prompt_format" : f"""<s>[INST] <<SYS>>\n
                                    {prompt[0]["content"]}\n 
                                    <</SYS>> \n\n
                                    {prompt[1]["content"]}[/INST]
                                    """
                }
    elif chat_format=="mistral-instruct":
        return {"stop_token":"</s>",
                "prompt_format" : f"""<s>[INST] 
                                    {prompt[0]["content"]}\n
                                    {prompt[1]["content"]} [/INST]
                                    """
                }
    else:
        return {"stop_token":'<|im_end|>'}
    
def get_grammar(grammar_size): 
    ''' Returns the grammar to use based on the size of the expected
    Adapt the grammar to match your model. This might help: https://grammar.intrinsiclabs.ai/
     :grammar_size: "long" or "short" '''

    #TODO : for now the list of categories and countries are omitted. TBC if we want to add constraints on the outputs to match the vales in DB. 
    #For now, the working assumption is that the model will set categories and countries, and we will retrieve the most relevant ones from the DB using embeddings

    # grammar to extract information from scraping data that haven't been be-processed
    if grammar_size=="long":
        grammar=r'''
            root ::= Article
            Summaries ::= "{"   ws   "\"short_summary\":"   ws   string   ","   ws   "\"long_summary\":"   ws   string   "}" ws
            Summarieslist ::= "[]" | "["   ws   Summaries   (","   ws   Summaries)*   "]" ws
            Metadata ::= "{"   ws   "\"authors\":"   ws   stringlist   ","   ws   "\"title\":"   ws   string   ","   ws   "\"slug\":"   ws   string   ","   ws   "\"categories\":"   ws   Categorieslist   ","   ws   "\"countries\":"   ws   Countrieslist   ","  ws   "\"date_published\":"   ws   string   "}" ws
            Metadatalist ::= "[]" | "["   ws   Metadata   (","   ws   Metadata)*   "]" ws
            Article ::= "{"   ws   "\"metadata\":"   ws   Metadata   ","   ws   "\"summaries\":"   ws   Summaries   "}" ws
            string ::= "\""   ([^"]*)   "\"" ws
            boolean ::= "true" | "false" ws
            ws ::= ([ \t\n] ws)?
            number ::= [0-9]+   "."?   [0-9]*
            stringlist ::= "["   ws   "]" | "["   ws   string   (","   ws   string)*   ws   "]" ws
            numberlist ::= "["   ws   "]" | "["   ws   number   (","   ws   number)*   ws   "]" ws
            Categorieslist ::= "["   ws   "]" | "["   ws   string   (","   ws   string)*   ws   "]" ws
            Countrieslist ::= "["   ws   "]" | "["   ws   string   (","   ws   string)*   ws   "]" ws
            '''
    
    if grammar_size=="short":
        #only for missing metadata after scraping Arxiv
        grammar=r'''
            root ::= Article
            Metadata ::= "{"   ws   "\"slug\":"   ws   string   ","   ws   "\"categories\":"   ws   Categorieslist   ","   ws   "\"countries\":"   ws   Countrieslist   "}" ws
            Metadatalist ::= "[]" | "["   ws   Metadata   (","   ws   Metadata)*   "]" ws
            Article ::= "{"   ws   "\"metadata\":"   ws   Metadata   ","   ws   "\"short_summary\":"   ws   string  "}" ws
            string ::= "\""   ([^"]*)   "\"" ws
            boolean ::= "true" | "false" ws
            ws ::= ([ \t\n] ws)?
            number ::= [0-9]+   "."?   [0-9]*
            stringlist ::= "["   ws   "]" | "["   ws   string   (","   ws   string)*   ws   "]" ws
            numberlist ::= "["   ws   "]" | "["   ws   number   (","   ws   number)*   ws   "]" ws
            Categorieslist ::= "["   ws   "]" | "["   ws   string   (","   ws   string)*   ws   "]" ws
            Countrieslist ::= "["   ws   "]" | "["   ws   string   (","   ws   string)*   ws   "]" ws
            '''
    return grammar

## LLM CALLS

def run_openai(prompt, api_url, api_key, model="gpt-3.5-turbo-1106"): 
    ''' Calls the OpenAI API 
    :model: gpt-3.5-turbo-1106 or gpt-4-1106-preview only for now as it is the only one that returns a JSON object
    list of models here: https://platform.openai.com/docs/models.
    '''
    
    client = OpenAI(base_url=f"{api_url}", api_key=api_key)
    
    try : 
        # call to the API
        #TODO: when other LLM API providers can provide json, automate stop token based on chat format in order 
        #to extend function to other models delivered by other LLM API providers
        response = client.chat.completions.create(
            model=model,
            messages=prompt,
            temperature=0.8,
            max_tokens=2000,
            top_p=0.95,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            response_format={ "type": "json_object" },
            stop=None 
        )

        return {"content":response.choices[0].message.content.strip(), "model":response.model.strip()}
        
    except Exception as e:
        # building a response object to match the one returned when request is successful so that it can be processed in the same way
        return {"model - error":str(e),"content":{}, "model":model}


def run_ggml(prompt, api_url, grammar, chat_format="chatml"):
    ''' Calls the llama.cpp server'''

    # convert the prompt to the appropriate format for the chat format
    completion_params=chat_params(chat_format, prompt)
    
    if completion_params.get("prompt_format",None) is None:
        prompt_format=prompt
    
    else:
        prompt_format=completion_params["prompt_format"]

    data={"temperature":0.8,
          "top_p":0.95,
          "frequency_penalty":0.0,
          "presence_penalty":0.0,
          "n_predict":2000,
          "stop":[completion_params["stop_token"]],
          "grammar":grammar,
          "prompt":prompt_format
        }
    
    headers={"Content-Type": "application/json"}

    try:
        #actual call to the server
        response = requests.post(
            f"{api_url}/completion",headers=headers, data=json.dumps(data),
        ).json()
        
        return {"content":response["content"].strip(), "model":response["generation_settings"]["model"].strip()}
    
    except Exception as e:
        # building a response object to match the one returned when request is successful so that it can be processed in the same way
        return {"model - error":str(e),"content":{}, "model":"llama.cpp server"}

def get_chat_completion(complete_prompt, client, grammar, chat_format, model): 
    ''' Calls the appropriate API based on user choice 
    :client: "openai" or "llama_cpp_server"
    '''

    if client == "openai":
        # TODO: add chat format choice when other LLM API providers can provide json
        # for now, chat format is not releavant for OpenAI
        completion = run_openai(complete_prompt, LLM_API_URL, LLM_API_KEY, model)
        
    elif client == "llama_cpp_server":
        # Note : model choice is not relevant for llama.cpp server as model is defined when the server is launched. 
        # A model able to process at least 16k tokens is recommended (gpt-3.5-turbo-1106 is 16k)
        completion = run_ggml(complete_prompt, LLAMA_CPP_SERVER_URL, grammar, chat_format) 

    else:
        #TODO: add others?
        completion = {"model - error": "Invalid client type", "content": {}, "model": "Invalid client type"}
    
    return completion

def generate_llm(prompt_input, client, chat_format, model):
    ''' Prepares the prompt, calls the API and returns the response in an appropriate JSON format 
     :client: "openai" or "llama_cpp_server"
    '''

    #adapt the json schema to match your model
    system_prompt = f"""
    You are a helpful assistant specialized in extracting information from unstructured articles. You are asked to extract metadata from the article provided by the user and write two summaries of the article, a short summary and a long summary. You have a strict methodology:
     - the slug must be a string un lowercase with no white spaces;
     - the short summary must not exceed 100 words and must include the names of the authors;
     - the long summary must not exceed 300 words;
     - You respond in a JSON format strictly following the model : {{ "metadata":{{"authors": list[str], "title": str, "slug": str, "categories": list[str], "countries": list[str], "date_published": str formatted as "YYYY/MM/DD"}}, "summaries":{{ "short_summary": str, "long_summary": str}}}};
     - if there is no value for a key, you must respond with an empyt string;
     - The response must be a dictionary with the following keys: metadata, summaries;
     - You must make sure that the JSON is valid, do not forget the commas and the brackets and do not add new lines;
     - You must not respond with anything else than the JSON. Do not add any text or comment.
    """
    user_prompt = f"""{prompt_input}"""
    complete_prompt = [{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}]

    grammar=get_grammar("long")

    completion=get_chat_completion(complete_prompt, client, grammar, chat_format, model) 
    
    return json.dumps(completion)

def generate_short_llm(prompt_input, client, chat_format, model): 
    ''' Prepares the prompt for what couldn't be scraped from Arxiv, calls the API and returns the response in an appropriate JSON format 
     :client: "openai" or "llama_cpp_server"'''

    #adapt the json schema to match your model
    system_prompt = f"""
    You are a helpful assistant specialized in extracting information from unstructured articles. You are asked to extract metadata from the article provided by the user and write a short summary. You have a strict methodology:
     - the slug must be a string un lowercase with no white spaces;
     - the short summary must not exceed 100 words and must include the names of the authors;
     - You respond in a JSON format strictly following the model : {{ "metadata":{{"slug": str, "categories": list[str], "countries": list[str]}}, "short_summary": str}};
     - if there is no value for a key, you must respond with an empyt string;
     - The response must be a dictionary with the following keys: metadata, short_summary;
     - You must make sure that the JSON is valid, do not forget the commas and the brackets and do not add new lines;
     - You must not respond with anything else than the JSON. Do not add any text or comment.
    """
    user_prompt = f"""{prompt_input}"""
    complete_prompt = [{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}]

    grammar=get_grammar("short")

    completion=get_chat_completion(complete_prompt, client, grammar, chat_format, model) 
    
    return json.dumps(completion)

def check_llm(prompt_input, client, chat_format, model): 
    ''' Prepares the prompt to check a wrong json, calls the API and returns the response in an appropriate JSON format 
     :client: "openai" or "llama_cpp_server"'''

    #adapt the json schema to match your model
    system_prompt = f"""
    You are a helpful assistant in charge of correcting an erroneous json file. The expected format was :
     {{ "metadata":{{"authors": list[str], "title": str, "slug": str, "categories": list[str], "countries": list[str], "date_published": str formatted as "YYYY/MM/DD"}}, "summaries":{{ "short_summary": str, "long_summary": str}}}};

     However, the json file you received was : {prompt_input}
    """

    user_prompt = f""" Please fix the json file to match the expected format. You must make sure that the JSON is valid, do not forget the commas and the brackets and do not add new lines. You must not respond with anything else than the JSON. Do not add any text or comment.
    """
    complete_prompt = [{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}]

    grammar=get_grammar("long")

    completion=get_chat_completion(complete_prompt, client, grammar, chat_format, model) 
    
    return json.dumps(completion)

def check_short_llm(prompt_input, client, chat_format, model): 
    ''' Prepares the prompt to check a wrong json, calls the API and returns the response in an appropriate JSON format
      :client: "openai" or "llama_cpp_server" '''

    #adapt the json schema to match your model
    system_prompt = f"""
    You are a helpful assistant in charge of correcting an erroneous json file. The expected format was :
     {{ "metadata":{{"slug": str, "categories": list[str], "countries": list[str]}}, "short_summary": str}};

     However, the json file you received was : {prompt_input}
    """

    user_prompt = f""" Please fix the json file to match the expected format. You must make sure that the JSON is valid, do not forget the commas and the brackets and do not add new lines. You must not respond with anything else than the JSON. Do not add any text or comment.
    """
    complete_prompt = [{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}]

    grammar=get_grammar("short")

    completion=get_chat_completion(complete_prompt, client, grammar, chat_format, model) 
    
    return json.dumps(completion)

## DATABASE UTILS

def extract_to_OutputTemplate(article, response):
    ''' Extracting the data from the response and adding it to a OutputTemplate object '''
    
    # if the model failed, an entry is added to the DB so users can manually add the data
    if response.get("model - error"):
        article.summary="could not use LLM "+ response.get("model - error")
        article.overview="could not use LLM "
        article.slug=url_to_slug(article.url) # slug cannot be null or blank and are essential for routing
    
    else:
        model_output=response.get("content",{})
        model_output=json.loads(model_output)
        article.title=model_output.get("metadata",{"title":"_"}).get("title","_") #title can be null or blank in theory (according to the model) but it is not practical for the admin interface
        article.overview=model_output.get("summaries",{}).get("short_summary",None)
        article.summary=model_output.get("summaries",{}).get("long_summary",None)
        article.categories=model_output.get("metadata",{}).get("categories",[])
        article.countries=model_output.get("metadata",{}).get("countries",[])
        article.date_published=model_output.get("metadata",{}).get("date_published",None)
        article.authors=model_output.get("metadata",{}).get("authors",[]) 
        article.slug=model_output.get("metadata",{"slug":"temp-slug"}).get("slug","temp-slug") # slug cannot be null or blank and are essential for routing
    
    return article

def short_extract_to_OutputTemplate(article, response):
    ''' Extracting the data from the response and adding it to a OutputTemplate object '''
    
    # if the model failed, an entry is added to the DB so users can manually add the data
    if response.get("model - error"):
        article.overview="could not use LLM "+ response.get("model - error")
        article.slug=slugify(article.title) # slug cannot be null or blank and are essential for routing
    
    else:
        model_output=response.get("content",{})
        model_output=json.loads(model_output)
        article.overview=model_output.get("short_summary",None)
        article.slug=model_output.get("metadata",{"slug":"temp-slug"}).get("slug","temp-slug") # slug cannot be null or blank and are essential for routing
        additional_categories=model_output.get("metadata",{}).get("categories",[])
        article.categories=article.categories+additional_categories
        article.countries=model_output.get("metadata",{}).get("countries",[])
    
    return article

def response_log(process_log, response):
    ''' Adding the LLM response to the process log'''
    
    # log if the model failed
    if response.get("model - error"):
        process_log["llm_output"]=response.get("model - error")
        process_log["success"]=False
    
    # otherwise, log the response
    else:
        process_log["llm_output"]=response.get("content",{})

    return process_log

def check_slug(slug):
    ''' Check if the slug is unique and append a random number at the end if it is not'''

    #make sure slugs provided by llm do not incude special characters
    slug=slugify(slug)

    #recursive function to add a random number at the end of the slug until it is unique
    try:
        LoggedDoc.objects.get(slug=slug)
        return check_slug(slug+str(random.randint(0, 9)))
    
    except LoggedDoc.DoesNotExist:
        return slug

## DATABASE ENTRY

def add_to_db(article, process_log):
    ''' Adding the data to the DB 
    article and process_logs are dictionaries populated in the pipeline'''
    
    #add log to DB
    to_log=ProcessingLog(task_id=process_log["task_id"],
                        source_url=process_log["url"], 
                        success=process_log.get("success",True), 
                        llm=article.get("model_used",None), 
                        llm_output=process_log.get("llm_output",None), 
                        llm_turns=process_log.get("turns",None))

    to_log.save()

    # make sure slugs are unique
    slug=check_slug(article["slug"])

    try:
        date_reformat(article["date_published"])
        pub_date=datetime.strptime(article["date_published"], '%Y/%m/%d').date()
    
    # in case of error, we use the current date as fallback
    #This is particularly relevant for Youtube videos as we can't get the publication date via scraping. 
    #API call to Youtube could be used to get the publication date. In the meantime, we use the current date as fallback
    except:
        pub_date=datetime.now().date() 
    
    #title can be null or blank in theory (according to the model) but it is not practical for the admin interface
    #given the checks performed in extract_to_OutputTemplate, there should not be any null or blank title but we keep the check just in case
    if not article["title"]:
        title="_" 
    else:
        title=article["title"]

    try:
        logged_doc = LoggedDoc.objects.get(source_url=article["url"])
    except LoggedDoc.DoesNotExist:
        logged_doc = None
        
    form_input={'slug':slug,
                    'title':title, 
                    'source_url':article["url"], 
                    'publication_date':pub_date, 
                    'overview':article["overview"],
                    'summary_type':article["summary_type"], 
                    'summary':article["summary"], 
                    'comment':None, 
                    'llm':article["model_used"], 
                    'is_draft':True}
        
    form=LoggedDocForm(form_input, instance=logged_doc)

    #only try to save the document if the form is valid
    if form.is_valid():
        to_add=form.save()

        #LLM may not return an empty list but None. Youtube may not identify the authors at all
        #only create an entry if the pair (author, doc) does not exist already
        if article["authors"] is None:
            article["authors"]=[]
        for author in article["authors"]:
            Author.objects.get_or_create(name=author, doc=to_add)

        if article["categories"] is None:
            article["categories"]=[]
        for category in article["categories"]:
            Category.objects.get_or_create(category_name=category, doc=to_add)

        if article["countries"] is None:
            article["countries"]=[]
        for country in article["countries"]:
            Country.objects.get_or_create(country_name=country, doc=to_add)

        if len(article["thumbnail"])>0:
            #create new images in DB
            for index in range(len(article["thumbnail"])):
                file_name = f"{to_add.slug}_{index}.png"
                image_path = os.path.join(MEDIA_ROOT, 'images', file_name)

                # Ensure the directory exists
                os.makedirs(os.path.dirname(image_path), exist_ok=True)

                # Write the image bytes to a file.
                with open(image_path, 'wb') as image_file:
                    image_file.write(article["thumbnail"][index])

                relative_path=os.path.join('images', file_name)

                new_image, created=DocImage.objects.get_or_create(image_url=relative_path, doc=to_add)

                if index==0:
                    #set first image as default
                    to_add.default_image=new_image
                    to_add.save()

    else:
        print("form invalid", form.errors)


## PROCESSING
    
def progress_update(task_id, total_docs, processed_docs, failed_docs, doc_category, current_doc, processing_step):
    ''' Updates the progress of the task in the cache 
    :task_id: string generated by process is launched. See template newdocs.pre_processing_block
    :total_docs: total number of documents to process
    :processed_docs: number of documents already processed
    :failed_docs: dictionary including a count and a list of documents that failed during the process
    :doc_category: "Arxiv", "Youtube" or "Others" for each for loop in the processing pipeline
    :current_doc: url of the document currently being processed
    :processing_step: information about the current step of the pipeline'''

    progress={"completed":processed_docs,
              "total":total_docs,
              "failed_docs":failed_docs, 
              "progress":processed_docs/max(total_docs,1)*100, 
              "current_category":doc_category, 
              "current_doc":current_doc, 
              "processing_step":processing_step}
    
    cache.set(f"progress_task_{task_id}", progress)

## MAIN

def processing_start(docs, client, chat_format, model, task_id):
    ''' Going through the list of URLs and extracting the data from each of them'''
    print("Received", docs, client) 
    total_docs=len(docs['youtube'])+len(docs['arxiv'])+len(docs['others'])
    processed_docs = []
    failed_docs={"count":0, "docs":[]}

    #logging progress in cache so that it can be displayed in the UI
    progress_update(task_id, total_docs, len(processed_docs), failed_docs, None, None, "starting...")

    #Youtube URLs
    for article in docs["youtube"]:

        #logging progress in cache so that it can be displayed in the UI
        progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Youtube", article, "scraping started")
        new_article = get_soup(article) 

        # process logs (task_id, url, model, success, model_output.... ) are stored in DB for analysis and debugging purposes
        process_log={"task_id":task_id,"url":article}
        
        if not hasattr(new_article, 'error'):
            youtube=youtube_soup(new_article.soup)
            new_article.authors=youtube.get("authors",[])  
            new_article.title=youtube.get("title",None)
            new_article.slug=slugify(new_article.title)
            new_article.summary_type="Youtube video"
            new_article.summary=youtube.get("abstract",None)
            new_article.date_published=youtube.get("publication_date",None)
            new_article.categories=youtube.get("categories",[])
        
        else:
            new_article.slug=url_to_slug(article)
            failed_docs["count"]+=1
            failed_docs["docs"].append([article,new_article.slug])
            process_log["success"]=False
        
        #remove BeautifulSoup object and errors (and anything else we may have added to the object during the pipeline) to avoid JSON serialisation error
        new_article=new_article.to_dict() 

        #adds the article and process log to DB
        progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Youtube", article, "adding to database")
        add_to_db(new_article, process_log)

        processed_docs.append(new_article)
        progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Youtube", article, "complete")

    #Arxiv URLs
    for article in docs["arxiv"]:

        progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Arxiv", article, "scraping started")
        new_article = get_soup(article)

        # process logs (task_id, url, model, success, model_output.... ) are stored in DB for analysis and debugging purposes
        process_log={"task_id":task_id,"url":article}
        
        if not hasattr(new_article, 'error'):
            arxiv=arxiv_soup(new_article.soup)
            new_article.authors=arxiv.get("authors",[])  
            new_article.title=arxiv.get("title",None)
            new_article.summary_type="Arxiv abstract"
            new_article.summary=arxiv.get("abstract_with_links",None)
            new_article.date_published=arxiv.get("publication_date",None)
            new_article.categories=arxiv.get("categories",[])

            progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Arxiv", article, "scraping complete")

            if new_article.summary is None or new_article.title is None or new_article.authors==[] or new_article.date_published is None or new_article.categories==[]:
                # scraping failed, append to others to be processed entirely by the LLM
                docs["others"].append(article)
            
            else:
                # scraping successful, but some data is missing. We use the LLM to fill the gaps
                prompt=f'''Please extract metadata from the article provided below and write a short summary: \n
                            {new_article.title} \n 
                            {new_article.summary}'''
                
                progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Arxiv", article, "sent to LLM, awaiting response")

                response = json.loads(generate_short_llm(prompt, client, chat_format, model))

                progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Arxiv", article, "LLM response received")
                print(response)
                new_article.model_used=response.get("model",None)
                process_log["turns"]=1
                process_log=response_log(process_log, response)
                
                try:
                    new_article=short_extract_to_OutputTemplate(new_article, response)
                    # this throws an error if the JSON is invalid
                
                except json.JSONDecodeError as e:
                    # json healing attempt
                    progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Arxiv", article, "LLM response was invalid, attempting healing, awaiting second response")
                    response = json.loads(check_short_llm(response.get("content",{}), client, chat_format, model))
                    print(response)
                    process_log["turns"]+=1
                    process_log=response_log(process_log, response)
                    
                    try:
                        new_article=short_extract_to_OutputTemplate(new_article, response)
                        # this throws an error if the JSON is invalid
                        
                        if not response.get("model - error"):
                            process_log["success"]=True
                    
                    except json.JSONDecodeError as err:
                        progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Arxiv", article, "second LLM response was invalid")
                        new_article.slug=slugify(new_article.title)
                        new_article.overview = f'''{new_article.model_used} could not generate a valid JSON despite GBNF grammar.'''
                        failed_docs["count"]+=1
                        failed_docs["docs"].append([article,new_article.slug])
                        process_log["success"]=False
        
        else:
            new_article.slug=url_to_slug(article)
            failed_docs["count"]+=1
            failed_docs["docs"].append([article,new_article.slug])
            process_log["success"]=False

        #remove BeautifulSoup object and errors (and anything else we may have added to the object during the pipeline) to avoid JSON serialisation error
        new_article=new_article.to_dict()

        #adds the article and process log to DB
        progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Arxiv", article, "adding to database")
        add_to_db(new_article, process_log)

        processed_docs.append(new_article)
        progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Arxiv", article, "complete")

    #Other URLs
    for article in docs["others"]:

        progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Others", article, "scraping started")
        new_article = get_soup(article)
        progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Others", article, "scraping complete")
        
        # process logs (task_id, url, model, success, model_output.... ) are stored in DB for analysis and debugging purposes
        process_log={"task_id":task_id,"url":article}
        
        if not hasattr(new_article, 'error'):
                
            # in case of pdf
            if hasattr(new_article, 'pdf'):

                text=new_article.pdf

                #max characters with a bit of headroom for 16k context (could be tight for 8k). 
                #TODO: use tokenizer wih small vocab size to get a better approximation
                try:
                    context = text[:25000]
                
                except:
                    new_article.overview = "Could not retrieve article (parsing error)"
                    new_article.summary = "Could not retrieve article (parsing error)"
                    # add an attribute to the object to indicate that the request failed
                    new_article.error = True
                    new_article.slug=url_to_slug(article)
                    failed_docs["count"]+=1
                    failed_docs["docs"].append([article,new_article.slug])
                    process_log["success"]=False

            # in case of  any other format 
            elif hasattr(new_article, 'soup'):

                soup=new_article.soup
                
                # retreiving the url of first image on the page, if any
                progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Others", article, "retrieving illustration")
                try:
                    first_image=soup.find("img")
                    if first_image:
                        new_r=requests.get(first_image.get("src"))
                        if new_r.status_code==200:
                            new_article.thumbnail.append(new_r.content)
                
                except:
                    pass
                
                #max characters with a bit of headroom for 16k context (could be tight for 8k). 
                #TODO: use tokenizer wih small vocab size to get a better approximation
                try:
                    context = soup.body.get_text()[:25000]
                    # This throws an error if beautifulsoup fails to parse the page
                
                except:
                    new_article.overview = "Could not retrieve article (bs4 error)"
                    new_article.summary = "Could not retrieve article (bs4 error)"
                    # add an attribute to the object to indicate that the request failed
                    new_article.error = True
                    new_article.slug=url_to_slug(article)
                    failed_docs["count"]+=1
                    failed_docs["docs"].append([article,new_article.slug])
                    process_log["success"]=False
            
            if not hasattr(new_article, 'error'):
                new_article.summary_type="Description"
                prompt=f"Please extract metadata from the article provided below and write two summaries: \n {context}"

                progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Others", article, "sent to LLM, awaiting response")
                response = json.loads(generate_llm(prompt, client, chat_format, model))
                print(response)

                progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Others", article, "LLM response received")
                new_article.model_used=response.get("model",None)
                process_log["turns"]=1
                process_log=response_log(process_log, response)
                
                try:
                    new_article=extract_to_OutputTemplate(new_article, response)
                    # this throws an error if the JSON is invalid
                
                except json.JSONDecodeError as e:
                    # json healing attempt
                    progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Others", article, "LLM response was invalid, attempting healing, awaiting second response")
                    response = json.loads(check_llm(response.get("content",{}), client, chat_format, model))
                    print(response)
                    process_log["turns"]+=1
                    process_log=response_log(process_log, response)
                    
                    try:
                        new_article=extract_to_OutputTemplate(new_article, response)
                        # this throws an error if the JSON is invalid
                        if not response.get("model - error"):
                            process_log["success"]=True
                    
                    except json.JSONDecodeError as err:
                        progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Others", article, "second LLM response was invalid")
                        new_article.slug=url_to_slug(article)
                        new_article.overview = "Model could not generate a valid JSON"
                        new_article.summary = f'''{new_article.model_used} could not generate a valid JSON despite GBNF grammar.'''
                        failed_docs["count"]+=1
                        failed_docs["docs"].append([article,new_article.slug])
                        process_log["success"]=False
        
        else:
            new_article.slug=url_to_slug(article)
            failed_docs["count"]+=1
            failed_docs["docs"].append([article,new_article.slug])
            process_log["success"]=False

        #remove BeautifulSoup object and pdf attribute and errors (and anything else we may have added to the object during the pipeline) to avoid JSON serialisation error
        new_article=new_article.to_dict() 
        
        #adds the article and process log to DB
        progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Others", article, "adding to database")
        add_to_db(new_article, process_log)

        processed_docs.append(new_article)
        progress_update(task_id, total_docs, len(processed_docs), failed_docs, "Others", article, "complete")


    progress_update(task_id, total_docs, len(processed_docs), failed_docs, None, None, "finished")
