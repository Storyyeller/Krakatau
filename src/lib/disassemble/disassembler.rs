use super::flags::Flags;
use super::refprinter::RefPrinter;
use super::refprinter::SingleTag;
use super::string::escape_byte_string;
use crate::lib::classfile::attrs;
use crate::lib::classfile::attrs::AttrBody;
use crate::lib::classfile::attrs::Attribute;
use crate::lib::classfile::code;
use crate::lib::classfile::code::SwitchArena;
use crate::lib::classfile::parse::Class;
use crate::lib::classfile::parse::Field;

use std::io::Result;
use std::io::Write;

static INDENT_BUF: &str = "                                        ";
const ERROR: &str = "Internal error: Please report this!";

static SHORT_CODE_WARNING: [&str; 6] = [
    "Warning! This classfile has been specially crafted so that it will parse",
    "differently (and thus be interpreted as having different bytecode) in JVMs",
    "for Java versions <= 13 and 14+. By default, Krakatau will show the code as",
    "interpreted in Java <= 13. If you are sure that this class actually targets",
    "Java 14+, pass the --no-short-code-attr option to see the alternate version",
    "of the code instead.",
];

#[derive(Debug, Clone, Copy)]
pub struct DisassemblerOptions {
    pub roundtrip: bool,
}

struct Disassembler<'a, W: Write> {
    w: W,
    rp: &'a RefPrinter<'a>,
    roundtrip: bool,
    cf_version: (u16, u16),
    indentlevel: usize,
    sol: &'static str,
}
impl<'a, W: Write> Disassembler<'a, W> {
    fn new(w: W, rp: &'a RefPrinter<'a>, roundtrip: bool, cf_version: (u16, u16)) -> Self {
        Self {
            w,
            rp,
            roundtrip,
            cf_version,
            indentlevel: 0,
            sol: "",
        }
    }

    fn enter_block(&mut self) {
        self.indentlevel += 1;
        self.sol = &INDENT_BUF[0..std::cmp::min(self.indentlevel * 4, INDENT_BUF.len())];
    }

    fn exit_block(&mut self) {
        if self.indentlevel == 0 {
            panic!("Internal error: Please report this!");
        }
        self.indentlevel -= 1;
        self.sol = &INDENT_BUF[0..std::cmp::min(self.indentlevel * 4, INDENT_BUF.len())];
    }

    fn field(&mut self, f: &Field<'a>) -> Result<()> {
        let rp = self.rp;

        let mut constant_value = None;
        let mut skip = std::ptr::null();
        if !self.roundtrip {
            for attr in &f.attrs {
                use AttrBody::*;
                match &attr.body {
                    ConstantValue(v) => {
                        constant_value = Some(*v);
                        skip = attr; // store pointer so we can skip it later
                    }
                    _ => {}
                }
            }
        }

        write!(self.w, ".field{} {} {}", Flags::field(f.access), rp.utf(f.name), rp.utf(f.desc))?;
        if let Some(cv) = constant_value {
            write!(self.w, " = {}", rp.ldc(cv))?;
        } else {
            write!(self.w, "")?;
        }

        let used_count = if constant_value.is_some() { 1 } else { 0 };
        if f.attrs.len() > used_count {
            writeln!(self.w, " .fieldattributes")?;
            self.enter_block();

            for a in &f.attrs {
                if std::ptr::eq(a, skip) {
                    continue;
                }
                self.attr(a)?;
            }

            self.exit_block();
            writeln!(self.w, ".end fieldattributes")?;
        } else {
            writeln!(self.w, "")?;
        }
        Ok(())
    }

    fn method(&mut self, m: &Field<'a>) -> Result<()> {
        let rp = self.rp;
        writeln!(self.w, "\n.method{} {} : {}", Flags::method(m.access), rp.utf(m.name), rp.utf(m.desc))?;
        self.enter_block();

        for a in &m.attrs {
            self.attr(a)?;
        }

        self.exit_block();
        writeln!(self.w, ".end method")?;
        Ok(())
    }

