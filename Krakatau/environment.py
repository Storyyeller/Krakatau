import zipfile
import os.path

from Krakatau import binUnpacker
from Krakatau import stdcache
from Krakatau.classfile import ClassFile
from Krakatau.error import ClassLoaderError

class Environment(object):
    def __init__(self):
        self.classes = {}
        self.path = []
        #Cache inheritance hierchies of standard lib classes so we don't have to load them to do subclass testing
        self.cache = stdcache.Cache(self, 'cache.txt')
        self._open = {}

    def addToPath(self, path):
        self.path.append(path)

    def getClass(self, name, subclasses=tuple(), partial=False):
        if name in subclasses:
            raise ClassLoaderError('ClassCircularityError', (name, subclasses))
        try:
            result = self.classes[name]
        except KeyError:
            result = self._loadClass(name, subclasses)
        if not partial:
            result.loadElements()
        return result

    def isSubclass(self, name1, name2):
        return name1 == name2 or (name2 in self.cache.superClasses(name1))
    def getFlags(self, name): return self.cache.flags(name)
    def getSupers(self, name): return self.cache.superClasses(name)
    def isCached(self, name): return self.cache.isCached(name)

    def _searchForFile(self, name):
        name += '.class'
        for place in self.path:
            try:
                archive = self._open[place]
            except KeyError: #plain folder
                try:
                    path = os.path.join(place, name)
                    with open(path, 'rb') as file_:
                        return file_.read()
                except IOError:
                    print 'failed to open', path.encode('utf8')
            else: #zip archive
                try:
                    return archive.read(name)
                except KeyError:
                    pass

    def _loadClass(self, name, subclasses):
        print "Loading", name.encode('utf8')[:70]
        data = self._searchForFile(name)

        if data is None:
            raise ClassLoaderError('ClassNotFoundException', name)

        stream = binUnpacker.binUnpacker(data=data)
        new = ClassFile(stream)
        new.loadSupers(self, name, subclasses)
        self.classes[new.name] = new
        return new

    #Context Manager methods to manager our zipfiles
    def __enter__(self):
        assert(not self._open)
        for place in self.path:
            if place.endswith('.jar') or place.endswith('.zip'):
                self._open[place] = zipfile.ZipFile(place, 'r').__enter__()
        return self

    def __exit__(self, type_, value, traceback):
        for place in reversed(self.path):
            if place in self._open:
                self._open[place].__exit__(type_, value, traceback)
                del self._open[place]