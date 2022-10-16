#[derive(Debug)]
pub struct ParseError(pub &'static str);
impl ParseError {
    pub fn s<T>(s: &'static str) -> Result<T, ParseError> {
        Err(ParseError(s))
    }
}

#[derive(Debug, Clone)]
pub(super) struct Reader<'a>(pub(super) &'a [u8]);
impl<'a> Reader<'a> {
    pub(super) fn get(&mut self, n: usize) -> Result<&'a [u8], ParseError> {
        if n > self.0.len() {
            return ParseError::s("end of data");
        }

        let (first, rest) = self.0.split_at(n);
        self.0 = rest;
        Ok(first)
    }

    pub(super) fn u8(&mut self) -> Result<u8, ParseError> {
        Ok(self.get(1)?[0])
    }
    pub(super) fn u16(&mut self) -> Result<u16, ParseError> {
        Ok(u16::from_be_bytes(self.get(2)?.try_into().unwrap()))
    }
    pub(super) fn u32(&mut self) -> Result<u32, ParseError> {
        Ok(u32::from_be_bytes(self.get(4)?.try_into().unwrap()))
    }
    pub(super) fn u64(&mut self) -> Result<u64, ParseError> {
        Ok(u64::from_be_bytes(self.get(8)?.try_into().unwrap()))
    }

    pub(super) fn i8(&mut self) -> Result<i8, ParseError> {
        Ok(self.u8()? as i8)
    }
    pub(super) fn i16(&mut self) -> Result<i16, ParseError> {
        Ok(self.u16()? as i16)
    }
    pub(super) fn i32(&mut self) -> Result<i32, ParseError> {
        Ok(self.u32()? as i32)
    }

    pub(super) fn parse_list<T>(
        &mut self,
        mut cb: impl FnMut(&mut Self) -> Result<T, ParseError>,
    ) -> Result<Vec<T>, ParseError> {
        let count = self.u16()? as usize;
        let mut vals = Vec::with_capacity(count);
        for _ in 0..count {
            vals.push(cb(self)?);
        }
        Ok(vals)
    }
    pub(super) fn parse_list_bytelen<T>(
        &mut self,
        mut cb: impl FnMut(&mut Self) -> Result<T, ParseError>,
    ) -> Result<Vec<T>, ParseError> {
        let count = self.u8()? as usize;
        let mut vals = Vec::with_capacity(count);
        for _ in 0..count {
            vals.push(cb(self)?);
        }
        Ok(vals)
    }
}
