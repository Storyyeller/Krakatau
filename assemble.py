import os.path, zipfile

import Krakatau
from Krakatau.assembler import tokenize, parse, assembler

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
    parser.add_argument('-d',help='Path to generate files in')
    parser.add_argument('-out',help='Name of output file')
    parser.add_argument('-g', action='store_true', help="Add line number information to the generated class")
    parser.add_argument('-jas', action='store_true', help="Enable Jasmin compatibility mode")
    parser.add_argument('-r', action='store_true', help="Process all files in the directory target and subdirectories")
    parser.add_argument('target',help='Name of file to assemble')
    args = parser.parse_args()

    targets = [args.target]

    if args.r:
        assert(os.path.isdir(args.target))
        targets = []
        for root, dirs, files in os.walk(args.target):
            targets += [os.path.join(root, fname) for fname in files if fname.endswith('.j')]
        print len(targets), '.j files found in directory'

    for target in targets:
        name, data = assembleClass(target, args.g, args.jas)

        path = args.d if args.d is not None else os.getcwd()
        out = path
        if args.out is not None:
            out = os.path.join(path, args.out)
        if os.path.isdir(out):
            out = os.path.join(out, *name.split('/'))
            out += '.class'

        dirpath = os.path.dirname(out)
        if dirpath and not os.path.exists(dirpath):
            os.makedirs(dirpath)

        open(out, 'wb').write(data)
        print 'Class written to', out