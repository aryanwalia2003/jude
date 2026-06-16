# jude-prompt-engine

Deterministic prompt compiler and optimizer for AI-driven code analysis. Part of the Jude AI Infrastructure suite.

## Installation

```bash
pip install jude-prompt-engine
```

## Quick Start

```bash
ai --help
```

## Features

- **Deterministic Compilation** — Reproducible prompt generation
- **Multi-mode Support** — strict, safe, deep modes for different use cases
- **Ranking & Context** — Deterministic symbol retrieval with audit trails
- **Output Validation** — Schema enforcement for structured outputs

## Usage

```bash
# Basic prompt
ai "debug why emit_sync is failing"

# With specific mode
ai --mode deep "analyze performance of scheduler"

# Custom preset
ai --preset code-review "check this function"
```

## Documentation

Full documentation is available in the [main repository](https://github.com/aryanwalia2003/jude).
