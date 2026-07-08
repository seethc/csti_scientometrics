#!/usr/bin/env python3
"""Local browser viewer for a Lens patent CSV export."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import threading
import webbrowser
from collections import Counter
from datetime import datetime
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


DEFAULT_CSV = Path(r"C:\Users\sugey\Dropbox\PC\Downloads\10yr-photonic-interconnects.csv")
APP_STATE_DIR = Path(__file__).resolve().parent / ".patent_csv_viewer_state"
VALID_REVIEW_LABELS = {"relevant", "not_relevant", "uncertain", ""}
CLASSIFICATION_FIELDS = {
    "cpc": "CPC Classifications",
    "ipcr": "IPCR Classifications",
    "uspc": "US Classifications",
}
FILTER_FIELDS = {
    "jurisdiction": "Jurisdiction",
    "status": "Legal Status",
    "document_type": "Document Type",
    "applicant": "Applicants",
}

NUMERIC_FIELDS = {
    "Cites Patent Count",
    "Cited by Patent Count",
    "Simple Family Size",
    "Extended Family Size",
    "NPL Citation Count",
    "NPL Resolved Citation Count",
    "Sequence Count",
}

SEARCH_FIELDS = [
    "Display Key",
    "Lens ID",
    "Title",
    "Abstract",
    "Applicants",
    "Inventors",
    "Owners",
    "CPC Classifications",
    "IPCR Classifications",
    "US Classifications",
    "NPL Citations",
    "Legal Status",
    "Document Type",
]

OWNER_DATE_RE = re.compile(r"\s+\(\d{4}-\d{2}-\d{2}\)$")

VOS_SCORE_FIELDS = [
    ("score<Pub. year>", "Publication Year", "int"),
    ("score<Application year>", "Application Date", "year"),
    ("score<Earliest priority year>", "Earliest Priority Date", "year"),
    ("score<Cited by patents>", "Cited by Patent Count", "int"),
    ("score<Cites patents>", "Cites Patent Count", "int"),
    ("score<Simple family size>", "Simple Family Size", "int"),
    ("score<Extended family size>", "Extended Family Size", "int"),
    ("score<NPL citations>", "NPL Citation Count", "int"),
]

VOS_THESAURUS_IGNORES = [
    "apparatus",
    "configured",
    "device",
    "devices",
    "embodiment",
    "embodiments",
    "example",
    "first",
    "method",
    "methods",
    "plurality",
    "provided",
    "second",
    "system",
    "systems",
    "wherein",
]


APP_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Patent CSV Viewer</title>
  <style>
    :root {
      --bg: #f7f6f1;
      --panel: #ffffff;
      --panel-2: #f0f4ef;
      --ink: #20242a;
      --muted: #646b73;
      --line: #d8ddd2;
      --accent: #1f7a5a;
      --accent-2: #b46a20;
      --accent-3: #335c99;
      --danger: #a8323e;
      --shadow: 0 10px 24px rgba(31, 42, 52, 0.08);
    }

    * {
      box-sizing: border-box;
    }

    html,
    body {
      height: 100%;
      margin: 0;
    }

    body {
      background: var(--bg);
      color: var(--ink);
      font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, Arial, sans-serif;
      font-size: 15px;
      letter-spacing: 0;
    }

    button,
    input,
    select,
    textarea {
      font: inherit;
    }

    button {
      cursor: pointer;
    }

    a {
      color: var(--accent-3);
      text-decoration: none;
    }

    a:hover {
      text-decoration: underline;
    }

    .shell {
      display: grid;
      grid-template-columns: minmax(240px, 300px) minmax(360px, 1fr) minmax(340px, 500px);
      min-height: 100vh;
    }

    .sidebar {
      border-right: 1px solid var(--line);
      background: #fbfaf6;
      padding: 18px;
      overflow: auto;
    }

    .main {
      display: flex;
      min-width: 0;
      flex-direction: column;
      border-right: 1px solid var(--line);
      background: var(--bg);
    }

    .detail {
      min-width: 0;
      overflow: auto;
      background: #fbfbf8;
    }

    .brand {
      margin-bottom: 18px;
    }

    .brand h1 {
      margin: 0 0 6px;
      font-size: 22px;
      line-height: 1.1;
      letter-spacing: 0;
    }

    .brand .file {
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }

    .filter-stack {
      display: grid;
      gap: 14px;
    }

    .open-panel {
      display: grid;
      gap: 8px;
      margin-bottom: 18px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
      padding: 12px;
    }

    .open-panel input[type="file"] {
      width: 100%;
      min-width: 0;
      color: var(--muted);
      font-size: 12px;
    }

    .open-status {
      min-height: 17px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }

    .field {
      display: grid;
      gap: 6px;
    }

    .field label,
    .field > span {
      color: #384049;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }

    .field input,
    .field select,
    .field textarea {
      width: 100%;
      min-height: 38px;
      border: 1px solid #ccd4c7;
      border-radius: 6px;
      background: #ffffff;
      color: var(--ink);
      padding: 8px 10px;
      outline: none;
    }

    .field textarea {
      min-height: 78px;
      resize: vertical;
    }

    .field input[type="checkbox"] {
      width: auto;
      min-height: auto;
      justify-self: start;
    }

    .field input:focus,
    .field select:focus,
    .field textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(31, 122, 90, 0.14);
    }

    .button-row {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }

    .button {
      min-height: 36px;
      border: 1px solid #bfc8bc;
      border-radius: 6px;
      background: #ffffff;
      color: var(--ink);
      padding: 8px 12px;
      font-weight: 650;
    }

    .button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: #ffffff;
    }

    .button:hover {
      box-shadow: 0 2px 8px rgba(24, 34, 41, 0.12);
    }

    .topbar {
      display: grid;
      gap: 12px;
      padding: 18px 20px 14px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }

    .stats {
      display: grid;
      grid-template-columns: repeat(5, minmax(100px, 1fr));
      gap: 10px;
    }

    .stat {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
      padding: 10px 12px;
      min-width: 0;
    }

    .stat .value {
      font-size: 22px;
      font-weight: 750;
      line-height: 1.1;
    }

    .stat .label {
      margin-top: 3px;
      color: var(--muted);
      font-size: 12px;
    }

    .status-line {
      color: var(--muted);
      font-size: 13px;
    }

    .view-tabs {
      display: inline-flex;
      width: max-content;
      max-width: 100%;
      gap: 4px;
      border: 1px solid #c8d1c4;
      border-radius: 8px;
      background: #f4f6f0;
      padding: 3px;
    }

    .tab-button {
      min-height: 32px;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: #3d454d;
      padding: 6px 10px;
      font-weight: 700;
    }

    .tab-button.active {
      background: #ffffff;
      color: var(--accent);
      box-shadow: 0 1px 6px rgba(24, 34, 41, 0.12);
    }

    .insights {
      display: grid;
      grid-template-columns: repeat(2, minmax(260px, 1fr));
      gap: 14px;
      padding: 16px 20px 24px;
      overflow: auto;
    }

    .insight-panel {
      display: grid;
      align-content: start;
      gap: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
      padding: 14px;
      min-width: 0;
    }

    .insight-panel h2 {
      margin: 0;
      font-size: 15px;
      line-height: 1.2;
      letter-spacing: 0;
    }

    .insight-note {
      grid-column: 1 / -1;
      border: 1px solid #d5c296;
      border-radius: 8px;
      background: #fff9ea;
      color: #60461b;
      padding: 10px 12px;
      line-height: 1.4;
    }

    .count-list {
      display: grid;
      gap: 8px;
    }

    .count-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
    }

    .count-label {
      min-width: 0;
      overflow-wrap: anywhere;
      font-weight: 650;
      line-height: 1.25;
    }

    .count-value {
      color: var(--muted);
      font-variant-numeric: tabular-nums;
      font-weight: 700;
    }

    .bar-track {
      grid-column: 1 / -1;
      height: 7px;
      overflow: hidden;
      border-radius: 999px;
      background: #edf0e9;
    }

    .bar-fill {
      height: 100%;
      border-radius: inherit;
      background: var(--accent);
    }

    .insight-panel.office .bar-fill {
      background: var(--accent-3);
    }

    .insight-panel.family .bar-fill {
      background: var(--accent);
    }

    .insight-panel.owner .bar-fill {
      background: var(--accent-2);
    }

    .insight-panel.classification .bar-fill {
      background: #3d6f91;
    }

    .insight-panel.status .bar-fill {
      background: #7a4f9a;
    }

    .analysis-view {
      display: grid;
      gap: 14px;
      padding: 16px 20px 24px;
      overflow: auto;
    }

    .analysis-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(280px, 1fr));
      gap: 14px;
    }

    .analysis-panel {
      display: grid;
      align-content: start;
      gap: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
      padding: 14px;
      min-width: 0;
    }

    .analysis-panel.wide {
      grid-column: 1 / -1;
    }

    .analysis-panel h2,
    .analysis-panel h3 {
      margin: 0;
      font-size: 15px;
      line-height: 1.2;
      letter-spacing: 0;
    }

    .analysis-panel h3 {
      color: #3a434b;
      font-size: 13px;
      text-transform: uppercase;
    }

    .panel-head {
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
    }

    .panel-head .button {
      min-height: 30px;
      padding: 5px 9px;
      font-size: 12px;
    }

    .analysis-help {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
    }

    .metric-table-wrap {
      max-width: 100%;
      overflow: auto;
      border: 1px solid #e0e5dc;
      border-radius: 8px;
    }

    .metric-table {
      width: 100%;
      border-collapse: collapse;
      background: #ffffff;
      font-size: 13px;
    }

    .metric-table th,
    .metric-table td {
      border-bottom: 1px solid #e7ebe3;
      padding: 7px 9px;
      text-align: left;
      vertical-align: top;
      white-space: nowrap;
    }

    .metric-table th {
      background: #f3f6f0;
      color: #354039;
      font-weight: 750;
    }

    .metric-table tr:last-child td {
      border-bottom: 0;
    }

    .scope-form {
      display: grid;
      grid-template-columns: repeat(2, minmax(180px, 1fr));
      gap: 10px;
    }

    .scope-form .wide {
      grid-column: 1 / -1;
    }

    .scope-list {
      display: grid;
      gap: 8px;
    }

    .scope-item {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      border: 1px solid #e0e5dc;
      border-radius: 8px;
      padding: 8px 10px;
    }

    .review-box {
      display: grid;
      gap: 8px;
      border: 1px solid #d8ddd2;
      border-radius: 8px;
      background: #f8faf5;
      padding: 10px;
      margin-bottom: 14px;
    }

    .review-button.active {
      border-color: var(--accent);
      background: rgba(31, 122, 90, 0.12);
      color: #175c43;
    }

    .results {
      display: grid;
      gap: 10px;
      padding: 16px 20px 24px;
      overflow: auto;
    }

    .record {
      display: grid;
      gap: 8px;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 13px 14px;
      text-align: left;
      box-shadow: none;
    }

    .record:hover {
      border-color: #aebaa7;
      box-shadow: var(--shadow);
    }

    .record.selected {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(31, 122, 90, 0.12);
    }

    .record-title {
      font-size: 15px;
      font-weight: 750;
      line-height: 1.25;
    }

    .record-meta,
    .record-foot {
      display: flex;
      gap: 7px;
      align-items: center;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
    }

    .pill {
      display: inline-flex;
      min-height: 22px;
      align-items: center;
      border: 1px solid #cad3c8;
      border-radius: 999px;
      background: var(--panel-2);
      color: #314038;
      padding: 2px 8px;
      font-size: 12px;
      line-height: 1.2;
      max-width: 100%;
    }

    .pill.status-active,
    .pill.status-pending,
    .pill.status-patented {
      border-color: rgba(31, 122, 90, 0.3);
      background: rgba(31, 122, 90, 0.11);
      color: #175c43;
    }

    .pill.status-inactive,
    .pill.status-discontinued,
    .pill.status-expired {
      border-color: rgba(168, 50, 62, 0.25);
      background: rgba(168, 50, 62, 0.09);
      color: #8c2932;
    }

    .pill.kind {
      border-color: rgba(180, 106, 32, 0.32);
      background: rgba(180, 106, 32, 0.1);
      color: #714112;
    }

    .muted {
      color: var(--muted);
    }

    .detail-inner {
      padding: 18px 20px 28px;
    }

    .empty-detail,
    .empty-results {
      border: 1px dashed #bfc8bc;
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.7);
      color: var(--muted);
      padding: 18px;
    }

    .detail-head {
      display: grid;
      gap: 10px;
      margin-bottom: 16px;
    }

    .detail-head h2 {
      margin: 0;
      font-size: 22px;
      line-height: 1.18;
      letter-spacing: 0;
    }

    .abstract {
      margin: 0;
      color: #343b43;
      line-height: 1.52;
    }

    details {
      border-top: 1px solid var(--line);
      padding: 12px 0;
    }

    details:first-of-type {
      border-top: 0;
    }

    summary {
      cursor: pointer;
      font-size: 13px;
      font-weight: 750;
      text-transform: uppercase;
    }

    .section-body {
      display: grid;
      gap: 9px;
      padding-top: 12px;
    }

    .info-grid {
      display: grid;
      grid-template-columns: minmax(110px, 150px) minmax(0, 1fr);
      gap: 8px 12px;
      align-items: start;
    }

    .info-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }

    .info-value {
      min-width: 0;
      overflow-wrap: anywhere;
      line-height: 1.38;
    }

    .chips {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      min-width: 0;
    }

    .wide-text {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      line-height: 1.45;
    }

    .footer-actions {
      display: flex;
      justify-content: center;
      padding: 0 20px 24px;
    }

    .notice {
      border: 1px solid #e0c7a3;
      border-radius: 8px;
      background: #fff8ed;
      color: #6c4819;
      padding: 12px;
      line-height: 1.4;
    }

    [hidden] {
      display: none !important;
    }

    @media (max-width: 1180px) {
      .shell {
        grid-template-columns: minmax(220px, 280px) minmax(360px, 1fr);
      }

      .detail {
        grid-column: 1 / -1;
        border-top: 1px solid var(--line);
        max-height: none;
      }
    }

    @media (max-width: 760px) {
      .shell {
        display: block;
      }

      .sidebar,
      .main,
      .detail {
        border-right: 0;
      }

      .sidebar {
        border-bottom: 1px solid var(--line);
      }

      .stats {
        grid-template-columns: repeat(2, minmax(120px, 1fr));
      }

      .insights {
        grid-template-columns: 1fr;
      }

      .analysis-grid,
      .scope-form {
        grid-template-columns: 1fr;
      }

      .analysis-panel.wide,
      .scope-form .wide {
        grid-column: auto;
      }

      .info-grid {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <h1>Patent CSV Viewer</h1>
        <div class="file" id="fileMeta">Loading CSV...</div>
      </div>

      <div class="open-panel">
        <div class="field">
          <label for="csvFileInput">Open CSV</label>
          <input id="csvFileInput" type="file" accept=".csv,text/csv">
        </div>
        <div class="button-row">
          <button class="button primary" id="openCsvButton" type="button">Open</button>
        </div>
        <div class="open-status" id="openStatus"></div>
      </div>

      <div class="filter-stack">
        <div class="field">
          <label for="searchInput">Search</label>
          <input id="searchInput" type="search" placeholder="Title, abstract, applicant, class">
        </div>

        <div class="field">
          <label for="yearSelect">Year</label>
          <select id="yearSelect"></select>
        </div>

        <div class="field">
          <label for="jurisdictionSelect">Jurisdiction</label>
          <select id="jurisdictionSelect"></select>
        </div>

        <div class="field">
          <label for="statusSelect">Legal status</label>
          <select id="statusSelect"></select>
        </div>

        <div class="field">
          <label for="typeSelect">Document type</label>
          <select id="typeSelect"></select>
        </div>

        <div class="field">
          <label for="applicantSelect">Applicant</label>
          <select id="applicantSelect"></select>
        </div>

        <div class="field">
          <label for="cpcSelect">CPC class</label>
          <select id="cpcSelect"></select>
        </div>

        <div class="field">
          <label for="ipcrSelect">IPC class</label>
          <select id="ipcrSelect"></select>
        </div>

        <div class="field">
          <label for="usClassSelect">USPC class</label>
          <select id="usClassSelect"></select>
        </div>

        <div class="field">
          <label for="sortSelect">Sort</label>
          <select id="sortSelect">
            <option value="publication_date">Publication date</option>
            <option value="cited_by">Cited by patents</option>
            <option value="cites">Cites patents</option>
            <option value="family_size">Extended family size</option>
            <option value="title">Title</option>
          </select>
        </div>

        <div class="button-row">
          <button class="button primary" id="applyButton" type="button">Apply</button>
          <button class="button" id="resetButton" type="button">Reset</button>
        </div>
      </div>

      <div class="open-panel">
        <div class="field">
          <label>VOSviewer export</label>
          <div class="button-row">
            <button class="button" id="exportCorpusButton" type="button">Corpus</button>
            <button class="button" id="exportScoresButton" type="button">Scores</button>
            <button class="button" id="exportMetadataButton" type="button">Metadata</button>
            <button class="button" id="exportThesaurusButton" type="button">Thesaurus</button>
          </div>
        </div>
        <div class="open-status" id="exportStatus"></div>
      </div>
    </aside>

    <main class="main">
      <div class="topbar">
        <div class="stats">
          <div class="stat">
            <div class="value" id="metricTotal">0</div>
            <div class="label">Matches</div>
          </div>
          <div class="stat">
            <div class="value" id="metricOpen">0</div>
            <div class="label">Active or pending</div>
          </div>
          <div class="stat">
            <div class="value" id="metricGranted">0</div>
            <div class="label">Granted</div>
          </div>
          <div class="stat">
            <div class="value" id="metricFamilies">0</div>
            <div class="label">Simple families</div>
          </div>
          <div class="stat">
            <div class="value" id="metricCited">0</div>
            <div class="label">Avg cited by</div>
          </div>
        </div>
        <div class="view-tabs" role="tablist" aria-label="View">
          <button class="tab-button active" id="insightsTab" type="button">Insights</button>
          <button class="tab-button" id="analysisTab" type="button">Analysis</button>
          <button class="tab-button" id="recordsTab" type="button">Records</button>
        </div>
        <div class="status-line" id="resultStatus">Loading records...</div>
      </div>

      <div class="insights" id="insights"></div>
      <div class="analysis-view" id="analysisView" hidden></div>
      <div class="results" id="results"></div>
      <div class="footer-actions">
        <button class="button" id="moreButton" type="button">More</button>
      </div>
    </main>

    <aside class="detail">
      <div class="detail-inner" id="detailPane">
        <div class="empty-detail">Select a record.</div>
      </div>
    </aside>
  </div>

  <script>
    const JURISDICTION_NAMES = {
      AU: "Australia",
      CA: "Canada",
      CH: "Switzerland",
      CN: "China",
      DE: "Germany",
      EP: "European Patent Office",
      FR: "France",
      GB: "United Kingdom",
      IL: "Israel",
      IN: "India",
      JP: "Japan",
      KR: "South Korea",
      SG: "Singapore",
      TW: "Taiwan",
      US: "United States",
      WO: "WIPO/PCT"
    };

    const state = {
      offset: 0,
      limit: 25,
      total: 0,
      selectedId: "",
      loading: false,
      view: "insights",
      analysisLoading: false
    };

    const controls = {
      search: document.getElementById("searchInput"),
      year: document.getElementById("yearSelect"),
      jurisdiction: document.getElementById("jurisdictionSelect"),
      status: document.getElementById("statusSelect"),
      type: document.getElementById("typeSelect"),
      applicant: document.getElementById("applicantSelect"),
      cpc: document.getElementById("cpcSelect"),
      ipcr: document.getElementById("ipcrSelect"),
      us_class: document.getElementById("usClassSelect"),
      sort: document.getElementById("sortSelect")
    };

    const resultsEl = document.getElementById("results");
    const insightsEl = document.getElementById("insights");
    const analysisEl = document.getElementById("analysisView");
    const detailEl = document.getElementById("detailPane");
    const moreButton = document.getElementById("moreButton");
    const footerActions = document.querySelector(".footer-actions");
    const resultStatus = document.getElementById("resultStatus");
    const insightsTab = document.getElementById("insightsTab");
    const analysisTab = document.getElementById("analysisTab");
    const recordsTab = document.getElementById("recordsTab");
    const csvFileInput = document.getElementById("csvFileInput");
    const openCsvButton = document.getElementById("openCsvButton");
    const openStatus = document.getElementById("openStatus");
    const exportCorpusButton = document.getElementById("exportCorpusButton");
    const exportScoresButton = document.getElementById("exportScoresButton");
    const exportMetadataButton = document.getElementById("exportMetadataButton");
    const exportThesaurusButton = document.getElementById("exportThesaurusButton");
    const exportStatus = document.getElementById("exportStatus");

    function text(value) {
      return value === null || value === undefined || value === "" ? "" : String(value);
    }

    function numberText(value, digits = 0) {
      const num = Number(value || 0);
      return num.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
    }

    function make(tag, className, content) {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (content !== undefined) node.textContent = content;
      return node;
    }

    function option(select, value, label) {
      const node = document.createElement("option");
      node.value = value;
      node.textContent = label;
      select.appendChild(node);
    }

    function fillSelect(select, items, allLabel, formatter) {
      select.textContent = "";
      option(select, "", allLabel);
      items.forEach((item) => {
        const value = Array.isArray(item) ? item[0] : item;
        const label = formatter ? formatter(item) : value;
        option(select, value, label);
      });
    }

    function jurisdictionLabel(code) {
      const value = text(code);
      const name = JURISDICTION_NAMES[value];
      return name ? `${value} - ${name}` : value;
    }

    function setView(view) {
      state.view = view;
      const insightsActive = view === "insights";
      const analysisActive = view === "analysis";
      insightsEl.hidden = !insightsActive;
      analysisEl.hidden = !analysisActive;
      resultsEl.hidden = insightsActive || analysisActive;
      footerActions.hidden = insightsActive || analysisActive;
      insightsTab.classList.toggle("active", insightsActive);
      analysisTab.classList.toggle("active", analysisActive);
      recordsTab.classList.toggle("active", view === "records");
      if (analysisActive) loadAnalysis();
    }

    function resetFilters() {
      Object.values(controls).forEach((control) => {
        if (control.tagName === "SELECT") control.selectedIndex = 0;
        else control.value = "";
      });
      controls.sort.value = "publication_date";
    }

    function params(resetOffset) {
      if (resetOffset) state.offset = 0;
      const query = filterParams();
      query.set("offset", state.offset);
      query.set("limit", state.limit);
      query.set("sort", controls.sort.value);
      return query;
    }

    function filterParams() {
      const query = new URLSearchParams();
      for (const [key, control] of Object.entries(controls)) {
        if (key === "sort") continue;
        const value = control.value.trim();
        if (value) query.set(key === "type" ? "document_type" : key, value);
      }
      return query;
    }

    async function getJson(url) {
      const response = await fetch(url);
      if (!response.ok) {
        const message = await response.text();
        throw new Error(message || response.statusText);
      }
      return response.json();
    }

    async function postJson(url, payload) {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!response.ok) {
        const message = await response.text();
        throw new Error(message || response.statusText);
      }
      return response.json();
    }

    async function loadMetadata() {
      const metadata = await getJson("/api/metadata");
      document.getElementById("fileMeta").textContent =
        `${metadata.file_name} - ${numberText(metadata.row_count)} rows - ${metadata.last_modified}`;

      fillSelect(controls.year, metadata.years, "Any year");
      fillSelect(controls.jurisdiction, metadata.jurisdictions, "Any jurisdiction", (item) => `${item[0]} (${item[1]})`);
      fillSelect(controls.status, metadata.statuses, "Any status", (item) => `${item[0]} (${item[1]})`);
      fillSelect(controls.type, metadata.document_types, "Any type", (item) => `${item[0]} (${item[1]})`);
      fillSelect(controls.applicant, metadata.applicants, "Any applicant", (item) => `${item[0]} (${item[1]})`);
      fillSelect(controls.cpc, metadata.cpc_classes, "Any CPC class", (item) => `${item[0]} (${item[1]})`);
      fillSelect(controls.ipcr, metadata.ipcr_classes, "Any IPC class", (item) => `${item[0]} (${item[1]})`);
      fillSelect(controls.us_class, metadata.us_classes, "Any USPC class", (item) => `${item[0]} (${item[1]})`);
    }

    async function openCsvFile() {
      const file = csvFileInput.files[0];
      if (!file) {
        openStatus.textContent = "Choose a CSV file first.";
        return;
      }

      openCsvButton.disabled = true;
      openStatus.textContent = `Opening ${file.name}...`;
      const form = new FormData();
      form.append("csv_file", file, file.name);

      try {
        const response = await fetch("/api/load_csv", { method: "POST", body: form });
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || response.statusText);
        }
        const metadata = await response.json();
        resetFilters();
        setView("insights");
        await loadMetadata();
        await loadRecords(true);
        openStatus.textContent = `Opened ${metadata.file_name}.`;
      } catch (error) {
        openStatus.textContent = error.message;
      } finally {
        openCsvButton.disabled = false;
      }
    }

    async function loadRecords(resetOffset = true) {
      if (state.loading) return;
      state.loading = true;
      const query = params(resetOffset);
      if (resetOffset) {
        resultsEl.textContent = "";
        state.selectedId = "";
      }
      resultStatus.textContent = "Loading records...";

      try {
        const data = await getJson(`/api/records?${query.toString()}`);
        state.total = data.total;
        updateMetrics(data.metrics);
        renderInsights(data.breakdowns);
        renderRecords(data.records, resetOffset);
        state.offset += data.records.length;
        moreButton.style.display = state.offset < state.total ? "inline-flex" : "none";
        resultStatus.textContent = `Showing ${numberText(Math.min(state.offset, state.total))} of ${numberText(state.total)} records`;
        if (state.view === "analysis") loadAnalysis();
        if (resetOffset && data.records.length) {
          selectRecord(data.records[0].id);
        }
        if (!data.records.length && resetOffset) {
          detailEl.innerHTML = "";
          detailEl.appendChild(make("div", "empty-detail", "No record selected."));
        }
      } catch (error) {
        resultsEl.textContent = "";
        resultsEl.appendChild(make("div", "notice", error.message));
        insightsEl.textContent = "";
        insightsEl.appendChild(make("div", "notice", error.message));
        resultStatus.textContent = "Could not load records.";
      } finally {
        state.loading = false;
      }
    }

    function updateMetrics(metrics) {
      document.getElementById("metricTotal").textContent = numberText(metrics.total);
      document.getElementById("metricOpen").textContent = numberText(metrics.active_or_pending);
      document.getElementById("metricGranted").textContent = numberText(metrics.granted);
      document.getElementById("metricFamilies").textContent = numberText(metrics.simple_families);
      document.getElementById("metricCited").textContent = numberText(metrics.avg_cited_by, 1);
    }

    function statusClass(status) {
      const normalized = text(status).toLowerCase();
      if (!normalized) return "";
      return `status-${normalized.replaceAll(" ", "-")}`;
    }

    function pill(value, extraClass = "") {
      const node = make("span", `pill ${extraClass}`.trim(), value);
      return node;
    }

    function renderInsights(breakdowns) {
      insightsEl.textContent = "";
      const note = make(
        "div",
        "insight-note",
        "Patent office counts are publication records. Family country coverage de-duplicates simple families. Applicant and owner country is not explicit in this CSV. Classification filters are exploratory; inspect examples for false positives."
      );
      insightsEl.appendChild(note);

      insightsEl.appendChild(countPanel(
        "Patent Offices / Countries",
        breakdowns.patent_offices,
        "office",
        jurisdictionLabel
      ));
      insightsEl.appendChild(countPanel(
        "Family Country Coverage",
        breakdowns.simple_family_jurisdictions,
        "family",
        jurisdictionLabel
      ));
      insightsEl.appendChild(countPanel("Top Applicants", breakdowns.applicants, "owner"));
      insightsEl.appendChild(countPanel("Top Owners", breakdowns.owners, "owner"));
      insightsEl.appendChild(countPanel("Top CPC Codes", breakdowns.cpc_classes, "classification"));
      insightsEl.appendChild(countPanel("Top IPC Codes", breakdowns.ipcr_classes, "classification"));
      insightsEl.appendChild(countPanel("Top USPC Codes", breakdowns.us_classes, "classification"));
      insightsEl.appendChild(countPanel("CPC Subclasses", breakdowns.cpc_subclasses, "classification"));
      insightsEl.appendChild(countPanel("IPC Subclasses", breakdowns.ipcr_subclasses, "classification"));
      insightsEl.appendChild(countPanel("Legal Status", breakdowns.legal_status, "status"));
      insightsEl.appendChild(countPanel("Publication Years", breakdowns.publication_years, "status"));
    }

    function countPanel(title, pairs, className, formatter) {
      const panel = make("section", `insight-panel ${className || ""}`.trim());
      panel.appendChild(make("h2", "", title));
      const list = make("div", "count-list");
      const rows = pairs || [];
      const max = rows.reduce((largest, row) => Math.max(largest, Number(row[1] || 0)), 0);
      if (!rows.length) {
        list.appendChild(make("div", "muted", "No values."));
      }
      rows.forEach((row) => {
        const label = formatter ? formatter(row[0]) : row[0];
        const value = Number(row[1] || 0);
        const percent = max ? Math.max(2, Math.round((value / max) * 100)) : 0;
        const item = make("div", "count-row");
        item.appendChild(make("div", "count-label", label || "(blank)"));
        item.appendChild(make("div", "count-value", numberText(value)));
        const track = make("div", "bar-track");
        const fill = make("div", "bar-fill");
        fill.style.width = `${percent}%`;
        track.appendChild(fill);
        item.appendChild(track);
        list.appendChild(item);
      });
      panel.appendChild(list);
      return panel;
    }

    async function loadAnalysis() {
      if (state.analysisLoading) return;
      state.analysisLoading = true;
      analysisEl.textContent = "";
      analysisEl.appendChild(make("div", "notice", "Loading analysis..."));
      const query = filterParams();
      query.set("sort", controls.sort.value);
      try {
        const data = await getJson(`/api/analysis?${query.toString()}`);
        renderAnalysis(data);
      } catch (error) {
        analysisEl.textContent = "";
        analysisEl.appendChild(make("div", "notice", error.message));
      } finally {
        state.analysisLoading = false;
      }
    }

    function renderAnalysis(data) {
      analysisEl.textContent = "";
      analysisEl.appendChild(make(
        "div",
        "insight-note",
        `Analysis uses the current filter slice (${numberText(data.record_count)} records). Country tables are separated by meaning because patent office, family coverage, and priority country answer different questions.`
      ));

      const grid = make("div", "analysis-grid");
      renderLensPanels(grid, data.lens_panels || {});
      grid.appendChild(reviewStatusPanel(data.review_totals || {}));
      grid.appendChild(codePrecisionPanel(data.code_precision || []));
      analysisEl.appendChild(grid);
    }

    function renderLensPanels(grid, panels) {
      grid.appendChild(tablePanel(
        "Patent Documents Over Time",
        ["Year", "Patent documents", "Applications", "Earliest priorities"],
        (panels.timeline || []).map((row) => [
          row.year,
          numberText(row.publication_documents),
          numberText(row.applications),
          numberText(row.earliest_priorities)
        ]),
        "wide",
        "Publication year is the closest match to Lens patent documents over time; application and priority years help reveal lag."
      ));
      grid.appendChild(counterPanel("Patent Documents By Jurisdiction", panels.jurisdictions || [], "Jurisdiction / office", jurisdictionLabel));
      grid.appendChild(countryRankPanel("Simple Family Countries", panels.simple_family_countries || [], "De-duplicated by simple family."));
      grid.appendChild(countryRankPanel("Extended Family Countries", panels.extended_family_countries || [], "De-duplicated by extended family."));
      grid.appendChild(countryRankPanel("Priority Countries", panels.priority_countries || [], "Parsed from priority number prefixes when available; use as an origin proxy only."));
      grid.appendChild(counterPanel("Document Types", panels.document_types || [], "Type"));
      grid.appendChild(counterPanel("Legal Status", panels.legal_status || [], "Status"));
      grid.appendChild(counterPanel("Top Applicants", panels.applicants || [], "Applicant"));
      grid.appendChild(counterPanel("Top Owners", panels.owners || [], "Owner"));
      grid.appendChild(counterPanel("Top Inventors", panels.inventors || [], "Inventor"));
      grid.appendChild(counterPanel("Top CPC Codes", panels.cpc_codes || [], "CPC code"));
      grid.appendChild(counterPanel("Top IPC Codes", panels.ipcr_codes || [], "IPC code"));
      grid.appendChild(counterPanel("Top USPC Codes", panels.uspc_codes || [], "USPC code"));
      grid.appendChild(tablePanel(
        "Top Cited Patent Records",
        ["Rank", "Display key", "Year", "Jurisdiction", "Cited by", "Title"],
        (panels.top_cited_records || []).map((row) => [
          row.rank,
          row.display_key || row.lens_id,
          row.publication_year,
          jurisdictionLabel(row.jurisdiction),
          numberText(row.cited_by),
          row.title
        ]),
        "wide",
        "These are records in the current CSV ranked by Cited by Patent Count."
      ));
      grid.appendChild(tablePanel(
        "Top Cited Patent References",
        ["Rank", "Cited patent", "Count"],
        (panels.cited_patent_references || []).map((row) => [
          row.rank,
          row.cited_patent,
          numberText(row.count)
        ]),
        "",
        "Shown only when the CSV export includes cited-patent reference fields."
      ));
      grid.appendChild(tablePanel(
        "Publication Lag Cutoffs",
        ["Cutoff", "Publication year <=", "Records", "Top offices"],
        (panels.lag_cutoffs || []).map((row) => [
          row.label,
          row.cutoff_year || "All",
          numberText(row.records),
          (row.patent_office_top || []).slice(0, 5).map((item) => `${item.country} ${item.count}`).join(", ")
        ]),
        "wide",
        "Use the 2/5/7-year versions when recent patent upload or publication lag may distort rankings."
      ));
    }

    function counterPanel(title, rows, labelName, formatter) {
      return tablePanel(title, [labelName, "Count", "Records %"], rows.map((row) => [
        formatter ? formatter(row.label) : row.label,
        numberText(row.count),
        `${numberText(row.record_pct, 1)}%`
      ]));
    }

    function countryRankPanel(title, rows, help) {
      return tablePanel(title, ["Rank", "Country", "Count"], rows.map((row) => [
        row.rank,
        jurisdictionLabel(row.country),
        numberText(row.count)
      ]), "", help);
    }

    function reviewStatusPanel(review) {
      const panel = tablePanel("Review Status", ["Metric", "Value"], [
        ["Relevant", numberText(review.relevant)],
        ["Not relevant", numberText(review.not_relevant)],
        ["Uncertain", numberText(review.uncertain)],
        ["Unreviewed", numberText(review.unreviewed)],
        ["Precision", `${numberText(review.precision_pct, 1)}%`]
      ]);
      const exportButton = make("button", "button", "Export labels");
      exportButton.type = "button";
      exportButton.addEventListener("click", () => {
        window.location.href = "/api/review_labels_export";
      });
      panel.appendChild(exportButton);
      return panel;
    }

    function codePrecisionPanel(rows) {
      return tablePanel("Precision By Code", ["System", "Code", "Reviewed", "Relevant", "Not rel.", "Uncertain", "Precision"], rows.map((row) => [
        row.system,
        row.code,
        numberText(row.reviewed),
        numberText(row.relevant),
        numberText(row.not_relevant),
        numberText(row.uncertain),
        `${numberText(row.precision_pct, 1)}%`
      ]), "wide");
    }

    function tablePanel(title, headers, rows, extraClass = "", helpText = "") {
      const panel = make("section", `analysis-panel ${extraClass}`.trim());
      addPanelHead(panel, title);
      if (helpText) panel.appendChild(make("div", "analysis-help", helpText));
      panel.appendChild(metricTable(headers, rows));
      return panel;
    }

    function addPanelHead(panel, title) {
      const head = make("div", "panel-head");
      head.appendChild(make("h2", "", title));
      const copy = make("button", "button", "Copy");
      copy.type = "button";
      copy.addEventListener("click", () => copyPanelTables(panel, copy));
      head.appendChild(copy);
      panel.appendChild(head);
    }

    async function copyPanelTables(panel, button) {
      const tables = Array.from(panel.querySelectorAll("table"));
      const textValue = tables.map((table) => (
        Array.from(table.rows).map((row) => (
          Array.from(row.cells).map((cell) => cell.textContent.trim()).join("\t")
        )).join("\n")
      )).join("\n\n");

      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(textValue);
        } else {
          const textarea = document.createElement("textarea");
          textarea.value = textValue;
          textarea.style.position = "fixed";
          textarea.style.left = "-9999px";
          document.body.appendChild(textarea);
          textarea.focus();
          textarea.select();
          document.execCommand("copy");
          textarea.remove();
        }
        const old = button.textContent;
        button.textContent = "Copied";
        window.setTimeout(() => { button.textContent = old; }, 900);
      } catch (error) {
        button.textContent = "Copy failed";
        window.setTimeout(() => { button.textContent = "Copy"; }, 1200);
      }
    }

    function metricTable(headers, rows) {
      const wrap = make("div", "metric-table-wrap");
      const table = make("table", "metric-table");
      const thead = document.createElement("thead");
      const headRow = document.createElement("tr");
      headers.forEach((header) => headRow.appendChild(make("th", "", header)));
      thead.appendChild(headRow);
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      if (!rows.length) {
        const row = document.createElement("tr");
        const cell = make("td", "muted", "No values.");
        cell.colSpan = headers.length;
        row.appendChild(cell);
        tbody.appendChild(row);
      }
      rows.forEach((values) => {
        const row = document.createElement("tr");
        values.forEach((value) => row.appendChild(make("td", "", value)));
        tbody.appendChild(row);
      });
      table.appendChild(tbody);
      wrap.appendChild(table);
      return wrap;
    }

    function renderRecords(records, resetOffset) {
      if (resetOffset) resultsEl.textContent = "";
      if (!records.length && resetOffset) {
        resultsEl.appendChild(make("div", "empty-results", "No matches."));
        return;
      }

      records.forEach((record) => {
        const button = make("button", "record");
        button.type = "button";
        button.dataset.id = record.id;
        button.addEventListener("click", () => selectRecord(record.id));

        const title = make("div", "record-title", record.title || "(Untitled)");
        const meta = make("div", "record-meta");
        [
          record.display_key,
          record.publication_date,
          record.jurisdiction,
          record.document_type
        ].filter(Boolean).forEach((value) => meta.appendChild(make("span", "", value)));

        const applicant = make("div", "muted", record.applicants || "No applicant listed");
        const foot = make("div", "record-foot");
        if (record.legal_status) foot.appendChild(pill(record.legal_status, statusClass(record.legal_status)));
        if (record.kind) foot.appendChild(pill(record.kind, "kind"));
        foot.appendChild(make("span", "", `Cited by ${numberText(record.cited_by)}`));
        foot.appendChild(make("span", "", `Family ${numberText(record.extended_family_size)}`));

        button.append(title, meta, applicant, foot);
        resultsEl.appendChild(button);
      });
    }

    async function selectRecord(id) {
      state.selectedId = id;
      document.querySelectorAll(".record").forEach((node) => {
        node.classList.toggle("selected", node.dataset.id === id);
      });
      detailEl.innerHTML = "";
      detailEl.appendChild(make("div", "empty-detail", "Loading record..."));

      try {
        const data = await getJson(`/api/record?id=${encodeURIComponent(id)}`);
        renderDetail(data);
      } catch (error) {
        detailEl.innerHTML = "";
        detailEl.appendChild(make("div", "notice", error.message));
      }
    }

    function fieldRow(label, value) {
      const labelEl = make("div", "info-label", label);
      const valueEl = make("div", "info-value");
      if (value instanceof Node) {
        valueEl.appendChild(value);
      } else {
        valueEl.textContent = text(value) || "-";
      }
      return [labelEl, valueEl];
    }

    function chipList(items) {
      const wrap = make("div", "chips");
      if (!items || !items.length) {
        wrap.appendChild(make("span", "muted", "-"));
        return wrap;
      }
      items.forEach((item) => wrap.appendChild(pill(item)));
      return wrap;
    }

    function linkValue(url) {
      if (!url) return "-";
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.target = "_blank";
      anchor.rel = "noreferrer";
      anchor.textContent = url;
      return anchor;
    }

    function section(title, rows, open = true) {
      const details = document.createElement("details");
      details.open = open;
      details.appendChild(make("summary", "", title));
      const body = make("div", "section-body");
      const grid = make("div", "info-grid");
      rows.forEach(([label, value]) => grid.append(...fieldRow(label, value)));
      body.appendChild(grid);
      details.appendChild(body);
      return details;
    }

    function textSection(title, value, open = false) {
      const details = document.createElement("details");
      details.open = open;
      details.appendChild(make("summary", "", title));
      const body = make("div", "section-body");
      body.appendChild(make("div", "wide-text", value || "-"));
      details.appendChild(body);
      return details;
    }

    function reviewBox(recordId, review) {
      const box = make("div", "review-box");
      box.appendChild(make("strong", "", "Review label"));
      let selected = (review && review.label) || "";
      const buttons = make("div", "button-row");
      const options = [
        ["relevant", "Relevant"],
        ["not_relevant", "Not relevant"],
        ["uncertain", "Uncertain"],
        ["", "Clear"]
      ];
      options.forEach(([value, label]) => {
        const button = make("button", `button review-button${selected === value ? " active" : ""}`, label);
        button.type = "button";
        button.addEventListener("click", () => {
          selected = value;
          buttons.querySelectorAll(".review-button").forEach((node) => node.classList.remove("active"));
          button.classList.add("active");
        });
        buttons.appendChild(button);
      });
      const noteField = make("div", "field");
      const noteLabel = document.createElement("label");
      noteLabel.textContent = "Note";
      const note = document.createElement("textarea");
      note.value = (review && review.note) || "";
      noteField.append(noteLabel, note);
      const status = make("div", "open-status", review && review.updated ? `Last updated ${review.updated}` : "");
      const save = make("button", "button primary", "Save review");
      save.type = "button";
      save.addEventListener("click", async () => {
        status.textContent = "Saving review...";
        try {
          const data = await postJson("/api/review_label", { id: recordId, label: selected, note: note.value });
          status.textContent = data.review.updated ? `Saved ${data.review.updated}` : "Review cleared.";
          if (state.view === "analysis") loadAnalysis();
        } catch (error) {
          status.textContent = error.message;
        }
      });
      box.append(buttons, noteField, save, status);
      return box;
    }

    function renderDetail(data) {
      const record = data.record;
      const lists = data.lists;
      detailEl.innerHTML = "";

      const head = make("div", "detail-head");
      head.appendChild(make("h2", "", record.Title || "(Untitled)"));
      const meta = make("div", "record-meta");
      [record["Display Key"], record["Publication Date"], record.Jurisdiction, record["Document Type"]]
        .filter(Boolean)
        .forEach((value) => meta.appendChild(make("span", "", value)));
      if (record["Legal Status"]) meta.appendChild(pill(record["Legal Status"], statusClass(record["Legal Status"])));
      head.appendChild(meta);
      if (record.Abstract) {
        head.appendChild(make("p", "abstract", record.Abstract));
      }
      detailEl.appendChild(head);
      detailEl.appendChild(reviewBox(data.id, data.review || {}));

      detailEl.appendChild(section("Identifiers", [
        ["Display Key", record["Display Key"]],
        ["Lens ID", record["Lens ID"]],
        ["Jurisdiction", record.Jurisdiction],
        ["Kind", record.Kind],
        ["URL", linkValue(record.URL)]
      ]));

      detailEl.appendChild(section("Dates", [
        ["Publication Date", record["Publication Date"]],
        ["Publication Year", record["Publication Year"]],
        ["Application Number", record["Application Number"]],
        ["Application Date", record["Application Date"]],
        ["Earliest Priority Date", record["Earliest Priority Date"]],
        ["Priority Numbers", record["Priority Numbers"]]
      ], false));

      detailEl.appendChild(section("People And Organizations", [
        ["Applicants", chipList(lists.Applicants)],
        ["Inventors", chipList(lists.Inventors)],
        ["Owners", chipList(lists.Owners)]
      ]));

      detailEl.appendChild(section("Citation Metrics", [
        ["Cites Patent Count", record["Cites Patent Count"]],
        ["Cited By Patent Count", record["Cited by Patent Count"]],
        ["NPL Citation Count", record["NPL Citation Count"]],
        ["NPL Resolved Citation Count", record["NPL Resolved Citation Count"]],
        ["Has Full Text", record["Has Full Text"]]
      ]));

      detailEl.appendChild(section("Classifications", [
        ["CPC", chipList(lists["CPC Classifications"])],
        ["IPCR", chipList(lists["IPCR Classifications"])],
        ["US", chipList(lists["US Classifications"])]
      ], false));

      detailEl.appendChild(section("Family", [
        ["Simple Family Size", record["Simple Family Size"]],
        ["Simple Family Jurisdictions", chipList(lists["Simple Family Member Jurisdictions"])],
        ["Simple Family Members", chipList(lists["Simple Family Members"])],
        ["Extended Family Size", record["Extended Family Size"]],
        ["Extended Family Jurisdictions", chipList(lists["Extended Family Member Jurisdictions"])],
        ["Extended Family Members", chipList(lists["Extended Family Members"])]
      ], false));

      detailEl.appendChild(section("Resolved NPL", [
        ["Resolved Lens IDs", chipList(lists["NPL Resolved Lens ID(s)"])],
        ["Resolved External IDs", chipList(lists["NPL Resolved External ID(s)"])]
      ], false));

      detailEl.appendChild(textSection("NPL Citations", record["NPL Citations"], false));
      detailEl.appendChild(textSection("Raw Record", JSON.stringify(record, null, 2), false));
    }

    function exportVosviewer(kind) {
      const query = filterParams();
      query.set("kind", kind);
      query.set("sort", controls.sort.value);
      exportStatus.textContent = `Preparing ${kind} export...`;
      window.location.href = `/api/vosviewer_raw_export?${query.toString()}`;
      window.setTimeout(() => {
        exportStatus.textContent = `Downloaded ${kind} export for the current filters.`;
      }, 700);
    }

    function debounce(fn, delay) {
      let timer = 0;
      return (...args) => {
        window.clearTimeout(timer);
        timer = window.setTimeout(() => fn(...args), delay);
      };
    }

    document.getElementById("applyButton").addEventListener("click", () => loadRecords(true));
    document.getElementById("resetButton").addEventListener("click", () => {
      resetFilters();
      loadRecords(true);
    });
    moreButton.addEventListener("click", () => loadRecords(false));
    insightsTab.addEventListener("click", () => setView("insights"));
    analysisTab.addEventListener("click", () => setView("analysis"));
    recordsTab.addEventListener("click", () => setView("records"));
    openCsvButton.addEventListener("click", openCsvFile);
    exportCorpusButton.addEventListener("click", () => exportVosviewer("corpus"));
    exportScoresButton.addEventListener("click", () => exportVosviewer("scores"));
    exportMetadataButton.addEventListener("click", () => exportVosviewer("metadata"));
    exportThesaurusButton.addEventListener("click", () => exportVosviewer("thesaurus"));

    controls.search.addEventListener("input", debounce(() => loadRecords(true), 300));
    ["year", "jurisdiction", "status", "type", "applicant", "cpc", "ipcr", "us_class", "sort"].forEach((name) => {
      controls[name].addEventListener("change", () => loadRecords(true));
    });

    setView("insights");
    loadMetadata()
      .then(() => loadRecords(true))
      .catch((error) => {
        document.getElementById("fileMeta").textContent = "CSV could not be loaded.";
        resultsEl.textContent = "";
        resultsEl.appendChild(make("div", "notice", error.message));
        insightsEl.textContent = "";
        insightsEl.appendChild(make("div", "notice", error.message));
      });
  </script>
</body>
</html>
"""


