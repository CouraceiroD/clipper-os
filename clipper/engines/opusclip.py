"""Pipeline B — OpusClip via MCP oficial (https://mcp.opus.pro/mcp), conduzido pelo Claude Code.

O Python orquestra e guarda o estado; o `claude -p` chama as tools do MCP `opusclip`
(com o login OAuth que fizeste no Claude Code). Nenhuma chave passa por este projeto.

Fases (retomáveis — o estado fica em outputs/<vod>/opusclip/state.json):
  1. submit   -> cria UM projeto no OpusClip (consome créditos). Nunca repete se já existir project_id.
  2. wait     -> consulta o estado até terminar (leituras não consomem créditos).
  3. fetch    -> lista clips + virality score, exporta os N melhores, devolve links de download.
  4. download -> descarrega os MP4 para outputs/<vod>/opusclip/clip-NN.mp4
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from .. import claude_cli

ALLOWED = ["mcp__opusclip"]
DISALLOWED = ["Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Task"]

SYSTEM = """Estás a operar a conta OpusClip do utilizador através das tools do MCP `opusclip`.
Regras de segurança e custo (obrigatórias):
- NUNCA publiques, agendes ou partilhes nada em redes sociais (nenhuma tool de schedule/publish/post).
- Só podes criar um projeto quando o pedido o disser explicitamente, e no máximo UM.
- Nunca apagues projetos nem clips.
- Se uma tool não existir ou falhar, não inventes valores: usa null e explica em `notes`.
- Responde apenas com o JSON pedido."""

NUM_OR_NULL = {"type": ["number", "null"]}
STR_OR_NULL = {"type": ["string", "null"]}

SUBMIT_SCHEMA = {
    "type": "object",
    "properties": {
        "project_id": STR_OR_NULL,
        "credits_before": NUM_OR_NULL,
        "credits_unit": STR_OR_NULL,
        "plan": STR_OR_NULL,
        "options_applied": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["project_id", "credits_before", "credits_unit", "plan", "options_applied", "notes"],
    "additionalProperties": False,
}

STATUS_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["queued", "processing", "done", "failed", "unknown"]},
        "progress_percent": NUM_OR_NULL,
        "notes": {"type": "string"},
    },
    "required": ["status", "progress_percent", "notes"],
    "additionalProperties": False,
}

CLIP_SCHEMA = {
    "type": "object",
    "properties": {
        "rank": {"type": "integer"},
        "clip_id": {"type": "string"},
        "title": {"type": "string"},
        "start_time": NUM_OR_NULL,
        "end_time": NUM_OR_NULL,
        "duration": NUM_OR_NULL,
        "virality_score": NUM_OR_NULL,
        "hook_score": NUM_OR_NULL,
        "coherence_score": NUM_OR_NULL,
        "connection_score": NUM_OR_NULL,
        "trend_score": NUM_OR_NULL,
        "reason_selected": {"type": "string"},
        "hook": STR_OR_NULL,
        "transcript": STR_OR_NULL,
        "description": STR_OR_NULL,
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "exported": {"type": "boolean"},
        "download_url": STR_OR_NULL,
        "preview_url": STR_OR_NULL,
    },
    "required": ["rank", "clip_id", "title", "start_time", "end_time", "duration", "virality_score",
                 "hook_score", "coherence_score", "connection_score", "trend_score", "reason_selected",
                 "hook", "transcript", "description", "hashtags", "exported", "download_url", "preview_url"],
    "additionalProperties": False,
}

FETCH_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {"type": "array", "items": CLIP_SCHEMA},
        "total_clips_in_project": {"type": "integer"},
        "credits_after": NUM_OR_NULL,
        "credits_unit": STR_OR_NULL,
        "notes": {"type": "string"},
    },
    "required": ["clips", "total_clips_in_project", "credits_after", "credits_unit", "notes"],
    "additionalProperties": False,
}

TOOLS_SCHEMA = {
    "type": "object",
    "properties": {
        "connected": {"type": "boolean"},
        "tools": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "description": {"type": "string"},
                           "consumes_credits": {"type": "boolean"}, "parameters": {"type": "string"}},
            "required": ["name", "description", "consumes_credits", "parameters"],
            "additionalProperties": False}},
        "credits_remaining": NUM_OR_NULL,
        "credits_unit": STR_OR_NULL,
        "notes": {"type": "string"},
    },
    "required": ["connected", "tools", "credits_remaining", "credits_unit", "notes"],
    "additionalProperties": False,
}


class OpusClipEngine:
    def __init__(self, cfg: dict, tracker, out_dir: Path):
        self.cfg = cfg
        self.o = cfg["opusclip"]
        self.c = cfg["clipping"]
        self.tracker = tracker
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = out_dir / "state.json"
        self.state = json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists() else {}

    # ------------------------------------------------------------ helpers
    def _save(self):
        self.state_path.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")

    def _claude(self, purpose: str, prompt: str, schema: dict, timeout: int = 900) -> dict:
        model = self.o["operator_model"]
        out, info = claude_cli.run(prompt, schema, model=model, system=SYSTEM,
                                   allowed_tools=ALLOWED, disallowed_tools=DISALLOWED, timeout=timeout)
        self.tracker.claude(f"opusclip.{purpose}", model, info["input_tokens"], info["output_tokens"],
                            info["cache_read"], info["cost_usd"], backend="claude_code")
        self.tracker.call("opusclip_mcp_session")
        return out

    # ------------------------------------------------------------ fases
    def submit(self, meta: dict) -> None:
        if self.state.get("project_id"):
            print(f"[opusclip] projeto já existe ({self.state['project_id']}) — não volto a submeter.")
            return
        url = meta.get("url", "")
        if not url.startswith("http"):
            raise RuntimeError("OpusClip precisa de um URL público (YouTube/Twitch...), não de um ficheiro local.")
        a = self.cfg["analyze"]
        prompt = f"""Tarefa: criar UM projeto de clipping no OpusClip para este vídeo e devolver o id.

