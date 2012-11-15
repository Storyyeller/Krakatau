from __future__ import division
import struct, collections

identity = lambda x:x

def decodeStr((s,)):
    return s.replace('\xc0\x80','\0').decode('utf8'),
def encodeStr((u,)):
    return u.encode('utf8').replace('\0','\xc0\x80'),
def strToBytes(args):
    s = encodeStr(args)[0]
    return struct.pack('>H',len(s)) + s

def trim(x, bits):
    m = 1<<bits
    x = x % m
    if x >= m//2:
        x -= m
    return x

cpoolInfo_t = collections.namedtuple('cpoolInfo_t',
                                     ['name','tag','fromArgs','recoverArgs','fromRaw','toBytes'])

Utf8 = cpoolInfo_t('Utf8',1,
                  (lambda self,s:(s,)),
                  (lambda self,(s,):(s,)),
                  decodeStr,
                  strToBytes)

Class = cpoolInfo_t('Class',7,
                    (lambda self,name:(self.Utf8(name),)),
                    (lambda self,(n_id,):self.getArgs(n_id)),
                    identity,
                    (lambda (n_id,): struct.pack('>H',n_id)))

NameAndType = cpoolInfo_t('NameAndType',12,
                (lambda self,name,desc:(self.Utf8(name),self.Utf8(desc))),
                (lambda self,(n,d):self.getArgs(n) + self.getArgs(d)),
                identity,
                (lambda (n,d): struct.pack('>HH',n,d)))

Field = cpoolInfo_t('Field',9,
                (lambda self,cls,name,desc:(self.Class(cls),self.NameAndType(name,desc))),
                (lambda self,(c_id, nat_id):self.getArgs(c_id) + self.getArgs(nat_id)),
                identity,
                (lambda (n,d): struct.pack('>HH',n,d)))

Method = cpoolInfo_t('Method',10,
                (lambda self,cls,name,desc:(self.Class(cls),self.NameAndType(name,desc))),
                (lambda self,(c_id, nat_id):self.getArgs(c_id) + self.getArgs(nat_id)),
                identity,
                (lambda (n,d): struct.pack('>HH',n,d)))

InterfaceMethod = cpoolInfo_t('InterfaceMethod',11,
                (lambda self,cls,name,desc:(self.Class(cls),self.NameAndType(name,desc))),
                (lambda self,(c_id, nat_id):self.getArgs(c_id) + self.getArgs(nat_id)),
                identity,
                (lambda (n,d): struct.pack('>HH',n,d)))

String = cpoolInfo_t('String',8,(lambda self,name:(self.Utf8(name),)),
                (lambda self,(n_id,):self.getArgs(n_id)),
                identity,
                (lambda (n_id,): struct.pack('>H',n_id)))

Int = cpoolInfo_t('Int',3,(lambda self,val:(trim(val,32),)),
                  (lambda self,(s,):(s,)),
                  identity,
                  (lambda (val,): struct.pack('>i',val)))

Long = cpoolInfo_t('Long',5,(lambda self,val:(trim(val,64),)),
                  (lambda self,(s,):(s,)),
                  identity,
                  (lambda (val,): struct.pack('>q',val)))

Float = cpoolInfo_t('Float',4,(lambda self,val:(val,)),
                  (lambda self,(s,):(s,)),
                  identity,
                  (lambda (val,): struct.pack('>f',val)))

Double = cpoolInfo_t('Double',6,(lambda self,val:(val,)),
                  (lambda self,(s,):(s,)),
                  identity,
                  (lambda (val,): struct.pack('>d',val)))

cpoolTypes = [Utf8, Class, NameAndType, Field, Method, InterfaceMethod,
              String, Int, Long, Float, Double]
name2Type = {t.name:t for t in cpoolTypes}
tag2Type = {t.tag:t for t in cpoolTypes}

class ConstPool(object):
    def __init__(self, initialData = [(None,None)]):
        self.pool = []

        for tag, val in initialData:
            if tag is None:
                self.addItem(None, None)
            else:
                t = tag2Type[tag]
                self.addItem(t.name, t.fromRaw(val))

    def getPoolIter(self):
        return (x for x in self.pool if x[0] is not None)
    def getEnumeratePoolIter(self):
        return ((i,x) for i,x in enumerate(self.pool) if x[0] is not None)

    def addItem(self, name, val):
        self.pool.append((name, val))
        return len(self.pool)-1

    def getArgs(self, i):
        if not (i >= 0 and i<len(self.pool)):
            raise IndexError('Constant pool index {} out of range'.format(i))        
        if self.pool[i][0] is None:
            raise IndexError('Constant pool index {} invalid'.format(i))
        
        name, val = self.pool[i]
        t = name2Type[name]
        return t.recoverArgs(self, val)

    # Special function for assembler
    def getItemRaw(self, item):
        if item[0] == 'Utf8':
            assert(isinstance(item[1][0], basestring))
        try:
            return self.pool.index(item)
        except ValueError:
            self.pool.append(item)
            i = len(self.pool)-1
            if item[0] in ('Long','Double'):
                self.addItem(None,None)
            return i

    # Accessors ####################################################################33
    def getArgsCheck(self, typen, index):
        assert(self.pool[index][0] == typen)
        val = self.getArgs(index)
        return val if len(val) > 1 else val[0]

    def getType(self, index): return self.pool[index][0]

    def bytes(self):
        parts = []
        pool = self.pool

        assert(len(pool) <= 65535)
        parts.append(struct.pack('>H',len(pool)))
        
        for name, vals in self.getPoolIter():
            t = name2Type[name]
            parts.append(struct.pack('>B',t.tag))
            parts.append(t.toBytes(vals))
        return ''.join(parts)

    def __str__(self, maxlen=79):
        def printLn(args):
            i,(name,val) = args
            if name == 'Utf8':
                s = val[0].encode('unicode_escape')
                return '{}: "{}"'.format(i, s)
            elif len(val) == 1:
                return '{}: {}({})'.format(i, name, val[0])
            else:
                return '{}: {}{}'.format(i, name, val)

        lines = [printLn(pair)[:maxlen] for pair in self.getEnumeratePoolIter()]
        return '\n'.join(lines)