import zipfile
import os.path

from .classfileformat.reader import Reader
from .classfile import ClassFile
from .error import ClassLoaderError

class Environment(object):
    def __init__(self):
        self.classes = {}
        self.path = []
        self._open = {}

    def addToPath(self, path):
        self.path.append(path)

    def _getSuper(self, name):
        if name in HARDCODED:
            return HARDCODED[name][0]
        return self.getClass(name).supername

    def getClass(self, name, partial=False):
        try:
            result = self.classes[name]
        except KeyError:
            result = self._loadClass(name)
        if not partial:
            result.loadElements()
        return result

    def isSubclass(self, name1, name2):
        if name2 == 'java/lang/Object':
            return True

        while name1 != 'java/lang/Object':
            if name1 == name2:
                return True
            name1 = self._getSuper(name1)
        return False

    def commonSuperclass(self, name1, name2):
        a, b = name1, name2
        supers = {a}
        while a != b and a != 'java/lang/Object':
            a = self._getSuper(a)
            supers.add(a)

        while b not in supers:
            b = self._getSuper(b)
        return b

    def isInterface(self, name, forceCheck=False):
        if name in HARDCODED:
            return HARDCODED[name][1]
        try:
            class_ = self.getClass(name, partial=True)
            return 'INTERFACE' in class_.flags
        except ClassLoaderError as e:
            if forceCheck:
                raise e
            # If class is not found, assume worst case, that it is a interface
            return True

    def isFinal(self, name):
        if name in HARDCODED:
            return HARDCODED[name][2]
        try:
            class_ = self.getClass(name, partial=True)
            return 'FINAL' in class_.flags
        except ClassLoaderError as e:
            return False

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

    def _loadClass(self, name):
        print "Loading", name.encode('utf8')[:70]
        data = self._searchForFile(name)

        if data is None:
            raise ClassLoaderError('ClassNotFoundException', name)

        stream = Reader(data=data)
        new = ClassFile(stream)
        new.env = self
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

# Hardcode required java classes to avoid depending on rt.jar
HARDCODED = {u'java/io/IOException': (u'java/lang/Exception', False, False), u'java/io/PrintStream': (u'java/io/FilterOutputStream', False, False), u'java/io/Serializable': (u'java/lang/Object', True, False), u'java/lang/AbstractStringBuilder': (u'java/lang/Object', False, False), u'java/lang/ArithmeticException': (u'java/lang/RuntimeException', False, False), u'java/lang/ArrayIndexOutOfBoundsException': (u'java/lang/IndexOutOfBoundsException', False, False), u'java/lang/ArrayStoreException': (u'java/lang/RuntimeException', False, False), u'java/lang/Boolean': (u'java/lang/Object', False, True), u'java/lang/CharSequence': (u'java/lang/Object', True, False), u'java/lang/Class': (u'java/lang/Object', False, True), u'java/lang/ClassCastException': (u'java/lang/RuntimeException', False, False), u'java/lang/Cloneable': (u'java/lang/Object', True, False), u'java/lang/Error': (u'java/lang/Throwable', False, False), u'java/lang/Exception': (u'java/lang/Throwable', False, False), u'java/lang/IllegalArgumentException': (u'java/lang/RuntimeException', False, False), u'java/lang/IllegalMonitorStateException': (u'java/lang/RuntimeException', False, False), u'java/lang/IndexOutOfBoundsException': (u'java/lang/RuntimeException', False, False), u'java/lang/Integer': (u'java/lang/Number', False, True), u'java/lang/Long': (u'java/lang/Number', False, True), u'java/lang/NegativeArraySizeException': (u'java/lang/RuntimeException', False, False), u'java/lang/NullPointerException': (u'java/lang/RuntimeException', False, False), u'java/lang/Number': (u'java/lang/Object', False, False), u'java/lang/NumberFormatException': (u'java/lang/IllegalArgumentException', False, False), u'java/lang/Object': (None, False, False), u'java/lang/OutOfMemoryError': (u'java/lang/VirtualMachineError', False, False), u'java/lang/RuntimeException': (u'java/lang/Exception', False, False), u'java/lang/String': (u'java/lang/Object', False, True), u'java/lang/StringBuffer': (u'java/lang/AbstractStringBuilder', False, True), u'java/lang/StringBuilder': (u'java/lang/AbstractStringBuilder', False, True), u'java/lang/Throwable': (u'java/lang/Object', False, False), u'java/lang/VirtualMachineError': (u'java/lang/Error', False, False), u'java/net/MalformedURLException': (u'java/io/IOException', False, False), u'java/nio/channels/FileLockInterruptionException': (u'java/io/IOException', False, False), u'java/nio/charset/UnsupportedCharsetException': (u'java/lang/IllegalArgumentException', False, False), u'java/util/ArrayList': (u'java/util/AbstractList', False, False), u'java/util/DuplicateFormatFlagsException': (u'java/util/IllegalFormatException', False, False), u'java/util/IllegalFormatException': (u'java/lang/IllegalArgumentException', False, False), u'java/util/UnknownFormatFlagsException': (u'java/util/IllegalFormatException', False, False)}
