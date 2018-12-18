# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import getpass

from django.contrib.auth.models import User

from minke.models import Host
from ..models import Server, AnySystem


def create_users():
    User.objects.create_superuser(
        'admin',
        'admin@testapp.org',
        'adminpassword')
    anyuser = User(username='anyuser', password='anyuserpassword')
    anyuser.save()

def create_hosts():
    # create a localhost with the current user
    # this might have a chance to be accessible via ssh
    user = getpass.getuser()
    host = Host.objects.create(
        hostname='localhost',
        host='localhost',
        user=user)

    # create some dummy-hosts as well
    for i in range(20):
        label = 'label' + str(i % 4) * 3
        hostname = 'host_{}_{}'.format(str(i), label)
        Host.objects.create(
            hostname=hostname,
            host=hostname,
            user='user' + label)

def create_players():
    for host in Host.objects.all():
        server = Server.objects.create(host=host, hostname=host.hostname)
        AnySystem.objects.create(server=server)

def create_test_data():
    create_users()
    create_hosts()
    create_players()
