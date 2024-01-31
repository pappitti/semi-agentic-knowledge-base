import os
import re
from django.conf import settings
from django.core.files.base import ContentFile
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q
from articles.forms import AuthorFormset, CategoryFormset, CountryFormset, LoggedDocForm
from backend.models import LoggedDoc, DocImage


MEDIA_ROOT = settings.MEDIA_ROOT
## UTILS

def img_index(array_img_docs, doc_slug):
    '''
    Returns the max index of an image given a document slug
    the objective is to avoid duplicate names when adding images
    '''
    
    indexes = []
    for i in range(len(array_img_docs)):
        file_name=array_img_docs[i].image_url
        match = re.search(rf"{doc_slug}_(\d+).png", file_name)
        if match:
            index = int(match.group(1))
            indexes.append(index)

    # Find the maximum index
    return max(indexes, default=0)


## VIEWS

def index(request):
    """ home page of the app"""

    #TODO pagination
    if request.method == 'GET':

        doc_list=LoggedDoc.objects.all()

        #TODO: embedding search

        #retrieve search params and apply filters
        kw=request.GET.get("kw")
        if kw:
            doc_list=doc_list.filter(
                Q(title__icontains=kw)|
                Q(overview__icontains=kw)|
                Q(summary__icontains=kw)|
                Q(comment__icontains=kw)|
                Q(llm__icontains=kw))

        author=request.GET.get("author")
        if author:
            doc_list=doc_list.filter(author__name__icontains=author)

        category=request.GET.get("category")
        if category:
            doc_list=doc_list.filter(category__category_name__icontains=category)

        country=request.GET.get("country")
        if country:
            doc_list=doc_list.filter(country__country_name__icontains=country)

        #retrieve sorting params, set default values and apply filters/sorting
        validation_filter=request.GET.get("sort-by-status","all")
        if validation_filter=="draft":
            doc_list=doc_list.filter(is_draft=True)
        elif validation_filter=="validated":
            doc_list=doc_list.filter(is_draft=False)

        date_sorting=request.GET.get("sort-by-date","publication_date")
        if date_sorting=="publication_date":
            doc_list=doc_list.order_by("-publication_date")
        elif date_sorting=="creation_date":
            doc_list=doc_list.order_by("-created_at")

        #prefetch related fields taking into account all parameters
        doc_list=doc_list.prefetch_related('author_set', 'country_set', 'category_set')

        #dictionaries with params are passed to the template to display values and allow for further filtering in the UI
        search_params=None
        if kw or author or category or country:
            search_params={"kw":kw, "author":author, "category":category, "country":country}

        sort_params={"date":date_sorting, "validation":validation_filter}
        
        context = {'doc_list': doc_list, "search_params":search_params, "sort_params":sort_params}
        return render(request, "homepage/content.html", context)
    
    else:
        redirect('/')


def save_doc(request):
    '''
    Database updates when a document is added or edited
    '''

    document = None
    origin_slug = request.POST.get('origin_slug') if request.method == 'POST' else None

    if origin_slug:
        document = get_object_or_404(LoggedDoc, slug=origin_slug)
        docimages = [image.image_url for image in document.docimage_set.all()]
    else:
        document = LoggedDoc()
        docimages = [] 

    # fill the forms with the data from the request, if any
    form = LoggedDocForm(request.POST or None, instance=document)
    author_formset = AuthorFormset(request.POST or None, instance=document)
    category_formset = CategoryFormset(request.POST or None, instance=document)
    country_formset = CountryFormset(request.POST or None, instance=document)
    

    if request.method == 'POST':
        if form.is_valid() and author_formset.is_valid() and category_formset.is_valid() and country_formset.is_valid(): 
            saved_document = form.save()

            # Process and save each formset
            author_formset.instance = saved_document
            category_formset.instance = saved_document
            country_formset.instance = saved_document
            author_formset.save()
            category_formset.save()
            country_formset.save()

            default_image_url= request.POST.get('default_image')

            # delete images first (if exist)
            images_to_delete = request.POST.get('images_to_delete')
            if images_to_delete:
                images_to_delete=images_to_delete.split(',')
                for image_url in images_to_delete:
                    try:
                        image_to_delete=DocImage.objects.get(image_url=image_url, doc=saved_document)
                        image_path = os.path.join(MEDIA_ROOT, image_to_delete.image_url)

                        # Check if file exists and delete it
                        if os.path.isfile(image_path):
                            os.remove(image_path)
                    
                        image_to_delete.delete()
                    
                    except DocImage.DoesNotExist:
                        pass
            
            # add new images
            images_to_add = request.FILES.getlist('new_images')
            if images_to_add:

                #find the max index of existing images
                name_pattern = rf"images/{saved_document.slug}_(\d+)\.png"
                existing_images = img_index(DocImage.objects.filter(image_url__regex=name_pattern), saved_document.slug)

                for image_file in range(len(images_to_add)):
                    file_name = f"{saved_document.slug}_{image_file+existing_images+1}.png"
                    image_path = os.path.join(MEDIA_ROOT, 'images', file_name)

                    # Ensure the directory exists
                    os.makedirs(os.path.dirname(image_path), exist_ok=True)

                    # Write the image bytes to a file
                    with open(image_path, 'wb') as img_file:
                        for chunk in images_to_add[image_file].chunks():
                            img_file.write(chunk)

                    relative_path=os.path.join('images', file_name)

                    DocImage.objects.get_or_create(image_url=relative_path, doc=saved_document)

                    if default_image_url==f"new_image_{image_file}":
                        default_image_url = relative_path
            
            # set default image
            if default_image_url:
                # Check if the selected image URL matches any DocumentImage instances
                try:
                    default_image, created = DocImage.objects.get_or_create(image_url=default_image_url, doc=saved_document)
                    saved_document.default_image = default_image
                    saved_document.save()
                
                except DocImage.DoesNotExist:
                    # Should not be raised given a new Image is created above
                    pass
            else:
                saved_document.default_image = None
                saved_document.save()

            return redirect(f"/document/{saved_document.slug}")

        else:
            print(form.errors, author_formset.errors, category_formset.errors, country_formset.errors)
            # Handle invalid form/formsets by re-rendering the page with errors
            context = {
                'document': document,
                'form': form,
                'author_formset': author_formset,
                'category_formset': category_formset,
                'country_formset': country_formset,
                'docimages': docimages,
                'origin_slug': origin_slug
            }
            return render(request, 'articles/edit_doc.html', context)

    else:
        redirect('/')


