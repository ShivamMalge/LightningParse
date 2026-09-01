//! Structured output types matching the JSON schema in docs/ARCHITECTURE.md §3.1.

use serde::{Deserialize, Serialize};

/// Top-level parse result for an entire document.
#[derive(Debug, Serialize, Deserialize)]
pub struct ParseResult {
    pub pages: Vec<Page>,
    pub metadata: DocumentMetadata,
}

/// Per-page result.
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Page {
    pub page_num: u32,
    pub blocks: Vec<Block>,
    /// Effective page width in PDF units (CropBox preferred, else MediaBox,
    /// inherited if absent, axes swapped for /Rotate 90|270).
    /// `None` when the document carries no usable page geometry.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub page_width: Option<f64>,
    /// Effective page height. See [`Page::page_width`].
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub page_height: Option<f64>,
}

/// A style span within a text block.
#[derive(Debug, Serialize, Deserialize, Clone, PartialEq)]
pub struct Span {
    pub start: usize,
    pub end: usize,
    pub bold: bool,
    pub font_size: f64,
    #[serde(default)]
    pub is_monospace: bool,
}

/// A single text block extracted from a page.
#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Block {
    Text {
        text: String,
        #[serde(default, skip_serializing_if = "Vec::is_empty")]
        spans: Vec<Span>,
        bbox: [f64; 4],
        section_id: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        block_role: Option<String>,
        source: String,
    },
    Table {
        rows: Vec<Vec<String>>,
        bbox: [f64; 4],
        section_id: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        block_role: Option<String>,
        source: String,
    },
}

impl Block {
    pub fn bbox(&self) -> &[f64; 4] {
        match self {
            Block::Text { bbox, .. } => bbox,
            Block::Table { bbox, .. } => bbox,
        }
    }

    pub fn bbox_mut(&mut self) -> &mut [f64; 4] {
        match self {
            Block::Text { bbox, .. } => bbox,
            Block::Table { bbox, .. } => bbox,
        }
    }

    pub fn section_id(&self) -> &str {
        match self {
            Block::Text { section_id, .. } => section_id,
            Block::Table { section_id, .. } => section_id,
        }
    }

    pub fn set_section_id(&mut self, new_id: String) {
        match self {
            Block::Text { section_id, .. } => *section_id = new_id,
            Block::Table { section_id, .. } => *section_id = new_id,
        }
    }

    pub fn source(&self) -> &str {
        match self {
            Block::Text { source, .. } => source,
            Block::Table { source, .. } => source,
        }
    }

    // Helper for Text variant. Returns empty string for Table.
    pub fn text(&self) -> &str {
        match self {
            Block::Text { text, .. } => text,
            Block::Table { .. } => "",
        }
    }

    pub fn text_mut(&mut self) -> Option<&mut String> {
        match self {
            Block::Text { text, .. } => Some(text),
            Block::Table { .. } => None,
        }
    }

    pub fn block_role(&self) -> Option<&str> {
        match self {
            Block::Text { block_role, .. } => block_role.as_deref(),
            Block::Table { block_role, .. } => block_role.as_deref(),
        }
    }
}

/// Document-level metadata.
#[derive(Debug, Serialize, Deserialize)]
pub struct DocumentMetadata {
    /// "digital", "scanned", or "mixed".
    pub tier: String,
    pub page_count: u32,
    pub parse_time_ms: u64,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub warnings: Vec<String>,
}
