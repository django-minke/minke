# -*- coding: utf-8 -*-
# Generated by Django 1.11.12 on 2018-10-28 14:32
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import minke.messages
import minke.sessions
import picklefield.fields


class Migration(migrations.Migration):

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('minke', '0002_auto_20180619_1703'),
    ]

    operations = [
        migrations.CreateModel(
            name='BaseMessage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('level', models.CharField(choices=[('info', 'info'), ('warning', 'warning'), ('error', 'error')], max_length=128)),
                ('text', models.TextField()),
                ('html', models.TextField()),
            ],
        ),
        migrations.CreateModel(
            name='BaseSession',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('object_id', models.PositiveIntegerField()),
                ('session_name', models.CharField(max_length=128)),
                ('session_data', picklefield.fields.PickledObjectField(blank=True, editable=False)),
                ('current', models.BooleanField(default=True)),
                ('status', models.CharField(choices=[('success', 'success'), ('warning', 'warning'), ('error', 'error')], default='success', max_length=128)),
                ('proc_status', models.CharField(choices=[('initialized', 'initialized'), ('running', 'running'), ('done', 'done')], default='initialized', max_length=128)),
                ('content_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.ContentType')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddField(
            model_name='basemessage',
            name='session',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='minke.BaseSession'),
        ),
        migrations.CreateModel(
            name='Message',
            fields=[
            ],
            options={
                'proxy': True,
                'indexes': [],
            },
            bases=(minke.messages.ProxyMixin, 'minke.basemessage'),
        ),
        migrations.CreateModel(
            name='Session',
            fields=[
            ],
            options={
                'proxy': True,
                'indexes': [],
            },
            bases=(minke.sessions.ProxyMixin, 'minke.basesession'),
        ),
        migrations.CreateModel(
            name='ExecutionMessage',
            fields=[
            ],
            options={
                'proxy': True,
                'indexes': [],
            },
            bases=('minke.message',),
        ),
        migrations.CreateModel(
            name='PreMessage',
            fields=[
            ],
            options={
                'proxy': True,
                'indexes': [],
            },
            bases=('minke.message',),
        ),
        migrations.CreateModel(
            name='SingleActionSession',
            fields=[
            ],
            options={
                'proxy': True,
                'indexes': [],
            },
            bases=('minke.session',),
        ),
        migrations.CreateModel(
            name='TableMessage',
            fields=[
            ],
            options={
                'proxy': True,
                'indexes': [],
            },
            bases=('minke.message',),
        ),
        migrations.CreateModel(
            name='UpdateEntriesSession',
            fields=[
            ],
            options={
                'proxy': True,
                'indexes': [],
            },
            bases=('minke.session',),
        ),
        migrations.CreateModel(
            name='ExceptionMessage',
            fields=[
            ],
            options={
                'proxy': True,
                'indexes': [],
            },
            bases=('minke.premessage',),
        ),
    ]
