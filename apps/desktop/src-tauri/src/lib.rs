use serde_json::{json, Value};
use std::{
    collections::HashMap,
    env,
    io::{BufRead, BufReader, Write},
    path::PathBuf,
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        atomic::{AtomicU64, Ordering},
        mpsc, Arc, Mutex,
    },
    thread,
    time::Duration,
};
use tauri::{AppHandle, Emitter, Manager, State};

type EngineResponse = Result<Value, Value>;
type Pending = Arc<Mutex<HashMap<String, mpsc::Sender<EngineResponse>>>>;

struct EngineBridge {
    child: Mutex<Child>,
    input: Arc<Mutex<ChildStdin>>,
    pending: Pending,
    next_id: AtomicU64,
}

impl EngineBridge {
    fn spawn(app: AppHandle) -> Result<Self, String> {
        let mut command = engine_command()?;
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| format!("Cannot start the organizing engine: {error}"))?;

        let input = child.stdin.take().ok_or("Cannot connect to organizing engine input")?;
        let output = child.stdout.take().ok_or("Cannot connect to organizing engine output")?;
        let stderr = child.stderr.take().ok_or("Cannot connect to organizing engine log")?;
        let pending: Pending = Arc::new(Mutex::new(HashMap::new()));
        let reader_pending = Arc::clone(&pending);

        thread::Builder::new()
            .name("organize-engine-output".into())
            .spawn(move || {
                for line in BufReader::new(output).lines() {
                    let Ok(line) = line else { break };
                    let Ok(message) = serde_json::from_str::<Value>(&line) else {
                        eprintln!("invalid engine message: {line}");
                        continue;
                    };
                    if message.get("event").is_some() {
                        let _ = app.emit("engine-event", &message);
                        continue;
                    }
                    let Some(id) = message.get("id").and_then(Value::as_str) else {
                        continue;
                    };
                    let sender = reader_pending
                        .lock()
                        .ok()
                        .and_then(|mut map| map.remove(id));
                    if let Some(sender) = sender {
                        let response = match message.get("error") {
                            Some(error) => Err(error.clone()),
                            None => Ok(message.get("result").cloned().unwrap_or(Value::Null)),
                        };
                        let _ = sender.send(response);
                    }
                }
                if let Ok(mut map) = reader_pending.lock() {
                    let error = json!({"code":"ENGINE_CRASHED","message":"Organizing engine stopped"});
                    for (_, sender) in map.drain() {
                        let _ = sender.send(Err(error.clone()));
                    }
                }
            })
            .map_err(|error| error.to_string())?;

        thread::Builder::new()
            .name("organize-engine-log".into())
            .spawn(move || {
                for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                    eprintln!("[organize-engine] {line}");
                }
            })
            .map_err(|error| error.to_string())?;

        Ok(Self {
            child: Mutex::new(child),
            input: Arc::new(Mutex::new(input)),
            pending,
            next_id: AtomicU64::new(1),
        })
    }
}

