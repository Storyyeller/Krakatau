use std::fs;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use anyhow::anyhow;
use anyhow::bail;
use anyhow::Context;
use anyhow::Result;

pub enum Writer<'a> {
    Dir(PathBuf),
    Jar(&'a Path, zip::ZipWriter<fs::File>),
    Merged(&'a Path, fs::File),
    Single(&'a Path, fs::File, bool),
}
impl<'a> Writer<'a> {
    pub fn new(p: &'a Path) -> Result<Self> {
        create_parent(p)?;
        if p.is_dir() {
            return Ok(Self::Dir(p.into()));
        }

        let f = create_file(p)?;

        let ext = p.extension().and_then(|s| s.to_str());
        Ok(if let Some(s) = ext {
            match s.to_ascii_lowercase().as_str() {
                "jar" | "zip" => Self::Jar(p, zip::ZipWriter::new(f)),
                "j" => Self::Merged(p, f),
                "class" => Self::Single(p, f, false),
                _ => bail!(
                    "Unsupported output extension {} for {}, expected directory, .jar, .zip, .j, or .class",
                    s,
                    p.display()
                ),
            }
        } else {
            bail!(
                "Unsupported output extension None for {}, expected directory, .jar, .zip, .j, or .class",
                p.display()
            )
        })
    }

    pub fn write(&mut self, name: Option<&str>, data: &[u8]) -> Result<()> {
        use Writer::*;
        match self {
            Dir(dir) => {
                let name = name.ok_or_else(|| {
                    anyhow!("Class has missing or invalid name. Try specifying a single file output name explicitly.")
                })?;
                if name.contains("..") {
                    panic!("Invalid path {}. Try outputting to a zip file instead.", name)
                } else {
                    let p = dir.join(name);
                    println!("Writing to {}", p.display());
                    create_parent(&p)?;
                    let mut f = create_file(&p)?;
                    f.write_all(data)?;
                }
            }
            Jar(p, zw) => {
                let name = name.ok_or_else(|| {
                    anyhow!("Class has missing or invalid name. Try specifying a single file output name explicitly.")
                })?;
                let options = zip::write::FileOptions::default()
                    .compression_method(zip::CompressionMethod::Stored)
                    .last_modified_time(zip::DateTime::default());

                zw.start_file(name, options)?;
                zw.write_all(data)?;
                println!("Wrote {} bytes to {} in {}", data.len(), name, p.display());
            }
            Merged(p, f) => {
                write(p, f, data)?;
            }
            Single(p, f, used) => {
                if *used {
                    bail!(
                        "Error: Attempting to write multiple classes to single file. Try outputting to a zip file instead."
                    )
                }
                write(p, f, data)?;
                *used = true;
            }
        }
        Ok(())
    }
}

fn create_parent(p: &Path) -> Result<()> {
    let parent = p
        .parent()
        .ok_or_else(|| anyhow!("Unable to determine parent directory for {}", p.display()))?;
    fs::create_dir_all(parent)
        .with_context(|| format!("Failed to create parent directory {} for {}", parent.display(), p.display()))
}

fn create_file(p: &Path) -> Result<std::fs::File> {
    fs::File::create(p).with_context(|| format!("Failed to create output file {}", p.display()))
}

fn write(p: &Path, f: &mut std::fs::File, data: &[u8]) -> Result<()> {
    f.write_all(data)
        .with_context(|| format!("Failed to write output to {}", p.display()))?;
    println!("Wrote {} bytes to {}", data.len(), p.display());
    Ok(())
}
