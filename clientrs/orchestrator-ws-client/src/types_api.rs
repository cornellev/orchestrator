//! Types REST API client.

use crate::error::{Error, Result};
use orchestrator_protocol::{load_message_definition, MessageRegistry};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::time::Duration;

/// A single type definition as returned/accepted by the Types API.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TypeDefinition {
    /// Fully-qualified type name (`package/Message`).
    #[serde(rename = "type")]
    pub type_name: String,
    /// Raw `.msg` definition text.
    pub definition: String,
    /// Optional ISO-8601 update timestamp.
    #[serde(default)]
    pub updated_at: Option<String>,
}

/// Response from `GET /api/types`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TypesListResponse {
    /// Matching type definitions.
    pub types: Vec<TypeDefinition>,
    /// Count of returned types.
    pub count: usize,
}

/// Response from `POST /api/types/sync`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TypesSyncResponse {
    /// Successfully saved entries.
    pub saved: Vec<SavedType>,
    /// Number saved.
    pub count: usize,
    /// Per-entry errors.
    #[serde(default)]
    pub errors: Vec<SyncError>,
}

/// One successfully saved type.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SavedType {
    /// Type name.
    #[serde(rename = "type")]
    pub type_name: String,
    /// Update timestamp.
    #[serde(default)]
    pub updated_at: Option<String>,
}

/// One sync error entry.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SyncError {
    /// Index in the request array.
    #[serde(default)]
    pub index: Option<usize>,
    /// Type name when available.
    #[serde(rename = "type", default)]
    pub type_name: Option<String>,
    /// Error message.
    pub error: String,
}

/// HTTP client for the Orchestrator Types API.
#[derive(Debug, Clone)]
pub struct TypesApiClient {
    base: String,
    token: Option<String>,
    http: reqwest::Client,
}

impl TypesApiClient {
    /// Create a client for `api_base` (e.g. `http://127.0.0.1:8090`).
    pub fn new(api_base: impl Into<String>) -> Result<Self> {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(10))
            .build()
            .map_err(|e| Error::TypesApi(e.to_string()))?;
        Ok(Self {
            base: api_base.into().trim_end_matches('/').to_owned(),
            token: None,
            http,
        })
    }

    /// Set an optional Bearer token for write operations.
    pub fn with_token(mut self, token: impl Into<String>) -> Self {
        self.token = Some(token.into());
        self
    }

    fn apply_auth(&self, req: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
        if let Some(token) = &self.token {
            req.header("Authorization", format!("Bearer {token}"))
        } else {
            req
        }
    }

    /// `GET /api/types[?since=...]`
    pub async fn list_types(&self, since: Option<&str>) -> Result<TypesListResponse> {
        let mut url = format!("{}/api/types", self.base);
        if let Some(since) = since {
            url.push_str(&format!("?since={}", urlencoding_lite(since)));
        }
        let req = self.apply_auth(self.http.get(&url));
        let response = req
            .send()
            .await
            .map_err(|e| Error::TypesApi(e.to_string()))?;
        if !response.status().is_success() {
            return Err(Error::TypesApi(format!(
                "list types failed: HTTP {}",
                response.status()
            )));
        }
        response
            .json()
            .await
            .map_err(|e| Error::TypesApi(e.to_string()))
    }

    /// `GET /api/types/<package>/<Message>`
    pub async fn get_type(&self, type_name: &str) -> Result<TypeDefinition> {
        let url = format!("{}/api/types/{type_name}", self.base);
        let req = self.apply_auth(self.http.get(&url));
        let response = req
            .send()
            .await
            .map_err(|e| Error::TypesApi(e.to_string()))?;
        if !response.status().is_success() {
            return Err(Error::TypesApi(format!(
                "get type failed: HTTP {}",
                response.status()
            )));
        }
        response
            .json()
            .await
            .map_err(|e| Error::TypesApi(e.to_string()))
    }

    /// `PUT /api/types/<package>/<Message>`
    pub async fn put_type(&self, type_name: &str, definition: &str) -> Result<TypeDefinition> {
        let url = format!("{}/api/types/{type_name}", self.base);
        let body = serde_json::json!({ "definition": definition });
        let req = self.apply_auth(self.http.put(&url).json(&body));
        let response = req
            .send()
            .await
            .map_err(|e| Error::TypesApi(e.to_string()))?;
        if !response.status().is_success() {
            let status = response.status();
            let text = response.text().await.unwrap_or_default();
            return Err(Error::TypesApi(format!(
                "put type failed: HTTP {status}: {text}"
            )));
        }
        response
            .json()
            .await
            .map_err(|e| Error::TypesApi(e.to_string()))
    }

    /// `POST /api/types/sync`
    pub async fn sync_types(
        &self,
        type_definitions: &BTreeMap<String, String>,
    ) -> Result<TypesSyncResponse> {
        let types: Vec<_> = type_definitions
            .iter()
            .map(|(type_name, definition)| {
                serde_json::json!({
                    "type": type_name,
                    "definition": definition,
                })
            })
            .collect();
        let body = serde_json::json!({ "types": types });
        let url = format!("{}/api/types/sync", self.base);
        let req = self.apply_auth(self.http.post(&url).json(&body));
        let response = req
            .send()
            .await
            .map_err(|e| Error::TypesApi(e.to_string()))?;
        let status = response.status();
        let payload: TypesSyncResponse = response
            .json()
            .await
            .map_err(|e| Error::TypesApi(e.to_string()))?;
        if !status.is_success() {
            return Err(Error::TypesApi(format!(
                "sync failed: HTTP {status}: {} errors",
                payload.errors.len()
            )));
        }
        Ok(payload)
    }
}

