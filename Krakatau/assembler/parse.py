from ply import yacc
import math, ast
import itertools, collections

from ..classfile import ClassFile
from ..method import Method
from ..field import Field

from . import instructions as ins
from .tokenize import tokens, wordget
from .assembler import PoolRef

###############################################################################
def p_top(p):
    '''top : sep classdec superdec interfacedecs topitems'''
    p[0] = tuple(p[2:])

name_counter = itertools.count()
def addRule(func, name, *rhs_rules):
    def _inner(p):
        func(p)
    _inner.__doc__ = name + ' : ' + '\n| '.join(rhs_rules)
    fname = 'p_{}'.format(next(name_counter))
    globals()[fname] = _inner

def list_sub(p):p[0] = p[1] + p[2:]
def list_rule(name):
    name2 = name + 's'
    addRule(list_sub, name2, '{} {}'.format(name2, name), 'empty')

def assign1(p):p[0] = p[1]
def assign2(p):p[0] = p[2]
def upper1(p): p[0] = p[1].upper()

# Common Rules ################################################################
def p_sep(p):
    '''sep : sep NEWLINE
            | NEWLINE '''

def p_empty(p):
    'empty :'
    p[0] = []

def p_intl(p):
    '''intl : INT_LITERAL'''
    p[0] = ast.literal_eval(p[1])

def p_longl(p):
    '''longl : LONG_LITERAL'''
    p[0] = ast.literal_eval(p[1][:-1])

def parseFloat(s):
    if s in ('NaN','Inf','+Inf','-Inf'):
        return float(s)
    if s.strip('-')[:2].lower() == '0x':
        return float.fromhex(s)
    return ast.literal_eval(s)

def p_floatl(p):
    '''floatl : FLOAT_LITERAL'''
    p[0] = parseFloat(p[1][:-1])
def p_doublel(p):
    '''doublel : DOUBLE_LITERAL'''
    p[0] = parseFloat(p[1])


def p_ref(p):
    '''ref : CPINDEX'''
    s = p[1][1:-1]
    try:
        i = int(s)
        if 0 <= i <= 0xFFFF:
            p[0] = PoolRef(index=int(s))
        else:
            p[0] = PoolRef(lbl=s)    
    except ValueError:
        p[0] = PoolRef(lbl=s)

def assignCP(p, typen): p[0] = PoolRef(typen, *p[1:])

def p_utf8_notref(p):
    '''utf8_notref : GENERIC
                    | STRING_LITERAL'''
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

for name in ('utf8','class', 'nameandtype', 'field', 'method', 'interfacemethod', 'string'):
    addRule(assign1, '{}ref'.format(name), '{}_notref'.format(name), 'ref')

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

def p_superdec(p):
    '''superdec : DSUPER classref sep'''
    p[0] = p[2]

def p_interfacedec(p):
    '''interfacedec : DIMPLEMENTS classref sep'''
    p[0] = p[2]
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
def p_const_spec(p):
    '''const_spec : DCONST ref EQUALS const_rhs sep'''
    p[0] = p[2], p[4]

def p_const_rhs_0(p):
    '''const_rhs : ref'''
    p[0] = p[1]

def p_const_rhs_1(p):
    '''const_rhs : UTF8 utf8_notref'''
    p[0] = p[2]

for tt in ['CLASS','STRING','NAMEANDTYPE','FIELD','METHOD','INTERFACEMETHOD']:
    addRule(assign2, 'const_rhs', '{} {}ref'.format(tt, tt.lower()))

###############################################################################


def p_field_spec(p):
    '''field_spec : DFIELD fflags utf8ref utf8ref field_constval sep'''
    p[0] = p[2:6]

def p_field_constval_0(p):
    '''field_constval : empty'''
def p_field_constval_1(p):
    '''field_constval : EQUALS ldc1_ref'''
    p[0] = p[2]
def p_field_constval_2(p):
    '''field_constval : EQUALS ldc2_ref'''
    p[0] = p[2]



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
    '''jas_meth_namedesc : GENERIC'''
    name, paren, desc = p[1].rpartition('(')
    name = PoolRef('Utf8', name)
    desc = PoolRef('Utf8', paren+desc)
    p[0] = name, desc

def p_endmethod(p):
    '''endmethod : DEND METHOD sep'''

def p_statement_0(p):
    '''statement : method_directive sep'''
    p[0] = 'dir',p[1]
def p_statement_1(p):
    '''statement : empty instruction sep 
                | lbldec instruction sep
                | lbldec sep'''
    p[0] = 'ins', (p[1] or None), p[2]
