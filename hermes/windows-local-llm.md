# Free open-source LLM API on Windows (Ollama)

Goal: a **free, local, OpenAI-compatible API** the agent can use as its LLM backend —
no API key costs, nothing leaves your PC.

```
Agent (Windows) ──► http://localhost:11434/v1 ──► Ollama ──► open model (Hermes 3 / Llama / Qwen)
```

---

## 1. Install Ollama

1. Download the Windows installer: <https://ollama.com/download/windows>
2. Run `OllamaSetup.exe` (no admin rights needed).
3. Ollama starts automatically and stays in the system tray; it also auto-starts
   with Windows. It listens on `http://localhost:11434`.

Verify in **PowerShell**:

```powershell
ollama --version
```

## 2. Pull a model that fits your hardware

| Your PC | Model | Command | Size |
|---|---|---|---|
| 8 GB RAM, no GPU | Llama 3.2 3B | `ollama pull llama3.2:3b` | ~2 GB |
| 8 GB RAM, no GPU (alt) | Qwen 2.5 3B | `ollama pull qwen2.5:3b` | ~2 GB |
| 16 GB RAM or 8 GB GPU | **Hermes 3 8B** (Nous Research) | `ollama pull hermes3:8b` | ~4.7 GB |
| 16 GB RAM (alt) | Llama 3.1 8B | `ollama pull llama3.1:8b` | ~4.7 GB |
| 32 GB RAM or 12+ GB GPU | Qwen 2.5 14B | `ollama pull qwen2.5:14b` | ~9 GB |

Rules of thumb:
- Model size on disk ≈ RAM/VRAM it needs while running. Leave a few GB free.
- NVIDIA GPU is used automatically if present; otherwise it runs on CPU (slower
  but works fine for a 3B–8B model).
- `hermes3:8b` is a nice match since you're testing the Hermes agent — same lab.

Quick chat test:

```powershell
ollama run hermes3:8b "Say hello in one short sentence."
```

(`/bye` exits the chat.)

## 3. Test the OpenAI-compatible API

```powershell
Invoke-RestMethod -Uri http://localhost:11434/v1/chat/completions `
  -Method Post -ContentType "application/json" -Body (@{
    model    = "hermes3:8b"
    messages = @(@{ role = "user"; content = "hello" })
  } | ConvertTo-Json -Depth 5) | ConvertTo-Json -Depth 10
```

You should get back a normal OpenAI-style `chat.completion` response.
That URL — `http://localhost:11434/v1` — is your free LLM API.

## 4. Point the agent at it

In the agent's configuration (its `.env` / settings — on Windows, NOT Railway):

```env
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama          # any dummy value — Ollama ignores it
# model name exactly as pulled:
MODEL=hermes3:8b
```

Hermes Agent specifics: it accepts any OpenAI-compatible endpoint, so set the
provider to "OpenAI-compatible / custom", base URL as above, model `hermes3:8b`.
Restart the agent and send it a message.

## 5. Useful commands

```powershell
ollama list        # installed models
ollama ps          # what's loaded in memory right now
ollama pull <m>    # download / update a model
ollama rm <m>      # delete a model (frees disk)
```

---

## ⚠️ If the agent runs on Railway (not on your PC)

`localhost` on Railway is the Railway container — it can NEVER reach the Ollama
on your Windows PC. Options, best first:

1. **OpenRouter free tier (recommended):** set `OPENROUTER_API_KEY` in Railway
   Variables and pick a `:free` model (e.g. `meta-llama/llama-3.3-70b-instruct:free`).
   Zero cost, no tunnel, works 24/7 even when your PC is off.
2. **Tunnel your Ollama** (advanced): expose `localhost:11434` with a Cloudflare
   tunnel and set `OPENAI_BASE_URL` to the tunnel URL. ⚠ Ollama has **no
   authentication** — never expose it without the tunnel's access controls, and
   remember the agent dies whenever your PC sleeps.
3. **Don't** run the model itself on Railway — RAM/CPU cost is high (the plan's
   "What NOT to do" list).

## Alternatives to Ollama

- **LM Studio** (<https://lmstudio.ai>) — GUI app; enable its local server
  (default `http://localhost:1234/v1`) if you prefer clicking to typing.
- **llama.cpp** — `llama-server.exe` from the GitHub releases; lightest option,
  manual GGUF downloads.

All three speak the same OpenAI API shape, so the agent config is identical —
only the base URL and model name change.