    fn attr(&mut self, a: &Attribute<'a>) -> Result<()> {
        let rp = self.rp;

        write!(self.w, "{}", self.sol)?;
        if a.length != a.actual_length {
            write!(self.w, ".attribute {} length {} ", rp.utf(a.name), a.length)?;
        } else if self.roundtrip || a.body.is_raw() {
            write!(self.w, ".attribute {} ", rp.utf(a.name))?;
        }

        use AttrBody::*;
        match &a.body {
            AnnotationDefault(ev) => {
                write!(self.w, ".annotationdefault ")?;
                self.element_value(ev)?;
            }
            BootstrapMethods(..) => write!(self.w, ".bootstrapmethods")?,
            Code((code, _code2)) => self.code(code)?,
            ConstantValue(r) => write!(self.w, ".constantvalue {}", rp.ldc(*r))?,
            Deprecated => write!(self.w, ".deprecated")?,
            EnclosingMethod(r, r2) => write!(self.w, ".enclosing method {} {}", rp.cls(*r), rp.nat(*r2))?,
            Exceptions(vals) => {
                write!(self.w, ".exceptions")?;
                for ex in vals.iter().copied() {
                    write!(self.w, " {}", rp.cls(ex))?;
                }
            }
            InnerClasses(lines) => {
                writeln!(self.w, ".innerclasses")?;
                self.enter_block();
                for val in lines.iter().copied() {
                    writeln!(
                        self.w,
                        "{}{} {} {}{}",
                        self.sol,
                        rp.cls(val.0),
                        rp.cls(val.1),
                        rp.utf(val.2),
                        Flags::class(val.3)
                    )?;
                }
                self.exit_block();
                write!(self.w, "{}.end innerclasses", self.sol)?;
            }
            LineNumberTable(lines) => {
                writeln!(self.w, ".linenumbertable")?;
                self.enter_block();
                for val in lines.iter().copied() {
                    writeln!(self.w, "{}{} {}", self.sol, val.0, val.1)?;
                }
                self.exit_block();
                write!(self.w, "{}.end linenumbertable", self.sol)?;
            }
            LocalVariableTable(lines) => {
                writeln!(self.w, ".localvariabletable")?;
                self.local_var_table(lines)?;
                write!(self.w, "{}.end localvariabletable", self.sol)?;
            }
            LocalVariableTypeTable(lines) => {
                writeln!(self.w, ".localvariabletypetable")?;
                self.local_var_table(lines)?;
                write!(self.w, "{}.end localvariabletypetable", self.sol)?;
            }
            MethodParameters(lines) => {
                writeln!(self.w, ".methodparameters")?;
                self.enter_block();
                for val in lines.iter().copied() {
                    writeln!(self.w, "{}{}{}", self.sol, rp.utf(val.0), Flags::mod_other(val.1))?;
                }
                self.exit_block();
                write!(self.w, "{}.end methodparameters", self.sol)?;
            }
            Module(modattr) => {
                self.module_attr(&modattr)?;
            }
            ModuleMainClass(r) => write!(self.w, ".modulemainclass {}", rp.cls(*r))?,
            ModulePackages(vals) => {
                write!(self.w, ".modulepackages")?;
                for ex in vals.iter().copied() {
                    write!(self.w, " {}", rp.single(ex, SingleTag::Package))?;
                }
            }
            NestHost(r) => write!(self.w, ".nesthost {}", rp.cls(*r))?,
            NestMembers(vals) => {
                write!(self.w, ".nestmembers")?;
                for ex in vals.iter().copied() {
                    write!(self.w, " {}", rp.cls(ex))?;
                }
            }
            PermittedSubclasses(vals) => {
                write!(self.w, ".permittedsubclasses")?;
                for ex in vals.iter().copied() {
                    write!(self.w, " {}", rp.cls(ex))?;
                }
            }
            Record(lines) => {
                writeln!(self.w, ".record")?;
                self.enter_block();
                for val in lines {
                    self.record_component(val)?;
                }
                self.exit_block();
                write!(self.w, "{}.end record", self.sol)?;
            }

            RuntimeInvisibleAnnotations(lines) => self.runtime_annotations("invisible", lines)?,
            RuntimeInvisibleParameterAnnotations(lines) => self.runtime_param_annotations("invisible", lines)?,
            RuntimeInvisibleTypeAnnotations(lines) => self.runtime_type_annotations("invisible", lines)?,
            RuntimeVisibleAnnotations(lines) => self.runtime_annotations("visible", lines)?,
            RuntimeVisibleParameterAnnotations(lines) => self.runtime_param_annotations("visible", lines)?,
            RuntimeVisibleTypeAnnotations(lines) => self.runtime_type_annotations("visible", lines)?,

            Signature(r) => write!(self.w, ".signature {}", rp.utf(*r))?,
            SourceDebugExtension(s) => write!(self.w, ".sourcedebugextension b'{}'", escape_byte_string(s))?,
            SourceFile(r) => write!(self.w, ".sourcefile {}", rp.utf(*r))?,
            StackMapTable(_) => write!(self.w, ".stackmaptable")?,
            Synthetic => write!(self.w, ".synthetic")?,

            Raw(s) => write!(self.w, "b'{}'", escape_byte_string(s))?,
        };

        writeln!(self.w, "")?;
        Ok(())
    }

    fn local_var_table(&mut self, lines: &[attrs::LocalVarLine]) -> Result<()> {
        let rp = self.rp;
        self.enter_block();
        for lvl in lines.iter().copied() {
            writeln!(
                self.w,
                "{}{} is {} {} from {} to {}",
                self.sol,
                lvl.ind,
                rp.utf(lvl.name),
                rp.utf(lvl.desc),
                lvl.start,
                lvl.end,
            )?;
        }
        self.exit_block();
        Ok(())
    }

