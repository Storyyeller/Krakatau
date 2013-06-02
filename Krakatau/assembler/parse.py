import ast, struct
import itertools

from ..classfile import ClassFile
from ..method import Method
from ..field import Field

#Important to import tokens here even though it appears unused, as ply uses it
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
def listRule(name): #returns a list
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
    else:
        f = float(s)
    return struct.unpack('>i', struct.pack('>f', f))[0]

def parseDouble(s):
    if s.strip('-')[:2].lower() == '0x':
        f = float.fromhex(s)
    else:
        f = float(s)
    return struct.unpack('>q', struct.pack('>d', f))[0]

def p_floatl(p):
    '''floatl : FLOAT_LITERAL'''
    p[0] = parseFloat(p[1])
def p_doublel(p):
    '''doublel : DOUBLE_LITERAL'''
    p[0] = parseDouble(p[1])

#We can allow keywords as inline classnames as long as they aren't flag names
#which would be ambiguous. We don't allow directives to simplfy the grammar
#rules, since they wouldn't be valid identifiers anyway.
badwords = frozenset(map(str.lower, flags))
badwords |= frozenset(k for k in wordget if '.' in k) 
oktokens = frozenset(v for k,v in wordget.items() if k not in badwords)
addRule(assign1, 'notflag', 'WORD', 'STRING_LITERAL', *oktokens)

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

for _name in ('utf8','class', 'nameandtype', 'method', 'interfacemethod', 'methodhandle'):
    addRule(assign1, '{}ref'.format(_name), '{}_notref'.format(_name), 'ref')

###############################################################################
def p_classnoend(p):
    '''classnoend : version_opt class_directive_lines classdec superdec interfacedecs class_directive_lines topitems'''
    p[0] = tuple(p[1:])

addRule(assign1, 'classwithend', 'classnoend D_END CLASS sep')
listRule('classwithend')

def p_top(p):
    '''top : sep classwithends classnoend'''
    p[0] = p[2] + [p[3]]
#case where all classes have an end
addRule(assign2, 'top', 'sep classwithends')

def p_version(p):
    '''version_opt : D_VERSION intl intl sep'''
    p[0] = p[2], p[3]
addRule(assign1, 'version_opt', 'empty')

###############################################################################
for c, type_ in zip('cmf', (ClassFile, Method, Field)):
    _name = "{}flag".format(c)
    addRule(upper1, _name, *list(type_.flagVals))
    listRule(_name)

def p_classdec(p):
    '''classdec : D_CLASS cflags classref sep 
                | D_INTERFACE cflags classref sep'''
    #if interface, add interface to flags
    p[0] = (p[1] == '.interface'), p[2], p[3]

addRule(assign2, 'superdec', 'D_SUPER classref sep')
addRule(assign2, 'interfacedec', 'D_IMPLEMENTS classref sep')
listRule('interfacedec')

addRule(assign1, 'class_directive', 'classattribute', 'innerlength_dir')
addRule(assign1, 'class_directive_line', 'class_directive sep')
listRule('class_directive_line')

def p_topitem_c(p):
    '''topitem : const_spec'''
    p[0] = 'const', p[1]
def p_topitem_f(p):
    '''topitem : field_spec'''
    p[0] = 'field', p[1]
def p_topitem_m(p):
    '''topitem : method_spec'''
    p[0] = 'method', p[1]
listRule('topitem')

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
listRule('bootstrap_arg')

def p_invokedynamic_notref(p):
    '''invokedynamic_notref : methodhandleref bootstrap_args COLON nameandtyperef'''
    args = [p[1]] + p[2] + [p[4]]
    p[0] = PoolRef('InvokeDynamic', *args)

###############################################################################
def p_const_spec(p):
    '''const_spec : D_CONST ref EQUALS const_rhs sep'''
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
    '''field_spec : D_FIELD fflags utf8ref utf8ref field_constval fieldattribute_list'''
    p[0] = p[2:7]

addRule(nothing, 'field_constval', 'empty')
addRule(assign2, 'field_constval', 'EQUALS ref', 
                                    'EQUALS ldc1_notref', 
                                    'EQUALS ldc2_notref')

