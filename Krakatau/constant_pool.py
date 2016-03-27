import collections
import struct

# ConstantPool stores strings as strings or unicodes. They are automatically
# converted to and from modified Utf16 when reading and writing to binary

# Floats and Doubles are internally stored as integers with the same bit pattern
# Since using raw floats breaks equality testing for signed zeroes and NaNs
# cpool.getArgs/getArgsCheck will automatically convert them into Python floats

def decodeStr(s):
    return s.replace('\xc0\x80','\0').decode('utf8'),
def encodeStr(u):
    return u.encode('utf8').replace('\0','\xc0\x80'),
def strToBytes(args):
    s = encodeStr(args)[0]
    return struct.pack('>H',len(s)) + s

def decodeFloat(i):
    return struct.unpack('>f', struct.pack('>i', i)) # Note: returns tuple
def decodeDouble(i):
    return struct.unpack('>d', struct.pack('>q', i))

cpoolInfo_t = collections.namedtuple('cpoolInfo_t',
                                     ['name','tag','recoverArgs','toBytes'])

Utf8 = cpoolInfo_t('Utf8',1,
                  (lambda self,s:(s,)),
                  strToBytes)

Class = cpoolInfo_t('Class',7,
                    (lambda self,n_id:self.getArgs(n_id)),
                    (lambda n_id: struct.pack('>H',n_id)))

NameAndType = cpoolInfo_t('NameAndType',12,
                (lambda self,n,d:self.getArgs(n) + self.getArgs(d)),
                (lambda n,d: struct.pack('>HH',n,d)))

Field = cpoolInfo_t('Field',9,
                (lambda self,c_id,nat_id:self.getArgs(c_id) + self.getArgs(nat_id)),
                (lambda n,d: struct.pack('>HH',n,d)))

Method = cpoolInfo_t('Method',10,
                (lambda self,c_id,nat_id:self.getArgs(c_id) + self.getArgs(nat_id)),
                (lambda n,d: struct.pack('>HH',n,d)))

InterfaceMethod = cpoolInfo_t('InterfaceMethod',11,
                (lambda self,c_id,nat_id:self.getArgs(c_id) + self.getArgs(nat_id)),
                (lambda n,d: struct.pack('>HH',n,d)))

String = cpoolInfo_t('String',8,
                (lambda self,n_id:self.getArgs(n_id)),
                (lambda n_id: struct.pack('>H',n_id)))

Int = cpoolInfo_t('Int',3,
                  (lambda self,s:(s,)),
                  (lambda val: struct.pack('>i',val)))

Long = cpoolInfo_t('Long',5,
                  (lambda self,s:(s,)),
                  (lambda val: struct.pack('>q',val)))

Float = cpoolInfo_t('Float',4,
                  (lambda self,s:decodeFloat(s)),
                  (lambda val: struct.pack('>i',val)))

Double = cpoolInfo_t('Double',6,
                  (lambda self,s:decodeDouble(s)),
                  (lambda val: struct.pack('>q',val)))

MethodHandle = cpoolInfo_t('MethodHandle',15,
                (lambda self,t,n_id:(t,)+self.getArgs(n_id)),
                (lambda t,n_id: struct.pack('>BH',t, n_id)))

MethodType = cpoolInfo_t('MethodType',16,
                (lambda self,n_id:self.getArgs(n_id)),
                (lambda n_id: struct.pack('>H',n_id)))

InvokeDynamic = cpoolInfo_t('InvokeDynamic',18,
                (lambda self,bs_id,nat_id:(bs_id,) + self.getArgs(nat_id)),
                (lambda n,d: struct.pack('>HH',n,d)))

cpoolTypes = [Utf8, Class, NameAndType, Field, Method, InterfaceMethod,
              String, Int, Long, Float, Double,
              MethodHandle, MethodType, InvokeDynamic]
name2Type = {t.name:t for t in cpoolTypes}
tag2Type = {t.tag:t for t in cpoolTypes}

class ConstPool(object):
    def __init__(self, initialData=((None,None),)):
        self.pool = []
        self.reserved = set()
        self.available = set()

        for tag, val in initialData:
            if tag is None:
                self.addEmptySlot()
            else:
                t = tag2Type[tag]
                if t.name == 'Utf8':
                    val = decodeStr(*val)
                self.pool.append((t.name, val))

    def size(self): # Number of slots including gaps, not number of entries
        return len(self.pool)
    def getPoolIter(self):
        return (x for x in self.pool if x[0] is not None)
    def getEnumeratePoolIter(self):
        return ((i,x) for i,x in enumerate(self.pool) if x[0] is not None)

    def addEmptySlot(self):
        self.pool.append((None, None))

    def getAvailableIndex(self):
        if self.available:
            return self.available.pop()
        while len(self.pool) in self.reserved:
            self.addEmptySlot()
        self.addEmptySlot()
        return len(self.pool)-1

    def getAvailableIndex2(self):
        for i in self.available:
            if i+1 in self.available:
                self.available.remove(i)
                self.available.remove(i+1)
                return i

        while len(self.pool) in self.reserved or len(self.pool)+1 in self.reserved:
            self.addEmptySlot()
        self.addEmptySlot()
        self.addEmptySlot()
        return len(self.pool)-2

    # Special function for assembler
    def addItem(self, item, index=None):
        if index is None and item in self.pool:
            return self.pool.index(item)

        if item[0] == 'Utf8':
            assert isinstance(item[1][0], basestring)
        cat2 = item[0] in ('Long','Double')

        if index is None:
            index = self.getAvailableIndex2() if cat2 else self.getAvailableIndex()
        else:
            temp = len(self.pool)
            if index >= temp:
                # If desired slot is past the end of current range, add a bunch of placeholder slots
                self.pool += [(None,None)] * (index+1-temp)
                self.available.update(range(temp,index))
                self.available -= self.reserved

            self.reserved.remove(index)
            if cat2:
                self.reserved.remove(index+1)
                self.addEmptySlot()

        assert index not in self.reserved
        self.pool[index] = item
        return index

    def copyItem(self, src, index):
        return self.addItem(self.pool[src], index=index)

    # Accessors ######################################################################
    def getArgs(self, i):
        if not (i >= 0 and i<len(self.pool)):
            raise IndexError('Constant pool index {} out of range'.format(i))
        if self.pool[i][0] is None:
            raise IndexError('Constant pool index {} invalid'.format(i))

        name, val = self.pool[i]
        t = name2Type[name]
        return t.recoverArgs(self, *val)

    def getArgsCheck(self, typen, index):
        # if (self.pool[index][0] != typen):
        #     raise KeyError('Constant pool index {} has incorrect type {}'.format(index, typen))
        val = self.getArgs(index)
        return val if len(val) > 1 else val[0]

    def getType(self, index): return self.pool[index][0]

    ##################################################################################
    def fillPlaceholders(self):
        # fill in all the placeholder slots with a dummy reference. Class and String items
        # have the smallest size (3 bytes). There should always be an existing class item
        # we can copy
        dummy = next(item for item in self.pool if item[0] == 'Class')
        for i in self.available:
            self.pool[i] = dummy

    def bytes(self):
        parts = []
        pool = self.pool

        assert not self.reserved
        self.fillPlaceholders()

        assert len(pool) <= 65535
        parts.append(struct.pack('>H',len(pool)))

        for name, vals in self.getPoolIter():
            t = name2Type[name]
            parts.append(struct.pack('>B',t.tag))
            parts.append(t.toBytes(*vals))
        return ''.join(parts)
