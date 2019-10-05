# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys
import django
sys.path.insert(0, os.path.abspath('../..'))
sys.path.insert(0, os.path.abspath('../../tests'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'testapp.settings'
django.setup()

# -- Project information -----------------------------------------------------

project = 'minke'
copyright = '2019, Thomas Leichtfuß'
author = 'Thomas Leichtfuß'


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.intersphinx',
    'sphinxcontrib.napoleon',
    # 'numpydoc',
]

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = 'sphinx_rtd_theme'

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']

# autodoc-configuration
autoclass_content = 'class'
autodoc_member_order = 'bysource'

# intersphinx-config
intersphinx_mapping = {
    'fabric': ('https://docs.fabfile.org/en/latest/', None),
    'invoke': ('http://docs.pyinvoke.org/en/latest/', None),
    'celery': ('https://docs.celeryproject.org/en/latest/', None),
    }

# numpydoc-configuration (not needed)
# numpydoc_show_class_members = True
# numpydoc_attributes_as_param_list = False