#Sadly, we must only allow .end field when at least one attribute is specified
#in order to avoid grammatical ambiguity. JasminXT does not share this problem
#because it lacks the .end class syntax which causes the conflict
def p_field_attrlist1(p):
    '''field_al_nonempty : fieldattribute sep field_al_nonempty'''
    p[0] = [p[1]]+ p[3]
def p_field_attrlist2(p):
    '''field_al_nonempty : fieldattribute sep D_END FIELD sep'''
    p[0] = [p[1]]

addRule(assign2, 'fieldattribute_list', 'sep field_al_nonempty', 'sep empty')


def p_method_spec(p):
    '''method_spec : defmethod statements endmethod'''
    p[0] = p[1],p[2]

def p_defmethod_0(p):
    '''defmethod : D_METHOD mflags jas_meth_namedesc sep'''
    p[0] = p[2],p[3] 
def p_defmethod_1(p):
    '''defmethod : D_METHOD mflags utf8ref COLON utf8ref sep'''
    p[0] = p[2],(p[3], p[5]) 

def p_jas_meth_namedesc(p):
    '''jas_meth_namedesc : WORD'''
    name, paren, desc = p[1].rpartition('(')
    name = PoolRef('Utf8', name)
    desc = PoolRef('Utf8', paren+desc)
    p[0] = name, desc
addRule(nothing, 'endmethod', 'D_END METHOD sep')

def p_statement_0(p):
    '''statement : method_directive sep'''
    p[0] = False, p[1]
def p_statement_1(p):
    '''statement : code_directive sep'''
    p[0] = True, (False, p[1])
def p_statement_2(p):
    '''statement : empty instruction sep 
                | lbldec instruction sep
                | lbldec sep'''
    p[0] = True, (True, ((p[1] or None), p[2]))
listRule('statement')

addRule(assign1, 'lbldec', 'lbl COLON')
addRule(assign1, 'method_directive', 'methodattribute')
addRule(assign1, 'code_directive', 'limit_dir', 'except_dir','localvar_dir','linenumber_dir','stack_dir', 'generic_codeattribute_dir')

def p_limit_dir(p):
    '''limit_dir : D_LIMIT LOCALS intl 
                | D_LIMIT STACK intl'''
    p[0] = p[1], (p[2], p[3])

def p_except_dir(p):
    '''except_dir : D_CATCH classref FROM lbl TO lbl USING lbl'''
    p[0] = p[1], (p[2], p[4], p[6], p[8])

def p_linenumber_dir(p):
    '''linenumber_dir : D_LINE intl'''
    p[0] = p[1], p[2]

def p_localvar_dir(p):
    '''localvar_dir : D_VAR intl IS utf8ref utf8ref FROM lbl TO lbl'''
    p[0] = p[1], (p[2], p[4], p[5], p[7], p[9])

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
listRule('luentry')

addRule(assign1, 'tblentry', 'lbl sep')
listRule('tblentry')

def p_lookupswitch(p):
    '''luswitch : empty sep luentrys defaultentry'''
    p[0] = p[1], p[3], p[4]

def p_tableswitch(p):
    '''tblswitch : intl sep tblentrys defaultentry'''
    p[0] = p[1], p[3], p[4]

def p_wide_instr(p):
    '''wide_instr : OP_INT intl
                | OP_INT_INT intl intl'''
    p[0] = p[1], tuple(p[2:])

#######################################################################
# Explicit Attributes
addRule(assign1, 'cfmattribute', 'annotation_dir', 'signature_dir', 'generic_attribute_dir')
addRule(assign1, 'classattribute', 'cfmattribute', 'sourcefile_dir', 'inner_dir', 'enclosing_dir')
addRule(assign1, 'fieldattribute', 'cfmattribute')
addRule(assign1, 'methodattribute', 'cfmattribute', 'throws_dir', 'annotation_param_dir', 'annotation_def_dir')

#Class, field, method
def p_annotation_dir(p):
    '''annotation_dir : D_RUNTIMEVISIBLE annotation
                    | D_RUNTIMEINVISIBLE annotation'''
    p[0] = p[1], (None, p[2])

def p_signature_dir(p):
    '''signature_dir : D_SIGNATURE utf8ref'''
    p[0] = p[1], p[2]

#Class only
def p_sourcefile_dir(p):
    '''sourcefile_dir : D_SOURCE utf8ref'''
    p[0] = p[1], p[2]

