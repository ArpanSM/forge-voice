# Local model bake-off — Stack B (Granite + LFM3-1.7B + Kokoro)

Date: 2026-11-08. Local only. No product code changes, no Groq/Orca/Go, no external CUDA.
The existing LFM3-Audio-2B **5/6 (all hard gates)** audio-local result is the baseline; it was
not re-run for this bake-off. The one baseline failure is the read-back street-name entity
(“88 Hyde/Tide Meridian Way” for “88 Meridian Way”).

## Stack B runtimes

| Component | Runtime | Version/backend | Path |
| --- | --- | --- | --- |
| STT | transcribe.cpp | 0.4.1 / Vulkan (GTX 1050 Ti) | `.tools/transcribe-cpp/...` + `.tools/py` |
| Chat/tools | LFM3-1.7B Q6_K | llama.cpp CUDA 2.68.0 (llama.cpp 0.8.0-dev, 1b6935b) | `~/.lmstudio` runtime, manual process |
| TTS | CrispASR Kokoro | 0.8.51 / Vulkan + `CRISPASR_KOKORO_GEN_GPU=1`, `--device 2` | `.tools/crispasr-vulkan/...` |

Resident processes during tests: LFM3-1.7B PID 191427/192621 on **8085** (1.83–1.94 GiB VRAM);
Granite loaded in-process (748 MiB); Kokoro peak 849 MiB. Only one large model at a time was
kept within the 4 GB card.

**Port 8080 blocker:** `lfm3 chat` could not bind 8080 because `oc-lan-forward.socket`
(OpenChamber LAN forwarding, PID 186706) already owns it. I did not touch that unit. I ran the
same LFM3-1.7B wrapper flags manually on **127.0.0.1:8085** (`--jinja --reasoning off`,
`-ngl 99 -c 8192 -t 4 -fa on`). `lfm3 audio` still uses 8082 normally.

Evidence:
- Before: `lfm3 off`; GPU 244/4096 MiB; no llama-server on 8080/8082; 8080 only the
  oc-lan-forward socket.
- After automated tests: killed the manual chat, `lfm3 off`; GPU 244 MiB; ports clear;
  `lfm3 audio` started, `curl http://127.0.0.1:8082/health` → `{"status":"ok"}`, 2590 MiB.
- Then stopped audio again for the listening room.

## STT: Granite Q8 (10 fixtures)

Warm model load 0.508 s; 748 MiB VRAM; 339 MB peak RSS; 0.49–0.69 s per clip
(**36.2–43.8× realtime**). WER uses lowercased punctuation-stripped text with spelled digits
normalized and adjacent digit tokens joined; entities are exact name/street/ZIP/phone.

| Fixture | WER | Entities | Fixture | WER | Entities |
|---|---:|---:|---|---:|---:|
| badline_01 | 2.7% | 4/4 | lowmic_01 | 0.0% | 4/4 |
| bargein_01 | 0.0% | 4/4 | multilingual_01 | 10.0% | 3/4 |
| emergency_01 | 0.0% | 4/4 | noisy_01 | 2.7% | 4/4 |
| entities_01 | 12.1% | 2/4 | packetloss_01 | 0.0% | 4/4 |
| readback_01 | 2.4% | 4/4 | silence_01 | 0.0% | 4/4 |

Corpus **2.78% WER**, **37/40 entity fields**. `readback_01` is clean (`88 Meridian Way`,
`95125`, `408-555-0142`), so Granite fixes the baseline’s read-back street miss at STT level.
`entities_01` still fails (`80 Tade Meridian Way`, ZIP `951`), and `multilingual_01` loses the
ZIP. On the six local audio scenarios, Granite gets **24/24 entities**.

## TTS: Kokoro Q8 + af_heart (10 scripts)

Batch CLI; no first-audio metric is exposed (only total WAV synthesis). All outputs 24 kHz
mono 16-bit. Total 15.3–20.4 s per script, **1.25–1.31× realtime**. Round-trip through
Granite: **1.67% WER** (6/360 edits), with all addresses/ZIPs/phones intact, including
“88 Meridian Way”. Kokoro’s clean synthesis is noticeably better for entity round-trip than
the existing LFM3-generated fixtures.

## Chat/tools: LFM3-1.7B, 8 product tools, 20 prompts

Exact tool-name + schema-required-args scoring; optional args not penalized. Median latency
**1.73 s** (range 1.21–3.06 s). **17/20 pass**, no malformed JSON or empty outputs.

Failures:
- `noavail_01` chose `get_service_area` instead of `transfer_to_human`.
- `emergency_02` (burst pipe) chose `get_service_area` instead of `create_emergency_ticket`.
- `handoff_01` answered in text with no tool call.

Booking, reschedule, cancel, status, pricing/no-tool, refusal/no-tool, out-of-area, gas
emergency, duplicate lookup and injection refusals selected the expected tool and required
arguments.

## End-to-end and LiveKit room

A single-pass “plan all tools from the transcript” test covered only 1/4 expected tools per
booking scenario (0/6 full), because LFM3-1.7B emits one tool call per turn. That is not a
valid full agent, so no 5/6 equivalence is claimed. A longer live utterance did complete the
stub flow: Granite transcript → LFM3-1.7B → `book_appointment` tool → Kokoro “booked” reply.
The stub read-back was garbled (“slot tu 1100 2026-1110-110”) and is not the product policy.

**Listening room (left running):**
- Room: **`forge-voice-stack-b`**
- Browser: **http://127.0.0.1:8001/** (token embedded in the page; also
  `/tmp/opencode/bakeoff/live/token.txt`, 24 h TTL)
- Join: open the URL, allow the microphone, press **Start microphone**, wait for the greeting.
- Demonstrates: greeting, Granite STT, LFM3-1.7B tool selection, Kokoro TTS. Booking tools are
  local stubs; this is **not** the full booking/policy demo.
- Processes: agent 193279, LiveKit 192645 (:7880), page 192736 (:8001), LFM3-1.7B 192621
  (:8085). VRAM ~1.83 GiB idle; Granite/Kokoro load on demand.

**Stop/cleanup:**
```bash
bash /tmp/opencode/bakeoff/live/stop.sh
```
The script kills the agent, page, LiveKit and manual chat, runs `lfm3 off`, waits, then starts
`lfm3 audio` and checks `http://127.0.0.1:8082/health`. Manual equivalent:
`kill 193279 192736 192645 192621; lfm3 off; sleep 2; lfm3 audio; curl -sS http://127.0.0.1:8082/health`.

## Recommendation

**Keep LFM3-Audio-2B as the demo baseline and do not replace it with Stack B yet.** Stack B
shows a real STT win on the six local audio fixtures (24/24 entities, 36–44× realtime vs the
baseline’s one read-back miss) and Kokoro TTS is usable at ~1.28× realtime with strong
round-trip WER. But the split stack needs three runtimes/ports, has a hard 8080 conflict on
this machine, exposes no first-audio metric, and the LFM3-1.7B tool layer is 17/20 and not the
product’s policy/confirmation/audit pipeline. It also still fails the held-out `entities_01`
STT entities. The honest next step is an optional Granite-STT pilot inside the existing
product pipeline (keeping LFM3-Audio TTS), not a demo swap.

Measured results are from this laptop; vendor WER/speed claims are not substituted for them.
