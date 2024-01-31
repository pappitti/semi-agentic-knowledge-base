from django.contrib import admin

# Register your models here.
from .models import LoggedDoc, Author, Category, DocImage, Country, ChatFormat, ProcessingLog, OpenaiModel

class AuthorInline(admin.TabularInline):
    model = Author
    extra = 1

class CategoryInline(admin.TabularInline):
    model = Category
    extra = 1

class CountryInline(admin.TabularInline):
    model = Country
    extra = 1

class LoggedDocAdmin(admin.ModelAdmin):
    list_display = ('title', 'source_url', 'publication_date','is_draft', 'slug', 'summary_type','llm','created_at','modified_at')
    search_fields = ('title', 'source_url', 'is_draft','summary','comment','llm','created_at')
    readonly_fields = ('created_at', 'modified_at')
    ordering = ('-modified_at',)
    list_filter = ('is_draft','llm','publication_date','created_at', 'modified_at')
    inlines = [AuthorInline, CategoryInline, CountryInline]

class CategoryAdmin(admin.ModelAdmin):
    list_display = ('category_name', 'doc')
    search_fields = ('category_name', 'doc')
    list_filter = ('category_name',)
    ordering = ('category_name',)

class AuthorAdmin(admin.ModelAdmin):
    list_display = ('name', 'doc')
    search_fields = ('name', 'doc')
    list_filter = ('name',)
    ordering = ('name',)

class DocImageAdmin(admin.ModelAdmin):
    list_display = ('image_url', 'doc')
    search_fields = ('image', 'doc')
    ordering = ('-created_at',)

class CountryAdmin(admin.ModelAdmin):
    list_display = ('country_name', 'doc')
    search_fields = ('country_name', 'doc')
    list_filter = ('country_name',)
    ordering = ('country_name',)

class ChatFormatAdmin(admin.ModelAdmin):
    list_display = ('chat_name', 'chat_description', 'default')
    search_fields = ('chat_name',)
    list_filter = ('chat_name',)
    ordering = ('chat_name',)

class ProcessingLogAdmin(admin.ModelAdmin):
    list_display = ('task_id','source_url', 'success', 'llm_turns','llm', 'created_at')
    search_fields = ('source_url', 'success', 'llm_turns','llm')
    list_filter = ('task_id','llm','success', 'llm_turns','created_at')
    ordering = ('-created_at',)

class OpenaiModelAdmin(admin.ModelAdmin):
    list_display = ('model_name', 'context_length', 'accepts_json', 'default')
    ordering = ('model_name',)

admin.site.register(LoggedDoc, LoggedDocAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(Author, AuthorAdmin)
admin.site.register(DocImage, DocImageAdmin)
admin.site.register(Country, CountryAdmin)
admin.site.register(ChatFormat, ChatFormatAdmin)
admin.site.register(ProcessingLog, ProcessingLogAdmin)
admin.site.register(OpenaiModel, OpenaiModelAdmin)
