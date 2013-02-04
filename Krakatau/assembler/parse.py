from ply import yacc
import math, ast, struct
import itertools, collections

from ..classfile import ClassFile
from ..method import Method
from ..field import Field

from . import instructions as ins
from .tokenize import tokens, wordget, flags
from .assembler import PoolRef

#Specify the starting symbol
start = 'top'

###############################################################################
name_counter = itertools.count()
def addRule(func, name, *rhs_rules):
    def _inner(p):
        func(p)
    _inner.__doc__ = name + ' : ' + '\n| '.join(rhs_rules)
    fname = 'p_{}'.format(next(name_counter))
    globals()[fname] = _inner

def list_sub(p):p[0] = p[1] + p[2:]
def list_rule(name): #returns a list
    name2 = name + 's'
    addRule(list_sub, name2, '{} {}'.format(name2, name), 'empty')    

def nothing(p):pass
def assign1(p):p[0] = p[1]
def assign2(p):p[0] = p[2]
def upper1(p): p[0] = p[1].upper()

# Common Rules ################################################################
addRule(nothing, 'sep', 'sep NEWLINE', 'NEWLINE')

def p_empty(p):
    'empty :'
    p[0] = []

def p_intl(p):
    '''intl : INT_LITERAL'''
    p[0] = ast.literal_eval(p[1])

def p_longl(p):
    '''longl : LONG_LITERAL'''
    p[0] = ast.literal_eval(p[1][:-1])

#Todo - find a better way of handling floats
def parseFloat(s):
    s = s[:-1]
    if s.strip('-')[:2].lower() == '0x':
        f = float.fromhex(s)
    f = float(s)
    return struct.unpack('>i', struct.pack('>f', f))[0]

def parseDouble(s):
    if s.strip('-')[:2].lower() == '0x':
        f = float.fromhex(s)
    f = float(s)
    return struct.unpack('>q', struct.pack('>d', f))[0]

def p_floatl(p):
    '''floatl : FLOAT_LITERAL'''
    p[0] = parseFloat(p[1])
def p_doublel(p):
    '''doublel : DOUBLE_LITERAL'''
    p[0] = parseDouble(p[1])


okwords = set([w for w in wordget.values() if w not in flags])
addRule(assign1, 'notflag', 'WORD', 'STRING_LITERAL', *okwords)

def p_ref(p):
    '''ref : CPINDEX'''
    s = p[1][1:-1]
    try:
        i = int(s)
        if 0 <= i <= 0xFFFF:
            p[0] = PoolRef(index=i)
        else:
            p[0] = PoolRef(lbl=s)    
    except ValueError:
        p[0] = PoolRef(lbl=s)

def p_utf8_notref(p):
    '''utf8_notref : notflag'''
    p[0] = PoolRef('Utf8', p[1])

def p_class_notref(p):
    '''class_notref : utf8_notref'''
    p[0] = PoolRef('Class', p[1])

def p_string_notref(p):
    '''string_notref : utf8_notref'''
    p[0] = PoolRef('String', p[1])

def p_nat_notref(p):
    '''nameandtype_notref : utf8ref utf8ref'''
    p[0] = PoolRef('NameAndType', p[1], p[2])

def p_field_notref(p):
    '''field_notref : classref nameandtyperef'''
    p[0] = PoolRef('Field', p[1], p[2])

def p_method_notref(p):
    '''method_notref : classref nameandtyperef'''
    p[0] = PoolRef('Method', p[1], p[2])

def p_imethod_notref(p):
    '''interfacemethod_notref : classref nameandtyperef'''
    p[0] = PoolRef('InterfaceMethod', p[1], p[2])

#constant pool types related to InvokeDynamic handled later

for name in ('utf8','class', 'nameandtype', 'method', 'interfacemethod', 'methodhandle'):
    addRule(assign1, '{}ref'.format(name), '{}_notref'.format(name), 'ref')

###############################################################################
def p_top(p):
    '''top : sep version_opt sourcedir_opt classdec superdec interfacedecs topitems'''
    p[0] = tuple(p[2:])

def p_version(p):
    '''version_opt : DVERSION intl intl sep'''
    p[0] = p[2], p[3]
addRule(assign1, 'version_opt', 'empty')

