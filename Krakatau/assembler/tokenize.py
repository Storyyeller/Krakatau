from ply import lex
import ast

from ..classfile import ClassFile
from ..method import Method
from ..field import Field
from .. import constant_pool
from . import instructions as ins

#Note: these values are used by the disassembler too - remember to update it if necessary
directives = 'CLASS','INTERFACE','SUPER','IMPLEMENTS','CONST','FIELD','METHOD','END','LIMIT','CATCH','SOURCE','LINE','VAR','THROWS','VERSION'
keywords = ['METHOD','LOCALS','STACK','FROM','TO','USING','DEFAULT','IS']
flags = ClassFile.flagVals.keys() + Method.flagVals.keys() + Field.flagVals.keys()

lowwords = (keywords + flags)
casewords = constant_pool.name2Type.keys()

wordget = {}
wordget.update({w.lower():w.upper() for w in lowwords})
wordget.update({w:w.upper() for w in casewords})
wordget.update({'.'+w.lower():'D'+w for w in directives})

assert(set(wordget).isdisjoint(ins.allinstructions))
for op in ins.instrs_noarg:
    wordget[op] = 'OP_NONE'
for op in ins.instrs_int:
    wordget[op] = 'OP_INT'
for op in ins.instrs_lbl:
    wordget[op] = 'OP_LBL'
for op in ('getstatic', 'putstatic', 'getfield', 'putfield'):
    wordget[op] = 'OP_FIELD'
#support invokenonvirtual for backwards compatibility with Jasmin
for op in ('invokevirtual', 'invokespecial', 'invokestatic', 'invokenonvirtual'): 
    wordget[op] = 'OP_METHOD'
for op in ('new', 'anewarray', 'checkcast', 'instanceof'):
    wordget[op] = 'OP_CLASS'
for op in ('wide','lookupswitch','tableswitch'):
    wordget[op] = 'OP_' + op.upper()

wordget['ldc'] = 'OP_LDC1'
wordget['ldc_w'] = 'OP_LDC1'
wordget['ldc2_w'] = 'OP_LDC2'
wordget['iinc'] = 'OP_INT_INT'
wordget['newarray'] = 'OP_NEWARR'
wordget['multianewarray'] = 'OP_CLASS_INT'
wordget['invokeinterface'] = 'OP_METHOD_INT'
wordget['invokedynamic'] = 'OP_DYNAMIC'

for op in ins.allinstructions:
    wordget.setdefault(op,op.upper())

#special PLY value
tokens = ('NEWLINE', 'COLON', 'EQUALS', 'WORD', 'CPINDEX', 
    'STRING_LITERAL', 'INT_LITERAL', 'LONG_LITERAL', 'FLOAT_LITERAL', 'DOUBLE_LITERAL') + tuple(set(wordget.values()))

def t_WORDS(t):
    t.type = wordget[t.value]
    return t
t_WORDS.__doc__ = r'(?:{})(?=$|[\s])'.format('|'.join(wordget.keys()))

def t_ignore_COMMENT(t):
    r';.*'

# Define a rule so we can track line numbers
def t_NEWLINE(t):
    r'\n+'
    t.lexer.lineno += len(t.value)
    return t

def t_STRING_LITERAL(t):
    # See http://stackoverflow.com/questions/430759/regex-for-managing-escaped-characters-for-items-like-string-literals/5455705#5455705
    r'''[uU]?[rR]?(?:
        """[^"\\]*              # any number of unescaped characters
            (?:\\.[^"\\]*       # escaped followed by 0 or more unescaped
                |"[^"\\]+       # single quote followed by at least one unescaped
                |""[^"\\]+      # two quotes followed by at least one unescaped
            )*"""
        |"[^"\n\\]*              # any number of unescaped characters
            (?:\\.[^"\n\\]*      # escaped followed by 0 or more unescaped
            )*"
    '''r"""                     # concatenated string literals
        |'''[^'\\]*              # any number of unescaped characters
            (?:\\.[^'\\]*       # escaped followed by 0 or more unescaped
                |'[^'\\]+       # single quote followed by at least one unescaped
                |''[^'\\]+      # two quotes followed by at least one unescaped
            )*'''
        |'[^'\n\\]*              # any number of unescaped characters
            (?:\\.[^'\n\\]*      # escaped followed by 0 or more unescaped
            )*'
        )"""

    t.value = ast.literal_eval(t.value)
    return t

#careful here: | is not greedy so hex must come first
int_base = r'[+-]?(?:0[xX][0-9a-fA-F]+|[0-9]+)'
float_base = r'''(?:
    [Nn][Aa][Nn]|                                       #Nan
    [-+]?(?:                                            #Inf and normal both use sign
        [Ii][Nn][Ff]|                                   #Inf
        \d+\.\d+(?:[eE][+-]?\d+)?|                         #decimal float
        0[xX][0-9a-fA-F]*\.[0-9a-fA-F]+[pP][+-]?\d+        #hexidecimal float
        )
    )
'''

t_INT_LITERAL = int_base
t_LONG_LITERAL = int_base + r'[lL]'
t_DOUBLE_LITERAL = float_base
t_FLOAT_LITERAL = float_base + r'[fF]'

t_COLON = r':'
t_EQUALS = r'='
t_CPINDEX = r'\[[0-9a-z_]+\]'
t_WORD = r'''[^\s:="']+'''
t_ignore = ' \t\r'

def t_error(t):
    print 'Parser error on line {} at {}'.format(t.lexer.lineno, t.lexer.lexpos)
    print t.value[:79]

def makeLexer(**kwargs):
    return lex.lex(**kwargs)