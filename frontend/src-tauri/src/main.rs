#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::{
    fs::{self, OpenOptions},
    io::{BufRead, BufReader},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    time::Duration,
};
use tauri::{Manager, State};

#[derive(Clone, Serialize)]
struct RuntimeStatus {
    state: String,
    message: String,
}

#[derive(Clone, Deserialize)]
struct Connection {
    port: u16,
    token: String,
}

struct Runtime {
    status: RuntimeStatus,
    connection: Option<Connection>,
    child: Option<Child>,
    closing: bool,
}

type SharedRuntime = Arc<Mutex<Runtime>>;

fn stop_child(child: &mut Child) {
    // Closing stdin also handles a crashed parent: Python observes EOF and exits.
    drop(child.stdin.take());
    for _ in 0..40 {
        if matches!(child.try_wait(), Ok(Some(_))) {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn start_runtime(shared: SharedRuntime, resource_dir: PathBuf, data_dir: PathBuf) {
    let outcome = (|| -> Result<(), String> {
        let service = resource_dir.join("service/clareza-service/clareza-service");
        if !service.is_file() {
            return Err(
                "O pacote do aplicativo está incompleto. Baixe o Clareza novamente.".into(),
            );
        }
        let log_dir = &data_dir;
        fs::create_dir_all(&log_dir).map_err(|e| e.to_string())?;
        let log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(log_dir.join("runtime.log"))
            .map_err(|e| e.to_string())?;
        let mut child = Command::new(service)
            .env("CLAREZA_DATA_DIR", &data_dir)
            .current_dir(&data_dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(log)
            .spawn()
            .map_err(|e| format!("Não foi possível iniciar os serviços locais: {e}"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or("Canal de inicialização indisponível.")?;
        {
            let mut state = shared.lock().unwrap();
            if state.closing {
                stop_child(&mut child);
                return Ok(());
            }
            state.child = Some(child);
        }
        let (sender, receiver) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let mut line = String::new();
            let result = BufReader::new(stdout).read_line(&mut line).map(|_| line);
            let _ = sender.send(result);
        });
        let line = receiver
            .recv_timeout(Duration::from_secs(120))
            .map_err(|_| {
                "A inicialização demorou demais. Consulte runtime.log na pasta de dados do Clareza."
                    .to_string()
            })?
            .map_err(|e| e.to_string())?;
        let connection: Connection = serde_json::from_str(&line)
            .map_err(|_| "Não foi possível abrir o banco ou o servidor local. Consulte runtime.log na pasta de dados do Clareza.".to_string())?;
        let mut state = shared.lock().unwrap();
        if !state.closing {
            state.connection = Some(connection);
            state.status = RuntimeStatus {
                state: "ready".into(),
                message: "Tudo pronto.".into(),
            };
        }
        Ok(())
    })();
    if let Err(message) = outcome {
        let mut state = shared.lock().unwrap();
        state.status = RuntimeStatus {
            state: "error".into(),
            message,
        };
        if let Some(mut child) = state.child.take() {
            stop_child(&mut child);
        }
    }
}

#[tauri::command]
fn runtime_status(runtime: State<'_, SharedRuntime>) -> RuntimeStatus {
    let mut state = runtime.lock().unwrap();
    if state.status.state == "ready" {
        if let Some(child) = state.child.as_mut() {
            if matches!(child.try_wait(), Ok(Some(_))) {
                state.connection = None;
                state.status = RuntimeStatus {
                    state: "error".into(),
                    message: "O serviço local parou. Feche e abra o Clareza novamente.".into(),
                };
            }
        }
    }
    state.status.clone()
}

fn valid_request(path: &str, method: &str) -> bool {
    let resource = path.split('/').next().unwrap_or_default();
    let allowed = [
        "profile",
        "sync",
        "dashboard",
        "accounts",
        "cards",
        "categories",
        "transactions",
        "invoices",
        "subscriptions",
        "goals",
        "bills",
        "payments",
        "planning",
        "history",
        "installment-purchases",
    ];
    allowed.contains(&resource)
        && path.len() < 2048
        && !path.contains([':', '\\', '#', '%'])
        && !path.contains("..")
        && !path.chars().any(char::is_control)
        && ["GET", "POST", "PATCH", "DELETE"].contains(&method)
}

#[derive(Serialize)]
struct ApiResponse {
    status: u16,
    body: serde_json::Value,
}

#[tauri::command]
async fn api_request(
    path: String,
    method: String,
    body: Option<String>,
    runtime: State<'_, SharedRuntime>,
) -> Result<ApiResponse, String> {
    if !valid_request(&path, &method) || body.as_ref().is_some_and(|b| b.len() > 1_000_000) {
        return Err("Solicitação inválida.".into());
    }
    let connection = runtime.lock().unwrap().connection.clone()
        .ok_or("O serviço local ainda não está pronto. Feche e abra o Clareza novamente se o problema persistir.")?;
    tauri::async_runtime::spawn_blocking(move || {
        let client = reqwest::blocking::Client::builder()
            .no_proxy()
            .timeout(Duration::from_secs(45))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|e| e.to_string())?;
        let method = reqwest::Method::from_bytes(method.as_bytes()).map_err(|e| e.to_string())?;
        let mut request = client
            .request(
                method,
                format!("http://127.0.0.1:{}/api/v1/{}", connection.port, path),
            )
            .header("X-Clareza-Token", connection.token)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json");
        if let Some(body) = body {
            request = request.body(body);
        }
        let response = request.send().map_err(|_| {
            "Não foi possível acessar o serviço local. Feche e abra o Clareza novamente."
                .to_string()
        })?;
        let status = response.status().as_u16();
        if status == 200 && path.starts_with("dashboard/") {
            eprintln!("Clareza: interface conectada ao serviço local.");
        }
        let body = if status == 204 {
            serde_json::Value::Null
        } else {
            response
                .json()
                .map_err(|_| "O serviço local retornou uma resposta inesperada.".to_string())?
        };
        Ok(ApiResponse { status, body })
    })
    .await
    .map_err(|e| e.to_string())?
}

fn main() {
    let shared = Arc::new(Mutex::new(Runtime {
        status: RuntimeStatus {
            state: "starting".into(),
            message: "Preparando suas finanças…".into(),
        },
        connection: None,
        child: None,
        closing: false,
    }));
    let startup = shared.clone();
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .manage(shared.clone())
        .invoke_handler(tauri::generate_handler![runtime_status, api_request])
        .setup(move |app| {
            let resource_dir = app.path().resource_dir()?;
            let data_dir = std::env::var_os("CLAREZA_DATA_DIR")
                .map(PathBuf::from)
                .unwrap_or(app.path().app_data_dir()?);
            std::thread::spawn(move || start_runtime(startup, resource_dir, data_dir));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Não foi possível abrir a janela do Clareza");
    app.run(move |_, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            let mut state = shared.lock().unwrap();
            state.closing = true;
            if let Some(mut child) = state.child.take() {
                stop_child(&mut child);
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn restrict_proxy_to_local_finance_endpoints() {
        assert!(valid_request("accounts/1/", "PATCH"));
        assert!(valid_request("dashboard/?year=2026&month=9", "GET"));
        assert!(valid_request("installment-purchases/preview/", "POST"));
        assert!(valid_request("subscriptions/preview/", "POST"));
        assert!(valid_request("subscriptions/1/review-first-charge/", "POST"));
        assert!(valid_request("payments/pending/?year=2026&month=10", "GET"));
        for path in [
            "https://example.com",
            "../admin/",
            "accounts/%2e%2e/",
            "accounts/../",
            "admin/",
        ] {
            assert!(!valid_request(path, "GET"));
        }
        assert!(!valid_request("accounts/", "CONNECT"));
    }
}