#optional Jasmin source directive
addRule(assign2, 'sourcedir_opt', 'DSOURCE utf8ref sep')
addRule(assign1, 'sourcedir_opt', 'empty')

###############################################################################
for c, type_ in zip('cmf', (ClassFile, Method, Field)):
    name = "{}flag".format(c)
    addRule(upper1, name, *list(type_.flagVals))
    list_rule(name)

def p_classdec(p):
    '''classdec : DCLASS cflags classref sep 
                | DINTERFACE cflags classref sep'''
    #if interface, add interface to flags
    p[0] = (p[1] == '.interface'), p[2], p[3]

addRule(assign2, 'superdec', 'DSUPER classref sep')
addRule(assign2, 'interfacedec', 'DIMPLEMENTS classref sep')
list_rule('interfacedec')

def p_topitem_c(p):
    '''topitem : const_spec'''
    p[0] = 'const', p[1]
def p_topitem_f(p):
    '''topitem : field_spec'''
    p[0] = 'field', p[1]
def p_topitem_m(p):
    '''topitem : method_spec'''
    p[0] = 'method', p[1]
list_rule('topitem')

###############################################################################
#invoke dynamic stuff
from .codes import handle_codes
_handle_token_types = set(wordget.get(x, 'WORD') for x in handle_codes)
def p_handle(p):
    p[0] = handle_codes[p[1]]
p_handle.__doc__ = "handlecode : " + '\n| '.join(_handle_token_types)

#The second argument's type depends on the code, so we require an explicit reference for simplicity
def p_methodhandle_notref(p):
    '''methodhandle_notref : handlecode ref'''
    p[0] = PoolRef('MethodHandle', p[1], p[2])

def p_methodtype_notref(p):
    '''methodtype_notref : utf8_notref'''
    p[0] = PoolRef('Methodtype', p[1])

addRule(assign1, 'bootstrap_arg', 'ref') #TODO - allow inline constants and strings?
list_rule('bootstrap_arg')

def p_invokedynamic_notref(p):
    '''invokedynamic_notref : methodhandleref bootstrap_args COLON nameandtyperef'''
    args = [p[1]] + p[2] + [p[4]]
    p[0] = PoolRef('InvokeDynamic', *args)

###############################################################################
def p_const_spec(p):
    '''const_spec : DCONST ref EQUALS const_rhs sep'''
    p[0] = p[2], p[4]

def assignPoolSingle(typen):
    def inner(p):
        p[0] = PoolRef(typen, p[2])
    return inner

addRule(assign1, 'const_rhs', 'ref')
for tt in ['UTF8', 'CLASS','STRING','NAMEANDTYPE','FIELD','METHOD','INTERFACEMETHOD',
            'METHODHANDLE','METHODTYPE','INVOKEDYNAMIC']:
    addRule(assign2, 'const_rhs', '{} {}_notref'.format(tt, tt.lower()))

#these are special cases, since they take a single argument
#and the notref version can't have a ref as its argument due to ambiguity
for ptype in ('Class','String','MethodType'):
    addRule(assignPoolSingle(ptype), 'const_rhs', ptype.upper() + ' ref')

for ptype in ('Int','Float','Long','Double'):
    addRule(assignPoolSingle(ptype), 'const_rhs', '{} {}l'.format(ptype.upper(), ptype.lower()))
###############################################################################


def p_field_spec(p):
    '''field_spec : DFIELD fflags utf8ref utf8ref field_constval sep'''
    p[0] = p[2:6]

addRule(nothing, 'field_constval', 'empty')
addRule(assign2, 'field_constval', 'EQUALS ref', 
                                    'EQUALS ldc1_notref', 
                                    'EQUALS ldc2_notref')

def p_method_spec(p):
    '''method_spec : defmethod statements endmethod'''
    p[0] = p[1],p[2]

def p_defmethod_0(p):
    '''defmethod : DMETHOD mflags jas_meth_namedesc sep'''
    p[0] = p[2],p[3] 
def p_defmethod_1(p):
    '''defmethod : DMETHOD mflags utf8ref COLON utf8ref sep'''
    p[0] = p[2],(p[3], p[5]) 

def p_jas_meth_namedesc(p):
    '''jas_meth_namedesc : WORD'''
    name, paren, desc = p[1].rpartition('(')
    name = PoolRef('Utf8', name)
    desc = PoolRef('Utf8', paren+desc)
    p[0] = name, desc
