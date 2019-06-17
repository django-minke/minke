# -*- coding: utf-8 -*-

import re
import datetime
from time import time
from collections import OrderedDict

from fabric2.runners import Result
from celery.task.control import revoke

from django.db import models
from django.db import transaction
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldError
from django.utils.safestring import mark_safe
from django.template.loader import render_to_string
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from .exceptions import InvalidMinkeSetup
from .utils import JSONField


class MinkeSessionQuerySet(models.QuerySet):
    """
    Working with current sessions.
    Which are those that are rendered within the changelist.
    """
    def get_currents(self, user, minkeobjs):
        """
        Get all current sessions for a given user and minke-objects.
        """
        ct_query = ContentType.objects.filter(model=minkeobjs.model.__name__.lower())[0]
        qs = self.filter(minkeobj_type=ct_query, minkeobj_id__in=minkeobjs)
        return qs.filter(user=user, current=True)

    def clear_currents(self, user, minkeobjs):
        """
        Clear all current sessions for a given user and minke-objects.
        """
        return self.get_currents(user, minkeobjs).update(current=False)


# TODO: Add indexes for sessions, messages and commandresults!
class MinkeSession(models.Model):
    """
    The MinkeSession holds the data of any executed session and tracks its process.
    """
    objects = MinkeSessionQuerySet.as_manager()

    SESSION_STATES = (
        ('success', 0),
        ('warning', 1),
        ('error', 2))
    PROC_STATES = (
        ('initialized', 'waiting...'),
        ('running', 'running...'),
        ('completed', 'completed in {0:.1f} seconds'),
        ('stopping', 'stopping...'),
        ('stopped', 'stopped after {0:.1f} seconds'),
        ('canceled', 'canceled!'),
        ('failed', 'failed!'))
    SESSION_CHOICES = ((s[0], _(s[0])) for s in SESSION_STATES)
    PROC_CHOICES = ((s[0], _(s[0])) for s in PROC_STATES)

    class Meta:
        ordering = ('minkeobj_type', 'minkeobj_id', '-created_time')
        verbose_name = _('Minke-Session')
        verbose_name_plural = _('Minke-Sessions')

    # those fields will be derived from the session-class
    session_name = models.CharField(
        max_length=128,
        verbose_name=_('Session-name'),
        help_text=_('Class-name of the session-class.'))
    session_verbose_name = models.CharField(
        max_length=128,
        verbose_name=_("Session's verbose-name"),
        help_text=_('Verbose-name-attribute of the session-class.'))
    session_description = models.TextField(
        blank=True, null=True, max_length=128,
        verbose_name=_("Session's description"),
        help_text=_('Doc-string of the session-class.'))
    session_status = models.CharField(
        max_length=128, choices=SESSION_CHOICES,
        verbose_name=_("Session-status"),
        help_text=_('Mostly set by the session-code itself.'))
    session_data = JSONField(
        blank=True, null=True,
        verbose_name=_("Session's extra-data"),
        help_text=_('Data coming from a session-form.'))

    # the minkeobj to work on
    minkeobj_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    minkeobj_id = models.PositiveIntegerField()
    minkeobj = GenericForeignKey('minkeobj_type', 'minkeobj_id')

    # execution-data of the session
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        verbose_name=_("User"),
        help_text=_('User that run this session.'))
    proc_status = models.CharField(
        max_length=128, choices=PROC_CHOICES,
        verbose_name=_("Process-status"),
        help_text=_('Status of session-processing.'))
    task_id = models.CharField(
        max_length=128, blank=True, null=True,
        verbose_name=_("Task-ID"),
        help_text=_('ID of the celery-task that run the session.'))
    start_time = models.DateTimeField(
        blank=True, null=True,
        verbose_name=_("Start-time"),
        help_text=_('Time the session has been started.'))
    end_time = models.DateTimeField(
        blank=True, null=True,
        verbose_name=_("End-time"),
        help_text=_('Time the session finished.'))
    run_time = models.DurationField(
        blank=True, null=True,
        verbose_name=_("Run-time"),
        help_text=_("Session's runtime."))
    created_time = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created-time"),
        help_text=_('Time the session has been initiated.'))
    current = models.BooleanField(default=True)

    def init(self, user, minkeobj, session_cls, session_data):
        """
        Initialize a session. Setup the session-attributes and save it.
        """
        self.proc_status = 'initialized'
        self.user = user
        self.minkeobj = minkeobj
        self.session_name = session_cls.__name__
        self.session_verbose_name = session_cls.verbose_name
        self.session_description = session_cls.__doc__
        self.session_data = session_data
        self.save()

    @transaction.atomic
    def start(self, task_id):
        """
        Start a session. Update proc_status, start_time and task_id.
        Since the cancel-method is called asynchrouniously to the whole session-
        processing, the start-, end- and cancel-method are each wrapped within a
        atomic transaction using select_for_update to protect them from interfering.
        """
        # We use the reloaded session for checks but update and save self.
        # On the database-level it doesn't make a difference from which object
        # we call the save-method.
        session = MinkeSession.objects.select_for_update().get(pk=self.id)
        if session.is_waiting:
            self.task_id = task_id
            self.proc_status = 'running'
            self.start_time = datetime.datetime.now()
            self.save(update_fields=['proc_status', 'start_time', 'task_id'])
            return True

    @transaction.atomic
    def cancel(self):
        """
        Cancel a session. Update proc_- and session_status.
        Since the cancel-method is called asynchrouniously to the whole session-
        processing, the start-, end- and cancel-method are each wrapped within a
        atomic transaction using select_for_update to protect them from interfering.
        """
        session = MinkeSession.objects.select_for_update().get(pk=self.id)
        if session.is_waiting:
            self.session_status = 'error'
            self.proc_status = 'canceled'
            self.save(update_fields=['proc_status', 'session_status'])
            return True
        elif session.proc_status == 'running':
            self.proc_status = 'stopping'
            self.save(update_fields=['proc_status'])
            revoke(session.task_id, signal='USR1', terminate=True)
            return True

    @transaction.atomic
    def end(self, failure=False):
        """
        End a session. Update proc_- and session_status, end_- and run_time.
        Since the cancel-method is called asynchrouniously to the whole session-
        processing, the start-, end- and cancel-method are each wrapped within a
        atomic transaction using select_for_update to protect them from interfering.
        """
        session = MinkeSession.objects.select_for_update().get(pk=self.id)
        if failure:
            self.session_status = 'error'
            self.proc_status = 'failed'
        elif session.proc_status == 'running':
            self.session_status = self.session_status or 'success'
            self.proc_status = 'completed'
        elif session.proc_status == 'stopping':
            self.session_status = 'error'
            self.proc_status = 'stopped'
        self.end_time = datetime.datetime.now()
        self.run_time = self.end_time - self.start_time
        fields = ['proc_status', 'session_status', 'end_time', 'run_time']
        self.save(update_fields=fields)

    @property
    def is_waiting(self):
        return self.proc_status == 'initialized'

    @property
    def is_running(self):
        return self.proc_status in ['running', 'stopping']

    @property
    def is_done(self):
        return self.proc_status in ['completed', 'canceled', 'stopped', 'failed']

    @property
    def proc_info(self):
        """
        Infos about the session-processing
        that will be rendered within the session-template.
        """
        info = next(s[1] for s in self.PROC_STATES if s[0] == self.proc_status)
        if self.run_time: return gettext(info).format(self.run_time.total_seconds())
        else: return gettext(info)

    def prnt(self):
        """
        Print a session and its messages.
        """
        width = 60
        pre_width = 7
        sep = ': '
        bg = dict(
            success = '\033[1;37;42m{}\033[0m'.format,
            warning = '\033[1;37;43m{}\033[0m'.format,
            error   = '\033[1;37;41m{}\033[0m'.format)
        fg = dict(
            info    = '\033[32m{}\033[39m'.format,
            warning = '\033[33m{}\033[39m'.format,
            error   = '\033[31m{}\033[39m'.format)
        ul = '\033[4m{}\033[0m'.format

        # print header
        minkeobj = str(self.minkeobj).ljust(width)
        status = self.session_status.upper().ljust(pre_width)
        print(bg[self.session_status](status + sep + minkeobj))

        # print messages
        msgs = list(self.messages.all())
        msg_count = len(msgs)
        for i, msg in enumerate(msgs, start=1):
            underlined = i < msg_count
            level = msg.level.ljust(pre_width)
            lines = msg.text.splitlines()
            for line in lines[:-1 if underlined else None]:
                print(fg[msg.level](level) + sep + line)
            if underlined:
                line = lines[-1].ljust(width)
                print(ul(fg[msg.level](level) + sep + line[:width]) + line[width:])


