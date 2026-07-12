import json
import sys
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python merge_chunks.py <output_dir> [output_file]")
        sys.exit(1)

    output_dir = Path(sys.argv[1])
    output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else output_dir / "chunks.jsonl"

    order = [
        "chunks_8_학사일정.jsonl",
        "chunks_9_학사제도변경.jsonl",
        "chunks_1.jsonl",
        "chunks_2.jsonl",
        "chunks_3.jsonl",
        "chunks_4.jsonl",
        "chunks_5.jsonl",
        "chunks_6.jsonl",
        "chunks_7.jsonl",
    ]

    per_file_counts = {}
    empty_text_chunks = []
    char_count_fixed = []
    merged = []

    idx = 0
    for fname in order:
        fpath = output_dir / fname
        if not fpath.exists():
            print(f"WARNING: file not found, skipping: {fpath}")
            per_file_counts[fname] = 0
            continue

        count = 0
        with open(fpath, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"ERROR: failed to parse {fname} line {line_num}: {e}")
                    continue

                new_chunk_id = f"chunk_{idx:04d}"
                obj["chunk_id"] = new_chunk_id
                obj["source_file"] = fname

                text = obj.get("text", "")
                if not text:
                    empty_text_chunks.append(new_chunk_id)

                actual_len = len(text)
                if obj.get("char_count") != actual_len:
                    char_count_fixed.append((new_chunk_id, obj.get("char_count"), actual_len))
                    obj["char_count"] = actual_len

                merged.append(obj)
                idx += 1
                count += 1

        per_file_counts[fname] = count

    with open(output_file, "w", encoding="utf-8") as f:
        for obj in merged:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    print("=" * 50)
    print("병합 완료 (Merge complete)")
    print("=" * 50)
    print(f"최종 총 청크 개수: {len(merged)}")
    print(f"결과 파일: {output_file}")
    print()
    print("파일별 청크 개수:")
    for fname in order:
        print(f"  {fname}: {per_file_counts.get(fname, 0)}개")
    print()

    if empty_text_chunks:
        print(f"WARNING: text 필드가 비어있는 청크 {len(empty_text_chunks)}개 발견:")
        for cid in empty_text_chunks:
            print(f"  - {cid}")
    else:
        print("text 필드가 비어있는 청크 없음 (OK)")

    print()
    if char_count_fixed:
        print(f"char_count 불일치로 재계산한 청크 {len(char_count_fixed)}개:")
        for cid, old, new in char_count_fixed:
            print(f"  - {cid}: {old} -> {new}")
    else:
        print("모든 char_count가 text 길이와 일치함 (OK)")

if __name__ == "__main__":
    main()