def p_inner_dir(p): 
    '''inner_dir : D_INNER cflags utf8ref classref classref'''
    p[0] = p[1], (p[4],p[5],p[3],p[2]) #use JasminXT's (flags, name, inner, outer) order but switch internally to correct order

def p_enclosing_dir(p): 
    '''enclosing_dir : D_ENCLOSING METHOD classref nameandtyperef'''
    p[0] = p[1], (p[3], p[4])

#This is included here even though strictly speaking, it's not an attribute. Rather it's a directive that affects the assembly
#of the InnerClasses attribute
def p_innerlength_dir(p): 
    '''innerlength_dir : D_INNERLENGTH intl'''
    p[0] = p[1], p[2]


#Method only
def p_throws_dir(p):
    '''throws_dir : D_THROWS classref'''
    p[0] = p[1], p[2]

def p_annotation_param_dir(p):
    '''annotation_param_dir : D_RUNTIMEVISIBLE PARAMETER intl annotation
                           | D_RUNTIMEINVISIBLE PARAMETER intl annotation'''
    p[0] = p[1], (p[3], p[4])
def p_annotation_def_dir(p):
    '''annotation_def_dir : D_ANNOTATIONDEFAULT element_value'''
    p[0] = p[1], p[2]

#Generic
def p_generic_attribute_dir(p): 
    '''generic_attribute_dir : D_ATTRIBUTE utf8ref STRING_LITERAL'''
    p[0] = p[1], (p[2], p[3])

def p_generic_codeattribute_dir(p): 
    '''generic_codeattribute_dir : D_CODEATTRIBUTE utf8ref STRING_LITERAL'''
    p[0] = p[1], (p[2], p[3])

#######################################################################
#Stack map stuff
addRule(nothing, 'endstack', 'D_END STACK') #directives are not expected to end with a sep

def assign1All(p):p[0] = tuple(p[1:])
addRule(assign1All, 'verification_type', 'TOP', 'INTEGER', 'FLOAT', 'DOUBLE', 'LONG', 'NULL', 'UNINITIALIZEDTHIS',
                                        'OBJECT classref', 'UNINITIALIZED lbl')
listRule('verification_type')
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
    p[0] = '.stackmap', tuple(p[1:])
addRule(assign2, 'stack_dir', 'D_STACK stack_dir_rest')
#######################################################################
#Annotation stuff
from .codes import et_tags
primtags = set(wordget.get(x, 'WORD') for x in 'byte char double int float long short boolean string'.split())
addRule(assign1, 'primtag', *primtags)
addRule(assign1, 'ldc_any', 'ldc1_notref', 'ldc2_notref', 'ref')

def p_element_value_0(p):
    '''element_value : primtag ldc_any
                    | CLASS utf8ref
                    | ENUM utf8ref utf8ref
                    | ARRAY sep element_array'''
    p[0] = et_tags[p[1]], tuple(p[2:])
def p_element_value_1(p):
    '''element_value : annotation'''
    p[0] = '@', (p[1],)

addRule(assign1, 'element_value_line', 'element_value sep')
listRule('element_value_line')
addRule(assign1, 'element_array', 'element_value_lines D_END ARRAY')

def p_key_ev_line(p):
    '''key_ev_line : utf8ref EQUALS element_value_line'''
    p[0] = p[1], p[3]
listRule('key_ev_line')

def p_annotation(p):
    '''annotation : ANNOTATION utf8ref sep key_ev_lines D_END ANNOTATION'''
    p[0] = p[2], p[4]
#######################################################################

def p_error(p):
    if p is None:
        print "Syntax error: unexpected EOF"
    else: #remember to subtract 1 from line number since we had a newline at the start of the file
        print "Syntax error at line {}: unexpected token {!r}".format(p.lineno-1, p.value)
    
    #Ugly hack since Ply doesn't provide any useful error information
    import inspect
    frame = inspect.currentframe()
    cvars = frame.f_back.f_locals
    print 'Expected:', ', '.join(cvars['actions'][cvars['state']].keys())
    print 'Found:', cvars['ltype']
    print 'Current stack:', cvars['symstack']

    #Discard the rest of the input so that Ply doesn't attempt error recovery
    from ply import yacc
    tok = yacc.token()
    while tok is not None:
        tok = yacc.token()

def makeParser(**kwargs):
    from ply import yacc
    return yacc.yacc(**kwargs)