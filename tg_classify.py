#!/usr/bin/env python3
"""Classify Telegram saved messages with Ollama decision models (/v1/systemone) and high-precision rules.

  python3 tg_classify.py classify ChatExport_2026-11-19/result.json --out results.jsonl

Categories & Targets:
  1. github_starred        -> gh api -X PUT /user/starred/{owner}/{repo}
  2. cheatsheet_terminale  -> Notion: Cheatsheet & Terminal Snippets
  3. ai_tech_generico      -> Notion: Tech & AI Knowledge Base
  4. trading_wiki          -> GitHub Wiki: trading-agent-wiki
  5. finanza_generale      -> Notion: Finanza & Investimenti
  6. carriera_studio       -> Notion: Private Pages Carriera & Studio
  7. fitness_allenamento   -> Notion: Fitness & Workout
  8. ricette_meal_prep     -> Notion: Meal Planner (+ yt-dlp se video)
  9. documenti_salute      -> Archivio Locale Cifrato + Notion Salute
 10. musica_thasup         -> Archivio Thasup & Playlist (yt-dlp audio)
 11. media_svago_generale  -> Archivio Video yt-dlp & Notion Swipe File
"""
import argparse, base64, io, json, os, random, re, sys, time, urllib.request
from pathlib import Path
from urllib.parse import urlparse

HOST = "http://localhost:11434"
OLLAMA = HOST + "/v1/systemone"
HERE = Path(__file__).parent
URL_RE = re.compile(r"https?://[^\s<>\")\]]+")
MAX_CHARS = 1200
IMG_SIDE = 512

MIN_AVAIL_GB = 1.5
MIN_SWAP_FREE_GB = 1.0
MAX_PSI_FULL = 20.0


# ---------------------------------------------------------------- Memory Guard
def meminfo_gb():
    d = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, v = line.split(":", 1)
        d[k] = int(v.split()[0]) / 1048576
    return d


def psi_full():
    try:
        for line in Path("/proc/pressure/memory").read_text().splitlines():
            if line.startswith("full"):
                return float(re.search(r"avg10=([\d.]+)", line).group(1))
    except OSError:
        pass
    return 0.0


def mem_ok(need_gb=MIN_AVAIL_GB):
    m = meminfo_gb()
    return m["MemAvailable"] >= need_gb and m.get("SwapFree", 99) >= MIN_SWAP_FREE_GB and psi_full() < MAX_PSI_FULL