    fn vtype(&mut self, vt: code::VType) -> Result<()> {
        let rp = self.rp;
        use code::VType::*;
        match vt {
            Top => write!(self.w, " Top"),
            Int => write!(self.w, " Integer"),
            Float => write!(self.w, " Float"),
            Long => write!(self.w, " Long"),
            Double => write!(self.w, " Double"),
            Null => write!(self.w, " Null"),
            UninitThis => write!(self.w, " UninitializedThis"),
            Object(r) => write!(self.w, " Object {}", rp.cls(r)),
            UninitObj(r) => write!(self.w, " Uninitialized {}", r),
        }
    }

    fn begin_bytecode_line<'i>(
        &mut self,
        pos: code::Pos,
        excepts: &mut std::iter::Peekable<impl Iterator<Item = code::Except>>,
        frames: &mut std::iter::Peekable<impl Iterator<Item = &'i (code::Pos, code::Frame)>>,
    ) -> Result<()> {
        let rp = self.rp;
        while excepts.peek().map(|e| e.start <= pos).unwrap_or(false) {
            let e = excepts.next().expect(ERROR);
            writeln!(
                self.w,
                "{}.catch {} from {} to {} using {}",
                self.sol,
                rp.cls(e.ctype),
                e.start,
                e.end,
                e.handler,
            )?;
        }

        if frames.peek().map(|e| e.0 <= pos).unwrap_or(false) {
            let f = frames.next().expect(ERROR);
            // Add blank line before stackmap frames for readability, except at start of code
            if !f.0.is_start() {
                writeln!(self.w, "")?;
            }
            write!(self.w, "{}.stack ", self.sol)?;
            use code::Frame::*;
            match &f.1 {
                Same => writeln!(self.w, "same")?,
                Stack1(vt) => {
                    write!(self.w, "stack_1")?;
                    self.vtype(*vt)?;
                    writeln!(self.w, "")?
                }
                Stack1Ex(vt) => {
                    write!(self.w, "stack_1_extended")?;
                    self.vtype(*vt)?;
                    writeln!(self.w, "")?
                }
                Chop(cnt) => writeln!(self.w, "chop {}", *cnt)?,
                SameEx => writeln!(self.w, "same_extended")?,
                Append(vts) => {
                    write!(self.w, "append")?;
                    for vt in vts.iter().copied() {
                        self.vtype(vt)?;
                    }
                    writeln!(self.w, "")?;
                }
                Full(locals, stack) => {
                    writeln!(self.w, "full")?;

                    self.enter_block();
                    write!(self.w, "{}locals", self.sol)?;
                    for vt in locals.iter().copied() {
                        self.vtype(vt)?;
                    }
                    writeln!(self.w, "")?;
                    write!(self.w, "{}stack", self.sol)?;
                    for vt in stack.iter().copied() {
                        self.vtype(vt)?;
                    }
                    writeln!(self.w, "")?;
                    self.exit_block();

                    writeln!(self.w, "{}.end stack", self.sol)?;
                }
            }
        }

        let lhs = format!("{}:", pos);
        let indent = self.sol.len();
        write!(self.w, "{:indent$}", lhs)
    }

    fn instr(&mut self, ins: &code::Instr, switches: &SwitchArena) -> Result<()> {
        let rp = self.rp;
        use code::Instr::*;
        match ins {
            Nop => writeln!(self.w, "nop")?,
            AconstNull => writeln!(self.w, "aconst_null")?,
            IconstM1 => writeln!(self.w, "iconst_m1")?,
            Iconst0 => writeln!(self.w, "iconst_0")?,
            Iconst1 => writeln!(self.w, "iconst_1")?,
            Iconst2 => writeln!(self.w, "iconst_2")?,
            Iconst3 => writeln!(self.w, "iconst_3")?,
            Iconst4 => writeln!(self.w, "iconst_4")?,
            Iconst5 => writeln!(self.w, "iconst_5")?,
            Lconst0 => writeln!(self.w, "lconst_0")?,
            Lconst1 => writeln!(self.w, "lconst_1")?,
            Fconst0 => writeln!(self.w, "fconst_0")?,
            Fconst1 => writeln!(self.w, "fconst_1")?,
            Fconst2 => writeln!(self.w, "fconst_2")?,
            Dconst0 => writeln!(self.w, "dconst_0")?,
            Dconst1 => writeln!(self.w, "dconst_1")?,
            Bipush(v0) => writeln!(self.w, "bipush {}", *v0)?,
            Sipush(v0) => writeln!(self.w, "sipush {}", *v0)?,
            Ldc(v0) => writeln!(self.w, "ldc {}", rp.ldc(*v0 as u16))?,
            LdcW(v0) => writeln!(self.w, "ldc_w {}", rp.ldc(*v0))?,
            Ldc2W(v0) => writeln!(self.w, "ldc2_w {}", rp.ldc(*v0))?,
            Iload(v0) => writeln!(self.w, "iload {}", *v0)?,
            Lload(v0) => writeln!(self.w, "lload {}", *v0)?,
            Fload(v0) => writeln!(self.w, "fload {}", *v0)?,
            Dload(v0) => writeln!(self.w, "dload {}", *v0)?,
            Aload(v0) => writeln!(self.w, "aload {}", *v0)?,
            Iload0 => writeln!(self.w, "iload_0")?,
            Iload1 => writeln!(self.w, "iload_1")?,
            Iload2 => writeln!(self.w, "iload_2")?,
            Iload3 => writeln!(self.w, "iload_3")?,
            Lload0 => writeln!(self.w, "lload_0")?,
            Lload1 => writeln!(self.w, "lload_1")?,
            Lload2 => writeln!(self.w, "lload_2")?,
            Lload3 => writeln!(self.w, "lload_3")?,
            Fload0 => writeln!(self.w, "fload_0")?,
            Fload1 => writeln!(self.w, "fload_1")?,
            Fload2 => writeln!(self.w, "fload_2")?,
            Fload3 => writeln!(self.w, "fload_3")?,
            Dload0 => writeln!(self.w, "dload_0")?,
            Dload1 => writeln!(self.w, "dload_1")?,
            Dload2 => writeln!(self.w, "dload_2")?,
            Dload3 => writeln!(self.w, "dload_3")?,
            Aload0 => writeln!(self.w, "aload_0")?,
            Aload1 => writeln!(self.w, "aload_1")?,
            Aload2 => writeln!(self.w, "aload_2")?,
            Aload3 => writeln!(self.w, "aload_3")?,
            Iaload => writeln!(self.w, "iaload")?,
            Laload => writeln!(self.w, "laload")?,
            Faload => writeln!(self.w, "faload")?,
            Daload => writeln!(self.w, "daload")?,
            Aaload => writeln!(self.w, "aaload")?,
            Baload => writeln!(self.w, "baload")?,
            Caload => writeln!(self.w, "caload")?,
            Saload => writeln!(self.w, "saload")?,
            Istore(v0) => writeln!(self.w, "istore {}", *v0)?,
            Lstore(v0) => writeln!(self.w, "lstore {}", *v0)?,
            Fstore(v0) => writeln!(self.w, "fstore {}", *v0)?,
            Dstore(v0) => writeln!(self.w, "dstore {}", *v0)?,
            Astore(v0) => writeln!(self.w, "astore {}", *v0)?,
            Istore0 => writeln!(self.w, "istore_0")?,
            Istore1 => writeln!(self.w, "istore_1")?,
            Istore2 => writeln!(self.w, "istore_2")?,
            Istore3 => writeln!(self.w, "istore_3")?,
            Lstore0 => writeln!(self.w, "lstore_0")?,
            Lstore1 => writeln!(self.w, "lstore_1")?,
            Lstore2 => writeln!(self.w, "lstore_2")?,
            Lstore3 => writeln!(self.w, "lstore_3")?,
            Fstore0 => writeln!(self.w, "fstore_0")?,
            Fstore1 => writeln!(self.w, "fstore_1")?,
            Fstore2 => writeln!(self.w, "fstore_2")?,
            Fstore3 => writeln!(self.w, "fstore_3")?,
            Dstore0 => writeln!(self.w, "dstore_0")?,
            Dstore1 => writeln!(self.w, "dstore_1")?,
            Dstore2 => writeln!(self.w, "dstore_2")?,
            Dstore3 => writeln!(self.w, "dstore_3")?,
            Astore0 => writeln!(self.w, "astore_0")?,
            Astore1 => writeln!(self.w, "astore_1")?,
            Astore2 => writeln!(self.w, "astore_2")?,
            Astore3 => writeln!(self.w, "astore_3")?,
            Iastore => writeln!(self.w, "iastore")?,
            Lastore => writeln!(self.w, "lastore")?,
            Fastore => writeln!(self.w, "fastore")?,
            Dastore => writeln!(self.w, "dastore")?,
            Aastore => writeln!(self.w, "aastore")?,
            Bastore => writeln!(self.w, "bastore")?,
            Castore => writeln!(self.w, "castore")?,
            Sastore => writeln!(self.w, "sastore")?,
            Pop => writeln!(self.w, "pop")?,
            Pop2 => writeln!(self.w, "pop2")?,
            Dup => writeln!(self.w, "dup")?,
            DupX1 => writeln!(self.w, "dup_x1")?,
            DupX2 => writeln!(self.w, "dup_x2")?,
            Dup2 => writeln!(self.w, "dup2")?,
            Dup2X1 => writeln!(self.w, "dup2_x1")?,
            Dup2X2 => writeln!(self.w, "dup2_x2")?,
            Swap => writeln!(self.w, "swap")?,
            Iadd => writeln!(self.w, "iadd")?,
            Ladd => writeln!(self.w, "ladd")?,
            Fadd => writeln!(self.w, "fadd")?,
            Dadd => writeln!(self.w, "dadd")?,
            Isub => writeln!(self.w, "isub")?,
            Lsub => writeln!(self.w, "lsub")?,
            Fsub => writeln!(self.w, "fsub")?,
            Dsub => writeln!(self.w, "dsub")?,
            Imul => writeln!(self.w, "imul")?,
            Lmul => writeln!(self.w, "lmul")?,
            Fmul => writeln!(self.w, "fmul")?,
            Dmul => writeln!(self.w, "dmul")?,
            Idiv => writeln!(self.w, "idiv")?,
            Ldiv => writeln!(self.w, "ldiv")?,
            Fdiv => writeln!(self.w, "fdiv")?,
            Ddiv => writeln!(self.w, "ddiv")?,
            Irem => writeln!(self.w, "irem")?,
            Lrem => writeln!(self.w, "lrem")?,
            Frem => writeln!(self.w, "frem")?,
            Drem => writeln!(self.w, "drem")?,
            Ineg => writeln!(self.w, "ineg")?,
            Lneg => writeln!(self.w, "lneg")?,
            Fneg => writeln!(self.w, "fneg")?,
            Dneg => writeln!(self.w, "dneg")?,
            Ishl => writeln!(self.w, "ishl")?,
            Lshl => writeln!(self.w, "lshl")?,
            Ishr => writeln!(self.w, "ishr")?,
            Lshr => writeln!(self.w, "lshr")?,
            Iushr => writeln!(self.w, "iushr")?,
            Lushr => writeln!(self.w, "lushr")?,
            Iand => writeln!(self.w, "iand")?,
            Land => writeln!(self.w, "land")?,
            Ior => writeln!(self.w, "ior")?,
            Lor => writeln!(self.w, "lor")?,
            Ixor => writeln!(self.w, "ixor")?,
            Lxor => writeln!(self.w, "lxor")?,
            Iinc(v0, v1) => writeln!(self.w, "iinc {} {}", *v0, *v1)?,
            I2l => writeln!(self.w, "i2l")?,
            I2f => writeln!(self.w, "i2f")?,
            I2d => writeln!(self.w, "i2d")?,
            L2i => writeln!(self.w, "l2i")?,
            L2f => writeln!(self.w, "l2f")?,
            L2d => writeln!(self.w, "l2d")?,
            F2i => writeln!(self.w, "f2i")?,
            F2l => writeln!(self.w, "f2l")?,
            F2d => writeln!(self.w, "f2d")?,
            D2i => writeln!(self.w, "d2i")?,
            D2l => writeln!(self.w, "d2l")?,
            D2f => writeln!(self.w, "d2f")?,
            I2b => writeln!(self.w, "i2b")?,
            I2c => writeln!(self.w, "i2c")?,
            I2s => writeln!(self.w, "i2s")?,
            Lcmp => writeln!(self.w, "lcmp")?,
            Fcmpl => writeln!(self.w, "fcmpl")?,
            Fcmpg => writeln!(self.w, "fcmpg")?,
            Dcmpl => writeln!(self.w, "dcmpl")?,
            Dcmpg => writeln!(self.w, "dcmpg")?,
            Ifeq(v0) => writeln!(self.w, "ifeq {}", *v0)?,
            Ifne(v0) => writeln!(self.w, "ifne {}", *v0)?,
            Iflt(v0) => writeln!(self.w, "iflt {}", *v0)?,
            Ifge(v0) => writeln!(self.w, "ifge {}", *v0)?,
            Ifgt(v0) => writeln!(self.w, "ifgt {}", *v0)?,
            Ifle(v0) => writeln!(self.w, "ifle {}", *v0)?,
            IfIcmpeq(v0) => writeln!(self.w, "if_icmpeq {}", *v0)?,
            IfIcmpne(v0) => writeln!(self.w, "if_icmpne {}", *v0)?,
            IfIcmplt(v0) => writeln!(self.w, "if_icmplt {}", *v0)?,
            IfIcmpge(v0) => writeln!(self.w, "if_icmpge {}", *v0)?,
            IfIcmpgt(v0) => writeln!(self.w, "if_icmpgt {}", *v0)?,
            IfIcmple(v0) => writeln!(self.w, "if_icmple {}", *v0)?,
            IfAcmpeq(v0) => writeln!(self.w, "if_acmpeq {}", *v0)?,
            IfAcmpne(v0) => writeln!(self.w, "if_acmpne {}", *v0)?,
            Goto(v0) => writeln!(self.w, "goto {}", *v0)?,
            Jsr(v0) => writeln!(self.w, "jsr {}", *v0)?,
            Ret(v0) => writeln!(self.w, "ret {}", *v0)?,
            Tableswitch(i) => {
                let jumps = switches.table(*i);
                writeln!(self.w, "tableswitch {}", jumps.low)?;
                self.enter_block();
                for target in jumps.table.iter().copied() {
                    writeln!(self.w, "{}{}", self.sol, target)?;
                }
                writeln!(self.w, "{}default : {}", self.sol, jumps.default)?;
                self.exit_block();
            }
            Lookupswitch(i) => {
                let jumps = switches.map(*i);
                writeln!(self.w, "lookupswitch")?;
                self.enter_block();
                for (val, target) in jumps.table.iter().copied() {
                    writeln!(self.w, "{}{} : {}", self.sol, val, target)?;
                }
                writeln!(self.w, "{}default : {}", self.sol, jumps.default)?;
                self.exit_block();
            }
            Ireturn => writeln!(self.w, "ireturn")?,
            Lreturn => writeln!(self.w, "lreturn")?,
            Freturn => writeln!(self.w, "freturn")?,
            Dreturn => writeln!(self.w, "dreturn")?,
            Areturn => writeln!(self.w, "areturn")?,
            Return => writeln!(self.w, "return")?,
            Getstatic(v0) => writeln!(self.w, "getstatic {}", rp.tagged_fmim(*v0))?,
            Putstatic(v0) => writeln!(self.w, "putstatic {}", rp.tagged_fmim(*v0))?,
            Getfield(v0) => writeln!(self.w, "getfield {}", rp.tagged_fmim(*v0))?,
            Putfield(v0) => writeln!(self.w, "putfield {}", rp.tagged_fmim(*v0))?,
            Invokevirtual(v0) => writeln!(self.w, "invokevirtual {}", rp.tagged_fmim(*v0))?,
            Invokespecial(v0) => writeln!(self.w, "invokespecial {}", rp.tagged_fmim(*v0))?,
            Invokestatic(v0) => writeln!(self.w, "invokestatic {}", rp.tagged_fmim(*v0))?,
            Invokeinterface(v0, v1) => writeln!(self.w, "invokeinterface {} {}", rp.tagged_fmim(*v0), *v1)?,
            Invokedynamic(v0) => writeln!(self.w, "invokedynamic {}", rp.cpref(*v0))?,
            New(v0) => writeln!(self.w, "new {}", rp.cls(*v0))?,
            Newarray(c) => writeln!(self.w, "newarray {}", *c)?,
            Anewarray(v0) => writeln!(self.w, "anewarray {}", rp.cls(*v0))?,
            Arraylength => writeln!(self.w, "arraylength")?,
            Athrow => writeln!(self.w, "athrow")?,
            Checkcast(v0) => writeln!(self.w, "checkcast {}", rp.cls(*v0))?,
            Instanceof(v0) => writeln!(self.w, "instanceof {}", rp.cls(*v0))?,
            Monitorenter => writeln!(self.w, "monitorenter")?,
            Monitorexit => writeln!(self.w, "monitorexit")?,
            Wide(w) => {
                use code::WideInstr::*;
                match w {
                    Iload(v0) => writeln!(self.w, "wide iload {}", *v0)?,
                    Lload(v0) => writeln!(self.w, "wide lload {}", *v0)?,
                    Fload(v0) => writeln!(self.w, "wide fload {}", *v0)?,
                    Dload(v0) => writeln!(self.w, "wide dload {}", *v0)?,
                    Aload(v0) => writeln!(self.w, "wide aload {}", *v0)?,
                    Istore(v0) => writeln!(self.w, "wide istore {}", *v0)?,
                    Lstore(v0) => writeln!(self.w, "wide lstore {}", *v0)?,
                    Fstore(v0) => writeln!(self.w, "wide fstore {}", *v0)?,
                    Dstore(v0) => writeln!(self.w, "wide dstore {}", *v0)?,
                    Astore(v0) => writeln!(self.w, "wide astore {}", *v0)?,
                    Iinc(v0, v1) => writeln!(self.w, "wide iinc {} {}", *v0, *v1)?,
                    Ret(v0) => writeln!(self.w, "wide ret {}", *v0)?,
                }
            }
            Multianewarray(v0, v1) => writeln!(self.w, "multianewarray {} {}", rp.cls(*v0), *v1)?,
            Ifnull(v0) => writeln!(self.w, "ifnull {}", *v0)?,
            Ifnonnull(v0) => writeln!(self.w, "ifnonnull {}", *v0)?,
            GotoW(v0) => writeln!(self.w, "goto_w {}", *v0)?,
            JsrW(v0) => writeln!(self.w, "jsr_w {}", *v0)?,
        }
        Ok(())
    }

    fn code(&mut self, c: &code::Code<'a>) -> Result<()> {
        let mut stack_map_table = None;
        let mut skip = std::ptr::null();
        for attr in &c.attrs {
            use AttrBody::*;
            match &attr.body {
                StackMapTable(v) => {
                    stack_map_table = Some(v);
                    if !self.roundtrip {
                        skip = attr; // store pointer so we can skip it later
                    }
                }
                _ => {}
            }
        }
        let stack_map_table = stack_map_table.map(|smt| &smt.0[..]).unwrap_or(&[]);

        if self.cf_version <= (45, 2) && !c.is_short {
            writeln!(self.w, ".code long stack {} locals {}", c.stack, c.locals)?;
        } else {
            writeln!(self.w, ".code stack {} locals {}", c.stack, c.locals)?;
        }
        self.enter_block();

        let mut excepts = c.exceptions.iter().copied().peekable();
        let mut frames = stack_map_table.iter().peekable();

        for &(addr, ref instr) in c.bytecode.0.iter() {
            self.begin_bytecode_line(addr, &mut excepts, &mut frames)?;
            self.instr(instr, &c.bytecode.2)?;
        }

        self.begin_bytecode_line(c.bytecode.1, &mut excepts, &mut frames)?;
        writeln!(self.w, "")?;

        for a in &c.attrs {
            if a as *const _ == skip {
                continue;
            }
            self.attr(a)?;
        }

        self.exit_block();
        write!(self.w, "{}.end code", self.sol)?;
        Ok(())
    }

    fn runtime_annotations(&mut self, kind: &'static str, lines: &[attrs::Annotation]) -> Result<()> {
        writeln!(self.w, ".runtime {} annotations", kind)?;
        self.enter_block();
        for line in lines {
            write!(self.w, "{}.annotation ", self.sol)?;
            self.annotation_contents(line)?;
            writeln!(self.w, "{}.end annotation", self.sol)?;
        }
        self.exit_block();
        write!(self.w, "{}.end runtime", self.sol)?;
        Ok(())
    }

    fn runtime_param_annotations(&mut self, kind: &'static str, lines: &[attrs::ParameterAnnotation]) -> Result<()> {
        writeln!(self.w, ".runtime {} paramannotations", kind)?;
        self.enter_block();
        for line in lines {
            writeln!(self.w, "{}.paramannotation", self.sol)?;
            self.enter_block();
            for anno in &line.0 {
                write!(self.w, "{}.annotation ", self.sol)?;
                self.annotation_contents(anno)?;
                writeln!(self.w, "{}.end annotation", self.sol)?;
            }
            self.exit_block();
            writeln!(self.w, "{}.end paramannotation", self.sol)?;
        }
        self.exit_block();
        write!(self.w, "{}.end runtime", self.sol)?;
        Ok(())
    }

    fn runtime_type_annotations(&mut self, kind: &'static str, lines: &[attrs::TypeAnnotation]) -> Result<()> {
        writeln!(self.w, ".runtime {} typeannotations", kind)?;
        self.enter_block();
        for line in lines {
            write!(self.w, "{}.typeannotation {} ", self.sol, line.info.0)?;
            self.enter_block();
            use attrs::TargetInfoData::*;
            match &line.info.1 {
                TypeParam(v) => writeln!(self.w, "typeparam {}", *v)?,
                Super(v) => writeln!(self.w, "super {}", *v)?,
                TypeParamBound(v, v2) => writeln!(self.w, "typeparambound {} {}", *v, *v2)?,
                Empty => writeln!(self.w, "empty")?,
                FormalParam(v) => writeln!(self.w, "methodparam {}", *v)?,
                Throws(v) => writeln!(self.w, "throws {}", *v)?,
                LocalVar(vals) => {
                    writeln!(self.w, "localvar")?;
                    // writeln!(self.w, "{}.localvar", self.sol)?;
                    self.enter_block();
                    for v in vals.iter().copied() {
                        if let Some((start, end)) = v.range {
                            writeln!(self.w, "{}from {} to {} {}", self.sol, start, end, v.index)?;
                        } else {
                            // WTF, Java?
                            writeln!(self.w, "{}nowhere {}", self.sol, v.index)?;
                        }
                    }
                    self.exit_block();
                    writeln!(self.w, "{}.end localvar", self.sol)?;
                }
                Catch(v) => writeln!(self.w, "catch {}", *v)?,
                Offset(v) => writeln!(self.w, "offset {}", *v)?,
                TypeArgument(v, v2) => writeln!(self.w, "typearg {} {}", *v, *v2)?,
            }

            writeln!(self.w, "{}.typepath", self.sol)?;
            self.enter_block();
            for (v1, v2) in line.path.iter().copied() {
                writeln!(self.w, "{}{} {}", self.sol, v1, v2)?;
            }
            self.exit_block();
            writeln!(self.w, "{}.end typepath", self.sol)?;

            write!(self.w, "{}", self.sol)?;
            self.annotation_contents(&line.anno)?;

            self.exit_block();
            writeln!(self.w, "{}.end typeannotation", self.sol)?;
        }
        self.exit_block();
        write!(self.w, "{}.end runtime", self.sol)?;
        Ok(())
    }

    fn record_component(&mut self, r: &attrs::RecordComponent<'a>) -> Result<()> {
        let rp = self.rp;

        write!(self.w, "{}{} {}", self.sol, rp.utf(r.name), rp.utf(r.desc))?;
        if r.attrs.len() > 0 {
            writeln!(self.w, "{} .attributes", self.sol)?;
            self.enter_block();

            for a in &r.attrs {
                self.attr(a)?;
            }

            self.exit_block();
            writeln!(self.w, "{}.end attributes", self.sol)?;
        } else {
            writeln!(self.w, "")?;
        }
        Ok(())
    }

    fn module_attr(&mut self, m: &attrs::ModuleAttr) -> Result<()> {
        let rp = self.rp;

        writeln!(
            self.w,
            ".module {}{} version {}",
            rp.single(m.module, SingleTag::Module),
            Flags::mod_other(m.flags),
            rp.utf(m.version)
        )?;
        self.enter_block();
        for req in &m.requires {
            writeln!(
                self.w,
                "{}.requires {}{} version {}",
                self.sol,
                rp.single(req.module, SingleTag::Module),
                Flags::mod_requires(req.flags),
                rp.utf(req.version)
            )?;
        }

        for p in &m.exports {
            write!(
                self.w,
                "{}.exports {}{} to",
                self.sol,
                rp.single(p.package, SingleTag::Package),
                Flags::mod_other(p.flags)
            )?;
            for submod in p.modules.iter().copied() {
                write!(self.w, " {}", rp.single(submod, SingleTag::Module))?;
            }
            writeln!(self.w, "")?;
        }
        for p in &m.opens {
            write!(
                self.w,
                "{}.opens {}{} to",
                self.sol,
                rp.single(p.package, SingleTag::Package),
                Flags::mod_other(p.flags)
            )?;
            for submod in p.modules.iter().copied() {
                write!(self.w, " {}", rp.single(submod, SingleTag::Module))?;
            }
            writeln!(self.w, "")?;
        }

        for u in m.uses.iter().copied() {
            writeln!(self.w, "{}.uses {}", self.sol, rp.cls(u))?;
        }

        for p in &m.provides {
            write!(self.w, "{}.provides {} with", self.sol, rp.cls(p.cls))?;
            for c in p.provides_with.iter().copied() {
                write!(self.w, " {}", rp.cls(c))?;
            }
            writeln!(self.w, "")?;
        }

        self.exit_block();
        writeln!(self.w, "{}.end module", self.sol)?;
        Ok(())
    }

    fn element_value(&mut self, ev: &attrs::ElementValue) -> Result<()> {
        let rp = self.rp;

        use attrs::ElementValue::*;
        match ev {
            Anno(anno) => {
                write!(self.w, "annotation ")?;
                self.annotation_contents(anno)?;
                writeln!(self.w, "{}.end annotation", self.sol)?;
            }
            Array(vals) => {
                writeln!(self.w, "array")?;
                self.enter_block();
                for val in vals {
                    write!(self.w, "{}", self.sol)?;
                    self.element_value(val)?;
                    writeln!(self.w, "")?;
                }
                self.exit_block();
                writeln!(self.w, "{}.end array", self.sol)?;
            }
            Enum(r1, r2) => write!(self.w, "enum {} {}", rp.utf(*r1), rp.utf(*r2))?,

            Class(r) => write!(self.w, "class {}", rp.utf(*r))?,
            Str(r) => write!(self.w, "string {}", rp.utf(*r))?,

            Byte(r) => write!(self.w, "byte {}", rp.ldc(*r))?,
            Boolean(r) => write!(self.w, "boolean {}", rp.ldc(*r))?,
            Char(r) => write!(self.w, "char {}", rp.ldc(*r))?,
            Short(r) => write!(self.w, "short {}", rp.ldc(*r))?,
            Int(r) => write!(self.w, "int {}", rp.ldc(*r))?,
            Float(r) => write!(self.w, "float {}", rp.ldc(*r))?,
            Long(r) => write!(self.w, "long {}", rp.ldc(*r))?,
            Double(r) => write!(self.w, "double {}", rp.ldc(*r))?,
        }
        Ok(())
    }

    fn annotation_contents(&mut self, anno: &attrs::Annotation) -> Result<()> {
        let rp = self.rp;

        writeln!(self.w, "{}", rp.utf(anno.0))?;
        self.enter_block();
        for val in &anno.1 {
            write!(self.w, "{}{} = ", self.sol, rp.utf(val.0))?;
            self.element_value(&val.1)?;
            writeln!(self.w, "")?;
        }
        self.exit_block();
        Ok(())
    }
}

