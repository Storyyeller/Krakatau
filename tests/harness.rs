// Data-driven tests. Run with BLESS=1 to update the expected output files.
//
// asm/good, examples: must assemble; sha256 of each output class is checked against asm/hashes.txt,
//     and roundtrip disassembly must reassemble to identical bytes.
// asm/bad: must fail to assemble; the error message is checked against foo.stderr.
// dis: sha256 of the normal disassembly of each class is checked against dis/hashes.txt, normal
//     disassembly must reassemble without error, and roundtrip disassembly must reassemble to
//     identical bytes.
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs;
use std::io::Cursor;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use libtest_mimic::Arguments;
use libtest_mimic::Failed;
use libtest_mimic::Trial;
use sha2::Digest;
use sha2::Sha256;

use krakatau2::AssemblerOptions;
use krakatau2::DisassemblerOptions;
use krakatau2::ParserOptions;

const IGNORED_BAD: &[&str] = &[
    // Accepted by v2 but rejected by v1. v2 may be changed to reject them.
    "code_in_record",
    "record_in_code",
    // Accepted by the v2 assembler. The CLI only fails afterwards because the class name can't be
    // used as an output file name.
    "invalid_unicode_name",
    "name0",
];
// The only test inputs with short code attributes (version < 45.3).
const SHORT_CODE: &[&str] = &["OldVersionTest"];

const DEFAULT_PARSE: ParserOptions = ParserOptions {
    no_short_code_attr: false,
};

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).to_owned()
}

fn bless() -> bool {
    std::env::var_os("BLESS").is_some()
}

fn files_with_ext(dir: &Path, exts: &[&str], recursive: bool) -> Vec<PathBuf> {
    let mut out = Vec::new();
    for entry in fs::read_dir(dir).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            if recursive {
                out.extend(files_with_ext(&path, exts, recursive));
            }
        } else if path.extension().is_some_and(|e| exts.iter().any(|x| e == *x)) {
            out.push(path);
        }
    }
    out.sort();
    out
}

fn rel_name(path: &Path, base: &Path) -> String {
    path.strip_prefix(base)
        .unwrap()
        .with_extension("")
        .to_str()
        .unwrap()
        .replace('\\', "/")
}

// Like Trial::test, but run on a 1MB stack, the smallest default main thread stack on common platforms (Windows),
// since the CLI runs on the main thread. This catches both unbounded recursion and excessively large stack frames.
fn trial(name: String, f: impl FnOnce() -> Result<(), Failed> + Send + 'static) -> Trial {
    Trial::test(name, move || {
        let child = std::thread::Builder::new().stack_size(1024 * 1024).spawn(f).unwrap();
        child.join().unwrap_or_else(|e| std::panic::resume_unwind(e))
    })
}

///////////////////////////////////////////////////////////////////////////////////////////////////
// Port of the v1 test preprocessor. Files starting with "###preprocess###" may contain
// "###range(args):pattern###", which is replaced by pattern repeated for each i in range(args),
// with "{}" replaced by i and "{ip1}" by i + 1.
const PP_MARKER: &str = "###preprocess###\n";
fn preprocess(source: &str) -> String {
    let Some(mut rest) = source.strip_prefix(PP_MARKER) else {
        return source.to_owned();
    };

    let mut out = String::new();
    while let Some(start) = rest.find("###range") {
        out.push_str(&rest[..start]);
        let end = start + 3 + rest[start + 3..].find("###").expect("unterminated ###range");
        let (args, pattern) = rest[start..end]
            .strip_prefix("###range(")
            .and_then(|s| s.split_once("):"))
            .expect("malformed ###range");

        let args: Vec<i64> = args
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(|s| s.parse().unwrap())
            .collect();
        let (lo, hi, step) = match args[..] {
            [hi] => (0, hi, 1),
            [lo, hi] => (lo, hi, 1),
            [lo, hi, step] => (lo, hi, step),
            _ => panic!("bad ###range args {:?}", args),
        };
        assert!(step > 0);
        for i in (lo..hi).step_by(step as usize) {
            format_pattern(&mut out, pattern, i);
        }
        rest = &rest[end + 3..];
    }
    out.push_str(rest);
    out
}

