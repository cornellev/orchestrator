//! ROS-style `.msg` schema parsing and registry.

use crate::error::{Error, Result};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, RwLock};

/// A single field inside a message definition.
#[derive(Debug, Clone, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct FieldDef {
    /// Field name.
    pub name: String,
    /// Resolved type name (scalar or `package/Message`).
    pub type_name: String,
    /// Whether the field is an array.
    pub is_array: bool,
    /// Fixed array length, if present.
    pub array_len: Option<usize>,
}

/// A registered message definition.
#[derive(Debug, Clone, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct MessageDef {
    /// Fully-qualified type name (`package/Message`).
    pub type_name: String,
    /// Ordered fields.
    pub fields: Vec<FieldDef>,
}

/// Thread-safe message type registry.
#[derive(Debug, Default, Clone)]
pub struct MessageRegistry {
    inner: Arc<RwLock<HashMap<String, MessageDef>>>,
}

impl MessageRegistry {
    /// Create an empty registry.
    pub fn new() -> Self {
        Self::default()
    }

    /// Register or replace a message definition.
    pub fn register(&self, def: MessageDef) {
        let mut guard = self.inner.write().expect("registry poisoned");
        guard.insert(def.type_name.clone(), def);
    }

    /// Look up a message definition by type name.
    pub fn get(&self, type_name: &str) -> Option<MessageDef> {
        let guard = self.inner.read().expect("registry poisoned");
        guard.get(type_name).cloned()
    }

    /// Return whether a type is registered.
    pub fn contains(&self, type_name: &str) -> bool {
        let guard = self.inner.read().expect("registry poisoned");
        guard.contains_key(type_name)
    }

    /// List all registered type names (sorted).
    pub fn type_names(&self) -> Vec<String> {
        let guard = self.inner.read().expect("registry poisoned");
        let mut names: Vec<_> = guard.keys().cloned().collect();
        names.sort();
        names
    }

    /// Number of registered types.
    pub fn len(&self) -> usize {
        let guard = self.inner.read().expect("registry poisoned");
        guard.len()
    }

    /// Whether the registry is empty.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

fn normalize_type_name(type_name: &str, package: Option<&str>) -> String {
    if type_name.contains('/') {
        return type_name.to_owned();
    }
    let scalar = type_name.to_ascii_lowercase();
    if is_builtin(&scalar) {
        return scalar;
    }
    if let Some(package) = package {
        return format!("{package}/{type_name}");
    }
    type_name.to_owned()
}

pub(crate) fn is_builtin(type_name: &str) -> bool {
    matches!(
        type_name.to_ascii_lowercase().as_str(),
        "bool"
            | "int8"
            | "uint8"
            | "byte"
            | "char"
            | "int16"
            | "uint16"
            | "int32"
            | "uint32"
            | "int64"
            | "uint64"
            | "float32"
            | "float64"
            | "string"
            | "time"
            | "duration"
    )
}

fn parse_field_type(type_token: &str) -> Result<(String, bool, Option<usize>)> {
    let (base, array_part) = match type_token.find('[') {
        Some(idx) => (&type_token[..idx], Some(&type_token[idx..])),
        None => (type_token, None),
    };

    if base.is_empty()
        || !base
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '/')
    {
        return Err(Error::InvalidFieldType(type_token.to_owned()));
    }

    let (is_array, fixed_len) = if let Some(part) = array_part {
        if !part.starts_with('[') || !part.ends_with(']') {
            return Err(Error::InvalidFieldType(type_token.to_owned()));
        }
        let inner = &part[1..part.len() - 1];
        if inner.is_empty() {
            (true, None)
        } else {
            let len: usize = inner
                .parse()
                .map_err(|_| Error::InvalidFieldType(type_token.to_owned()))?;
            (true, Some(len))
        }
    } else {
        (false, None)
    };

    Ok((base.to_owned(), is_array, fixed_len))
}

/// Parse and register a ROS-style `.msg` definition text.
pub fn load_message_definition(
    registry: &MessageRegistry,
    type_name: &str,
    definition: &str,
) -> Result<String> {
    if !type_name.contains('/') {
        return Err(Error::InvalidTypeName);
    }
    let package_name = type_name
        .split_once('/')
        .map(|(p, _)| p)
        .ok_or(Error::InvalidTypeName)?;

    let mut fields = Vec::new();
    for raw_line in definition.lines() {
        let line = raw_line.split('#').next().unwrap_or("").trim();
        if line.is_empty() || line.contains('=') {
            continue;
        }
        let mut parts = line.split_whitespace();
        let Some(type_token) = parts.next() else {
            continue;
        };
        let Some(name) = parts.next() else {
            continue;
        };
        let (base, is_array, array_len) = parse_field_type(type_token)?;
        let resolved = normalize_type_name(&base, Some(package_name));
        fields.push(FieldDef {
            name: name.to_owned(),
            type_name: resolved,
            is_array,
            array_len,
        });
    }

    let normalized = normalize_type_name(type_name, None);
    registry.register(MessageDef {
        type_name: normalized.clone(),
        fields,
    });
    Ok(normalized)
}

