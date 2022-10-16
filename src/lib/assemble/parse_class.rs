use super::base_parser::BaseParser;
use super::class_parser::ns;
use super::class_parser::ClassParser;
use super::cpool::types;
use super::cpool::BsAttrNameNeeded;
use super::cpool::Or;
use super::parse_attr::AttrResult;
use super::span::Error;
use super::tokenize::TokenType;
use super::writer::BufWriter;
use super::writer::Writer;

impl<'a> ClassParser<'a> {
    fn parse_const_def(&mut self) -> Result<(), Error> {
        self.val(".const")?;
        let lhs_span = self.assert_type(TokenType::Ref)?;
        let lhs = self.ref_type(lhs_span)?;
        self.val("=")?;
        let rhs_span = self.peek()?.1;
        let rhs = self.ref_or_tagged_const()?;

        match lhs {
            types::RefType::Raw(ind) => {
                let rhs = match rhs {
                    Or::A(_) => return self.err1("Raw refs cannot be defined by another ref", rhs_span),
                    Or::B(b) => b,
                };
                self.pool.add_raw_def(ind, lhs_span, rhs)?
            }
            types::RefType::Sym(name) => self.pool.add_sym_def(name, ns(rhs))?,
        };

        self.eol()
    }

    fn parse_bootstrap_def(&mut self) -> Result<(), Error> {
        self.val(".bootstrap")?;
        let lhs_span = self.assert_type(TokenType::BsRef)?;
        let lhs = self.ref_type(lhs_span)?;
        self.val("=")?;
        let rhs_span = self.peek()?.1;
        let rhs = self.ref_or_tagged_bootstrap()?;

        match lhs {
            types::RefType::Raw(ind) => {
                let rhs = match rhs {
                    Or::A(_) => return self.err1("Raw refs cannot be defined by another ref", rhs_span),
                    Or::B(b) => b,
                };
                self.pool.add_bs_raw_def(ind, lhs_span, rhs)?
            }
            types::RefType::Sym(name) => self.pool.add_bs_sym_def(name, ns(rhs))?,
        };

        self.eol()
    }
    ///////////////////////////////////////////////////////////////////////////

    fn parse_field_def(&mut self, w: &mut Writer<'a>) -> Result<(), Error> {
        self.val(".field")?;
        w.u16(self.flags()?);
        w.cp(self.utf()?);
        w.cp(self.utf()?);

        let ph = w.ph();
        let mut attr_count = 0;

        if let Some(span) = self.tryv2("=") {
            w.cp(Self::static_utf("ConstantValue", span));
            w.u32(2);
            w.cp(self.ldc_rhs()?);
            attr_count += 1;
        }

        if self.tryv(".fieldattributes") {
            self.eol()?;

            while !self.tryv(".end") {
                self.parse_attr(w, &mut attr_count)?;
                self.eol()?;
            }

            self.val("fieldattributes")?;
        }

        w.fill(ph, attr_count);
        self.eol()?;
        Ok(())
    }

    fn parse_method_def(&mut self, w: &mut Writer<'a>) -> Result<(), Error> {
        self.val(".method")?;
        w.u16(self.flags()?);
        w.cp(self.utf()?);
        self.val(":")?;
        w.cp(self.utf()?);
        self.eol()?;

        let ph = w.ph();
        let mut attr_count = 0;

        if self.peek()?.1 .0 == ".limit" {
            self.parse_legacy_method_body(w)?;
            attr_count = 1;
        } else {
            while !self.tryv(".end") {
                self.parse_attr(w, &mut attr_count)?;
                self.eol()?;
            }
        }
        self.val("method")?;
        self.eol()?;

        w.fill(ph, attr_count);
        Ok(())
    }

    ///////////////////////////////////////////////////////////////////////////