// Subset of Python's str.format(i, ip1=i+1)
fn format_pattern(out: &mut String, pattern: &str, i: i64) {
    let mut chars = pattern.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '{' if chars.peek() == Some(&'{') => {
                chars.next();
                out.push('{');
            }
            '}' if chars.peek() == Some(&'}') => {
                chars.next();
                out.push('}');
            }
            '{' => {
                let field: String = chars.by_ref().take_while(|&c| c != '}').collect();
                match field.as_str() {
                    "" => out.push_str(&i.to_string()),
                    "ip1" => out.push_str(&(i + 1).to_string()),
                    _ => panic!("unsupported format field {{{}}}", field),
                }
            }
            '}' => panic!("unmatched }} in pattern"),
            c => out.push(c),
        }
    }
}

///////////////////////////////////////////////////////////////////////////////////////////////////
fn diff(expected: &str, actual: &str) -> String {
    const MAX_LINES: usize = 100;
    let diff = similar::TextDiff::from_lines(expected, actual)
        .unified_diff()
        .header("expected", "actual")
        .to_string();
    let mut lines: Vec<&str> = diff.lines().collect();
    if lines.len() > MAX_LINES {
        let extra = lines.len() - MAX_LINES;
        lines.truncate(MAX_LINES);
        return format!("{}\n... {} more lines", lines.join("\n"), extra);
    }
    lines.join("\n")
}

fn check_snapshot(path: &Path, actual: &str) -> Result<(), Failed> {
    let expected = fs::read_to_string(path).ok();
    if expected.as_deref() == Some(actual) {
        return Ok(());
    }
    if bless() {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, actual).unwrap();
        return Ok(());
    }
    match expected {
        None => Err(format!("missing {}, run with BLESS=1 to create it", path.display()).into()),
        Some(expected) => Err(format!(
            "output does not match {} (run with BLESS=1 to update)\n{}",
            path.display(),
            diff(&expected, actual)
        )
        .into()),
    }
}

fn assemble(source: &str) -> Result<Vec<(Option<String>, Vec<u8>)>, Failed> {
    krakatau2::assemble(source, AssemblerOptions {}).map_err(|err| err.format("<input>", source).into())
}

fn disassemble(data: &[u8], parse_opts: ParserOptions, roundtrip: bool) -> Result<String, Failed> {
    let (_, out) = krakatau2::disassemble(data, parse_opts, DisassemblerOptions { roundtrip })
        .map_err(|err| format!("disassembly failed: {:?}", err))?;
    Ok(String::from_utf8(out).unwrap())
}

// Roundtrip disassembly must reassemble to identical bytes.
fn check_roundtrip(data: &[u8], parse_opts: ParserOptions) -> Result<(), Failed> {
    let text = disassemble(data, parse_opts, true)?;
    let classes = assemble(&text).map_err(|e| format!("reassembly failed:\n{}", e.message().unwrap_or("")))?;
    let [(_, new_data)] = &classes[..] else {
        return Err(format!("reassembly produced {} classes", classes.len()).into());
    };
    if new_data == data {
        return Ok(());
    }
    let new_text = disassemble(new_data, parse_opts, true)?;
    Err(format!(
        "reassembled bytes differ ({} vs {} bytes), roundtrip disassembly diff:\n{}",
        data.len(),
        new_data.len(),
        diff(&text, &new_text)
    )
    .into())
}

fn read_classes(path: &Path) -> Vec<(String, Vec<u8>)> {
    let data = fs::read(path).unwrap();
    if path.extension().unwrap() == "class" {
        return vec![(path.file_name().unwrap().to_str().unwrap().to_owned(), data)];
    }

    let mut zip = zip::ZipArchive::new(Cursor::new(data)).unwrap();
    let mut out = Vec::new();
    for i in 0..zip.len() {
        let mut file = zip.by_index(i).unwrap();
        if file.is_file() && file.name().ends_with(".class") {
            let mut buf = Vec::new();
            file.read_to_end(&mut buf).unwrap();
            out.push((file.name().to_owned(), buf));
        }
    }
    out
}

