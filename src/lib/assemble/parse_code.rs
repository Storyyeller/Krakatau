use super::class_parser::ns;
use super::class_parser::ClassParser;
use super::cpool::types;
use super::cpool::InlineConst;
use super::cpool::Or;
use super::label::Pos;
use super::span::Error;
use super::span::Span;
use super::tokenize::Token;
use super::tokenize::TokenType;
use super::writer::Placeholder;
use super::writer::Writer;
use std::collections::HashMap;

#[derive(Debug)]
struct ExceptionHandler<'a> {
    cls: types::SymSpanClass<'a>,
    start: Span<'a>,
    end: Span<'a>,
    target: Span<'a>,
}

struct LazyJump<'a, const N: usize> {
    base: Pos,
    target: Span<'a>,
    ph: Placeholder<N>,
}

#[derive(Default)]
struct BytecodeState<'a> {
    labels: HashMap<&'a str, Pos>,
    short_jumps: Vec<LazyJump<'a, 2>>,
    long_jumps: Vec<LazyJump<'a, 4>>,
    exceptions: Vec<ExceptionHandler<'a>>,
    stack_map_table: StackMapTable<'a>,
    no_implicit_stackmap: bool,
}

#[derive(Default)]
struct StackMapTable<'a> {
    w: Writer<'a>,
    vtype_lbls: Vec<(Placeholder<2>, Span<'a>)>,
    num_entries: u16,
    last_pos: Option<Pos>,
    // track first .stack span so we can use it as span for implicit attr if necessary
    debug_span: Option<Span<'a>>,
}

impl<'a> ClassParser<'a> {
    fn legacy_fmim(
        &mut self,
        f: fn(types::SymClassRef<'a>, types::SymNatRef<'a>) -> types::SymConstInline<'a>,
    ) -> Result<types::SymSpanConst<'a>, Error> {
        // Hacks to support undocumented legacy syntax
        let first = self.peek()?.1;

        if self.has_type(TokenType::Ref) {
            self.next()?; // consume first
                          // Legacy method syntax
            if self.has_type(TokenType::Word) || self.has_type(TokenType::StringLit) {
                let nat = self.nat()?;
                return Ok(Or::B(first.of(f(self.ref_from(first)?, ns(nat)))));
            }
            return self.ref_from(first);
        }

        // Official syntax requires Field, Method, or InterfaceMethod tag (or ref, handled above)
        match first.0 {
            "Field" | "Method" | "InterfaceMethod" => return self.ref_or_tagged_const(),
            _ => (),
        }

        let mut words = Vec::with_capacity(3);
        while words.len() < 3 && (self.has_type(TokenType::Word) || self.has_type(TokenType::StringLit)) {
            words.push(self.next()?);
        }

        if self.has_type(TokenType::Ref) {
            if words.len() == 2 {
                let cls = self.cls_from(words[0])?;
                let name = self.utf_from(words[1])?;
                let desc = self.utf()?;
                let nat = types::InlineNat(ns(name), ns(desc));
                return Ok(Or::B(first.of(f(ns(cls), Or::B(nat)))));
            } else if words.len() == 1 {
                let cls = self.cls_from(words[0])?;
                let nat = self.nat()?;
                return Ok(Or::B(first.of(f(ns(cls), ns(nat)))));
            }
        }