    pub fn parse(mut self) -> Result<(BaseParser<'a>, (Option<&'a [u8]>, Vec<u8>)), Error> {
        if self.tryv(".version") {
            self.version = (self.u16()?, self.u16()?);
            self.eol()?;
        };

        // todo
        let debug_span = self.peek()?.1;

        let mut w = Writer::default();
        self.val(".class")?;
        w.u16(self.flags()?);

        w.cp(self.cls()?);
        self.eol()?;

        self.val(".super")?;
        w.cp(self.cls()?);
        self.eol()?;

        let ph = w.ph();
        let mut interface_count = 0;
        while let Some(span) = self.tryv2(".implements") {
            if interface_count == u16::MAX {
                return self.err1("Maximum number of interfaces (65535) exceeded", span);
            }
            interface_count += 1;

            w.cp(self.cls()?);
            self.eol()?;
        }
        w.fill(ph, interface_count);

        let mut field_w = w;
        let field_ph = field_w.ph();
        let mut field_count = 0;

        let mut method_w = Writer::default();
        let mut method_count = 0;

        // We won't know how the contents of the bootstrap attr, and thus how long it should be,
        // until the constant pool has been fully resolved at the end. Therefore, we use two
        // writers, one for attributes before the .bootstrapmethods attr (if any), including the
        // name of the later, and second writer for any attributes that appear after the
        // .bootstrapmethods attr if one is present. Once we put all the pieces of the classfile together
        // at the end, we'll fill in the actual data for the bootstramp methods table in between.
        let mut attr_w1 = Writer::default();
        let mut bs_attr_placeholder_info = None;
        let mut attr_w2 = Writer::default();
        let mut attr_count = 0;

        while let Ok(tok) = self.peek() {
            match tok.1 .0 {
                ".bootstrap" => self.parse_bootstrap_def()?,
                ".const" => self.parse_const_def()?,
                ".field" => {
                    if field_count == u16::MAX {
                        return self.err1("Maximum number of fields (65535) exceeded", tok.1);
                    }
                    field_count += 1;
                    self.parse_field_def(&mut field_w)?;
                }
                ".method" => {
                    if method_count == u16::MAX {
                        return self.err1("Maximum number of methods (65535) exceeded", tok.1);
                    }
                    method_count += 1;
                    self.parse_method_def(&mut method_w)?;
                }
                ".end" => {
                    self.val(".end")?;
                    self.val("class")?;
                    self.eol()?;
                    break;
                }
                _ => {
                    if bs_attr_placeholder_info.is_none() {
                        match self.parse_attr_allow_bsm(&mut attr_w1, &mut attr_count)? {
                            AttrResult::Normal => (),
                            AttrResult::ImplicitBootstrap { name, len, span: _ } => {
                                let bs_name_ph = match name {
                                    Some(name) => {
                                        // attr has name explicitly provided, so just write it and don't store a placeholder
                                        attr_w1.cp(name);
                                        None
                                    }
                                    None => {
                                        // attr has no explicit name, so store a placeholder
                                        // to be filled in with the implicitly created name later
                                        Some(attr_w1.ph())
                                    }
                                };

                                bs_attr_placeholder_info = Some((bs_name_ph, len));
                            }
                        }
                    } else {
                        match self.parse_attr_allow_bsm(&mut attr_w2, &mut attr_count)? {
                            AttrResult::Normal => (),
                            AttrResult::ImplicitBootstrap { span, .. } => {
                                return self.err1("Duplicate .bootstrapmethods attribute", span);
                            }
                        }
                    }
                    self.eol()?;

                    // return self.err1("Expected .field, .method, .const, .bootstrap, .end class, or attribute directive", tok.1)
                }
            }
        }
        field_w.fill(field_ph, field_count);

        let mut pool = self.pool.finish_defs()?;
        // println!("data {:?}", field_w);

        field_w.resolve_ldc_refs(|r, s| pool.resolve_ldc(r, s))?;
        method_w.resolve_ldc_refs(|r, s| pool.resolve_ldc(r, s))?;
        attr_w1.resolve_ldc_refs(|r, s| pool.resolve_ldc(r, s))?;
        attr_w2.resolve_ldc_refs(|r, s| pool.resolve_ldc(r, s))?;

        let field_w = field_w.resolve_refs(|r| pool.resolve(r))?;
        let method_w = method_w.resolve_refs(|r| pool.resolve(r))?;
        let mut attr_w1 = attr_w1.resolve_refs(|r| pool.resolve(r))?;
        let attr_w2 = attr_w2.resolve_refs(|r| pool.resolve(r))?;

        // println!("data {:?}", field_w);

        let mut w = BufWriter::default();
        w.u32(0xCAFEBABE);
        w.u16(self.version.1);
        w.u16(self.version.0);

        let bs_attr_needed = match bs_attr_placeholder_info {
            Some((Some(_), _)) => BsAttrNameNeeded::Always,
            Some((None, _)) => BsAttrNameNeeded::Never,
            None => BsAttrNameNeeded::IfPresent,
        };
        let class_name_ind = field_w.read_u16(2);
        let (assembled_bs_attr_info, class_name) = pool.end().build(&mut w, bs_attr_needed, class_name_ind)?;

        w.extend(&field_w);
        w.u16(method_count);
        w.extend(&method_w);

        // println!("bsattr info {:?}", bs_attr_placeholder_info);
        if let Some((name_ph, len)) = bs_attr_placeholder_info {
            if let Some(ph) = name_ph {
                attr_w1.fill(ph, assembled_bs_attr_info.name.unwrap());
            }

            w.u16(attr_count);
            w.extend(&attr_w1);

            let actual_length = assembled_bs_attr_info.data_len().ok_or_else(|| {
                self.parser
                    .error1("BootstrapMethods table exceeds maximum attribute length", debug_span)
            })?;

            w.u32(len.unwrap_or(actual_length));
            w.u16(assembled_bs_attr_info.num_bs);
            w.write(&assembled_bs_attr_info.buf);

            w.extend(&attr_w2);
        } else {
            // check if we need to add an implicit BootstrapMethods attribute at the end
            if let Some(name) = assembled_bs_attr_info.name {
                if attr_count == u16::MAX {
                    return self.parser.err1(
                        "Exceeded maximum class attribute count due to implicit BootstrapMethods attribute",
                        debug_span,
                    );
                }
                let actual_length = assembled_bs_attr_info.data_len().ok_or_else(|| {
                    self.parser
                        .error1("BootstrapMethods table exceeds maximum attribute length", debug_span)
                })?;

                w.u16(attr_count + 1);
                w.extend(&attr_w1);
                w.u16(name);
                w.u32(actual_length);
                w.u16(assembled_bs_attr_info.num_bs);
                w.write(&assembled_bs_attr_info.buf);
            } else {
                w.u16(attr_count);
                w.extend(&attr_w1);
            }
        }
        // println!("finish bs stuff");

        // println!("data {:?}", w);
        Ok((self.parser, (class_name, w.into_buf())))
    }
}
