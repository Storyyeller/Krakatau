use std::cmp::Eq;
use std::cmp::PartialEq;
use std::fmt::Debug;
use std::hash::Hash;
use std::hash::Hasher;

#[derive(Debug, Clone, Copy)]
pub struct Span<'a>(pub &'a str);
impl<'a> Span<'a> {
    pub fn of<T>(self, val: T) -> Spanned<'a, T> {
        Spanned { v: val, span: self }
    }
}

#[derive(Clone, Copy)]
pub struct Spanned<'a, T> {
    pub v: T,
    pub span: Span<'a>,
}
impl<T: Hash> Hash for Spanned<'_, T> {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.v.hash(state);
    }
}
impl<T: PartialEq> PartialEq for Spanned<'_, T> {
    fn eq(&self, other: &Self) -> bool {
        self.v == other.v
    }
}
impl<T: Eq> Eq for Spanned<'_, T> {}
impl<T: Debug> Debug for Spanned<'_, T> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.v.fmt(f)
    }
}

#[derive(Debug, Clone, Copy)]
pub struct SpanBounds {
    start: usize,
    end: usize,
}
impl SpanBounds {
    fn new(span: Span, source: &str) -> Self {
        let start = span.0.as_ptr() as usize - source.as_ptr() as usize;
        assert!(start <= source.len());
        let end = start + span.0.len();
        assert!(end <= source.len());
        Self { start, end }
    }
}

struct ErrorPrinter<'a> {
    fname: &'a str,
    lines: Vec<(Span<'a>, SpanBounds)>,
}
impl<'a> ErrorPrinter<'a> {
    fn new(fname: &'a str, source: &'a str) -> Self {
        // get line offsets
        // let mut pos = 0;
        let lines: Vec<_> = source
            .lines()
            .map(|line| {
                // println!("{line:?}");
                // let start = pos;
                // pos += line.len();
                // (start, pos)
                let span = Span(line);
                (span, SpanBounds::new(span, source))
            })
            .collect();
        // offsets.push(pos);

        // println!("offsets {:?}", lines);
        // for sb in offsets {
        //     println!("{:?}", &source[sb.start..sb.end]);
        // }
        // dbg!(lines.partition_point(|sb| sb.start <= 0));
        Self { fname, lines }
    }

    fn print(&self, is_first: bool, msg: &str, span: SpanBounds) {
        // const MAXLINELEN: usize = 80; // todo
        const TABWIDTH: usize = 8;

        let line_no = self.lines.partition_point(|(_, bounds)| bounds.end < span.start);
        let (Span(line), line_bounds) = self.lines[line_no];

        // convert byte positions to character positions (within the line)
        let mut start_ci = None;
        let mut end_ci = None;
        let mut ci = 0;
        // println!("{span:?}");
        for (byte_offset, c) in line.char_indices() {
            let bpos = line_bounds.start + byte_offset;
            // println!("{bpos} {ci} {c}");
            if span.start == bpos {
                start_ci = Some(ci);
            }
            if span.end == bpos {
                end_ci = Some(ci);
            }
            ci += if c == '\t' { TABWIDTH } else { 1 };
        }
        let start_ci = start_ci.unwrap_or(ci);
        let end_ci = end_ci.unwrap_or(ci);

        let underline: String = (0..ci + 1)
            .map(|i| {
                if i == start_ci {
                    '^'
                } else if i > start_ci && i < end_ci {
                    '~'
                } else {
                    ' '
                }
            })
            .collect();

        // if is_first {
        //     eprintln!("{}:{}:{} {}", self.fname, line_no + 1, start_ci + 1, msg);
        // } else {
        //     eprintln!("{}:{}:{} {}", self.fname, line_no + 1, start_ci + 1, msg);
        // }

        // todo - better line limit
        fn trim(s: &str) -> &str {
            &s[0..std::cmp::min(115, s.len())]
        }

        eprintln!("{}:{}:{} {}", self.fname, line_no + 1, start_ci + 1, msg);
        // eprintln!(
        //     "{}:{}:{} {} {}",
        //     self.fname,
        //     line_no + 1,
        //     start_ci + 1,
        //     msg,
        //     trim(&self.source[span.start..span.end])
        // );
        if is_first && line_no > 0 {
            eprintln!("{}", trim(self.lines[line_no - 1].0 .0));
        }
        eprintln!("{}", trim(line));
        eprintln!("{}", trim(&underline));
        if is_first && line_no + 1 < self.lines.len() {
            eprintln!("{}", trim(self.lines[line_no + 1].0 .0));
        }
    }
}

#[derive(Debug)]
pub struct Error(Vec<(String, SpanBounds)>);
impl Error {
    pub fn new(source: &str, pairs: Vec<(&str, Span<'_>)>) -> Self {
        Self(
            pairs
                .into_iter()
                .map(|(msg, span)| (msg.to_owned(), SpanBounds::new(span, source)))
                .collect(),
        )
    }

    pub fn display(&self, fname: &str, source: &str) {
        let printer = ErrorPrinter::new(fname, source);
        let mut is_first = true;
        for (msg, span) in self.0.iter() {
            printer.print(is_first, msg, *span);
            is_first = false;
        }
    }
}

#[derive(Clone, Copy)]
pub struct ErrorMaker<'a> {
    source: &'a str,
}
impl<'a> ErrorMaker<'a> {
    pub fn new(source: &'a str) -> Self {
        Self { source }
    }

    pub fn error1(&self, msg: &str, span: Span<'_>) -> Error {
        Error::new(self.source, vec![(msg, span)])
    }

    pub fn error2(&self, msg: &str, span: Span<'_>, msg2: &str, span2: Span<'_>) -> Error {
        Error::new(self.source, vec![(msg, span), (msg2, span2)])
    }

    pub fn err1<T>(&self, msg: &str, span: Span<'_>) -> Result<T, Error> {
        Err(self.error1(msg, span))
    }

    pub fn err2<T>(&self, msg: &str, span: Span<'_>, msg2: &str, span2: Span<'_>) -> Result<T, Error> {
        Err(self.error2(msg, span, msg2, span2))
    }

    pub fn error1str(&self, msg: String, span: Span<'_>) -> Error {
        Error(vec![(msg, SpanBounds::new(span, self.source))])
    }

    pub fn err1str<T>(&self, msg: String, span: Span<'_>) -> Result<T, Error> {
        Err(self.error1str(msg, span))
    }
}