class CommandResult(Result, models.Model):
    """
    Add a db-layer to fabric's Result-class.
    """
    command = models.TextField()
    exited = models.SmallIntegerField()
    stdout = models.TextField(blank=True, null=True)
    stderr = models.TextField(blank=True, null=True)
    shell = models.CharField(max_length=128)
    encoding = models.CharField(max_length=128)
    pty = models.BooleanField()
    created_time = models.DateTimeField(auto_now_add=True)
    session = models.ForeignKey(MinkeSession, on_delete=models.CASCADE, related_name='commands')

    class Meta:
        ordering = ('session', 'created_time')
        verbose_name = _('Command-Result')
        verbose_name_plural = _('Command-Results')

    def __init__(self, *args, **kwargs):
        """
        This model could also be initiated as fabric's result-class.
        """
        try:
            # First we try to initiate the model.
            models.Model.__init__(self, *args, **kwargs)
        except TypeError:
            # If this fails, its a result-class-initiation.
            models.Model.__init__(self)
            Result.__init__(self, *args, **kwargs)

    def as_message(self):
        """
        Return this instance as an ExecutionMessage.
        """
        # FIXME: messages imports from models and vice versa.
        # We should find another solution here. Maybe define message-proxies
        # right here in the models-module?
        from .messages import ExecutionMessage
        return ExecutionMessage(self)


