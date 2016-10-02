#!/usr/bin/env python2
import functools
import os.path
import time, zipfile, sys
import StringIO

import Krakatau
from Krakatau import script_util
from Krakatau.classfileformat.reader import Reader
from Krakatau.classfileformat.classdata import ClassData
from Krakatau.assembler.disassembly import Disassembler

def readArchive(archive, name):
    with archive.open(name.decode('utf8')) as f:
        return f.read()

def readFile(filename):
    with open(filename, 'rb') as f:
        return f.read()

def disassembleSub(readTarget, out, targets, roundtrip=False):
    start_time = time.time()
    with out:
        for i, target in enumerate(targets):
            print 'processing target {}, {}/{} remaining'.format(target, len(targets)-i, len(targets))

            data = readTarget(target)
            clsdata = ClassData(Reader(data))
            name = clsdata.pool.getclsutf(clsdata.this)

            output = StringIO.StringIO()
            # output = sys.stdout
            Disassembler(clsdata, output.write, roundtrip=roundtrip).disassemble()

            filename = out.write(name, output.getvalue())
            if filename is not None:
                # filename = out.write(target.replace('.class', ''), output.getvalue())
                print 'Class written to', filename
                print time.time() - start_time, ' seconds elapsed'

def disassembleFile(targets, out, roundtrip=False):
    disassembleSub(readFile, out, targets, args.roundtrip)

def disassembleJar(targets, out, roundtrip=False):
    with zipfile.ZipFile(jar, 'r') as archive:
        readFunc = functools.partial(readArchive, archive)
        disassembleSub(readFunc, out, targets, args.roundtrip)

if __name__== "__main__":
    print script_util.copyright

    import argparse
    parser = argparse.ArgumentParser(description='Krakatau decompiler and bytecode analysis tool')
    parser.add_argument('-out', help='Path to generate files in')
    parser.add_argument('-r', action='store_true', help="Process all files in the directory target and subdirectories")
    parser.add_argument('-path', help='Jar to look for class in')
    parser.add_argument('-roundtrip', action='store_true', help='Create assembly file that can roundtrip to original binary.')
    parser.add_argument('target', help='Name of class or jar file to decompile')
    args = parser.parse_args()

    targets = script_util.findFiles(args.target, args.r, '.class')

    jar = args.path
    if jar is None and args.target.endswith('.jar'):
        jar = args.target

    out = script_util.makeWriter(args.out, '.j')
    (disassembleJar if jar else disassembleFile)(targets, out, args.roundtrip)
