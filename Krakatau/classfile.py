from __future__ import division
import collections

import binUnpacker, constant_pool, method, field

cp_structFmts = {3: '>i',
                4: '>i',    #floats and doubles internally represented as integers with same bit pattern
                5: '>q',
                6: '>q',
                7: '>H',
                8: '>H',
                9: '>HH',
                10: '>HH',
                11: '>HH',
                12: '>HH',
                15: '>BH',
                16: '>H',
                18: '>HH'}

def get_cp_raw(bytestream):
    const_count = bytestream.get('>H')
    assert(const_count > 1)

    placeholder = None,None
    pool = [placeholder]

    while len(pool) < const_count:
        tag = bytestream.get('B')
        if tag == 1: #utf8
            length = bytestream.get('>H')
            data = bytestream.getRaw(length)
            val = tag, (data,)
        else:
            val = tag,bytestream.get(cp_structFmts[tag], True)
        pool.append(val)
        #Longs and Doubles take up two spaces in the pool
        if tag == 5 or tag == 6:
            pool.append(placeholder)
    assert(len(pool) == const_count)
    return pool

from attributes_raw import get_attributes_raw

def get_field_raw(bytestream):
    flags, name, desc = bytestream.get('>HHH')
    attributes = get_attributes_raw(bytestream)
    return flags, name, desc, attributes

def get_fields_raw(bytestream):
    count = bytestream.get('>H')
    return [get_field_raw(bytestream) for i in range(count)]

#fields and methods have same raw format
get_method_raw = get_field_raw
get_methods_raw = get_fields_raw

class ClassFile(object):
    flagVals = {'PUBLIC':0x0001,
                'FINAL':0x0010,
                'SUPER':0x0020,
                'INTERFACE':0x0200,
                'ABSTRACT':0x0400,
                'SYNTHETIC':0x1000, 
                'ANNOTATION':0x2000, 
                'ENUM':0x4000, 
                }

    def __init__(self, bytestream):
        magic, minor, major = bytestream.get('>LHH')
        assert(magic == 0xCAFEBABE)
        self.version = major,minor

        self.const_pool_raw = get_cp_raw(bytestream)
        flags, self.this, self.super = bytestream.get('>HHH')

        interface_count = bytestream.get('>H')
        self.interfaces_raw = [bytestream.get('>H') for i in range(interface_count)]

        self.fields_raw = get_fields_raw(bytestream)
        self.methods_raw = get_methods_raw(bytestream)
        self.attributes_raw = get_attributes_raw(bytestream)
        assert(bytestream.size() == 0)

        self.flags = set(name for name,mask in ClassFile.flagVals.items() if (mask & flags))

        #convert raw data
        self.cpool = constant_pool.ConstPool(self.const_pool_raw)
        self.name = self.cpool.getArgsCheck('Class', self.this)
        
        self.fields = [field.Field(m, self) for m in self.fields_raw]    
        self.methods = [method.Method(m, self) for m in self.methods_raw]

    def load(self, env, name, subclasses):
        self.env = env
        assert(self.name == name)

        if self.super:
            self.supername = self.cpool.getArgsCheck('Class', self.super)
            # if superclass is cached, we can assume it is free from circular inheritance
            # since it must have been loaded successfully on a previous run 
            if not self.env.isCached(self.supername):
                self.env.getClass(self.supername, subclasses + (name,))
            self.hierachy = self.env.getSupers(self.supername) + (self.name,)         
        else:
            assert(name == 'java/lang/Object')
            self.supername = None
            self.hierachy = (self.name,)

    def getSuperclassHierachy(self):
        return self.hierachy