pub fn disassemble(mut w: impl Write, c: &Class, opts: DisassemblerOptions) -> Result<()> {
    let mut bstable = None;
    let mut inner_classes = None;
    for attr in &c.attrs {
        use AttrBody::*;
        match &attr.body {
            BootstrapMethods(v) => bstable = Some(v.as_ref()),
            InnerClasses(v) => inner_classes = Some(v.as_ref()),
            _ => {}
        }
    }

    let rp = RefPrinter::new(opts.roundtrip, &c.cp, bstable, inner_classes);

    // d.v(".version")?.v(c.version.0)?.v(c.version.1)?.eol()?;

    if c.has_ambiguous_short_code {
        for line in SHORT_CODE_WARNING {
            writeln!(w, "; {}", line)?;
        }
    }

    writeln!(w, ".version {} {}", c.version.0, c.version.1)?;
    writeln!(w, ".class{} {}", Flags::class(c.access), rp.cls(c.this))?;
    writeln!(w, ".super {}", rp.cls(c.super_))?;

    for ind in c.interfaces.iter().copied() {
        writeln!(w, ".implements {}", rp.cls(ind))?;
    }

    let mut d = Disassembler::new(w, &rp, opts.roundtrip, c.version);
    for field in c.fields.iter() {
        d.field(field)?;
    }

    for method in c.methods.iter() {
        d.method(method)?;
    }

    for attr in c.attrs.iter() {
        d.attr(attr)?;
    }

    let mut w = d.w;
    rp.print_const_defs(&mut w)?;
    writeln!(w, ".end class")
}
