import os.path

import Krakatau
from Krakatau.assembler import tokenize, parse, assembler
from Krakatau import script_util

def assembleClass(filename, makeLineNumbers, jasmode, debug=0):
    basename = os.path.basename(filename)
    assembly = open(filename, 'rb').read()
    if assembly.startswith('\xca\xfe') or assembly.startswith('\x50\x4b\x03\x04'):
        print 'Error: You appear to have passed a jar or classfile instead of an assembly file'
        print 'Perhaps you meant to invoke the disassembler instead?'
        return []

    assembly = '\n'+assembly+'\n' #parser expects newlines at beginning and end
    lexer = tokenize.makeLexer(debug=debug)
    parser = parse.makeParser(debug=debug)
    parse_trees = parser.parse(assembly, lexer=lexer)
    return parse_trees and [assembler.assemble(tree, makeLineNumbers, jasmode, basename) for tree in parse_trees]

if __name__== "__main__":
    print script_util.copyright

    import argparse
    parser = argparse.ArgumentParser(description='Krakatau bytecode assembler')
    parser.add_argument('-out',help='Path to generate files in')
    parser.add_argument('-g', action='store_true', help="Add line number information to the generated class")
    parser.add_argument('-jas', action='store_true', help="Enable Jasmin compatibility mode")
    parser.add_argument('-r', action='store_true', help="Process all files in the directory target and subdirectories")
    parser.add_argument('target',help='Name of file to assemble')
    args = parser.parse_args()

    targets = script_util.findFiles(args.target, args.r, '.j')
    writeout = script_util.fileDirOut(args.out, '.class')

    for i, target in enumerate(targets):
        print 'Processing file {}, {}/{} remaining'.format(target, len(targets)-i, len(targets))
        pairs = assembleClass(target, args.g, args.jas)

        # if pairs is None:
        #     print 'Assembly of ', target, 'failed!'
        #     continue

        for name, data in pairs:
            filename = writeout(name, data)
            print 'Class written to', filename