from datetime import datetime, date, time
from decimal import Decimal
from operator import itemgetter

from django import forms
from django.contrib import admin
from django.contrib.admin import widgets
from django.contrib.admin.options import csrf_protect_m
from django.conf.urls.defaults import patterns, url
from django.forms import fields
from django.http import HttpResponseRedirect
from django.shortcuts import render_to_response
from django.template.context import RequestContext
from django.utils.formats import localize
from django.utils.translation import ugettext as _

from constance import config, settings


class FieldType(object):
    def __init__(self, form_field, form_field_kwargs=None):
        self.form_field = form_field
        self.form_field_kwargs = form_field_kwargs or {}

    def get_form_field(self, name, label=None, help_text=None, **kwargs):
        return self.form_field(label=label or name, help_text=help_text, **self.form_field_kwargs)

    def load_value(self, value):
        return value

    def store_value(self, value):
        return value


NUMERIC_WIDGET = forms.TextInput(attrs={'size': 10})
INTEGER_LIKE = FieldType(fields.IntegerField, {'widget': NUMERIC_WIDGET})
STRING_LIKE = FieldType(fields.CharField, {'widget': forms.Textarea(attrs={'rows': 3})})

FIELDS = {
    bool: FieldType(fields.BooleanField, {'required': False}),
    int: INTEGER_LIKE,
    long: INTEGER_LIKE,
    Decimal: FieldType(fields.DecimalField, {'widget': NUMERIC_WIDGET}),
    str: STRING_LIKE,
    unicode: STRING_LIKE,
    datetime: FieldType(fields.DateTimeField, {'widget': widgets.AdminSplitDateTime}),
    date: FieldType(fields.DateField, {'widget': widgets.AdminDateWidget}),
    time: FieldType(fields.TimeField, {'widget': widgets.AdminTimeWidget}),
    float: FieldType(fields.FloatField, {'widget': NUMERIC_WIDGET}),
}


def register_field_type(type_name, field_type):
    FIELDS[type_name] = field_type


def _get_field_type(default, type_name):
    if type_name and type_name in FIELDS:
        return FIELDS[type_name]

    return FIELDS[type(default)]


def iterate_config():
    for name, data in settings.CONFIG.items():
        if isinstance(data, tuple):
            data = {'default': data[0], 'help_text': data[1]}

        field_type = _get_field_type(data['default'], data.get('type'))
        yield name, data, field_type


class ConstanceForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super(ConstanceForm, self).__init__(*args, **kwargs)
        for name, data, field_type in iterate_config():
            if name in self.initial:
                self.initial[name] = field_type.load_value(self.initial[name])
            self.fields[name] = field_type.get_form_field(name, **data)

    def save(self):
        for name, data, field_type in iterate_config():
            setattr(config, name, field_type.store_value(self.cleaned_data[name]))


class ConstanceAdmin(admin.ModelAdmin):

    def get_urls(self):
        info = self.model._meta.app_label, self.model._meta.module_name
        return patterns('',
            url(r'^$',
                self.admin_site.admin_view(self.changelist_view),
                name='%s_%s_changelist' % info
            ),
            url(r'^$',
                self.admin_site.admin_view(self.changelist_view),
                name='%s_%s_add' % info
            ),
        )

    @csrf_protect_m
    def changelist_view(self, request, extra_context=None):
        # First load a mapping between config name and default value
        default_initial = ((name, data['default'])
            for name, data, field_type in iterate_config())
        # Then update the mapping with actually values from the backend
        initial = dict(default_initial,
            **dict(config._backend.mget(settings.CONFIG.keys())))
        form = ConstanceForm(initial=initial)
        if request.method == 'POST':
            form = ConstanceForm(request.POST)
            if form.is_valid():
                form.save()
                self.message_user(request, _('Live settings updated successfully.'))
                return HttpResponseRedirect('.')
        context = {
            'config': [],
            'title': _('Constance config'),
            'app_label': 'constance',
            'opts': Config._meta,
            'form': form,
            'media': self.media + form.media,
        }
        for name, data, field_type in iterate_config():
            default = field_type.load_value(data['default'])

            value = initial.get(name)
            if value is None:
                value = getattr(config, name)
            value = field_type.load_value(value)

            context['config'].append({
                'name': name,
                'default': localize(default),
                'modified': value != default,
                'form_field': form[name]
            })
        context['config'].sort(key=itemgetter('name'))
        context_instance = RequestContext(request, current_app=self.admin_site.name)
        return render_to_response('admin/constance/change_list.html',
            context, context_instance=context_instance)

    def has_add_permission(self, *args, **kwargs):
        return False

    def has_delete_permission(self, *args, **kwargs):
        return False

    def has_change_permission(self, request, obj=None, *args, **kwargs):
        if request.user.is_superuser:
            return True
        else:
            return False


class Config(object):
    class Meta(object):
        app_label = 'constance'
        module_name = 'config'
        verbose_name_plural = 'config'
        get_ordered_objects = lambda x: False
        abstract = False
    _meta = Meta()


admin.site.register([Config], ConstanceAdmin)
