#!/usr/bin/env python3
"""
Summarize Unreal Engine Blueprint text exports into compact execution paths.

Usage:
    python ue_blueprint_parser_v2.py blueprint.txt
    python ue_blueprint_parser_v2.py blueprint.txt -o summary.txt
    python ue_blueprint_parser_v2.py --clipboard
    python ue_blueprint_parser_v2.py --clipboard -o summary.txt
    python ue_blueprint_parser_v2.py blueprint.txt --paths-only

The parser is intentionally conservative: it reports connections found in the
export and does not try to infer Blueprint semantics.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Pin:
    name: str
    category: str = ""
    direction: str = ""
    default: Optional[str] = None
    pin_id: str = ""
    # Each LinkedTo entry is (other node object name, other pin GUID).
    links: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Node:
    object_name: str
    class_name: str
    display_name: str
    pins: list[Pin] = field(default_factory=list)

    def pins_by_direction(self, direction: str) -> list[Pin]:
        return [p for p in self.pins if p.direction == direction]


def unquote(value: str) -> str:
    """Decode common escaped characters inside Unreal's quoted values."""
    return value.replace(r'\"', '"').replace(r"\\", "\\")


def extract_balanced(text: str, opening_index: int) -> tuple[str, int]:
    """Return content inside balanced parentheses and the index after ')'."""
    depth = 0
    in_quote = False
    escaped = False
    for i in range(opening_index, len(text)):
        ch = text[i]
        if in_quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_quote = False
            continue
        if ch == '"':
            in_quote = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[opening_index + 1:i], i + 1
    return text[opening_index + 1:], len(text)


def extract_node_blocks(raw_text: str) -> list[tuple[str, str, str]]:
    """Extract Begin Object blocks; handles nested Begin Object/End Object."""
    starts = list(re.finditer(
        r'Begin Object\s+Class=([^\s]+)\s+Name="([^"]+)"',
        raw_text
    ))
    blocks = []
    for start in starts:
        # Only accept top-level Begin Object blocks.
        prefix = raw_text[:start.start()]
        depth = len(re.findall(r'\bBegin Object\b', prefix)) - len(
            re.findall(r'\bEnd Object\b', prefix)
        )
        if depth != 0:
            continue

        depth = 1
        token_re = re.compile(r'\bBegin Object\b|\bEnd Object\b')
        end_pos = None
        for token in token_re.finditer(raw_text, start.end()):
            if token.group() == "Begin Object":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    end_pos = token.start()
                    break
        if end_pos is not None:
            blocks.append((start.group(1), start.group(2), raw_text[start.end():end_pos]))
    return blocks


def read_quoted_property(text: str, prop: str) -> Optional[str]:
    match = re.search(r'\b' + re.escape(prop) + r'="((?:\\.|[^"])*)"', text)
    return unquote(match.group(1)) if match else None


def read_pin_blocks(body: str) -> list[str]:
    blocks = []
    marker = "CustomProperties Pin"
    pos = 0
    while True:
        idx = body.find(marker, pos)
        if idx < 0:
            break
        opening = body.find("(", idx + len(marker))
        if opening < 0:
            break
        content, end = extract_balanced(body, opening)
        blocks.append(content)
        pos = end
    return blocks


def parse_pin(pin_text: str) -> Optional[Pin]:
    name = read_quoted_property(pin_text, "PinName")
    if name is None:
        return None

    category = read_quoted_property(pin_text, "PinCategory") or ""
    # UE exports usually omit Direction for input pins; output pins specify it.
    direction = read_quoted_property(pin_text, "Direction") or "EGPD_Input"
    default = read_quoted_property(pin_text, "DefaultValue")
    pin_id_match = re.search(r"\bPinId=([^\s,)]+)", pin_text)
    pin_id = pin_id_match.group(1) if pin_id_match else ""

    links = []
    link_match = re.search(r'\bLinkedTo=\((.*?)\)', pin_text, re.DOTALL)
    if link_match:
        for item in link_match.group(1).split(","):
            item = item.strip()
            if not item:
                continue
            # UE references generally look like: NodeObjectName PinName
            parts = item.split(None, 1)
            if len(parts) == 2:
                links.append((parts[0], parts[1].strip()))
    return Pin(
        name=name,
        category=category,
        direction=direction,
        default=default,
        pin_id=pin_id,
        links=links,
    )


