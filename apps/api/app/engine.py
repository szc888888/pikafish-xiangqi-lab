import asyncio
import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any

from .models import CandidateFilterSummary, CandidateRejection, EngineLine, EngineResponse, Score
from .logging_config import get_logger, log_extra, request_id_context
from .settings import PROJECT_ROOT
from .xiangqi import Position, describe_uci, terminal_status, validate_candidate, validate_moves

logger = get_logger(__name__)


def _log_fields(**values: Any) -> dict[str, Any]:
    return log_extra(request_id=request_id_context.get(), **values)


def _exception_fields(exc: BaseException) -> dict[str, str]:
    frames = []
    traceback = exc.__traceback__
    while traceback is not None:
        code = traceback.tb_frame.f_code
        frames.append(f"{Path(code.co_filename).name}:{traceback.tb_lineno}:{code.co_name}")
        traceback = traceback.tb_next
    return {
        "exception_type": "EngineUnavailable" if isinstance(exc, EngineRuleViolation) else type(exc).__name__,
        "stack_locations": "|".join(frames[-8:]) or "-",
    }


def _bounded(value: int, low: int, high: int) -> int:
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return low


class EngineUnavailable(RuntimeError):
    pass


class EngineRuleViolation(EngineUnavailable):
    def __init__(self, message: str, summary: CandidateFilterSummary):
        super().__init__(message)
        self.summary = summary
        self.code = "no_legal_engine_candidate"