        fn tok_from_substr<'a>(s: &'a str) -> Token<'a> {
            Token(TokenType::Word, Span(s))
        }

        let (cls, name, desc) = match words.len() {
            3 => (self.cls_from(words[0])?, self.utf_from(words[1])?, self.utf_from(words[2])?),
            2 => {
                let cnn = words[0].1 .0;
                let (left, right) = cnn.rsplit_once('/').unwrap_or((cnn, cnn));

                let cls = self.cls_from(tok_from_substr(left))?;
                let name = self.utf_from(tok_from_substr(right))?;
                let desc = self.utf_from(words[1])?;
                (cls, name, desc)
            }
            1 => {
                let cnnd = words[0].1 .0;
                let (cnn, _) = cnnd.split_once('(').unwrap_or((cnnd, cnnd));
                let (_, d) = cnnd.split_at(cnn.len()); // include the ( back into d
                let (left, right) = cnn.rsplit_once('/').unwrap_or((cnn, cnn));

                let cls = self.cls_from(tok_from_substr(left))?;
                let name = self.utf_from(tok_from_substr(right))?;
                let desc = self.utf_from(tok_from_substr(d))?;
                (cls, name, desc)
            }
            _ => return self.err1("Expected Field, Method, InterfaceMethod, or ref", first),
        };

        let nat = types::InlineNat(ns(name), ns(desc));
        Ok(Or::B(first.of(f(ns(cls), Or::B(nat)))))
    }

    fn parse_invokeinterface(&mut self, w: &mut Writer<'a>) -> Result<(), Error> {
        let r = self.legacy_fmim(InlineConst::InterfaceMethod)?;

        let args = if self.has_type(TokenType::Newlines) {
            let debug_span = self.peek()?.1;
            let desc = r
                .as_b()
                .and_then(|const_| match &const_.v {
                    InlineConst::InterfaceMethod(_, nat) => nat.as_b().and_then(|nat| nat.1.as_b().map(|utf| utf.0 .0)),
                    _ => None,
                })
                .ok_or_else(|| self.error1("Exceeded maximum bytecode length", debug_span))?;

            let mut count = 1;
            let mut off = 1;
            while off < desc.len() {
                match desc[off] {
                    // )
                    41 => {
                        break;
                    }
                    // [
                    91 => {}
                    // J, D
                    68 | 74 => {
                        count += 2;
                    }
                    // L
                    76 => {
                        count += 1;
                        while off < desc.len() && desc[off] != 59
                        /* ; */
                        {
                            off += 1;
                        }
                    }
                    _ => {
                        count += 1;
                    }
                }
                off += 1;
            }

            count
        } else {
            self.u8()?
        };

        w.cp(r);
        w.u8(args);
        w.u8(0);
        Ok(())
    }

    fn short_jump_instr(&mut self, pos: Pos, state: &mut BytecodeState<'a>, w: &mut Writer<'a>) -> Result<(), Error> {
        let target = self.lbl()?;
        state.short_jumps.push(LazyJump {
            base: pos,
            target,
            ph: w.ph(),
        });
        Ok(())
    }

    fn long_jump_instr(&mut self, pos: Pos, state: &mut BytecodeState<'a>, w: &mut Writer<'a>) -> Result<(), Error> {
        let target = self.lbl()?;
        state.long_jumps.push(LazyJump {
            base: pos,
            target,
            ph: w.ph32(),
        });
        Ok(())
    }

    fn parse_tableswitch(&mut self, pos: Pos, state: &mut BytecodeState<'a>, w: &mut Writer<'a>) -> Result<(), Error> {
        // 0 to 3 padding bytes
        for _ in (pos.0 % 4)..3 {
            w.u8(0);
        }

        let low = self.i32()?;
        self.eol()?;

        let base = pos;
        let default_ph = w.ph32();

        w.u32(low as u32);
        let high_ph = w.ph32();

        // First non-default jump
        state.long_jumps.push(LazyJump {
            base,
            target: self.lbl()?,
            ph: w.ph32(),
        });
        self.eol()?;
        let mut high = low;
        // Now do the rest of the jumps
        while !self.tryv("default") {
            if high == i32::MAX {
                let span = self.peek()?.1;
                return self.err1("Overflow in tableswitch index", span);
            }
            high += 1;
            state.long_jumps.push(LazyJump {
                base,
                target: self.lbl()?,
                ph: w.ph32(),
            });
            self.eol()?;
        }
        // default jump
        self.val(":")?;
        state.long_jumps.push(LazyJump {
            base,
            target: self.lbl()?,
            ph: default_ph,
        });

        w.fill32(high_ph, high as u32);
        Ok(())
    }
    fn parse_lookupswitch(&mut self, pos: Pos, state: &mut BytecodeState<'a>, w: &mut Writer<'a>) -> Result<(), Error> {
        // 0 to 3 padding bytes
        for _ in (pos.0 % 4)..3 {
            w.u8(0);
        }
        self.eol()?;
        let base = pos;

        let mut jumps = HashMap::new();
        while !self.tryv("default") {
            let span = self.peek()?.1;
            let key = self.i32()?;
            self.val(":")?;
            let target = self.lbl()?;
            self.eol()?;

            if jumps.insert(key, target).is_some() {
                return self.err1("Duplicate lookupswitch key", span);
            }
            if jumps.len() > (i32::MAX as usize) {
                return self.err1("Overflow in lookupswitch jump count", span);
            }
        }
        // default jump
        self.val(":")?;
        state.long_jumps.push(LazyJump {
            base,
            target: self.lbl()?,
            ph: w.ph32(),
        });

        w.u32(jumps.len().try_into().unwrap());

        let mut pairs: Vec<_> = jumps.into_iter().collect();
        pairs.sort_unstable_by_key(|t| t.0);

        for (k, v) in pairs {
            w.u32(k as u32);
            state.long_jumps.push(LazyJump {
                base,
                target: v,
                ph: w.ph32(),
            });
        }

        Ok(())
    }

    fn parse_wide(&mut self, w: &mut Writer<'a>) -> Result<(), Error> {
        let tok = self.next()?;
        match tok.1 .0 {
            "aload" => (w.u8(25), w.u16(self.u16()?)).0,
            "astore" => (w.u8(58), w.u16(self.u16()?)).0,
            "dload" => (w.u8(24), w.u16(self.u16()?)).0,
            "dstore" => (w.u8(57), w.u16(self.u16()?)).0,
            "fload" => (w.u8(23), w.u16(self.u16()?)).0,
            "fstore" => (w.u8(56), w.u16(self.u16()?)).0,
            "iinc" => (w.u8(132), w.u16(self.u16()?), w.u16(self.i16()? as u16)).0,
            "iload" => (w.u8(21), w.u16(self.u16()?)).0,
            "istore" => (w.u8(54), w.u16(self.u16()?)).0,
            "lload" => (w.u8(22), w.u16(self.u16()?)).0,
            "lstore" => (w.u8(55), w.u16(self.u16()?)).0,
            "ret" => (w.u8(169), w.u16(self.u16()?)).0,
            _ => return self.err1("Unrecognized wide bytecode opcode", tok.1),
        };
        Ok(())
    }

    fn newarray_code(&mut self) -> Result<u8, Error> {
        let span = self.next()?.1;
        match span.0 {
            "boolean" => Ok(4),
            "byte" => Ok(8),
            "char" => Ok(5),
            "double" => Ok(7),
            "float" => Ok(6),
            "int" => Ok(10),
            "long" => Ok(11),
            "short" => Ok(9),
            _ => self.err1(
                "Error, expected 'boolean', 'byte', 'char', 'double', 'float', 'int', 'long', or 'short'.",
                span,
            ),
        }
    }

    fn parse_stack_directive(&mut self, pos: Pos, state: &mut StackMapTable<'a>) -> Result<(), Error> {
        let w = &mut state.w;
        let vtype_lbls = &mut state.vtype_lbls;
        let span = self.next()?.1;

        let offset = if let Some(prev) = state.last_pos {
            if pos.0 > prev.0 {
                pos.0 - prev.0 - 1
            } else {
                return self.err1("Stack frame must have strictly greater bytecode offset than previous frame", span);
            }
        } else {
            pos.0
        };
        let offset: u16 = offset
            .try_into()
            .map_err(|_| self.error1("Exceeded maximum bytecode offset", span))?;

        match span.0 {
            "same" => {
                if offset <= 63 {
                    w.u8(offset as u8);
                } else {
                    return self.err1("Exceeded maximum bytecode offset (try using same_extended instead).", span);
                }
            }
            "stack_1" => {
                if offset <= 63 {
                    w.u8(offset as u8 + 64);
                    self.parse_vtype(w, vtype_lbls)?;
                } else {
                    return self.err1("Exceeded maximum bytecode offset (try using same_extended instead).", span);
                }
            }
            "stack_1_extended" => {
                w.u8(247);
                w.u16(offset);
                self.parse_vtype(w, vtype_lbls)?;
            }
            "chop" => {
                let amt = self.u8()?;
                if amt > 4 {
                    return self.err1("Chop amount must be at most 4. Use a full frame to remove more items.", span);
                }
                w.u8(251 - amt);
                w.u16(offset);
            }
            "same_extended" => {
                w.u8(251);
                w.u16(offset);
            }
            "append" => {
                let ph = w.ph8();
                w.u16(offset);

                let mut tag = 251;
                while tag < 255 && self.has_type(TokenType::Word) {
                    self.parse_vtype(w, vtype_lbls)?;
                    tag += 1;
                }

                w.fill8(ph, tag);
            }
            "full" => {
                w.u8(255);
                w.u16(offset);
                self.eol()?;
                {
                    self.val("locals")?;
                    let ph = w.ph();
                    let mut count = 0;
                    while count < u16::MAX && self.has_type(TokenType::Word) {
                        self.parse_vtype(w, vtype_lbls)?;
                        count += 1;
                    }
                    w.fill(ph, count);
                    self.eol()?;
                }
                {
                    self.val("stack")?;
                    let ph = w.ph();
                    let mut count = 0;
                    while count < u16::MAX && self.has_type(TokenType::Word) {
                        self.parse_vtype(w, vtype_lbls)?;
                        count += 1;
                    }
                    w.fill(ph, count);
                    self.eol()?;
                }
                self.val(".end")?;
                self.val("stack")?;
            }
            _ => return self.err1("Expected same, stack_1, stack_1_extended, chop, same_extended, append, or full", span),
        }

        if state.num_entries == u16::MAX {
            return self.err1("Exceeded maximum number of stack map entries per method (65535).", span);
        }
        state.num_entries += 1;
        state.last_pos = Some(pos);
        Ok(())
    }

    fn parse_vtype(&mut self, w: &mut Writer<'a>, vtype_lbls: &mut Vec<(Placeholder<2>, Span<'a>)>) -> Result<(), Error> {
        let span = self.next()?.1;
        match span.0 {
"Double" => w.u8(3),
            "Float" => w.u8(2),
            "Integer" => w.u8(1),
            "Long" => w.u8(4),
            "Null" => w.u8(5),
            "Object" => (w.u8(7), w.cp(self.cls()?)).0,
            "Top" => w.u8(0),
            "Uninitialized" => {
                w.u8(8);
                vtype_lbls.push((w.ph(), self.lbl()?));
            }
            "UninitializedThis" => w.u8(6),
            _ => return self.err1("Expected 'Double', 'Float', 'Integer', 'Long', 'Null', 'Object', 'Top', 'Uninitialized', or 'UninitializedThis'", span),

        }
        Ok(())
    }

    ///////////////////////////////////////////////////////////////////////////////////////////////////////////////////

    fn parse_code_inner(&mut self, w: &mut Writer<'a>) -> Result<usize, Error> {
        let start_buf_len = w.len();
        let mut state = BytecodeState::default();
        let debug_span = self.peek()?.1;

        loop {
            let tok = self.peek()?;
            let pos = Pos((w.len() - start_buf_len)
                .try_into()
                .map_err(|_| self.error1("Exceeded maximum bytecode length", tok.1))?);

            match tok.0 {
                TokenType::LabelDef => {
                    let lbl = self.next()?.1 .0.trim_end_matches(':');
                    if state.labels.insert(lbl, pos).is_some() {
                        return self.err1("Duplicate label.", tok.1);
                    }

                    if self.has_type(TokenType::Word) {
                        self.parse_instr_line(pos, &mut state, w)?;
                    } else {
                        self.eol()?;
                    }
                }
                TokenType::Directive => {
                    if !self.parse_code_directive_line(pos, &mut state, w, tok.1)? {
                        break;
                    }
                }
                TokenType::Word => self.parse_instr_line(pos, &mut state, w)?,
                _ => return self.err1("Expected bytecode instruction or directive.", tok.1),
            }
        }

        let bytecode_len = w.len() - start_buf_len;

        if !self.labels.is_empty() || !self.stack_map_table.is_none() {
            return self.err1("Invalid nested Code attribute", debug_span);
        }

        self.labels = state.labels;
        for jump in state.short_jumps {
            let target = self.lbl_to_pos(jump.target)?;
            let offset = self.pos_diff_to_i16(jump.base, target)?;
            w.fill(jump.ph, offset as u16);
        }
        for jump in state.long_jumps {
            let target = self.lbl_to_pos(jump.target)?;
            let offset = self.pos_diff_to_i32(jump.base, target)?;
            w.fill32(jump.ph, offset as u32);
        }
        for (ph, lbl) in state.stack_map_table.vtype_lbls {
            let offset = self.pos_to_u16(self.lbl_to_pos(lbl)?)?;
            state.stack_map_table.w.fill(ph, offset);
        }

        w.u16(state.exceptions.len().try_into().unwrap());
        for except in state.exceptions {
            w.u16(self.pos_to_u16(self.lbl_to_pos(except.start)?)?);
            w.u16(self.pos_to_u16(self.lbl_to_pos(except.end)?)?);
            w.u16(self.pos_to_u16(self.lbl_to_pos(except.target)?)?);
            w.cp(except.cls);
        }

        self.stack_map_table = Some((state.stack_map_table.num_entries, state.stack_map_table.w));

        // Only accept code attributes after all bytecode and code directives
        let ph = w.ph();
        let mut attr_count = 0;
        while !self.tryv(".end") {
            self.parse_attr(w, &mut attr_count)?;
            self.eol()?;
        }

        // Implicit StackMapTable attribute
        if let Some((count, buf)) = self.stack_map_table.take() {
            if count > 0 && !state.no_implicit_stackmap {
                let span = state.stack_map_table.debug_span.unwrap();
                w.cp(Self::static_utf("StackMapTable", span));
                w.u32(2 + buf.len() as u32);
                w.u16(count);
                w.extend_from_writer(buf);
                attr_count += 1;
            }
        }
        w.fill(ph, attr_count);

        self.labels.clear();
        Ok(bytecode_len)
    }

    pub fn parse_code(&mut self, w: &mut Writer<'a>) -> Result<(), Error> {
        let is_short = self.version < (45, 3) && !self.tryv("long");

        if is_short {
            (self.val("stack")?, w.u8(self.u8()?), self.val("locals")?, w.u8(self.u8()?), self.eol()?);
            let ph = w.ph();

            let bytecode_len = self.parse_code_inner(w)?;
            let debug_span = self.peek()?.1;
            let len = bytecode_len
                .try_into()
                .map_err(|_| self.error1("Exceeded maximum bytecode length", debug_span))?;
            w.fill(ph, len);
        } else {
            (
                self.val("stack")?,
                w.u16(self.u16()?),
                self.val("locals")?,
                w.u16(self.u16()?),
                self.eol()?,
            );
            let ph = w.ph32();

            let bytecode_len = self.parse_code_inner(w)?;
            let debug_span = self.peek()?.1;
            let len = bytecode_len
                .try_into()
                .map_err(|_| self.error1("Exceeded maximum bytecode length", debug_span))?;
            w.fill32(ph, len);
        }

        self.val("code")
    }

    pub fn parse_legacy_method_body(&mut self, w: &mut Writer<'a>) -> Result<(), Error> {
        let debug_span = self.peek()?.1;
        w.cp(Self::static_utf("Code", debug_span));

        let code_len_ph = w.ph32();
        let start_buf_len = w.len();

        /////////////////////////
        let mut stack = u16::MAX;
        let mut locals = u16::MAX;
        while self.tryv(".limit") {
            if self.tryv("stack") {
                stack = self.u16()?;
            } else {
                self.val("locals")?;
                locals = self.u16()?;
            }
            self.eol()?;
        }

        let is_short = self.version < (45, 3);
        if is_short {
            w.u8(stack as u8);
            w.u8(locals as u8);
            let ph = w.ph();

            let bytecode_len = self.parse_code_inner(w)?;
            w.fill(ph, bytecode_len as u16);
        } else {
            w.u16(stack);
            w.u16(locals);
            let ph = w.ph32();

            let bytecode_len = self.parse_code_inner(w)?;
            w.fill32(ph, bytecode_len as u32);
        }

        let code_attr_len = w.len() - start_buf_len;
        w.fill32(code_len_ph, code_attr_len as u32);
        Ok(())
    }

    fn parse_code_directive_line(
        &mut self,
        pos: Pos,
        state: &mut BytecodeState<'a>,
        _w: &mut Writer<'a>,
        directive: Span<'a>,
    ) -> Result<bool, Error> {
        match directive.0 {
            ".catch" => {
                self.next()?;
                let cls = self.cls()?;
                self.val("from")?;
                let start = self.lbl()?;
                self.val("to")?;
                let end = self.lbl()?;
                self.val("using")?;
                let target = self.lbl()?;
                state.exceptions.push(ExceptionHandler { cls, start, end, target });

                if state.exceptions.len() > u16::MAX as usize {
                    return self.err1("Maximum 65535 exception handlers per method", directive);
                }
            }
            // Uncodumented directive for backwards compatibility with Krakatau v1
            ".noimplicitstackmap" => {
                self.next()?;
                state.no_implicit_stackmap = true;
            }
            ".stack" => {
                self.next()?;
                state.stack_map_table.debug_span.get_or_insert(directive);
                self.parse_stack_directive(pos, &mut state.stack_map_table)?;
            }
            _ => return Ok(false),
        }
        self.eol()?;
        Ok(true)
    }

    fn parse_instr_line(&mut self, pos: Pos, state: &mut BytecodeState<'a>, w: &mut Writer<'a>) -> Result<(), Error> {
        let instr = self.next()?.1;
        match instr.0 {
            "aaload" => (w.u8(50), ()).0,
            "aastore" => (w.u8(83), ()).0,
            "aconst_null" => (w.u8(1), ()).0,
            "aload" => (w.u8(25), w.u8(self.u8()?)).0,
            "aload_0" => (w.u8(42), ()).0,
            "aload_1" => (w.u8(43), ()).0,
            "aload_2" => (w.u8(44), ()).0,
            "aload_3" => (w.u8(45), ()).0,
            "anewarray" => (w.u8(189), w.cp(self.cls()?)).0,
            "areturn" => (w.u8(176), ()).0,
            "arraylength" => (w.u8(190), ()).0,
            "astore" => (w.u8(58), w.u8(self.u8()?)).0,
            "astore_0" => (w.u8(75), ()).0,
            "astore_1" => (w.u8(76), ()).0,
            "astore_2" => (w.u8(77), ()).0,
            "astore_3" => (w.u8(78), ()).0,
            "athrow" => (w.u8(191), ()).0,
            "baload" => (w.u8(51), ()).0,
            "bastore" => (w.u8(84), ()).0,
            "bipush" => (w.u8(16), w.u8(self.i8()? as u8)).0,
            "caload" => (w.u8(52), ()).0,
            "castore" => (w.u8(85), ()).0,
            "checkcast" => (w.u8(192), w.cp(self.cls()?)).0,
            "d2f" => (w.u8(144), ()).0,
            "d2i" => (w.u8(142), ()).0,
            "d2l" => (w.u8(143), ()).0,
            "dadd" => (w.u8(99), ()).0,
            "daload" => (w.u8(49), ()).0,
            "dastore" => (w.u8(82), ()).0,
            "dcmpg" => (w.u8(152), ()).0,
            "dcmpl" => (w.u8(151), ()).0,
            "dconst_0" => (w.u8(14), ()).0,
            "dconst_1" => (w.u8(15), ()).0,
            "ddiv" => (w.u8(111), ()).0,
            "dload" => (w.u8(24), w.u8(self.u8()?)).0,
            "dload_0" => (w.u8(38), ()).0,
            "dload_1" => (w.u8(39), ()).0,
            "dload_2" => (w.u8(40), ()).0,
            "dload_3" => (w.u8(41), ()).0,
            "dmul" => (w.u8(107), ()).0,
            "dneg" => (w.u8(119), ()).0,
            "drem" => (w.u8(115), ()).0,
            "dreturn" => (w.u8(175), ()).0,
            "dstore" => (w.u8(57), w.u8(self.u8()?)).0,
            "dstore_0" => (w.u8(71), ()).0,
            "dstore_1" => (w.u8(72), ()).0,
            "dstore_2" => (w.u8(73), ()).0,
            "dstore_3" => (w.u8(74), ()).0,
            "dsub" => (w.u8(103), ()).0,
            "dup" => (w.u8(89), ()).0,
            "dup2" => (w.u8(92), ()).0,
            "dup2_x1" => (w.u8(93), ()).0,
            "dup2_x2" => (w.u8(94), ()).0,
            "dup_x1" => (w.u8(90), ()).0,
            "dup_x2" => (w.u8(91), ()).0,
            "f2d" => (w.u8(141), ()).0,
            "f2i" => (w.u8(139), ()).0,
            "f2l" => (w.u8(140), ()).0,
            "fadd" => (w.u8(98), ()).0,
            "faload" => (w.u8(48), ()).0,
            "fastore" => (w.u8(81), ()).0,
            "fcmpg" => (w.u8(150), ()).0,
            "fcmpl" => (w.u8(149), ()).0,
            "fconst_0" => (w.u8(11), ()).0,
            "fconst_1" => (w.u8(12), ()).0,
            "fconst_2" => (w.u8(13), ()).0,
            "fdiv" => (w.u8(110), ()).0,
            "fload" => (w.u8(23), w.u8(self.u8()?)).0,
            "fload_0" => (w.u8(34), ()).0,
            "fload_1" => (w.u8(35), ()).0,
            "fload_2" => (w.u8(36), ()).0,
            "fload_3" => (w.u8(37), ()).0,
            "fmul" => (w.u8(106), ()).0,
            "fneg" => (w.u8(118), ()).0,
            "frem" => (w.u8(114), ()).0,
            "freturn" => (w.u8(174), ()).0,
            "fstore" => (w.u8(56), w.u8(self.u8()?)).0,
            "fstore_0" => (w.u8(67), ()).0,
            "fstore_1" => (w.u8(68), ()).0,
            "fstore_2" => (w.u8(69), ()).0,
            "fstore_3" => (w.u8(70), ()).0,
            "fsub" => (w.u8(102), ()).0,
            "getfield" => (w.u8(180), w.cp(self.legacy_fmim(InlineConst::Field)?)).0,
            "getstatic" => (w.u8(178), w.cp(self.legacy_fmim(InlineConst::Field)?)).0,
            "goto" => (w.u8(167), self.short_jump_instr(pos, state, w)?).0,
            "goto_w" => (w.u8(200), self.long_jump_instr(pos, state, w)?).0,
            "i2b" => (w.u8(145), ()).0,
            "i2c" => (w.u8(146), ()).0,
            "i2d" => (w.u8(135), ()).0,
            "i2f" => (w.u8(134), ()).0,
            "i2l" => (w.u8(133), ()).0,
            "i2s" => (w.u8(147), ()).0,
            "iadd" => (w.u8(96), ()).0,
            "iaload" => (w.u8(46), ()).0,
            "iand" => (w.u8(126), ()).0,
            "iastore" => (w.u8(79), ()).0,
            "iconst_0" => (w.u8(3), ()).0,
            "iconst_1" => (w.u8(4), ()).0,
            "iconst_2" => (w.u8(5), ()).0,
            "iconst_3" => (w.u8(6), ()).0,
            "iconst_4" => (w.u8(7), ()).0,
            "iconst_5" => (w.u8(8), ()).0,
            "iconst_m1" => (w.u8(2), ()).0,
            "idiv" => (w.u8(108), ()).0,
            "if_acmpeq" => (w.u8(165), self.short_jump_instr(pos, state, w)?).0,
            "if_acmpne" => (w.u8(166), self.short_jump_instr(pos, state, w)?).0,
            "if_icmpeq" => (w.u8(159), self.short_jump_instr(pos, state, w)?).0,
            "if_icmpge" => (w.u8(162), self.short_jump_instr(pos, state, w)?).0,
            "if_icmpgt" => (w.u8(163), self.short_jump_instr(pos, state, w)?).0,
            "if_icmple" => (w.u8(164), self.short_jump_instr(pos, state, w)?).0,
            "if_icmplt" => (w.u8(161), self.short_jump_instr(pos, state, w)?).0,
            "if_icmpne" => (w.u8(160), self.short_jump_instr(pos, state, w)?).0,
            "ifeq" => (w.u8(153), self.short_jump_instr(pos, state, w)?).0,
            "ifge" => (w.u8(156), self.short_jump_instr(pos, state, w)?).0,
            "ifgt" => (w.u8(157), self.short_jump_instr(pos, state, w)?).0,
            "ifle" => (w.u8(158), self.short_jump_instr(pos, state, w)?).0,
            "iflt" => (w.u8(155), self.short_jump_instr(pos, state, w)?).0,
            "ifne" => (w.u8(154), self.short_jump_instr(pos, state, w)?).0,
            "ifnonnull" => (w.u8(199), self.short_jump_instr(pos, state, w)?).0,
            "ifnull" => (w.u8(198), self.short_jump_instr(pos, state, w)?).0,
            "iinc" => (w.u8(132), w.u8(self.u8()?), w.u8(self.i8()? as u8)).0,
            "iload" => (w.u8(21), w.u8(self.u8()?)).0,
            "iload_0" => (w.u8(26), ()).0,
            "iload_1" => (w.u8(27), ()).0,
            "iload_2" => (w.u8(28), ()).0,
            "iload_3" => (w.u8(29), ()).0,
            "imul" => (w.u8(104), ()).0,
            "ineg" => (w.u8(116), ()).0,
            "instanceof" => (w.u8(193), w.cp(self.cls()?)).0,
            "invokedynamic" => (w.u8(186), w.cp(self.ref_or_tagged_const()?), w.u16(0)).0,
            "invokeinterface" => (w.u8(185), self.parse_invokeinterface(w)?).0,
            "invokespecial" => (w.u8(183), w.cp(self.legacy_fmim(InlineConst::Method)?)).0,
            "invokestatic" => (w.u8(184), w.cp(self.legacy_fmim(InlineConst::Method)?)).0,
            "invokevirtual" => (w.u8(182), w.cp(self.legacy_fmim(InlineConst::Method)?)).0,
            "ior" => (w.u8(128), ()).0,
            "irem" => (w.u8(112), ()).0,
            "ireturn" => (w.u8(172), ()).0,
            "ishl" => (w.u8(120), ()).0,
            "ishr" => (w.u8(122), ()).0,
            "istore" => (w.u8(54), w.u8(self.u8()?)).0,
            "istore_0" => (w.u8(59), ()).0,
            "istore_1" => (w.u8(60), ()).0,
            "istore_2" => (w.u8(61), ()).0,
            "istore_3" => (w.u8(62), ()).0,
            "isub" => (w.u8(100), ()).0,
            "iushr" => (w.u8(124), ()).0,
            "ixor" => (w.u8(130), ()).0,
            "jsr" => (w.u8(168), self.short_jump_instr(pos, state, w)?).0,
            "jsr_w" => (w.u8(201), self.long_jump_instr(pos, state, w)?).0,
            "l2d" => (w.u8(138), ()).0,
            "l2f" => (w.u8(137), ()).0,
            "l2i" => (w.u8(136), ()).0,
            "ladd" => (w.u8(97), ()).0,
            "laload" => (w.u8(47), ()).0,
            "land" => (w.u8(127), ()).0,
            "lastore" => (w.u8(80), ()).0,
            "lcmp" => (w.u8(148), ()).0,
            "lconst_0" => (w.u8(9), ()).0,
            "lconst_1" => (w.u8(10), ()).0,
            "ldc" => (w.u8(18), w.cp_ldc(self.ldc_rhs()?, instr)).0,
            "ldc2_w" => (w.u8(20), w.cp(self.ldc_rhs()?)).0,
            "ldc_w" => (w.u8(19), w.cp(self.ldc_rhs()?)).0,
            "ldiv" => (w.u8(109), ()).0,
            "lload" => (w.u8(22), w.u8(self.u8()?)).0,
            "lload_0" => (w.u8(30), ()).0,
            "lload_1" => (w.u8(31), ()).0,
            "lload_2" => (w.u8(32), ()).0,
            "lload_3" => (w.u8(33), ()).0,
            "lmul" => (w.u8(105), ()).0,
            "lneg" => (w.u8(117), ()).0,
            "lookupswitch" => (w.u8(171), self.parse_lookupswitch(pos, state, w)?).0,
            "lor" => (w.u8(129), ()).0,
            "lrem" => (w.u8(113), ()).0,
            "lreturn" => (w.u8(173), ()).0,
            "lshl" => (w.u8(121), ()).0,
            "lshr" => (w.u8(123), ()).0,
            "lstore" => (w.u8(55), w.u8(self.u8()?)).0,
            "lstore_0" => (w.u8(63), ()).0,
            "lstore_1" => (w.u8(64), ()).0,
            "lstore_2" => (w.u8(65), ()).0,
            "lstore_3" => (w.u8(66), ()).0,
            "lsub" => (w.u8(101), ()).0,
            "lushr" => (w.u8(125), ()).0,
            "lxor" => (w.u8(131), ()).0,
            "monitorenter" => (w.u8(194), ()).0,
            "monitorexit" => (w.u8(195), ()).0,
            "multianewarray" => (w.u8(197), w.cp(self.cls()?), w.u8(self.u8()?)).0,
            "new" => (w.u8(187), w.cp(self.cls()?)).0,
            "newarray" => (w.u8(188), w.u8(self.newarray_code()?)).0,
            "nop" => (w.u8(0), ()).0,
            "pop" => (w.u8(87), ()).0,
            "pop2" => (w.u8(88), ()).0,
            "putfield" => (w.u8(181), w.cp(self.legacy_fmim(InlineConst::Field)?)).0,
            "putstatic" => (w.u8(179), w.cp(self.legacy_fmim(InlineConst::Field)?)).0,
            "ret" => (w.u8(169), w.u8(self.u8()?)).0,
            "return" => (w.u8(177), ()).0,
            "saload" => (w.u8(53), ()).0,
            "sastore" => (w.u8(86), ()).0,
            "sipush" => (w.u8(17), w.u16(self.i16()? as u16)).0,
            "swap" => (w.u8(95), ()).0,
            "tableswitch" => (w.u8(170), self.parse_tableswitch(pos, state, w)?).0,
            "wide" => (w.u8(196), self.parse_wide(w)?).0,
            _ => return self.err1("Unrecognized bytecode opcode", instr),
        }

        self.eol()
    }
}
