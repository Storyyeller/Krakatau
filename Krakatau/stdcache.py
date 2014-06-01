def shouldCache(name):
    return name.startswith('java/') or name.startswith('javax/')

class Cache(object):
    def __init__(self, env, filename):
        self.env = env
        self.filename = filename

        try:
            with open(self.filename, 'r') as f:
                fdata = f.read()
        except IOError:
            fdata = ''

        #Note, we assume \n will never appear in a class name. This should be true for classes in the Java package,
        #but isn't necessarily true for user defined classes (Which we don't cache anyway)
        lines = fdata.split('\n')[:-1]
        data = [[part.split(',') for part in line.split(';')] for line in lines]
        data = tuple(map(tuple, x) for x in data)
        self.data = {s[0][-1]:s for s in data}

    def _cache_info(self, class_):
        assert(class_.name not in self.data)
        newvals = class_.getSuperclassHierarchy(), class_.flags
        self.data[class_.name] = newvals
        writedata = ';'.join(','.join(x) for x in newvals)
        with open(self.filename, 'ab') as f:
            f.write(writedata + '\n')
        print class_.name, 'cached'

    def isCached(self, name): return name in self.data

    def superClasses(self, name):
        if name in self.data:
            return self.data[name][0]

        class_ = self.env.getClass(name, partial=True)
        if shouldCache(name):
            self._cache_info(class_)
        return class_.getSuperclassHierarchy()

    def flags(self, name):
        if name in self.data:
            return self.data[name][1]

        class_ = self.env.getClass(name, partial=True)
        if shouldCache(name):
            self._cache_info(class_)
        return class_.flags