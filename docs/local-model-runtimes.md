# Local model runtimes (Granite Speech + Kokoro)

Status: 2026-11-08. All runtimes here are isolated, prebuilt, and disposable.
No product code, system packages, CUDA toolkit, cuDNN, or PyTorch were installed.

## Models

| Model | Path | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Granite Speech 5.0 TurboCTC Q8_0 | `models/granite-speech-5.0-470m-turboctc/granite-speech-5.0-470m-turboctc-Q8_0.gguf` | 505,663,136 | `fc34cbe71f979a6aeb8bea08bfac88d5c62c1736c0bc845827e37c90f28e336c` |
| Kokoro-82M Q8_0 | `models/kokoro-82m/kokoro-82m-q8_0.gguf` | 141,322,336 | `3c8b60064b287a10abd35396a59c9981675c618db8bc91bd290db63f55eb492d` |
| Kokoro voice `af_heart` | `models/kokoro-82m/kokoro-voice-af_heart.gguf` | 522,784 | `14463a5a5204a16a382b2da87b4b0206fcda225b44b7c4627999eb527f49c018` |

The other six Kokoro voices (522,784–524,832 bytes each) are also in
`models/kokoro-82m/` but are not needed for the smoke test.

Both model directories are git-ignored (`.gitignore` line 38, `models/`).

## Working runtimes

| Model | Runtime | Version | Source | Install path | Backend | Interface |
| --- | --- | --- | --- | --- | --- | --- |
| Granite | transcribe.cpp (native CPU+Vulkan) | 0.4.1 | GitHub release `handy-computer/transcribe.cpp` v0.4.1, asset `transcribe-native-0.4.1-linux-x86_64-cpu-vulkan.tar.gz` | `.tools/transcribe-cpp/transcribe-native-linux-x86_64-cpu-vulkan/` | Vulkan, GTX 1050 Ti (`Vulkan1`) | Python bindings, in-process |
| Kokoro | CrispASR | 0.8.51 (git 008a771c) | GitHub release `CrispStrobe/CrispASR` v0.8.51, asset `crispasr-linux-x86_64-vulkan.tar.gz` | `.tools/crispasr-vulkan/crispasr-linux-x86_64-vulkan/` | Vulkan, GTX 1050 Ti (`--device 2`) | CLI, batch WAV output |

Both use the already-installed LM Studio Vulkan loader:
`~/.lmstudio/extensions/backends/vendor/linux-llama-vulkan-vendor-v1`.
No new CUDA libraries were installed.

Python binding: `transcribe_cpp==0.4.1`, installed only into `.tools/py`
(`pip install --target .tools/py --no-deps transcribe_cpp==0.4.1`).
The wheel is `.tools/transcribe_cpp-0.4.1-py3-none-any.whl`.

### Granite command

```bash
cd /home/arpan/Forge/forge-voice
export PYTHONPATH="$PWD/.tools/py"
export TRANSCRIBE_LIBRARY="$PWD/.tools/transcribe-cpp/transcribe-native-linux-x86_64-cpu-vulkan/libtranscribe.so"
export LD_LIBRARY_PATH="$PWD/.tools/transcribe-cpp/transcribe-native-linux-x86_64-cpu-vulkan:$HOME/.lmstudio/extensions/backends/vendor/linux-llama-vulkan-vendor-v1"
python3 /tmp/opencode/model-runtimes/smoke_granite.py
```

The script resamples the 24 kHz fixtures to 16 kHz, selects `Vulkan1`
(NVIDIA), loads the model once, and prints text plus timings.

### Kokoro command

```bash
cd /home/arpan/Forge/forge-voice
export LD_LIBRARY_PATH="$PWD/.tools/crispasr-vulkan/crispasr-linux-x86_64-vulkan:$HOME/.lmstudio/extensions/backends/vendor/linux-llama-vulkan-vendor-v1"
export CRISPASR_KOKORO_GEN_GPU=1
.tools/crispasr-vulkan/crispasr-linux-x86_64-vulkan/crispasr \
  --backend kokoro \
  -m models/kokoro-82m/kokoro-82m-q8_0.gguf \
  --voice models/kokoro-82m/kokoro-voice-af_heart.gguf \
  --tts "Thanks for calling Harborlight Home Services. I can book a drain cleaning visit for Tuesday at 11:30 AM." \
  -l en --gpu-backend vulkan --device 2 \
  --tts-output /tmp/opencode/model-runtimes/out/kokoro_nv.wav
```

