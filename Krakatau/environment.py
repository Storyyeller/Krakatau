import zipfile
import os.path

from . import binUnpacker
from .classfile import ClassFile
from .error import ClassLoaderError

class Environment(object):
    def __init__(self):
        self.classes = {}
        self.path = []
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
        return name1 == name2 or (name2 in self.getClass(name1).getSuperclassHierarchy())

    def getData(self, name, suppressErrors):
        try:
            class_ = self.getClass(name, partial=True)
            return class_.getSuperclassHierarchy(), class_.flags, class_.all_interfaces
        except ClassLoaderError as e:
            if not suppressErrors:
                raise e
            return [None]*3

    def getSupers(self, name, suppressErrors=False): return self.getData(name, suppressErrors)[0]
    def getFlags(self, name, suppressErrors=False): return self.getData(name, suppressErrors)[1]
    def getInterfaces(self, name, suppressErrors=False): return self.getData(name, suppressErrors)[2]

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