///////////////////////////////////////////////////////////////////////////////////////////////////
// Expected sha256 hashes of test output, stored as lines of "<test>#<class index> <hash>"
struct Hashes {
    path: PathBuf,
    expected: BTreeMap<String, Vec<String>>,
    actual: Mutex<BTreeMap<String, Vec<String>>>,
    names: Mutex<BTreeSet<String>>,
}
impl Hashes {
    fn load(path: PathBuf) -> Self {
        let mut expected: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for line in fs::read_to_string(&path).unwrap_or_default().lines() {
            let (key, hash) = line.split_once(' ').unwrap();
            let (name, _) = key.rsplit_once('#').unwrap();
            expected.entry(name.to_owned()).or_default().push(hash.to_owned());
        }
        Self {
            path,
            expected,
            actual: Mutex::new(BTreeMap::new()),
            names: Mutex::new(BTreeSet::new()),
        }
    }

    // Record that a test exists, so that its hashes are kept when blessing with a filter.
    fn register(&self, name: &str) {
        self.names.lock().unwrap().insert(name.to_owned());
    }

    // On mismatch, `dump` is called to write a readable form of the output to the given directory.
    fn check(&self, name: &str, outputs: &[&[u8]], dump: impl FnOnce(&Path)) -> Result<(), Failed> {
        let actual: Vec<String> = outputs
            .iter()
            .map(|data| Sha256::digest(data).iter().map(|b| format!("{:02x}", b)).collect())
            .collect();
        let expected = self.expected.get(name);
        let ok = expected == Some(&actual);
        self.actual.lock().unwrap().insert(name.to_owned(), actual);
        if ok || bless() {
            return Ok(());
        }

        // Dump the new output so it can be compared with the output of an older version.
        let dump_dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join("output").join(name);
        let _ = fs::remove_dir_all(&dump_dir);
        fs::create_dir_all(&dump_dir).unwrap();
        dump(&dump_dir);

        Err(match expected {
            None => format!("no hashes for {} in {}, run with BLESS=1 to add them", name, self.path.display()),
            Some(_) => format!(
                "output hashes differ from {} (run with BLESS=1 to update)\nnew output written to {}",
                self.path.display(),
                dump_dir.display()
            ),
        }
        .into())
    }

    // Rewrite the hash file, keeping old entries for tests that exist but weren't run (e.g. due to filtering).
    fn save(&self) {
        let names = self.names.lock().unwrap();
        let mut merged = self.expected.clone();
        merged.retain(|name, _| names.contains(name));
        merged.extend(self.actual.lock().unwrap().clone());

        let mut out = String::new();
        for (name, hashes) in merged {
            for (i, hash) in hashes.iter().enumerate() {
                out += &format!("{}#{} {}\n", name, i, hash);
            }
        }
        if fs::read_to_string(&self.path).ok().as_deref() != Some(&out) {
            fs::write(&self.path, out).unwrap();
        }
    }
}

///////////////////////////////////////////////////////////////////////////////////////////////////
fn asm_good_tests(trials: &mut Vec<Trial>, hashes: &Arc<Hashes>, dir: &Path, prefix: &str) {
    for path in files_with_ext(dir, &["j"], true) {
        let name = format!("{}/{}", prefix, rel_name(&path, dir));
        hashes.register(&name);

        let hashes = hashes.clone();
        let (p, n) = (path.clone(), name.clone());
        trials.push(trial(format!("{}/hash", name), move || {
            let classes = assemble(&preprocess(&fs::read_to_string(&p).unwrap()))?;
            let outputs: Vec<&[u8]> = classes.iter().map(|(_, data)| &data[..]).collect();
            hashes.check(&n, &outputs, |dir| {
                for (i, data) in outputs.iter().enumerate() {
                    let text = disassemble(data, DEFAULT_PARSE, true).unwrap_or_else(|e| format!("{:?}\n", e));
                    fs::write(dir.join(format!("{}.j", i)), text).unwrap();
                }
            })
        }));
        trials.push(trial(format!("{}/roundtrip", name), move || {
            for (_, data) in assemble(&preprocess(&fs::read_to_string(&path).unwrap()))? {
                check_roundtrip(&data, DEFAULT_PARSE)?;
            }
            Ok(())
        }));
    }
}

