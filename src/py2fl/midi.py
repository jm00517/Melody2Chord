from __future__ import annotations

import json
import struct
from pathlib import Path

from .models import BAR_TICKS, NoteEvent, TrackData


def _read_vlq(data: bytes, index: int) -> tuple[int, int]:
    value = 0
    while True:
        byte = data[index]
        index += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, index


def _write_vlq(value: int) -> bytes:
    buffer = [value & 0x7F]
    value >>= 7
    while value:
        buffer.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(buffer))


def parse_midi_notes(path: Path) -> tuple[list[TrackData], int | None]:
    data = path.read_bytes()
    if data[:4] != b"MThd":
        raise ValueError("Invalid MIDI header")
    header_length = struct.unpack(">I", data[4:8])[0]
    _, track_count, division = struct.unpack(">HHH", data[8:14])
    if division <= 0:
        raise ValueError("Unsupported SMPTE MIDI division")

    index = 8 + header_length
    tracks: list[TrackData] = []
    tempo_bpm: int | None = None

    for _ in range(track_count):
        if data[index:index + 4] != b"MTrk":
            raise ValueError("Invalid MIDI track header")
        track_length = struct.unpack(">I", data[index + 4:index + 8])[0]
        track_data = data[index + 8:index + 8 + track_length]
        index += 8 + track_length
        abs_time = 0
        pos = 0
        running_status: int | None = None
        active: dict[tuple[int, int], list[tuple[int, int]]] = {}
        notes: list[NoteEvent] = []
        name = f"Track {len(tracks) + 1}"

        while pos < len(track_data):
            delta, pos = _read_vlq(track_data, pos)
            abs_time += delta
            status = track_data[pos]
            if status < 0x80:
                if running_status is None:
                    raise ValueError("Running status encountered without previous status")
                status = running_status
            else:
                pos += 1
                running_status = status

            if status == 0xFF:
                meta_type = track_data[pos]
                pos += 1
                meta_length, pos = _read_vlq(track_data, pos)
                meta_data = track_data[pos:pos + meta_length]
                pos += meta_length
                if meta_type == 0x03 and meta_data:
                    name = meta_data.decode("latin1", errors="ignore")
                elif meta_type == 0x51 and len(meta_data) == 3 and tempo_bpm is None:
                    micros = int.from_bytes(meta_data, "big")
                    if micros:
                        tempo_bpm = round(60_000_000 / micros)
                continue

            if status in (0xF0, 0xF7):
                sysex_length, pos = _read_vlq(track_data, pos)
                pos += sysex_length
                continue

            event_type = status & 0xF0
            channel = status & 0x0F

            if event_type in (0xC0, 0xD0):
                pos += 1
                continue

            data1 = track_data[pos]
            data2 = track_data[pos + 1]
            pos += 2

            if event_type == 0x90 and data2 > 0:
                active.setdefault((channel, data1), []).append((abs_time, data2))
            elif event_type in (0x80, 0x90):
                stack = active.get((channel, data1))
                if stack:
                    start, velocity = stack.pop()
                    duration = max(division // 8, abs_time - start)
                    notes.append(NoteEvent(pitch=data1, start=start, duration=duration, velocity=velocity, channel=channel))

        tracks.append(TrackData(name=name, notes=sorted(notes, key=lambda note: (note.start, note.pitch))))

    return tracks, tempo_bpm


def write_midi(path: Path, tracks: list[TrackData], tempo_bpm: int, ppq: int = 480) -> None:
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks) + 1, ppq)
    control_track = _build_control_track(tempo_bpm)
    rendered_tracks = [control_track]
    for track in tracks:
        rendered_tracks.append(_build_note_track(track))
    path.write_bytes(header + b"".join(rendered_tracks))


def write_meta(path: Path, metadata: dict[str, object]) -> None:
    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def _build_control_track(tempo_bpm: int) -> bytes:
    micros = round(60_000_000 / tempo_bpm)
    events = bytearray()
    events.extend(_write_vlq(0))
    events.extend(b"\xFF\x03\x08py2flctl")
    events.extend(_write_vlq(0))
    events.extend(b"\xFF\x51\x03" + micros.to_bytes(3, "big"))
    events.extend(_write_vlq(0))
    events.extend(b"\xFF\x58\x04\x04\x02\x18\x08")
    events.extend(_write_vlq(0))
    events.extend(b"\xFF\x2F\x00")
    return b"MTrk" + struct.pack(">I", len(events)) + bytes(events)


def _build_note_track(track: TrackData) -> bytes:
    events: list[tuple[int, int, int, int, int]] = []
    for note in track.notes:
        status_on = 0x90 | (track.channel & 0x0F)
        status_off = 0x80 | (track.channel & 0x0F)
        events.append((note.start, 1, status_on, note.pitch, max(1, min(127, note.velocity))))
        events.append((note.end, 0, status_off, note.pitch, 0))
    events.sort(key=lambda item: (item[0], item[1], item[3]))

    data = bytearray()
    track_name = track.name.encode("latin1", errors="ignore")[:127]
    data.extend(_write_vlq(0))
    data.extend(b"\xFF\x03" + bytes([len(track_name)]) + track_name)

    last_time = 0
    for abs_time, _, status, pitch, velocity in events:
        data.extend(_write_vlq(abs_time - last_time))
        data.extend(bytes([status, pitch, velocity]))
        last_time = abs_time

    data.extend(_write_vlq(0))
    data.extend(b"\xFF\x2F\x00")
    return b"MTrk" + struct.pack(">I", len(data)) + bytes(data)


def infer_bars_from_notes(notes: list[NoteEvent]) -> int:
    if not notes:
        return 4
    last_tick = max(note.end for note in notes)
    return max(1, (last_tick + BAR_TICKS - 1) // BAR_TICKS)
