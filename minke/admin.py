# -*- coding: utf-8 -*-
from pydoc import locate

from django import forms
from django.contrib.admin.options import IncorrectLookupParameters
from django.contrib.contenttypes.models import ContentType
from django.contrib.admin.views.main import ChangeList
from django.contrib.admin.filters import RelatedOnlyFieldListFilter
from django.contrib.admin import helpers
from django.contrib import messages
from django.contrib import admin
from django.utils.text import Truncator
from django.utils.html import escape
from django.utils.translation import gettext as _
from django.utils.safestring import mark_safe
from django.template.response import TemplateResponse
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.urls import reverse
from django.http import HttpResponseRedirect

from . import settings
from . import engine
from .sessions import REGISTRY
from .models import MinkeSession
from .models import Host
from .models import HostGroup
from .models import CommandResult
from .models import BaseMessage
from .forms import MinkeForm
from .forms import SessionSelectForm
from .filters import StatusFilter


class SessionChangeList(ChangeList):
    """
    A changelist to make our get-params valid.
    """
    def get_filters_params(self, params=None):
        params = super().get_filters_params(params)
        for key in ('display_messages', 'display_commands'):
            if key in params: del params[key]
        return params

    def get_queryset(self, request):
        use_cmds = 'display_commands' in request.GET
        related = 'commands' if use_cmds else 'messages'
        qs = super().get_queryset(request).prefetch_related(related)
        return qs.prefetch_related('minkeobj')


@admin.register(MinkeSession)
class SessionAdmin(admin.ModelAdmin):
    model = MinkeSession
    change_list_template = 'minke/change_list.html'

    def get_changelist(self, request, **kwargs):
        """
        Use our own ChangeList.
        """
        return SessionChangeList

    class Media:
        css = dict(all=('minke/css/minke.css',))

    date_hierarchy = 'created_time'
    search_fields = ('session_name',)
    list_display = (
        'session_verbose_name',
        'minkeobj_view',
        'minkeobj_type',
        'session_status',
        'proc_status',
        'start_time',
        'run_time')
    list_filter = (
        'session_name',
        'session_status',
        'proc_status',
        ('minkeobj_type', RelatedOnlyFieldListFilter),
        'user')
    fieldsets = (
        (None, {
            'fields': (
                'minkeobj_view',
                'minkeobj_type',
                'user',
            ),
            'classes': ('extrapretty', 'wide')
        }),
        (_('Session'), {
            'fields': (
                'session_name',
                'session_verbose_name',
                'session_status',
                'session_description',
                'session_data',
            ),
            'classes': ('extrapretty', 'wide')
        }),
        (_('Processing'), {
            'fields': (
                'proc_status',
                'task_id',
                'created_time',
                'start_time',
                'end_time',
                'run_time',
            ),
            'classes': ('extrapretty', 'wide')
        }),
    )
    readonly_fields = fieldsets[0][1]['fields'] + fieldsets[1][1]['fields'] + fieldsets[2][1]['fields']

    def minkeobj_view(self, obj):
        opts = obj.minkeobj._meta
        lookup = "admin:{}_{}_change".format(opts.app_label, opts.model_name)
        href = reverse(lookup, args=(obj.minkeobj.id,))
        return mark_safe('<a href="{}">{}</a>'.format(href, obj.minkeobj))
    minkeobj_view.short_description = 'Minke-object'
    minkeobj_view.admin_order_field = 'minkeobj_id'

    def changelist_view(self, request, extra_context=None):
        display_messages = bool(int(request.GET.get('display_messages', 0)))
        display_commands = bool(int(request.GET.get('display_commands', 0)))
        extra_context = extra_context or dict()
        extra_context['display_session_switch'] = True
        extra_context['display_session_info'] = display_messages or display_commands
        extra_context['commands_instead_of_messages'] = display_commands
        return super().changelist_view(request, extra_context)


