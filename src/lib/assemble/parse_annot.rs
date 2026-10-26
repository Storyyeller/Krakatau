use super::class_parser::ClassParser;
use super::span::Error;
use super::writer::Writer;

impl<'a> ClassParser<'a> {
    pub(super) fn annotation(&mut self, w: &mut Writer<'a>, is_type: bool) -> Result<(), Error> {
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

    pub(super) fn element_value(&mut self, w: &mut Writer<'a>) -> Result<(), Error> {
        let tok = self.next()?;
        match tok.1.0 {
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
}