addRule(nothing, 'endmethod', 'DEND METHOD sep')

def p_statement_0(p):
    '''statement : method_directive sep'''
    p[0] = 'dir',p[1]
def p_statement_1(p):
    '''statement : empty instruction sep 
                | lbldec instruction sep
                | lbldec sep'''
    p[0] = 'ins', ((p[1] or None), p[2])
list_rule('statement')

addRule(assign1, 'lbldec', 'lbl COLON')
addRule(assign1, 'method_directive', 'limit_dir', 'except_dir','localvar_dir','linenumber_dir','throws_dir','stack_dir')

def p_limit_dir(p):
    '''limit_dir : DLIMIT LOCALS intl 
                | DLIMIT STACK intl'''
    p[0] = p[2], p[3]

def p_except_dir(p):
    '''except_dir : DCATCH classref FROM lbl TO lbl USING lbl'''
    p[0] = 'catch', (p[2], p[4], p[6], p[8])

def p_throws_dir(p):
    '''throws_dir : DTHROWS classref'''
    p[0] = 'throws', p[2]

def p_linenumber_dir(p):
    '''linenumber_dir : DLINE intl'''
    p[0] = 'line', p[2]

def p_localvar_dir(p):
    '''localvar_dir : DVAR intl IS utf8ref utf8ref FROM lbl TO lbl'''
    p[0] = 'var', p[2], p[4], p[5], p[7], p[9]

def p_instruction(p):
    '''instruction : OP_NONE
                    | OP_INT intl
                    | OP_INT_INT intl intl
                    | OP_LBL lbl
                    | OP_FIELD fieldref_or_jas
                    | OP_METHOD methodref_or_jas
                    | OP_METHOD_INT imethodref_or_jas intl
                    | OP_DYNAMIC ref
                    | OP_CLASS classref
                    | OP_CLASS_INT classref intl
                    | OP_LDC1 ldc1_ref
                    | OP_LDC2 ldc2_ref
                    | OP_NEWARR nacode
                    | OP_LOOKUPSWITCH luswitch
                    | OP_TABLESWITCH tblswitch
                    | OP_WIDE wide_instr
                    '''
    if p[1] == 'invokenonvirtual':
        p[1] = 'invokespecial'
    p[0] = tuple(p[1:])
    #these instructions have 0 padding at the end
    #this is kind of an ungly hack, but the best way I could think of
    if p[1] in ('invokeinterface','invokedynamic'):
        p[0] += (0,)

addRule(assign1, 'lbl', 'WORD')
addRule(assign1, 'fieldref_or_jas', 'jas_fieldref', 'ref', 'inline_fieldref')
def p_jas_fieldref(p):
    '''jas_fieldref : WORD WORD'''
    class_, sep, name = p[1].replace('.','/').rpartition('/')

    desc = PoolRef('Utf8', p[2])
    class_ = PoolRef('Class', PoolRef('Utf8', class_))
    name = PoolRef('Utf8', name)
    nt = PoolRef('NameAndType', name, desc)
    p[0] = PoolRef('Field', class_, nt)

#This is an ugly hack to work around the fact that Jasmin syntax would otherwise be impossible to 
#handle with a LALR(1) parser
def p_inline_fieldref_1(p):
    '''inline_fieldref : WORD nameandtyperef
                        | STRING_LITERAL nameandtyperef'''
    class_ = PoolRef('Class', PoolRef('Utf8', p[1]))
    p[0] = PoolRef('Field', class_, p[2])
def p_inline_fieldref_2(p):
    '''inline_fieldref : ref nameandtyperef'''
    p[0] = PoolRef('Field', p[1], p[2])


def p_jas_meth_classnamedesc(p):
    '''jas_methodref : WORD'''
    name, paren, desc = p[1].rpartition('(')
    class_, sep, name = name.replace('.','/').rpartition('/')
    desc = paren + desc

    class_ = PoolRef('Class', PoolRef('Utf8', class_))
    nt = PoolRef('NameAndType', PoolRef('Utf8', name), PoolRef('Utf8', desc))
    p[0] = class_, nt