def friendly_node_name(class_name: str, object_name: str, body: str) -> str:
    cls = class_name.rsplit(".", 1)[-1]
    member = read_quoted_property(body, "MemberName")
    target_type = read_quoted_property(body, "TargetType")

    if "K2Node_DynamicCast" in cls:
        # TargetType formats vary, e.g. /Script/Engine.Character or
        # Class'/Script/Engine.Character'. Extract the class token, not its
        # repeated quoted object name.
        matches = re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)", target_type or "")
        target = matches[-1] if matches else "Unknown"
        return "CastTo" + target

    if "K2Node_Event" in cls:
        event = member or object_name
        event = re.sub(r"^K2_", "", event)
        event = re.sub(r"^Receive", "", event)
        return "Event" + event

    if "K2Node_CallFunction" in cls and member:
        return re.sub(r"^K2_", "", member)

    if "K2Node_VariableGet" in cls and member:
        return "Get " + member
    if "K2Node_VariableSet" in cls and member:
        return "Set " + member

    aliases = {
        "K2Node_IfThenElse": "Branch",
        "K2Node_ExecutionSequence": "Sequence",
        "K2Node_MacroInstance": "Macro",
        "K2Node_AbilityTask_WaitGameplayEvent": "WaitGameplayEvent",
    }
    if cls in aliases:
        return aliases[cls]

    # Keep unknown node classes identifiable rather than guessing.
    return cls.removeprefix("K2Node_")


def parse_nodes(raw_text: str) -> dict[str, Node]:
    nodes: dict[str, Node] = {}
    for class_name, object_name, body in extract_node_blocks(raw_text):
        node = Node(
            object_name=object_name,
            class_name=class_name,
            display_name=friendly_node_name(class_name, object_name, body),
        )
        for pin_text in read_pin_blocks(body):
            pin = parse_pin(pin_text)
            if pin:
                node.pins.append(pin)
        nodes[object_name] = node
    return nodes


def build_connection_indexes(nodes: dict[str, Node]):
    """Resolve UE's LinkedTo pin GUIDs and reconstruct incoming/outgoing edges.

    UE text exports commonly serialize LinkedTo=(OtherNode OtherPinGuid,).
    The second token is a PinId GUID, not the human-readable pin name.
    Some exports expose a connection on only one endpoint, so edges are
    reconstructed from either output-side or input-side links.
    """
    pin_lookup: dict[tuple[str, str], Pin] = {}
    for node in nodes.values():
        for pin in node.pins:
            if pin.pin_id:
                pin_lookup[(node.object_name, pin.pin_id)] = pin

    edges: set[tuple[str, str, str, str]] = set()
    for node in nodes.values():
        for pin in node.pins:
            if not pin.pin_id:
                continue
            for other_node_id, other_pin_id in pin.links:
                if pin.direction == "EGPD_Output":
                    # Current pin is the source; LinkedTo identifies the target.
                    edges.add((node.object_name, pin.pin_id, other_node_id, other_pin_id))
                elif pin.direction == "EGPD_Input":
                    # Current pin is the target; LinkedTo identifies the source.
                    edges.add((other_node_id, other_pin_id, node.object_name, pin.pin_id))

    outgoing: dict[tuple[str, str], list[tuple[str, str]]] = {}
    incoming: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for src_node, src_pin, dst_node, dst_pin in edges:
        outgoing.setdefault((src_node, src_pin), []).append((dst_node, dst_pin))
        incoming.setdefault((dst_node, dst_pin), []).append((src_node, src_pin))

    return pin_lookup, outgoing, incoming