def split_multi(value: str | None) -> list[str]:
    if not value:
        return []
    seen: set[str] = set()
    items: list[str] = []
    for part in str(value).split(";;"):
        clean = part.strip()
        if clean and clean not in seen:
            seen.add(clean)
            items.append(clean)
    return items


def normalize_classification(code: str) -> str:
    return re.sub(r"\s+", "", code.strip().upper())


def classification_subclass(code: str) -> str:
    normalized = normalize_classification(code)
    match = re.match(r"^([A-HY]\d{2}[A-Z])", normalized)
    if match:
        return match.group(1)
    return normalized.split("/")[0] if normalized else ""


def clean_owner_name(value: str) -> str:
    return OWNER_DATE_RE.sub("", value).strip()


def family_key(row: dict[str, str], member_field: str) -> tuple[str, ...]:
    members = split_multi(row.get(member_field))
    if members:
        return tuple(sorted(members))
    return (row.get("_id", ""),)


def decode_csv_bytes(contents: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return contents.decode(encoding)
        except UnicodeDecodeError:
            pass
    return contents.decode("utf-8", errors="replace")


def to_int(value: Any) -> int:
    try:
        return int(str(value or "0").replace(",", "").strip() or 0)
    except ValueError:
        return 0


def parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.min
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return datetime.min


def year_from_date(value: str | None) -> int:
    if not value:
        return 0
    text = str(value).strip()
    if re.match(r"^\d{4}$", text):
        return int(text)
    parsed = parse_date(text)
    if parsed != datetime.min:
        return parsed.year
    match = re.search(r"(19|20)\d{2}", text)
    return int(match.group(0)) if match else 0


def vos_score_value(row: dict[str, str], field: str, kind: str) -> int:
    if kind == "year":
        return year_from_date(row.get(field))
    return to_int(row.get(field))


def clean_vos_text(value: str) -> str:
    value = value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", value).strip()


def safe_download_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(value).stem).strip("._")
    return stem or "lens_patents"