1. Primeiro consulta os créditos/uso restantes da conta (tool de usage/créditos, se existir) -> credits_before.
2. Submete o projeto com este URL: {url}
   Opções desejadas (aplica as que as tools suportarem e diz quais aplicaste em options_applied):
   - formato vertical 9:16 com reframing automático (AI reframe)
   - legendas automáticas ativadas
   - duração dos clips entre {a['min_duration']} e {a['max_duration']} segundos
   - idioma do vídeo: {self.cfg['transcribe']['language'] or 'auto'}
   - se houver opção de processar só parte do vídeo, processa o vídeo inteiro
3. Não esperes que termine. Devolve o project_id logo após a submissão.
"""
        with self.tracker.stage("opusclip.submit"):
            res = self._claude("submit", prompt, SUBMIT_SCHEMA)
        if not res.get("project_id"):
            raise RuntimeError(f"OpusClip não devolveu project_id: {res.get('notes')}")
        self.state.update(project_id=res["project_id"], submitted_at=time.time(), submit=res)
        self.tracker.opusclip.update(project_id=res["project_id"], credits_before=res["credits_before"],
                                     credits_unit=res["credits_unit"], plan=res["plan"],
                                     options_applied=res["options_applied"])
        self._save()
        print(f"[opusclip] projeto {res['project_id']} submetido. Créditos antes: "
              f"{res['credits_before']} {res['credits_unit'] or ''}")

    def wait(self) -> None:
        if self.state.get("status") == "done":
            return
        pid = self.state["project_id"]
        deadline = time.time() + self.o["max_wait_minutes"] * 60
        with self.tracker.stage("opusclip.wait"):
            while True:
                res = self._claude("status", f"""Consulta o estado de processamento do projeto OpusClip `{pid}`
(só leitura; não cries nem alteres nada). Devolve status e progresso.""", STATUS_SCHEMA, timeout=300)
                print(f"[opusclip] estado={res['status']} progresso={res['progress_percent']}  {res['notes'][:120]}")
                if res["status"] == "done":
                    break
                if res["status"] == "failed":
                    raise RuntimeError(f"Projeto OpusClip falhou: {res['notes']}")
                if time.time() > deadline:
                    raise TimeoutError(f"OpusClip não terminou em {self.o['max_wait_minutes']} min. "
                                       "Volta a correr o mesmo comando mais tarde: retoma sem custos extra.")
                time.sleep(self.o["poll_seconds"])
        self.state.update(status="done", done_at=time.time())
        self.tracker.opusclip["processing_seconds"] = round(self.state["done_at"] - self.state["submitted_at"], 1)
        self._save()

    def fetch(self) -> dict:
        if self.state.get("fetch"):
            return self.state["fetch"]
        pid = self.state["project_id"]
        n_cand, n_exp = self.c["max_candidates"], self.c["max_renders"]
        prompt = f"""Projeto OpusClip `{pid}` (já processado).
1. Lista os clips do projeto com virality score e sub-scores (hook, coherence, connection, trend) quando existirem.
   Usa describe/detalhes do clip se for preciso para obter início/fim no vídeo original (segundos), título,
   hook, transcrição e porque foi selecionado.
