# -*- coding: utf-8 -*-

import re

from fabric.api import run

from django.db.utils import OperationalError
from django.core.exceptions import FieldDoesNotExist
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.utils.text import camel_case_to_spaces, slugify

from .views import SessionView
from .models import Host
from .messages import ExecutionMessage
from .messages import PreMessage
from .exceptions import InvalidMinkeSetup


registry = list()
def register(session_cls, models=None,
             short_description=None,
             permission_required=None,
             create_permission=False):
    """
    Register session-classes.
    They will be provided as admin-actions for the specified models
    """

    if models:
        if not type(models) == tuple:
            models = (models,)
        session_cls.models = models

    if permission_required:
        if not type(permission_required) == tuple:
            permission_required = (permission_required,)
        session_cls.permission_required = permission_required

    if short_description:
        session_cls.short_description = short_description

    if not issubclass(session_cls, Session):
        raise InvalidMinkeSetup('Registered class must subclass Session.')

    if not session_cls.models:
        raise InvalidMinkeSetup('At least one model must be specified for a session.')

    for model in session_cls.models:
        if model is not Host and not hasattr(model, 'get_host'):
            raise InvalidMinkeSetup(
                'Models used with sessions must define a get_host-method.')

    if create_permission:
        # We only create a permission for one model. Otherwise a user would
        # must have all permissions for all session-models and not as expected
        # only the permission for the model she wants to run the session with.
        # FIXME: Better solution here?
        model = session_cls.models[0]

        # Applying minke-migrations tumbles over get_for_model if the
        # migrations for this model aren't applied yet.
        try: content_type = ContentType.objects.get_for_model(model)
        except OperationalError: return

        model_name = slugify(model.__name__)
        session_name = session_cls.__name__
        session_codename = camel_case_to_spaces(session_name).replace(' ', '_')
        codename = 'run_{}_on_{}'.format(session_codename, model_name)
        permission_name = '{}.{}'.format(model._meta.app_label, codename)

        # create permission...
        permission = Permission.objects.get_or_create(
            name='Can run {}'.format(session_name),
            codename=codename,
            content_type=content_type)

        # add permission to permission_required...
        session_cls.permission_required += (permission_name,)

    registry.append(session_cls)


class BaseSession(object):
    """
    Implement the base-functionality of a session-class.
    """

    SUCCESS = 'success'
    WARNING = 'warning'
    ERROR = 'error'
    FORM = None

    def __init__(self, host, player, **session_data):
        self.host = host
        self.player = player
        self.session_data = session_data
        self.news = list()
        self.status = self.SUCCESS

    def set_status(self, status):
        """
        Set session-status.

        The session-status can be 'error', 'warning' or 'success'.
        You can pass a status-code as 'error', 'ERROR' or self.ERROR.
        You can also pass a boolean while True means 'success' and False 'error'.
        (The default session-status is 'success'.)
        """
        try: status = getattr(self, status)
        except (AttributeError, TypeError): pass

        if status in (self.SUCCESS, self.WARNING, self.ERROR):
            self.status = status
        elif type(status) is bool:
            self.status = self.SUCCESS if status else self.ERROR
        else:
            raise ValueError('Invalid session-status: {}'.format(status))

    def process(self):
        """
        Real work is done here...

        This is the part of a session which is executed within fabric's
        multiprocessing-szenario. It's the right place for all
        fabric-operations. But keep it clean of database-related stuff.
        Database-connections are multiplied with spawend processes and
        then are not reliable anymore.
        """
        raise NotImplementedError('Your session must define a process-method!')

    def rework(self):
        """
        This method is called after fabric's work is done.
        Database-related actions should be done here."""
        pass


class AdminSession(BaseSession):
    """
    Implement attributes for admin-site-integration.
    """

    models = tuple()
    short_description = None
    permission_required = tuple()

    @classmethod
    def as_action(cls):
        def action(modeladmin, request, queryset):
            session_view = SessionView.as_view()
            return session_view(request, session_cls=cls, queryset=queryset)
        action.__name__ = cls.__name__
        action.short_description = cls.short_description
        return action


class Session(AdminSession):

    def format_cmd(self, cmd):
        """
        Will format a given command-string using the player's attributes
        and the session_data while the session_data has precedence.
        """
        params = vars(self.player)
        params.update(self.session_data)
        return cmd.format(**params)

    def valid(self, result, regex=None):
        """
        Validate result.

        Return True if rtn-code is 0.
        If regex is given it must also match stdout.
        """
        if regex and result.return_code == 0:
            return bool(re.match(regex, result.stdout))
        else:
            return result.return_code == 0

    def message(self, cmd, **kwargs):
        """
        Just run cmd and leave a message.
        """
        result = run(cmd, **kwargs)
        valid = self.valid(result)

        if not valid or result.stderr:
            level = 'WARNING' if valid else 'ERROR'
            self.news.append(ExecutionMessage(result, level))
        else:
            self.news.append(PreMessage(result, 'INFO'))

        return valid


class UpdateEntriesSession(Session):

    def update_field(self, field, cmd, regex=None):
        """
        Update a field using either the stdout or the first matching-group
        from regex.
        """
        # is field a player-attribute?
        try: getattr(self.player, field)
        except AttributeError as e: raise e

        # run cmd
        result = run(cmd)
        valid = self.valid(result, regex)

        # A valid call and stdout? Then try to use the first captured
        # regex-group or just use stdout as value.
        if valid and result.stdout:
            try:
                assert regex
                value = re.match(regex, result.stdout).groups()[0]
            except (AssertionError, IndexError):
                value = result.stdout

        # call were valid but no stdout? Leave a warning.
        elif valid and not result.stdout:
            self.news.append(ExecutionMessage(result, 'WARNING'))
            value = None

        # call failed.
        else:
            value = None
            self.news.append(ExecutionMessage(result, 'ERROR'))

        setattr(self.player, field, value)
        return bool(value)

    def rework(self):
        # TODO: catch exceptions that may be raised because of invalid values.
        self.player.save()
