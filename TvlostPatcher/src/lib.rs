use std::fmt::Write as _;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;

pub const PATCH: &[u8] = include_bytes!("../patch/tvlost-2007-to-ru.tvp");
const MAGIC: &[u8; 8] = b"TVLPAT01";

pub fn sha256(data: &[u8]) -> [u8; 32] {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut h = [
        0x6a09e667u32,
        0xbb67ae85,
        0x3c6ef372,
        0xa54ff53a,
        0x510e527f,
        0x9b05688c,
        0x1f83d9ab,
        0x5be0cd19,
    ];
    let mut padded = data.to_vec();
    padded.push(0x80);
    while padded.len() % 64 != 56 {
        padded.push(0);
    }
    padded.extend_from_slice(&(data.len() as u64 * 8).to_be_bytes());
    for block in padded.chunks_exact(64) {
        let mut w = [0u32; 64];
        for (i, chunk) in block.chunks_exact(4).enumerate() {
            w[i] = u32::from_be_bytes(chunk.try_into().unwrap());
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh] = h;
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ (!e & g);
            let t1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        for (dst, value) in h.iter_mut().zip([a, b, c, d, e, f, g, hh]) {
            *dst = dst.wrapping_add(value);
        }
    }
    let mut result = [0; 32];
    for (chunk, value) in result.chunks_exact_mut(4).zip(h) {
        chunk.copy_from_slice(&value.to_be_bytes());
    }
    result
}

pub fn hex(hash: &[u8]) -> String {
    let mut result = String::with_capacity(hash.len() * 2);
    for b in hash {
        write!(result, "{b:02x}").unwrap();
    }
    result
}

#[derive(Debug)]
pub struct Metadata {
    pub source_len: usize,
    pub target_len: usize,
    pub source_hash: [u8; 32],
    pub target_hash: [u8; 32],
    pub ranges: u32,
}

fn take<'a>(bytes: &'a [u8], pos: &mut usize, len: usize) -> Result<&'a [u8], String> {
    let end = pos.checked_add(len).ok_or("Переполнение размера патча")?;
    let result = bytes.get(*pos..end).ok_or("Патч обрезан")?;
    *pos = end;
    Ok(result)
}
fn number(bytes: &[u8], pos: &mut usize) -> Result<usize, String> {
    usize::try_from(u64::from_le_bytes(take(bytes, pos, 8)?.try_into().unwrap()))
        .map_err(|_| "Размер не поддерживается".into())
}

pub fn metadata(patch: &[u8]) -> Result<Metadata, String> {
    if patch.len() < 124 {
        return Err("Патч обрезан".into());
    }
    let checksum_offset = patch.len() - 32;
    if sha256(&patch[..checksum_offset]) != patch[checksum_offset..] {
        return Err("Повреждена контрольная сумма патча".into());
    }
    let mut pos = 0;
    if take(patch, &mut pos, 8)? != MAGIC {
        return Err("Неизвестный формат патча".into());
    }
    let source_len = number(patch, &mut pos)?;
    let target_len = number(patch, &mut pos)?;
    // This format is intentionally limited to small game executables.
    if source_len > 64 * 1024 * 1024 || target_len > 64 * 1024 * 1024 {
        return Err("EXE превышает лимит 64 МиБ".into());
    }
    let source_hash = take(patch, &mut pos, 32)?.try_into().unwrap();
    let target_hash = take(patch, &mut pos, 32)?.try_into().unwrap();
    let ranges = u32::from_le_bytes(take(patch, &mut pos, 4)?.try_into().unwrap());
    Ok(Metadata {
        source_len,
        target_len,
        source_hash,
        target_hash,
        ranges,
    })
}

pub fn apply(source: &[u8], patch: &[u8]) -> Result<Vec<u8>, String> {
    let meta = metadata(patch)?;
    let hash = sha256(source);
    if source.len() == meta.target_len && hash == meta.target_hash {
        return Err("Этот EXE уже пропатчен".into());
    }
    if source.len() != meta.source_len || hash != meta.source_hash {
        return Err(format!(
            "Не подходит исходный EXE. Нужен оригинальный tvlost.exe 2007 года.\nОжидается SHA-256: {}\nПолучен SHA-256:   {}",
            hex(&meta.source_hash),
            hex(&hash)
        ));
    }
    let mut result = source.to_vec();
    result.resize(meta.target_len, 0);
    let body = &patch[..patch.len() - 32];
    let mut pos = 92;
    let mut last_end = 0;
    for _ in 0..meta.ranges {
        let offset = number(body, &mut pos)?;
        let length = number(body, &mut pos)?;
        let end = offset.checked_add(length).ok_or("Переполнение диапазона")?;
        if length == 0 || offset < last_end || end > result.len() {
            return Err("Недопустимый диапазон патча".into());
        }
        result[offset..end].copy_from_slice(take(body, &mut pos, length)?);
        last_end = end;
    }
    if pos != body.len() {
        return Err("Лишние данные в патче".into());
    }
    if sha256(&result) != meta.target_hash {
        return Err("Результат не совпадает с эталонным EXE; запись отменена".into());
    }
    Ok(result)
}

