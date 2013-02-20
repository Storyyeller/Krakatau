import os.path

import Krakatau
from Krakatau.assembler import tokenize, parse, assembler
from Krakatau import script_util

def assembleClass(filename, makeLineNumbers, jasmode, debug=0):
    assembly = open(filename, 'rb').read()

    lexer = tokenize.makeLexer(debug=debug)
    parser = parse.makeParser(debug=debug)
    parse_tree = parser.parse('\n'+assembly+'\n', lexer=lexer)
    return assembler.assemble(parse_tree, makeLineNumbers, jasmode, os.path.basename(filename))

if __name__== "__main__":
    print 'Krakatau  Copyright (C) 2012-13  Robert Grosse'

    import argparse
    parser = argparse.ArgumentParser(description='Krakatau bytecode assembler')
    parser.add_argument('-out',help='Path to generate files in')
    parser.add_argument('-g', action='store_true', help="Add line number information to the generated class")
    parser.add_argument('-jas', action='store_true', help="Enable Jasmin compatibility mode")
    parser.add_argument('-r', action='store_true', help="Process all files in the directory target and subdirectories")
    parser.add_argument('target',help='Name of file to assemble')
    args = parser.parse_args()

    targets = script_util.findFiles(args.target, args.r, '.j')
    base_path = args.out if args.out is not None else os.getcwd()

    for target in targets:
        name, data = assembleClass(target, args.g, args.jas)
        filename = script_util.writeFile(base_path, name, '.class', data)
        print 'Class written to', filename
