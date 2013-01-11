import itertools

from .. import error as error_types
from .. import opnames
from .. import bytecode
from verifier_types import *

def parseFieldDescriptors(desc_str, unsynthesize=True):
    baseTypes = {'B':[T_BYTE], 'C':[T_CHAR], 'D':T_DOUBLE, 'F':[T_FLOAT],
                 'I':[T_INT], 'J':T_LONG, 'S':[T_SHORT], 'Z':[T_BOOL]}

    fields = []
    while desc_str:
        dim = 0
        while desc_str[0] == '[':
            desc_str = desc_str[1:]
            dim += 1
            
        if desc_str[0] == 'L':
            end = desc_str.index(';')
            name = desc_str[1:end]
            desc_str = desc_str[end+1:]
            baset = [T_OBJECT(name)]
        else:
            baset = baseTypes[desc_str[0]]
            desc_str = desc_str[1:]

        if dim:
            #Hotspot considers byte[] and bool[] identical for type checking purposes
            if unsynthesize and baset[0] == T_BOOL:
                baset = [T_BYTE]
            baset = [T_ARRAY(baset[0], dim)]
        elif len(baset) == 1:
            #synthetics are only meaningful as basetype of an array
            #if they are by themselves, convert to int.
            baset = [unSynthesizeType(baset[0])] if unsynthesize else [baset[0]]
        
        fields += baset
    return fields

#get a single descriptor
def parseFieldDescriptor(desc_str, unsynthesize=True):
    rval = parseFieldDescriptors(desc_str, unsynthesize)
    if rval[0].cat2:
        rval, extra = rval[:2], rval[2:]
    else:
        rval, extra = rval[:1], rval[1:]
    assert(not extra)
    return rval

#Parse a string to get a Java Method Descriptor
def parseMethodDescriptor(desc_str, unsynthesize=True):
    assert(desc_str[0] == '(')
    arg_end = desc_str.index(')')

    args, rval = desc_str[1:arg_end], desc_str[arg_end+1:]
    args = parseFieldDescriptors(args, unsynthesize)

    if rval == 'V':
        rval = []
    else:
        rval = parseFieldDescriptor(rval, unsynthesize)
    return args, rval

#Adds self argument for nonstatic. Constructors must be handled seperately
def parseUnboundMethodDescriptor(desc_str, target, isstatic):
    args, rval = parseMethodDescriptor(desc_str)
    if not isstatic:
        args = [T_OBJECT(target)] + args
    return args, rval
