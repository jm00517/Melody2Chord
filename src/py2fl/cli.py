from __future__ import annotations

import argparse
import json
from pathlib import Path

from .generator import generate_candidates, generate_song
from .models import GenerationRequest
from .web import run_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="py2fl", description="Generate FL Studio friendly MIDI arrangements.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate", help="Generate a MIDI arrangement from text, melody, or both.")
    generate_parser.add_argument("--text", help="Text prompt or lyrics.")
    generate_parser.add_argument("--melody-midi", type=Path, help="Path to a melody MIDI file.")
    generate_parser.add_argument("--progression", help="Chord progression, for example 1-5-6-4 or Am-F-C-G.")
    generate_parser.add_argument("--tempo", type=int, help="Tempo override in BPM.")
    generate_parser.add_argument("--key", help="Key override, for example C, F#, or A.")
    generate_parser.add_argument("--genre", help="Genre hint, for example trap or rnb.")
    generate_parser.add_argument("--bars", type=int, help="Number of bars to generate.")
    generate_parser.add_argument("--chord-density", choices=["1", "2", "3", "auto"], help="Chord changes per bar. Default: auto")
    generate_parser.add_argument("--melody-density", choices=["sparse", "normal", "dense", "xdense", "auto"], help="Melody note density. Default: auto")
    generate_parser.add_argument("--chord-rhythm-style", choices=["hold", "stab", "strum", "auto"], help="Chord rhythm playback style. Default: auto")
    generate_parser.add_argument("--seed", type=int, help="Random seed for reproducible output.")
    generate_parser.add_argument("--count", type=int, default=1, help="Number of candidate options to generate.")
    generate_parser.add_argument("--out", type=Path, default=Path("exports"), help="Base output directory.")

    serve_parser = subparsers.add_parser("serve", help="Run the local web UI.")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host to bind. Default: 127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765, help="Port to bind. Default: 8765")
    serve_parser.add_argument("--out", type=Path, default=Path("exports"), help="Base output directory for generated files.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "generate":
        if not args.text and not args.melody_midi and not args.progression:
            parser.error("generate requires --text, --melody-midi, --progression, or a valid combination")
        request = GenerationRequest(
            text=args.text,
            melody_midi_path=args.melody_midi,
            chord_progression=args.progression,
            tempo=args.tempo,
            key=args.key,
            genre=args.genre,
            bars=args.bars,
            chord_density=None if args.chord_density == "auto" else args.chord_density,
            melody_density=None if args.melody_density == "auto" else args.melody_density,
            chord_rhythm_style=None if args.chord_rhythm_style == "auto" else args.chord_rhythm_style,
            seed=args.seed,
            output_dir=args.out,
        )
        if args.count > 1:
            results = generate_candidates(request, count=args.count)
            print(json.dumps({
                "batch_output_dir": str(results[0].output_dir.parent),
                "candidates": [
                    {
                        "output_dir": str(result.output_dir),
                        "files": [str(path) for path in result.files],
                        "metadata": result.metadata,
                    }
                    for result in results
                ],
            }, indent=2))
        else:
            result = generate_song(request)
            print(json.dumps({
                "output_dir": str(result.output_dir),
                "files": [str(path) for path in result.files],
                "metadata": result.metadata,
            }, indent=2))
        return 0

    if args.command == "serve":
        run_server(host=args.host, port=args.port, output_dir=args.out)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