`CRISPASR_KOKORO_GEN_GPU=1` is required; otherwise the iSTFT generator stays
on CPU. `--device 2` selects the NVIDIA Vulkan device on this host: `0` is the
Intel iGPU, `1` resolves to llvmpipe, `2` is the GTX 1050 Ti.

## Why not LM Studio llama-server?

| Runtime | Granite | Kokoro |
| --- | --- | --- |
| llama-server 2.71.0 CUDA (llama.cpp 0.9.0-dev, 6c01da6) | `unknown model architecture: 'granite_speech5_ctc'` | `unknown model architecture: 'kokoro'` |
| llama-server 2.65.1 Vulkan | same architecture error | same architecture error |

The 2.68.0 CUDA runtime failed identically. `llm-lfm3-*`, the LFM3 models, and
the systemd units were not modified.

## Smoke results

### Granite STT (transcribe.cpp 0.4.1, Vulkan, GTX 1050 Ti)

- Load: **1.068 s**; weights copied to Vulkan: 481.6 MiB.
- VRAM: **717 MiB** total (including ~232 MiB desktop) after load.
- Host peak RSS: ~208 MB (round-trip run).
- Cold first run: 27.48 s audio in 4.432 s (6.2×) — includes Vulkan shader compile.
- Warm: 21.66 s audio in 0.596 s (**36.3×**, encoder 521 ms).
- `readback_01.wav`:
  `Hi, I need an ac repair. The address is 88 Meridian Way, San Jose, 9154t The zip is 95125. My name is Dana Whitfield. My phone is 408-555-0142. Monday at 11 works. Actually, make it Tuesday at 11. Yes, that is correct.`
  Street name correct, ZIP 95125 present (with a stray `9154t` before it), phone correct.
- `entities_01.wav`:
  `Hi, I need an ac repair. The address is 80 Tade Meridian Way, San Jose, 951. My name is Dana Whitfield. My phone is 408-555-0142. Tuesday at nine would be great. Yes, wo it.`
  Street name wrong (`80 Tade Meridian`), ZIP truncated (`951`), phone correct. So the entity miss is fixed on readback but not on this fixture.

### Kokoro TTS (CrispASR 0.8.51, Vulkan, GTX 1050 Ti)

- Total: **7.93 s** for 7.775 s audio (**0.98× realtime**); batch CLI only, so
  first-audio latency is not exposed.
- Peak sampled VRAM: **849 MiB** (desktop baseline 232 MiB).
- Output: `/tmp/opencode/model-runtimes/out/kokoro_nv.wav`, 24 kHz mono 16-bit,
  7.775 s, peak 16,475 / RMS 1,496 (non-silent).
- Without `CRISPASR_KOKORO_GEN_GPU=1`: 213.9 s for 7.8 s audio (llvmpipe/CPU
  generator), unusable.
- Granite round-trip: `Thanks for calling Hairbar Light Home Services. I can
  book a drain cleaning visit for Tuesday at 11. 30 a..` — intelligible, but
  the brand and time are imperfect.

## Cleanup map

| Thing | Path | Delete |
| --- | --- | --- |
| transcribe.cpp runtime | `.tools/transcribe-cpp/` | `rm -rf .tools/transcribe-cpp` |
| CrispASR runtime | `.tools/crispasr-vulkan/` | `rm -rf .tools/crispasr-vulkan` |
| Python bindings | `.tools/py/` | `rm -rf .tools/py` |
| Runtime archives | `.tools/transcribe-vulkan.tar.gz`, `.tools/crispasr-vulkan.tar.gz`, `.tools/transcribe_cpp-0.4.1-py3-none-any.whl` | `rm -f` those three |
| Scratch scripts/output | `/tmp/opencode/model-runtimes/` | `rm -rf /tmp/opencode/model-runtimes` |
| Granite weights | `models/granite-speech-5.0-470m-turboctc/` | `rm -rf` that directory |
| Kokoro weights/voices | `models/kokoro-82m/` | `rm -rf` that directory |

No pip uninstall is needed: the binding was installed with `--target .tools/py`
and is removed with that directory. Restore the voice service with:

```bash
lfm3 audio && curl -sS http://127.0.0.1:8082/health
```

`.tools/` is already git-ignored (`.gitignore` line 21) and `models/` on line
38. This document is tracked; model and runtime files are not.
