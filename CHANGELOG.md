# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## 0.1.0 (2026-05-22)

- `grokko setup` — installs Playwright Chromium browser dependencies.
- `grokko session` — manages browser session cookies for authenticated requests.
- `grokko chat` — fetches conversations by ID, optionally downloading attachments.
- `grokko export` — triggers and downloads Grok data exports via the web UI.
- `grokko extract` — converts a Grok export ZIP into Obsidian-compatible Markdown.
- `grokko overview` — summarises export contents.
- Plugin architecture: validated by a real integration test that installs a dummy plugin via dist-info discovery.