class BaseMessage(models.Model):
    """
    This is the database-layer for all messages. Proxies of this model are defined
    within the messages-module.
    """
    LEVELS = (
        ('info', 'info'),
        ('warning', 'warning'),
        ('error', 'error'))

    session = models.ForeignKey(MinkeSession, on_delete=models.CASCADE, related_name='messages')
    level = models.CharField(max_length=128, choices=LEVELS)
    text = models.TextField()
    html = models.TextField()
    created_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('session', 'created_time')
        verbose_name = _('Message')
        verbose_name_plural = _('Messages')


class HostGroup(models.Model):
    """
    A Group of hosts. (Not sure if this is practical.)
    """
    name = models.CharField(max_length=255, unique=True)
    comment = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['name']
        verbose_name = _('Hostgroup')
        verbose_name_plural = _('Hostgroups')

    def __str__(self):
        return self.name


class HostQuerySet(models.QuerySet):
    """
    Besides the get_lock-method this is an imitation of the minkemodel-queryset-api.
    """
    def get_lock(self):
        """
        Set a lock on all selected hosts.
        """
        # The most atomic way to get a lock is a update-query.
        # We use a timestamp to be able to identify the updated objects.
        timestamp = repr(time())
        self.filter(lock=None).update(lock=timestamp)
        return timestamp

    def get_hosts(self):
        """
        Return itself (minkemodel-api).
        """
        return self

    def host_filter(self, hosts):
        """
        Return an intersection of itself and the given hosts (minkemodel-api).
        """
        return self & hosts

    def select_related_hosts(self):
        """
        Return itself (minkemodel-api).
        """
        return self