fn urlencoding_lite(value: &str) -> String {
    let mut out = String::new();
    for b in value.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' | b':' => {
                out.push(b as char);
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/// Pull types from the server and register them into `registry`.
pub async fn sync_types_from_server(
    registry: &MessageRegistry,
    api_base: &str,
    since: Option<&str>,
    token: Option<&str>,
) -> Result<BTreeMap<String, String>> {
    let mut client = TypesApiClient::new(api_base)?;
    if let Some(token) = token {
        client = client.with_token(token);
    }
    let listed = client.list_types(since).await?;
    let mut loaded = BTreeMap::new();
    for item in listed.types {
        load_message_definition(registry, &item.type_name, &item.definition)?;
        loaded.insert(item.type_name, item.definition);
    }
    Ok(loaded)
}

/// Push in-memory type definitions to the server.
pub async fn sync_types_to_server(
    type_definitions: &BTreeMap<String, String>,
    api_base: &str,
    token: Option<&str>,
) -> Result<TypesSyncResponse> {
    let mut client = TypesApiClient::new(api_base)?;
    if let Some(token) = token {
        client = client.with_token(token);
    }
    client.sync_types(type_definitions).await
}

/// Collect `<folder>/<package>/msg/*.msg` and push them to the server.
pub async fn sync_types_folder_to_server(
    folder: impl AsRef<Path>,
    api_base: &str,
    token: Option<&str>,
) -> Result<TypesSyncResponse> {
    let definitions = collect_msg_definitions(folder.as_ref())?;
    sync_types_to_server(&definitions, api_base, token).await
}

fn collect_msg_definitions(folder: &Path) -> Result<BTreeMap<String, String>> {
    if !folder.is_dir() {
        return Err(Error::TypesApi(format!("not a directory: {folder:?}")));
    }
    let mut result = BTreeMap::new();
    let mut packages: Vec<PathBuf> = std::fs::read_dir(folder)
        .map_err(|e| Error::TypesApi(e.to_string()))?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.is_dir())
        .collect();
    packages.sort();
    for package_dir in packages {
        let msg_dir = package_dir.join("msg");
        if !msg_dir.is_dir() {
            continue;
        }
        let package = package_dir
            .file_name()
            .and_then(|n| n.to_str())
            .ok_or_else(|| Error::TypesApi(format!("invalid package dir {package_dir:?}")))?;
        let mut files: Vec<_> = std::fs::read_dir(&msg_dir)
            .map_err(|e| Error::TypesApi(e.to_string()))?
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| p.extension().and_then(|e| e.to_str()) == Some("msg"))
            .collect();
        files.sort();
        for msg_file in files {
            let stem = msg_file
                .file_stem()
                .and_then(|s| s.to_str())
                .ok_or_else(|| Error::TypesApi(format!("invalid msg file {msg_file:?}")))?;
            let type_name = format!("{package}/{stem}");
            let definition =
                std::fs::read_to_string(&msg_file).map_err(|e| Error::TypesApi(e.to_string()))?;
            result.insert(type_name, definition);
        }
    }
    Ok(result)
}
