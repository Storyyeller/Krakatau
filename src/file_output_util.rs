use std::fs;
use std::io;
use std::io::Write;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use anyhow::anyhow;
use anyhow::bail;

pub enum Writer<'a> {
    Dir(PathBuf),
    // The file is listed before the TempFile so that it is closed before the TempFile's Drop tries to delete it.
    Jar(zip::ZipWriter<fs::File>, TempFile<'a>),
    Merged(fs::File, TempFile<'a>),
    Stdout(io::Stdout),
    Single(fs::File, TempFile<'a>),
}
impl<'a> Writer<'a> {
    pub fn new(p: &'a Path) -> Result<Self> {
        if p.is_dir() {
            return Ok(Self::Dir(p.into()));
        }

        // Check the extension before creating anything, so that a bad output path doesn't clobber an existing file.
        let ext = p.extension().and_then(|s| s.to_str()).map(str::to_ascii_lowercase);
        let ext = match ext.as_deref() {
            Some(s @ ("jar" | "zip" | "j" | "class")) => s,
            _ => bail!(
                "Unsupported output extension {} for {}, expected directory, .jar, .zip, .j, or .class",
                ext.as_deref().unwrap_or("None"),
                p.display()
            ),
        };

        create_parent(p)?;
        let (f, tf) = TempFile::new(p)?;
        Ok(match ext {
            "jar" | "zip" => Self::Jar(zip::ZipWriter::new(f), tf),
            "j" => Self::Merged(f, tf),
            _ => Self::Single(f, tf),
        })
    }

    pub fn write(&mut self, name: Option<&str>, data: &[u8]) -> Result<()> {
        use Writer::*;
        match self {
            Dir(dir) => {
                let name = name.ok_or_else(|| {
                    anyhow!("Class has missing or invalid name. Try specifying a single file output name explicitly.")
                })?;
                let p = dir.join(safe_relative_path(name)?);
                println!("Writing to {}", p.display());
                create_parent(&p)?;
                let mut f = create_file(&p)?;
                f.write_all(data)
                    .with_context(|| format!("Failed to write output to {}", p.display()))?;
            }
            Jar(zw, tf) => {
                let name = name.ok_or_else(|| {
                    anyhow!("Class has missing or invalid name. Try specifying a single file output name explicitly.")
                })?;
                // Jars are often extracted later, so don't create entries that would escape the extraction directory.
                safe_relative_path(name)?;
                let options = zip::write::SimpleFileOptions::default()
                    .compression_method(zip::CompressionMethod::Stored)
                    .last_modified_time(zip::DateTime::default());

                zw.start_file(name, options)?;
                zw.write_all(data)?;
                tf.written = true;
                println!("Wrote {} bytes to {} in {}", data.len(), name, tf.dest.display());
            }
            Merged(f, tf) => {
                write(tf, f, data)?;
            }
            Stdout(out) => {
                out.write_all(data).context("Failed to write output to stdout")?;
            }
            Single(f, tf) => {
                if tf.written {
                    bail!("Attempting to write multiple classes to single file. Try outputting to a zip file instead.")
                }
                write(tf, f, data)?;
            }
        }
        Ok(())
    }

    /// Moves the output into place. If this isn't called (e.g. because the run was aborted), an existing file at the
    /// output path is left untouched. The same is true if nothing was written, e.g. because every input failed.
    pub fn finish(self) -> Result<()> {
        use Writer::*;
        match self {
            Dir(_) | Stdout(_) => Ok(()),
            Jar(zw, tf) => {
                let f = zw
                    .finish()
                    .with_context(|| format!("Failed to write output to {}", tf.dest.display()))?;
                tf.commit(f)
            }
            Merged(f, tf) | Single(f, tf) => tf.commit(f),
        }
    }
}

/// A temporary file next to the output path, which replaces the output path on commit, and is deleted otherwise.
pub struct TempFile<'a> {
    dest: &'a Path,
    tmp: Option<PathBuf>,
    written: bool,
}
impl<'a> TempFile<'a> {
    fn new(dest: &'a Path) -> Result<(fs::File, Self)> {
        let fname = dest
            .file_name()
            .ok_or_else(|| anyhow!("Invalid output file name {}", dest.display()))?;
        let mut tmp_name = std::ffi::OsString::from(".");
        tmp_name.push(fname);
        tmp_name.push(format!(".{}.tmp", std::process::id()));
        let tmp = dest.with_file_name(tmp_name);

        let f = create_file(&tmp)?;
        Ok((
            f,
            Self {
                dest,
                tmp: Some(tmp),
                written: false,
            },
        ))
    }

    fn commit(mut self, f: fs::File) -> Result<()> {
        drop(f);
        if self.written {
            let tmp = self.tmp.take().unwrap();
            fs::rename(&tmp, self.dest)
                .with_context(|| format!("Failed to move temporary file {} to {}", tmp.display(), self.dest.display()))?;
        }
        Ok(())
    }
}
impl Drop for TempFile<'_> {
    fn drop(&mut self) {
        if let Some(tmp) = &self.tmp {
            let _ = fs::remove_file(tmp);
        }
    }
}

/// Class names come from the input, so refuse ones that could write outside the output directory,
/// such as absolute paths or paths containing "..". Backslashes are treated as separators as well,
/// since they are separators on Windows.
fn safe_relative_path(name: &str) -> Result<&Path> {
    let p = Path::new(name);
    let ok = name.split(['/', '\\']).all(|part| !matches!(part, "" | "." | ".."))
        && p.components().all(|c| matches!(c, Component::Normal(_)));
    if !ok {
        bail!(
            "Refusing to write {} because it is not a safe relative path. Try outputting to a single .j or .class file instead.",
            name
        );
    }
    Ok(p)
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

fn write(tf: &mut TempFile, f: &mut std::fs::File, data: &[u8]) -> Result<()> {
    f.write_all(data)
        .with_context(|| format!("Failed to write output to {}", tf.dest.display()))?;
    tf.written = true;
    println!("Wrote {} bytes to {}", data.len(), tf.dest.display());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_safe_relative_path() {
        for name in ["Foo.class", "a/b/Foo.j", "a..b.j", "...j", "a/...j", "$/é.class"] {
            assert!(safe_relative_path(name).is_ok(), "{}", name);
        }
        for name in [
            "/tmp/Foo.class",
            "//Foo.class",
            "a//b.class",
            "../Foo.class",
            "a/../../Foo.class",
            "a/./b.class",
            "./a.class",
            "a\\..\\..\\b.class",
            "\\Foo.class",
            "",
        ] {
            assert!(safe_relative_path(name).is_err(), "{}", name);
        }
    }
}