class PikafishEngine:
    def __init__(self) -> None:
        root = PROJECT_ROOT
        self.path = Path(os.getenv("PIKAFISH_PATH", str(root / "engine" / "pikafish.exe")))
        self.eval_file = os.getenv("PIKAFISH_EVAL_FILE", "")
        if not self.eval_file:
            candidates = list(self.path.parent.glob("*.nnue")) if self.path.parent.exists() else []
            self.eval_file = str(candidates[0]) if candidates else ""
        self.default_depth = int(os.getenv("PIKAFISH_DEFAULT_DEPTH", "15"))
        self.timeout_seconds = float(os.getenv("PIKAFISH_TIMEOUT_SECONDS", "30"))
        self.process: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.last_error: str | None = None
        self.engine_version: str | None = None
        self.nnue_version: str | None = None

    @property
    def configured(self) -> bool:
        return self.path.is_file()

    @property
    def ready(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def start(self) -> None:
        if self.ready:
            return
        logger.info("engine.starting", extra=_log_fields(
            event="engine.starting", path=str(self.path), nnue_path=self.eval_file or "-"
        ))
        if not self.configured:
            self.last_error = f"找不到 Pikafish 可执行文件: {self.path}"
            logger.error("engine.start_failed", extra=_log_fields(
                event="engine.start_failed", phase="configuration",
                path=str(self.path), nnue_path=self.eval_file or "-",
                outcome="missing_executable", exception_type="FileNotFoundError",
            ))
            return
        phase = "spawn"
        try:
            self.process = await asyncio.create_subprocess_exec(
                str(self.path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.path.parent),
            )
            pid = self.process.pid
            phase = "uci"
            logger.info("engine.handshake", extra=_log_fields(
                event="engine.handshake", phase=phase, pid=pid, outcome="started"
            ))
            await self._send("uci")
            uci_lines = await self._wait_for("uciok")
            self.engine_version = self._engine_version_from_uci(uci_lines)
            self.nnue_version = self._hash_nnue(self.eval_file)
            if self.eval_file:
                await self._send(f"setoption name EvalFile value {self.eval_file}")
            phase = "isready"
            logger.info("engine.handshake", extra=_log_fields(
                event="engine.handshake", phase=phase, pid=pid, outcome="started"
            ))
            await self._send("isready")
            await self._wait_for("readyok")
            self.last_error = None
            logger.info("engine.ready", extra=_log_fields(
                event="engine.ready", phase=phase, path=str(self.path),
                nnue_path=self.eval_file or "-", pid=pid, outcome="success",
            ))
        except Exception as exc:
            self.last_error = str(exc)
            process = self.process
            logger.error("engine.start_failed", extra=_log_fields(
                event="engine.start_failed", phase=phase,
                path=str(self.path), nnue_path=self.eval_file or "-",
                pid=getattr(process, "pid", "-"), outcome="failed",
                **_exception_fields(exc),
            ))
            await self.stop()

    async def stop(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        logger.info("engine.stopping", extra=_log_fields(
            event="engine.stopping", pid=getattr(process, "pid", "-"), outcome="requested"
        ))
        if process.returncode is None:
            try:
                process.kill()
                await process.wait()
            except Exception as exc:
                logger.error("engine.stopped", extra=_log_fields(
                    event="engine.stopped", pid=getattr(process, "pid", "-"),
                    outcome="failed", **_exception_fields(exc),
                ))
                return
        logger.info("engine.stopped", extra=_log_fields(
            event="engine.stopped", pid=getattr(process, "pid", "-"), outcome="success"
        ))

    async def reset(self) -> None:
        await self.stop()
        await self.start()
        logger.info("engine.reset", extra=_log_fields(
            event="engine.reset", outcome="success" if self.ready else "failed"
        ))

    async def _send(self, command: str) -> None:
        if not self.process or not self.process.stdin:
            raise EngineUnavailable(self.last_error or "Pikafish 未启动")
        self.process.stdin.write((command + "\n").encode())
        await self.process.stdin.drain()

    async def _readline(self, timeout: float | None = None) -> str:
        if not self.process or not self.process.stdout:
            raise EngineUnavailable(self.last_error or "Pikafish 未启动")
        line = await asyncio.wait_for(self.process.stdout.readline(), timeout or self.timeout_seconds)
        if not line:
            logger.warning("engine.unexpected_exit", extra=_log_fields(
                event="engine.unexpected_exit", pid=getattr(self.process, "pid", "-"),
                returncode=getattr(self.process, "returncode", "-"), outcome="eof",
            ))
            raise EngineUnavailable("Pikafish 进程已退出")
        return line.decode(errors="replace").strip()

    async def _wait_for(self, token: str) -> list[str]:
        lines: list[str] = []
        while True:
            line = await self._readline()
            lines.append(line)
            if token in line:
                return lines

    @staticmethod
    def _engine_version_from_uci(lines: list[str]) -> str | None:
        return next((line[len("id name "):].strip() for line in lines if line.startswith("id name ") and line[len("id name "):].strip()), None)

    @staticmethod
    def _hash_nnue(path: str) -> str | None:
        if not path:
            return None
        file_path = Path(path)
        if not file_path.is_file():
            return None
        digest = hashlib.sha256()
        with file_path.open("rb") as model_file:
            for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"

    async def analyze(
        self,
        fen: str,
        moves: list[str],
        depth: int | None,
        movetime_ms: int,
        multipv: int,
        threads: int = 1,
        hash_mb: int = 16,
    ) -> EngineResponse:
        valid, error, index = validate_moves(fen, moves)
        if not valid:
            raise ValueError(f"第 {index + 1} 步无效: {error}")
        position = Position.from_fen(fen)
        for move in moves:
            position.apply_uci(move)
        terminal = terminal_status(position)
        if terminal:
            return EngineResponse(bestmove="0000", terminal_status=terminal)
        async with self.lock:
            await self.start()
            if not self.ready:
                raise EngineUnavailable(self.last_error or "Pikafish 未配置")
            effective_depth = _bounded(depth or self.default_depth, 1, 64)
            bounded_movetime = _bounded(movetime_ms, 0, 120000)
            bounded_multipv = _bounded(multipv, 1, 32)
            bounded_threads = _bounded(threads, 1, 128)
            bounded_hash = _bounded(hash_mb, 1, 8192)
            pid = getattr(self.process, "pid", "-")
            started_at = time.monotonic()
            params = dict(
                depth=effective_depth, movetime_ms=bounded_movetime,
                multipv=bounded_multipv, threads=bounded_threads, hash_mb=bounded_hash,
            )
            logger.info("engine.search.started", extra=_log_fields(
                event="engine.search.started", pid=pid, outcome="started", **params
            ))
            try:
                result = await self._search(
                    fen, moves, effective_depth, bounded_movetime, bounded_multipv,
                    bounded_threads, bounded_hash,
                    search_params=params, pid=pid, started_at=started_at,
                )
                return result
            except Exception as exc:
                cause = exc.__cause__ if isinstance(exc.__cause__, TimeoutError) else exc
                outcome = "timeout" if isinstance(cause, TimeoutError) else "failed"
                logger.error("engine.search.failed", extra=_log_fields(
                    event="engine.search.failed",
                    pid=pid, outcome=outcome,
                    duration_ms=round((time.monotonic() - started_at) * 1000),
                    **params, **_exception_fields(cause),
                ))
                raise

    async def _search(
        self, fen: str, moves: list[str], depth: int | None, movetime_ms: int,
        multipv: int, threads: int, hash_mb: int, *, search_params: dict[str, int],
        pid: int | str, started_at: float,
    ) -> EngineResponse:
            await self._send(f"setoption name Threads value {threads}")
            await self._send(f"setoption name Hash value {hash_mb}")
            await self._send(f"setoption name MultiPV value {multipv}")
            command = f"position fen {fen}"
            if moves:
                command += " moves " + " ".join(moves)
            await self._send(command)
            await self._send("isready")
            await self._wait_for("readyok")
            go = f"go depth {depth}" if not movetime_ms else f"go movetime {movetime_ms}"
            await self._send(go)
            raw_info: list[str] = []
            parsed: dict[str, Any] = {"lines_by_depth": {}}
            search_timeout = max(self.timeout_seconds, (movetime_ms / 1000) + 10 if movetime_ms else self.timeout_seconds)
            try:
                while True:
                    line = await self._readline(search_timeout)
                    if line.startswith("info"):
                        raw_info.append(line)
                        self._parse_info(line, parsed)
                    elif line.startswith("bestmove"):
                        parts = line.split()
                        bestmove = parts[1] if len(parts) > 1 else "0000"
                        line_set = self._final_lines(parsed.get("lines_by_depth", {}), multipv)
                        board = Position.from_fen(fen)
                        for previous_move in moves:
                            board.apply_uci(previous_move)
                        current_position = Position.from_fen(fen)
                        positions = [Position([row[:] for row in current_position.board], current_position.red_to_move)]
                        for move in moves:
                            current_position.apply_uci(move)
                            positions.append(Position([row[:] for row in current_position.board], current_position.red_to_move))
                        candidate_rows = [
                            (rank, line["pv"][0], line)
                            for rank, line in sorted(line_set.items())
                            if line.get("pv")
                        ]
                        requested = max(multipv, len(candidate_rows), 1)
                        rejected: list[CandidateRejection] = []
                        accepted: list[tuple[int, str, dict[str, Any]]] = []
                        seen: set[str] = set()
                        for rank, candidate, line in candidate_rows:
                            if candidate in seen:
                                continue
                            seen.add(candidate)
                            validation = validate_candidate(current_position, candidate, positions, moves)
                            if validation.issue:
                                rejected.append(CandidateRejection(move=candidate, code=validation.issue.code, reason=validation.issue.message))
                            else:
                                accepted.append((rank, candidate, line))

                        if bestmove not in {"0000", "(none)", "none"} and bestmove not in seen:
                            validation = validate_candidate(current_position, bestmove, positions, moves)
                            if validation.issue:
                                rejected.append(CandidateRejection(move=bestmove, code=validation.issue.code, reason=validation.issue.message))
                            else:
                                accepted.insert(0, (0, bestmove, {"score": parsed.get("score"), "depth": parsed.get("depth"), "pv": [bestmove]}))
                        if not accepted:
                            summary = CandidateFilterSummary(requested=requested, returned=0, rejected=rejected)
                            reason = rejected[0].reason if rejected else "引擎没有返回可用候选着法"
                            raise EngineRuleViolation(f"引擎候选着法均不可用：不合法着法 {reason}", summary)

                        accepted.sort(key=lambda item: item[0])
                        if bestmove not in {item[1] for item in accepted}:
                            bestmove = accepted[0][1]
                        else:
                            accepted.sort(key=lambda item: (0 if item[1] == bestmove else 1, item[0]))
                        lines = [EngineLine(
                            rank=index,
                            move=candidate,
                            label=describe_uci(current_position, candidate),
                            score=line.get("score"),
                            depth=line.get("depth"),
                            pv=line.get("pv", [candidate]),
                        ) for index, (_, candidate, line) in enumerate(accepted, start=1)]
                        best_line = next((line for _, candidate, line in accepted if candidate == bestmove), accepted[0][2])
                        filter_summary = CandidateFilterSummary(requested=requested, returned=len(lines), rejected=rejected)
                        result = EngineResponse(
                            bestmove=bestmove,
                            score=best_line.get("score", parsed.get("score")),
                            depth=best_line.get("depth", parsed.get("depth")),
                            nodes=parsed.get("nodes"),
                            nps=parsed.get("nps"),
                            pv=best_line.get("pv", parsed.get("pv", [])),
                            raw_info=raw_info[-30:],
                            lines=lines,
                            filter_summary=filter_summary,
                        )
                        logger.info("engine.search.completed", extra=_log_fields(
                            event="engine.search.completed", pid=pid, outcome="success",
                            duration_ms=round((time.monotonic() - started_at) * 1000), **search_params,
                        ))
                        return result
            except TimeoutError as exc:
                try:
                    await self._send("stop")
                    await asyncio.wait_for(self._wait_for("bestmove"), 2)
                except Exception:
                    await self.stop()
                raise EngineUnavailable("Pikafish 搜索超时，已停止本次分析") from exc

    @staticmethod
    def _parse_info(line: str, parsed: dict[str, Any]) -> None:
        depth = re.search(r"\bdepth (\d+)", line)
        nodes = re.search(r"\bnodes (\d+)", line)
        nps = re.search(r"\bnps (\d+)", line)
        score = re.search(r"\bscore (cp|mate) (-?\d+)", line)
        pv = re.search(r"\bpv (.+)$", line)
        multipv = re.search(r"\bmultipv (\d+)", line)
        rank = int(multipv.group(1)) if multipv else 1
        current_depth = int(depth.group(1)) if depth else parsed.get("depth", 0)
        if depth:
            parsed["depth"] = int(depth.group(1))
        if nodes:
            parsed["nodes"] = int(nodes.group(1))
        if nps:
            parsed["nps"] = int(nps.group(1))
        entry = parsed.setdefault("lines_by_depth", {}).setdefault(current_depth, {}).setdefault(rank, {})
        if score:
            entry["score"] = Score(type=score.group(1), value=int(score.group(2)))
            if rank == 1:
                parsed["score"] = entry["score"]
        if pv:
            entry["pv"] = pv.group(1).split()
            if rank == 1:
                parsed["pv"] = entry["pv"]
        if depth:
            entry["depth"] = int(depth.group(1))

    @staticmethod
    def _final_lines(by_depth: dict[int, dict[int, dict]], multipv: int) -> dict[int, dict]:
        """Return the deepest complete MultiPV set, or the deepest available partial set."""
        for depth in sorted(by_depth, reverse=True):
            rows = by_depth[depth]
            if all(rank in rows and rows[rank].get("pv") for rank in range(1, multipv + 1)):
                return rows
        for depth in sorted(by_depth, reverse=True):
            rows = by_depth[depth]
            if rows:
                return rows
        return {}

