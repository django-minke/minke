# -*- coding: utf-8 -*-
# Generated by Django 1.11.12 on 2019-03-17 22:11
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('minke', '0002_auto_20180619_1703'),
    ]

    operations = [
        migrations.CreateModel(
            name='AnySystem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=128)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Server',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, max_length=128, null=True)),
                ('host', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='minke.Host')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='anysystem',
            name='server',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='example.Server'),
        ),
    ]