class MinkeChangeList(ChangeList):
    """
    Subclass ChangeList to build the session-list based on the result_list.
    """
    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        # We need a plain session-list with the same order as the result_list.
        # They will be zipped with the results coming from the result_list-templatetag.
        self.sessions = [(list(o.sessions.all())[0:]+[None])[0] for o in self.result_list]
        self.session_count = sum(len(o.sessions.all()) for o in self.result_list)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        currents = MinkeSession.objects.filter(current=True, user=request.user)
        currents = currents.prefetch_related('messages')
        return qs.prefetch_related(Prefetch('sessions', queryset=currents))


class MinkeAdmin(admin.ModelAdmin):
    """
    MinkeAdmin is the ModelAdmin-baseclass for MinkeModels.
    It allows to run sessions from the changelist-view.
    """
    session_history_on_top = True
    session_history_on_bottom = False
    change_form_template = 'minke/change_form.html'
    change_list_template = 'minke/change_list.html'
    session_select_form = SessionSelectForm

    class Media:
        css = dict(all=('minke/css/minke.css',))

    def get_changelist(self, request, **kwargs):
        """
        Use our own ChangeList.
        """
        return MinkeChangeList

    def get_changelist_instance(self, request):
        """
        Normalize the way to get a changelist-instance. Prior django-2.0 the
        get_changelist_instance-method is missing.
        """
        try:
            return super().get_changelist_instance(request)
        except AttributeError:
            # prior django-2.0 get_changelist_instance does not exists
            list_display = self.get_list_display(request)
            list_display_links = self.get_list_display_links(request, list_display)
            list_filter = self.get_list_filter(request)
            search_fields = self.get_search_fields(request)
            list_select_related = self.get_list_select_related(request)

            # Check actions to see if any are available on this changelist
            actions = self.get_actions(request)
            if actions:
                # Add the action checkboxes if there are any actions available.
                list_display = ['action_checkbox'] + list(list_display)

            ChangeList = self.get_changelist(request)
            return ChangeList(
                request, self.model, list_display,
                list_display_links, list_filter, self.date_hierarchy,
                search_fields, list_select_related, self.list_per_page,
                self.list_max_show_all, self.list_editable, self)

    def permit_session(self, request, session):
        permitted = request.user.has_perms(session.permissions)
        permitted &= self.model in session.work_on
        return permitted

    def get_session_options(self, request):
        """
        Get sessions  valid for the user and model of this request.
        Return a list of tuples like with session-name and -verbose-name.
        """
        REGISTRY.reload()
        sessions = [(None, '---------')]

        # filter sessions in respect to their permissions- and work_on-attrs
        for session in REGISTRY.values():
            if not self.permit_session(request, session): continue
            sessions.append((session.__name__, session.verbose_name))
        return sessions

    def get_session_select_form(self, request, data=None):
        """
        Return SessionSelectForm-instance with apropriate session-choices.
        """
        form = self.session_select_form(data or dict())
        form.fields['session'].choices = self.get_session_options(request)
        return form

    def get_session_cls(self, request):
        session_name = request.POST.get('session', None)
        if not session_name:
            msg = _("No session were selected that should be run.")
            self.message_user(request, msg, messages.WARNING)
            return None
        else:
            REGISTRY.reload()
            return REGISTRY.get(session_name, None)

    def run_sessions(self, request, session_cls, queryset, force_confirm=False):
        wait = session_cls.wait_for_execution
        confirm = force_confirm or session_cls.confirm
        fabric_config = None
        session_data = dict()
        session_form_cls = session_cls.get_form()
        fabric_form_cls = None
        render_params = dict()

        # import fabric-form if needed...
        if settings.MINKE_FABRIC_FORM:
            fabric_form_cls = locate(settings.MINKE_FABRIC_FORM)
            if not fabric_form_cls:
                msg = '{} could not be loaded'.format(settings.MINKE_FABRIC_FORM)
                raise InvalidMinkeSetup(msg)

        # Do we have to work with a minke-form?
        if confirm or fabric_form_cls or session_form_cls:

            # Do we come from a minke-form?
            from_form = request.POST.get('minke_form', False)
            if from_form:
                minke_form = MinkeForm(request.POST, auto_id=False)
                valid = minke_form.is_valid()
                form_data = [request.POST]
            else:
                minke_form = MinkeForm(initial=request.POST, auto_id=False)
                valid = False
                form_data = list()

            # initiate fabric-form
            if fabric_form_cls:
                fabric_form = fabric_form_cls(*form_data, auto_id=False)
                render_params['fabric_form'] = fabric_form
                valid &= fabric_form.is_valid()

            # initiate session-form
            if session_form_cls:
                session_form = session_cls.form(*form_data, auto_id=False)
                render_params['session_form'] = session_form
                valid &= session_form.is_valid()

            # render minke-form first time or if form-data is invalid
            if not from_form or not valid:
                render_params['title'] = session_cls.verbose_name,
                render_params['minke_form'] = minke_form
                render_params['objects'] = queryset
                render_params['object_list'] = confirm
                return TemplateResponse(request, 'minke/minke_form.html', render_params)

            else:
                # collect form-data
                if fabric_form_cls: fabric_config = fabric_form.cleaned_data
                if session_form_cls: session_data = session_form.cleaned_data

        # lets rock...
        engine.process(session_cls, queryset, session_data, request.user,
                       fabric_config=fabric_config, wait=wait)

    def changelist_view(self, request, extra_context=None):
        """
        Extend the modeladmin-changelist_view by session-processing.
        """
        extra_context = extra_context or dict()
        extra_context['display_session_select'] = extra_context.get('display_session_select', True)
        extra_context['display_session_info'] = extra_context.get('display_session_info', True)
        extra_context['display_session_proc_info'] = extra_context.get('display_session_proc_info', True)

        # Does this request has something to do with sessions at all?
        if ('run_sessions' not in request.POST
        and 'clear_sessions' not in request.POST):
            return super().changelist_view(request, extra_context)

        # setup
        force_confirm = False
        selected = request.POST.getlist(helpers.ACTION_CHECKBOX_NAME)
        select_across = bool(int(request.POST.get('select_across', 0)))
        session_form = self.get_session_select_form(request, request.POST)
        redirect_url = request.get_full_path()

        try:
            cl = self.get_changelist_instance(request)
        except IncorrectLookupParameters:
            # Since we are coming from a form-subimission our url-query
            # should be valid. So this shouldn't happen at all.
            return HttpResponseRedirect(redirect_url)

        # Do we have any selected items? Else leave a message and redirect.
        if not selected:
            msg = _("No items selected.")
            self.message_user(request, msg, messages.WARNING)
            return HttpResponseRedirect(redirect_url)

        # get queryset
        queryset = cl.get_queryset(request)
        if not select_across:
            queryset = queryset.filter(pk__in=selected)

        # clear session-infos for selected items
        if 'clear_sessions' in request.POST:
            MinkeSession.objects.clear_currents(request.user, queryset)
            return HttpResponseRedirect(redirect_url)

        # run sessions
        elif 'run_sessions' in request.POST:

            # get session_cls.
            session_form = self.get_session_select_form(request, request.POST)
            if session_form.is_valid():
                session_name = session_form.cleaned_data['session']
                REGISTRY.reload()
                session_cls = REGISTRY[session_name]
            else:
                msg = _("No session selected.")
                self.message_user(request, msg, messages.WARNING)
                return HttpResponseRedirect(redirect_url)

            # Do the user have permissions to run this session-type?
            if not self.permit_session(request, session_cls):
                raise PermissionDenied

            # If this is a select-across-request, we force confirmation
            # and redirect to a show-all-changelist.
            # FIXME: select-across should be limited at least to the value of
            # list_max_show_all.
            if select_across:
                force_confirm = True
                delimiter = '&' if '?' in redirect_url else '?'
                redirect_url += delimiter + 'all='

            # run_sessions might want to render a minke- or session-form
            response = self.run_sessions(request, session_cls, queryset, force_confirm)
            return response or HttpResponseRedirect(redirect_url)

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        """
        Add session-history-view to the changeform-view.
        """
        extra_context = extra_context or dict()
        extra_context['session_history_on_top'] = self.session_history_on_top
        extra_context['session_history_on_bottom'] = self.session_history_on_bottom
        # Has been asked for a session-history?
        if object_id and 'session_history' in request.GET:
            use_cmds = 'use_commands' in request.GET
            related = 'commands' if use_cmds else 'messages'
            ct = ContentType.objects.get_for_model(self.model)
            sessions = MinkeSession.objects.prefetch_related(related)
            sessions = sessions.filter(
                minkeobj_type=ct,
                minkeobj_id=object_id,
                user=request.user,
                proc_status__in=('completed', 'stopped', 'failed'))
            sessions = sessions[:int(request.GET['session_history'])]
            extra_context['sessions'] = sessions
            extra_context['commands_instead_of_messages'] = use_cmds
            extra_context['display_session_date'] = True

        # call super-changeform-view with our extra-context
        return super().changeform_view(request, object_id, form_url, extra_context)


