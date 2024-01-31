from django.db import models

# Create your models here. 
#NOTE : for most models, we added a JSONField for embeddings. It is just a placeholder for the moment but we plan to use it later for retrieval.
class Author(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    doc = models.ForeignKey("LoggedDoc", on_delete=models.CASCADE)
    name_embedding = models.JSONField(null=True, blank=True)

    def __str__(self):
        return self.name

# TODO : For now, we're are just building a table of established one-to-many relationships between a doc and its categories without constraints on the categories themselves (e.g. no unique constraint on category_name). Will adjust later and add a unique constraint, and then add a many-to-many relationship between docs and categories.
class Category(models.Model):
    category_name = models.CharField(max_length=255, db_index=True)
    doc = models.ForeignKey("LoggedDoc", on_delete=models.CASCADE)
    name_embedding = models.JSONField(null=True, blank=True)

    def __str__(self):
        return self.category_name

# TODO : For now, we're are just building a table of established one-to-many relationships between a doc and its countries without constraints on the countries themselves (e.g. no unique constraint on country_name). Will adjust later and add a unique constraint, and then add a many-to-many relationship between docs and countries.
class Country(models.Model):
    country_name = models.CharField(max_length=255, db_index=True)
    doc = models.ForeignKey("LoggedDoc", on_delete=models.CASCADE)
    name_embedding = models.JSONField(null=True, blank=True)

    def __str__(self):
        return self.country_name

class DocImage(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    image_url = models.URLField(max_length=1024)
    doc = models.ForeignKey("LoggedDoc", on_delete=models.CASCADE)


    def __str__(self):
        return self.image_url

class ProcessingLog(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

    task_id = models.CharField(max_length=50, null=True, blank=True)
    source_url = models.CharField(max_length=255)
    llm = models.TextField(max_length=255,null=True, blank=True)
    llm_output = models.TextField(max_length=1000,null=True, blank=True)
    success = models.BooleanField(default=False)
    llm_turns = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return self.source_url

# TODO: automating the update of the LLM prompt, GBNF grammar to reflect any changes to the LoggedDoc model.
# in the meantime, the LLM prompt, GBNF grammar have to be updated manually (in newdocs/doc_processing.py)
class LoggedDoc(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    is_draft = models.BooleanField(default=True)
    source_url = models.CharField(max_length=255, unique=True, null=True, blank=True)

    # fields scraped/generate for the doc:
    slug = models.CharField(max_length=255, unique=True)
    title = models.CharField(max_length=255, db_index=True, default="No title", blank=True)
    publication_date = models.DateField(db_index=True, null=True, blank=True)
    overview = models.TextField(db_index=True, null=True, blank=True)
    summary = models.TextField(db_index=True, null=True, blank=True)
    summary_type = models.CharField(max_length=255, null=True, blank=True )
    comment = models.TextField(null=True, blank=True)

    # model used (if any) to generate the fields above:
    llm = models.TextField(max_length=255,null=True, blank=True)
    
    # TODO : un-comment when we turn on the many-to-many relationships
    # countries = models.ManyToManyField(Country, related_name="countries")
    # categories = models.ManyToManyField(Category, related_name="categories")

    default_image = models.ForeignKey('DocImage', on_delete=models.SET_NULL, null=True, blank=True)
    summary_embedding = models.JSONField(null=True, blank=True)

    def __str__(self):
        return self.slug
    
class ChatFormat(models.Model):
    chat_name = models.CharField(max_length=60, db_index=True, unique=True)
    chat_description = models.CharField(max_length=255)
    default= models.BooleanField(default=False)

    def __str__(self):
        return self.chat_name
    
class OpenaiModel(models.Model):
    model_name = models.CharField(max_length=60, db_index=True, unique=True)
    context_length = models.CharField(max_length=60, null=True, blank=True)
    accepts_json = models.BooleanField(default=False)
    default= models.BooleanField(default=False)

    def __str__(self):
        return self.model_name