pub fn build_patch(source: &[u8], target: &[u8]) -> Result<Vec<u8>, String> {
    if source.len() > 64 * 1024 * 1024 || target.len() > 64 * 1024 * 1024 {
        return Err("EXE превышает лимит 64 МиБ".into());
    }
    let changed = |i: usize| source.get(i) != target.get(i);
    let mut ranges = Vec::new();
    let mut i = 0;
    while i < target.len() {
        if !changed(i) {
            i += 1;
            continue;
        }
        let start = i;
        let mut end = i + 1;
        i += 1;
        while i < target.len() {
            if changed(i) {
                end = i + 1;
            } else if i - end >= 16 {
                break;
            }
            i += 1;
        }
        ranges.push((start, end));
    }
    let mut patch = Vec::new();
    patch.extend_from_slice(MAGIC);
    patch.extend_from_slice(&(source.len() as u64).to_le_bytes());
    patch.extend_from_slice(&(target.len() as u64).to_le_bytes());
    patch.extend_from_slice(&sha256(source));
    patch.extend_from_slice(&sha256(target));
    patch.extend_from_slice(&(ranges.len() as u32).to_le_bytes());
    for (start, end) in ranges {
        patch.extend_from_slice(&(start as u64).to_le_bytes());
        patch.extend_from_slice(&((end - start) as u64).to_le_bytes());
        patch.extend_from_slice(&target[start..end]);
    }
    let checksum = sha256(&patch);
    patch.extend_from_slice(&checksum);
    Ok(patch)
}

pub fn write_new(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|e| {
            format!(
                "Не удалось создать {}: {e}. Существующие файлы не перезаписываются.",
                path.display()
            )
        })?;
    let written = (|| -> Result<(), String> {
        file.write_all(bytes)
            .and_then(|_| file.sync_all())
            .map_err(|e| format!("Ошибка записи: {e}"))?;
        let saved =
            fs::read(path).map_err(|e| format!("Ошибка проверки записанного файла: {e}"))?;
        if saved != bytes {
            return Err("Проверка записанного файла не прошла".into());
        }
        Ok(())
    })();
    drop(file);
    if written.is_err() {
        let _ = fs::remove_file(path);
    }
    written
}

#[cfg(test)]
mod tests {
    use super::*;
    fn resign(patch: &mut Vec<u8>) {
        patch.truncate(patch.len() - 32);
        let checksum = sha256(patch);
        patch.extend_from_slice(&checksum);
    }
    #[test]
    fn rejects_invalid_ranges_even_with_valid_checksum() {
        let patch = build_patch(b"abc", b"XYZ").unwrap();
        let mut outside = patch.clone();
        outside[92..100].copy_from_slice(&u64::MAX.to_le_bytes());
        resign(&mut outside);
        assert!(apply(b"abc", &outside).is_err());
        let mut zero_length = patch.clone();
        zero_length[100..108].copy_from_slice(&0u64.to_le_bytes());
        resign(&mut zero_length);
        assert!(apply(b"abc", &zero_length).is_err());
        let mut extra = patch.clone();
        extra.insert(extra.len() - 32, 1);
        resign(&mut extra);
        assert!(apply(b"abc", &extra).unwrap_err().contains("Лишние"));
        let mut wrong_result = patch;
        wrong_result[108] ^= 1;
        resign(&mut wrong_result);
        assert!(
            apply(b"abc", &wrong_result)
                .unwrap_err()
                .contains("эталонным")
        );
    }
    #[test]
    fn standard_sha_vectors() {
        assert_eq!(
            hex(&sha256(b"")),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            hex(&sha256(b"abc")),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_eq!(
            hex(&sha256(&vec![b'a'; 1_000_000])),
            "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0"
        );
    }
    #[test]
    fn delta_roundtrip_boundaries() {
        for (a, b) in [
            (vec![], vec![]),
            (vec![], vec![1, 2]),
            (vec![1, 2], vec![]),
            (vec![1; 128], vec![2; 128]),
            (vec![1; 128], vec![1; 128]),
            (vec![1; 128], vec![1; 129]),
        ] {
            let p = build_patch(&a, &b).unwrap();
            if a == b {
                assert!(apply(&a, &p).unwrap_err().contains("уже"));
            } else {
                assert_eq!(apply(&a, &p).unwrap(), b);
            }
        }
    }
    #[test]
    fn rejects_wrong_source_and_corrupt_patch() {
        let p = build_patch(b"abc", b"xyz123").unwrap();
        assert!(apply(b"abd", &p).is_err());
        for n in 0..p.len() {
            assert!(metadata(&p[..n]).is_err());
        }
        let mut p = p;
        p[92] ^= 1;
        assert!(apply(b"abc", &p).is_err());
    }
    #[test]
    fn embedded_metadata_matches_release() {
        let m = metadata(PATCH).unwrap();
        assert_eq!(m.source_len, 1003520);
        assert_eq!(m.target_len, 1007616);
        assert_eq!(
            hex(&m.source_hash),
            "4e83a346cbec2cfb75e63568244deedb12ffe1cc22ba5ae5d6803ad7f55ffd2e"
        );
        assert_eq!(
            hex(&m.target_hash),
            "d1129cfde8c449cc4ffd5edcae6f176f0bb8160cdddd193ab60294931ce48239"
        );
    }
}