2. Escolhe os {n_cand} clips com maior virality score (rank 1 = melhor) e devolve-os todos.
3. Exporta APENAS os {n_exp} primeiros (HD/1080p, 9:16, com as legendas e reframe do OpusClip) e devolve
   o link de download direto em download_url (exported=true). Se a exportação for assíncrona, consulta o estado
   até teres o link. Os restantes ficam com exported=false e download_url=null.
4. Consulta os créditos restantes no fim -> credits_after.
Não submetas novos projetos. Não publiques nem agendes nada.
"""
        with self.tracker.stage("opusclip.fetch"):
            res = self._claude("fetch", prompt, FETCH_SCHEMA, timeout=1800)
        res["clips"] = sorted(res["clips"], key=lambda c: c["rank"])[:n_cand]
        self.state["fetch"] = res
        self._save()
        return res

    def download(self, res: dict) -> list[dict]:
        before = self.tracker.opusclip.get("credits_before") or self.state.get("submit", {}).get("credits_before")
        after = res.get("credits_after")
        used = round(before - after, 2) if isinstance(before, (int, float)) and isinstance(after, (int, float)) else None
        self.tracker.opusclip.update(credits_after=after, credits_used=used,
                                     credits_unit=res.get("credits_unit") or self.tracker.opusclip.get("credits_unit"),
                                     total_clips_in_project=res.get("total_clips_in_project"), notes=res.get("notes"))
        n = max(len(res["clips"]), 1)
        claude_cost = self.tracker.claude_cost("opusclip.")
        proc = self.tracker.opusclip.get("processing_seconds") or (
            round(self.state["done_at"] - self.state["submitted_at"], 1) if self.state.get("done_at") else None)
        results = []
        for i, c in enumerate(res["clips"], 1):
            scores = [c[k] for k in ("hook_score", "coherence_score", "connection_score", "trend_score")
                      if isinstance(c[k], (int, float))]
            item = {
                "provider": "opusclip",
                "rank": i,
                "clip_id": c["clip_id"],
                "start_time": c["start_time"],
                "end_time": c["end_time"],
                "duration": c["duration"] or ((c["end_time"] - c["start_time"])
                                              if c["start_time"] is not None and c["end_time"] is not None else None),
                "title": c["title"],
                "hook": c["hook"],
                "reason_selected": c["reason_selected"],
                # sub-scores do OpusClip em 0-10 são convertidos para 0-100 (mesma escala do own)
                "engagement_score": (round(sum(scores) / len(scores) * (10 if max(scores) <= 10 else 1), 1)
                                     if scores else None),
                "virality_score": c["virality_score"],
                "sub_scores": {k: c[k] for k in ("hook_score", "coherence_score", "connection_score", "trend_score")},
                "transcript": c["transcript"],
                "description": c["description"],
                "hashtags": c["hashtags"],
                "preview_url": c["preview_url"],
                "editing": "OpusClip: " + (self.tracker.opusclip.get("options_applied") or "reframe/legendas por defeito"),
                "rendered": False,
                "file": None,
                "final_duration": None,
                # OpusClip renderiza tudo no servidor: tempo total de processamento repartido pelos clips
                "render_time": round(proc / n, 1) if proc else None,
                "estimated_cost_usd": round(claude_cost / n, 4),
                "estimated_credits": round(used / n, 2) if used is not None else None,
            }
            if c["exported"] and c["download_url"]:
                dest = self.out_dir / f"clip-{i:02d}.mp4"
                if not dest.exists():
                    with self.tracker.stage("opusclip.download"):
                        _download(c["download_url"], dest)
                    self.tracker.call("opusclip_cdn_download")
                item.update(rendered=True, file=str(dest))
            (self.out_dir / f"clip-{i:02d}.json").write_text(json.dumps(item, indent=2, ensure_ascii=False),
                                                              encoding="utf-8")
            results.append(item)
        return results

    def list_tools(self) -> dict:
        return self._claude("tools", """Lista todas as tools disponíveis no MCP `opusclip` (nome exato, descrição,
parâmetros resumidos e se consomem créditos). Consulta também os créditos restantes se houver tool para isso.
Não executes nenhuma tool que consuma créditos.""", TOOLS_SCHEMA, timeout=300)


def _download(url: str, dest: Path, tries: int = 4) -> None:
    tmp = dest.with_suffix(".part")
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "clipper-os/0.2"})
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            tmp.rename(dest)
            print(f"[opusclip] descarregado {dest.name}")
            return
        except Exception as e:  # noqa: BLE001
            if k == tries - 1:
                raise RuntimeError(f"Falha a descarregar {url}: {e}") from e
            time.sleep(2 ** (k + 1))
