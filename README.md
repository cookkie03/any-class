# AnyClass 🧭

**Zero-token local decision engine for classifying Telegram Saved Messages, notes, and links directly on consumer CPU/RAM with Ollama System One models (`tev1:0.8b` + `d1-omni:600m`).**

Includes an interactive local **Dashboard** with real-time topic filtering, automatic GitHub starring commands, `yt-dlp` batch downloading scripts, and Notion Second Brain routing.

---

## ⚡ Why AnyClass?

Traditional generative LLMs generate free-form text token-by-token, which is computationally expensive, prone to hallucinations, slow on local CPU, and consumes gigabytes of VRAM.

**AnyClass uses Decision Models via Ollama (`/v1/systemone`):**
- **0 Generated Tokens**: Reads single-token logprobs in a single forward pass.
- **Fast & Lightweight**: ~1s per message on an AMD Ryzen 5 CPU, taking only ~1.3 GB of RAM.
- **Memory-Guarded**: Protects the machine against OOM with real-time `/proc/meminfo` and cgroup v2 pressure checks.
- **Hybrid Pipeline**: Combines deterministic regex rules (GitHub repos, CLI commands, sensitive data) with local decision models for ambiguous items.

---

## 📊 Interactive Dashboard

AnyClass includes an interactive web interface:
- **Topic Breakdown**: Categorizes items into *AI & Tech KB*, *GitHub Starred*, *Trading Wiki*, *Finanza & Macro*, *Carriera & Studio*, *Fitness*, *Meal Prep*, *Thasup / Music*, *Cheatsheet Terminale*.
- **Quick Export Tools**:
  - ⭐ **GitHub Starred CLI**: Generates `gh api -X PUT /user/starred/{owner}/{repo}` to star saved repos.
  - 🎬 **yt-dlp Batch**: One-click script to download Instagram Reels, TikToks, and YouTube audio tracks offline.
  - 📘 **Notion Second Brain Hub**: Groups items ready to be imported into Notion databases.
  - 🔐 **Credential Detection**: Automatically flags plaintext passwords and tokens so you can safely migrate them to a password manager.

---

## 🚀 Quick Start

### 1. Requirements
- Linux or macOS with [Ollama](https://ollama.com/) 0.35+
- Python 3.10+ (standard library only; `Pillow` optional for image support)

Pull the recommended decision model:
```bash
ollama pull tev1:0.8b
# (Optional for image classification)
ollama pull d1-omni:600m
```

### 2. Export Telegram Messages
1. Open **Telegram Desktop** → Settings → Advanced → **Export Telegram data**.
2. Select **Saved Messages** (JSON format).

### 3. Run Classification
```bash
# Classify your export
python3 tg_classify.py ChatExport_YYYY-MM-DD/result.json --out results.jsonl
```

The script is **resumable**: if interrupted, re-running it will skip already classified items.

### 4. Open Dashboard
```bash
# Start a local web server
python3 -m http.server 8085

# Open in your browser:
# http://localhost:8085
```
You can drop or upload your `results.jsonl` directly in the dashboard.

---

## ⚙️ Customizing Categories

Edit `categories.json` to customize your classification taxonomy:
```json
{
  "my_category": {
    "description": "Clear description for the decision model",
    "destination": "Notion: My Target Database",
    "action": "Action to perform"
  }
}
```

---

## 🛡️ License

MIT License. Built for local privacy and local-first knowledge management.