def resolve_pin(node_id: str, pin_id: str, nodes: dict[str, Node],
                pin_lookup: dict[tuple[str, str], Pin]) -> str:
    node = nodes.get(node_id)
    pin = pin_lookup.get((node_id, pin_id))
    if node and pin:
        return f"{node.display_name}.{pin.name}"
    if node:
        return f"{node.display_name}.?"
    return f"{node_id}.?"

def is_exec_pin(pin: Pin) -> bool:
    return pin.category in {"exec", "delegate"}


def node_description(
    node: Node,
    nodes: dict[str, Node],
    pin_lookup: dict[tuple[str, str], Pin],
    outgoing: dict[tuple[str, str], list[tuple[str, str]]],
    incoming: dict[tuple[str, str], list[tuple[str, str]]],
) -> str:
    inputs = []
    outputs = []

    for pin in node.pins:
        if not pin.pin_id or is_exec_pin(pin):
            continue
        key = (node.object_name, pin.pin_id)
        if pin.direction == "EGPD_Input":
            sources = incoming.get(key, [])
            if sources:
                source_names = []
                for src_node, src_pin in sources:
                    source_names.append(resolve_pin(src_node, src_pin, nodes, pin_lookup))
                desc = f"{pin.name}=" + "|".join(dict.fromkeys(source_names))
                if pin.name not in {"self", "WorldContextObject"}:
                    inputs.append(desc)
            elif pin.default not in (None, "") and pin.name not in {"self", "WorldContextObject"}:
                inputs.append(f"{pin.name}={pin.default}")
        elif pin.direction == "EGPD_Output":
            targets = outgoing.get(key, [])
            if targets:
                target_names = [
                    resolve_pin(target_node, target_pin, nodes, pin_lookup)
                    for target_node, target_pin in targets
                ]
                outputs.append(f"{pin.name}->{ '|'.join(dict.fromkeys(target_names)) }")

    # Execution links are shown too; their target PinId is resolved to a node/pin name.
    for pin in node.pins:
        if not pin.pin_id or not is_exec_pin(pin) or pin.direction != "EGPD_Output":
            continue
        targets = outgoing.get((node.object_name, pin.pin_id), [])
        if targets:
            target_names = [
                nodes[target_node].display_name if target_node in nodes else target_node
                for target_node, _ in targets
            ]
            outputs.append(f"{pin.name}->{ '|'.join(dict.fromkeys(target_names)) }")

    return f"{node.display_name}(input:{', '.join(inputs) or '-'}; output:{', '.join(outputs) or '-'})"


def exec_targets(node: Node, outgoing: dict[tuple[str, str], list[tuple[str, str]]]) -> list[tuple[str, str]]:
    targets = []
    for pin in node.pins:
        if not pin.pin_id or not is_exec_pin(pin) or pin.direction != "EGPD_Output":
            continue
        for target_id, _ in outgoing.get((node.object_name, pin.pin_id), []):
            targets.append((pin.name, target_id))
    return targets

def find_start_nodes(nodes: dict[str, Node]) -> list[str]:
    starts = []
    for node_id, node in nodes.items():
        cls = node.class_name.rsplit(".", 1)[-1]
        if cls in {"K2Node_Event", "K2Node_CustomEvent", "K2Node_ReceiveBeginPlay"}:
            starts.append(node_id)
        elif node.display_name in {"EventActivateAbility", "EventBeginPlay"}:
            starts.append(node_id)
    return starts or (list(nodes.keys())[:1] if nodes else [])


