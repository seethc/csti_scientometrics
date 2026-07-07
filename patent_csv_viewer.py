#!/usr/bin/env python3
"""Local browser viewer for a Lens patent CSV export."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
import webbrowser
from collections import Counter
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


DEFAULT_CSV = Path(r"C:\Users\sugey\Dropbox\PC\Downloads\10yr-photonic-interconnects.csv")

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
    select {
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

    .field {
      display: grid;
      gap: 6px;
    }

    .field label {
      color: #384049;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }

    .field input,
    .field select {
      width: 100%;
      min-height: 38px;
      border: 1px solid #ccd4c7;
      border-radius: 6px;
      background: #ffffff;
      color: var(--ink);
      padding: 8px 10px;
      outline: none;
    }

    .field input:focus,
    .field select:focus {
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

    .insight-panel.status .bar-fill {
      background: #7a4f9a;
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
          <button class="tab-button" id="recordsTab" type="button">Records</button>
        </div>
        <div class="status-line" id="resultStatus">Loading records...</div>
      </div>

      <div class="insights" id="insights"></div>
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
      view: "insights"
    };

    const controls = {
      search: document.getElementById("searchInput"),
      year: document.getElementById("yearSelect"),
      jurisdiction: document.getElementById("jurisdictionSelect"),
      status: document.getElementById("statusSelect"),
      type: document.getElementById("typeSelect"),
      applicant: document.getElementById("applicantSelect"),
      cpc: document.getElementById("cpcSelect"),
      sort: document.getElementById("sortSelect")
    };

    const resultsEl = document.getElementById("results");
    const insightsEl = document.getElementById("insights");
    const detailEl = document.getElementById("detailPane");
    const moreButton = document.getElementById("moreButton");
    const footerActions = document.querySelector(".footer-actions");
    const resultStatus = document.getElementById("resultStatus");
    const insightsTab = document.getElementById("insightsTab");
    const recordsTab = document.getElementById("recordsTab");

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
      insightsEl.hidden = !insightsActive;
      resultsEl.hidden = insightsActive;
      footerActions.hidden = insightsActive;
      insightsTab.classList.toggle("active", insightsActive);
      recordsTab.classList.toggle("active", !insightsActive);
    }

    function params(resetOffset) {
      if (resetOffset) state.offset = 0;
      const query = new URLSearchParams();
      query.set("offset", state.offset);
      query.set("limit", state.limit);
      query.set("sort", controls.sort.value);
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
        "Patent office counts are publication records. Family country coverage de-duplicates simple families. Applicant and owner country is not explicit in this CSV."
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

    function debounce(fn, delay) {
      let timer = 0;
      return (...args) => {
        window.clearTimeout(timer);
        timer = window.setTimeout(() => fn(...args), delay);
      };
    }

    document.getElementById("applyButton").addEventListener("click", () => loadRecords(true));
    document.getElementById("resetButton").addEventListener("click", () => {
      Object.values(controls).forEach((control) => {
        if (control.tagName === "SELECT") control.selectedIndex = 0;
        else control.value = "";
      });
      controls.sort.value = "publication_date";
      loadRecords(true);
    });
    moreButton.addEventListener("click", () => loadRecords(false));
    insightsTab.addEventListener("click", () => setView("insights"));
    recordsTab.addEventListener("click", () => setView("records"));

    controls.search.addEventListener("input", debounce(() => loadRecords(true), 300));
    ["year", "jurisdiction", "status", "type", "applicant", "cpc", "sort"].forEach((name) => {
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


def clean_owner_name(value: str) -> str:
    return OWNER_DATE_RE.sub("", value).strip()


def family_key(row: dict[str, str], member_field: str) -> tuple[str, ...]:
    members = split_multi(row.get(member_field))
    if members:
        return tuple(sorted(members))
    return (row.get("_id", ""),)


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


def public_row(row: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in row.items() if not key.startswith("_")}


class PatentDataset:
    def __init__(self, csv_path: Path):
        self.csv_path = csv_path
        self.rows: list[dict[str, str]] = []
        self.fieldnames: list[str] = []
        self.record_by_id: dict[str, dict[str, str]] = {}
        self._mtime = 0.0
        self._lock = threading.Lock()
        self.load()

    def ensure_current(self) -> None:
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
            reader = csv.DictReader(handle)
            rows = []
            for index, row in enumerate(reader, start=1):
                clean_row = {key: (value or "").strip() for key, value in row.items() if key is not None}
                clean_row["_row_number"] = str(index)
                clean_row["_id"] = clean_row.get("Lens ID") or clean_row.get("Display Key") or str(index)
                clean_row["_search"] = " ".join(clean_row.get(field, "") for field in SEARCH_FIELDS).lower()
                rows.append(clean_row)

        self.rows = rows
        self.fieldnames = list(reader.fieldnames or [])
        self.record_by_id = {row["_id"]: row for row in rows}
        self._mtime = self.csv_path.stat().st_mtime

    def metadata(self) -> dict[str, Any]:
        self.ensure_current()
        years = sorted(
            {row.get("Publication Year", "") for row in self.rows if row.get("Publication Year", "")},
            reverse=True,
        )
        applicants: Counter[str] = Counter()
        cpc_classes: Counter[str] = Counter()
        for row in self.rows:
            applicants.update(split_multi(row.get("Applicants")))
            cpc_classes.update(split_multi(row.get("CPC Classifications")))

        stat = self.csv_path.stat()
        return {
            "file_name": self.csv_path.name,
            "file_path": str(self.csv_path),
            "last_modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "row_count": len(self.rows),
            "columns": self.fieldnames,
            "years": years,
            "jurisdictions": self._common("Jurisdiction"),
            "statuses": self._common("Legal Status"),
            "document_types": self._common("Document Type"),
            "applicants": applicants.most_common(120),
            "cpc_classes": cpc_classes.most_common(120),
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
            records = [row for row in records if cpc in split_multi(row.get("CPC Classifications"))]

        records = self._sort(records, first(query, "sort") or "publication_date")
        metrics = self.metrics(records)
        return records, metrics

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
            "record": public_row(row),
            "lists": {field: split_multi(row.get(field)) for field in split_fields},
        }


def first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key, [])
    return values[0] if values else ""


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def make_handler(dataset: PatentDataset) -> type[BaseHTTPRequestHandler]:
    class PatentRequestHandler(BaseHTTPRequestHandler):
        server_version = "PatentCSVViewer/1.0"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)

            try:
                if parsed.path in ("/", "/index.html"):
                    self.send_bytes(APP_HTML.encode("utf-8"), "text/html; charset=utf-8")
                elif parsed.path == "/api/metadata":
                    self.send_json(dataset.metadata())
                elif parsed.path == "/api/records":
                    self.send_json(dataset.page(query))
                elif parsed.path == "/api/record":
                    record_id = first(query, "id")
                    if not record_id:
                        self.send_error(400, "Missing record id")
                    else:
                        self.send_json(dataset.detail(record_id))
                else:
                    self.send_error(404, "Not found")
            except FileNotFoundError as exc:
                self.send_error(404, str(exc))
            except KeyError as exc:
                self.send_error(404, str(exc))
            except Exception as exc:  # pragma: no cover - defensive for local app errors
                self.send_error(500, str(exc))

        def send_json(self, payload: Any) -> None:
            self.send_bytes(json_bytes(payload), "application/json; charset=utf-8")

        def send_bytes(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
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
    handler = make_handler(dataset)
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
