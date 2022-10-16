use super::class_parser::ClassParser;
use super::cpool::types;
use super::cpool::InlineConst;
use super::span::Error;
use super::span::Span;
use super::string;
use super::tokenize::TokenType;
use super::writer::Writer;

pub enum AttrResult<'a> {
    Normal,
    ImplicitBootstrap {
        name: Option<types::SymSpanUtf8<'a>>,
        len: Option<u32>,
        span: Span<'a>,
    },
}

type ParseFn<'a> = fn(&mut ClassParser<'a>, &mut Writer<'a>) -> Result<(), Error>;

enum ListKind {
    Line,
    DotEnd,
    Greedy(&'static str),
}
impl ListKind {
    fn at_end(&self, p: &mut ClassParser<'_>) -> bool {
        use ListKind::*;
        match self {
            Line => p.has_type(TokenType::Newlines),
            DotEnd => p.tryv(".end"),
            Greedy(dir) => !p.tryv(dir),
        }
    }
}

macro_rules! line_list {
    ($p: ident, $w:ident, $( $s:expr );+) => {
        |p, w| p.list(w, ListKind::Line, |$p, $w| {$( $s );+; Ok(())})
    };
}

macro_rules! dotend_list {
    ($tag:expr, $p: ident, $w:ident, $( $s:expr );+) => {
        |p, w| {p.eol()?; p.list(w, ListKind::DotEnd, |$p, $w| {$( $s );+; Ok(())})?; p.val($tag)}
    };
}

macro_rules! dotend_list8 {
    ($tag:expr, $p: ident, $w:ident, $( $s:expr );+) => {
        |p, w| {p.eol()?; p.list8(w, ListKind::DotEnd, |$p, $w| {$( $s );+; Ok(())})?; p.val($tag)}
    };
}

impl<'a> ClassParser<'a> {
    fn get_parse_attr_body_fn(&mut self, directive: Span<'a>) -> Result<(&'static str, ParseFn<'a>), Error> {
        Ok(match directive.0 {
            ".annotationdefault" => ("AnnotationDefault", Self::element_value),
            ".code" => ("Code", Self::parse_code),
            ".constantvalue" => ("ConstantValue", |p, w| {
                w.cp(p.ldc_rhs()?);
                Ok(())
            }),
            ".deprecated" => ("Deprecated", |_p, _w| Ok(())),
            ".enclosing" => ("EnclosingMethod", |p, w| {
                p.val("method")?;
                w.cp(p.cls()?);
                w.cp(p.nat()?);
                Ok(())
            }),
            ".exceptions" => ("Exceptions", line_list! {p, w, w.cp(p.cls()?)}),
            ".innerclasses" => (
                "InnerClasses",
                dotend_list! {"innerclasses", p, w,
                    w.cp(p.cls()?); w.cp(p.cls()?); w.cp(p.utf()?); w.u16(p.flags()?); p.eol()?
                },
            ),
            ".linenumbertable" => (
                "LineNumberTable",
                dotend_list! {"linenumbertable", p, w, w.u16(p.lbl16()?); w.u16(p.u16()?); p.eol()?},
            ),
            ".localvariabletable" => (
                "LocalVariableTable",
                dotend_list! {"localvariabletable", p, w, p.local_var_table_item(w)?},
            ),
            ".localvariabletypetable" => (
                "LocalVariableTypeTable",
                dotend_list! {"localvariabletypetable", p, w, p.local_var_table_item(w)?},
            ),
            ".methodparameters" => (
                "MethodParameters",
                dotend_list8! {"methodparameters", p, w, w.cp(p.utf()?); w.u16(p.flags()?); p.eol()?},
            ),
            ".module" => ("Module", Self::module),
            ".modulemainclass" => ("ModuleMainClass", |p, w| {
                w.cp(p.cls()?);
                Ok(())
            }),
            ".modulepackages" => ("ModulePackages", line_list! {p, w, w.cp(p.single(InlineConst::Package)?)}),
            ".nesthost" => ("NestHost", |p, w| {
                w.cp(p.cls()?);
                Ok(())
            }),
            ".nestmembers" => ("NestMembers", line_list! {p, w, w.cp(p.cls()?)}),
            ".permittedsubclasses" => ("PermittedSubclasses", line_list! {p, w, w.cp(p.cls()?)}),
            ".record" => ("Record", dotend_list! {"record", p, w, p.record_item(w)?}),
            ".runtime" => {
                let tok = self.next()?;
                let visible = match tok.1 .0 {
                    "visible" => true,
                    "invisible" => false,
                    _ => return self.err1("Expected visible or invisible", tok.1),
                };

                let tok = self.next()?;
                match tok.1 .0 {
                    "annotations" => (
                        if visible {
                            "RuntimeVisibleAnnotations"
                        } else {
                            "RuntimeInvisibleAnnotations"
                        },
                        dotend_list! {"runtime", p, w, p.val(".annotation")?; p.annotation(w, false)?; p.eol()?},
                    ),
                    "paramannotations" => (
                        if visible {
                            "RuntimeVisibleParameterAnnotations"
                        } else {
                            "RuntimeInvisibleParameterAnnotations"
                        },
                        dotend_list8! {"runtime", p, w,
                            p.val(".paramannotation")?;
                            p.eol()?;
                            p.list(w, ListKind::DotEnd, |p, w| {p.val(".annotation")?; p.annotation(w, false)?; p.eol()})?;
                            p.val("paramannotation")?;
                            p.eol()?
                        },
                    ),
                    "typeannotations" => (
                        if visible {
                            "RuntimeVisibleTypeAnnotations"
                        } else {
                            "RuntimeInvisibleTypeAnnotations"
                        },
                        dotend_list! {"runtime", p, w, p.val(".typeannotation")?; p.ta_target_info(w)?; p.ta_target_path(w)?; p.annotation(w, true)?; p.eol()?},
                    ),
                    _ => return self.err1("Expected annotations, paramannotations, or typeannotations", tok.1),
                }
            }

            ".signature" => ("Signature", |p, w| {
                w.cp(p.utf()?);
                Ok(())
            }),
            ".sourcedebugextension" => ("SourceDebugExtension", |p, w| {
                let span = p.assert_type(TokenType::StringLit)?;
                let bs = string::unescape(span.0).map_err(|(msg, s)| p.error1(msg, Span(s)))?;
                w.write(&bs);
                Ok(())
            }),
            ".sourcefile" => ("SourceFile", |p, w| {
                w.cp(p.utf()?);
                Ok(())
            }),
            ".stackmaptable" => ("StackMapTable", |p, w| {
                if let Some((count, buf)) = p.stack_map_table.take() {
                    w.u16(count);
                    w.extend_from_writer(buf);
                    Ok(())
                } else {
                    let span = p.next()?.1;
                    p.err1(
                        "StackMapTable attribute may only be used inside Code attributes, and only once per method",
                        span,
                    )
                }
            }),
            ".synthetic" => ("Synthetic", |_p, _w| Ok(())),
            _ => return self.err1("Unrecognized attribute directive", directive),
        })
    }