def execution_paths(
    nodes: dict[str, Node],
    outgoing: dict[tuple[str, str], list[tuple[str, str]]],
    max_paths: int = 80,
    max_depth: int = 200,
) -> list[list[str]]:
    """Return execution paths; path-local cycle detection preserves converging branches."""
    paths: list[list[str]] = []

    def walk(node_id: str, path: list[str], seen: set[str]) -> None:
        if len(paths) >= max_paths:
            return
        if node_id not in nodes:
            paths.append(path + [f"[Unknown node: {node_id}]"])
            return
        if node_id in seen:
            paths.append(path + [f"[cycle to {nodes[node_id].display_name}]"])
            return
        node = nodes[node_id]
        new_path = path + [node_id]
        targets = exec_targets(node, outgoing)
        if not targets or len(new_path) >= max_depth:
            paths.append(new_path)
            return
        new_seen = seen | {node_id}
        for _, target_id in targets:
            walk(target_id, new_path, new_seen)

    for start in find_start_nodes(nodes):
        walk(start, [], set())
        if len(paths) >= max_paths:
            break
    return paths


def render_summary(raw_text: str, paths_only: bool = False) -> str:
    nodes = parse_nodes(raw_text)
    if not nodes:
        return (
            "没有识别到节点块。请确认输入是 UE Blueprint 的文本导出，"
            "其中包含 `Begin Object Class=... Name=\"...\"`。"
        )

    pin_lookup, outgoing, incoming = build_connection_indexes(nodes)
    paths = execution_paths(nodes, outgoing)
    path_node_ids = {node_id for path in paths for node_id in path if node_id in nodes}

    lines = [
        f"Blueprint summary: {len(nodes)} nodes",
        "=" * 60,
        "",
        "EXECUTION PATHS",
        "---------------",
    ]
    if not paths:
        lines.append("没有识别到执行入口。")
    for index, path in enumerate(paths, 1):
        labels = [
            node_description(nodes[nid], nodes, pin_lookup, outgoing, incoming)
            if nid in nodes else nid
            for nid in path
        ]
        lines.append(f"Path {index}:")
        lines.append("  " + " -> ".join(labels))
        lines.append("")

    if not paths_only:
        # Avoid printing all execution-path nodes a second time. Pure data nodes
        # are retained because they often explain attribute values and references.
        support_nodes = [node for node_id, node in nodes.items() if node_id not in path_node_ids]
        lines.extend(["", "SUPPORTING NODES (data-only / not on an execution path)", "-----------------------------------------------------"])
        if not support_nodes:
            lines.append("没有额外节点。")
        else:
            for node in support_nodes:
                lines.append(node_description(node, nodes, pin_lookup, outgoing, incoming))

    lines.extend(["", "NOTES", "-----"])
    lines.append("- LinkedTo 中的 GUID 已映射回真实 PinName；若无法映射会显示 `.?`，而不是猜测。")
    lines.append("- `input` 中的 `Node.Pin` 表示该输入引脚的数据来源；`output` 中的连线表示目标节点/引脚。")
    lines.append("- Path 编号和路径展开由脚本生成；Branch 的 `then` 通常对应条件成立分支，`else` 对应条件不成立分支。")
    lines.append("- 这是连接结构摘要，不等于完整运行语义；宏、委托和特殊节点仍需对照编辑器核验。")
    if len(paths) >= 80:
        lines.append("- 执行路径达到上限 80 条，可能还有未显示的分支。")
    return "\n".join(lines)

def read_clipboard() -> str:
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        text = root.clipboard_get()
        root.destroy()
        return text
    except Exception as exc:
        raise RuntimeError(
            "读取剪贴板失败。请传入文本文件路径，或确认 Windows 剪贴板可用。"
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize Unreal Blueprint text exports.")
    parser.add_argument("file", nargs="?", help="Blueprint export text file")
    parser.add_argument("-o", "--output", help="write summary to a file instead of stdout")
    parser.add_argument("--clipboard", action="store_true", help="read raw Blueprint text from clipboard")
    parser.add_argument("--paths-only", action="store_true", help="omit supporting/data-only nodes")
    args = parser.parse_args()

    try:
        raw_text = read_clipboard() if args.clipboard or not args.file else Path(args.file).read_text(encoding="utf-8-sig")
    except (OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    summary = render_summary(raw_text, paths_only=args.paths_only)
    if args.output:
        Path(args.output).write_text(summary, encoding="utf-8")
        print(f"Summary written to: {args.output}")
    else:
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
