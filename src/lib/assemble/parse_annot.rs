use super::class_parser::ClassParser;
use super::span::Error;
use super::writer::Placeholder;
use super::writer::Writer;

#[derive(Clone, Copy)]
enum ListKind {
    Annotation { is_type_annot: bool },
    Array,
}

// An annotation or array element value whose contents are still being parsed. Annotations and arrays can be
// nested arbitrarily deeply, so they are parsed using an explicit stack of these rather than recursion.
// The recursion structure is the same in both cases, so all we need is ListKind to distinguish them.
struct List {
    kind: ListKind,
    ph: Placeholder<2>,
    count: u16,
}

impl<'a> ClassParser<'a> {
    // called from parse_attr
    pub(super) fn annotation(&mut self, w: &mut Writer<'a>, is_type_annot: bool) -> Result<(), Error> {
        let list = self.annotation_header(w, is_type_annot)?;
        self.parse_lists(w, list)
    }

    // called from parse_attr
    pub(super) fn element_value(&mut self, w: &mut Writer<'a>) -> Result<(), Error> {
        match self.element_value_header(w)? {
            Some(list) => self.parse_lists(w, list),
            None => Ok(()),
        }
    }

    fn annotation_header(&mut self, w: &mut Writer<'a>, is_type_annot: bool) -> Result<List, Error> {
        w.cp(self.utf()?);
        Ok(List {
            kind: ListKind::Annotation { is_type_annot },
            ph: w.ph(),
            count: 0,
        })
    }

    // Parse an element value. For annotations and arrays, only the header is parsed (not including the
    // end of the line), and the returned list must be parsed by the caller.
    fn element_value_header(&mut self, w: &mut Writer<'a>) -> Result<Option<List>, Error> {
        let tok = self.next()?;
        match tok.1.0 {
            "annotation" => {
                w.u8(64);
                return Ok(Some(self.annotation_header(w, false)?));
            }
            "array" => {
                w.u8(91);
                return Ok(Some(List {
                    kind: ListKind::Array,
                    ph: w.ph(),
                    count: 0,
                }));
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
        Ok(None)
    }

    // Parse the remaining contents of list and any lists nested inside it. Each iteration of the loop parses
    // either one item or the end of the innermost list. Only the parents of the innermost list are kept on
    // the stack. The end of the root list's line is left for the caller, as with scalar element values.
    fn parse_lists(&mut self, w: &mut Writer<'a>, mut list: List) -> Result<(), Error> {
        let mut parents = Vec::new();
        loop {
            // Each iteration starts at the end of the line containing the list header or the previous item,
            // which may be a scalar or the end of a nested list.
            self.eol()?;
            if self.tryv(".end") {
                self.val(match list.kind {
                    ListKind::Annotation { is_type_annot: false } => "annotation",
                    ListKind::Annotation { is_type_annot: true } => "typeannotation",
                    ListKind::Array => "array",
                })?;
                w.fill(list.ph, list.count);

                match parents.pop() {
                    Some(parent) => list = parent,
                    None => return Ok(()),
                }
            } else {
                if list.count == u16::MAX {
                    let span = self.peek()?.1;
                    return self.err1(
                        match list.kind {
                            ListKind::Annotation { .. } => "Maximum number of annotations elements (65535) exceeded",
                            ListKind::Array => "Maximum number of annotations in array element (65535) exceeded",
                        },
                        span,
                    );
                }
                list.count += 1;

                // Annotation includes "name =", arrays include values directly
                if let ListKind::Annotation { .. } = list.kind {
                    w.cp(self.utf()?);
                    self.val("=")?;
                }
                if let Some(child) = self.element_value_header(w)? {
                    parents.push(std::mem::replace(&mut list, child));
                }
            }
        }
    }
}