list_rule('statement')

def p_lbldec(p):
    '''lbldec : lbl COLON'''
    p[0] = p[1]

def p_method_directive(p):
    '''method_directive : limit_dir 
                        | except_dir'''
    p[0] = p[1]

def p_limit_dir(p):
    '''limit_dir : DLIMIT LOCALS intl 
                | DLIMIT STACK intl'''
    p[0] = p[2], p[3]

def p_except_dir(p):
    '''except_dir : DCATCH classref FROM lbl TO lbl USING lbl'''
    p[0] = 'catch', p[2], p[4], p[6], p[8]

def p_instruction(p):
    '''instruction : OP_NONE
                    | OP_INT intl
                    | OP_INT_INT intl intl
                    | OP_LBL lbl
                    | OP_FIELD fieldref_or_jas
                    | OP_METHOD methodref_or_jas
                    | OP_METHOD_INT imethodref_or_jas intl
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

def p_lbl(p):
    '''lbl : GENERIC'''
    p[0] = p[1]

addRule(assign1, 'fieldref_or_jas', 'jas_fieldref', 'ref', 'inline_fieldref')
# addRule(assign1, 'fieldref_or_jas', 'fieldref')
def p_jas_fieldref(p):
    '''jas_fieldref : GENERIC GENERIC'''
    class_, sep, name = p[1].replace('.','/').rpartition('/')

    desc = PoolRef('Utf8', p[2])
    class_ = PoolRef('Class', PoolRef('Utf8', class_))
    name = PoolRef('Utf8', name)
    nt = PoolRef('NameAndType', name, desc)
    p[0] = PoolRef('Field', class_, nt)

#This is an ugly hack to work around the fact that Jasmin syntax would otherwise be impossible to 
#handle with a LALR(1) parser
def p_inline_fieldref_1(p):
    '''inline_fieldref : GENERIC nameandtyperef'''
    class_ = PoolRef('Class', PoolRef('Utf8', p[1]))
    p[0] = PoolRef('Field', class_, p[2])
def p_inline_fieldref_2(p):
    '''inline_fieldref : ref nameandtyperef'''
    p[0] = PoolRef('Field', p[1], p[2])


def p_jas_meth_classnamedesc(p):
    '''jas_methodref : GENERIC'''
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



_newarr_codes = dict(zip('boolean char float double byte short int long'.split(), range(4,12)))
_newarr_token_types = set(wordget.get(x, 'GENERIC') for x in _newarr_codes)
def p_nacode(p):
    p[0] = _newarr_codes[p[1]]
p_nacode.__doc__ = "nacode : " + '\n| '.join(_newarr_token_types)

def p_ldc1_ref_ref(p):
    '''ldc1_ref : ref'''
    p[0] = p[1]
def p_ldc1_ref_string(p):
    '''ldc1_ref : STRING_LITERAL'''
    p[0] = PoolRef('String', PoolRef('Utf8', p[1]))
def p_ldc1_ref_int(p):
    '''ldc1_ref : intl'''
    p[0] = PoolRef('Int', p[1])
def p_ldc1_ref_float(p):
    '''ldc1_ref : floatl'''
    p[0] = PoolRef('Float', p[1])

def p_ldc2_ref_long(p):
    '''ldc2_ref : longl'''
    p[0] = PoolRef('Long', p[1])
def p_ldc2_ref_double(p):
    '''ldc2_ref : doublel'''
    p[0] = PoolRef('Double', p[1])

def p_defaultentry(p):
    '''defaultentry : DEFAULT COLON lbl'''
    p[0] = p[3]

def p_luentry(p):
    '''luentry : intl COLON lbl sep'''
    p[0] = p[1], p[3]
list_rule('luentry')

def p_tblentry(p):
    '''tblentry : lbl sep'''
    p[0] = p[2]
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

def p_error(p):
    if p is None:
        print "Syntax error: unexpected EOF"
    else:
        print "Syntax error at line {}: unexpected token {}".format(p.lineno, p.value)
    
    #Ugly hack since Ply doesn't provide any useful error information
    import inspect
    frame = inspect.currentframe()
    cvars = frame.f_back.f_locals
    print 'Expected:', ', '.join(cvars['actions'][cvars['state']].keys())
    print 'Found:', cvars['ltype']
    print 'Current stack:', cvars['symstack']

def makeParser(**kwargs):
    return yacc.yacc(**kwargs)