addRule(assign1, 'methodref_or_jas', 'methodref')
def p_methodref_or_jas(p):
    '''methodref_or_jas : jas_methodref'''
    p[0] = PoolRef('Method', *p[1])

addRule(assign1, 'imethodref_or_jas', 'interfacemethodref')
def p_imethodref_or_jas(p):
    '''imethodref_or_jas : jas_methodref'''
    p[0] = PoolRef('InterfaceMethod', *p[1])


from .codes import newarr_codes
_newarr_token_types = set(wordget.get(x, 'WORD') for x in newarr_codes)
def p_nacode(p):
    p[0] = newarr_codes[p[1]]
p_nacode.__doc__ = "nacode : " + '\n| '.join(_newarr_token_types)

addRule(assign1, 'ldc1_ref', 'ldc1_notref', 'ref')
def p_ldc1_notref_string(p):
    '''ldc1_notref : STRING_LITERAL'''
    p[0] = PoolRef('String', PoolRef('Utf8', p[1]))
def p_ldc1_notref_int(p):
    '''ldc1_notref : intl'''
    p[0] = PoolRef('Int', p[1])
def p_ldc1_notref_float(p):
    '''ldc1_notref : floatl'''
    p[0] = PoolRef('Float', p[1])

addRule(assign1, 'ldc2_ref', 'ldc2_notref', 'ref')
def p_ldc2_notref_long(p):
    '''ldc2_notref : longl'''
    p[0] = PoolRef('Long', p[1])
def p_ldc2_notref_double(p):
    '''ldc2_notref : doublel'''
    p[0] = PoolRef('Double', p[1])

def p_defaultentry(p):
    '''defaultentry : DEFAULT COLON lbl'''
    p[0] = p[3]

def p_luentry(p):
    '''luentry : intl COLON lbl sep'''
    p[0] = p[1], p[3]
list_rule('luentry')

addRule(assign2, 'tblentry', 'lbl sep')
list_rule('tblentry')

def p_lookupswitch(p):
    '''luswitch : empty sep luentrys defaultentry'''
    p[0] = p[1], p[3], p[4]

def p_tableswitch(p):
    '''tblswitch : intl sep tblentrys defaultentry'''
    p[0] = p[1], p[3], p[4]

def p_wide_instr(p):
    '''wide_instr : OP_INT intl
                | OP_INT_INT intl intl'''
    p[0] = tuple(p[1:])
#######################################################################
#Stack map stuff
addRule(nothing, 'endstack', 'DEND STACK') #directives are not expected to end with a sep

def assign1All(p):p[0] = tuple(p[1:])
addRule(assign1All, 'verification_type', 'TOP', 'INTEGER', 'FLOAT', 'DOUBLE', 'LONG', 'NULL', 'UNINITIALIZEDTHIS',
                                        'OBJECT classref', 'UNINITIALIZED lbl')
list_rule('verification_type')
addRule(assign2, 'locals_vtlist', 'LOCALS verification_types sep')
addRule(assign2, 'stack_vtlist', 'STACK verification_types sep')

def p_stack_dir(p):
    '''stack_dir_rest : SAME 
                    | SAME_EXTENDED
                    | CHOP intl 
                    | SAME_LOCALS_1_STACK_ITEM sep stack_vtlist endstack
                    | SAME_LOCALS_1_STACK_ITEM_EXTENDED sep stack_vtlist endstack
                    | APPEND sep locals_vtlist endstack
                    | FULL sep locals_vtlist stack_vtlist endstack'''
    p[0] = 'stackmap', tuple(p[1:])
addRule(assign2, 'stack_dir', 'DSTACK stack_dir_rest')
#######################################################################

def p_error(p):
    if p is None:
        print "Syntax error: unexpected EOF"
    else: #remember to subtract 1 from line number since we had a newline at the start of the file
        print "Syntax error at line {}: unexpected token {}".format(p.lineno-1, p.value)
    
    #Ugly hack since Ply doesn't provide any useful error information
    import inspect
    frame = inspect.currentframe()
    cvars = frame.f_back.f_locals
    print 'Expected:', ', '.join(cvars['actions'][cvars['state']].keys())
    print 'Found:', cvars['ltype']
    print 'Current stack:', cvars['symstack']

def makeParser(**kwargs):
    return yacc.yacc(**kwargs)