fn asm_bad_tests(trials: &mut Vec<Trial>, dir: &Path) {
    for path in files_with_ext(dir, &["j"], false) {
        let stem = rel_name(&path, dir);
        let display_name = format!("asm/bad/{}.j", stem);
        let stderr_path = path.with_extension("stderr");
        let trial = trial(format!("asm_bad/{}", stem), move || {
            let source = preprocess(&fs::read_to_string(&path).unwrap());
            match krakatau2::assemble(&source, AssemblerOptions {}) {
                Ok(_) => Err("assembly unexpectedly succeeded".into()),
                Err(err) => check_snapshot(&stderr_path, &err.format(&display_name, &source)),
            }
        });
        trials.push(trial.with_ignored_flag(IGNORED_BAD.contains(&stem.as_str())));
    }
}

fn dis_tests(trials: &mut Vec<Trial>, hashes: &Arc<Hashes>, dir: &Path) {
    for path in files_with_ext(dir, &["class", "jar"], false) {
        let stem = rel_name(&path, dir);
        let name = format!("dis/{}", stem);
        hashes.register(&name);

        let hashes = hashes.clone();
        let p = path.clone();
        trials.push(trial(format!("{}/hash", name), move || {
            let mut texts = Vec::new();
            for (_, data) in read_classes(&p) {
                texts.push(disassemble(&data, DEFAULT_PARSE, false)?);
            }
            let outputs: Vec<&[u8]> = texts.iter().map(|text| text.as_bytes()).collect();
            hashes.check(&name, &outputs, |dir| {
                for (i, text) in texts.iter().enumerate() {
                    fs::write(dir.join(format!("{}.j", i)), text).unwrap();
                }
            })
        }));

        let p = path.clone();
        trials.push(trial(format!("dis/{}/reassemble", stem), move || {
            for (fname, data) in read_classes(&p) {
                assemble(&disassemble(&data, DEFAULT_PARSE, false)?)
                    .map_err(|e| format!("{}: reassembly failed:\n{}", fname, e.message().unwrap_or("")))?;
            }
            Ok(())
        }));

        let p = path.clone();
        trials.push(trial(format!("dis/{}/roundtrip", stem), move || {
            for (fname, data) in read_classes(&p) {
                check_roundtrip(&data, DEFAULT_PARSE).map_err(|e| format!("{}: {}", fname, e.message().unwrap_or("")))?;
            }
            Ok(())
        }));

        if SHORT_CODE.contains(&stem.as_str()) {
            trials.push(trial(format!("dis/{}/roundtrip_no_short_code", stem), move || {
                for (_, data) in read_classes(&path) {
                    check_roundtrip(
                        &data,
                        ParserOptions {
                            no_short_code_attr: true,
                        },
                    )?;
                }
                Ok(())
            }));
        }
    }
}

fn main() {
    let args = Arguments::from_args();
    let data = root().join("tests").join("data");
    let asm_hashes = Arc::new(Hashes::load(data.join("asm").join("hashes.txt")));
    let dis_hashes = Arc::new(Hashes::load(data.join("dis").join("hashes.txt")));

    let mut trials = Vec::new();
    asm_good_tests(&mut trials, &asm_hashes, &data.join("asm").join("good"), "asm_good");
    asm_good_tests(&mut trials, &asm_hashes, &root().join("examples"), "examples");
    asm_bad_tests(&mut trials, &data.join("asm").join("bad"));
    dis_tests(&mut trials, &dis_hashes, &data.join("dis"));

    let conclusion = libtest_mimic::run(&args, trials);
    if bless() {
        asm_hashes.save();
        dis_hashes.save();
    }
    conclusion.exit();
}
