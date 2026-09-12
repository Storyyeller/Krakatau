use anyhow::anyhow;
use anyhow::bail;
use anyhow::Result;
use std::fs;
use std::io::Read;
use std::path::Path;

// pub fn read_files<E>(p: &Path, ext: &str, mut cb: impl FnMut(&[u8]) -> Result<(), E>) -> Result<(), E> {
pub fn read_files(p: &Path, ext: &str, mut cb: impl FnMut(&str, &[u8]) -> Result<()>) -> Result<()> {
    let input_ext = p
        .extension()
        .and_then(|s| s.to_str())
        .ok_or_else(|| anyhow!("Missing input file extension for '{}'", p.display()))?;
    let input_ext = input_ext.to_ascii_lowercase();

    if input_ext == ext {
        let data = fs::read(p)?;
        cb(&p.to_string_lossy(), &data)?;
    } else if input_ext == "jar" || input_ext == "zip" {
        let mut inbuf = Vec::new();
        let file = fs::File::open(p)?;
        let mut zip = zip::ZipArchive::new(file)?;
        let ext = format!(".{}", ext); // temp hack

        // Java doesn't check CRC32 when loading jar entries, so obfuscators sometimes
        // ship intentionally-invalid CRCs to break tooling. Match JVM behavior by
        // ignoring the CRC instead of rejecting the entry (see krakatau2#170).
        for i in 0..zip.len() {
            let read_opts = zip::read::ZipReadOptions::default().ignore_crc32(true);
            let mut file = zip.by_index_with_options(i, read_opts)?;
            // println!("found {} {:?} {} {}", i, file.name(), file.size(), file.compressed_size());

            let name = file.name().to_owned();
            if !name.trim_end_matches('/').ends_with(&ext) {
                continue;
            }

            inbuf.clear();
            inbuf.reserve(file.size() as usize);
            file.read_to_end(&mut inbuf)?;
            // println!("read {} bytes", inbuf.len());

            cb(&name, &inbuf)?;
        }
    } else {
        bail!("Unsupported input extension {}", input_ext)
    }
    Ok(())
}
