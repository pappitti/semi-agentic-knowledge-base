from django import forms
from django.forms import inlineformset_factory
from backend.models import LoggedDoc, Author, Category, Country, DocImage

# Create the inline formset class
class LoggedDocForm(forms.ModelForm):
    class Meta:
        model = LoggedDoc
        fields = ['slug','title', 'source_url', 'publication_date', 'overview','summary_type', 'summary', 'comment', 'llm', 'is_draft']  # Add fields as needed


class DocImageForm(forms.ModelForm):
    class Meta:
        model = DocImage
        fields = ['image_url']  # Add fields as needed

    set_as_default = forms.BooleanField(required=False)

AuthorFormset = inlineformset_factory(
    LoggedDoc, Author, 
    fields=('name',),  # Specify the fields to include
    extra=1,           # Number of empty forms to display
    can_delete=True    # Allow deletion of authors
)

CategoryFormset = inlineformset_factory(
    LoggedDoc, Category, 
    fields=('category_name',),  
    extra=1,           
    can_delete=True    
)

CountryFormset = inlineformset_factory(
    LoggedDoc, Country, 
    fields=('country_name',),  
    extra=1,           
    can_delete=True  
)

DocImageFormSet = inlineformset_factory(
    LoggedDoc, 
    DocImage, 
    form=DocImageForm, 
    extra=0,
    can_delete=True  
)



