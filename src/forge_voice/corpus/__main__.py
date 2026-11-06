"""`python -m forge_voice.corpus` entry point."""

from __future__ import annotations

from pathlib import Path

from forge_voice.corpus.generator import generate_corpus


def main() -> int:
    summary = generate_corpus(Path.cwd())
    print(
        f"corpus: {summary.text_scenarios} text + {summary.audio_scenarios} audio, "
        f"{len(summary.artifacts)} artifacts"
    )
    print(f"manifest sha256: {summary.manifest_sha256}")
    print(f"output: {summary.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
