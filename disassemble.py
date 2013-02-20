import os.path
import time

import Krakatau
import Krakatau.binUnpacker
from Krakatau.classfile import ClassFile
import Krakatau.assembler.disassembler

from Krakatau import script_util

def disassembleClass(targets=None, outpath=None):
    if outpath is None:
        outpath = os.getcwd()


    # targets = targets[::-1]
    start_time = time.time()
    # random.shuffle(targets)
    for i,target in enumerate(targets):
        print 'processing target {}, {} remaining'.format(target, len(targets)-i)

        with open(target, 'rb') as f:
            data = f.read()
        stream = Krakatau.binUnpacker.binUnpacker(data=data)
        class_ = ClassFile(stream)

        source = Krakatau.assembler.disassembler.disassemble(class_)
        filename = script_util.writeFile(outpath, class_.name, '.j', source)
        print 'Class written to', filename
        print time.time() - start_time, ' seconds elapsed'

if __name__== "__main__":
    print 'Krakatau  Copyright (C) 2012-13  Robert Grosse'

    import argparse
    parser = argparse.ArgumentParser(description='Krakatau decompiler and bytecode analysis tool')
    parser.add_argument('-out',help='Path to generate files in')
    parser.add_argument('-r', action='store_true', help="Process all files in the directory target and subdirectories")
    parser.add_argument('target',help='Name of class or jar file to decompile')
    args = parser.parse_args()

    targets = script_util.findFiles(args.target, args.r, '.class')
    disassembleClass(targets, args.out)