impl Drop for EngineBridge {
    fn drop(&mut self) {
        if let Ok(mut child) = self.child.lock() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn similar_photos_binary() -> Option<PathBuf> {
    if let Ok(value) = env::var("ORGANIZE_SIMILAR_PHOTOS") {
        let path = PathBuf::from(value);
        if path.is_file() {
            return Some(path);
        }
    }
    let name = if cfg!(windows) {
        "similar-photos.exe"
    } else {
        "similar-photos"
    };
    if let Ok(executable) = env::current_exe() {
        if let Some(directory) = executable.parent() {
            let bundled = directory.join(name);
            if bundled.is_file() {
                return Some(bundled);
            }
        }
    }
    if cfg!(debug_assertions) {
        let binaries = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("binaries");
        if let Ok(entries) = std::fs::read_dir(binaries) {
            let mut matches: Vec<PathBuf> = entries
                .flatten()
                .map(|entry| entry.path())
                .filter(|path| {
                    path.file_name()
                        .and_then(|name| name.to_str())
                        .is_some_and(|name| name.starts_with("similar-photos-"))
                })
                .collect();
            matches.sort();
            return matches.pop();
        }
    }
    None
}

fn engine_command() -> Result<Command, String> {
    if let Ok(binary) = env::var("ORGANIZE_GUI_ENGINE") {
        let mut command = Command::new(binary);
        if let Some(scanner) = similar_photos_binary() {
            command.env("ORGANIZE_SIMILAR_PHOTOS", scanner);
        }
        return Ok(command);
    }

    let executable = env::current_exe().map_err(|error| format!("Cannot locate the application: {error}"))?;
    let bundled_name = if cfg!(windows) {
        "organize-engine.exe"
    } else {
        "organize-engine"
    };
    if let Some(directory) = executable.parent() {
        let bundled = directory.join(bundled_name);
        if bundled.is_file() {
            let mut command = Command::new(bundled);
            if let Some(scanner) = similar_photos_binary() {
                command.env("ORGANIZE_SIMILAR_PHOTOS", scanner);
            }
            return Ok(command);
        }
    }

    if !cfg!(debug_assertions) {
        return Err("The organizing engine is missing from the package. Please reinstall the app".into());
    }

    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let source = manifest.join("../../../engine/src");
    let source = source
        .canonicalize()
        .map_err(|error| format!("Cannot find the Python engine: {error}"))?;
    let python = env::var("ORGANIZE_GUI_PYTHON").unwrap_or_else(|_| "python3".into());
    let mut command = Command::new(python);
    command.arg("-m").arg("organize_gui.rpc_server");
    let mut paths = vec![source];
    if let Some(existing) = env::var_os("PYTHONPATH") {
        paths.extend(env::split_paths(&existing));
    }
    command.env(
        "PYTHONPATH",
        env::join_paths(paths).map_err(|error| error.to_string())?,
    );
    if let Some(scanner) = similar_photos_binary() {
        command.env("ORGANIZE_SIMILAR_PHOTOS", scanner);
    }
    Ok(command)
}

#[tauri::command]
async fn engine_request(
    bridge: State<'_, EngineBridge>,
    method: String,
    params: Value,
) -> EngineResponse {
    let input = Arc::clone(&bridge.input);
    let pending = Arc::clone(&bridge.pending);
    let next_id = bridge.next_id.fetch_add(1, Ordering::Relaxed).to_string();
    tauri::async_runtime::spawn_blocking(move || {
        request_with_parts(input, pending, next_id, method, params)
    })
    .await
    .unwrap_or_else(|error| Err(json!({"code":"ENGINE_BRIDGE_FAILED","message":error.to_string()})))
}

fn request_with_parts(
    input: Arc<Mutex<ChildStdin>>,
    pending: Pending,
    id: String,
    method: String,
    params: Value,
) -> EngineResponse {
    let message = json!({"id": id, "method": method, "params": params});
    let (sender, receiver) = mpsc::channel();
    pending
        .lock()
        .map_err(|_| json!({"code":"ENGINE_LOCKED","message":"Organizing engine response queue unavailable"}))?
        .insert(id.clone(), sender);
    let result = input
        .lock()
        .map_err(|_| json!({"code":"ENGINE_LOCKED","message":"Organizing engine input unavailable"}))
        .and_then(|mut writer| {
            writeln!(writer, "{}", message)
                .and_then(|_| writer.flush())
                .map_err(|error| json!({"code":"ENGINE_CRASHED","message":error.to_string()}))
        });
    if let Err(error) = result {
        if let Ok(mut map) = pending.lock() {
            map.remove(&id);
        }
        return Err(json!({"code":"ENGINE_CRASHED","message":error.to_string()}));
    }
    receiver
        .recv_timeout(Duration::from_secs(30 * 60))
        .unwrap_or_else(|_| {
            if let Ok(mut map) = pending.lock() {
                map.remove(&id);
            }
            Err(json!({"code":"ENGINE_TIMEOUT","message":"Organizing engine response timed out"}))
        })
}

#[tauri::command]
fn reveal_path(path: String) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    let mut command = Command::new("open");
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut value = Command::new("explorer");
        value.arg("/select,");
        value
    };
    #[cfg(all(not(target_os = "macos"), not(target_os = "windows")))]
    let mut command = Command::new("xdg-open");
    command
        .arg(path)
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Cannot open location: {error}"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let bridge =
                EngineBridge::spawn(app.handle().clone()).map_err(std::io::Error::other)?;
            app.manage(bridge);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            engine_request,
            reveal_path,
            open_legal_resource
        ])
        .run(tauri::generate_context!())
        .expect("error while running organize");
}

fn legal_resource_path(directory: &std::path::Path, resource: &str) -> Result<PathBuf, String> {
    match resource {
        "licenses" => Ok(directory.join("legal")),
        "mpl-sources" => Ok(directory.join("legal/MPL-SOURCES.zip")),
        _ => Err("Unknown license resource".into()),
    }
}

#[tauri::command]
fn open_legal_resource(app: AppHandle, resource: String) -> Result<(), String> {
    let directory = app
        .path()
        .resource_dir()
        .map_err(|error| error.to_string())?;
    let path = legal_resource_path(&directory, &resource)?;
    if !path.exists() {
        return Err(
            "License resources are missing from the package. Please reinstall; in development mode check the repository legal/generated".into(),
        );
    }
    reveal_path(path.to_string_lossy().into_owned())
}

#[cfg(test)]
mod legal_tests {
    use super::*;

    #[test]
    fn only_allow_named_bundled_legal_resources() {
        let root = PathBuf::from("resources");
        assert_eq!(
            legal_resource_path(&root, "licenses").unwrap(),
            root.join("legal")
        );
        assert_eq!(
            legal_resource_path(&root, "mpl-sources").unwrap(),
            root.join("legal/MPL-SOURCES.zip")
        );
        assert!(legal_resource_path(&root, "../../etc/passwd").is_err());
        assert!(legal_resource_path(&root, "/tmp/file").is_err());
    }
}
