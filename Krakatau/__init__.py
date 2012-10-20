'''Monkeypatch a fix for bugs.python.org/issue9825 in case users are running an old version.'''
import collections
del collections.OrderedDict.__del__