def percent(part: int | float, total: int | float, digits: int = 1) -> float:
    return round((part / total) * 100, digits) if total else 0.0


def median(values: list[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return round((ordered[middle - 1] + ordered[middle]) / 2, 2)


def percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    index = (len(ordered) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def split_scope_terms(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = re.split(r"[\n,;]+", str(value or ""))
    seen: set[str] = set()
    terms: list[str] = []
    for item in raw_items:
        clean = item.strip()
        if clean and clean.lower() not in seen:
            seen.add(clean.lower())
            terms.append(clean)
    return terms


def normalize_scope(raw: dict[str, Any], index: int = 0) -> dict[str, Any]:
    name = str(raw.get("name") or f"Scope {index + 1}").strip()
    scope_id = str(raw.get("id") or safe_download_stem(name).lower() or f"scope_{index + 1}").strip()
    scope_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", scope_id).strip("._").lower() or f"scope_{index + 1}"
    filters = raw.get("filters") if isinstance(raw.get("filters"), dict) else {}
    return {
        "id": scope_id,
        "name": name,
        "keywords": split_scope_terms(raw.get("keywords")),
        "cpc": [normalize_classification(term) for term in split_scope_terms(raw.get("cpc"))],
        "ipcr": [normalize_classification(term) for term in split_scope_terms(raw.get("ipcr"))],
        "uspc": [normalize_classification(term) for term in split_scope_terms(raw.get("uspc"))],
        "filters": {
            "jurisdiction": split_scope_terms(filters.get("jurisdiction") or raw.get("jurisdiction")),
            "status": split_scope_terms(filters.get("status") or raw.get("status")),
            "document_type": split_scope_terms(filters.get("document_type") or raw.get("document_type")),
            "applicant": split_scope_terms(filters.get("applicant") or raw.get("applicant")),
        },
    }


def scope_has_criteria(scope: dict[str, Any]) -> bool:
    if scope.get("keywords") or scope.get("cpc") or scope.get("ipcr") or scope.get("uspc"):
        return True
    return any(scope.get("filters", {}).get(key) for key in FILTER_FIELDS)


def row_review_key(row: dict[str, str]) -> str:
    return row.get("Lens ID") or row.get("Display Key") or row.get("_id") or row.get("_row_number", "")


def row_year(row: dict[str, str], field: str) -> int:
    if field == "Publication Year":
        return to_int(row.get(field))
    return year_from_date(row.get(field))


def classification_values(row: dict[str, str], field: str) -> list[str]:
    return [normalize_classification(code) for code in split_multi(row.get(field))]


def matches_classification(values: list[str], needles: list[str]) -> bool:
    if not needles:
        return True
    return any(value == needle or value.startswith(needle) for value in values for needle in needles)


def matches_any_text(text_value: str, needles: list[str]) -> bool:
    if not needles:
        return True
    haystack = text_value.lower()
    return any(needle.lower() in haystack for needle in needles)


def matches_filter_values(row: dict[str, str], field: str, values: list[str]) -> bool:
    if not values:
        return True
    if field == "Applicants":
        current = set(split_multi(row.get(field)))
        return any(value in current for value in values)
    return row.get(field, "") in values


def row_matches_scope(row: dict[str, str], scope: dict[str, Any]) -> bool:
    if not scope_has_criteria(scope):
        return True
    text_blob = f"{row.get('Title', '')} {row.get('Abstract', '')}".lower()
    if not matches_any_text(text_blob, scope.get("keywords", [])):
        return False
    for key, field in CLASSIFICATION_FIELDS.items():
        if not matches_classification(classification_values(row, field), scope.get(key, [])):
            return False
    filters = scope.get("filters", {})
    for key, field in FILTER_FIELDS.items():
        if not matches_filter_values(row, field, filters.get(key, [])):
            return False
    return True


def priority_countries(row: dict[str, str]) -> list[str]:
    countries: list[str] = []
    seen: set[str] = set()
    values = split_multi(row.get("Priority Numbers"))
    if not values and row.get("Priority Numbers"):
        values = re.split(r"[;,]+", row.get("Priority Numbers", ""))
    for value in values:
        clean = value.strip().upper()
        match = re.match(r"^PCT/([A-Z]{2})", clean)
        if not match:
            match = re.match(r"^([A-Z]{2})[\s/_-]*[A-Z0-9]", clean)
        if match:
            country = match.group(1)
            if country not in seen:
                seen.add(country)
                countries.append(country)
    return countries


def public_row(row: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in row.items() if not key.startswith("_")}


class AppState:
    def __init__(self, directory: Path):
        self.directory = directory
        self.scopes_path = directory / "scopes.json"
        self.review_path = directory / "review_labels.json"
        self._lock = threading.Lock()

    def scopes(self) -> list[dict[str, Any]]:
        with self._lock:
            payload = self._read_json(self.scopes_path, [])
        if not isinstance(payload, list):
            payload = []
        return [normalize_scope(scope, index) for index, scope in enumerate(payload) if isinstance(scope, dict)]

    def save_scope(self, raw_scope: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            scopes = self._read_json(self.scopes_path, [])
            if not isinstance(scopes, list):
                scopes = []
            normalized = normalize_scope(raw_scope, len(scopes))
            kept = [
                normalize_scope(scope, index)
                for index, scope in enumerate(scopes)
                if isinstance(scope, dict) and normalize_scope(scope, index)["id"] != normalized["id"]
            ]
            kept.append(normalized)
            self._write_json(self.scopes_path, kept)
        return self.scopes()

    def delete_scope(self, scope_id: str) -> list[dict[str, Any]]:
        with self._lock:
            scopes = self._read_json(self.scopes_path, [])
            if not isinstance(scopes, list):
                scopes = []
            kept = [
                normalize_scope(scope, index)
                for index, scope in enumerate(scopes)
                if isinstance(scope, dict) and normalize_scope(scope, index)["id"] != scope_id
            ]
            self._write_json(self.scopes_path, kept)
        return self.scopes()

    def labels(self) -> dict[str, dict[str, str]]:
        with self._lock:
            payload = self._read_json(self.review_path, {})
        if not isinstance(payload, dict):
            return {}
        labels: dict[str, dict[str, str]] = {}
        for key, value in payload.items():
            if isinstance(value, dict):
                label = str(value.get("label", ""))
                if label in VALID_REVIEW_LABELS:
                    labels[str(key)] = {
                        "label": label,
                        "note": str(value.get("note", "")),
                        "updated": str(value.get("updated", "")),
                    }
        return labels

    def label_for(self, review_key: str) -> dict[str, str]:
        return self.labels().get(review_key, {"label": "", "note": "", "updated": ""})

    def save_label(self, review_key: str, label: str, note: str) -> dict[str, str]:
        if label not in VALID_REVIEW_LABELS:
            raise ValueError("Review label must be relevant, not_relevant, uncertain, or blank.")
        with self._lock:
            labels = self._read_json(self.review_path, {})
            if not isinstance(labels, dict):
                labels = {}
            if label:
                labels[review_key] = {
                    "label": label,
                    "note": note.strip(),
                    "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
            else:
                labels.pop(review_key, None)
            self._write_json(self.review_path, labels)
        return self.label_for(review_key)

    def labels_csv(self) -> bytes:
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=["record_key", "label", "note", "updated"], lineterminator="\n")
        writer.writeheader()
        for key, value in sorted(self.labels().items()):
            writer.writerow({
                "record_key": key,
                "label": value.get("label", ""),
                "note": value.get("note", ""),
                "updated": value.get("updated", ""),
            })
        return output.getvalue().encode("utf-8-sig")

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _write_json(self, path: Path, payload: Any) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class PatentDataset:
    def __init__(self, csv_path: Path):
        self.csv_path = csv_path
        self.source_name = csv_path.name
        self.source_path = str(csv_path)
        self.last_modified = ""
        self._uploaded = False
        self.rows: list[dict[str, str]] = []
        self.fieldnames: list[str] = []
        self.record_by_id: dict[str, dict[str, str]] = {}
        self._mtime = 0.0
        self._lock = threading.Lock()
        if csv_path.exists():
            self.load()
        else:
            self._set_rows([], [])
            self.last_modified = "file not found; use Open CSV"
            self._uploaded = True

    def ensure_current(self) -> None:
        if self._uploaded:
            return
        try:
            mtime = self.csv_path.stat().st_mtime
        except FileNotFoundError:
            raise FileNotFoundError(f"CSV file not found: {self.csv_path}")
        if mtime != self._mtime:
            with self._lock:
                if mtime != self._mtime:
                    self.load()

    def load(self) -> None:
        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {self.csv_path}")

        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows, fieldnames = self._read_rows(handle)

        stat = self.csv_path.stat()
        self._set_rows(rows, fieldnames)
        self.source_name = self.csv_path.name
        self.source_path = str(self.csv_path)
        self.last_modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        self._uploaded = False
        self._mtime = stat.st_mtime

    def load_uploaded(self, filename: str, contents: bytes) -> dict[str, Any]:
        text = decode_csv_bytes(contents)
        with io.StringIO(text, newline="") as handle:
            rows, fieldnames = self._read_rows(handle)

        with self._lock:
            self._set_rows(rows, fieldnames)
            self.source_name = Path(filename or "uploaded.csv").name
            self.source_path = "Browser upload"
            self.last_modified = datetime.now().strftime("%Y-%m-%d %H:%M")
            self._uploaded = True
            self._mtime = 0.0
        return self.metadata()

    def _read_rows(self, handle: Any) -> tuple[list[dict[str, str]], list[str]]:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV file needs a header row.")

        rows = []
        id_counts: Counter[str] = Counter()
        for index, row in enumerate(reader, start=1):
            clean_row = {key: (value or "").strip() for key, value in row.items() if key is not None}
            clean_row["_row_number"] = str(index)
            base_id = clean_row.get("Lens ID") or clean_row.get("Display Key") or str(index)
            id_counts[base_id] += 1
            clean_row["_id"] = base_id if id_counts[base_id] == 1 else f"{base_id}#{id_counts[base_id]}"
            clean_row["_search"] = " ".join(clean_row.get(field, "") for field in SEARCH_FIELDS).lower()
            rows.append(clean_row)
        return rows, list(reader.fieldnames or [])

    def _set_rows(self, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
        self.rows = rows
        self.fieldnames = fieldnames
        self.record_by_id = {row["_id"]: row for row in rows}

    def metadata(self) -> dict[str, Any]:
        self.ensure_current()
        years = sorted(
            {row.get("Publication Year", "") for row in self.rows if row.get("Publication Year", "")},
            reverse=True,
        )
        applicants: Counter[str] = Counter()
        cpc_classes: Counter[str] = Counter()
        ipcr_classes: Counter[str] = Counter()
        us_classes: Counter[str] = Counter()
        for row in self.rows:
            applicants.update(split_multi(row.get("Applicants")))
            cpc_classes.update(normalize_classification(code) for code in split_multi(row.get("CPC Classifications")))
            ipcr_classes.update(normalize_classification(code) for code in split_multi(row.get("IPCR Classifications")))
            us_classes.update(normalize_classification(code) for code in split_multi(row.get("US Classifications")))

        return {
            "file_name": self.source_name,
            "file_path": self.source_path,
            "last_modified": self.last_modified,
            "row_count": len(self.rows),
            "columns": self.fieldnames,
            "years": years,
            "jurisdictions": self._common("Jurisdiction"),
            "statuses": self._common("Legal Status"),
            "document_types": self._common("Document Type"),
            "applicants": applicants.most_common(120),
            "cpc_classes": cpc_classes.most_common(120),
            "ipcr_classes": ipcr_classes.most_common(120),
            "us_classes": us_classes.most_common(120),
        }

    def _common(self, field: str) -> list[tuple[str, int]]:
        values = Counter(row.get(field, "") for row in self.rows if row.get(field, ""))
        return values.most_common()

    def filtered_records(self, query: dict[str, list[str]]) -> tuple[list[dict[str, str]], dict[str, Any]]:
        self.ensure_current()
        records = self.rows

        search = first(query, "search").lower().strip()
        if search:
            tokens = [token for token in search.split() if token]
            records = [row for row in records if all(token in row.get("_search", "") for token in tokens)]

        exact_filters = {
            "year": "Publication Year",
            "jurisdiction": "Jurisdiction",
            "status": "Legal Status",
            "document_type": "Document Type",
        }
        for query_name, field_name in exact_filters.items():
            value = first(query, query_name)
            if value:
                records = [row for row in records if row.get(field_name, "") == value]

        applicant = first(query, "applicant")
        if applicant:
            records = [row for row in records if applicant in split_multi(row.get("Applicants"))]

        cpc = first(query, "cpc")
        if cpc:
            records = [row for row in records if cpc in self.normalized_split(row, "CPC Classifications")]

        ipcr = first(query, "ipcr")
        if ipcr:
            records = [row for row in records if ipcr in self.normalized_split(row, "IPCR Classifications")]

        us_class = first(query, "us_class")
        if us_class:
            records = [row for row in records if us_class in self.normalized_split(row, "US Classifications")]

        records = self._sort(records, first(query, "sort") or "publication_date")
        metrics = self.metrics(records)
        return records, metrics

    def normalized_split(self, row: dict[str, str], field: str) -> list[str]:
        return [normalize_classification(code) for code in split_multi(row.get(field))]

    def _sort(self, records: list[dict[str, str]], sort_name: str) -> list[dict[str, str]]:
        if sort_name == "title":
            return sorted(records, key=lambda row: row.get("Title", "").lower())
        if sort_name == "cited_by":
            return sorted(records, key=lambda row: to_int(row.get("Cited by Patent Count")), reverse=True)
        if sort_name == "cites":
            return sorted(records, key=lambda row: to_int(row.get("Cites Patent Count")), reverse=True)
        if sort_name == "family_size":
            return sorted(records, key=lambda row: to_int(row.get("Extended Family Size")), reverse=True)
        return sorted(records, key=lambda row: parse_date(row.get("Publication Date")), reverse=True)

    def metrics(self, records: list[dict[str, str]]) -> dict[str, Any]:
        statuses = Counter(row.get("Legal Status", "") for row in records)
        doc_types = Counter(row.get("Document Type", "") for row in records)
        cited_by = [to_int(row.get("Cited by Patent Count")) for row in records]
        simple_families = {family_key(row, "Simple Family Members") for row in records}
        return {
            "total": len(records),
            "active_or_pending": statuses.get("ACTIVE", 0) + statuses.get("PENDING", 0),
            "granted": doc_types.get("Granted Patent", 0),
            "simple_families": len(simple_families),
            "avg_cited_by": round(sum(cited_by) / len(cited_by), 1) if cited_by else 0,
        }

    def breakdowns(self, records: list[dict[str, str]]) -> dict[str, list[tuple[str, int]]]:
        return {
            "patent_offices": self.count_field(records, "Jurisdiction", 30),
            "simple_family_jurisdictions": self.count_family_jurisdictions(
                records,
                "Simple Family Members",
                "Simple Family Member Jurisdictions",
                30,
            ),
            "extended_family_jurisdictions": self.count_family_jurisdictions(
                records,
                "Extended Family Members",
                "Extended Family Member Jurisdictions",
                30,
            ),
            "applicants": self.count_split_field(records, "Applicants", 25),
            "owners": self.count_owners(records, 25),
            "cpc_classes": self.count_classifications(records, "CPC Classifications", 30),
            "ipcr_classes": self.count_classifications(records, "IPCR Classifications", 30),
            "us_classes": self.count_classifications(records, "US Classifications", 30),
            "cpc_subclasses": self.count_classification_subclasses(records, "CPC Classifications", 30),
            "ipcr_subclasses": self.count_classification_subclasses(records, "IPCR Classifications", 30),
            "legal_status": self.count_field(records, "Legal Status", 12),
            "publication_years": self.count_years(records),
        }

    def count_field(self, records: list[dict[str, str]], field: str, limit: int) -> list[tuple[str, int]]:
        counts = Counter(row.get(field, "") for row in records if row.get(field, ""))
        return counts.most_common(limit)

    def count_split_field(self, records: list[dict[str, str]], field: str, limit: int) -> list[tuple[str, int]]:
        counts: Counter[str] = Counter()
        for row in records:
            counts.update(split_multi(row.get(field)))
        return counts.most_common(limit)

    def count_classifications(self, records: list[dict[str, str]], field: str, limit: int) -> list[tuple[str, int]]:
        counts: Counter[str] = Counter()
        for row in records:
            counts.update(normalize_classification(code) for code in split_multi(row.get(field)))
        return counts.most_common(limit)

    def count_classification_subclasses(
        self,
        records: list[dict[str, str]],
        field: str,
        limit: int,
    ) -> list[tuple[str, int]]:
        counts: Counter[str] = Counter()
        for row in records:
            counts.update(classification_subclass(code) for code in split_multi(row.get(field)))
        counts.pop("", None)
        return counts.most_common(limit)

    def count_owners(self, records: list[dict[str, str]], limit: int) -> list[tuple[str, int]]:
        counts: Counter[str] = Counter()
        for row in records:
            owners = [clean_owner_name(owner) for owner in split_multi(row.get("Owners"))]
            counts.update(owner for owner in owners if owner)
        return counts.most_common(limit)

    def count_family_jurisdictions(
        self,
        records: list[dict[str, str]],
        member_field: str,
        jurisdiction_field: str,
        limit: int,
    ) -> list[tuple[str, int]]:
        counts: Counter[str] = Counter()
        seen_pairs: set[tuple[tuple[str, ...], str]] = set()
        for row in records:
            key = family_key(row, member_field)
            jurisdictions = split_multi(row.get(jurisdiction_field)) or split_multi(row.get("Jurisdiction"))
            for jurisdiction in jurisdictions:
                pair = (key, jurisdiction)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    counts[jurisdiction] += 1
        return counts.most_common(limit)

    def count_years(self, records: list[dict[str, str]]) -> list[tuple[str, int]]:
        counts = Counter(row.get("Publication Year", "") for row in records if row.get("Publication Year", ""))
        return sorted(counts.items(), key=lambda pair: pair[0], reverse=True)

    def analysis(
        self,
        query: dict[str, list[str]],
        saved_scopes: list[dict[str, Any]],
        labels: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        records, _metrics = self.filtered_records(query)
        scopes = [{"id": "current", "name": "Current filter slice", "keywords": [], "cpc": [], "ipcr": [], "uspc": [], "filters": {}}]
        scopes.extend(saved_scopes)
        scope_rows = {
            scope["id"]: [row for row in records if row_matches_scope(row, scope)]
            for scope in scopes
        }
        citation_percentiles = self.year_normalized_citation_percentiles(records)
        return {
            "record_count": len(records),
            "scopes": scopes,
            "scope_summaries": [
                self.scope_summary(scope, scope_rows[scope["id"]], labels, citation_percentiles)
                for scope in scopes
            ],
            "overlap_matrix": self.overlap_matrix(scopes, scope_rows),
            "classification_lift": self.classification_lift(records, scopes, scope_rows),
            "code_precision": self.code_precision(records, labels),
            "country_sensitivity": self.country_sensitivity(scopes, scope_rows),
            "lens_panels": self.lens_analysis_panels(records),
            "lag_timing": self.lag_timing(records),
            "saved_scopes": saved_scopes,
            "review_totals": self.review_summary(records, labels),
        }

    def lens_analysis_panels(self, records: list[dict[str, str]]) -> dict[str, Any]:
        total = len(records)
        return {
            "timeline": self.timeline_rows(records),
            "jurisdictions": self.counter_rows(Counter(row.get("Jurisdiction", "") for row in records if row.get("Jurisdiction", "")), total),
            "simple_family_countries": self.country_rows(self.family_country_counter(records, "Simple Family Members", "Simple Family Member Jurisdictions")),
            "extended_family_countries": self.country_rows(self.family_country_counter(records, "Extended Family Members", "Extended Family Member Jurisdictions")),
            "priority_countries": self.country_rows(self.priority_country_counter(records)),
            "document_types": self.counter_rows(Counter(row.get("Document Type", "") for row in records if row.get("Document Type", "")), total),
            "legal_status": self.counter_rows(Counter(row.get("Legal Status", "") for row in records if row.get("Legal Status", "")), total),
            "applicants": self.counter_rows(self.split_counter(records, "Applicants"), total),
            "owners": self.counter_rows(self.owner_counter(records), total),
            "inventors": self.counter_rows(self.split_counter(records, "Inventors"), total),
            "cpc_codes": self.counter_rows(self.classification_counter(records, "CPC Classifications"), total),
            "ipcr_codes": self.counter_rows(self.classification_counter(records, "IPCR Classifications"), total),
            "uspc_codes": self.counter_rows(self.classification_counter(records, "US Classifications"), total),
            "top_cited_records": self.top_cited_records(records),
            "cited_patent_references": self.cited_patent_reference_rows(records),
            "lag_cutoffs": self.lag_timing(records)["cutoffs"],
        }

    def timeline_rows(self, records: list[dict[str, str]]) -> list[dict[str, int]]:
        publication = Counter(row_year(row, "Publication Year") for row in records if row_year(row, "Publication Year"))
        application = Counter(row_year(row, "Application Date") for row in records if row_year(row, "Application Date"))
        priority = Counter(row_year(row, "Earliest Priority Date") for row in records if row_year(row, "Earliest Priority Date"))
        years = sorted(set(publication) | set(application) | set(priority))
        return [
            {
                "year": year,
                "publication_documents": publication.get(year, 0),
                "applications": application.get(year, 0),
                "earliest_priorities": priority.get(year, 0),
            }
            for year in years
        ]

    def split_counter(self, records: list[dict[str, str]], field: str) -> Counter[str]:
        counts: Counter[str] = Counter()
        for row in records:
            counts.update(split_multi(row.get(field)))
        return counts

    def owner_counter(self, records: list[dict[str, str]]) -> Counter[str]:
        counts: Counter[str] = Counter()
        for row in records:
            counts.update(owner for owner in (clean_owner_name(value) for value in split_multi(row.get("Owners"))) if owner)
        return counts

    def counter_rows(self, counts: Counter[str], total: int, limit: int = 25) -> list[dict[str, Any]]:
        return [
            {"label": label, "count": count, "record_pct": percent(count, total)}
            for label, count in counts.most_common(limit)
            if label
        ]

    def country_rows(self, counts: Counter[str], limit: int = 25) -> list[dict[str, Any]]:
        return [
            {"rank": index + 1, "country": country, "count": count}
            for index, (country, count) in enumerate(counts.most_common(limit))
            if country
        ]

    def top_cited_records(self, records: list[dict[str, str]], limit: int = 25) -> list[dict[str, Any]]:
        rows = sorted(records, key=lambda row: to_int(row.get("Cited by Patent Count")), reverse=True)
        return [
            {
                "rank": index + 1,
                "display_key": row.get("Display Key", ""),
                "lens_id": row.get("Lens ID", ""),
                "title": row.get("Title", ""),
                "jurisdiction": row.get("Jurisdiction", ""),
                "publication_year": row.get("Publication Year", ""),
                "cited_by": to_int(row.get("Cited by Patent Count")),
            }
            for index, row in enumerate(rows[:limit])
            if to_int(row.get("Cited by Patent Count"))
        ]

    def cited_patent_reference_rows(self, records: list[dict[str, str]], limit: int = 25) -> list[dict[str, Any]]:
        candidates = [
            "Cited Patents",
            "Cited Patent",
            "Cited Patent(s)",
            "Cited Patent Lens IDs",
            "Cited Patents Lens ID(s)",
            "Cited Lens IDs",
            "Patent Citations",
        ]
        counts: Counter[str] = Counter()
        fields = [field for field in candidates if field in self.fieldnames]
        for row in records:
            for field in fields:
                counts.update(split_multi(row.get(field)))
        return [
            {"rank": index + 1, "cited_patent": patent, "count": count}
            for index, (patent, count) in enumerate(counts.most_common(limit))
        ]

    def scope_summary(
        self,
        scope: dict[str, Any],
        records: list[dict[str, str]],
        labels: dict[str, dict[str, str]],
        citation_percentiles: dict[str, float],
    ) -> dict[str, Any]:
        total = len(records)
        simple_families = {family_key(row, "Simple Family Members") for row in records}
        extended_families = {family_key(row, "Extended Family Members") for row in records}
        cpc_counts = [len(classification_values(row, "CPC Classifications")) for row in records]
        ipcr_counts = [len(classification_values(row, "IPCR Classifications")) for row in records]
        uspc_counts = [len(classification_values(row, "US Classifications")) for row in records]
        cited = [to_int(row.get("Cited by Patent Count")) for row in records]
        family_sizes = [to_int(row.get("Extended Family Size")) for row in records]
        doc_types = Counter(row.get("Document Type", "") for row in records)
        statuses = Counter(row.get("Legal Status", "") for row in records)
        citation_scores = [citation_percentiles.get(row_review_key(row), 0.0) for row in records if row_review_key(row) in citation_percentiles]
        return {
            "id": scope["id"],
            "name": scope["name"],
            "records": total,
            "simple_families": len(simple_families),
            "extended_families": len(extended_families),
            "duplication_ratio": round(total / len(simple_families), 2) if simple_families else 0,
            "title_complete_pct": percent(sum(1 for row in records if row.get("Title")), total),
            "abstract_complete_pct": percent(sum(1 for row in records if row.get("Abstract")), total),
            "unique_cpc": len({code for row in records for code in classification_values(row, "CPC Classifications")}),
            "unique_ipcr": len({code for row in records for code in classification_values(row, "IPCR Classifications")}),
            "unique_uspc": len({code for row in records for code in classification_values(row, "US Classifications")}),
            "avg_cpc_per_patent": round(sum(cpc_counts) / total, 2) if total else 0,
            "avg_ipcr_per_patent": round(sum(ipcr_counts) / total, 2) if total else 0,
            "avg_uspc_per_patent": round(sum(uspc_counts) / total, 2) if total else 0,
            "cited_avg": round(sum(cited) / total, 2) if total else 0,
            "cited_median": median(cited),
            "cited_p90": percentile(cited, 0.9),
            "year_normalized_citation_pct": round(sum(citation_scores) / len(citation_scores), 1) if citation_scores else 0,
            "grant_rate_pct": percent(doc_types.get("Granted Patent", 0), total),
            "active_pending_rate_pct": percent(statuses.get("ACTIVE", 0) + statuses.get("PENDING", 0), total),
            "family_size_median": median(family_sizes),
            "family_size_p90": percentile(family_sizes, 0.9),
            "review": self.review_summary(records, labels),
        }

    def review_summary(self, records: list[dict[str, str]], labels: dict[str, dict[str, str]]) -> dict[str, Any]:
        counts = Counter()
        for row in records:
            label = labels.get(row_review_key(row), {}).get("label", "")
            counts[label or "unreviewed"] += 1
        reviewed_for_precision = counts["relevant"] + counts["not_relevant"]
        return {
            "relevant": counts["relevant"],
            "not_relevant": counts["not_relevant"],
            "uncertain": counts["uncertain"],
            "unreviewed": counts["unreviewed"],
            "reviewed": counts["relevant"] + counts["not_relevant"] + counts["uncertain"],
            "precision_pct": percent(counts["relevant"], reviewed_for_precision),
        }

    def overlap_matrix(
        self,
        scopes: list[dict[str, Any]],
        scope_rows: dict[str, list[dict[str, str]]],
    ) -> list[dict[str, Any]]:
        scope_ids = {scope["id"]: {row.get("_id", row_review_key(row)) for row in scope_rows[scope["id"]]} for scope in scopes}
        rows = []
        for left in scopes:
            cells = []
            left_ids = scope_ids[left["id"]]
            for right in scopes:
                right_ids = scope_ids[right["id"]]
                intersection = len(left_ids & right_ids)
                union = len(left_ids | right_ids)
                cells.append({
                    "scope_id": right["id"],
                    "intersection": intersection,
                    "jaccard_pct": percent(intersection, union),
                    "containment_pct": percent(intersection, len(left_ids)),
                })
            rows.append({"scope_id": left["id"], "scope_name": left["name"], "cells": cells})
        return rows

    def classification_lift(
        self,
        baseline_records: list[dict[str, str]],
        scopes: list[dict[str, Any]],
        scope_rows: dict[str, list[dict[str, str]]],
    ) -> dict[str, list[dict[str, Any]]]:
        baseline_total = max(1, len(baseline_records))
        baseline_counts = {
            key: self.classification_counter(baseline_records, field)
            for key, field in CLASSIFICATION_FIELDS.items()
        }
        result: dict[str, list[dict[str, Any]]] = {}
        for scope in scopes:
            records = scope_rows[scope["id"]]
            scope_total = max(1, len(records))
            rows: list[dict[str, Any]] = []
            for system, field in CLASSIFICATION_FIELDS.items():
                counts = self.classification_counter(records, field)
                for code, count in counts.items():
                    baseline_count = baseline_counts[system].get(code, 0)
                    baseline_rate = baseline_count / baseline_total
                    scope_rate = count / scope_total
                    lift = round(scope_rate / baseline_rate, 2) if baseline_rate else 0
                    rows.append({
                        "system": system.upper(),
                        "code": code,
                        "count": count,
                        "scope_pct": percent(count, len(records)),
                        "baseline_count": baseline_count,
                        "lift": lift,
                    })
            result[scope["id"]] = sorted(rows, key=lambda row: (-row["lift"], -row["count"], row["code"]))[:15]
        return result

    def classification_counter(self, records: list[dict[str, str]], field: str) -> Counter[str]:
        counts: Counter[str] = Counter()
        for row in records:
            counts.update(classification_values(row, field))
        counts.pop("", None)
        return counts

    def code_precision(self, records: list[dict[str, str]], labels: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
        code_rows: dict[tuple[str, str], list[dict[str, str]]] = {}
        for row in records:
            if labels.get(row_review_key(row), {}).get("label", "") not in {"relevant", "not_relevant", "uncertain"}:
                continue
            for system, field in CLASSIFICATION_FIELDS.items():
                for code in classification_values(row, field):
                    code_rows.setdefault((system.upper(), code), []).append(row)

        rows = []
        for (system, code), values in code_rows.items():
            review = self.review_summary(values, labels)
            if review["reviewed"]:
                rows.append({
                    "system": system,
                    "code": code,
                    **review,
                })
        return sorted(rows, key=lambda row: (-row["reviewed"], -row["precision_pct"], row["code"]))[:30]

    def country_sensitivity(
        self,
        scopes: list[dict[str, Any]],
        scope_rows: dict[str, list[dict[str, str]]],
    ) -> dict[str, Any]:
        by_scope: dict[str, Any] = {}
        for scope in scopes:
            records = scope_rows[scope["id"]]
            modes = {
                "patent_office": self.ranked_country_counts(Counter(row.get("Jurisdiction", "") for row in records if row.get("Jurisdiction", ""))),
                "simple_family": self.ranked_country_counts(self.family_country_counter(records, "Simple Family Members", "Simple Family Member Jurisdictions")),
                "extended_family": self.ranked_country_counts(self.family_country_counter(records, "Extended Family Members", "Extended Family Member Jurisdictions")),
                "priority_country": self.ranked_country_counts(self.priority_country_counter(records)),
            }
            by_scope[scope["id"]] = {
                "scope_name": scope["name"],
                "modes": modes,
                "mode_rank_deltas": self.rank_deltas(modes["patent_office"], modes["priority_country"]),
            }

        baseline = by_scope.get("current", {}).get("modes", {}).get("patent_office", [])
        for scope in scopes:
            by_scope[scope["id"]]["scope_rank_deltas"] = self.rank_deltas(baseline, by_scope[scope["id"]]["modes"]["patent_office"])
        return by_scope

    def family_country_counter(
        self,
        records: list[dict[str, str]],
        member_field: str,
        jurisdiction_field: str,
    ) -> Counter[str]:
        counts: Counter[str] = Counter()
        seen_pairs: set[tuple[tuple[str, ...], str]] = set()
        for row in records:
            key = family_key(row, member_field)
            for jurisdiction in split_multi(row.get(jurisdiction_field)) or split_multi(row.get("Jurisdiction")):
                pair = (key, jurisdiction)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    counts[jurisdiction] += 1
        return counts

    def priority_country_counter(self, records: list[dict[str, str]]) -> Counter[str]:
        counts: Counter[str] = Counter()
        seen_pairs: set[tuple[tuple[str, ...], str]] = set()
        for row in records:
            key = family_key(row, "Simple Family Members")
            for country in priority_countries(row):
                pair = (key, country)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    counts[country] += 1
        return counts

    def ranked_country_counts(self, counts: Counter[str], limit: int = 12) -> list[dict[str, Any]]:
        return [
            {"country": country, "count": count, "rank": index + 1}
            for index, (country, count) in enumerate(counts.most_common(limit))
        ]

    def rank_deltas(self, baseline: list[dict[str, Any]], comparison: list[dict[str, Any]]) -> list[dict[str, Any]]:
        baseline_ranks = {row["country"]: row["rank"] for row in baseline}
        comparison_ranks = {row["country"]: row["rank"] for row in comparison}
        countries = sorted(set(baseline_ranks) | set(comparison_ranks))
        rows = []
        missing_rank = max(len(countries), 1) + 1
        for country in countries:
            old_rank = baseline_ranks.get(country, missing_rank)
            new_rank = comparison_ranks.get(country, missing_rank)
            rows.append({
                "country": country,
                "baseline_rank": None if country not in baseline_ranks else old_rank,
                "comparison_rank": None if country not in comparison_ranks else new_rank,
                "delta": old_rank - new_rank,
            })
        return sorted(rows, key=lambda row: (-abs(row["delta"]), row["country"]))[:12]

    def lag_timing(self, records: list[dict[str, str]]) -> dict[str, Any]:
        current_year = datetime.now().year
        cutoffs = [
            {"label": "Raw", "years_excluded": 0, "cutoff_year": None},
            {"label": "2-year lag", "years_excluded": 2, "cutoff_year": current_year - 2},
            {"label": "5-year lag", "years_excluded": 5, "cutoff_year": current_year - 5},
            {"label": "7-year lag", "years_excluded": 7, "cutoff_year": current_year - 7},
        ]
        cutoff_rows = []
        for cutoff in cutoffs:
            cutoff_year = cutoff["cutoff_year"]
            subset = [
                row for row in records
                if cutoff_year is None or (row_year(row, "Publication Year") and row_year(row, "Publication Year") <= cutoff_year)
            ]
            cutoff_rows.append({
                **cutoff,
                "records": len(subset),
                "patent_office_top": self.ranked_country_counts(Counter(row.get("Jurisdiction", "") for row in subset if row.get("Jurisdiction", "")), 8),
            })
        return {
            "current_year": current_year,
            "cutoffs": cutoff_rows,
            "publication_years": self.year_counts(records, "Publication Year"),
            "application_years": self.year_counts(records, "Application Date"),
            "priority_years": self.year_counts(records, "Earliest Priority Date"),
        }

    def year_counts(self, records: list[dict[str, str]], field: str) -> list[dict[str, int]]:
        counts: Counter[int] = Counter()
        for row in records:
            year = row_year(row, field)
            if year:
                counts[year] += 1
        return [{"year": year, "count": count} for year, count in sorted(counts.items(), reverse=True)]

    def year_normalized_citation_percentiles(self, records: list[dict[str, str]]) -> dict[str, float]:
        by_year: dict[int, list[int]] = {}
        for row in records:
            year = row_year(row, "Publication Year")
            if year:
                by_year.setdefault(year, []).append(to_int(row.get("Cited by Patent Count")))
        ordered = {year: sorted(values) for year, values in by_year.items()}
        percentiles: dict[str, float] = {}
        for row in records:
            year = row_year(row, "Publication Year")
            values = ordered.get(year, [])
            if not values:
                continue
            cited = to_int(row.get("Cited by Patent Count"))
            rank = sum(1 for value in values if value <= cited)
            percentiles[row_review_key(row)] = percent(rank, len(values))
        return percentiles

    def vosviewer_raw_export(self, query: dict[str, list[str]]) -> tuple[str, str, bytes]:
        records, _metrics = self.filtered_records(query)
        kind = (first(query, "kind") or "corpus").lower()
        prefix = f"{safe_download_stem(self.source_name)}_filtered"

        if kind == "corpus":
            return (
                f"{prefix}_vos_corpus.txt",
                "text/plain; charset=utf-8",
                self.vosviewer_corpus_file(records),
            )
        if kind == "scores":
            return (
                f"{prefix}_vos_scores.txt",
                "text/tab-separated-values; charset=utf-8",
                self.vosviewer_scores_file(records),
            )
        if kind == "metadata":
            return (
                f"{prefix}_vos_metadata.csv",
                "text/csv; charset=utf-8",
                self.vosviewer_metadata_file(records),
            )
        if kind == "thesaurus":
            return (
                f"{prefix}_vos_thesaurus_terms.txt",
                "text/tab-separated-values; charset=utf-8",
                self.vosviewer_thesaurus_file(),
            )
        raise ValueError("Unknown VOSviewer export type.")

    def vosviewer_corpus_file(self, records: list[dict[str, str]]) -> bytes:
        lines = []
        for row in records:
            text = clean_vos_text(". ".join(part for part in [row.get("Title", ""), row.get("Abstract", "")] if part))
            lines.append(text)
        return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8-sig")

    def vosviewer_scores_file(self, records: list[dict[str, str]]) -> bytes:
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow([header for header, _field, _kind in VOS_SCORE_FIELDS])
        for row in records:
            writer.writerow([
                vos_score_value(row, source_field, kind)
                for _score_header, source_field, kind in VOS_SCORE_FIELDS
            ])
        return output.getvalue().encode("utf-8-sig")

    def vosviewer_metadata_file(self, records: list[dict[str, str]]) -> bytes:
        output = io.StringIO(newline="")
        fieldnames = [
            "corpus_line",
            "source_row",
            "display_key",
            "lens_id",
            "title",
            "publication_year",
            "jurisdiction",
            "document_type",
            "legal_status",
            "applicants",
            "url",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for index, row in enumerate(records, start=1):
            writer.writerow({
                "corpus_line": str(index),
                "source_row": row.get("_row_number", ""),
                "display_key": row.get("Display Key", ""),
                "lens_id": row.get("Lens ID", ""),
                "title": row.get("Title", ""),
                "publication_year": row.get("Publication Year", ""),
                "jurisdiction": row.get("Jurisdiction", ""),
                "document_type": row.get("Document Type", ""),
                "legal_status": row.get("Legal Status", ""),
                "applicants": row.get("Applicants", ""),
                "url": row.get("URL", ""),
            })
        return output.getvalue().encode("utf-8-sig")

    def vosviewer_thesaurus_file(self) -> bytes:
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow(["label", "replace by"])
        for term in VOS_THESAURUS_IGNORES:
            writer.writerow([term, ""])
        return output.getvalue().encode("utf-8-sig")

    def page(self, query: dict[str, list[str]]) -> dict[str, Any]:
        records, metrics = self.filtered_records(query)
        offset = max(0, to_int(first(query, "offset")))
        limit = min(100, max(1, to_int(first(query, "limit")) or 25))
        page_records = records[offset : offset + limit]
        return {
            "total": len(records),
            "offset": offset,
            "limit": limit,
            "metrics": metrics,
            "breakdowns": self.breakdowns(records),
            "records": [self.summary(row) for row in page_records],
        }

    def summary(self, row: dict[str, str]) -> dict[str, Any]:
        return {
            "id": row.get("_id", ""),
            "display_key": row.get("Display Key", ""),
            "title": row.get("Title", ""),
            "publication_date": row.get("Publication Date", ""),
            "publication_year": row.get("Publication Year", ""),
            "jurisdiction": row.get("Jurisdiction", ""),
            "kind": row.get("Kind", ""),
            "document_type": row.get("Document Type", ""),
            "legal_status": row.get("Legal Status", ""),
            "applicants": row.get("Applicants", ""),
            "cited_by": to_int(row.get("Cited by Patent Count")),
            "cites": to_int(row.get("Cites Patent Count")),
            "extended_family_size": to_int(row.get("Extended Family Size")),
        }

    def detail(self, record_id: str) -> dict[str, Any]:
        self.ensure_current()
        row = self.record_by_id.get(record_id)
        if not row:
            raise KeyError(f"Record not found: {record_id}")
        split_fields = [
            "Applicants",
            "Inventors",
            "Owners",
            "CPC Classifications",
            "IPCR Classifications",
            "US Classifications",
            "Simple Family Members",
            "Simple Family Member Jurisdictions",
            "Extended Family Members",
            "Extended Family Member Jurisdictions",
            "NPL Resolved Lens ID(s)",
            "NPL Resolved External ID(s)",
        ]
        return {
            "id": record_id,
            "review_key": row_review_key(row),
            "record": public_row(row),
            "lists": {field: split_multi(row.get(field)) for field in split_fields},
        }


def first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key, [])
    return values[0] if values else ""


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def uploaded_csv_from_multipart(content_type: str, body: bytes) -> tuple[str, bytes]:
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("Expected a CSV file upload.")

    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name != "csv_file":
            continue
        filename = part.get_filename() or "uploaded.csv"
        contents = part.get_payload(decode=True) or b""
        if not contents:
            raise ValueError("The selected CSV file is empty.")
        return filename, contents
    raise ValueError("Choose a CSV file first.")


def make_handler(dataset: PatentDataset, app_state: AppState) -> type[BaseHTTPRequestHandler]:
    class PatentRequestHandler(BaseHTTPRequestHandler):
        server_version = "PatentCSVViewer/1.0"
        max_upload_bytes = 250 * 1024 * 1024

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)

            try:
                if parsed.path in ("/", "/index.html"):
                    self.send_bytes(APP_HTML.encode("utf-8"), "text/html; charset=utf-8")
                elif parsed.path == "/api/metadata":
                    self.send_json(dataset.metadata())
                elif parsed.path == "/api/scopes":
                    self.send_json({"scopes": app_state.scopes()})
                elif parsed.path == "/api/analysis":
                    self.send_json(dataset.analysis(query, app_state.scopes(), app_state.labels()))
                elif parsed.path == "/api/records":
                    self.send_json(dataset.page(query))
                elif parsed.path == "/api/vosviewer_raw_export":
                    filename, content_type, body = dataset.vosviewer_raw_export(query)
                    self.send_download(filename, body, content_type)
                elif parsed.path == "/api/review_labels_export":
                    self.send_download("patent_review_labels.csv", app_state.labels_csv(), "text/csv; charset=utf-8")
                elif parsed.path == "/api/record":
                    record_id = first(query, "id")
                    if not record_id:
                        self.send_error(400, "Missing record id")
                    else:
                        detail = dataset.detail(record_id)
                        detail["review"] = app_state.label_for(detail["review_key"])
                        self.send_json(detail)
                else:
                    self.send_error(404, "Not found")
            except FileNotFoundError as exc:
                self.send_error(404, str(exc))
            except KeyError as exc:
                self.send_error(404, str(exc))
            except ValueError as exc:
                self.send_error(400, str(exc))
            except Exception as exc:  # pragma: no cover - defensive for local app errors
                self.send_error(500, str(exc))

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/load_csv":
                    content_length = int(self.headers.get("Content-Length", "0") or 0)
                    if content_length <= 0:
                        raise ValueError("Choose a CSV file first.")
                    if content_length > self.max_upload_bytes:
                        raise ValueError("CSV upload is larger than 250 MB.")

                    body = self.rfile.read(content_length)
                    filename, contents = uploaded_csv_from_multipart(self.headers.get("Content-Type", ""), body)
                    self.send_json(dataset.load_uploaded(filename, contents))
                    return

                if parsed.path == "/api/scopes":
                    payload = self.read_json_body()
                    action = str(payload.get("action", "save"))
                    if action == "delete":
                        self.send_json({"scopes": app_state.delete_scope(str(payload.get("id", "")))})
                    else:
                        self.send_json({"scopes": app_state.save_scope(payload.get("scope", payload))})
                    return

                if parsed.path == "/api/review_label":
                    payload = self.read_json_body()
                    record_id = str(payload.get("id", ""))
                    if not record_id:
                        raise ValueError("Missing record id.")
                    detail = dataset.detail(record_id)
                    label = str(payload.get("label", ""))
                    note = str(payload.get("note", ""))
                    review = app_state.save_label(detail["review_key"], label, note)
                    self.send_json({"review_key": detail["review_key"], "review": review})
                    return

                else:
                    self.send_error(404, "Not found")
                    return
            except ValueError as exc:
                self.send_text(str(exc), status=400)
            except KeyError as exc:
                self.send_text(str(exc), status=404)
            except Exception as exc:  # pragma: no cover - defensive for local app errors
                self.send_text(str(exc), status=500)

        def read_json_body(self) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0") or 0)
            if content_length <= 0:
                return {}
            body = self.rfile.read(content_length)
            try:
                payload = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError("Expected a JSON request body.") from exc
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object.")
            return payload

        def send_json(self, payload: Any) -> None:
            self.send_bytes(json_bytes(payload), "application/json; charset=utf-8")

        def send_text(self, message: str, status: int = 200) -> None:
            self.send_bytes(message.encode("utf-8"), "text/plain; charset=utf-8", status=status)

        def send_download(self, filename: str, body: bytes, content_type: str) -> None:
            safe_name = filename.replace("\\", "_").replace("/", "_").replace('"', "")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), format % args))

    return PatentRequestHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local browser viewer for a Lens patent CSV.")
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help="Path to the CSV file.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", default=8765, type=int, help="Port to bind.")
    parser.add_argument("--open", action="store_true", help="Open the app in the default browser.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = PatentDataset(Path(args.csv))
    app_state = AppState(APP_STATE_DIR)
    handler = make_handler(dataset, app_state)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{server.server_address[1]}"
    print(f"Serving {dataset.csv_path}")
    print(f"Open {url}")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
