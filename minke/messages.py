# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import sys
import traceback

from django.utils.html import escape

from .models import BaseMessage


# We declare the Meta-class whithin a mixin.
# Otherwise the proxy-attribute won't be inherited by child-classes of Session.
class ProxyMixin(object):
    class Meta:
        proxy = True


class Message(ProxyMixin, BaseMessage):
    def __init__(self, data, level='info'):
        super(Message, self).__init__()
        self.text = self.get_text(data)
        self.html = self.get_html(data)

        levels = dict(self.LEVELS).keys()
        if type(level) == bool:
            self.level = 'info' if level else 'error'
        elif level.lower() in levels:
            self.level = level.lower()
        else:
            msg = 'message-level must be one of {}'.format(levels)
            raise InvalidMinkeSetup(msg)

    def get_text(self, data):
        return data

    def get_html(self, data):
        return escape(data)


class PreMessage(Message):
    def get_html(self, data):
        return '<pre>{}</pre>'.format(escape(self.get_text(data)))


class TableMessage(PreMessage):
    def get_text(self, data):
        widths = dict()
        rows = list()
        spacer = '    '
        for row in data:
            for i, col in enumerate(row):
                if widths.get(i, -1) < len(col):
                    widths[i] = len(col)
        for row in data:
            ljust_row = [s.ljust(widths[i]) for i, s in enumerate(row)]
            rows.append(spacer.join(ljust_row))
        return '\n'.join(rows)


class ExecutionMessage(PreMessage):
    def _get_chunk(self, prefix, lines):
        new_lines = list()
        for line in lines:
            new_lines.append(prefix.ljust(10) + line)
            prefix = str()
        return new_lines

    def get_text(self, data):
        lines = list()
        prefix = 'code[{}]'.format(data.return_code)
        lines += self._get_chunk(prefix, data.command.split('\n'))
        lines += self._get_chunk('stdout:', data.stdout.splitlines())
        lines += self._get_chunk('stderr:', data.stderr.splitlines())
        return '\n'.join(lines)


class ExceptionMessage(PreMessage):
    def __init__(self, level='error', print_tb=False):
        type, value, tb = sys.exc_info()
        if print_tb:
            data = traceback.format_exception(type, value, tb)
        else:
            data = traceback.format_exception_only(type, value)
        data = str().join(data).decode('utf-8')
        super(ExceptionMessage, self).__init__(data, level)
