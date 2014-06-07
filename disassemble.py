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
    writeout = script_util.fileDirOut(outpath, '.j')

    # targets = targets[::-1]
    start_time = time.time()
    # __import__('random').shuffle(targets)
    for i,target in enumerate(targets):
        script_util.printVerbose('processing target {}, {}/{} remaining'.format(target, len(targets)-i, len(targets)))

        data = readTarget(target)
        stream = Krakatau.binUnpacker.binUnpacker(data=data)
        class_ = ClassFile(stream)
        class_.loadElements(keepRaw=True)

        source = Krakatau.assembler.disassembler.disassemble(class_)
        filename = writeout(class_.name, source)
        script_util.printVerbose('Class written to ' + filename)
        script_util.printVerbose('{} seconds elapsed'.format(time.time() - start_time))

if __name__== "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Krakatau decompiler and bytecode analysis tool')
    parser.add_argument('-out',help='Path to generate files in')
    parser.add_argument('-r', action='store_true', help="Process all files in the directory target and subdirectories")
    parser.add_argument('-q', action='store_true', help="Quiet output; only show warnings or errors")
    parser.add_argument('-path',help='Jar to look for class in')
    parser.add_argument('target',help='Name of class or jar file to decompile')
    args = parser.parse_args()

    script_util.setVerbose(args.q == False)
    script_util.printVerbose(script_util.copyright)

    targets = script_util.findFiles(args.target, args.r, '.class')

    jar = args.path
    if jar is None and args.target.endswith('.jar'):
        jar = args.target

    #allow reading files from a jar if target is specified as a jar
    if jar:
        def readArchive(name):
            with zipfile.ZipFile(jar, 'r') as archive:
                return archive.open(name).read()
        readTarget = readArchive
    else:
        readTarget = readFile

    disassembleClass(readTarget, targets, args.out)