    fn parse_attr_sub(&mut self, w: &mut Writer<'a>) -> Result<AttrResult<'a>, Error> {
        let (name, len) = if self.tryv(".attribute") {
            (Some(self.utf()?), if self.tryv("length") { Some(self.u32()?) } else { None })
        } else {
            (None, None)
        };

        if self.has_type(TokenType::StringLit) {
            if let Some(name) = name {
                let span = self.next()?.1;
                let bs = string::unescape(span.0).map_err(|(msg, s)| self.error1(msg, Span(s)))?;
                w.cp(name);
                w.u32(len.unwrap_or(bs.len() as u32));
                w.write(&bs);
                return Ok(AttrResult::Normal);
            }
        }

        let directive = self.next()?.1;
        if directive.0 == ".bootstrapmethods" {
            return Ok(AttrResult::ImplicitBootstrap {
                name,
                len,
                span: directive,
            });
        }

        let (name_str, body_cb) = self.get_parse_attr_body_fn(directive)?;
        w.cp(name.unwrap_or(Self::static_utf(name_str, directive)));
        let ph = w.ph32();
        let start_buf_len = w.len();

        body_cb(&mut *self, &mut *w)?;
        let end_buf_len = w.len();

        let len = len.unwrap_or(
            (end_buf_len - start_buf_len)
                .try_into()
                .map_err(|_| self.error1("Exceeded maximum attribute length (2^32-1 bytes)", directive))?,
        );
        w.fill32(ph, len);

        Ok(AttrResult::Normal)
    }

    pub fn parse_attr_allow_bsm(&mut self, w: &mut Writer<'a>, count: &mut u16) -> Result<AttrResult<'a>, Error> {
        let span = self.peek()?.1;
        let res = self.parse_attr_sub(w)?;
        if *count == u16::MAX {
            self.err1("Maximum number of attributes (65535) exceeded", span)
        } else {
            *count += 1;
            Ok(res)
        }
    }

    pub fn parse_attr(&mut self, w: &mut Writer<'a>, count: &mut u16) -> Result<(), Error> {
        match self.parse_attr_allow_bsm(w, count)? {
            AttrResult::Normal => Ok(()),
            AttrResult::ImplicitBootstrap { span, .. } => {
                self.err1("Implicit bootstrap method attributes can only be used at class level.", span)
            }
        }
    }

    ///////////////////////////////////////////////////////////////////////////////
    fn annotation(&mut self, w: &mut Writer<'a>, is_type: bool) -> Result<(), Error> {
        w.cp(self.utf()?);
        self.eol()?;
        let ph = w.ph();
        let mut count = 0;
        while !self.tryv(".end") {
            if count == u16::MAX {
                let span = self.peek()?.1;
                return self.err1("Maximum number of annotations elements (65535) exceeded", span);
            }
            count += 1;
            w.cp(self.utf()?);
            self.val("=")?;
            self.element_value(w)?;
            self.eol()?;
        }
        if is_type {
            self.val("typeannotation")?;
        } else {
            self.val("annotation")?;
        }
        w.fill(ph, count);
        Ok(())
    }

    fn element_value(&mut self, w: &mut Writer<'a>) -> Result<(), Error> {
        let tok = self.next()?;
        match tok.1 .0 {
            "annotation" => {
                w.u8(64);
                self.annotation(w, false)?;
            }
            "array" => {
                w.u8(91);
                self.eol()?;
                let ph = w.ph();
                let mut count = 0;
                while !self.tryv(".end") {
                    if count == u16::MAX {
                        let span = self.peek()?.1;
                        return self.err1("Maximum number of annotations in array element (65535) exceeded", span);
                    }
                    count += 1;
                    self.element_value(w)?;
                    self.eol()?;
                }
                self.val("array")?;
                w.fill(ph, count);
            }
            "boolean" => {
                w.u8(90);
                w.cp(self.ldc_rhs()?);
            }
            "byte" => {
                w.u8(66);
                w.cp(self.ldc_rhs()?);
            }
            "char" => {
                w.u8(67);
                w.cp(self.ldc_rhs()?);
            }
            "class" => {
                w.u8(99);
                w.cp(self.utf()?);
            }
            "double" => {
                w.u8(68);
                w.cp(self.ldc_rhs()?);
            }
            "enum" => {
                w.u8(101);
                w.cp(self.utf()?);
                w.cp(self.utf()?);
            }
            "float" => {
                w.u8(70);
                w.cp(self.ldc_rhs()?);
            }
            "int" => {
                w.u8(73);
                w.cp(self.ldc_rhs()?);
            }
            "long" => {
                w.u8(74);
                w.cp(self.ldc_rhs()?);
            }
            "short" => {
                w.u8(83);
                w.cp(self.ldc_rhs()?);
            }
            "string" => {
                w.u8(115);
                w.cp(self.utf()?);
            }
            _ => return self.err1("Unrecognized element value tag", tok.1),
        };
        Ok(())
    }

    fn local_var_table_item(&mut self, w: &mut Writer<'a>) -> Result<(), Error> {
        let (ind, _, name, desc, _, start, _, end) = (
            self.u16()?,
            self.val("is")?,
            self.utf()?,
            self.utf()?,
            self.val("from")?,
            self.lblpos()?,
            self.val("to")?,
            self.lblpos()?,
        );
        w.u16(self.pos_to_u16(start)?);
        w.u16(self.pos_diff_to_u16(start.v, end)?);
        w.cp(name);
        w.cp(desc);
        w.u16(ind);
        self.eol()
    }

    fn list(&mut self, w: &mut Writer<'a>, kind: ListKind, f: ParseFn<'a>) -> Result<(), Error> {
        let ph = w.ph();
        let mut count = 0;
        while !kind.at_end(self) {
            if count == u16::MAX {
                let span = self.peek()?.1;
                return self.err1("Maximum number of elements (65535) exceeded", span);
            }
            count += 1;
            f(self, w)?;
        }
        w.fill(ph, count);
        Ok(())
    }

    fn list8(&mut self, w: &mut Writer<'a>, kind: ListKind, f: ParseFn<'a>) -> Result<(), Error> {
        let ph = w.ph8();
        let mut count = 0;
        while !kind.at_end(self) {
            if count == u8::MAX {
                let span = self.peek()?.1;
                return self.err1("Maximum number of elements (255) exceeded", span);
            }
            count += 1;
            f(self, w)?;
        }
        w.fill8(ph, count);
        Ok(())
    }

    fn module(&mut self, w: &mut Writer<'a>) -> Result<(), Error> {
        use ListKind::Greedy;
        w.cp(self.utf()?);
        w.u16(self.flags()?);
        self.val("version")?;
        w.cp(self.utf()?);
        self.eol()?;

        let exports_item = |p: &mut Self, w: &mut Writer<'a>| {
            w.cp(p.single(InlineConst::Package)?);
            w.u16(p.flags()?);
            if p.tryv("to") {
                p.list(w, ListKind::Line, |p, w| Ok(w.cp(p.single(InlineConst::Package)?)))?;
            } else {
                w.u16(0); // count of 0 targets
            }
            p.eol()
        };

        self.list(w, Greedy(".requires"), |p, w| {
            w.cp(p.single(InlineConst::Module)?);
            w.u16(p.flags()?);
            p.val("version")?;
            w.cp(p.utf()?);
            p.eol()
        })?;
        self.list(w, Greedy(".exports"), exports_item)?;
        self.list(w, Greedy(".opens"), exports_item)?;
        self.list(w, Greedy(".uses"), |p, w| {
            w.cp(p.cls()?);
            p.eol()
        })?;
        self.list(w, Greedy(".provides"), |p, w| {
            w.cp(p.cls()?);
            p.val("with")?;
            p.list(w, ListKind::Line, |p, w| Ok(w.cp(p.cls()?)))?;
            p.eol()
        })?;

        self.val(".end")?;
        self.val("module")
    }

    fn record_item(&mut self, w: &mut Writer<'a>) -> Result<(), Error> {
        w.cp(self.utf()?);
        w.cp(self.utf()?);
        if self.tryv(".attributes") {
            self.eol()?;

            let ph = w.ph();
            let mut attr_count = 0;

            while !self.tryv(".end") {
                self.parse_attr(w, &mut attr_count)?;
                self.eol()?;
            }
            self.val("attributes")?;
            w.fill(ph, attr_count);
        } else {
            w.u16(0);
        }
        self.eol()
    }

    fn ta_target_info(&mut self, w: &mut Writer<'a>) -> Result<(), Error> {
        w.u8(self.u8()?);
        let span = self.next()?.1;
        match span.0 {
            "typeparam" => w.u8(self.u8()?),
            "super" => w.u16(self.u16()?),
            "typeparambound" => {
                w.u8(self.u8()?);
                w.u8(self.u8()?)
            }
            "empty" => (),
            "methodparam" => w.u8(self.u8()?),
            "throws" => w.u16(self.u16()?),
            "localvar" => {
                self.eol()?;
                self.list(w, ListKind::DotEnd, |p, w| {
                    if p.tryv("nowhere") {
                        w.u16(0xFFFF);
                        w.u16(0xFFFF);
                    } else {
                        let (_, start, _, end) = (p.val("from")?, p.lblpos()?, p.val("to")?, p.lblpos()?);
                        w.u16(p.pos_to_u16(start)?);
                        w.u16(p.pos_diff_to_u16(start.v, end)?);
                    }
                    w.u16(p.u16()?);
                    p.eol()
                })?;
                self.val("localvar")?;
            }
            "catch" => w.u16(self.u16()?),
            "offset" => w.u16(self.lbl16()?),
            "typearg" => {
                w.u16(self.lbl16()?);
                w.u8(self.u8()?)
            }

            _ => return self.err1("Expected type annotation target info type", span),
        }

        self.eol()
    }

    fn ta_target_path(&mut self, w: &mut Writer<'a>) -> Result<(), Error> {
        self.val(".typepath")?;
        self.eol()?;
        self.list8(w, ListKind::DotEnd, |p, w| {
            w.u8(p.u8()?);
            w.u8(p.u8()?);
            p.eol()
        })?;
        self.val("typepath")?;
        self.eol()
    }
}