/// Load a single `.msg` file.
pub fn load_message_file(
    registry: &MessageRegistry,
    file_path: impl AsRef<Path>,
    package: Option<&str>,
) -> Result<String> {
    let path = file_path.as_ref();
    let text = fs::read_to_string(path).map_err(|e| Error::Io(format!("{path:?}: {e}")))?;
    let inferred_package = package
        .map(str::to_owned)
        .or_else(|| {
            path.parent()
                .and_then(|p| p.parent())
                .and_then(|p| p.file_name())
                .and_then(|n| n.to_str())
                .map(str::to_owned)
        })
        .ok_or_else(|| Error::Io(format!("cannot infer package for {path:?}")))?;
    let msg_name = path
        .file_stem()
        .and_then(|s| s.to_str())
        .ok_or_else(|| Error::Io(format!("invalid message file name {path:?}")))?;
    let full_type = format!("{inferred_package}/{msg_name}");
    load_message_definition(registry, &full_type, &text)
}

/// Load all `.msg` files from a package folder (`folder/msg/*.msg` or `folder/*.msg`).
pub fn load_message_folder(
    registry: &MessageRegistry,
    folder_path: impl AsRef<Path>,
    package: Option<&str>,
) -> Result<Vec<String>> {
    let folder = folder_path.as_ref();
    if !folder.is_dir() {
        return Err(Error::Io(format!("not a directory: {folder:?}")));
    }
    let resolved_package = package
        .map(str::to_owned)
        .or_else(|| {
            folder
                .file_name()
                .and_then(|n| n.to_str())
                .map(str::to_owned)
        })
        .ok_or_else(|| Error::Io(format!("cannot infer package for {folder:?}")))?;

    let msg_dir = folder.join("msg");
    let search_dirs = if msg_dir.is_dir() {
        vec![msg_dir]
    } else {
        vec![folder.to_path_buf()]
    };

    let mut loaded = Vec::new();
    for dir in search_dirs {
        let mut entries: Vec<PathBuf> = fs::read_dir(&dir)
            .map_err(|e| Error::Io(format!("{dir:?}: {e}")))?
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| p.extension().and_then(|e| e.to_str()) == Some("msg"))
            .collect();
        entries.sort();
        for msg_file in entries {
            loaded.push(load_message_file(
                registry,
                &msg_file,
                Some(&resolved_package),
            )?);
        }
    }
    Ok(loaded)
}

/// Load `<root>/<package>/msg/*.msg` trees.
pub fn load_message_root(
    registry: &MessageRegistry,
    root_path: impl AsRef<Path>,
) -> Result<Vec<String>> {
    let root = root_path.as_ref();
    if !root.is_dir() {
        return Err(Error::Io(format!("not a directory: {root:?}")));
    }
    let mut package_dirs: Vec<_> = fs::read_dir(root)
        .map_err(|e| Error::Io(format!("{root:?}: {e}")))?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.is_dir())
        .collect();
    package_dirs.sort();

    let mut loaded = Vec::new();
    for package_dir in package_dirs {
        let msg_dir = package_dir.join("msg");
        if msg_dir.is_dir() {
            let package = package_dir
                .file_name()
                .and_then(|n| n.to_str())
                .ok_or_else(|| Error::Io(format!("invalid package dir {package_dir:?}")))?;
            loaded.extend(load_message_folder(registry, &package_dir, Some(package))?);
        }
    }
    Ok(loaded)
}

/// Discover message definitions from `ORCH_MSG_PATHS` and common cwd folders.
///
/// Matches the Python `_auto_discover_message_defs` helper: failures for individual
/// candidates are ignored.
pub fn discover_message_defs(registry: &MessageRegistry) -> Vec<String> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(env_paths) = std::env::var("ORCH_MSG_PATHS") {
        // Python uses os.pathsep (`:` on Unix, `;` on Windows).
        for token in env_paths.split(if cfg!(windows) { ';' } else { ':' }) {
            let token = token.trim();
            if !token.is_empty() {
                candidates.push(PathBuf::from(token));
            }
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.join("messages"));
        candidates.push(cwd.join("msgs"));
        candidates.push(cwd.join("msg"));
    }

    let mut loaded = Vec::new();
    for candidate in candidates {
        if !candidate.is_dir() {
            continue;
        }
        let has_package_dirs = fs::read_dir(&candidate)
            .ok()
            .map(|iter| {
                iter.filter_map(|e| e.ok())
                    .any(|e| e.path().is_dir() && e.path().join("msg").is_dir())
            })
            .unwrap_or(false);

        let result = if has_package_dirs {
            load_message_root(registry, &candidate)
        } else {
            load_message_folder(registry, &candidate, None)
        };
        if let Ok(names) = result {
            loaded.extend(names);
        }
    }
    loaded
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_basic_definition() {
        let registry = MessageRegistry::new();
        load_message_definition(
            &registry,
            "geometry_msgs/Point32",
            "float32 x\nfloat32 y\nfloat32 z\n",
        )
        .unwrap();
        let def = registry.get("geometry_msgs/Point32").unwrap();
        assert_eq!(def.fields.len(), 3);
        assert_eq!(def.fields[0].name, "x");
        assert_eq!(def.fields[0].type_name, "float32");
    }

    #[test]
    fn skips_constants_and_comments() {
        let registry = MessageRegistry::new();
        load_message_definition(
            &registry,
            "demo_msgs/Thing",
            "# comment\nint32 VALUE=1\nint32 value\n",
        )
        .unwrap();
        let def = registry.get("demo_msgs/Thing").unwrap();
        assert_eq!(def.fields.len(), 1);
        assert_eq!(def.fields[0].name, "value");
    }
}
