use std::{env, fs, path::PathBuf, process::ExitCode};
use tvlost_patcher::{PATCH, apply, hex, metadata, sha256, write_new};

fn run() -> Result<(), String> {
    let args: Vec<_> = env::args_os().skip(1).collect();
    if args.first().is_some_and(|x| x == "--help" || x == "-h") {
        println!(
            "Tvlost Patcher {}\n\nАвтоматически: tvlost-patcher.exe\nС путями:      tvlost-patcher.exe <tvlost.exe> [выходной.exe]\nПроверка:      tvlost-patcher.exe --check <файл.exe>\n\nБез аргументов ищет tvlost.exe рядом с самим патчером.\nБез имени выхода создаётся tvlost_rus_new.exe рядом с оригиналом.\nОригинал сохраняется. Существующие файлы не перезаписываются.\nПатч встроен; Интернет и установленные библиотеки не нужны.",
            env!("CARGO_PKG_VERSION")
        );
        return Ok(());
    }
    if args.first().is_some_and(|x| x == "--check") {
        if args.len() != 2 {
            return Err("Использование: tvlost-patcher.exe --check <файл.exe>".into());
        }
        let path = PathBuf::from(&args[1]);
        let bytes = fs::read(&path).map_err(|e| format!("{}: {e}", path.display()))?;
        let hash = sha256(&bytes);
        let m = metadata(PATCH)?;
        println!("SHA-256: {}", hex(&hash));
        if bytes.len() == m.source_len && hash == m.source_hash {
            println!("Подходящий оригинальный EXE (2007).");
            return Ok(());
        }
        if bytes.len() == m.target_len && hash == m.target_hash {
            println!("Эталонный пропатченный EXE с переводом.");
            return Ok(());
        }
        return Err("Неизвестная версия EXE".into());
    }
    if args.len() > 2 {
        return Err("Использование: tvlost-patcher.exe <tvlost.exe> [выходной.exe]\nСправка: tvlost-patcher.exe --help".into());
    }
    let input = if let Some(path) = args.first() {
        PathBuf::from(path)
    } else {
        let executable = env::current_exe()
            .map_err(|e| format!("Не удалось определить расположение патчера: {e}"))?;
        executable.with_file_name("tvlost.exe")
    };
    let output = args
        .get(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| input.with_file_name("tvlost_rus_new.exe"));
    let source =
        fs::read(&input).map_err(|e| format!("Не удалось прочитать {}: {e}", input.display()))?;
    let result = apply(&source, PATCH)?;
    write_new(&output, &result)?;
    println!(
        "Готово: {}\nSHA-256: {}\nИсходный файл сохранён.",
        output.display(),
        hex(&sha256(&result))
    );
    Ok(())
}
fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("Ошибка: {e}");
            ExitCode::FAILURE
        }
    }
}
