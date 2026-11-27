use std::{env, fs, path::PathBuf, process::ExitCode};
use tvlost_patcher::{build_patch, metadata, write_new};
fn run() -> Result<(), String> {
    let args: Vec<_> = env::args_os().skip(1).map(PathBuf::from).collect();
    if args.len() != 3 {
        return Err("Использование: make-patch <оригинал.exe> <эталон.exe> <новый.tvp>".into());
    }
    let source = fs::read(&args[0]).map_err(|e| e.to_string())?;
    let target = fs::read(&args[1]).map_err(|e| e.to_string())?;
    let patch = build_patch(&source, &target)?;
    write_new(&args[2], &patch)?;
    println!(
        "Диапазонов: {}. Размер дельты: {} байт.",
        metadata(&patch)?.ranges,
        patch.len()
    );
    Ok(())
}
fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("{e}");
            ExitCode::FAILURE
        }
    }
}
