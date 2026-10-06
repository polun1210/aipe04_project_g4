"""用本機 Claude Code 與 Codex CLI 各自標註一張照片（D20）。

雙盲與「只看圖」的做法：
- 每個標註者、每張照片各開一個**只放那張照片**的暫存資料夾當工作目錄，放在系統暫存區（repo 之外）。
  schema 檔與輸出檔放在另一個暫存資料夾，工作目錄裡看不到。兩個標註者的輸出都寫到 repo 的
  輸出資料夾，彼此的工作目錄裡都沒有對方的結果與既有標準答案。
- Claude：`--restricted` 把讀檔範圍鎖在工作目錄內、移除所有能執行程式的工具，並忽略個人與專案設定；
  `--safe-mode` 另外停用 CLAUDE.md、技能、外掛、hooks、MCP 等所有自訂內容；
  `--tools Read` 只開放讀檔工具、`--strict-mcp-config` 不載入任何 MCP 伺服器；
  非互動模式下未核准的工具一律拒絕，因此不能執行程式、上網或讀工作目錄外的檔案。
- Codex：`--sandbox read-only`，不能寫檔、不能連網。
  已知限制（只剩 Codex 這側）：Codex 的唯讀沙盒仍能「讀」工作目錄外的檔案，無法從技術上完全阻止它去翻 repo；
  因為工作目錄在 repo 之外、提示詞也明確禁止，風險低，但報告方法論時應如實說明。
- 提示詞從 stdin 傳入：Windows 上經 .cmd 包裝的指令，多行參數會被截斷。
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from scripts.annotate.schema import JSON_SCHEMA, PROMPT, PROMPT_VERSION, Annotation, AnnotationRecord

ANNOTATORS = ("claude", "codex")
TIMEOUT_SECONDS = 600

# (指令, 工作目錄, stdin) → 執行結果。測試換成假的，不真的執行 claude／codex
Runner = Callable[[list[str], Path, str], subprocess.CompletedProcess]


class AnnotationError(Exception):
    """標註工具執行失敗或輸出不符結構。"""


_SECRET_ENV = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.IGNORECASE)


def annotator_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    """交給標註工具的環境變數：拿掉看起來像金鑰的變數；PATH 去掉 WindowsApps。

    本機的 pwsh.exe 是 Microsoft Store 版（WindowsApps），Codex 沙盒的受限權限啟動不了它，
    Codex 就會改用電腦操作工具在沙盒外執行（D58、D59）；去掉後改用內建 PowerShell，沙盒才有效。
    """
    env = {k: v for k, v in (environ if environ is not None else os.environ).items() if not _SECRET_ENV.search(k)}
    for key in [k for k in env if k.upper() == "PATH"]:
        env[key] = os.pathsep.join(p for p in env[key].split(os.pathsep) if "windowsapps" not in p.lower())
    return env


def run_subprocess(cmd: list[str], cwd: Path, stdin: str) -> subprocess.CompletedProcess:
    exe = shutil.which(cmd[0])
    if exe is None:
        raise AnnotationError(f"找不到指令 {cmd[0]}，請確認已安裝並登入")
    return subprocess.run(
        [exe, *cmd[1:]],
        cwd=cwd,
        env=annotator_env(),
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        check=False,
    )


def claude_command(model: str) -> list[str]:
    return [
        "claude",
        "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(JSON_SCHEMA, ensure_ascii=False),
        "--model", model,
        "--restricted",
        "--safe-mode",  # 不載入 CLAUDE.md、技能、外掛、hooks、MCP 等個人自訂內容
        "--tools", "Read",
        "--allowedTools", "Read",
        "--strict-mcp-config",
    ]  # fmt: skip


def codex_command(model: str, image: Path, workdir: Path, schema: Path, output: Path) -> list[str]:
    return [
        "codex",
        "exec",
        "--image", str(image),
        "--sandbox", "read-only",
        "--skip-git-repo-check",
        "--cd", str(workdir),
        "--model", model,
        "--output-schema", str(schema),
        "--output-last-message", str(output),
        # 不載入使用者的電腦操作、瀏覽器外掛與 node_repl：它們能在沙盒外操作電腦（D59）
        "-c", "mcp_servers.node_repl.enabled=false",
        "-c", 'plugins."computer-use@openai-bundled".enabled=false',
        "-c", 'plugins."unified-computer-use@openai-bundled".enabled=false',
        "-c", 'plugins."chrome@openai-bundled".enabled=false',
        "-c", 'plugins."browser@openai-bundled".enabled=false',
        "-",  # 提示詞從 stdin 讀
    ]  # fmt: skip


def annotate_image(image_path: Path, annotator: str, model: str, runner: Runner = run_subprocess) -> AnnotationRecord:
    """在只含這張照片的暫存資料夾裡執行一個標註者，回傳驗證過的標註紀錄。"""
    if annotator not in ANNOTATORS:
        raise ValueError(f"未知的標註者 {annotator}")
    prompt = PROMPT.format(filename=image_path.name)
    with TemporaryDirectory(prefix="annotate-work-") as work, TemporaryDirectory(prefix="annotate-io-") as io:
        workdir, iodir = Path(work), Path(io)
        image = workdir / image_path.name
        shutil.copyfile(image_path, image)  # 只複製像素檔，不帶原資料夾的任何東西
        seen_sha256 = image_sha256(image)  # 實際交給模型的那份副本的指紋
        if annotator == "claude":
            proc = runner(claude_command(model), workdir, prompt)
            _check(proc, annotator, image_path)
            payload, reported = _parse_claude(proc.stdout, image_path)
        else:
            schema, output = iodir / "schema.json", iodir / "output.json"
            schema.write_text(json.dumps(JSON_SCHEMA, ensure_ascii=False), encoding="utf-8")
            proc = runner(codex_command(model, image, workdir, schema, output), workdir, prompt)
            _check(proc, annotator, image_path)
            if not output.exists():
                raise AnnotationError(f"{image_path.name}：codex 沒有寫出結果")
            payload, reported = _loads(output.read_text(encoding="utf-8"), image_path), []
    try:
        annotation = Annotation.model_validate(payload)
    except ValidationError as e:
        raise AnnotationError(f"{image_path.name}：{annotator} 的標註不符結構：{e}") from e
    return AnnotationRecord(
        image_id=image_path.stem,
        annotator=annotator,
        model=model,
        models_reported=reported,
        prompt_version=PROMPT_VERSION,
        annotated_at=datetime.now(timezone.utc),
        annotation=annotation,
        image_sha256=seen_sha256,
    )


def image_sha256(image_path: Path) -> str:
    return hashlib.sha256(image_path.read_bytes()).hexdigest()


def _stale_reason(target: Path, image_path: Path, model: str) -> str | None:
    """已有標註時，確認它對應的還是同一張照片、同一個模型、同一版提示詞；不是就回傳原因。"""
    record = AnnotationRecord.model_validate_json(target.read_text(encoding="utf-8"))
    if record.image_sha256 is not None and record.image_sha256 != image_sha256(image_path):
        return "照片內容已經換過"
    if record.model != model:
        return f"模型不同（{record.model} → {model}）"
    if record.prompt_version != PROMPT_VERSION:
        return f"提示詞版本不同（{record.prompt_version} → {PROMPT_VERSION}）"
    return None


def _check(proc: subprocess.CompletedProcess, annotator: str, image_path: Path) -> None:
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-500:]
        raise AnnotationError(f"{image_path.name}：{annotator} 結束碼 {proc.returncode}：{tail}")


def _loads(text: str, image_path: Path) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise AnnotationError(f"{image_path.name}：輸出不是 JSON") from e


def _parse_claude(stdout: str, image_path: Path) -> tuple[dict, list[str]]:
    """claude -p --output-format json 的輸出：結構化結果在 structured_output，模型用量在 modelUsage。"""
    envelope = _loads(stdout, image_path)
    if envelope.get("is_error"):
        raise AnnotationError(f"{image_path.name}：claude 回報錯誤：{envelope.get('result')}")
    payload = envelope.get("structured_output")
    if payload is None:  # 舊版沒有 structured_output 時，結果文字本身應是 JSON
        payload = _loads(envelope.get("result") or "", image_path)
    return payload, sorted(envelope.get("modelUsage") or {})


def annotate_all(
    images: list[Path],
    out: Path,
    models: dict[str, str],
    force: bool = False,
    runner: Runner = run_subprocess,
) -> list[str]:
    """每張照片依序給每個標註者標註，寫到 <out>/<標註者>/<照片編號>.json。回傳失敗清單。"""
    failed = []
    for image_path in images:
        for annotator, model in models.items():
            target = out / annotator / f"{image_path.stem}.json"
            if target.exists() and not force:
                stale = _stale_reason(target, image_path, model)
                if stale:  # 不默默沿用舊標註，也不自動覆蓋：要使用者確認後加 --force 重做
                    print(f"失敗 {annotator} {image_path.stem}：已有標註但{stale}，確認後加 --force 重做")
                    failed.append(f"{annotator}:{image_path.stem}")
                else:
                    print(f"跳過 {annotator} {image_path.stem}（已標註；要重做加 --force）")
                continue
            try:
                record = annotate_image(image_path, annotator, model, runner)
            except (AnnotationError, subprocess.TimeoutExpired) as e:
                print(f"失敗 {annotator} {image_path.stem}：{e}")
                failed.append(f"{annotator}:{image_path.stem}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
            print(f"完成 {annotator} {image_path.stem}（{len(record.annotation.rows)} 列）")
    return failed
