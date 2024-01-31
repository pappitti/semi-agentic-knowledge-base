import json
from threading import Thread
from urllib.parse import urlparse

from django.shortcuts import render
from django.http import JsonResponse
from django.core.cache import cache

from newdocs.doc_processing import processing_start
from articles.forms import AuthorFormset, CategoryFormset, CountryFormset
from backend.models import LoggedDoc, ChatFormat, OpenaiModel, ProcessingLog

## UTILS

def validate_url(url):
    '''
    Check if the url is valid
    '''
    # Remove unwanted quotes and whitespace
    url = url.strip(" '\"`")
    url = url.rstrip("/") #this helps avoiding duplicates
    
    parsed = urlparse(url)
    is_valid = bool(parsed.scheme) and bool(parsed.netloc)
    
    return url if is_valid else None

def classify_urls(urls): #urls is a list of strings
    '''
    classify urls 
    '''

    data = {"arxiv":[], "youtube":[], "others":[]}

    for url in urls:
        if "https://arxiv.org/abs" in url:
                    data["arxiv"].append(url)
                
        elif "youtube.com/watch" in url:
            data["youtube"].append(url)
        
        else:
            data["others"].append(url)

    return data

def augment_urls(urls): #urls is a list of strings
    '''
    check if urls exist in the database and add information about the last processing
    '''

    augmented_urls = []

    for url in urls:
        url_info = {"url":url, "exists":False, 'slug':None, "last_processing":None, "was_success":None, "output":None, 'model':None}

        #check if the url already exists in the database
        try:
            existing_doc = LoggedDoc.objects.get(source_url=url)
            url_info["exists"]=True
            url_info["slug"]=existing_doc.slug
            last_processing=ProcessingLog.objects.filter(source_url=url).order_by('-created_at').first()
        
            if last_processing is not None:
                url_info["last_processing"]=last_processing.created_at
                url_info["was_success"]=last_processing.success
                url_info["output"]=last_processing.llm_output
                url_info["model"]=last_processing.llm

        except LoggedDoc.DoesNotExist:
            pass

        augmented_urls.append(url_info)

    return augmented_urls

## VIEWS 

def new_docs(request):
    '''
    Initial stage of addition pipeline
    '''

    return render(request, 'newdocs/add_new_docs.html')

def manual(request):
    ''' 
    If user wants to add a document manually
    This loads the same template as when an existing entry is edited
    except that the form is empty
    '''

    document=LoggedDoc()
    author_formset = AuthorFormset(request.POST or None, instance=document)
    category_formset = CategoryFormset(request.POST or None, instance=document)
    country_formset = CountryFormset(request.POST or None, instance=document)
    docimages = []

    context = {'document': document, 
             'author_formset': author_formset, 
             'category_formset': category_formset, 
             'country_formset': country_formset,
             'docimages':docimages}

    return render(request, 'articles/edit_doc.html',context)

def add_new_docs(request):
    '''
    This is the second stage of the addition pipeline
    urls provided at first stage are pre-processed and users can review the results
    user will then be able to select options for processing
    '''

    if request.method == 'POST':
        #retrieves the entire string of urls and break it down into a list of urls
        urls_input = request.POST.get('url')
        urls = [url.strip() for url in urls_input.split(',')]

        #remove empty strings from the list and trailing slashes
        urls = [validate_url(url) for url in urls]
        urls = [url for url in urls if url != None]
        

        #in this app, arxiv, youtube and others websites will be dealt with differently. We split them into different lists
        data = classify_urls(urls)

        #converts list into a list of dictionaries with extra information on the urls if they already exist in the database
        urls = augment_urls(urls)

        # Count the number of URLs in each category
        counts = {key: len(value) for key, value in data.items()}

        # Check for duplicates
        duplicates = [url for url in urls if url["exists"]]
        new_entries = [url for url in urls if not url["exists"]]

        #list of Openai-compatible models and chatformats for llama.cpp
        models = OpenaiModel.objects.all()
        chat_formats = ChatFormat.objects.all()

        context = {'counts': counts, 
                 'urls': urls, 
                 'duplicates': duplicates,
                 'new_entries': new_entries,
                 'models': models, 
                 'chat_formats': chat_formats}

        return render(request, 'newdocs/pre_processing_block.html', context)
    
    else:
        # Handle non-POST request, fallback to default
        return render(request, 'newdocs/add_new_docs.html')

