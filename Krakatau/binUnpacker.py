import struct

class binUnpacker(object):
    def __init__(self, data="", fileName=""):
        if fileName:
            self.bytes = open(fileName,'rb').read()
        else:
            self.bytes = data
        self.off = 0

    def get(self, fmt, forceTuple=False, peek=False):       
        val = struct.unpack_from(fmt, self.bytes, self.off)
        
        if not peek:
            self.off += struct.calcsize(fmt)
        if not forceTuple and len(val) == 1:
            val = val[0]
        return val

    def getRaw(self, num):
        val = self.bytes[self.off:self.off+num]
        self.off += num
        return val

    def size(self):
        return len(self.bytes) - self.off
