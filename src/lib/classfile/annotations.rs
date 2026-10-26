use super::reader::ParseError;
use super::reader::Reader;

#[derive(Debug)]
pub enum ElementValue {
    Anno(Annotation),
    Array(Vec<ElementValue>),
    Enum(u16, u16),

    Class(u16),
    Str(u16),

    Byte(u16),
    Boolean(u16),
    Char(u16),
    Short(u16),
    Int(u16),
    Float(u16),
    Long(u16),
    Double(u16),
}
impl ElementValue {
    pub(super) fn new(r: &mut Reader) -> Result<Self, ParseError> {
        match Self::header(r)? {
            Header::Value(v) => Ok(v),
            Header::List(list) => Ok(PendingList::parse(r, list)?.into_value()),
        }
    }

    // Parse an element value. For annotations and arrays, only the header is parsed, and the
    // returned list must be parsed by the caller.
    fn header(r: &mut Reader) -> Result<Header, ParseError> {
        use ElementValue::*;
        Ok(Header::Value(match r.u8()? {
            64 => return Ok(Header::List(PendingList::anno(r)?)),
            66 => Byte(r.u16()?),
            67 => Char(r.u16()?),
            68 => Double(r.u16()?),
            70 => Float(r.u16()?),
            73 => Int(r.u16()?),
            74 => Long(r.u16()?),
            83 => Short(r.u16()?),
            90 => Boolean(r.u16()?),
            91 => return Ok(Header::List(PendingList::array(r)?)),
            99 => Class(r.u16()?),
            101 => Enum(r.u16()?, r.u16()?),
            115 => Str(r.u16()?),
            _ => return ParseError::s("Invalid element value tag"),
        }))
    }
}
// The derived drop would recurse once per level of nesting, so move all descendants into a flat
// list instead. Each one has its children taken out before it is dropped, so its drop is shallow.
impl Drop for ElementValue {
    fn drop(&mut self) {
        fn take_children(ev: &mut ElementValue, out: &mut Vec<ElementValue>) {
            match ev {
                ElementValue::Array(vals) => out.extend(std::mem::take(vals)),
                ElementValue::Anno(Annotation(_, vals)) => out.extend(std::mem::take(vals).into_iter().map(|(_, v)| v)),
                _ => {}
            }
        }

        let mut pending = Vec::new();
        take_children(self, &mut pending);
        while let Some(mut ev) = pending.pop() {
            take_children(&mut ev, &mut pending);
        }
    }
}

#[derive(Debug)]
pub struct Annotation(pub u16, pub Vec<(u16, ElementValue)>);
impl Annotation {
    pub(super) fn new(r: &mut Reader) -> Result<Self, ParseError> {
        let list = PendingList::anno(r)?;
        let PendingItems::Anno(anno, _) = PendingList::parse(r, list)? else {
            unreachable!()
        };
        Ok(anno)
    }
}

enum Header {
    Value(ElementValue),
    List(PendingList),
}

enum PendingItems {
    // Also holds the name of the element currently being parsed
    Anno(Annotation, u16),
    Array(Vec<ElementValue>),
}
impl PendingItems {
    fn into_value(self) -> ElementValue {
        match self {
            PendingItems::Anno(anno, _) => ElementValue::Anno(anno),
            PendingItems::Array(vals) => ElementValue::Array(vals),
        }
    }
}

// An annotation or array element value whose contents are still being parsed. Annotations and arrays can be
// nested arbitrarily deeply, so they are parsed using an explicit stack of these rather than recursion.
struct PendingList {
    items: PendingItems,
    remaining: u16,
}
impl PendingList {
    fn anno(r: &mut Reader) -> Result<Self, ParseError> {
        let desc = r.u16()?;
        let remaining = r.u16()?;
        let anno = Annotation(desc, Vec::with_capacity(remaining as usize));
        Ok(Self {
            items: PendingItems::Anno(anno, 0),
            remaining,
        })
    }

    fn array(r: &mut Reader) -> Result<Self, ParseError> {
        let remaining = r.u16()?;
        Ok(Self {
            items: PendingItems::Array(Vec::with_capacity(remaining as usize)),
            remaining,
        })
    }

    fn add(&mut self, v: ElementValue) {
        match &mut self.items {
            PendingItems::Anno(anno, name) => anno.1.push((*name, v)),
            PendingItems::Array(vals) => vals.push(v),
        }
    }

    // Parse the remaining contents of list and any lists nested inside it. Each iteration of the loop parses
    // either one item or the end of the innermost list. Only the parents of the innermost list are kept on
    // the stack.
    fn parse(r: &mut Reader, mut list: Self) -> Result<PendingItems, ParseError> {
        let mut parents: Vec<Self> = Vec::new();
        loop {
            if list.remaining == 0 {
                match parents.pop() {
                    Some(mut parent) => {
                        parent.add(list.items.into_value());
                        list = parent;
                    }
                    None => return Ok(list.items),
                }
            } else {
                list.remaining -= 1;

                if let PendingItems::Anno(_, name) = &mut list.items {
                    *name = r.u16()?;
                }
                match ElementValue::header(r)? {
                    Header::Value(v) => list.add(v),
                    Header::List(child) => parents.push(std::mem::replace(&mut list, child)),
                }
            }
        }
    }
}