def resubmit_document(request, document_slug):
    '''Starting a submission process from step 2'''

    url = LoggedDoc.objects.get(slug=document_slug).source_url

    urls = [validate_url(url)]

    #in this app, arxiv, youtube and others websites will be dealt with differently. We split them into different lists
    data = classify_urls(urls)

    #converts list into a list of dictionaries with extra information on the urls if they already exist in the database
    urls = augment_urls(urls)

    # Count the number of URLs in each category
    counts = {key: len(value) for key, value in data.items()}

    # Check for duplicates
    duplicates = [url for url in urls if url["exists"]]
    new_entries = [url for url in urls if not url["exists"]]

    #list of Openai-compatible models and chatformats for llama.cpp
    models = OpenaiModel.objects.all()
    chat_formats = ChatFormat.objects.all()

    context = {'counts': counts, 
                'urls': urls, 
                'duplicates': duplicates,
                'new_entries': new_entries,
                'models': models, 
                'chat_formats': chat_formats}

    return render(request, 'newdocs/pre_processing_block.html', context)
    
def launch_processing(request):
    '''
    This is the third stage of the addition pipeline
    where the actual processing starts based on user's selection
    This view is called by an AJAX request (launch button in the template)
    which allows to keep updating users on progress
    '''

    if request.method == 'POST':

        if request.headers.get('x-Requested-with') == 'XMLHttpRequest':
            #retrieves information from the form
            client = request.POST.get('client')
            chat_format = request.POST.get('chat')
            model = request.POST.get('model_name')
            selected_urls = request.POST.getlist('selected_urls')

            #check if the urls are valid
            selected_urls = [validate_url(url) for url in selected_urls]
            selected_urls = [url for url in selected_urls if url != None]
            
            #in this app, arxiv, youtube and others websites will be dealt with differently. We split them into different lists
            data = classify_urls(selected_urls)

            task_id = request.POST.get('task_id')
            print(data, client) 

            #lauch thread for a long process
            thread = Thread(target=processing_start, args=(data, client, chat_format, model, task_id))
            thread.start()

            response_content = {'status': 'processing started', 'task_id': task_id}
            
        else:
            # Handle non-AJAX POST request
            # You might want to redirect or return a different HttpResponse here
            response_content = {'error': 'Invalid request', "status":400}

        return JsonResponse(response_content) 
    
    else:
        # Handle non-POST request, fallback to default
        return render(request, 'newdocs/add_new_docs.html')
    
def progress_update(request, task_id):
    '''
    Whilst the processing is ongoing, this view is called by an AJAX request
    to get information about the progress from the cache
    '''

    default_progress_message = {"progress":0, "processing_step":"launching..."}

    progress = cache.get(f"progress_task_{task_id}", default_progress_message)
    return JsonResponse(progress)
    
def process_summary(request):
    ''' This is the one-but-last stage of the addition pipeline
    retrieving information from the processing log and comparing with 
    the initial input, running stats saving a session variable
    for rendering
    '''

    if request.method == 'POST':

        if request.headers.get('x-Requested-with') == 'XMLHttpRequest':
            selected_urls = request.POST.getlist('selected_urls')
            task_id = request.POST.get('task_id')
            duration = float(request.POST.get('duration'))
            
            total = len(selected_urls) if selected_urls else 0

            #retrieve info from processing log
            logs = ProcessingLog.objects.filter(task_id=task_id)
            failed = logs.filter(success=False).count()
            processed_by_llm = logs.filter(llm_turns__gt=0).count()
            two_shot_success = logs.filter(success=True, llm_turns__gt=1).count()
            failed_json = logs.filter(success=False, llm_turns__gt=1).count()
            model = logs.exclude(llm=None).values_list('llm', flat=True).distinct()
            if len(model)>0:
                model = model[0]
            else:
                model = None

            #translate duration into minutes and seconds
            minutes = int(duration)//60
            seconds = int(duration)%60

            context={'completed': True,
                     'task_id': task_id,
                     'total': total,
                     'llm': model, 
                     'logged': len(logs),
                     'failed': failed,
                     'processed_by_llm': processed_by_llm,
                     'two_shot_success': two_shot_success,
                     'failed_json': failed_json,
                     'minutes': minutes,
                     'seconds': seconds}
            
            print(context)
            request.session['processing_summary'] = context
            
            return JsonResponse({'redirect_url': '/new/process-complete'})
        

def process_complete(request):

     # Retrieve the processed data
    context = request.session.get('processing_summary', {})

    # Render the page with the data
    return render(request, 'newdocs/add_new_docs.html', context)

