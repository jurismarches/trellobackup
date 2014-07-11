#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys


try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup


readme = open('README.rst').read()
history = open('HISTORY.rst').read().replace('.. :changelog:', '')

requirements = [
    'wheel==0.23.0',
    'PyYAML==3.11',
    'oauth2==1.5.211',
    'py-trello==0.1.4',
]

test_requirements = [
    # TODO: put package test requirements here
]

setup(
    name='trellobackup',
    version='0.1.0',
    description='A simple script to periodically save the state of your trello boards."',
    long_description=readme + '\n\n' + history,
    author='Jurismarches',
    author_email='informatique@jurismarches.com',
    url='https://github.com/jurismarches/trellobackup',
    packages=[
        'trellobackup',
    ],
    package_dir={'trellobackup':
                 'trellobackup'},
    include_package_data=True,
    install_requires=requirements,
    license="BSD",
    zip_safe=False,
    keywords='trellobackup',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        "Programming Language :: Python :: 2",
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
    ],
    test_suite='tests',
    tests_require=test_requirements
)
