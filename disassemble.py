import os.path
import time, zipfile

import Krakatau
import Krakatau.binUnpacker
from Krakatau.classfile import ClassFile
import Krakatau.assembler.disassembler

from Krakatau import script_util

def readFile(filename):
    with open(filename, 'rb') as f:
        return f.read()

def disassembleClass(readTarget, targets=None, outpath=None):
    if outpath is None:
        outpath = os.getcwd()

    # targets = targets[::-1]
    start_time = time.time()
    # __import__('random').shuffle(targets)
    for i,target in enumerate(targets):
        print 'processing target {}, {}/{} remaining'.format(target, len(targets)-i, len(targets))

        data = readTarget(target)
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

    #allow reading files from a jar if target is specified as a jar
    if args.target.endswith('.jar'):
        def readArchive(name):
            with zipfile.ZipFile(args.target, 'r') as archive:
                return archive.open(name).read()
        readTarget = readArchive
    else:
        readTarget = readFile

    disassembleClass(readTarget, targets, args.out)