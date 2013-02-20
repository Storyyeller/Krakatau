import zipfile
import os.path

import binUnpacker
import stdcache
from classfile import ClassFile
from error import ClassLoaderError

class Environment(object):
    def __init__(self):
        self.classes = {}
        self.path = []
        #Cache inheritance hierchies of standard lib classes so we don't have to load them to do subclass testing
        self.cache = stdcache.Cache(self, 'cache.txt')

    def addToPath(self, path):
        self.path.append(path)

    def getClass(self, name, subclasses = tuple(), loadSuper = True):
        if name in subclasses:
            raise ClassLoaderError('ClassCircularityError', (name, subclasses))
        try:
            return self.classes[name]
        except KeyError:
            self._loadClass(name, subclasses, loadSuper)
            return self.classes[name]     

    def isSubclass(self, name1, name2):
        return name1 == name2 or (name2 in self.cache.superClasses(name1))
    def getFlags(self, name): return self.cache.flags(name)
    def getSupers(self, name): return self.cache.superClasses(name)
    def isCached(self, name): return self.cache.isCached(name)

    def _searchForFile(self, name):
        name += '.class'

        for place in self.path:
            if place[-4:] in ('.jar','.zip'):
                try:
                    with zipfile.ZipFile(place, 'r') as archive:
                        return archive.read(name)
                except KeyError:
                    pass
            else: #plain folder
                try:
                    path = os.path.join(place, name)
                    with open(path, 'rb') as file:
                        return file.read()
                except IOError:
                    pass

    def _loadClass(self, name, subclasses, loadSuper):
        print "Loading ", name[:70]
        data = self._searchForFile(name)

        if data is None:
            raise ClassLoaderError('ClassNotFoundException', name)
        
        stream = binUnpacker.binUnpacker(data=data)
        new = ClassFile(self, stream)
        self.classes[name] = new  

        if loadSuper:
            new.load(name, subclasses)
