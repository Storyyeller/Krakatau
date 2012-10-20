'''Monkeypatch a fix for bugs.python.org/issue9825 in case users are running an old version.'''
import collections
try:
    del collections.OrderedDict.__del__
except AttributeError:
    pass