def post_json(path, body, timeout=10):
    req = urllib.request.Request(HOST + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def unload_all():
    try:
        for m in json.load(urllib.request.urlopen(HOST + "/api/ps", timeout=10)).get("models", []):
            post_json("/api/generate", {"model": m["name"], "keep_alive": 0})
    except Exception:
        pass


def guard(need_gb=MIN_AVAIL_GB, wait=120):
    if mem_ok(need_gb):
        return
    unload_all()
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(5)
        if mem_ok(need_gb):
            return
    m = meminfo_gb()
    sys.exit(f"FERMATO per memoria: MemAvailable {m['MemAvailable']:.1f} GB, SwapFree {m.get('SwapFree', 0):.1f} GB")


# ---------------------------------------------------------------- High-Precision Rules
def apply_rules(m):
    txt = m.get("text", "")
    ltxt = txt.lower()
    fn = (m.get("file_name") or m.get("photo") or "").lower()
    urls = m.get("urls", [])

    # 1. GitHub repo direct links
    gh_match = re.search(r"github\.com/([a-zA-Z0-9_\.-]+)/([a-zA-Z0-9_\.-]+)", txt)
    if gh_match:
        owner, repo = gh_match.groups()
        if owner not in ["features", "pricing", "marketplace", "about"]:
            return {
                "categoria": "github_starred",
                "destinazione": "GitHub Starred",
                "proposta": "Aggiungi a Starred GitHub",
                "comando": f"gh api -X PUT /user/starred/{owner}/{repo}",
                "confidence": 1.0,
                "regola": "github_repo_link",
            }

    # 2. Musica thasup / yungest moonstar
    if any(k in ltxt or k in fn for k in ["thasup", "tha supreme", "tha sup", "yungest moonstar", "yungest-moonstar"]):
        cmd = f"yt-dlp -x --audio-format mp3 \"{urls[0]}\"" if urls else "Archivia file audio thasup"
        return {
            "categoria": "musica_thasup",
            "destinazione": "Archivio Thasup & Playlist",
            "proposta": "Download audio offline con yt-dlp",
            "comando": cmd,
            "confidence": 1.0,
            "regola": "thasup_keyword",
        }
    if any(u in ltxt for u in ["watch?v=jxxfgain7ta", "youtu.be/zocp9sho1mg", "youtu.be/pxpfzhgasgi", "youtu.be/f8uthvzrdgy"]):
        cmd = f"yt-dlp -x --audio-format mp3 \"{urls[0]}\"" if urls else ""
        return {
            "categoria": "musica_thasup",
            "destinazione": "Archivio Thasup & Playlist",
            "proposta": "Download audio offline con yt-dlp",
            "comando": cmd,
            "confidence": 1.0,
            "regola": "thasup_youtube_id",
        }

    # 3. Documenti sanitari o documenti personali sensibili
    if any(k in ltxt or k in fn for k in ["sanitario", "allergolog", "visita", "carta circolazione", "patente", "asma", "referto"]):
        return {
            "categoria": "documenti_salute",
            "destinazione": "Notion: Salute & Archivio Locale Cifrato",
            "proposta": "Archivia PDF in cartella protetta + log in Notion 'Salute & Documenti'",
            "comando": f"cp {m.get('file_name')} ~/Second-Brain/00-InBox/Documenti/" if m.get("file_name") else "",
            "confidence": 1.0,
            "regola": "health_document_keyword",
        }

    # 4. Trading wiki (MT5, broker, trading quantitativo, posizioni insider)
    if any(k in ltxt for k in ["trade.mt5", "admiralmarkets", "quiverquant", "algorithmictrading", "trading-agent"]):
        return {
            "categoria": "trading_wiki",
            "destinazione": "GitHub Wiki: trading-agent-wiki",
            "proposta": "Aggiungi a repository wiki 'trading-agent-wiki'",
            "comando": "Salva snippet in docs/trading-agent-wiki",
            "confidence": 1.0,
            "regola": "trading_agent_keyword",
        }

    # 5. Carriera & Studio (CV, universita)
    if any(k in fn or k in ltxt for k in ["cv_", "curriculum", "al cv", "bocconi", "iulm", "cattolica", "laurea lampo", "unibocconi"]):
        return {
            "categoria": "carriera_studio",
            "destinazione": "Notion: Private Pages Carriera & Studio",
            "proposta": "Salva in Notion 'Carriera & Università'",
            "comando": "",
            "confidence": 1.0,
            "regola": "career_study_keyword",
        }

    # 6. Cheatsheet terminale
    if any(k in ltxt for k in ["hermes gateway", "edge_py=", "close hermes desktop", "export path=", "run these commands in a terminal"]):
        return {
            "categoria": "cheatsheet_terminale",
            "destinazione": "Notion: Cheatsheet & Terminal Snippets",
            "proposta": "Salva blocco comandi in Notion Cheatsheet",
            "comando": "",
            "confidence": 1.0,
            "regola": "terminal_cheatsheet_keyword",
        }

    # 7. Ricette / Cibo
    if any(k in ltxt for k in ["cibo greco", "ricetta", "ricette", "meal prep"]):
        cmd = f"yt-dlp \"{urls[0]}\"" if urls else ""
        return {
            "categoria": "ricette_meal_prep",
            "destinazione": "Notion: Meal Planner & Ricette",
            "proposta": "Aggiungi a Notion Meal Planner",
            "comando": cmd,
            "confidence": 0.95,
            "regola": "recipe_food_keyword",
        }

    # 8. Fitness & Workout
    if any(k in ltxt for k in ["dropset", "myo reps", "tensione continua"]):
        return {
            "categoria": "fitness_allenamento",
            "destinazione": "Notion: Fitness & Workout",
            "proposta": "Aggiungi a Notion scheda workout/fitness",
            "comando": "",
            "confidence": 0.95,
            "regola": "gym_workout_keyword",
        }

    return None


# ---------------------------------------------------------------- Data Preparation
def flat_text(t):
    if isinstance(t, str):
        return t
    return "".join(p if isinstance(p, str) else p.get("text", "") for p in t)


def load_messages(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = data.get("messages", []) if "messages" in data else [m for c in data.get("chats", {}).get("list", []) for m in c.get("messages", [])]
    out = []
    for m in raw:
        if m.get("type") != "message":
            continue
        text = flat_text(m.get("text", "")).strip()
        media = m.get("media_type") or ("photo" if "photo" in m else None) or ("file" if "file" in m else None)
        if not text and not media:
            continue
        urls = URL_RE.findall(text)
        out.append({
            "id": m.get("id"),
            "date": m.get("date"),
            "text": text,
            "media": media,
            "urls": urls,
            "domains": sorted({urlparse(u).netloc.removeprefix("www.") for u in urls}),
            "forwarded_from": m.get("forwarded_from"),
            "file_name": m.get("file") or m.get("file_name"),
            "photo": m.get("photo"),
        })
    return out


def prep_image(export_dir, rel):
    if not rel:
        return None
    try:
        from PIL import Image
        p = Path(export_dir) / rel
        if not p.is_file():
            return None
        im = Image.open(p).convert("RGB")
        im.thumbnail((IMG_SIDE, IMG_SIDE))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


# ---------------------------------------------------------------- Model Decision
def decide(model, state, cats, image=None, retries=3):
    criteria = {k: v["description"] for k, v in cats.items()}
    body = {
        "model": model,
        "state": state,
        "keep_alive": "15m",
        "questions": {
            "categoria": {
                "type": "choice",
                "instructions": "In quale categoria tematica precisa rientra questo messaggio salvato su Telegram?",
                "criteria": criteria
            },
            "azione_urgente": {
                "type": "noul",
                "instructions": "Il messaggio contiene una cosa urgente da fare, studiare o verificare con priorità?"
            }
        }
    }
    if image:
        body["images"] = [image]
    req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
    for i in range(retries):
        try:
            res = json.load(urllib.request.urlopen(req, timeout=120))
            return res["answers"]
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))


