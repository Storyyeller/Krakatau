use std::fs;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

pub enum Writer {
    Dir(PathBuf),
    Jar(zip::ZipWriter<fs::File>),
    Merged(fs::File),
    Single(fs::File, bool),
}
impl Writer {
    pub fn new(p: &Path) -> Self {
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        if p.is_dir() {
            return Self::Dir(p.into());
        }

        let f = fs::File::create(p).unwrap();

        let ext = p.extension().and_then(|s| s.to_str());
        if let Some(s) = ext {
            match s.to_ascii_lowercase().as_str() {
                "jar" | "zip" => Self::Jar(zip::ZipWriter::new(f)),
                "j" => Self::Merged(f),
                "class" => Self::Single(f, false),
                _ => panic!("Unsupported output extension {}", s),
            }
        } else {
            panic!("Unsupported output extension {:?}", ext)
        }
    }

    pub fn write(&mut self, name: Option<&str>, data: &[u8]) {
        use Writer::*;
        match self {
            Dir(dir) => {
                let name =
                    name.expect("Class has missing or invalid name. Try specifying a single file output name explicitly.");
                if name.contains("..") {
                    panic!("Invalid path {}. Try outputting to a zip file instead.", name)
                } else {
                    let p = dir.join(name);
                    println!("Writing to {}", p.display());
                    fs::create_dir_all(p.parent().unwrap())
                        .expect("Unable to create directory. Try outputting to a zip file instead");
                    let mut f = fs::File::create(p).expect("Unable to create file. Try outputting to a zip file instead");
                    f.write_all(data).unwrap();
                }
            }
            Jar(zw) => {
                let name =
                    name.expect("Class has missing or invalid name. Try specifying a single file output name explicitly.");
                let options = zip::write::FileOptions::default()
                    .compression_method(zip::CompressionMethod::Stored)
                    .last_modified_time(zip::DateTime::default());

                zw.start_file(name, options).unwrap();
                zw.write_all(data).unwrap();
            }
            Merged(f) => {
                f.write_all(data).unwrap();
            }
            Single(f, used) => {
                if *used {
                    panic!(
                        "Error: Attempting to write multiple classes to single file. Try outputting to a zip file instead."
                    )
                }
                f.write_all(data).unwrap();
                *used = true;
            }
        }
    }
}
