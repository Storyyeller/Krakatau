# core modules
from setuptools import find_packages
from setuptools import setup
import io
import os
import unittest


def read(file_name):
    """Read a text file and return the content as a string."""
    with io.open(os.path.join(os.path.dirname(__file__), file_name),
                 encoding='utf-8') as f:
        return f.read()


def my_test_suite():
    """Return a a composite test consisting of a number of TestCases."""
    test_loader = unittest.TestLoader()
    test_suite = test_loader.discover('tests', pattern='test_*.py')
    return test_suite


config = {
    'name': 'Krakatau',
    'version': '0.1.0',
    'author': 'Robert Grosse',
    # 'author_email': '[[email]]',
    'maintainer': 'Robert Grosse',
    # 'maintainer_email': '[[email]]',
    'packages': find_packages(),
    'scripts': ['bin/krakatau',
                'assemble.py',
                'decompile.py',
                'disassemble.py',
                ],
    'platforms': ['Linux'],
    'url': 'https://github.com/Storyyeller/Krakatau',
    'download_url': 'https://github.com/Storyyeller/Krakatau',
    'license': 'GNUv3',
    'description': 'Java decompiler, assembler, and disassembler',
    'long_description': read('README.TXT'),
    'long_description_content_type': 'text/markdown',
    'install_requires': ['click'],
    'keywords': ['utility'],
    # https://pypi.org/pypi?%3Aaction=list_classifiers
    'classifiers': ['Development Status :: 1 - Planning',
                    'Environment :: Console',
                    'Intended Audience :: Developers',
                    'Natural Language :: English',
                    'Programming Language :: Python :: 2.7',
                    'Programming Language :: Python :: 3.6',
                    ],
    'zip_safe': True,
    'test_suite': 'setup.my_test_suite',
}

setup(**config)