# ---------------------------------------------------------------- Main Classifier
def run_classification(export_json_path, out_jsonl_path, model="tev1:0.8b"):
    export_dir = Path(export_json_path).parent
    msgs = load_messages(export_json_path)
    cats = json.loads((HERE / "categories.json").read_text(encoding="utf-8"))

    out_path = Path(out_jsonl_path)
    done_ids = set()
    if out_path.exists():
        for l in out_path.read_text(encoding="utf-8").splitlines():
            if l.strip():
                done_ids.add(json.loads(l).get("id"))

    todo = [m for m in msgs if m["id"] not in done_ids]
    print(f"=== CLASSIFICAZIONE TELEGRAM ===")
    print(f"Messaggi totali: {len(msgs)} | Già completati: {len(done_ids)} | Da fare: {len(todo)}")

    t0 = time.time()
    with out_path.open("a", encoding="utf-8") as f:
        for i, m in enumerate(todo, 1):
            guard(MIN_AVAIL_GB)

            # 1. Rule Fast-Path
            rule_res = apply_rules(m)
            if rule_res:
                rec = {
                    **m,
                    "categoria": rule_res["categoria"],
                    "destinazione": rule_res["destinazione"],
                    "proposta": rule_res["proposta"],
                    "comando": rule_res["comando"],
                    "confidence": rule_res["confidence"],
                    "metodo": f"rule:{rule_res['regola']}",
                    "azione_urgente_p": 0.5,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                continue

            # 2. Decision Model Path
            img_b64 = None
            if m.get("photo"):
                img_b64 = prep_image(export_dir, m["photo"])

            active_model = "d1-omni:600m" if (img_b64 and not m["text"].strip()) else model

            state_text = m["text"][:MAX_CHARS] or "(Nessun testo)"
            if m.get("file_name"):
                state_text += f"\n[allegato: {m['file_name']}]"
            if m.get("domains"):
                state_text += f"\n[domini link: {', '.join(m['domains'])}]"
            if m.get("forwarded_from"):
                state_text += f"\n[inoltrato da: {m['forwarded_from']}]"

            try:
                ans = decide(active_model, state_text, cats, image=img_b64)
                cat_ans = ans["categoria"]
                act_ans = ans.get("azione_urgente", {"noul": 0.1})
                chosen_cat = cat_ans["choice"]
                conf = cat_ans.get("confidence") or max(cat_ans.get("probabilities", {chosen_cat: 0.8}).values())

                cat_meta = cats.get(chosen_cat, {
                    "destination": "Notion: Inbox",
                    "action": "Smista manualmente"
                })

                # Synthesize command helper
                urls = m.get("urls", [])
                cmd = ""
                if urls and ("instagram.com" in urls[0] or "tiktok.com" in urls[0] or "youtu" in urls[0]):
                    if chosen_cat == "musica_thasup":
                        cmd = f"yt-dlp -x --audio-format mp3 \"{urls[0]}\""
                    else:
                        cmd = f"yt-dlp \"{urls[0]}\""

                rec = {
                    **m,
                    "categoria": chosen_cat,
                    "destinazione": cat_meta.get("destination", "Notion: Inbox"),
                    "proposta": cat_meta.get("action", "Notion"),
                    "comando": cmd,
                    "confidence": round(conf, 3),
                    "metodo": f"model:{active_model}",
                    "azione_urgente_p": round(act_ans["noul"], 2),
                }
            except Exception as e:
                rec = {
                    **m,
                    "error": str(e),
                    "categoria": "media_svago_generale",
                    "destinazione": "Notion: Inbox",
                    "proposta": "Verifica manuale errore",
                    "confidence": 0.0,
                    "metodo": "error_fallback"
                }

            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()

            if i % 20 == 0 or i == len(todo):
                rate = i / max(0.1, time.time() - t0)
                eta_m = (len(todo) - i) / max(0.01, rate) / 60
                print(f"[{i}/{len(todo)}] {rate:.2f} msg/s | ETA: {eta_m:.1f} min | Ultimo: {rec['categoria']} ({rec['confidence']})")

    unload_all()
    print(f"=== CLASSIFICAZIONE TERMINATA: {out_path} ===")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("export", help="Path to result.json")
    p.add_argument("--out", default="results.jsonl")
    p.add_argument("--model", default="tev1:0.8b")
    a = p.parse_args()
    run_classification(a.export, a.out, a.model)


if __name__ == "__main__":
    main()