class Host(models.Model):
    """
    This model is mainly a ssh-config.
    Each host represents an unique ssh-connection.
    It also imitates the minkemodel-api to normalize the way the engine the engine
    runs sessions on them.
    """
    name = models.SlugField(max_length=128, unique=True)
    verbose_name = models.CharField(max_length=255, blank=True, null=True)
    hostname = models.CharField(max_length=255, blank=True, null=True)
    username = models.CharField(max_length=255, blank=True, null=True)
    port = models.IntegerField(blank=True, null=True)
    comment = models.TextField(blank=True, null=True)
    group = models.ForeignKey(HostGroup, blank=True, null=True, on_delete=models.SET_NULL)
    disabled = models.BooleanField(default=False)
    lock = models.CharField(max_length=20, blank=True, null=True)

    objects = HostQuerySet.as_manager()
    sessions = GenericRelation(MinkeSession,
        content_type_field='minkeobj_type',
        object_id_field='minkeobj_id')

    def get_host(self):
        """
        Return itself (minkemodel-api).
        """
        return self

    def release_lock(self):
        """
        Release the host's lock.
        """
        self.lock = None
        self.save(update_fields=['lock'])

    class Meta:
        ordering = ['name']
        verbose_name = _('Host')
        verbose_name_plural = _('Hosts')

    def __str__(self):
        return self.name


class MinkeQuerySet(models.QuerySet):
    """
    A queryset-api to work with related hosts.
    This api is mainly used by the engine-module.
    """
    def get_hosts(self):
        """
        Get all hosts related to the objects of this queryset.
        """
        lookup = self.model.get_reverse_host_lookup() + '__in'
        try:
            return Host.objects.filter(**{lookup:self})
        except FieldError:
            msg = "Invalid reverse-host-lookup: {}".format(lookup)
            raise InvalidMinkeSetup(msg)

    def host_filter(self, hosts):
        """
        Get all objects related to the given hosts.
        """
        lookup = self.model.HOST_LOOKUP + '__in'
        try:
            return self.filter(**{lookup:hosts})
        except FieldError:
            msg = "Invalid host-lookup: {}".format(lookup)
            raise InvalidMinkeSetup(msg)

    def select_related_hosts(self):
        """
        Return a queryset which selects related hosts.
        """
        try:
            return self.select_related(self.model.HOST_LOOKUP)
        except FieldError:
            msg = "Invalid host-lookup: {}".format(self.model.HOST_LOOKUP)
            raise InvalidMinkeSetup(msg)


# TODO: implement a post-delete-signal-handler to cleanup sessions on deleting
# a minkeobject.
class MinkeModel(models.Model):
    """
    An abstract baseclass for all models on which sessions should be run.
    """
    objects = MinkeQuerySet.as_manager()
    sessions = GenericRelation(MinkeSession,
        content_type_field='minkeobj_type',
        object_id_field='minkeobj_id')

    HOST_LOOKUP = 'host'
    REVERSE_HOST_LOOKUP = None

    class Meta:
        abstract = True

    @classmethod
    def get_reverse_host_lookup(cls):
        """
        Derive a reverse lookup-term from HOST_LOOKUP.
        """
        if cls.REVERSE_HOST_LOOKUP:
            lookup = self.REVERSE_HOST_LOOKUP
        else:
            lookup_list = cls.HOST_LOOKUP.split('__')
            lookup_list.reverse()
            lookup_list.append(cls.__name__.lower())
            lookup = '__'.join(lookup_list[1:])
        return lookup

    def get_host(self):
        """
        Return the related host-instance.
        """
        host = self
        for attr in self.HOST_LOOKUP.split('__'):
            host = getattr(host, attr, None)
        if not isinstance(host, Host):
            msg = "Invalid host-lookup: {}".format(self.HOST_LOOKUP)
            raise InvalidMinkeSetup(msg)
        else:
            return host