def get_ssh_options():
    choices = ((None, '---------'),)
    choices += tuple(((k, k) for k in settings.MINKE_HOST_CONFIG.keys()))
    return choices


class HostAdminForm(forms.ModelForm):
    class Meta:
        model = Host
        exclude = tuple()
        widgets = dict(config=forms.Select(choices=get_ssh_options()))


class HostGroupAdminForm(forms.ModelForm):
    class Meta:
        model = HostGroup
        exclude = tuple()
        widgets = dict(config=forms.Select(choices=get_ssh_options()))


@admin.register(Host)
class HostAdmin(MinkeAdmin):
    model = Host
    form = HostAdminForm
    list_display = ('name', 'verbose_name', 'username', 'hostname', 'port')
    search_fields = ('name', 'hostname')
    ordering = ('name',)
    list_filter = (StatusFilter,)


@admin.register(HostGroup)
class HostGroupAdmin(admin.ModelAdmin):
    model = HostGroup
    form = HostGroupAdminForm
    list_display = ('name',)
    search_fields = ('name',)
    ordering = ('name',)


class CommandResultAdmin(admin.ModelAdmin):
    model = CommandResult
    list_display = ('command', 'session', 'exited', 'stdout_view', 'stderr_view', 'shell', 'pty', 'encoding', 'created_time')
    readonly_fields = list_display
    search_fields = ('session', 'command')
    ordering = ('session', 'created_time')

    def stdout_view(self, obj):
        if not obj.stdout: return
        abbr = escape(Truncator(obj.stdout).words(3))
        html = '<span title="{}">{}</span>'.format(escape(obj.stdout), abbr)
        return mark_safe(html)
    stdout_view.short_description = 'stdout'

    def stderr_view(self, obj):
        if not obj.stderr: return
        abbr = escape(Truncator(obj.stderr).words(3))
        html = '<span title="{}">{}</span>'.format(escape(obj.stderr), abbr)
        return mark_safe(html)
    stderr_view.short_description = 'stderr'


class BaseMessageAdmin(admin.ModelAdmin):
    model = BaseMessage
    list_display = ('text_view', 'html_view', 'level', 'session', 'created_time')
    search_fields = ('text',)
    ordering = ('session', 'created_time')

    def text_view(self, obj):
        if not obj.text: return
        abbr = escape(Truncator(obj.text).words(3))
        html = '<span title="{}">{}</span>'.format(escape(obj.text), abbr)
        return mark_safe(html)
    text_view.short_description = 'text'

    def html_view(self, obj):
        if not obj.html: return
        abbr = escape(Truncator(obj.html).words(3))
        html = '<span title="{}">{}</span>'.format(escape(obj.html), abbr)
        return mark_safe(html)
    html_view.short_description = 'html'
