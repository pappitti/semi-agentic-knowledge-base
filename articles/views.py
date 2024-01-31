from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from articles.forms import AuthorFormset, CategoryFormset, CountryFormset
from backend.models import LoggedDoc

# Create your views here.
def document_details(request, document_slug):
    '''
    Get information of a document and display it in a template
    '''

    document = get_object_or_404(LoggedDoc, slug=document_slug)
    authors= document.author_set.all()
    categories= document.category_set.all()
    countries= document.country_set.all()

    return render(request, 'articles/document_details.html', {'document': document, 'authors': authors, 'categories': categories, 'countries': countries})


def edit_document_details(request, document_slug):
    '''
    Get information of a document and display it in the edit template
    '''
    
    # fills the form with the existing data of the document
    document = get_object_or_404(LoggedDoc, slug=document_slug)
    author_formset = AuthorFormset(request.POST or None, instance=document)
    category_formset = CategoryFormset(request.POST or None, instance=document)
    country_formset = CountryFormset(request.POST or None, instance=document)
    docimages = [image.image_url for image in document.docimage_set.all()]

    return render(request, 'articles/edit_doc.html', {'document': document, 'author_formset': author_formset, 'category_formset': category_formset, 'country_formset': country_formset, 'docimages':docimages,'origin_slug': document_slug})


def delete_document(request, document_slug):
    '''
    Delete a document
    '''
    
    if request.method == 'POST':

        if request.headers.get('x-Requested-with') == 'XMLHttpRequest':
            document = get_object_or_404(LoggedDoc, slug=document_slug)
            document.delete()
            return JsonResponse({'deleted': document_slug})
     
