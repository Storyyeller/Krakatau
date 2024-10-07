## Krakatau assembly syntax

This is a low level specification of the Krakatau assembler syntax. [For a high level introduction to the Krakatau assembler, click here](assembly_tutorial.md).

## Tokens

`NL` represents one or more newlines, with optional comments or other whitespace. Comments begin with `;` and continue until the end of the line. Places where `NL` appears in the grammar *must* have a newline. All other tokens are implicitly separated by non-NL whitespace (you can't break lines except where permitted by the grammar).

```
WORD:
    (?:[a-zA-Z_$\(<]|\[[A-Z\[])[\w$;/\[\(\)<>*+-]*

REF:
    \[[a-z0-9_]+\]

BSREF:
    \[bs:[a-z0-9_]+\]

LABEL_DEF:
    L\w+:

STRING_LITERAL:
    b?"[^"\n\\]*(?:\\.[^"\n\\]*)*"
    b?'[^'\n\\]*(?:\\.[^'\n\\]*)*'

INT_LITERAL:
    [+-]?(?:0x[0-9a-fA-F]+|[1-9][0-9]*|0)

DOUBLE_LITERAL:
    [+-]Infinity
    [+-]NaN(?:<0x[0-9a-fA-F]+>)?
    [+-]?\d+\.\d+(?:e[+-]?\d+)?       // decimal float
    [+-]?\d+(?:e[+-]?\d+)             // decimal float without fraction (exponent mandatory)
    [+-]?0x[0-9a-fA-F]+(?:\.[0-9a-fA-F]+)?(?:p[+-]?\d+)       // hex float

```

A `WORD` consists of one or more ascii letters, digits, `_`, `$`, `;`, `/`, `[`, `(`, `)`, `<`, `>`, `*`, `+`, or `-`, except that it must start with a letter, `_`, `$`, `[`, `<`, or `(`, and if it starts with `[`, the second character must be `A-Z` (upper case) or `[`. (A token with `[` followed by a digit or lowercase letter is instead parsed as the `BSREF` or `REF` token type).

`LONG_LITERAL` has the same format as `INT_LITERAL` followed by an uppcercase `L`. `FLOAT_LITERAL` has the same format as `DOUBLE_LITERAL` followed by a lowercase `f`.

NaNs with a specific binary representation can be represented by suffixing with the hexadecimal value in angle brackets. For example, `-NaN<0x7ff0123456789abc>` or `+NaN<0xFFABCDEF>f`. This must have exactly 8 or 16 hex digits for float and double literals respectively.

As an example of hexidecimal float literals, the minimum positive float is `0x0.000001p-125F` and the maximum negative double is `-0x0.0000000000001p-1022`. Likewise, the maximum denormal is `0x0.fffffffffffffp-1022`.

String literals may be double or single quoted, and may be proceeded by `b` to indicate a raw byte string. Additionally, the permitted escape sequences are as follows: `\\`, `\n`, `\r`, `\t`, `\"`, `\'`, `\uDDDD`, `\U00DDDDDD`, `\xDD`. `\u` and `\U` are 16 and 32 bit unicode escapes respectively, and must be followed by the appropriate hex digits. `\U` escapes must be a legal unicode code point. `\x` is a byte escape and can be used to represent non-ascii byte values in raw byte strings.



## Grammar

The productions `u8`, `u16`, etc. rerepresent `INTEGER_LITERAL`s with value constrained to be an 8, 16, etc. bit unsigned integer. Likewise, `i8`, `i16`, etc. represent signed integer literals.

The `flags` production represents zero or more of the tokens `"abstract"`, `"annotation"`, `"bridge"`, `"enum"`, `"final"`, `"interface"`, `"mandated"`, `"module"`, `"native"`, `"open"`, `"private"`, `"protected"`, `"public"`, `"static"`, `"static_phase"`, `"strict"`, `"strictfp"`, `"super"`, `"synchronized"`, `"synthetic"`, `"transient"`, `"transitive"`, `"varargs"`, `"volatile"`. Additionally, if the token following `flags` is a `WORD`, it must not be one of these values (in other words, `flags` is greedy).

The `lbl` production represents a `WORD` that begins with an uppercase `L`.


The top most production is `source_file`. A Krakatau assembly file can contain any number of class definitions.

```
source_file:
    NL? class_def*

class_def:
    (".version" u16 u16 NL)? 
    ".class" flags clsref NL
    ".super" clsref NL
    interface*
    clsitem*
    ".end" "class" NL

interface:
    ".implements" clsref NL

clsitem:
    ".bootstrap" BSREF "=" ref_or_tagged_bootstrap NL
    ".const" REF "=" ref_or_tagged_const NL
    field NL
    method NL
    attribute NL 

field:
    ".field" flags utfref utfref ("=" ldc_rhs)? fieldattrs?

fieldattrs:
    ".fieldattributes" NL 
    (attribute NL)* 
    ".end" "fieldattributes"

method:
    ".method" flags utfref ":" utfref NL 
    (attribute NL)* 
    ".end" "method"

attribute:
    ".attribute" utfref ("length" u32)? STRING_LITERAL
    ".attribute" utfref ("length" u32)? attrbody
    attrbody
```

Attributes:
```
attrbody:
    ".annotationdefault" element_value
    ".bootstrapmethods"
    ".code" code_attr
    ".constantvalue" ldc_rhs
    ".deprecated"
    ".enclosing" "method" clsref natref
    ".exceptions" clsref*
    ".innerclasses" NL (clsref clsref utfref flags NL)* ".end" "innerclasses"
    ".linenumbertable" NL (lbl u16 NL)* ".end" "linenumbertable"
    ".localvariabletable" NL (local_var_table_item NL)* ".end" "localvariabletable"
    ".localvariabletypetable" NL (local_var_table_item NL)* ".end" "localvariabletypetable"
    ".methodparameters" NL (utfref flags NL)* ".end" "methodparameters"
    ".module" module
    ".modulemainclass" clsref
    ".modulepackages" single*
    ".nesthost" clsref
    ".nestmembers" clsref*
    ".permittedsubclasses" clsref*
    ".record" NL (recorD_item NL)* ".end" "record"
    ".runtime" runtime_visibility runtime_attr
    ".signature" utfref
    ".sourcedebugextension" STRING_LITERAL
    ".sourcefile" utfref
    ".stackmaptable"
    ".synthetic"

annotation:
    annotation_sub "annotation"

annotation_sub:
    utfref NL (utfref "=" element_value NL)* ".end"

element_value:
    "annotation" annotation
    "array" NL (element_value NL)* ".end" "array"
    "boolean" ldc_rhs
    "byte" ldc_rhs
    "char" ldc_rhs
    "class" utfref
    "double" ldc_rhs
    "enum" utfref utfref
    "float" ldc_rhs
    "int" ldc_rhs
    "long" ldc_rhs
    "short" ldc_rhs
    "string" utfref
    
local_var_table_item:
    u16 "is" utfref utfref "from" lbl "to" lbl

module:
    utfref flags "version" utfref NL
    (".requires" single flags "version" utfref NL)*
    (".exports" exports_item NL)*
    (".opens" exports_item NL)*
    (".uses" clsref NL)*
    (".provides" clsref "with" (clsref NL)* NL)*
    ".end" "module"

exports_item:
    single flags ("to" (single NL)*)?

record_item:
    utfref utfref record_attrs? NL

record_attrs:
    ".attributes" (attribute NL)* ".end" "attributes"

runtime_visibility:
    "visible"
    "invisible"

runtime_attr:
    "annotations" NL (annotation NL)* ".end" "annotations"
    "paramannotations" NL (param_annotation NL)* ".end" "paramannotations"
    "typeannotations" NL (type_annotation NL)* ".end" "typeannotations"

param_annotation:
    ".paramannotation" NL
    (annotation NL)*
    ".end" "paramannotation"

type_annotation:
    ".typeannotation" ta_target_info ta_target_path annotation_sub "typeannotation"

ta_target_info:
    u8 ta_target_info_body NL

ta_target_info_body:
    "typeparam" u8
    "super" u16
    "typeparambound" u8 u8
    "empty"
    "methodparam" u8
    "throws" u16
    "localvar" NL (localvar_info NL)* ".end" "localvar"
    "catch" u16
    "offset" lbl
    "typearg" lbl u8

localvar_info:
    "nowhere"
    "from" lbl "to" lbl

ta_target_path:
    ".typepath" NL (u8 u8 NL)* ".end" "typepath" NL

```

Code:
```
code_attr:
    "long"? "stack" u16 "locals" u16 NL
    (code_item NL)*
    (attribute NL)*
    ".end" "code"

code_item:
    LABEL_DEF instruction?
    instruction
    code_directive

code_directive:
    ".catch" clsref "from" lbl "to" lbl "using" lbl
    ".stack" stack_map_item

stack_map_item:
    "same"
    "stack_1" vtype
    "stack_1_extended" vtype
    "chop" u8
    "same_extended"
    "append" vtype+
    "full" NL "locals" vtype* NL "stack" vtype* NL ".end" "stack"

vtype:
    "Float"
    "Integer"
    "Long"
    "Null"
    "Object" clsref
    "Top"
    "Uninitialized" lbl
    "UninitializedThis"
```

Bytecode instructions:
```
instruction:
    "aaload"
    "aastore"
    "aconst_null"
    "aload" u8
    "aload_0"
    "aload_1"
    "aload_2"
    "aload_3"
    "anewarray" clsref
    "areturn"
    "arraylength"
    "astore"  u8
    "astore_0"
    "astore_1"
    "astore_2"
    "astore_3"
    "athrow"
    "baload"
    "bastore"
    "bipush" i8
    "caload"
    "castore"
    "checkcast" clsref
    "d2f"
    "d2i"
    "d2l"
    "dadd"
    "daload"
    "dastore"
    "dcmpg"
    "dcmpl"
    "dconst_0"
    "dconst_1"
    "ddiv"
    "dload" u8
    "dload_0"
    "dload_1"
    "dload_2"
    "dload_3"
    "dmul"
    "dneg"
    "drem"
    "dreturn"
    "dstore" u8
    "dstore_0"
    "dstore_1"
    "dstore_2"
    "dstore_3"
    "dsub"
    "dup"
    "dup2"
    "dup2_x1"
    "dup2_x2"
    "dup_x1"
    "dup_x2"
    "f2d"
    "f2i"
    "f2l"
    "fadd"
    "faload"
    "fastore"
    "fcmpg"
    "fcmpl"
    "fconst_0"
    "fconst_1"
    "fconst_2"
    "fdiv"
    "fload" u8
    "fload_0"
    "fload_1"
    "fload_2"
    "fload_3"
    "fmul"
    "fneg"
    "frem"
    "freturn"
    "fstore" u8
    "fstore_0"
    "fstore_1"
    "fstore_2"
    "fstore_3"
    "fsub"
    "getfield" ref_or_tagged_const
    "getstatic" ref_or_tagged_const
    "goto" lbl
    "goto_w" lbl
    "i2b"
    "i2c"
    "i2d"
    "i2f"
    "i2l"
    "i2s"
    "iadd"
    "iaload"
    "iand"
    "iastore"
    "iconst_0"
    "iconst_1"
    "iconst_2"
    "iconst_3"
    "iconst_4"
    "iconst_5"
    "iconst_m1"
    "idiv"
    "if_acmpeq" lbl
    "if_acmpne" lbl
    "if_icmpeq" lbl
    "if_icmpge" lbl
    "if_icmpgt" lbl
    "if_icmple" lbl
    "if_icmplt" lbl
    "if_icmpne" lbl
    "ifeq" lbl
    "ifge" lbl
    "ifgt" lbl
    "ifle" lbl
    "iflt" lbl
    "ifne" lbl
    "ifnonnull" lbl
    "ifnull" lbl
    "iinc" u8 i8
    "iload" u8
    "iload_0"
    "iload_1"
    "iload_2"
    "iload_3"
    "imul"
    "ineg"
    "instanceof" clsref
    "invokedynamic" ref_or_tagged_const
    "invokeinterface" ref_or_tagged_const u8?
    "invokespecial" ref_or_tagged_const
    "invokestatic" ref_or_tagged_const
    "invokevirtual" ref_or_tagged_const
    "ior"
    "irem"
    "ireturn"
    "ishl"
    "ishr"
    "istore" u8
    "istore_0"
    "istore_1"
    "istore_2"
    "istore_3"
    "isub"
    "iushr"
    "ixor"
    "jsr" lbl 
    "jsr_w" lbl
    "l2d"
    "l2f"
    "l2i"
    "ladd"
    "laload"
    "land"
    "lastore"
    "lcmp"
    "lconst_0"
    "lconst_1"
    "ldc" ldc_rhs
    "ldc2_w" ldc_rhs
    "ldc_w" ldc_rhs
    "ldiv"
    "lload" u8
    "lload_0"
    "lload_1"
    "lload_2"
    "lload_3"
    "lmul"
    "lneg"
    "lookupswitch" lookupswitch
    "lor"
    "lrem"
    "lreturn"
    "lshl"
    "lshr"
    "lstore" u8
    "lstore_0"
    "lstore_1"
    "lstore_2"
    "lstore_3"
    "lsub"
    "lushr"
    "lxor"
    "monitorenter"
    "monitorexit"
    "multianewarray" clsref u8
    "new" clsref
    "newarray" ("boolean" | "char" | "float" | "double" | "byte" | "short" | "int" | "long")
    "nop"
    "pop"
    "pop2"
    "putfield" ref_or_tagged_const
    "putstatic" ref_or_tagged_const
    "ret" u8
    "return"
    "saload"
    "sastore"
    "sipush" i16
    "swap"
    "tableswitch" tableswitch
    "wide" wide_instruction

lookupswitch:
    NL 
    (i32 ":" lbl NL)*
    "default" ":" lbl

tableswitch:
    i32 NL
    (lbl NL)+
    "default" ":" lbl

wide_instruction:
    "aload" u16
    "astore" u16
    "dload" u16
    "dstore" u16
    "fload" u16
    "fstore" u16
    "iinc" u16 i16
    "iload" u16
    "istore" u16
    "lload" u16
    "lstore" u16
    "ret" u16    
```


Constants:
```
utf:
    WORD
    STRING_LITERAL

utfref:
    REF
    utf

clsref:
    REF
    utf 

single:
    REF 
    utf

natref:
    REF
    utf utfref

mhnotref:
    mhtag ref_or_tagged_const

mhtag:
    "getField"
    "getStatic"
    "putField"
    "putStatic"
    "invokeVirtual"
    "invokeStatic"
    "invokeSpecial"
    "newInvokeSpecial"
    "invokeInterface"

tagged_const:
    "Utf8" utf
    "Int" i32
    "Float" FLOAT_LITERAL
    "Long" LONG_LITERAL
    "Double" DOUBLE_LITERAL
    "Class" utfref
    "String" utfref
    "MethodType" utfref
    "Module" utfref
    "Package" utfref
    "Field" clsref natref
    "Method" clsref natref
    "InterfaceMethod" clsref natref
    "NameAndType" utfref utfref
    "MethodHandle" mhnotref
    "Dynamic" bsref natref
    "InvokeDynamic" bsref natref

ref_or_tagged_const:
    REF
    tagged_const

bs_args:
    ref_or_tagged_const* ":"

bsref:
    BSREF
    mhnotref bs_args

ref_or_tagged_bootstrap:
    BSREF
    "Bootstrap" REF bs_args
    "Bootstrap" mhnotref bs_args

ldc_rhs:
    INTEGER_LITERAL
    FLOAT_LITERAL
    LONG_LITERAL
    DOUBLE_LITERAL
    STRING_LITERAL
    REF
    tagged_const

```
