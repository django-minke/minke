# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from multiprocessing import Process
from multiprocessing import JoinableQueue
from threading import Thread
import logging

from django.contrib import messages

import minke.sessions
from .messages import Message
from .messages import Printer
from .models import BaseSession
from .tasks import process_sessions


logger = logging.getLogger(__name__)


def process(session_cls, queryset, session_data, user,
            fabric_config=None, join=False, console=False):
    """Initiate fabric's session-processing."""

    BaseSession.objects.clear_currents(user, queryset)
    hosts = queryset.get_hosts()
    lock = hosts.filter(disabled=False).get_lock()

    # group sessions by hosts
    session_groups = dict()
    for player in queryset.all():
        host = player.get_host()

        session = session_cls()
        session.user = user
        session.player = player
        session.session_data = session_data
        session.save()

        # Skip disabled or locked hosts...
        if host.disabled or host.locked and host.locked != lock:
            msg = 'disabled' if host.disabled else 'locked'
            msg = '{}: Host is {}.'.format(player, msg)
            session.messages.add(Message(msg, 'error'), bulk=False)
            session.status = 'error'
            session.proc_status = 'done'
            session.save(update_fields=['status', 'proc_status'])
            if console: Printer.prnt(session)

        # otherwise group sessions by hosts...
        else:
            if not session_groups.has_key(host):
                session_groups[host] = list()
            session_groups[host].append(session)

    # Stop here if no valid hosts are left...
    if not session_groups: return

    # run celery-tasks to process the sessions...
    results = list()
    for host, sessions in session_groups.items():
        try:
            result = process_sessions.delay(host, sessions, fabric_config)
            results.append((result, [s.id for s in sessions]))
        except process_sessions.OperationalError as exc:
            # TODO: What to do here?
            pass

    # print sessions in cli-mode as soon as they are ready...
    if console:
        print_results = results[:]
        while print_results:
            try: result, ids = next((r for r in print_results if r[0].ready()))
            except StopIteration: continue
            sessions = session_cls.objects.filter(id__in=ids)
            for session in sessions: Printer.prnt(session)
            print_results.remove((result, ids))

    # wait for joined sessions...
    elif join:
        for result, session_ids in results:
            result.wait()

    # At least call forget on every result - in case a result-backend is in use
    # that eats up ressources to store result-data...
    for result, session_ids in results:
        try: result.forget()
        except NotImplementedError: pass
